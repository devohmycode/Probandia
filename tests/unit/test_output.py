import json
import unittest

from probandia.cli.output import Result, escape
from probandia.limits import OUTPUT_MAX_LINES


class Statuses(unittest.TestCase):
    def test_exit_code_of_each_status(self):
        expected = {"OK": 0, "WARN": 0, "FAIL": 1, "ASK": 3, "STOP": 4}
        for status, code in expected.items():
            self.assertEqual(Result(status).exit_code, code, status)

    def test_first_line_is_status(self):
        for status in ("OK", "WARN", "FAIL", "ASK", "STOP"):
            self.assertTrue(Result(status).render_text().startswith(f"STATUS={status}\n"))

    def test_unknown_status_is_refused(self):
        with self.assertRaises(ValueError):
            Result("MAYBE")

    def test_explicit_exit_code(self):
        self.assertEqual(Result("FAIL", exit_code=5).exit_code, 5)


class TextForm(unittest.TestCase):
    def test_layout(self):
        r = Result("OK", {"RESEARCH": "r1", "PASS": 2}, ["one", "two"], details="work/d.md")
        self.assertEqual(r.render_text(),
                         "STATUS=OK\nRESEARCH=r1\nPASS=2\n- one\n- two\nDETAILS=work/d.md\n")

    def test_keys_are_upper_case(self):
        for bad in ("research", "Pass", "A-B", "STATUS", "DETAILS", ""):
            with self.assertRaises(ValueError, msg=bad):
                Result("OK").set(bad, 1)

    def test_newlines_are_escaped(self):
        r = Result("OK", {"QUESTION": "a\nb\r\nc"}, ["x\ny"])
        self.assertEqual(r.render_text(), "STATUS=OK\nQUESTION=a\\nb\\nc\n- x\\ny\n")

    def test_booleans(self):
        self.assertEqual(escape(True), "true")
        self.assertEqual(escape(False), "false")

    def test_quiet_keeps_status_and_details(self):
        r = Result("OK", {"A": 1}, ["x"], details="d.md")
        self.assertEqual(r.render_text(quiet=True), "STATUS=OK\nDETAILS=d.md\n")


class Cap(unittest.TestCase):
    def test_forty_lines_at_most(self):
        r = Result("OK", {"A": 1, "B": 2}, [f"line {i}" for i in range(100)], details="d.md")
        out = r.render_text().splitlines()
        self.assertEqual(len(out), OUTPUT_MAX_LINES)
        self.assertEqual(out[0], "STATUS=OK")
        self.assertEqual(out[-1], "DETAILS=d.md")
        self.assertEqual(out[-2], "- … 65 more lines omitted")
        self.assertEqual(out[3], "- line 0")

    def test_exactly_forty_lines_are_not_cut(self):
        r = Result("OK", lines=[str(i) for i in range(39)])
        out = r.render_text().splitlines()
        self.assertEqual(len(out), 40)
        self.assertEqual(out[-1], "- 38")

    def test_too_many_values(self):
        r = Result("OK", {"K" + "A" * i: i for i in range(60)}, ["x"], details="d.md")
        out = r.render_text().splitlines()
        self.assertEqual(len(out), OUTPUT_MAX_LINES)
        self.assertEqual(out[-1], "DETAILS=d.md")
        self.assertTrue(out[-2].endswith("more values omitted"))


class AskAndStop(unittest.TestCase):
    def test_ask(self):
        r = Result.ask("launch", "ask-launch", ["session", "subagent", "team"], "session")
        self.assertEqual(r.exit_code, 3)
        self.assertEqual(r.render_text(),
                         "STATUS=ASK\nQUESTION=launch\nPROMPT=ask-launch\n"
                         "CHOICES=session|subagent|team\nALLOW_OTHER=false\nDEFAULT=session\n")

    def test_ask_survives_quiet(self):
        r = Result.ask("q", "p", ["a", "b"], "a", allow_other=True)
        r.line("hidden")
        self.assertIn("ALLOW_OTHER=true", r.render_text(quiet=True))
        self.assertNotIn("hidden", r.render_text(quiet=True))

    def test_ask_says_each_value_once(self):
        from probandia import questions
        for qids in (["team_agents", "team_effort", "team_passes"], ["interrupted_pass"]):
            r = questions.ask(qids, "claude-code")
            for name in ("PROMPT", "CHOICES", "DEFAULT", "OPTION"):
                keys = [k for k in r.values if k == name or k.startswith(name + "_")]
                values = [r.values[k] for k in keys]
                self.assertEqual(len(values), len(qids), (qids, keys))
                self.assertEqual(len(set(values)), len(values), (qids, keys))
            self.assertNotIn("QUESTIONS", r.values) if len(qids) == 1 else self.assertIn("QUESTIONS", r.values)
            quiet = r.render_text(quiet=True)  # --quiet keeps every question
            self.assertTrue(all(f"OPTION{'_' + q.upper() if len(qids) > 1 else ''}=" in quiet for q in qids), quiet)

    def test_stop(self):
        r = Result.stop("quota:brave", alternative="tavily")
        self.assertEqual(r.exit_code, 4)
        self.assertEqual(r.render_text(quiet=True),
                         "STATUS=STOP\nREASON=quota:brave\nALTERNATIVE=tavily\n")


class JsonForm(unittest.TestCase):
    def test_one_object(self):
        r = Result("WARN", {"A": "é"}, ["x"], details="d.md")
        obj = json.loads(r.render_json())
        self.assertEqual(obj, {"status": "WARN", "values": {"A": "é"}, "lines": ["x"],
                               "details": "d.md"})
        self.assertEqual(r.render_json().count("\n"), 1)

class Tables(unittest.TestCase):
    def test_tables_go_to_json_only(self):
        r = Result("OK", {"PROVIDERS": 1})
        r.table("providers", [{"id": "serpapi", "left": 225}])
        self.assertEqual(r.to_json()["data"], {"providers": [{"id": "serpapi", "left": 225}]})
        self.assertEqual(r.render_text(), "STATUS=OK" + chr(10) + "PROVIDERS=1" + chr(10))
        self.assertEqual(r.tables["providers"]["columns"], ["id", "left"])

    def test_no_data_key_without_tables(self):
        self.assertNotIn("data", Result("OK").to_json())
