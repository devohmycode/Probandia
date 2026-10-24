"""The readable layouts of the existing commands (CLI5): reference renderings,
without colour, at a fixed time, on a copy of the sample project."""
import datetime
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

import types

from probandia import __version__, cli, doctor, i18n
from probandia.cli import export_cmd, search_cmd, views
from probandia.lang import detect
from probandia.ledger import Ledger
from probandia.providers import catalogue
from tests import REUSE, ROOT
from tests.unit.test_human import golden
from tests.unit.test_usage import KEYS

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ViewCase(unittest.TestCase):
    """A copy of the sample project, a fixed clock, a terminal 100 columns wide."""

    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = dict(KEYS, PROBANDIA_CONFIG_DIR=os.path.join(self.tmp.name, "u"), NO_COLOR="1",
                        PROBANDIA_PAGER="none", CLAUDE_CONFIG_DIR=os.path.join(self.tmp.name, "claude"))
        # the report language must not come from this machine: its Claude Code
        # settings (above) nor its system language (Windows reads it outside environ)
        for patcher in (mock.patch.object(views, "_now", return_value=NOW),
                        mock.patch.object(detect, "os_language", return_value=None),
                        mock.patch.object(search_cmd, "_ledger", lambda ctx: Ledger(
                            ctx.project, catalogue.load(), clock=lambda: NOW, environ=ctx.environ))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, *argv, terminal=True, cwd=None, env=None):
        out = Terminal() if terminal else io.StringIO()
        code = cli.main(list(argv) + (["--width", "100"] if terminal else []), stdout=out,
                        environ=dict(self.env, **(env or {})), cwd=cwd or self.dir, stdin=io.StringIO())
        return code, out.getvalue()


class Status(ViewCase):
    """status (cli.md 5.6.1)."""

    def test_readable(self):
        code, out = self.call("status")
        self.assertEqual(code, 0, out)
        golden(self, "status", out)
        self.assertIn("Lowest accounts", out)

    def test_open_pass_and_lock(self):
        res = "2026-09-01-ancestors-of-louis-marchand"
        agent = {"CLAUDECODE": "1"}
        self.assertEqual(self.call("resume", res, terminal=False, env=agent)[0], 0)
        self.assertEqual(self.call("lock", "take", "family:marchand", terminal=False, env=agent)[0], 0)
        code, out = self.call("status")
        self.assertIn("pass 3 open", out)
        self.assertIn("Open passes", out)
        self.assertIn("2 locks held", out)   # resume holds the research
        self.assertIn("family-marchand", out)

    def test_contract_unchanged(self):
        code, out = self.call("status", terminal=False)
        self.assertTrue(out.startswith("STATUS=OK\nFAMILIES=1\nRESEARCHES=1\n"), out)
        self.assertIn("- family=marchand 1 researches\n", out)
        self.assertNotIn("Lowest accounts", out)


