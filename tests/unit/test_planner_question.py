"""token-economy C1 to C3: what a question seeks, the facts it gives, its window and its places."""
import io
import os
import shutil
import tempfile
import unittest

from probandia import cli
from probandia.planner import detect_type, find_person, find_window, given_facts, question_places
from probandia.util import yamlio
from tests import ROOT

# a case of the bench's kind: a birth and a parentage sought, a dated and placed death given
CASE = ("Où et quand est né Jean de LA FONTAINE, mort le 13 avril 1695 à Paris, "
        "et qui étaient ses parents ?")


class SoughtAndGiven(unittest.TestCase):
    """C1: the event words of the facts given do not say what the question seeks."""

    def test_french_english_german(self):
        for question, qtype, fact in (
                (CASE, "parents", ("death", 1695, "1695-04-13", "Paris")),
                ("Où et quand est né Pierre LAFONTAINE, mort en 1876 ?", "birth", ("death", 1876, "1876", None)),
                ("Quand est mort Jean MARTIN, né vers 1803 à Nancy ?", "death", ("birth", 1803, "1803", "Nancy")),
                ("Where was John Smith born, who died on 3 March 1876 in Boston?", "birth",
                 ("death", 1876, "1876-03-03", "Boston")),
                ("Who were the parents of Victor Hugo, born about 1802 in Besançon?", "parents",
                 ("birth", 1802, "1802", "Besançon")),
                ("Wann und wo wurde Johann Müller geboren, der am 13. April 1695 in Hamburg starb?", "birth",
                 ("death", 1695, "1695-04-13", "Hamburg")),
                ("Wer waren die Eltern von Johann Müller, geboren 1850 in Köln?", "parents",
                 ("birth", 1850, "1850", "Köln"))):
            with self.subTest(question):
                self.assertEqual(detect_type(question), qtype)
                facts = given_facts(question)
                self.assertEqual(len(facts), 1, facts)
                self.assertEqual(tuple(facts[0][k] for k in ("type", "year", "date", "place")), fact)

    def test_two_facts_in_one_clause(self):
        facts = given_facts("Qui étaient les parents de Jean, né le 8 juillet 1621 à Château-Thierry et mort en 1695 à Paris ?")
        self.assertEqual([(f["type"], f["year"]) for f in facts], [("birth", 1621), ("death", 1695)])
        self.assertEqual([f["place"] for f in facts], ["Château-Thierry", "Paris"])
        self.assertEqual(facts[0]["date"], "1621-07-08")

    def test_the_year_of_the_event_sought_still_counts(self):
        self.assertEqual(detect_type("Quand est né Jean en 1621 ?"), "birth")
        self.assertEqual(detect_type("Wann ist er gestorben?"), "death")
        self.assertEqual(detect_type("Où habitait la famille en 1900 ?"), "residence")
        self.assertEqual(given_facts("Où habitait la famille en 1900 ?"), [])
        self.assertEqual(given_facts("Died aged 73 in 1695")[0]["age"], 73)

    def test_the_given_name_marie_is_no_marriage(self):
        # T224: "Victor Marie HUGO" made a death question a marriage one
        self.assertEqual(detect_type("Quand et où est mort Victor Marie HUGO, né à Besançon en 1802 ?"), "death")
        self.assertEqual(detect_type("Où est née Marie MARTIN ?"), "birth")
        self.assertEqual(detect_type("Quand Jean s'est-il marié avec Marie ?"), "marriage")

    def test_every_given_name(self):
        # T224: the subject was "Marie HUGO", the word before the surname alone
        family = {"name": "HUGO", "surnames": ["Hugo"]}
        for question, given in (("Quand et où est mort Victor Marie HUGO, né à Besançon ?", "Victor Marie"),
                                ("Quand Victor HUGO est-il mort ?", "Victor"), ("Où est né HUGO ?", ""),
                                ("Where was John Hugo born?", "John")):
            with self.subTest(question):
                self.assertEqual(find_person(question, family)[0], given)


