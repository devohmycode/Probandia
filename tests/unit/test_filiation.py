"""T250: what a filiation rests on, in GEDCOM and in the trees; and no person is their own ancestor."""
import datetime
import os
import unittest

from probandia import gedcom, svg, trees
from probandia.proposals import check_ancestry
from probandia.util import yamlio
from tests.unit.test_data_layer import Project

TODAY = datetime.date(2026, 10, 1)


def person(pid, father=None, mother=None, births=(), sex="M"):
    """A dead person of the 1800s, with birth or baptism facts given as (type, status)."""
    return {"id": pid, "names": {"given": pid.split("-")[0].title(), "surname": "MARTIN"}, "sex": sex,
            "living": False, "parents": {"father": father, "mother": mother}, "spouses": [],
            "facts": [{"id": f"{pid}.{kind}" + (f".{n}" if n else ""), "type": kind, "status": status,
                       "date": {"value": "1820"}} for n, (kind, status) in enumerate(births)]}


FAMILY = [person("pierre-martin-1790"), person("marie-durand-1792", sex="F"),
          person("jean-martin-1820", "pierre-martin-1790", "marie-durand-1792", [("birth", "record")]),
          person("luc-martin-1822", "pierre-martin-1790", "marie-durand-1792", [("baptism", "index")]),
          person("paul-martin-1824", "pierre-martin-1790", "marie-durand-1792", [("birth", "hypothesis")]),
          person("noel-martin-1826", "pierre-martin-1790", "marie-durand-1792"),
          person("remi-martin-1828", "pierre-martin-1790", "marie-durand-1792", [("birth", "refuted")]),
          person("eloi-martin-1830", "pierre-martin-1790", "marie-durand-1792",
                 [("birth", "refuted"), ("baptism", "record")])]


def famc(text, pid, persons=FAMILY):
    """The lines under the FAMC of a person's INDI record."""
    roots = gedcom.parse(text)
    xref = gedcom.Export(persons, [], today=TODAY).indi[pid]
    indi = next(r for r in roots if r.tag == "INDI" and r.xref == xref)
    node = indi.first("FAMC")
    return {c.tag: c.value for c in node.children} if node is not None else None


class Gedcom(unittest.TestCase):
    def test_gedcom7_qualifies_the_link(self):
        text = gedcom.Export(FAMILY, [], today=TODAY, version=7).text()
        self.assertEqual(famc(text, "jean-martin-1820"), {"PEDI": "BIRTH", "STAT": "PROVEN"})
        self.assertEqual(famc(text, "luc-martin-1822"), {"PEDI": "BIRTH"})   # an index: no opinion on the link
        self.assertEqual(famc(text, "paul-martin-1824"), {"STAT": "CHALLENGED"})
        self.assertEqual(famc(text, "noel-martin-1826"), {})   # deduced: no birth fact founds it
        self.assertEqual(famc(text, "remi-martin-1828"), {"STAT": "DISPROVEN"})
        self.assertEqual(famc(text, "eloi-martin-1830"), {"PEDI": "BIRTH", "STAT": "PROVEN"})   # the strongest
        self.assertIsNone(famc(text, "pierre-martin-1790"))
        self.assertIn("1 FAMC @F1@\n2 PEDI BIRTH\n2 STAT PROVEN\n", text)

    def test_gedcom551_has_pedi_only(self):
        text = gedcom.Export(FAMILY, [], today=TODAY, version=5).text()
        self.assertEqual(famc(text, "jean-martin-1820"), {"PEDI": "birth"})
        self.assertEqual(famc(text, "paul-martin-1824"), {})
        self.assertNotIn("STAT", text)

    def test_a_masked_person_gets_no_qualification(self):
        living = [dict(person("zoe-martin-1990", "jean-martin-1820", None, [("birth", "record")]), living=True)]
        text = gedcom.Export(FAMILY + living, [], today=TODAY, version=7).text()
        self.assertEqual(famc(text, "zoe-martin-1990", FAMILY + living), {})


class Trees(unittest.TestCase):
    def setUp(self):
        self.tree = trees.Tree(FAMILY, today=TODAY)

    def test_a_link_without_a_birth_fact_is_dotted(self):
        self.assertEqual(self.tree.link("noel-martin-1826"), "deduced")
        self.assertEqual(self.tree.link("jean-martin-1820"), "record")
        self.assertEqual(self.tree.link("eloi-martin-1830"), "record")   # its baptism holds, the birth refuted
        block = trees.mermaid_block(self.tree, list(self.tree.persons))
        self.assertRegex(block, r"U_\d+ -\.-> P_noel_martin_1826")
        self.assertRegex(block, r"U_\d+ -\.-> P_paul_martin_1824")
        self.assertRegex(block, r"U_\d+ --> P_jean_martin_1820")
        self.assertRegex(block, r"U_\d+ --> P_luc_martin_1822")
        edges = trees.data(self.tree, list(self.tree.persons))["edges"]
        self.assertIn({"from": "pierre-martin-1790", "to": "noel-martin-1826", "role": "father", "link": "deduced"},
                      edges)

    def test_the_charts_draw_it_dotted(self):
        down = svg.descendants(self.tree, "pierre-martin-1790", 2)
        self.assertEqual(down.count('class="link hypothesis"'), 2)   # Paul's hypothesis and Noël's deduced link
        alone = trees.Tree([person("pierre-martin-1790"), person("noel-martin-1826", "pierre-martin-1790")])
        self.assertIn('class="link hypothesis"', svg.ancestors(alone, "noel-martin-1826", 2))


class Ancestry(unittest.TestCase):
    def test_a_cycle_is_found_from_the_person_touched(self):
        family = [person("a-1800", "b-1780"), person("b-1780", "c-1760"), person("c-1760", "a-1800")]
        self.assertEqual(check_ancestry(family, {"b-1780"}),
                         ["b-1780 would be their own ancestor: b-1780 → c-1760 → a-1800 → b-1780"])
        self.assertEqual(len(check_ancestry(family, {"a-1800", "b-1780", "c-1760"})), 1)   # one cycle, said once
        self.assertEqual(check_ancestry([person("d-1800", "d-1800")], {"d-1800"}),
                         ["d-1800 would be their own ancestor: d-1800 → d-1800"])
        self.assertEqual(check_ancestry(FAMILY, {p["id"] for p in FAMILY}), [])


class ApplyRefusesACycle(Project):
    def test_apply_refuses_a_person_made_their_own_ancestor(self):
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))["persons"]
        victor = next(p for p in persons if p["id"] == "victor-hugo-1802")
        before = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))
        son = {"id": "charles-hugo-1826", "names": {"given": "Charles", "surname": "HUGO"}, "sex": "M",
               "living": False, "parents": {"father": "victor-hugo-1802", "mother": None}, "spouses": [], "facts": []}
        wrong = dict(victor, facts=[], parents={"father": "charles-hugo-1826", "mother": None})
        (code, out), _doc = self.propose_and_apply(persons=[son, wrong])
        self.assertEqual(code, 1, out)
        self.assertIn("- charles-hugo-1826 would be their own ancestor: charles-hugo-1826 → victor-hugo-1802 → "
                      "charles-hugo-1826\n", out)
        self.assertEqual(yamlio.load(os.path.join(self.family, "index", "persons.yaml")), before)
        (code, out), _doc = self.propose_and_apply(persons=[son])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