class Doctor(ViewCase):
    """doctor (cli.md 5.13.1): a mark per check, and how to install what is missing."""

    def render(self, system):
        tools = {"playwright": (True, "headless browser for pages that need one"),
                 "tesseract": (False, "OCR of printed records"),
                 "pillow": (False, "sheets of views, crops and turns of images")}
        with mock.patch.object(doctor, "optional_tools", return_value=tools),                 mock.patch.object(doctor, "catalogue_ages", return_value=[("serpapi", 12), ("jina", 40)]),                 mock.patch.object(doctor, "system_name", return_value=system),                 mock.patch.object(doctor, "_user_env", return_value="~/.config/probandia/.env"),                 mock.patch.object(doctor, "sys", types.SimpleNamespace(version_info=(3, 12, 4))):
            return self.call("doctor", "--harness", "codex", "--output-format", "human", cwd=self.tmp.name)

    def test_windows(self):
        code, out = self.render("windows")
        self.assertEqual(code, 0, out)
        golden(self, "doctor-windows", out)
        self.assertIn("winget install UB-Mannheim.TesseractOCR", out)
        self.assertNotIn("apt install", out)

    def test_linux(self):
        code, out = self.render("linux")
        golden(self, "doctor-linux", out)
        self.assertIn("sudo apt install tesseract-ocr", out)
        self.assertIn('-m pip install "Pillow>=12,<13"', out)

    def test_keys_are_named_never_shown(self):
        code, out = self.call("doctor", "--harness", "codex", cwd=self.tmp.name,
                              env={"TAVILY_API_KEY": "tvly-secret-0123456789"})
        self.assertIn("TAVILY_API_KEY", out)
        self.assertNotIn("tvly-secret", out)

    def test_install_commands(self):
        self.assertEqual(doctor.install_commands("tesseract", "darwin"), ["brew install tesseract tesseract-lang"])
        import sys

        python = sys.executable if " " not in sys.executable else f'"{sys.executable}"'   # the engine's own
        self.assertEqual(doctor.install_commands("pillow", "windows"),
                         [f'{python} -m pip install "Pillow>=12,<13"',
                          f'uv pip install --python {python} "Pillow>=12,<13"'])
        self.assertEqual(doctor.install_commands("unknown"), [])


class Verify(ViewCase):
    """verify (cli.md 5.6.5): the rules in a table; a failed rule with what it concerns and what corrects it."""

    def test_failed_rule(self):
        code, out = self.call("verify", "2026-09")
        self.assertEqual(code, 1, out)
        golden(self, "verify", out)
        self.assertIn("✗ V-8", out)
        self.assertIn("concerned: trees missing", out)
        self.assertIn("to correct: regenerate the trees", out)
        self.assertNotIn("V-1=PASS", out)

    def test_every_rule_has_a_title_and_a_fix(self):
        from probandia import verify

        self.assertEqual(set(verify.TITLES), set(verify.RULES))
        self.assertEqual(set(verify.FIXES), set(verify.RULES))

    def test_contract_unchanged(self):
        code, out = self.call("verify", "2026-09", terminal=False)
        self.assertIn("- V-8=FAIL trees missing or older than branch.added in passes 1\n", out)


class Config(ViewCase):
    """config (cli.md 5.12.1 to 5.12.3): readable, and usable outside a project."""

    def outside(self):
        folder = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(folder, exist_ok=True)
        return folder

    def test_set_user_outside_a_project(self):
        code, out = self.call("config", "set", "--user", "language", "fr", terminal=False, cwd=self.outside())
        self.assertEqual(code, 0, out)
        self.assertIn("LAYER=user", out)
        code, out = self.call("config", "show", "--user", terminal=False, cwd=self.outside())
        self.assertEqual(code, 0, out)
        self.assertIn("- language=fr", out)
        code, out = self.call("config", "unset", "--user", "language", terminal=False, cwd=self.outside())
        self.assertEqual(code, 0, out)

    def test_project_files_still_need_a_project(self):
        code, out = self.call("config", "set", "report.mode", "living", terminal=False, cwd=self.outside())
        self.assertEqual(code, 6, out)

    def test_show(self):
        self.call("config", "set", "--user", "language", "fr", terminal=False)
        code, out = self.call("config", "show")
        self.assertEqual(code, 0, out)
        golden(self, "config-show", out)
        self.assertIn("language             fr         user", out)

    def test_explain(self):
        code, out = self.call("config", "explain", "report.mode")
        golden(self, "config-explain", out)
        self.assertIn("PROBANDIA_REPORT_MODE", out)

    def test_path(self):
        self.call("config", "set", "--user", "language", "fr", terminal=False)
        code, out = self.call("config", "path", env={"PROBANDIA_REPORT_MODE": "living"})
        self.assertEqual(code, 0, out)
        golden(self, "config-path", out.replace(self.tmp.name, "<tmp>").replace("\\", "/"))
        code, out = self.call("config", "path", terminal=False, cwd=self.outside())
        self.assertIn("- project=absent", out)
        self.assertIn("PROJECT=none", out)


