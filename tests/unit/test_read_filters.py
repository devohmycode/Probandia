"""token-economy D1: read --links, --grep and --select, offline, on a list page."""
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, i18n
from probandia.reading import extract as E
from tests import ROOT

PAGE = os.path.join(ROOT, "tests", "fixtures", "lists", "registers.html")
URL = "https://archives.example.org/registres?commune=S"


def page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


class Helpers(unittest.TestCase):
    def test_links_by_text_or_address(self):
        found = E.links(page(), "valognes", URL)
        self.assertEqual(len(found), 3)
        self.assertEqual(found[1], ("Valognes, naissances 1803-1812",
                                    "https://archives.example.org/ark:/57115/val-1803-1812"))
        self.assertEqual([h for _t, h in E.links(page(), "tou-18")], ["/ark:/57115/tou-1806-1815"])

    def test_links_of_a_readers_markdown(self):
        self.assertEqual(E.links("See [Valognes 1803](https://x.org/s) and [other](https://x.org/o)", "valognes"),
                         [("Valognes 1803", "https://x.org/s")])

    def test_grep_keeps_one_line_of_context(self):
        text = "a\nb\nValognes 1803\nc\nd\ne\nf valognes\n"
        self.assertEqual(E.grep(text, "VALOGNES"), ["b", "Valognes 1803", "c", "…", "e", "f valognes"])

    def test_select_one_block(self):
        block = E.select(page(), "div.results")
        self.assertIn("Tourlaville, décès 1806-1815", block)
        self.assertNotIn("Mentions légales", block)
        self.assertEqual(E.select(page(), "#filters"), "A S L")
        self.assertEqual(E.select(page(), "footer").split("\n")[0], "Mentions légales Contact")
        self.assertEqual(E.select(page(), "table"), "")
        with self.assertRaises(ValueError):
            E.select(page(), "div > p")


class Command(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = os.path.join(tmp.name, "p")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "u")}

    def read(self, *args):
        from probandia.cli import reading_cmd
        from probandia.reading.ladder import ReadResult

        class Reader:
            def read(self, url, fresh=False, max_step=None):
                r = ReadResult(url)
                r.status, r.step, r.html = "ok", "extract", page()
                r.text = E.extract(r.html)[0]
                return r

        out = io.StringIO()
        with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work: Reader()):
            code = cli.main(["read", URL, *args], stdout=out, environ=dict(self.env), cwd=self.project)
        return code, out.getvalue()

    def test_links(self):
        code, out = self.read("--links", "Valognes")
        self.assertEqual(code, 0, out)
        self.assertIn("LINKS=3\n", out)
        self.assertIn("- link=Valognes, naissances 1803-1812 "
                      "https://archives.example.org/ark:/57115/val-1803-1812\n", out)
        self.assertNotIn("passage=", out)
        self.assertLess(len(out.splitlines()), 40)
        self.assertIn("DETAILS=", out)   # the whole page stays there

    def test_grep(self):
        code, out = self.read("--grep", "5 Mi")
        self.assertEqual(code, 0, out)
        self.assertIn("- line=Cote 5 Mi 1234 : Valognes, an XI - 1812.\n", out)
        self.assertLess(len(out.splitlines()), 40)

    def test_select(self):
        code, out = self.read("--select", "div.results")
        self.assertEqual(code, 0, out)
        self.assertIn("- line=Saint-Hilaire-du-Harcouët, naissances 1800-1810\n", out)
        self.assertNotIn("Mentions", out)
        self.assertLess(len(out.splitlines()), 40)

    def test_nothing_matches(self):
        code, out = self.read("--links", "Granville")
        self.assertIn("STATUS=WARN", out)
        self.assertIn("LINKS=0\n", out)


if __name__ == "__main__":
    unittest.main()
