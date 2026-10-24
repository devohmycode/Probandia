import ast
import io
import os
import sys
import unittest

from probandia import i18n
from probandia.cli import human
from probandia.cli.output import Result
from tests import ROOT

GOLDEN = os.path.join(ROOT, "tests", "golden", "human")


def golden(test, name, text, folder=GOLDEN, ext=".txt"):
    """Compares ``text`` with ``<folder>/<name><ext>``, by default ``tests/golden/human/<name>.txt``;
    PROBANDIA_UPDATE_GOLDEN rewrites it."""
    path = os.path.join(folder, name + ext)
    if os.environ.get("PROBANDIA_UPDATE_GOLDEN"):
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    with open(path, encoding="utf-8") as fh:
        expected = fh.read()
    if text != expected:
        # a mismatch seen once under load, never again by hand: keep what was rendered to compare it
        import tempfile

        kept = os.path.join(tempfile.gettempdir(), "probandia-golden", name + ext)
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        with open(kept, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        test.assertEqual(text, expected, f"rendered output kept in {kept}")


def sample():
    r = Result("WARN", {"PROVIDERS": 3, "KEYS_MISSING": 0, "SYNCED": True, "LOG": ""})
    r.line("the free quota of serper expires on 14 March 2027; nothing is paid beyond it, and the next "
           "provider of the same family takes over")
    r.data("provider", "serpapi ready left=199")
    r.details = "families/marchand/work/details/x.md"
    return r


class Render(unittest.TestCase):
    """Reference renderings, without colour (cli.md § 6.2)."""

    def setUp(self):
        i18n.activate("en")
        self.style = human.Style(color=False, width=72)

    def test_generic_result(self):
        golden(self, "generic", human.render(sample(), self.style))

    def test_table(self):
        r = Result("OK", {"PROVIDERS": 3})
        r.table("accounts", [
            {"provider": "SerpApi · Google", "left": "199", "pays for": "199 searches", "resets": "1 Nov"},
            {"provider": "Jina Reader", "left": "8,814,000", "pays for": "2,938 pages", "resets": "never"},
            {"provider": "Apify · search and read, a very long name that must be cut", "left": "4.19",
             "pays for": "761 searches or 1,676 pages", "resets": "1 Nov"},
        ])
        golden(self, "table", human.render(r, self.style))

    def test_plain_style(self):
        golden(self, "plain", human.render(sample(), human.Style(plain=True, width=72)))

    def test_bars(self):
        bars = [human.bar(f, self.style) for f in (0, 0.25, 0.796, 1, 1.5)]
        self.assertEqual(bars[0], "░" * 16)
        self.assertEqual(bars[2], "█" * 13 + "░" * 3)
        self.assertEqual(bars[3], bars[4])
        self.assertEqual(human.bar(0.5, human.Style(plain=True), 8), "####....")

    def test_colours(self):
        coloured = human.render(Result("FAIL"), human.Style(color=True))
        self.assertIn("\x1b[31m", coloured)
        self.assertNotIn("\x1b[", human.render(Result("FAIL"), human.Style(color=True, plain=True)))


class Colours(unittest.TestCase):
    """NO_COLOR, FORCE_COLOR and the terminal decide (no-color.org)."""

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    def test_no_color(self):
        self.assertFalse(human.style_for(self.Terminal(), {"NO_COLOR": "1"}).color)

    def test_force_color(self):
        self.assertTrue(human.style_for(io.StringIO(), {"FORCE_COLOR": "1"}).color)

    def test_not_a_terminal(self):
        self.assertFalse(human.style_for(io.StringIO(), {}).color)


class Pager(unittest.TestCase):
    """A readable output taller than the terminal goes through a pager, whole."""

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    def test_long_output_is_paged_whole(self):
        import tempfile
        from unittest import mock

        from probandia import cli
        with tempfile.TemporaryDirectory() as tmp:
            seen = os.path.join(tmp, "paged.txt")
            script = os.path.join(tmp, "pager.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(f"import sys\nopen({seen!r}, 'w', encoding='utf-8').write(sys.stdin.read())\n")
            env = {"PROBANDIA_PAGER": f'"{sys.executable}" "{script}"', "PROBANDIA_CONFIG_DIR": tmp}
            out = self.Terminal()
            with mock.patch.object(human, "terminal_height", return_value=3):
                code = cli.main(["variants", "Hugo"], stdout=out, environ=env, cwd=tmp)
            self.assertEqual(code, 0)
            self.assertEqual(out.getvalue(), "")
            with open(seen, encoding="utf-8") as fh:
                paged = fh.read()
        self.assertIn("form", paged)
        self.assertGreater(paged.count("\n"), 3)

    def test_paging_turned_off(self):
        tall = "line\n" * 500
        self.assertFalse(human.page_if_long(tall, self.Terminal(), {"PROBANDIA_PAGER": "none"}))
        self.assertIsNone(human.pager_command({"PROBANDIA_PAGER": ""}))

    def test_short_output_is_not_paged(self):
        self.assertFalse(human.page_if_long("one line\n", self.Terminal(), {"PROBANDIA_PAGER": "x"}))

    def test_builtin_pager_when_there_is_no_less(self):
        from unittest import mock

        with mock.patch.object(human.shutil, "which", return_value=None):
            self.assertEqual(human.pager_command({}), human.BUILTIN)   # never Windows' more
        with mock.patch.object(human.shutil, "which", return_value="/usr/bin/less"):
            self.assertEqual(human.pager_command({}), "less -R")

    def test_builtin_pager_shows_everything_screen_by_screen(self):
        text = "".join(f"ligne {i} ✓ ─ é\n" for i in range(1, 11))
        out = io.StringIO()
        keys = iter([" ", "\r", " ", " "])
        human.builtin_pager(text, out, key=lambda: next(keys), height=4)
        shown = out.getvalue()
        for i in range(1, 11):
            self.assertIn(f"ligne {i} ✓ ─ é\n", shown)
        self.assertEqual(shown.count("Space: next screen"), 3)   # 3 lines, then 3, then 1, then the last 3
        self.assertNotIn("-- S", shown.replace("Space", ""))

    def test_builtin_pager_stops_on_q(self):
        out = io.StringIO()
        human.builtin_pager("".join(f"l{i}\n" for i in range(20)), out, key=lambda: "q", height=5)
        self.assertIn("l3\n", out.getvalue())
        self.assertNotIn("l4\n", out.getvalue())

    def test_contract_keeps_its_cut(self):
        r = Result("OK", lines=[f"line {i}" for i in range(80)])
        self.assertEqual(r.render_text().count("\n"), 40)


class StandardLibraryOnly(unittest.TestCase):
    def test_imports(self):
        with open(human.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        modules = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        third_party = {m for m in modules if m not in sys.stdlib_module_names and m != "probandia"}
        self.assertEqual(third_party, set())


if __name__ == "__main__":
    unittest.main()