RESEARCH = "2026-09-01-ancestors-of-louis-marchand"


def steady(text):
    """Without what changes from one run to the next: today's date, new ids."""
    text = re.sub(r"\d{4}-\d{2}-\d{2}\.(gdz|ged)", r"<today>.\1", text)
    return re.sub(r"\b[0-9A-HJKMNP-TV-Z]{26}\b", "<ulid>", text)


class UserCommands(ViewCase):
    """The other commands of the user (cli.md 5.7.3, 5.9.3, 5.9.5, 5.9.7, 5.9.8, 5.11.4, 5.14.1)."""

    def test_known(self):
        code, out = self.call("known", RESEARCH)
        self.assertEqual(code, 0, out)
        golden(self, "known", out)
        self.assertIn("Open hypotheses", out)

    def test_render(self):
        code, out = self.call("render", RESEARCH)
        self.assertEqual(code, 0, out)
        golden(self, "render", out)
        self.assertIn("file  families/marchand/research", out)

    def test_tree(self):
        code, out = self.call("tree")
        self.assertEqual(code, 0, out)
        golden(self, "tree", out)

    def test_export(self):
        code, out = self.call("export", "gedcom7")
        self.assertEqual(code, 0, out)
        golden(self, "export", steady(out))
        with mock.patch.object(export_cmd, "open_folder") as opened:
            self.call("export", "gedcom551", "--living", "exclude", "--open-folder")
        opened.assert_called_once_with(os.path.join(self.dir, "exports"))

    def test_export_counts_the_living(self):
        living = {"louis-marchand-1898", "henri-marchand-1870"}
        with mock.patch("probandia.gedcom.living_set", return_value=living):
            self.assertIn("2 presumed-living persons masked", self.call("export", "gedcom7")[1])
            out = self.call("export", "gedcom7", "--living", "exclude")[1]
        self.assertIn("2 presumed-living persons left out of the file", out)

    def test_import_gedcom(self):
        code, out = self.call("import-gedcom", os.path.join(ROOT, "tests", "fixtures", "gedcom", "tree-7.ged"))
        self.assertEqual(code, 0, out)
        golden(self, "import-gedcom", steady(out))
        self.assertIn("To review: 1 proposal", out)

    def test_library(self):
        os.makedirs(os.path.join(self.dir, "library"))
        shutil.copy(os.path.join(ROOT, "tests", "fixtures", "library", "valid", "manifest.yaml"),
                    os.path.join(self.dir, "library", "manifest.yaml"))
        code, out = self.call("library", "list")
        self.assertEqual(code, 0, out)
        golden(self, "library", out)
        self.assertIn("draft", out)

    def test_team(self):
        code, out = self.call("team", "budget", RESEARCH)
        self.assertEqual(code, 0, out)
        golden(self, "team", out)

    def test_plan(self):
        code, out = self.call("plan", RESEARCH)
        self.assertEqual(code, 0, out)
        golden(self, "plan", out)

    def test_contracts_unchanged(self):
        out = self.call("known", RESEARCH, terminal=False)[1]
        self.assertTrue(out.startswith("STATUS=OK\nFAMILY=marchand\nFACTS=63\n"), out)
        line = "fact=louis-marchand-1898.birth birth 1898 bourg-vert [record] "
        self.assertNotIn(line, out)   # F1: unfiltered, each fact is in the details file
        details = [x.split("=", 1)[1] for x in out.splitlines() if x.startswith("DETAILS=")][0]
        with open(os.path.join(self.dir, details), encoding="utf-8") as fh:
            self.assertIn(line, fh.read())
        self.assertIn("- " + line, self.call("known", RESEARCH, "--names", "Marchand", terminal=False)[1])
        out = self.call("export", "gedcom7", terminal=False)[1]
        self.assertNotIn("presumed", out)


