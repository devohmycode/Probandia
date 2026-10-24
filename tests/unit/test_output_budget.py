"""The size of what each command prints for an agent (optimize 2.11).

Every command runs on a copy of the sample project, in the contract that
agents read, and its output must stay under its ceiling in bytes: about 10 %
above its size when the ceiling was set. Raising a ceiling is justified in the
commit. No line is decorative: a line that holds only punctuation fails.
Set PROBANDIA_PRINT_SIZES=1 to print the sizes measured.
"""
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, i18n
from probandia.util import yamlio
from tests import REUSE, ROOT

RESEARCH = "2026-09-01-ancestors-of-louis-marchand"
SOURCE = "src-01JA0000000000000000000001"
GEDCOM = os.path.join(ROOT, "tests", "fixtures", "gedcom", "tree-7.ged")

# name: (argv, ceiling in bytes)
COMMANDS = {
    "status": (["status"], 260),
    "status-research": (["status", RESEARCH], 270),
    "doctor": (["doctor", "--harness", "codex"], 1070),   # + PYTHON_PATH and LIBRARY_ISSUES (3 October 2026)
    # token-economy F4: verify, known, plan, archive find, places guide, propose and apply at about 10 % above
    # their size on 10 Oct. 2026, so that none grows back unseen
    "verify": (["verify", RESEARCH], 105),   # F2: only the rule that fails, V-8; measured 94 (was 370)
    "known": (["known", RESEARCH], 545),   # token-economy F1: counts here, the facts in DETAILS; measured 493
    "known-filtered": (["known", RESEARCH, "--names", "Perrin"], 500),
    "plan": (["plan", RESEARCH], 820),   # token-economy C6: no-key removals in DETAILS only, measured 748 (was 1320)
    "digest": (["digest", RESEARCH], 780),
    "quota-show": (["quota", "show"], 2950),
    "usage": (["usage"], 1840),
    "usage-provider": (["usage", "serper"], 330),
    "config-show": (["config", "show"], 240),
    "config-explain": (["config", "explain", "report.mode"], 280),
    "config-path": (["config", "path"], 490),
    "config-diff": (["config", "diff"], 30),
    "dates": (["dates", "3 nivôse an XII"], 100),
    "variants": (["variants", "Hugo"], 140),
    "places": (["places", "Bourg-Vert", "--offline"], 150),
    "cite": (["cite", "--form", "--repository", "AD Doubs", "--reference", "3 E 41"], 50),
    "library": (["library", "list"], 30),
    "team-budget": (["team", "budget", RESEARCH], 80),
    "team-inbox": (["team", "inbox", RESEARCH], 40),
    "render": (["render", RESEARCH], 660),
    "tree": (["tree"], 280),
    "export": (["export", "gedcom7"], 150),
    "import-gedcom": (["import-gedcom", GEDCOM], 380),
    "keys": (["keys"], 1250),
    "keys-where": (["keys", "where"], 230),
    "providers": (["providers"], 2200),
    "providers-show": (["providers", "show", "serper"], 320),
    "archive-list": (["archive", "list"], 1520),   # 6.19: seven archives added; FL3: persee, hathitrust, geneanet; A8: ad50 third-party=forbidden
    "archive-coverage": (["archive", "coverage", "Morbihan", "--from", "1850", "--to", "1900"], 1010),   # 6.19: two French sources; FL3: persee, hathitrust, geneanet
    "archive-find": (["archive", "find", "births in Morbihan 1850"], 605),   # F3: three operations; measured 549
    "help": (["help", "exit-codes"], 480),
    "lock-status": (["lock", "status", f"research:{RESEARCH}"], 90),
    "transcribe-template": (["transcribe", "template", SOURCE], 190),   # TRUST1-T2: propose it to the source
    "manifests-check": (["manifests", "check"], 20),
    "completion": (["completion", "bash"], 290),
    # token-economy B1: known and plan come with new (measured 876 bytes; the two calls printed 2,780); T67: the
    # plan's names=, places=, record_types= and native searches, no PLACES= nor reminder: measured 954 (852 before)
    "new": (["new", "Who were the parents of Henri Marchand?", "--mode", "session"], 960),
    # token-economy F4: the guide of a place of the Manche, one index fact proposed, then applied (PROPOSAL);
    # T67: after the plan, as in a pass, only the repositories of its window, and no "shown only" once applied:
    # measured 1782 (2029 before), ceiling 2300 before
    "places-guide": (["places", "guide", "Cherbourg (Manche)", "--offline"], 1960),
    "propose": (["propose", "{project}/proposal.yaml"], 430),   # measured 391
    "propose-draft": (["propose", "--draft", RESEARCH], 290),   # T76: DRAFT=, the counts, SUBJECT=; measured 265
    "apply": (["apply", "01JA0000000000000000000P01"], 75),   # measured 65
    # T66: four results of a recorded Tavily answer (tests/fixtures/http/tavily/search-ok.json), each with
    # its excerpt of 160 characters at most, which may spare a read: measured 1205 (626 without the excerpts)
    "search": (["search", "Hugo Besançon 1802", "--engine", "tavily"], 1330),
}


