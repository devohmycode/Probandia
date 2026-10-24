"""``tree.html``: a name cannot close the JSON block that carries it (T143); the tree usable at the keyboard,
and the charts named in the report's language (T123, PRD N-10).

The behaviour in a browser was checked by hand with axe-core 4.14.0 and Chromium (see the commit of
T123): every card reached by Tab, the arrows moving the focus, no violation on report.html nor tree.html."""
import html.parser
import json
import os
import re
import unittest

from probandia import svg, treeview, trees
from probandia.i18n import Translator
from probandia.report import labels as L
from tests.unit.test_trees_exports import TODAY, Project, golden, tree_persons

NAME = "Victor</SCRIPT><img src=x onerror=alert(1)><!--"


def persons(given):
    return [{"id": "victor-hugo-1802", "names": {"given": given, "surname": "HUGO"}, "sex": "M", "living": False,
             "parents": {"father": "leopold-hugo-1773", "mother": None}, "spouses": [],
             "facts": [{"id": "victor-hugo-1802.birth", "type": "birth", "status": "record",
                        "date": {"value": "1802-02-26", "qualifier": "exact"}}]},
            {"id": "leopold-hugo-1773", "names": {"given": "Léopold</script >", "surname": "HUGO"}, "sex": "M",
             "living": False, "parents": {}, "spouses": [], "facts": []}]


class Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.blocks, self.inside = [], [], None

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "script":
            self.inside = dict(attrs).get("id") or ""

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = None

    def handle_data(self, data):
        if self.inside == "tree-data":
            self.blocks.append(data)


class InlineJson(unittest.TestCase):
    def page(self, given):
        tree = trees.Tree(persons(given), living=set())
        return treeview.html_page(tree, "victor-hugo-1802", Translator("en"), "en")

    def test_a_name_with_a_closing_script_tag(self):
        page = self.page(NAME)
        start = page.index('<script type="application/json" id="tree-data">')
        block = page[start:page.index("</script>", start)]
        self.assertFalse(re.search(r"</script", block[1:], re.I), block)
        self.assertNotIn("<!--", block)
        parser = Tags()
        parser.feed(page)
        parser.close()
        self.assertNotIn("img", parser.tags)
        self.assertEqual(parser.tags.count("script"), 4)          # the data, d3, family-chart, the init
        data = json.loads("".join(parser.blocks))
        names = {p["id"]: p["data"]["label"] for p in data["people"]}
        self.assertEqual(names["victor-hugo-1802"], NAME + " HUGO")  # the name intact once read back

    def test_an_ordinary_name_is_unchanged(self):
        self.assertIn('"label": "Victor HUGO"', self.page("Victor"))



class Keyboard(unittest.TestCase):
    def setUp(self):
        self.tree = trees.Tree(tree_persons(), today=TODAY)
        self.page = treeview.html_page(self.tree, "victor-hugo-1802", Translator("en"))

    def script(self):
        return re.findall(r"<script>(.*?)</script>", self.page, re.S)[-1]

    def test_every_card_is_reached_by_tab(self):
        js = self.script()
        self.assertIn('querySelectorAll(".pb-card")', js)   # each card of the chart…
        self.assertIn("card.tabIndex = 0", js)               # …in the order of Tab
        self.assertIn('setAttribute("aria-label"', js)
        self.assertIn("new MutationObserver(label)", js)      # and those family-chart draws after a click

    def test_the_arrows_move_the_focus(self):
        js = self.script()
        self.assertIn('addEventListener("keydown"', js)
        for key in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"):
            self.assertIn(key, js)
        self.assertIn("next.focus()", js)
        self.assertIn('e.key === "Enter"', js)

    def test_the_focus_is_visible_and_the_page_has_its_landmarks(self):
        self.assertRegex(self.page, r"\[data-pb-card\]:focus-visible \.pb-card \{ outline: 3px solid")
        self.assertIn("<main><div id=\"FamilyChart\"", self.page)
        self.assertIn('aria-describedby="tree-help"', self.page)


class ChartLabels(Project):
    def test_french_labels_of_the_charts(self):
        t = Translator("fr")
        tree = trees.Tree(tree_persons(), today=TODAY)
        anc = svg.ancestors(tree, "victor-hugo-1802", 4, t(L.LIVING_PERSON), t(L.ANCESTORS_OF))
        desc = svg.descendants(tree, "nicolas-hugot-1850", 4, t(L.LIVING_PERSON), t(L.DESCENDANTS_OF))
        self.assertEqual(anc, golden("ancestors-fr.svg", anc))
        self.assertEqual(desc, golden("descendants-fr.svg", desc))
        self.assertIn('aria-label="Ascendance de Victor HUGO"', anc)
        self.assertIn('aria-label="Descendance de Nicolas HUGOT"', desc)

    def test_the_tree_command_in_french(self):
        self.use_tree()
        code, out = self.call("-l", "fr", "tree", "--root", "victor-hugo-1802")
        self.assertEqual(code, 0, out)
        folder = os.path.join(self.family, "trees")
        for name, word in (("ancestors.svg", "Ascendance de "), ("descendants.svg", "Descendance de "),
                           ("tree.html", "Ascendance de ")):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                self.assertIn(f'aria-label="{word}', fh.read(), name)


if __name__ == "__main__":
    unittest.main()