class Window(unittest.TestCase):
    """C2: the window of the event sought, from the facts given."""

    def test_from_the_facts_given(self):
        for question, window in (
                (CASE, (1595, 1680, "anchor")),
                ("Où et quand est né Jean de LA FONTAINE, mort le 13 avril 1695 à l'âge de 73 ans ?", (1621, 1622, "anchor")),
                ("Where was John Smith born, who died aged 73 in 1695?", (1621, 1622, "anchor")),
                ("Where was John Smith born, who died about 1876?", (1771, 1866, "anchor")),
                ("Wann wurde Johann Müller geboren, der 1876 in Hamburg starb?", (1776, 1861, "anchor")),
                ("Quand s'est marié Jean MARTIN, né en 1803 ?", (1818, 1863, "anchor")),
                ("Quand est mort Jean MARTIN, né en 1803 ?", (1803, 1903, "anchor")),
                ("Who were the parents of Victor Hugo, born about 1802 in Besançon?", (1797, 1807, "about")),
                ("Quand est né Jean en 1621 ?", (1619, 1623, "exact")),
                ("Où habitait la famille en 1900 ?", (1898, 1902, "exact")),
                ("Qui étaient les enfants de Jean, mort en 1876 ?", (1874, 1878, "exact")),
                ("Où est né Jean ?", (1800, 1900, "family"))):
            with self.subTest(question):
                self.assertEqual(find_window(question, {"period": [1800, 1900]}), window)


class Places(unittest.TestCase):
    """C3: the places a question names, as departments, countries or communes of the COG."""

    def test_without_the_cog(self):
        self.assertEqual(question_places(CASE), ([("Paris", ["FR-75", "FR"])], []))
        self.assertEqual(question_places("mort à Valognes (Manche)"), ([("Valognes", ["FR-50", "FR"])], []))
        self.assertEqual(question_places("who stayed in Luxembourg in 1862"), ([("Luxembourg", ["LU"])], []))
        self.assertEqual(question_places("geboren 1850 in Köln"), ([], ["Köln"]))
        self.assertEqual(question_places("Quand est né Henri MARCHAND, et de qui ?"), ([], []))

    def test_with_the_cog(self):
        cog = os.path.join(ROOT, "tests", "fixtures", "cog")
        self.assertEqual(question_places("né à Besançon", cog)[0], [("Besançon", ["FR-25", "FR"])])
        self.assertEqual(question_places("né à Beaulieu", cog)[0], [("Beaulieu", ["FR"])])   # Ardèche or Cantal
        self.assertEqual(question_places("né à Beaulieu (Cantal)", cog)[0], [("Beaulieu", ["FR-15", "FR"])])
        self.assertEqual(question_places(CASE, cog)[0], [("Paris", ["FR-75", "FR"])])
        self.assertEqual(question_places("mort à Valognes (Manche)", cog)[0], [("Valognes", ["FR-50", "FR"])])
        self.assertEqual(question_places("mort à Nulle-Part en 1876", cog), ([], ["Nulle-Part"]))