def _search_client(ctx):
    """search's HTTP client, its answers recorded: no provider is called."""
    from probandia.util.http import Client

    def transport(method, url, headers, body, timeout):
        if url.startswith("https://api.tavily.com/search"):
            with open(os.path.join(ROOT, "tests", "fixtures", "http", "tavily", "search-ok.json"),
                      encoding="utf-8") as fh:
                return 200, {}, json.dumps(json.load(fh)["body"]).encode(), url
        return (200, {}, b"", url) if url.endswith("/robots.txt") else (404, {}, b"", url)
    return Client(os.path.join(ctx.project, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)
PROPOSAL = {"schema": 1, "id": "01JA0000000000000000000P01", "research": RESEARCH, "pass": 3,
            "author": {"harness": "claude-code", "agent": "session"},
            "facts": [{"id": "pierre-marchand-1841.burial", "type": "burial", "status": "index",
                       "date": {"value": "1868", "qualifier": "exact"},
                       "place": {"id": "bourg-vert", "as_written": "Bourg-Vert"},
                       "source": "src-01JA0000000000000000000004"}]}
DECORATIVE = re.compile(r"^- [\W_]*$")


class OutputBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sizes, cls.outputs, cls.projects = {}, {}, {}
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        i18n.activate("en")
        env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "u"), "PROBANDIA_DATA_DIR": os.path.join(tmp.name, "d"),
               "TAVILY_API_KEY": "k", "SERPER_API_KEY": "k"}
        for name, (argv, _ceiling) in COMMANDS.items():
            project = os.path.join(tmp.name, name)
            shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), project)
            if name in ("propose", "apply"):   # F4: the proposal, proposed already before apply
                yamlio.dump(os.path.join(project, "proposal.yaml"), PROPOSAL)
                if name == "apply":
                    cli.main(["propose", os.path.join(project, "proposal.yaml")], stdout=io.StringIO(),
                             environ=dict(env), cwd=project, stdin=io.StringIO())
            if name == "places-guide":   # T67: in a pass, new has made the plan whose window the guide lists
                with mock.patch("probandia.cli.search_cmd.auto_sync", return_value=None):
                    cli.main(["plan", RESEARCH], stdout=io.StringIO(), environ=dict(env), cwd=project,
                             stdin=io.StringIO())
            out = io.StringIO()
            # the balances new reads once a day (T52) are tested in test_lifecycle; the network is blocked here
            with mock.patch("probandia.doctor.optional_tools", return_value={}), \
                    mock.patch("probandia.doctor.catalogue_ages", return_value=[("serpapi", 12)]), \
                    mock.patch("probandia.cli.search_cmd.auto_sync", return_value=None), \
                    mock.patch("probandia.cli.search_cmd._client", _search_client):
                run_env = dict(env, **REUSE) if name == "search" else dict(env)   # T217: Tavily
                cli.main([a.replace("{project}", project) for a in argv], stdout=out, environ=run_env, cwd=project,
                         stdin=io.StringIO())
            text = out.getvalue()
            cls.outputs[name] = text
            cls.projects[name] = project
            cls.sizes[name] = len(text.encode("utf-8"))
        if os.environ.get("PROBANDIA_PRINT_SIZES"):
            print(json.dumps(cls.sizes, indent=1))

    def test_every_command_under_its_ceiling(self):
        for name, (argv, ceiling) in COMMANDS.items():
            with self.subTest(name):
                self.assertLessEqual(self.sizes[name], ceiling, f"{name}: {self.outputs[name]}")

    def test_every_command_ran(self):
        for name, text in self.outputs.items():
            with self.subTest(name):
                self.assertNotIn("STATUS=FAIL\nREASON=internal", text)
                self.assertTrue(text.startswith("STATUS=") or name == "completion", text[:200])

    def test_the_budgets_measure_real_work(self):   # token-economy F4: a refusal under its budget proves nothing
        self.assertTrue(self.outputs["propose"].startswith("STATUS=OK\n"), self.outputs["propose"])
        self.assertIn("- verdict=would-apply", self.outputs["propose"])
        self.assertEqual(self.outputs["apply"], "STATUS=OK\nPROPOSAL=01JA0000000000000000000P01\nEVENTS=1\nPERSONS=1\n")
        self.assertIn("\n- first=ad50 ", self.outputs["places-guide"])
        self.assertIn("\nOPERATIONS=3\n", self.outputs["archive-find"])

    def test_search_gives_an_excerpt_per_result(self):   # T66
        rows = [line for line in self.outputs["search"].splitlines() if line.startswith("- result=")]
        self.assertEqual(len(rows), 4, self.outputs["search"])
        self.assertTrue(rows[0].startswith("- result=https://genealogy.example.org/people/Victor-Hugo/"
                                           "6000000012345678901 [tavily] Victor Hugo (1802-1885) - Genealogy - "
                                           "Example Genealogy — Victor Hugo was born on 26 February 1802 in "
                                           "Besançon"), rows[0])
        for row in rows:
            self.assertLessEqual(len(row.split(" — ", 1)[1]), 160, row)

    def test_an_excerpt_is_cut_on_a_word_and_never_repeats_the_title(self):
        from probandia.cli.search_exec import EXCERPT_CHARS, _excerpt

        long = "Baptême de Victor Hugo à Besançon, paroisse Saint-Jean, " * 8
        cut = _excerpt({"title": "Registre", "snippet": long})
        self.assertTrue(cut.startswith(" — Baptême de Victor Hugo") and cut.endswith("…"), cut)
        self.assertLessEqual(len(cut) - len(" — "), EXCERPT_CHARS)
        self.assertNotIn("  ", cut)
        self.assertEqual(_excerpt({"title": "Hugo à Nancy", "snippet": " Hugo à\nNancy "}), "")
        self.assertEqual(_excerpt({"title": "Hugo", "snippet": None}), "")
        self.assertEqual(_excerpt({"title": "Hugo", "snippet": "Né à Besançon.\n1802"}), " — Né à Besançon. 1802")

    def test_plan_lists_no_keyless_call(self):   # token-economy C6
        out = self.outputs["plan"]
        self.assertNotIn("unusable", out)   # counted in REMOVED=, listed in DETAILS= only
        self.assertIn("\nLOGIN_NEEDED=none\n", out)   # no sign-in the plan does not call for
        # 25 lines measured, 18 of them keys the skills read: under 20 needs fewer keys
        self.assertLessEqual(len(out.splitlines()), 25, out)

    def test_new_holds_known_and_plan(self):
        for key in ("KNOWN_FACTS", "KNOWN_NEGATIVES_DUE", "TYPE", "WINDOW", "FOCUS", "LOGIN_NEEDED", "NATIVE_PARALLEL",
                    "NATIVE_LEFT"):
            self.assertRegex(self.outputs["new"], rf"\n{key}=", key)
        self.assertNotIn("\nMCP=", self.outputs["new"])   # T65: no MCP server to choose
        # T67: the plan's names, places and record types, which sent the agent to work/new-<n>.txt, under 960 bytes
        for line in ("- names=PERRIN, PERRYN, PERIN, PERRINE, PERRINS", "- places=Les Ormes, Bourg-Vert, Bourgvert",
                     "- record_types=birth, baptism, marriage"):
            self.assertIn("\n" + line + "\n", self.outputs["new"])
        self.assertLessEqual(self.sizes["new"], 960)

    def test_places_guide_lists_the_window_and_stores_the_whole_guide(self):
        # T67: the repositories of other years are not listed, but places.yaml keeps them all
        out = self.outputs["places-guide"]
        self.assertIn("\nREPOSITORIES=8\nWINDOW=1813-1823\nOUTSIDE_WINDOW=2\n", out)
        for archive in ("arolsen", "matchid"):   # the Second World War, the deaths since 1970
            self.assertNotIn(f" {archive} ", out)
        self.assertNotIn("before 1793", out)   # where to look first, for this window only
        self.assertNotIn("shown only", out)    # the guide was applied
        places = yamlio.load(os.path.join(self.projects["places-guide"], "families", "marchand", "index",
                                          "places.yaml"))["places"]
        stored = {p["id"]: p for p in places}["cherbourg"]
        self.assertEqual(len(stored["repositories"]), 10)
        self.assertIn("before 1793", stored["repositories"][0]["note"])

    def test_no_decorative_line(self):
        for name, text in self.outputs.items():
            for line in text.splitlines():
                self.assertIsNone(DECORATIVE.match(line), f"{name}: {line!r}")

    def test_paths_inside_the_project_are_relative(self):
        for name, text in self.outputs.items():
            root = os.path.abspath(self.projects[name]).replace("\\", "/")
            self.assertNotIn(root.lower() + "/", text.replace("\\", "/").lower(), name)

    def test_the_passages_of_read_are_set(self):
        from probandia.cli import reading_cmd
        from probandia.reading.ladder import ReadResult

        text = "\n\n".join(f"Louis Marchand paragraph {n} " + "x" * 300 for n in range(20))

        class Reader:
            def read(self, url, fresh=False, max_step=None):
                r = ReadResult(url)
                r.status, r.step = "ok", "http"
                r.text = text
                return r

        project = self.projects["status"]
        for env, expected in (({}, 12), ({"PROBANDIA_READING_MAX_PASSAGES": "2"}, 2)):
            out = io.StringIO()
            with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work: Reader()):
                cli.main(["read", "https://example.org/x", "--question", "Louis Marchand"], stdout=out,
                         environ=dict(env, PROBANDIA_CONFIG_DIR=os.path.join(project, "u")), cwd=project)
            self.assertIn(f"PASSAGES={expected}\n", out.getvalue())
            self.assertIn(f"\nCHARS={len(text)}\n", out.getvalue())   # token-economy I2: the size of the page