class Tools(ViewCase):
    """The genealogist's tools (cli.md 5.10.1 to 5.10.7)."""

    def outside(self):
        folder = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(folder, exist_ok=True)
        return folder

    def test_dates(self):
        code, out = self.call("dates", "3 nivôse an XII", cwd=self.outside())
        self.assertEqual(code, 0, out)
        golden(self, "dates", out)
        self.assertIn("25 December 1803", out)
        out = self.call("dates", "--age", "34", "--on", "1885-03-02", cwd=self.outside())[1]
        self.assertIn("between 3 March 1850 and 2 March 1851", out)
        out = self.call("-l", "fr", "dates", "3 nivôse an XII", cwd=self.outside())[1]
        self.assertIn("25 décembre 1803", out)

    def test_variants(self):
        code, out = self.call("variants", "Hugo", "--given", "Victor", cwd=self.outside())
        self.assertEqual(code, 0, out)
        golden(self, "variants", out)

    def test_places(self):
        code, out = self.call("places", "Bourg-Vert")
        golden(self, "places", out)
        self.assertIn("Bourg-Vert", out)

    def test_cite_copy(self):
        copied = []

        def run(cmd, input=None, **kw):
            copied.append((cmd, input))
            return types.SimpleNamespace(returncode=0)

        with mock.patch("probandia.util.clipboard.shutil.which", side_effect=lambda n: f"/bin/{n}"), \
                mock.patch("probandia.util.clipboard.subprocess.run", run), \
                mock.patch("probandia.util.clipboard.sys.platform", "linux"):
            code, out = self.call("cite", "--form", "--repository", "AD Doubs", "--collection", "État civil",
                                  "--reference", "3 E 41", "--page", "12", "--copy", cwd=self.outside())
        self.assertEqual(code, 0, out)
        golden(self, "cite", out)
        self.assertEqual(copied, [(["/bin/xclip", "-selection", "clipboard"],
                                   "AD Doubs, État civil, 3 E 41, page 12.".encode())])

    BAPTISM = ["--form", "--type", "parish-register", "--jurisdiction", "Saint-Epvre de Nancy", "--register",
               "Baptêmes, mariages, sépultures, 1780-1792", "--reference", "3 E 160/4", "--folio", "12 v°",
               "--act", "baptism", "--act-date", "1785-03-14", "--names", "Nicolas Hugot",
               "--repository", "Archives départementales de Meurthe-et-Moselle", "--layer", "online-image",
               "--layer-url", "https://archives.meurthe-et-moselle.fr/ark:/example", "--layer-image", "27",
               "--layer-accessed", "2026-10-04"]

    def test_cite_typed_three_forms(self):
        code, out = self.call("cite", *self.BAPTISM, cwd=self.outside())
        self.assertEqual(code, 0, out)
        golden(self, "cite-typed", out)

    def test_cite_typed_one_form_in_french(self):
        code, out = self.call("cite", *self.BAPTISM, "--as", "short", "--lang", "fr", cwd=self.outside())
        self.assertEqual(code, 0, out)
        golden(self, "cite-typed-short-fr", out)

    def test_cite_without_a_clipboard(self):
        with mock.patch("probandia.util.clipboard.shutil.which", return_value=None):
            code, out = self.call("cite", "--form", "--repository", "AD", "--copy", terminal=False,
                                  cwd=self.outside())
        self.assertIn("STATUS=WARN", out)
        self.assertIn("no clipboard tool found", out)

    def test_clipboard_tools(self):
        from probandia.util import clipboard

        self.assertEqual([t[0] for t in clipboard.tools({}, "win32")], ["clip"])
        self.assertEqual([t[0] for t in clipboard.tools({"WAYLAND_DISPLAY": "w"}, "linux")], ["wl-copy", "xclip"])
        self.assertEqual([t[0] for t in clipboard.tools({}, "linux")], ["xclip", "wl-copy"])

    def test_search(self):
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        def transport(method, url, headers, body, timeout):
            if url.startswith("https://api.tavily.com/search"):
                fx = fixture("tavily", "search-ok.json")
                return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url
            return 404, {}, b"", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        with mock.patch.object(search_cmd, "_client", make_client):
            code, out = self.call("search", "Hugo Besançon", "--engine", "tavily", "--research", RESEARCH,
                                  env=REUSE)   # T217: Tavily may train on what it is sent
        self.assertEqual(code, 0, out)
        golden(self, "search", steady(out))
        self.assertIn("Tavily: ", out)

    def test_read(self):
        from probandia.cli import reading_cmd
        from probandia.reading.ladder import ReadResult

        class Reader:
            def read(self, url, fresh=False, max_step=None):
                r = ReadResult(url)
                r.status, r.step, r.extractor = "ok", "reader", "jina"
                r.text = "Acte de naissance de Louis Marchand, né à Bourg-Vert le 2 mars 1898, fils de Henri."
                r.tried = [("http", "blocked"), ("reader:jina", "ok")]
                r.spent = [("jina", "read", 3000)]
                return r

        with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work: Reader()):
            code, out = self.call("read", "https://example.org/acte", "--question", "naissance Louis Marchand")
        self.assertEqual(code, 0, out)
        golden(self, "read", steady(out))
        self.assertIn("Read at step 5: a reading service (jina)", out)
        self.assertIn("jina 3,000 units", out)

    def test_read_says_when_the_browser_could_not_start(self):
        from probandia.cli import reading_cmd
        from probandia.reading.ladder import ReadResult

        class Reader:
            def read(self, url, fresh=False, max_step=None):
                r = ReadResult(url)
                r.status = "template"
                r.tried = [("http", "template"), ("browser", "unavailable")]
                return r

        with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work: Reader()):
            code, out = self.call("read", "https://example.org/search", terminal=False)
        self.assertEqual(code, 1, out)
        self.assertIn("TRIED=http:template browser:unavailable", out)
        self.assertIn("the local browser could not start; to read such pages, install it:", out)
        self.assertIn("-m playwright install chromium", out)

    def test_ocr(self):
        from probandia import transcription

        with mock.patch.object(transcription, "tesseract", return_value=["L'an mil huit cent", "quatre-vingt-dix-huit"]):
            code, out = self.call("transcribe", "ocr", "families/marchand/evidence/images/bourg-vert-1898-57.jpg")
        self.assertEqual(code, 0, out)
        golden(self, "ocr", out)

    def test_transcribe_template(self):
        code, out = self.call("transcribe", "template", "src-01JA0000000000000000000001")
        golden(self, "transcribe-template", out)


