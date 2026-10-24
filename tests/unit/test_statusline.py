"""T146: ``statusline`` and ``usage --short``, one line for a status bar, from the files only."""
import datetime
import io
import json
import os
import shutil
import socket
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

from probandia import cli, i18n
from probandia.cli import board_cmd, usage_cmd
from probandia.ledger import Ledger
from tests import ROOT

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)


def no_network(*args, **kwargs):
    raise AssertionError("statusline went to the network")


class Stdin(io.StringIO):
    def isatty(self):
        return False


class StatusLine(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.dir = os.path.join(self.tmp, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp, "u"), "PROBANDIA_DATA_DIR": os.path.join(self.tmp, "d"),
                    "CLAUDECODE": "1", "SERPAPI_API_KEY": "k-test", "SERPER_API_KEY": "k-test"}   # never sent
        for patcher in (mock.patch.object(board_cmd, "_ledger", lambda project, cat, environ: Ledger(
                            project, cat, clock=lambda: NOW, environ=environ)),
                        mock.patch.object(usage_cmd, "_now", lambda: NOW),
                        mock.patch.object(socket.socket, "connect", no_network),
                        mock.patch.object(socket, "create_connection", no_network),
                        mock.patch.object(urllib.request, "urlopen", no_network)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, argv, stdin="", cwd=None):
        out = io.StringIO()
        code = cli.main(argv, stdout=out, stdin=Stdin(stdin), environ=self.env, cwd=cwd or self.tmp)
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def claude_code(self, cwd):
        """What Claude Code sends the command of its statusLine setting (fields of its documentation)."""
        return json.dumps({"hook_event_name": "Status", "session_id": "s-146", "cwd": cwd,
                           "model": {"id": "claude-opus-4-1", "display_name": "Opus"},
                           "workspace": {"current_dir": cwd, "project_dir": cwd}, "version": "2.0.0"})

    def test_the_line_in_the_project_then_outside(self):
        line = self.run_cli(["statusline"], self.claude_code(os.path.join(self.dir, "families")))
        self.assertEqual(line, "Probandia · marchand · pass 2 ended · web 0/40 · Jina Reader 9.0 M\n")
        self.assertEqual(self.run_cli(["statusline"], self.claude_code(self.tmp)), "\n")

    def test_the_line_is_kept_while_its_files_do_not_change(self):
        from probandia.providers import accounts

        first = self.run_cli(["statusline"], cwd=self.dir)
        with mock.patch.object(accounts, "accounts", side_effect=AssertionError("read again")):
            self.assertEqual(self.run_cli(["statusline"], cwd=self.dir), first)   # the kept line
        log = os.path.join(self.dir, "families", "marchand", "research", "2026-09-01-ancestors-of-louis-marchand",
                           "events.jsonl")
        st = os.stat(log)
        os.utime(log, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))   # a write of the journal
        self.assertIsNone(board_cmd.cached_line("", self.env, self.dir))   # a file changed: read again
        self.assertEqual(self.run_cli(["statusline"], cwd=self.dir), first)
        self.assertEqual(board_cmd.cached_line("", self.env, self.dir) + "\n", first)
        with mock.patch("time.time", return_value=time.time() + board_cmd.STATUSLINE_TTL + 1):
            self.assertIsNone(board_cmd.cached_line("", self.env, self.dir))   # too old
        self.assertEqual(board_cmd.cached_line("", self.env, self.tmp), "")   # outside a project

    def test_json_carries_its_data(self):
        out = json.loads(self.run_cli(["statusline", "--json"], cwd=self.dir))
        self.assertTrue(out["values"]["LINE"].startswith("Probandia · marchand · pass 2"))
        self.assertEqual(out["data"]["line"][0]["research"], "2026-09-01-ancestors-of-louis-marchand")

    def test_usage_short(self):
        self.assertEqual(self.run_cli(["usage", "--short"], cwd=self.dir),
                         "Jina Reader 9.0 M · SerpApi 225 · Serper 2,250\n")

    def test_the_help_gives_the_setting(self):
        from probandia.cli.helptext import examples_epilog

        text = examples_epilog("statusline")   # under --help
        self.assertIn('"statusLine": {"type": "command", "command": "probandia statusline"}', text)

    def test_the_harness_does_not_count_it_as_an_engine_call(self):
        os.makedirs(os.path.join(self.dir, ".probandia", "locks"), exist_ok=True)
        with open(os.path.join(self.dir, ".probandia", "locks", "research-x.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.run_cli(["statusline"], cwd=self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".probandia", "calls.jsonl")))


if __name__ == "__main__":
    unittest.main()
