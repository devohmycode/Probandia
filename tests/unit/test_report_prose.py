"""Prose that promises more than the data: ``render`` warns (version-1.0.0 T252)."""
import glob
import os
import unittest

from probandia import events
from probandia.indexes import FamilyIndexes
from probandia.report import prose
from tests import ROOT
from tests.unit.test_report import ReportProject, ev, section


class Sentences(unittest.TestCase):
    def check(self, body, facts=(), years_of=None):
        return [(kind, text) for _sid, kind, text in prose.check_section("S1", body, facts, years_of)]

    def test_a_source_or_evidence_called_primary_warns_once_per_section(self):
        body = ("Les sources primaires confirment. Une source secondaire aussi. La preuve primaire est là.\n\n"
                "A primary source agrees; so do secondary sources and the primary evidence.")
        self.assertEqual(self.check(body), [("classed", "sources primaires, source secondaire, preuve primaire, "
                                                        "primary source, secondary sources, primary evidence")])
        self.assertEqual(self.check("L'information primaire de l'acte, une source originale."), [])
        self.assertEqual(self.check("Le mot `source primaire` est banni."), [])

    def test_a_dated_sentence_without_a_fact_warns_once_per_sentence(self):
        body = ("Henri naît en 1870 à Bourg-Vert. Son père est cultivateur. Il épouse Jeanne le 3 mai.\n\n"
                "- 1802 : naissance\n- 1870 : mariage [[f:h.marriage]]\n\n"
                "Le 26/02/1802, un baptême. Il meurt en l'an VIII. Victor naît le 26 février 1802 à Besançon "
                "[[f:victor-hugo-1802.birth]].")
        self.assertEqual(self.check(body), [
            ("uncited", "Henri naît en 1870 à Bourg-Vert."), ("uncited", "Il épouse Jeanne le 3 mai."),
            ("uncited", "- 1802 : naissance"), ("uncited", "Le 26/02/1802, un baptême."),
            ("uncited", "Il meurt en l'an VIII.")])

    def test_what_is_not_a_claim_is_not_counted(self):
        for body in (
                # numbers inside references, sections that cite their facts
                "Louis naît [[f:louis-marchand-1898.birth]]. Fils de [[p:henri-marchand-1870]].",
                "Henri naît en 1870 (voir [[s:01JA000000000000000000SEC1]]).",
                # a source's title, a quotation, a link's address, code
                "Voir *Registres paroissiaux 1790-1802* aux archives.",
                "Le curé note « né le trois mai 1802 » en marge.",
                "L'[acte](https://example.org/ad/1802/vue-12) est en ligne.",
                "La commande `tables 1802` répond.\n\n```\n1870\n```",
                # numbers that are not years
                "Le village compte 1500 habitants. Voir la page 1802 et la vue 1234, le n° 1803.",
                "Le moteur 0.9.41 lit 2000 octets.",
                # initials and abbreviations do not cut a sentence from its fact
                "Né le 1er janv. 1802 à St. Martin [[f:x.birth]].",
                "J. Martin, né en 1802 [[f:j-martin.birth]], meurt jeune."):
            with self.subTest(body=body):
                self.assertEqual(self.check(body), [])

    def test_a_year_of_a_fact_the_section_lists_or_cites_is_cited(self):
        years = {"louise-perrin-1818.death": {1880}, "h.birth": {1870}}
        self.assertEqual(self.check("Louise meurt en 1880.", ["louise-perrin-1818.death"], years), [])
        # cited in another sentence of the section
        self.assertEqual(self.check("Henri naît [[f:h.birth]]. En 1870, son père a trente ans.", (), years), [])
        # a year no fact holds, or a day the year does not tell
        self.assertEqual(self.check("Louise meurt en 1881.", ["louise-perrin-1818.death"], years),
                         [("uncited", "Louise meurt en 1881.")])
        self.assertEqual(self.check("Louise meurt le 3 mai 1880.", ["louise-perrin-1818.death"], years), [])
        self.assertEqual(self.check("Louise meurt un 3 mai, en 1880.", ["louise-perrin-1818.death"], years),
                         [("uncited", "Louise meurt un 3 mai, en 1880.")])

    def test_a_long_sentence_is_cut_on_a_word(self):
        found = self.check("Henri naît en 1870 à Bourg-Vert, " + "dans la maison de ses grands-parents " * 4 + ".")
        self.assertEqual(len(found), 1)
        self.assertLessEqual(len(found[0][1]), prose.EXCERPT + 1)
        self.assertTrue(found[0][1].endswith("…"))

    def test_the_samples_trigger_nothing(self):
        researches = glob.glob(os.path.join(ROOT, "tests", "sample-project*", "families", "*", "research", "*"))
        self.assertGreaterEqual(len(researches), 3)
        for folder in researches:
            with self.subTest(research=os.path.basename(folder)):
                project = folder.split(os.sep + "families" + os.sep)[0]
                family = folder.split(os.sep + "families" + os.sep)[1].split(os.sep)[0]
                persons = FamilyIndexes(project, family).load_all()["persons"].get("persons", [])
                self.assertEqual(prose.check(events.read(os.path.join(folder, "events.jsonl")), persons), [])


