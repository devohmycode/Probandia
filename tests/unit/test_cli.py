import io
import json
import os
import tempfile
import unittest
from unittest import mock

from probandia import cli
from probandia.cli.commands import COMMAND_NAMES, COMMANDS
from probandia.cli.output import Result

# Every command of the command table, user and engine.
EXPECTED_COMMANDS = [
    "new", "resume", "fork", "verify", "question", "matrix", "fact", "close", "status", "report", "tree", "export", "config", "quota",
    "doctor", "library", "memory", "template", "import", "import-gedcom", "usage", "cache", "help", "completion", "init", "keys", "providers", "research", "family", "find", "person", "searches", "sources", "negatives",
    "hypotheses", "gaps", "proposals", "board", "statusline", "tui", "watch",
    "plan", "known", "correlate", "proof", "search", "login", "browser", "read", "archive", "transcribe", "image", "dates", "variants", "places", "cite", "id", "workshop",
    "propose", "apply", "event", "render", "digest", "pass", "volet", "team", "lock", "manifests", "install", "mcp", "hook",
]


def call(*argv, cwd=None, environ=None):
    out = io.StringIO()
    env = {} if environ is None else environ
    code = cli.main(list(argv), stdout=out, environ=env, cwd=cwd or tempfile.gettempdir())
    return code, out.getvalue()


class Help(unittest.TestCase):
    def test_lists_every_command(self):
        self.assertEqual(COMMAND_NAMES, EXPECTED_COMMANDS)
        out = io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit) as cm:
            cli.main(["--help"], stdout=io.StringIO())
        self.assertEqual(cm.exception.code, 0)
        text = out.getvalue()
        for name in EXPECTED_COMMANDS:
            self.assertRegex(text, rf"\n\s+{name}\s", name)


class ExitCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_usage_error_is_2(self):
        code, out = call("no-such-command", cwd=self.dir)
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("STATUS=FAIL\nREASON=usage\n"))

    def test_bad_option_is_2(self):
        code, out = call("lock", "take", "--no-such-option", cwd=self.dir)
        self.assertEqual(code, 2)

    def test_outside_a_project_is_6(self):
        code, out = call("status", cwd=self.dir)
        self.assertEqual(code, 6)
        self.assertIn("REASON=no-project", out)

    def test_lock_held_is_5(self):
        call("config", "init", cwd=self.dir)
        self.assertEqual(call("lock", "take", "family:hugo", cwd=self.dir,
                              environ={"PROBANDIA_SESSION": "a"})[0], 0)
        code, out = call("lock", "take", "family:hugo", cwd=self.dir,
                         environ={"PROBANDIA_SESSION": "b"})
        self.assertEqual(code, 5)
        self.assertIn("REASON=lock-held", out)

    def test_one_agent_at_a_time_in_the_browser(self):
        # FL4-T3: the file the reading ladder already reads (reading/ladder.py, _browser_lock_held)
        from probandia.reading.ladder import Reader

        call("config", "init", cwd=self.dir)
        a, b = {"PROBANDIA_SESSION": "a"}, {"PROBANDIA_SESSION": "b"}
        self.assertEqual(call("lock", "take", "browser", "--agent", "researcher", cwd=self.dir, environ=a)[0], 0)
        lock = os.path.join(self.dir, ".probandia", "locks", "browser.json")
        self.assertTrue(os.path.isfile(lock))
        self.assertTrue(Reader._browser_lock_held(mock.Mock(state_dir=os.path.join(self.dir, ".probandia"))))
        code, out = call("lock", "take", "browser", cwd=self.dir, environ=b)
        self.assertEqual(code, 5)
        self.assertIn("REASON=lock-held", out)
        code, out = call("lock", "status", "browser", cwd=self.dir, environ=b)
        self.assertIn("STATE=held", out)
        self.assertEqual(call("lock", "release", "browser", "--agent", "researcher", cwd=self.dir, environ=a)[0], 0)
        self.assertFalse(os.path.exists(lock))
        self.assertIn("STATE=free", call("lock", "status", "browser", cwd=self.dir, environ=b)[1])

    def test_internal_error_is_10(self):
        def boom(ctx):
            raise ZeroDivisionError("boom")

        spec = next(c for c in COMMANDS if c.name == "doctor")
        with mock.patch.object(spec, "handler", boom):
            code, out = call("doctor", cwd=self.dir)
        self.assertEqual(code, 10)
        self.assertIn("REASON=internal-error", out)
        log = next(line[4:] for line in out.splitlines() if line.startswith("LOG="))
        with open(log, encoding="utf-8") as fh:
            self.assertIn("ZeroDivisionError", fh.read())
        os.unlink(log)

    def test_status_codes_pass_through(self):
        cases = {"OK": 0, "WARN": 0, "FAIL": 1, "ASK": 3, "STOP": 4}
        spec = next(c for c in COMMANDS if c.name == "doctor")
        for status, expected in cases.items():
            with mock.patch.object(spec, "handler", lambda ctx, s=status: Result(s)):
                code, out = call("doctor", cwd=self.dir)
            self.assertEqual(code, expected, status)
            self.assertTrue(out.startswith(f"STATUS={status}\n"))


class GlobalOptions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        call("config", "init", cwd=self.dir)

    def test_json_before_or_after_the_command(self):
        for argv in (["--json", "lock", "status", "research:r"],
                     ["lock", "status", "research:r", "--json"]):
            code, out = call(*argv, cwd=self.dir)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["values"]["STATE"], "free")

    def test_json_on_usage_error(self):
        code, out = call("--json", "nope", cwd=self.dir)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "FAIL")

    def test_quiet(self):
        code, out = call("lock", "status", "research:r", "--quiet", cwd=self.dir)
        self.assertEqual(out, "STATUS=OK\n")

    def test_project_option(self):
        other = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(other, ignore_errors=True))
        code, out = call("--project", self.dir, "lock", "status", "family:x", cwd=other)
        self.assertEqual(code, 0)

    def test_harness_and_agent(self):
        code, out = call("--harness", "codex", "--agent", "orchestrator", "lock", "take",
                         "research:r", cwd=self.dir, environ={"PROBANDIA_SESSION": "s1"})
        self.assertIn("HOLDER=codex/s1/orchestrator", out)

    def test_unknown_harness_is_refused(self):
        code, out = call("--harness", "notepad", "lock", "status", "research:r", cwd=self.dir)
        self.assertEqual(code, 2)

    def test_output_is_capped(self):
        spec = next(c for c in COMMANDS if c.name == "doctor")
        many = Result("OK", lines=[str(i) for i in range(500)])
        with mock.patch.object(spec, "handler", lambda ctx: many):
            code, out = call("doctor", cwd=self.dir)
        self.assertEqual(len(out.splitlines()), 40)