class ReadOnlyProject(unittest.TestCase):
    """T129: Codex runs the contradictor in a read-only sandbox; what it runs must still answer."""

    def test_known_and_proof_show_without_writing(self):
        import builtins
        import tempfile as tmpmod

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = os.path.join(tmp.name, "p")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project-gps"), project)
        root = os.path.normcase(os.path.realpath(project))

        def inside(path):
            try:
                return os.path.normcase(os.path.realpath(os.fspath(path))).startswith(root)
            except TypeError:   # a file descriptor
                return False

        def refuse(real, writes=lambda *a, **k: True):
            def fake(path, *args, **kwargs):
                if inside(path) and writes(*args, **kwargs):
                    raise PermissionError(13, "read-only file system", path)
                return real(path, *args, **kwargs)
            return fake

        def writing(mode="r", *a, **k):
            return any(c in mode for c in "wax+")

        real_mkstemp = tmpmod.mkstemp

        def mkstemp(*args, dir=None, **kwargs):
            if dir and inside(dir):
                raise PermissionError(13, "read-only file system", dir)
            return real_mkstemp(*args, dir=dir, **kwargs)

        research = "2026-09-04-birth-of-henri-marchand"
        env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "u"), "PROBANDIA_DATA_DIR": os.path.join(tmp.name, "d")}
        before = sorted(os.path.join(d, f) for d, _s, fs in os.walk(project) for f in fs)
        for argv in (["known", research], ["proof", "show", f"pf-q1-{research}", "--research", research]):
            out = io.StringIO()
            with mock.patch.object(builtins, "open", refuse(builtins.open, writing)), \
                    mock.patch.object(os, "makedirs", refuse(os.makedirs)), \
                    mock.patch.object(os, "mkdir", refuse(os.mkdir)), \
                    mock.patch.object(os, "replace", refuse(os.replace)), \
                    mock.patch.object(tmpmod, "mkstemp", mkstemp):
                code = cli.main(argv + ["--agent", "contradictor"], stdout=out, environ=dict(env), cwd=project,
                                stdin=io.StringIO())
            text = out.getvalue()
            self.assertEqual(code, 0, text)
            self.assertTrue(text.startswith("STATUS=OK\n"), text)
            self.assertNotIn("DETAILS=", text)
            if argv[0] == "known":
                self.assertIn("- the details could not be written", text)
        self.assertEqual(sorted(os.path.join(d, f) for d, _s, fs in os.walk(project) for f in fs), before)

    def test_the_contradictor_of_codex_stays_read_only(self):
        from probandia.install import convert

        fm, body = convert.agents()["contradictor"]
        self.assertIn('sandbox_mode = "read-only"', convert.codex_agent("contradictor", fm, body))


if __name__ == "__main__":
    unittest.main()