class StudiedCase(unittest.TestCase):
    """The question of the bench's case, planned in a new family, offline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"),
                    "PROBANDIA_SESSION": "t", "SERPAPI_API_KEY": "k"}

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--output-format", "contract"], stdout=out, environ=dict(self.env),
                        cwd=self.dir, stdin=io.StringIO())
        return code, out.getvalue()

    def plan(self, question=CASE, *extra):
        code, out = self.call("new", question, "--family", "lafontaine", "--mode", "session")
        self.assertEqual(code, 0, out)
        self.rid = next(x for x in out.splitlines() if x.startswith("RESEARCH=")).split("=", 1)[1]
        code, out = self.call("plan", self.rid, *extra)
        details = next(x for x in out.splitlines() if x.startswith("DETAILS=")).split("=", 1)[1]
        return code, out, yamlio.load(os.path.join(self.dir, details))

    def test_type_and_anchor(self):
        code, out, doc = self.plan()
        self.assertEqual(code, 0, out)
        self.assertIn("TYPE=parents\n", out)
        self.assertIn("ANCHOR=death 1695 Paris\n", out)
        self.assertEqual(doc["axes"]["anchors"][0]["date"], "1695-04-13")
        self.assertEqual(doc["axes"]["record_types"], ["birth", "baptism", "marriage"])

    def test_window_from_the_death(self):
        code, out, doc = self.plan()
        # it covers 1621, the birth, and leaves out the years around the death, where the plan of 9 October 2026 looked
        self.assertIn("WINDOW=1595-1680\nWINDOW_BASIS=anchor\n", out)
        # matchID (deaths since 1970) is asked nothing for births and marriages
        self.assertNotIn("matchid", {c["engine"] for c in doc["calls"]})
        self.assertEqual({c["record_type"] for c in doc["removed"] if c["engine"] == "matchid"},
                         {"birth", "baptism", "marriage"})
        self.assertIn("- removed=matchid birth,baptism,marriage out-of-coverage 1970-2026\n", out)

    def test_coverage_of_type_and_place(self):
        # C5: within matchID's years, a birth is still not a death; Open Archives holds no French register
        code, out, doc = self.plan(CASE, "--window", "1940-1990")   # within every archive's years
        self.assertEqual(code, 0, out)
        self.assertNotIn("matchid", {c["engine"] for c in doc["calls"]})
        self.assertIn("- removed=matchid birth,baptism,marriage out-of-coverage types death\n", out)
        self.assertIn("- removed=openarchives birth,baptism,marriage out-of-coverage places NL,BE,DE\n", out)
        self.assertIn("gallica", {c["engine"] for c in doc["calls"]})   # press: no record type to miss

    def test_places(self):
        code, out, doc = self.plan()
        self.assertIn("PLACES=1\n", out)
        self.assertIn("PLACE_CODES=FR-75\n", out)
        self.assertIn("- places=Paris\n", out)
        self.assertNotIn("PLACES_UNKNOWN", out)
        self.assertIn("Lafontaine Paris", {c["query"] for c in doc["calls"]})

    def test_a_place_found_nowhere_is_said(self):
        code, out, doc = self.plan("Wann wurde Pierre LAFONTAINE geboren, der 1876 in Hamburg starb?")
        self.assertEqual(code, 0, out)
        self.assertIn("PLACES=0\n", out)
        self.assertIn("PLACES_UNKNOWN=Hamburg\n", out)
        self.assertIn("- insee: the COG files are not installed (places --update-cog)\n", out)
        self.assertEqual(doc["axes"]["places_unknown"], ["Hamburg"])

    def test_window_given(self):
        code, out, doc = self.plan(CASE, "--window", "1795-1810")
        self.assertEqual(code, 0, out)
        self.assertIn("WINDOW=1795-1810\nWINDOW_BASIS=argument\n", out)
        self.assertEqual(doc["axes"]["window"], {"from": 1795, "to": 1810, "basis": "argument"})
        code, out = self.call("plan", self.rid, "--window", "around 1800")
        self.assertEqual(code, 2, out)

    def test_new_runs_known_and_plan(self):
        # token-economy B1: the first two steps of the pass come with new, the detail in DETAILS
        code, out = self.call("new", CASE, "--family", "lafontaine", "--mode", "session")
        self.assertEqual(code, 0, out)
        for line in ("KNOWN_FACTS=0", "KNOWN_NEGATIVES_DUE=0", "TYPE=parents", "ANCHOR=death 1695 Paris",
                     "WINDOW=1595-1680", "WINDOW_BASIS=anchor", "PLACE_CODES=FR-75", "NATIVE_PARALLEL=3",
                     "- pass 1 is open; known and plan are done", "- places=Paris",
                     "- record_types=birth, baptism, marriage"):
            self.assertIn(line + "\n", out)
        self.assertIn("\n- names=Lafontaine, La Fontaine, Fontaine, ", out)   # T67: no need to open DETAILS for them
        self.assertNotIn("\nPLACES=", out)
        details = next(x for x in out.splitlines() if x.startswith("DETAILS=")).split("=", 1)[1]
        self.assertTrue(details.endswith("/work/new-1.txt"), details)
        with open(os.path.join(self.dir, details), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("NEGATIVES_DUE=0\n", text)
        self.assertIn("- names=Lafontaine, La Fontaine, Fontaine", text)
        self.assertIn("/work/plan-1.yaml\n", text)   # the plan itself, written as plan writes it
        rid = next(x for x in out.splitlines() if x.startswith("RESEARCH=")).split("=", 1)[1]
        with open(os.path.join(self.dir, "families", "lafontaine", "research", rid, "events.jsonl"), encoding="utf-8") as fh:
            self.assertIn('"plan.made"', fh.read())
        # in subagent mode the orchestrator runs them, in its own context
        code, out = self.call("new", "Who were the parents of Pierre LAFONTAINE?", "--family", "lafontaine",
                              "--mode", "subagent", "--harness", "cursor")
        self.assertEqual(code, 0, out)
        self.assertNotIn("TYPE=", out)
        self.assertIn("- pass 1 is open; next: known, then plan\n", out)


if __name__ == "__main__":
    unittest.main()