class TheOtherUserCommands(ViewCase):
    """new, resume, fork, quota and import: the generic layout, tested (CLI5 acceptance)."""

    def setUp(self):
        super().setUp()
        # the balances read at the day's first resume (T52), with the network blocked here: test_lifecycle
        patcher = mock.patch("probandia.cli.search_cmd.auto_sync", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def today(self, text):
        import datetime as dt

        return steady(text.replace(dt.date.today().isoformat(), "<today>"))

    def test_new(self):
        code, out = self.call("new", "Who were the parents of Henri Marchand?", env={"PROBANDIA_RUN_MODE": "session"})
        self.assertEqual(code, 0, out)
        golden(self, "new", self.today(out))

    def test_new_asks(self):
        code, out = self.call("new", "Who were the parents of Henri Marchand?")
        self.assertEqual(code, 3, out)
        golden(self, "new-ask", out)

    def test_resume(self):
        code, out = self.call("resume", RESEARCH)
        self.assertEqual(code, 0, out)
        golden(self, "resume", out)

    def test_fork(self):
        code, out = self.call("fork", RESEARCH, "--name", "perrin-line")
        self.assertEqual(code, 0, out)
        golden(self, "fork", self.today(out))

    def test_quota(self):
        code, out = self.call("quota", "show")
        self.assertEqual(code, 0, out)
        golden(self, "quota", out)

    def test_import(self):
        work = os.path.join(self.tmp.name, "workshop")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "workshop"), work)
        code, out = self.call("import", work)
        golden(self, "import", self.today(out.replace(self.tmp.name, "<tmp>").replace("\\", "/")))


