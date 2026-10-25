"""T112: report open, report show, report render and the -r shortcut (cli.md 5.1.4, 5.9.1 to 5.9.3)."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from probandia import cli, i18n
from tests import ROOT

RESEARCH = "2026-09-01-ancestors-of-louis-marchand"


class Report(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "PROBANDIA_PAGER": "none"}
        self.research = os.path.join(self.dir, "families", "marchand", "research", RESEARCH)
        self.html = os.path.join(self.research, "report", "report.html")
        self.opened = []
        # the opening is simulated, whatever the system: Windows, macOS (open) or Linux (xdg-open)
        for patcher in (mock.patch.object(os, "startfile", self.opened.append, create=True),
                        mock.patch.object(subprocess, "Popen", lambda argv, **k: self.opened.append(argv[-1]))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main([*argv, "--json"], stdout=out, environ=self.env, cwd=self.dir, stdin=io.StringIO())
        self.assertEqual(code, 0, out.getvalue())
        return json.loads(out.getvalue())

    def age(self, path, seconds):
        t = os.path.getmtime(os.path.join(self.research, "events.jsonl")) + seconds
        os.utime(path, (t, t))

    def test_open_renders_a_report_older_than_the_log_then_opens_it(self):
        self.call("render", RESEARCH, "--formats", "md,html")
        self.age(self.html, -60)
        before = os.path.getmtime(self.html)
        out = self.call("report", "open", RESEARCH)
        self.assertEqual(out["values"]["RENDERED"], True)
        self.assertGreater(os.path.getmtime(self.html), before)
        self.assertEqual([os.path.normcase(p) for p in self.opened], [os.path.normcase(self.html)])
        self.assertEqual(out["data"]["files"][0]["file"], f"families/marchand/research/{RESEARCH}/report/report.html")

    def test_open_keeps_a_report_up_to_date(self):
        self.call("render", RESEARCH, "--formats", "md,html")
        self.age(self.html, 60)
        before = os.path.getmtime(self.html)
        out = self.call("report", "open", RESEARCH)
        self.assertEqual(out["values"]["RENDERED"], False)
        self.assertEqual(os.path.getmtime(self.html), before)
        self.assertEqual(len(self.opened), 1)

    def test_the_shortcut_is_report_open(self):
        self.call("render", RESEARCH, "--formats", "md,html")
        self.age(self.html, 60)
        self.assertEqual(self.call("-r", RESEARCH), self.call("report", "open", RESEARCH))
        self.assertEqual(self.call("--report", RESEARCH), self.call("report", "open", RESEARCH))

    def test_show_prints_the_markdown_at_a_terminal(self):
        out = io.StringIO()
        code = cli.main(["report", "show", RESEARCH, "--output-format", "human"], stdout=out, environ=self.env,
                        cwd=self.dir, stdin=io.StringIO())
        self.assertEqual(code, 0)
        with open(os.path.join(self.research, "report", "report.md"), encoding="utf-8") as fh:
            self.assertEqual(out.getvalue(), fh.read())
        self.assertEqual(self.opened, [])

    def test_render_is_the_engine_render(self):
        out = self.call("report", "render", RESEARCH)
        self.assertEqual(out["values"]["RESEARCH"], RESEARCH)
        self.assertTrue(os.path.isfile(os.path.join(self.research, "report", "report.json")))

    def test_the_views_of_the_acts(self):
        # T-08: the view of an act that proves a fact goes with the report: a file of views/ (the default),
        # data: in the page, or nothing; a view whose rights are not free is named, never copied
        family = os.path.join(self.dir, "families", "marchand")
        view = os.path.join(family, "evidence", "images", "bourg-vert-1898-57.jpg")
        os.makedirs(os.path.dirname(view), exist_ok=True)
        with open(view, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0 a view of the act")   # not an image Pillow reads: copied as it is
        views = os.path.join(self.research, "report", "views")
        out = self.call("render", RESEARCH, "--formats", "html")
        self.assertEqual(out["values"]["TEMPLATE"], "habillage")
        self.assertEqual(out["values"]["VIEWS"], 1)
        self.assertEqual(os.listdir(views), ["bourg-vert-1898-57.jpg"])
        with open(self.html, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn('<img src="views/bourg-vert-1898-57.jpg"', page)
        self.assertIn("<h3>Vues des actes</h3>", page)   # the research is in French
        self.call("config", "set", "report.images", "inline")
        out = self.call("render", RESEARCH, "--formats", "html")
        self.assertNotIn("VIEWS", out["values"])
        self.assertFalse(os.path.exists(views))   # the files of the last render are gone
        with open(self.html, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn('<img src="data:image/jpeg;base64,', page)
        self.assertLessEqual(len(page.encode("utf-8")), 1024 * 1024)
        self.call("config", "set", "report.images", "off")
        self.call("render", RESEARCH, "--formats", "html")
        with open(self.html, encoding="utf-8") as fh:
            self.assertNotIn("act-view", fh.read())

    def test_a_view_whose_rights_are_not_free_is_named_never_copied(self):
        from probandia.util import yamlio

        path = os.path.join(self.dir, "families", "marchand", "index", "sources.yaml")
        doc = yamlio.load(path)
        doc["sources"][0]["rights"] = "restricted"
        yamlio.dump(path, doc)
        out = self.call("render", RESEARCH, "--formats", "html")
        self.assertNotIn("VIEWS", out["values"])
        with open(self.html, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("Vue non reproduite, ses droits n&#x27;en permettent pas la copie : "
                      "evidence/images/bourg-vert-1898-57.jpg", page)
        self.assertNotIn("<img", page)

    def test_completion_knows_the_shortcut(self):
        from probandia.cli.completion import candidates

        self.assertIn("--formats", candidates(["-r", "--f"], self.env, self.dir))
        self.assertEqual(candidates(["report", "o"], self.env, self.dir), ["open"])


if __name__ == "__main__":
    unittest.main()
