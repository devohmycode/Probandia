"""T111: every user command publishes its records in ``data`` with ``--json``, on a copy of
the sample project; no process is started and no service is called."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from probandia import cli, doctor, i18n, library
from probandia.cli import export_cmd, watch_cmd
from probandia.cli.commands import COMMANDS
from probandia.lang import detect
from tests import ROOT

RESEARCH = "2026-09-01-ancestors-of-louis-marchand"
# what each command is run with; a command not named runs with no argument
ARGS = {
    "new": ["Who were the parents of Henri Marchand?", "--family", "marchand", "--mode", "session"],
    "resume": [RESEARCH],
    "fork": [RESEARCH, "--name", "perrin-line"],
    "question": ["list"],
    "report": ["open", RESEARCH],
    "export": ["gedcom7"],
    "config": ["show"],
    "quota": ["show"],
    "library": ["list"],
    "memory": ["list"],
    "template": ["list"],
    "import": ["<workshop>"],
    "import-gedcom": [os.path.join(ROOT, "tests", "fixtures", "gedcom", "tree-7.ged")],
    "cache": ["stats"],
    "keys": ["list"],
    "providers": ["list"],
    "research": ["list"],
    "family": ["list"],
    "find": ["Marchand"],
    "person": ["louis-marchand-1898"],
    "proposals": ["list"],
}
# a terminal script, the application and the browser print no record; fact check is written by
# a person at the terminal only (T248), so --json always refuses it
EXEMPT = {"completion", "tui", "browser", "fact"}


def _no_process(*args, **kwargs):
    raise AssertionError(f"a process was started: {args[:1]}")


class JsonData(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "PROBANDIA_HEADLESS": "1",
                    "PROBANDIA_PAGER": "none", "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude")}
        fake = [{"archive": "wikitree", "operation": "search", "state": "passed", "reason": None, "count": 3,
                 "failure": None}]
        for patcher in (mock.patch.object(watch_cmd, "witnesses", lambda *a, **k: fake),
                        mock.patch.object(doctor, "optional_tools", return_value={}),
                        # import tests the workshop's connectors: their run is a process, simulated here
                        mock.patch.object(library.Library, "run", return_value=(False, None, "not run")),
                        # the system's language, which macOS gives by a process (defaults read)
                        mock.patch.object(detect, "os_language", return_value="en-US"),
                        mock.patch.object(subprocess, "run", _no_process),
                        mock.patch.object(subprocess, "Popen", _no_process),
                        mock.patch.object(export_cmd, "open_folder", lambda path: True)):   # report open, on every system
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_json(self, name, project):
        workshop = os.path.join(self.tmp.name, "workshop")
        if name == "import":
            shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "workshop"), workshop)
        argv = [workshop if a == "<workshop>" else a for a in ARGS.get(name, [])]
        out = io.StringIO()
        code = cli.main([name, *argv, "--json"], stdout=out, environ=self.env, cwd=project, stdin=io.StringIO())
        return code, json.loads(out.getvalue())

    def project(self, name):
        path = os.path.join(self.tmp.name, name)
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), path)
        return path

    def test_every_user_command_has_data(self):
        names = [c.name for c in COMMANDS if not c.engine and c.name not in EXEMPT]
        self.assertGreaterEqual(len(names), 35)
        for name in names:
            with self.subTest(command=name):
                project = self.project(name)
                if name == "close":   # a research closes once its questions are settled
                    self.call(project, "question", "unresolved", "Q1", "--reason", "no record left")
                _code, result = self.run_json(name, project)
                self.assertNotIn(result["values"].get("REASON"), ("internal-error", "usage"), result)
                self.assertIn("data", result, f"{name}: {result}")
                self.assertTrue(result["data"], name)

    def call(self, project, *argv):
        out = io.StringIO()
        code = cli.main([*argv, "--json"], stdout=out, environ=self.env, cwd=project, stdin=io.StringIO())
        self.assertEqual(code, 0, out.getvalue())

    def test_the_exempt_commands_are_few(self):
        self.assertEqual(EXEMPT - {c.name for c in COMMANDS if not c.engine}, set())


if __name__ == "__main__":
    unittest.main()
