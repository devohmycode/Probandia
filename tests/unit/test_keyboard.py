"""Questions and confirmations at the keyboard (cli.md § 6.3, § 6.4; CLI6)."""
import io
import os
import shutil
import tempfile
import unittest

from probandia import cli, events, i18n
from probandia.research import find_research
from tests import REUSE, ROOT

QUESTION = "Who were the parents of Henri Marchand?"


class TTY(io.StringIO):
    def isatty(self):
        return True


class Interrupting(TTY):
    def readline(self, *a):
        raise KeyboardInterrupt


class KeyboardCase(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "NO_COLOR": "1",
                    "PROBANDIA_PAGER": "none", "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d")}

    def call(self, *argv, keys=None, terminal=True, env=None, stdin=None, cwd=None):
        out = TTY() if terminal else io.StringIO()
        stdin = stdin if stdin is not None else TTY("".join(k + "\n" for k in keys or []))
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=cwd or self.dir,
                        stdin=stdin)
        return code, out.getvalue()

    def research(self, rid):
        return find_research(self.dir, rid)


class Questions(KeyboardCase):
    """CLI6-T1: an ASK is put to the person, then the command runs again with the answers."""

    def test_keyboard_reaches_the_state_of_the_arguments(self):
        code, out = self.call("new", QUESTION, keys=["3", "7", "3"])
        self.assertEqual(code, 0, out)
        self.assertIn("Who runs this research?", out)
        self.assertIn("  3. team", out)
        rid = [x for x in os.listdir(os.path.join(self.dir, "families", "marchand", "research"))
               if "henri" in x][0]
        by_keyboard = self.research(rid).meta()["run"]
        shutil.rmtree(os.path.join(self.dir, "families", "marchand", "research", rid))
        code, out = self.call("new", QUESTION, "--mode", "team", "--agents", "7", "--passes", "3", "--no-pass",
                              terminal=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.research(rid).meta()["run"], by_keyboard)
        self.assertEqual(by_keyboard["mode"], "team")
        self.assertEqual(by_keyboard["max_agents"], 7)

    def test_enter_takes_the_default_shown(self):
        code, out = self.call("new", QUESTION, keys=[""])
        self.assertEqual(code, 0, out)
        self.assertIn("Your choice [1]:", out)
        self.assertIn("run by    session", out)

    def test_a_wrong_answer_is_asked_again(self):
        code, out = self.call("new", QUESTION, keys=["9", "1"])
        self.assertEqual(code, 0, out)
        self.assertIn("answer with a number from 1 to 3", out)

    def test_ctrl_c_stops(self):
        code, out = self.call("new", QUESTION, stdin=Interrupting())
        self.assertEqual(code, 130, out)
        self.assertIn("stopped", out)
        self.assertNotIn("henri", " ".join(os.listdir(os.path.join(self.dir, "families", "marchand", "research"))))

    def test_end_of_input_stops(self):
        code, out = self.call("new", QUESTION, keys=[])
        self.assertEqual(code, 130, out)

    def test_headless_takes_the_defaults(self):
        code, out = self.call("new", QUESTION, keys=[], env={"PROBANDIA_HEADLESS": "1"})
        self.assertEqual(code, 0, out)
        self.assertNotIn("Who runs this research?", out)

    def test_the_contract_never_asks_at_the_keyboard(self):
        code, out = self.call("new", QUESTION, keys=["3"], terminal=False)
        self.assertEqual(code, 3, out)
        self.assertTrue(out.startswith("STATUS=ASK\n"), out)

    def test_input_that_is_not_a_terminal_is_not_read(self):
        code, out = self.call("new", QUESTION, stdin=io.StringIO("3\n"))
        self.assertEqual(code, 3, out)

    def test_the_application_puts_the_questions(self):
        """T107: through the terminal application's function, nothing read from the input: a choice
        is checked as at the keyboard (a rank, a wrong answer asked again), a cancel stops."""
        from probandia.cli import asking

        asked = []

        def ask(kind, prompt, choices=(), default="", other=False):
            asked.append((kind, prompt, list(choices)))
            return answers.pop(0)

        answers = ["9", "3", "7", "3"]   # 9: no choice of that rank, asked again
        with asking.through(ask):
            code, out = self.call("new", QUESTION, stdin=io.StringIO())
        self.assertEqual(code, 0, out)
        self.assertEqual([a[0] for a in asked], ["choose"] * 4)
        self.assertEqual(asked[0][1:], ("Who runs this research?", ["session", "subagent", "team"]))
        self.assertNotIn("Your choice", out)   # put by the application, not written
        rid = [x for x in os.listdir(os.path.join(self.dir, "families", "marchand", "research")) if "henri" in x][0]
        self.assertEqual(self.research(rid).meta()["run"]["mode"], "team")
        self.assertIsNone(asking.given())   # only while in the block
        answers = [None]
        with asking.through(ask):
            code, out = self.call("new", QUESTION + " again", stdin=io.StringIO())
        self.assertEqual(code, 130, out)


