"""T116: board --json, the shared view of the board (cli.md § 7.2, P1-T1 of claude-code-mod.md)."""
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, doctor, i18n
from probandia.cli import board_cmd
from probandia.ledger import Ledger
from tests import ROOT
from tests.unit.test_human import golden

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)
RESEARCH = "2026-09-01-ancestors-of-louis-marchand"


class Board(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude")}
        for patcher in (mock.patch.object(board_cmd, "_ledger", lambda project, cat, environ: Ledger(
                            project, cat, clock=lambda: NOW, environ=environ)),
                        mock.patch.object(doctor, "catalogue_ages", return_value=[("serpapi", 12)])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def board(self, *argv, cwd=None):
        out = io.StringIO()
        code = cli.main(["board", *argv, "--json"], stdout=out, environ=self.env, cwd=cwd or self.dir)
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def test_reference_on_the_sample_project(self):
        text = self.board()
        shown = json.loads(text)
        shown["values"]["VERSION"] = "<version>"
        golden(self, "board", json.dumps(shown, ensure_ascii=False, indent=1) + "\n",
               folder=os.path.join(ROOT, "tests", "golden"), ext=".json")
        self.assertLess(len(text.encode("utf-8")), 4096)
        focus = json.loads(text)["data"]["research"][0]
        self.assertEqual(focus["research"], RESEARCH)
        for field in ("steps", "native", "searches", "pending", "failed_rules"):
            self.assertIn(field, focus)
        self.assertLessEqual(len(focus["searches"]), 3)
        self.assertTrue(json.loads(text)["data"]["accounts"])

    def test_a_research_named_and_outside_a_project(self):
        self.assertEqual(json.loads(self.board(RESEARCH[:10]))["values"]["RESEARCH"], RESEARCH)
        out = json.loads(self.board(cwd=self.tmp.name))
        self.assertEqual((out["values"]["PROJECT"], out["data"]["research"]), ("none", []))


if __name__ == "__main__":
    unittest.main()