def unversioned(out):
    """The welcome screen without its version number, so that a new version touches no reference file."""
    return out.replace(f"Probandia {__version__} ", "Probandia <version> ", 1)


class Welcome(ViewCase):
    """probandia alone (cli.md § 6.6, D-11): the welcome screen, readable only."""

    def setUp(self):
        super().setUp()
        from probandia.cli import board_cmd

        for patcher in (mock.patch.object(board_cmd, "_ledger", lambda project, cat, environ: Ledger(
                            project, cat, clock=lambda: NOW, environ=environ)),
                        mock.patch.object(doctor, "catalogue_ages", return_value=[("serpapi", 12)])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_in_a_project(self):
        self.call("import-gedcom", os.path.join(ROOT, "tests", "fixtures", "gedcom", "tree-7.ged"), terminal=False)
        code, out = self.call()
        self.assertEqual(code, 0, out)
        golden(self, "board", unversioned(out).replace(self.dir, "<project>"))
        self.assertIn("1 proposal waiting", out)
        self.assertIn("→ probandia apply <proposal>", out)

    def test_open_pass_and_alerts(self):
        agent = {"CLAUDECODE": "1"}
        self.call("resume", RESEARCH, terminal=False, env=agent)
        lock = os.path.join(self.dir, ".probandia", "locks", "research-" + RESEARCH + ".json")
        with open(lock, encoding="utf-8") as fh:
            data = json.load(fh)
        data["expires"] = "2026-10-01T10:00:00Z"
        with open(lock, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, out = self.call()
        self.assertIn("pass 3 open", out)
        self.assertIn("Alerts", out)
        self.assertIn("expired", out)
        self.assertIn("in your agent, to go on with the open pass", out)

    def test_outside_a_project(self):
        folder = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(folder)
        code, out = self.call(cwd=folder)
        self.assertEqual(code, 0, out)
        golden(self, "board-outside", unversioned(out))
        self.assertIn("no project here", out)

    def test_the_contract_keeps_its_usage_error(self):
        code, out = self.call(terminal=False)
        self.assertEqual(code, 2, out)
        self.assertTrue(out.startswith("STATUS=FAIL\nREASON=usage\n"), out)
        code, out = self.call("--json")
        self.assertEqual(code, 2, out)

    def test_global_options_alone_still_welcome(self):
        code, out = self.call("-l", "fr")
        self.assertEqual(code, 0, out)
        self.assertIn("Ensuite", out)


class Providers(ViewCase):
    """providers (cli.md 5.4.1 to 5.4.4; CLI7-T6, T7)."""

    def setUp(self):
        super().setUp()
        from probandia.cli import providers_cmd, usage_cmd

        # T217: the catalogue was read again on 2026-10-23; two days later
        for patcher in (mock.patch.object(providers_cmd, "_today", return_value=datetime.date(2026, 10, 25)),
                        mock.patch.object(usage_cmd, "_now", return_value=NOW),
                        mock.patch("probandia.i18n.formats.local_time", return_value="2026-10-02 18:30")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_list(self):
        code, out = self.call("providers")
        self.assertEqual(code, 0, out)
        golden(self, "providers", out)

    def test_show(self):
        code, out = self.call("providers", "show", "brave")
        self.assertEqual(code, 0, out)
        golden(self, "provider", out)
        self.assertIn("card required       yes", out)

    def test_stale(self):
        from probandia.cli import providers_cmd

        with mock.patch.object(providers_cmd, "_today", return_value=datetime.date(2027, 3, 1)):
            code, out = self.call("providers", "stale")
        golden(self, "providers-stale", out)
        self.assertIn("entries checked more than 90 days ago", out)
        self.assertEqual(self.call("providers", "stale", terminal=False)[1].split("\n")[0], "STATUS=OK")

    def test_disable_freezes_no_list(self):
        self.call("providers", "disable", "serper", terminal=False)
        with open(os.path.join(self.dir, "probandia.toml"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('providers.disabled = ["serper"]', text)
        self.assertNotIn("providers.enabled", text)   # a provider added to the catalogue later stays on
        self.call("providers", "enable", "serper", terminal=False)
        with open(os.path.join(self.dir, "probandia.toml"), encoding="utf-8") as fh:
            self.assertNotIn("providers.", fh.read())

    def test_disable_then_usage(self):
        code, out = self.call("providers", "disable", "serper", terminal=False)
        self.assertEqual(code, 0, out)
        self.assertIn("STATE=not-enabled", out)
        out = self.call("-u", "--width", "110")[1]
        self.assertRegex(out, r"disabled: [^\n]*Serper")
        self.assertNotIn(" ✓ Serper ", out)
        code, out = self.call("providers", "enable", "serper", terminal=False)
        self.assertIn("STATE=ready", out)

    def test_enable_warns(self):
        out = self.call("providers", "enable", "serpapi_bing", terminal=False)[1]
        self.assertIn("4 exact genealogical queries out of 5", out)
        out = self.call("providers", "enable", "brave", terminal=False)[1]
        self.assertIn("STATUS=WARN", out)   # already listed, and its card keeps it off
        self.assertIn("unknown provider", self.call("providers", "show", "serpap", terminal=False)[1])

    def test_user_file(self):
        folder = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(folder)
        code, out = self.call("providers", "disable", "exa", "--user", terminal=False, cwd=folder)
        self.assertEqual(code, 0, out)
        self.assertIn("LAYER=user", out)


class Archives(ViewCase):
    """archive list and archive coverage (cli.md 5.4.6, 5.4.7; CLI7-T8)."""

    def test_list(self):
        code, out = self.call("archive", "list")
        self.assertEqual(code, 0, out)
        golden(self, "archive-list", out)
        out = self.call("archive", "list", terminal=False)[1]
        self.assertIn("CONNECTORS=14\n", out)   # A4: ad50
        self.assertIn("- archive=socface index html key=- third-party=forbidden\n", out)
        self.assertIn("- archive=europeana press enabled key=EUROPEANA_API_KEY\n", out)

    def test_coverage_of_a_french_department(self):
        code, out = self.call("archive", "coverage", "Morbihan", "--from", "1850", "--to", "1900")
        self.assertEqual(code, 0, out)
        golden(self, "archive-coverage", out)
        out = self.call("archive", "coverage", "Morbihan", "--from", "1850", "--to", "1900", terminal=False)[1]
        self.assertIn("CODES=FR-56,FR\n", out)
        self.assertIn("- archive=ad56 image 1550-1936 browser", out)
        self.assertNotIn("archive=matchid", out)        # deaths since 1970 only
        self.assertIn("archive=matchid", self.call("archive", "coverage", "FR-56", "--from", "1980",
                                                   terminal=False)[1])

    def test_a_department_an_archive_lacks(self):
        out = self.call("archive", "coverage", "Manche", "--from", "1850", "--to", "1900", terminal=False)[1]
        self.assertNotIn("socface", out)                # Manche is absent from SocFace
        self.assertNotIn("ad56", out)

    def test_nowhere(self):
        code, out = self.call("archive", "coverage", "Atlantis", terminal=False)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("place not recognised", out)
        self.assertIn("did you mean Morbihan?", self.call("archive", "coverage", "Morbihn", terminal=False)[1])
        self.assertIn("place not recognised", self.call("archive", "coverage", "Atlantis")[1])


if __name__ == "__main__":
    unittest.main()