class NewAtATerminal(KeyboardCase):
    """CLI6-T2: new creates the research without a pass; resume opens pass 1."""

    def test_new_no_pass_then_resume(self):
        code, out = self.call("new", QUESTION, "--mode", "session", "--no-pass", "--instructions", "look in Les Ormes",
                              terminal=False)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS=0\n", out)
        rid = out.split("RESEARCH=")[1].split("\n")[0]
        self.assertIn(f"NEXT=/probandia:resume {rid}\n", out)
        code, out = self.call("resume", rid, terminal=False, env={"CLAUDECODE": "1"})
        self.assertEqual(code, 0, out)
        self.assertIn("PASS=1\n", out)
        started = [e for e in events.read(self.research(rid).events_path) if e["type"] == "pass.started"]
        self.assertEqual([e["pass"] for e in started], [1])
        self.assertEqual(started[0]["payload"]["instructions"], ["look in Les Ormes"])

    def test_readable_new_opens_no_pass(self):
        code, out = self.call("new", QUESTION, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertIn("In your agent: /probandia:resume", out)
        code, out = self.call("status", terminal=False)
        self.assertNotIn("pass 1 open", out)

    def test_open_pass_at_a_terminal(self):
        code, out = self.call("new", QUESTION, "--mode", "session", "--open-pass")
        self.assertIn("pass 1 is open", out)

    def test_the_contract_still_opens_pass_1(self):
        code, out = self.call("new", QUESTION, "--mode", "session", terminal=False)
        self.assertIn("PASS=1\n", out)


class Confirmations(KeyboardCase):
    """CLI6-T3: before spending a quota or writing what is hard to undo, [y/N]."""

    def used(self, provider):
        from probandia.ledger import Ledger
        from probandia.providers import catalogue

        return Ledger(self.dir, catalogue.load(), environ=self.env).used(provider)[0]

    def test_quota_add_accepted(self):
        code, out = self.call("quota", "add", "tavily", "5", keys=["y"])
        self.assertEqual(code, 0, out)
        self.assertIn("Record 5.0 units used on tavily? The ledger is only ever added to. [y/N]", out)
        self.assertEqual(self.used("tavily"), 5)

    def test_quota_add_declined(self):
        code, out = self.call("quota", "add", "tavily", "5", keys=["n"])
        self.assertEqual(code, 4, out)
        self.assertIn("nothing was done", out)
        self.assertEqual(self.used("tavily"), 0)

    def test_anything_but_yes_declines(self):
        self.call("quota", "add", "tavily", "5", keys=[""])
        self.assertEqual(self.used("tavily"), 0)

    def test_yes_skips_the_question(self):
        code, out = self.call("quota", "add", "tavily", "5", "--yes", keys=[])
        self.assertEqual(code, 0, out)
        self.assertNotIn("[y/N]", out)
        self.call("-y", "quota", "add", "tavily", "1", keys=[])
        self.assertEqual(self.used("tavily"), 6)

    def test_no_question_outside_a_terminal(self):
        code, out = self.call("quota", "add", "tavily", "5", keys=["n"], terminal=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.used("tavily"), 5)

    def test_french(self):
        code, out = self.call("-l", "fr", "quota", "add", "tavily", "5", keys=["o"])
        self.assertIn("[o/N]", out)
        self.assertEqual(self.used("tavily"), 5)

    def test_export_that_replaces_a_file(self):
        self.assertEqual(self.call("export", "gedcom551", terminal=False)[0], 0)
        folder = os.path.join(self.dir, "exports")
        path = os.path.join(folder, os.listdir(folder)[0])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("mine")
        code, out = self.call("export", "gedcom551", keys=["n"])
        self.assertIn("already exists. Replace it?", out)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "mine")
        self.call("export", "gedcom551", keys=["y"])
        with open(path, encoding="utf-8") as fh:
            self.assertNotEqual(fh.read(), "mine")

    def test_search_declined_spends_nothing(self):
        from unittest import mock

        from probandia.cli import search_cmd

        calls = []

        def make_client(ctx):
            calls.append(ctx)
            raise AssertionError("no provider may be called")

        with mock.patch.object(search_cmd, "_client", make_client):
            code, out = self.call("search", "Hugo Besançon", "--engine", "tavily", keys=["n"],
                                  env={**REUSE, "TAVILY_API_KEY": "k"})
        self.assertEqual(code, 4, out)
        self.assertIn('Search "Hugo Besançon"? It uses the free quotas: Tavily: 1 credit, 900 left.', out)
        self.assertEqual(calls, [])
        self.assertEqual(self.used("tavily"), 0)

    def test_read_declined(self):
        from unittest import mock

        from probandia.cli import reading_cmd

        with mock.patch.object(reading_cmd, "build_reader", side_effect=AssertionError("no read")):
            code, out = self.call("read", "https://example.org/acte", keys=["n"])
        self.assertEqual(code, 4, out)
        self.assertIn("Read https://example.org/acte?", out)


