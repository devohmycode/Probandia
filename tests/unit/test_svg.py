"""The SVG charts stay well-formed XML whatever a name holds (T159)."""
import unittest
import xml.etree.ElementTree as ET

from probandia import svg, trees

GIVEN = 'Louis "le Grand"'


def persons():
    def person(pid, given, father=None, year="1802"):
        return {"id": pid, "names": {"given": given, "surname": "HUGO"}, "sex": "M", "living": False,
                "parents": {"father": father, "mother": None}, "spouses": [],
                "facts": [{"id": f"{pid}.birth", "type": "birth", "status": "record",
                           "date": {"value": year, "qualifier": "exact"}}]}

    return [person("louis-hugo-1760", GIVEN, year="1760"),
            person("leopold-hugo-1773", "Léopold <dit> & \"Brutus\"", "louis-hugo-1760", "1773"),
            person("victor-hugo-1802", GIVEN, "leopold-hugo-1773")]


class Quotes(unittest.TestCase):
    def setUp(self):
        self.tree = trees.Tree(persons(), living=set())

    def test_ancestors_and_descendants_parse(self):
        for chart in (svg.ancestors(self.tree, "victor-hugo-1802"), svg.descendants(self.tree, "louis-hugo-1760")):
            root = ET.fromstring(chart)
            texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
            self.assertIn(GIVEN + " HUGO", texts)     # read back as written
            self.assertIn('aria-label', chart)

    def test_attributes_escape_the_quote(self):
        self.assertEqual(svg.escape('a "b" <c> & d'), "a &quot;b&quot; &lt;c&gt; &amp; d")


if __name__ == "__main__":
    unittest.main()