class Render(ReportProject):
    def append(self, *evs):
        events.append(self.log, list(evs))

    def lines(self, out):
        return out.splitlines()

    def call(self, *argv, env=None):
        return super().call(*argv, env=dict({"PROBANDIA_LANGUAGE": "en"}, **(env or {})))

    def test_the_fixture_renders_without_a_warning(self):
        code, out = self.call("render", "--formats", "md")
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=OK", out)
        self.assertNotIn("PROSE=", out)

    def test_render_warns_with_a_line_per_section_and_per_sentence(self):
        self.append(ev(20, "section.added", section(20, "Le baptême", "La source primaire le dit. Victor est "
                                                    "baptisé en 1802. Son parrain signe.", kind="chapter"), 2))
        code, out = self.call("render", "--formats", "md")
        self.assertEqual(code, 0, out)
        lines = self.lines(out)
        self.assertEqual(lines[0], "STATUS=WARN")
        self.assertIn("REASON=prose-claims", lines)
        self.assertIn("PROSE=2", lines)
        sid = section(20, "", "")["section"]["id"]
        self.assertIn(f"- CLAIM={sid} classed: source primaire", lines)
        self.assertIn(f"- CLAIM={sid} uncited: Victor est baptisé en 1802.", lines)
        # after the files, which a cut output must keep
        self.assertLess(max(i for i, x in enumerate(lines) if x.startswith("- FILE=")),
                        min(i for i, x in enumerate(lines) if x.startswith("- CLAIM=")))

    def test_an_unresolved_reference_keeps_its_reason(self):
        self.append(ev(20, "section.added", section(20, "Le baptême", "Baptisé en 1802. Voir [[s:01NOWHERE]].",
                                                    kind="chapter"), 2))
        code, out = self.call("render", "--formats", "md")
        lines = self.lines(out)
        self.assertEqual(lines[0], "STATUS=WARN")
        self.assertIn("REASON=unresolved-references", lines)
        self.assertIn("UNRESOLVED=1", lines)
        self.assertIn("PROSE=1", lines)

    def test_ten_claims_at_most_and_the_count_of_the_rest(self):
        body = " ".join(f"Un acte de {1800 + n}." for n in range(13))
        self.append(ev(20, "section.added", section(20, "Les actes", body, kind="chapter"), 2))
        code, out = self.call("render", "--formats", "md")
        lines = self.lines(out)
        self.assertIn("PROSE=13", lines)
        self.assertEqual(len([x for x in lines if x.startswith("- CLAIM=")]), 10)
        self.assertEqual(lines[-1], "- 3 more claims to check in the sections")

    def test_a_workshop_import_is_not_the_agent_prose(self):
        actor = {"harness": "cli", "agent": "import"}
        imported = ev(20, "section.added", section(20, "Rapport", "Victor naît en 1802.", kind="chapter"), 2)
        imported["actor"] = actor
        self.append(imported)
        self.assertEqual(self.call("render", "--formats", "md")[1].splitlines()[0], "STATUS=OK")
        # rewritten in a pass, it is
        self.append(ev(21, "section.replaced", {"section": section(20, "", "")["section"]["id"],
                                                "body_md": "Victor naît en 1802 à Besançon.", "reason": "relu"}, 2))
        self.assertIn("PROSE=1", self.call("render", "--formats", "md")[1].splitlines())


if __name__ == "__main__":
    unittest.main()