class ErrorsThatSayWhatToDo(KeyboardCase):
    """CLI6-T5 (cli.md § 6.5)."""

    def outside(self):
        folder = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(folder, exist_ok=True)
        return folder

    def test_no_project(self):
        code, out = self.call("status", cwd=self.outside())
        self.assertEqual(code, 6, out)
        for step in ('probandia new "<question>"', "probandia config init", "probandia -p <folder>", "probandia -u"):
            self.assertIn(step, out)
        code, out = self.call("status", cwd=self.outside(), terminal=False)
        self.assertEqual(out, "STATUS=FAIL\nREASON=no-project\n- not inside a project: no probandia.toml here or "
                              "above\n- create one with: config init\n")

    def test_typo_in_a_command(self):
        code, out = self.call("statsu", terminal=False)
        self.assertEqual(code, 2)
        self.assertIn("- did you mean status?\n", out)

    def test_typo_in_a_provider(self):
        self.assertIn("- did you mean serpapi?\n", self.call("usage", "serpap", terminal=False)[1])
        self.assertIn("- did you mean serpapi?\n", self.call("quota", "show", "serpap", terminal=False)[1])
        self.assertIn("- did you mean tavily?\n",
                      self.call("search", "x", "--engine", "tavly", terminal=False, env={"PROBANDIA_HEADLESS": "1"})[1])

    def test_typo_in_a_setting(self):
        self.assertIn("- did you mean report.mode?\n", self.call("config", "explain", "report.mod", terminal=False)[1])

    def test_typo_in_a_family(self):
        self.assertIn("- did you mean marchand?\n", self.call("status", "--family", "marchnd", terminal=False)[1])

    def test_nothing_close_suggests_nothing(self):
        self.assertNotIn("did you mean", self.call("usage", "zzzzzz", terminal=False)[1])

    def test_ambiguous_prefix_is_a_choice(self):
        ids = []
        for q in ("Who were the parents of Henri Marchand?", "Where did Henri Marchand die?"):
            out = self.call("new", q, "--mode", "session", "--no-pass", terminal=False)[1]
            ids.append(out.split("RESEARCH=")[1].split("\n")[0])
        prefix = os.path.commonprefix(ids)
        code, out = self.call("known", prefix, terminal=False)
        self.assertEqual(code, 2, out)
        self.assertIn("matches several researches", out)
        code, out = self.call("verify", prefix, keys=["2"])
        self.assertIn("names several researches: which one?", out)
        listed = [line.split(". ", 1)[1] for line in out.splitlines() if line.startswith("  2. ")]
        verdict = [line for line in out.splitlines() if "rules passed · " in line][0]
        self.assertTrue(verdict.endswith(listed[0]), verdict)


class Completion(KeyboardCase):
    """CLI6-T6: probandia __complete and the completion scripts."""

    def complete(self, *words):
        out = io.StringIO()
        code = cli.main(["__complete", *words], stdout=out, environ=self.env, cwd=self.dir)
        self.assertEqual(code, 0)
        return out.getvalue().splitlines()

    def test_commands(self):
        self.assertEqual(self.complete("st"), ["status", "statusline"])
        self.assertIn("usage", self.complete(""))
        self.assertNotIn("__complete", self.complete("_"))
        self.assertIn("-u", self.complete("-"))

    def test_research_ids(self):
        self.assertEqual(self.complete("verify", "2026"), ["2026-09-01-ancestors-of-louis-marchand"])
        self.assertEqual(self.complete("-l", "fr", "known", "20"), ["2026-09-01-ancestors-of-louis-marchand"])

    def test_options_and_their_values(self):
        self.assertEqual(self.complete("verify", "--ru"), ["--rule"])
        self.assertEqual(self.complete("verify", "x", "--rule", "V-1"), ["V-1", "V-10", "V-11", "V-12", "V-13", "V-14", "V-15", "V-16", "V-17", "V-18", "V-19"])
        self.assertEqual(self.complete("verify", "x", "--rule", "V-2"), ["V-2", "V-20"])   # T242
        self.assertEqual(self.complete("status", "--family", ""), ["marchand"])
        self.assertEqual(self.complete("--output-format", "h"), ["human"])
        self.assertEqual(self.complete("search", "x", "--engine", "tav"), ["tavily"])

    def test_providers_settings_and_actions(self):
        self.assertIn("serpapi", self.complete("usage", "serp"))
        self.assertIn("path", self.complete("config", ""))
        self.assertEqual(self.complete("config", "explain", "report.mo"), ["report.mode"])
        self.assertEqual(self.complete("completion", "p"), ["powershell"])

    def test_outside_a_project(self):
        out = io.StringIO()
        cli.main(["__complete", "verify", ""], stdout=out, environ=self.env, cwd=self.tmp.name)
        self.assertEqual(out.getvalue(), "")

    def test_scripts(self):
        for shell, marker in (("powershell", "Register-ArgumentCompleter"), ("bash", "complete -o default"),
                              ("zsh", "bashcompinit"), ("fish", "complete -c probandia")):
            code, out = self.call("completion", shell, terminal=False)
            self.assertEqual(code, 0)
            self.assertIn(marker, out)
            self.assertIn("__complete", out)
            self.assertNotIn("STATUS=", out)


class Watch(KeyboardCase):
    """CLI6-T7: --watch refreshes status and usage until Ctrl+C."""

    def watched(self, *argv, terminal=True):
        import datetime
        from unittest import mock

        waits = []

        def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                raise KeyboardInterrupt

        with mock.patch.object(cli, "_sleep", sleep), \
                mock.patch.object(cli, "_clock", return_value=datetime.datetime(2026, 10, 3, 11, 0, 0)):
            code, out = self.call(*argv, terminal=terminal)
        return code, out, waits

    def test_two_refreshes(self):
        code, out, waits = self.watched("status", "--watch", "5")
        self.assertEqual(code, 0, out)
        self.assertEqual(waits, [5.0, 5.0])
        self.assertEqual(out.count("\x1b[H\x1b[2J"), 2)
        self.assertIn("refreshed every 5 s, at 11:00:00 · Ctrl+C to stop", out)

    def test_usage_with_the_default_interval(self):
        code, out, waits = self.watched("-u", "-w")
        self.assertEqual(waits, [2.0, 2.0])
        self.assertEqual(out.count("Free quotas"), 2)

    def test_the_contract_does_not_watch(self):
        code, out, waits = self.watched("status", "--watch", terminal=False)
        self.assertEqual(waits, [])
        self.assertTrue(out.startswith("STATUS=OK\n"))


class InitAndWizard(KeyboardCase):
    """CLI7-T9: init and config wizard ask the eight essential settings."""

    # language, report.mode, report.numbering, report.formats, tree.format, run.mode, search.max_parallel, grade
    ANSWERS = ["fr", "2", "", "md,html,json", "2", "3", "5", "2"]

    def toml(self, folder):
        import tomllib

        with open(os.path.join(folder, "probandia.toml"), "rb") as fh:
            return tomllib.load(fh)

    def test_init_writes_the_answers(self):
        folder = os.path.join(self.tmp.name, "new-project")
        os.makedirs(folder)
        code, out = self.call("init", keys=self.ANSWERS, cwd=folder)
        self.assertEqual(code, 0, out)
        self.assertIn("report.mode · Report mode", out)
        doc = self.toml(folder)
        self.assertEqual(doc["language"], "fr")
        self.assertEqual(doc["report"]["mode"], "living")
        self.assertEqual(doc["report"]["numbering"], "arabic")
        self.assertEqual(doc["report"]["formats"], ["md", "html", "json"])
        self.assertEqual(doc["tree"]["format"], "md")
        self.assertEqual(doc["run"]["mode"], "subagent")
        self.assertEqual(doc["search"]["max_parallel"], 5)
        self.assertEqual(doc["grade"], "advanced")
        code, out = self.call("config", "validate", terminal=False, cwd=folder)
        self.assertEqual(code, 0, out)

    def test_a_wrong_value_is_asked_again(self):
        folder = os.path.join(self.tmp.name, "p2")
        os.makedirs(folder)
        answers = ["not a tag!"] + self.ANSWERS
        code, out = self.call("init", keys=answers, cwd=folder)
        self.assertEqual(code, 0, out)
        self.assertIn("invalid value 'not a tag!' for language", out)

    def test_ctrl_c_writes_no_answer(self):
        folder = os.path.join(self.tmp.name, "p3")
        os.makedirs(folder)
        code, out = self.call("init", keys=["fr", "2"], cwd=folder)   # the input ends before the last question
        self.assertEqual(code, 130, out)
        self.assertNotIn("language", self.toml(folder))

    def test_init_without_a_terminal_asks_nothing(self):
        folder = os.path.join(self.tmp.name, "p4")
        os.makedirs(folder)
        code, out = self.call("init", terminal=False, cwd=folder)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(folder, "probandia.toml")))

    def test_config_wizard_in_a_project(self):
        code, out = self.call("config", "wizard", keys=self.ANSWERS)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.toml(self.dir)["report"]["mode"], "living")
        code, out = self.call("config", "wizard", terminal=False)
        self.assertEqual(code, 2, out)


class ConfigEditGradeDiff(KeyboardCase):
    """CLI7-T10: config edit (editor simulated), config grade, config diff."""

    def test_edit_opens_the_file_then_checks_it(self):
        from unittest import mock

        from probandia.cli import config_cmd

        opened = []

        def editor(command, path):
            opened.append((command, path))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write('report.mode = "living"\n')
            return 0

        with mock.patch.object(config_cmd, "_run_editor", editor):
            code, out = self.call("config", "edit", "--local", terminal=False, env={"EDITOR": "myeditor --wait"})
        self.assertEqual(code, 0, out)
        self.assertEqual(opened[0][0], ["myeditor", "--wait"])
        self.assertTrue(opened[0][1].endswith("probandia.local.toml"))
        self.assertIn("- every layer is valid", out)

    def test_edit_reports_a_bad_value(self):
        from unittest import mock

        from probandia.cli import config_cmd

        def editor(command, path):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write('report.mode = "novel"\n')
            return 0

        with mock.patch.object(config_cmd, "_run_editor", editor):
            code, out = self.call("config", "edit", terminal=False)
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=config", out)

    def test_default_editor(self):
        from probandia.cli import config_cmd

        self.assertEqual(config_cmd._editor({"VISUAL": "code -w", "EDITOR": "vim"}), ["code", "-w"])
        self.assertEqual(config_cmd._editor({}), ["notepad"] if os.name == "nt" else ["vi"])

    def test_grade_shows_what_appears(self):
        code, out = self.call("config", "grade", "advanced", terminal=False)
        self.assertEqual(code, 0, out)
        self.assertIn("WAS=essential\n", out)
        self.assertIn("- providers.disabled=\n", out)
        self.assertIn("grade=advanced", self.call("config", "show", terminal=False)[1])

    def test_diff_layer_by_layer(self):
        self.call("config", "set", "--user", "language", "fr", terminal=False)
        self.call("config", "set", "report.mode", "living", terminal=False)
        code, out = self.call("config", "diff", terminal=False, env={"PROBANDIA_SEARCH_MAX_PARALLEL": "5"})
        self.assertEqual(code, 0, out)
        lines = [line for line in out.splitlines() if line.startswith("- ")]
        self.assertEqual(lines, ["- language=fr (default auto) from user",
                                 "- report.mode=living (default journal) from project",
                                 "- search.max_parallel=5 (default 3) from env"])
        readable = self.call("config", "diff", env={"PROBANDIA_SEARCH_MAX_PARALLEL": "5"})[1]
        self.assertIn("3 settings differ from their default", readable)


if __name__ == "__main__":
    unittest.main()
