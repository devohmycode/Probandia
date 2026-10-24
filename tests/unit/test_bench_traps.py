"""The checks of an expected answer, scored on a played project without any session (version-1.0.0 T254)."""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia.errors import SchemaError
from probandia.util import yamlio
from probandia.util.schema import validate_document
from tests import ROOT
from tests.unit.test_bench_cases import CASE, FAMILY, fact, load_tool, make_case, person

HOMONYM_A = "jean-martin-1758"
HOMONYM_B = "jean-martin-1761"


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_tool("run")
        cls.cases = load_tool("cases")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = make_case(self.tmp.name)
        self.played = os.path.join(self.tmp.name, "played")
        shutil.copytree(os.path.join(self.folder, "solution"), self.played)

    def persons(self, change, side=None):
        path = os.path.join(side or self.played, "families", FAMILY, "index", "persons.yaml")
        doc = yamlio.load(path)
        change(doc["persons"])
        yamlio.dump(path, doc)

    def expect(self, *items, **case):
        doc = yamlio.load(os.path.join(self.folder, "case.yaml"))
        doc["expected"] = list(items)
        doc.update(case)
        yamlio.dump(os.path.join(self.folder, "case.yaml"), doc)

    def score(self, side=None):
        q = self.runner.load_case(self.folder, side or self.played)
        return self.runner.run_question(q)

    def states(self, side=None):
        return [(c["answer"], c["check"], c["state"]) for c in self.score(side)["checks"]]

    def birth(self, **extra):
        return dict({"label": "birth", "person": "Yves TANGUY", "type": "birth", "year": 1815}, **extra)

    def test_the_schema_takes_the_checks(self):
        doc = yamlio.load(os.path.join(self.folder, "case.yaml"))
        doc.update(observed=True, offline=True)
        doc["expected"] = [self.birth(date="1815-05-03", tolerance_days=1, uncertain_reading=False,
                                      axes={"source": "original", "information": "primary", "evidence": "direct"},
                                      confidence_max="probable"),
                           {"label": "other", "person": "Yves TANGUY", "type": "death", "distinct": "birth"}]
        validate_document("bench-case", doc, "case.yaml")
        for bad in ({"axes": {"evidence": "strong"}}, {"confidence_max": "certain"}, {"date": "3 mai 1815"},
                    {"distinct": "Not A Label"}, {"tolerance_days": -1}):
            with self.subTest(bad=bad), self.assertRaises(SchemaError):
                validate_document("bench-case", dict(doc, expected=[self.birth(**bad)]), "case.yaml")

    def test_the_date(self):
        self.expect(self.birth(date="1815-05-03"), self.birth(label="near", date="1815-05-05", tolerance_days=2),
                    self.birth(label="far", date="1815-05-13", tolerance_days=2))
        self.assertEqual(self.states(), [("birth", "date", "passed"), ("near", "date", "passed"),
                                         ("far", "date", "failed")])
        self.persons(lambda ps: ps[0]["facts"][0]["date"].update(value="1815"))   # the year only
        self.assertEqual(self.states()[0], ("birth", "date", "failed"))

    def test_the_axes(self):
        axes = {"source": "original", "information": "primary", "evidence": "direct"}
        self.expect(self.birth(axes=axes))
        self.assertEqual(self.states(), [("birth", "axes", "failed")])   # not classified
        self.persons(lambda ps: ps[0]["facts"][0].update(evidence=dict(axes, evidence="indirect")))
        self.assertEqual(self.states(), [("birth", "axes", "failed")])
        self.persons(lambda ps: ps[0]["facts"][0].update(evidence=axes))
        self.assertEqual(self.states(), [("birth", "axes", "passed")])

    def test_the_uncertain_reading(self):
        self.expect(self.birth(uncertain_reading=True))
        self.assertEqual(self.states(), [("birth", "uncertain_reading", "failed")])
        self.persons(lambda ps: ps[0]["facts"][0].update(uncertain_reading="line 2: 'trois'[?] or 'treize'"))
        self.assertEqual(self.states(), [("birth", "uncertain_reading", "passed")])

    def test_a_check_is_not_judged_when_the_answer_is_not_found(self):
        self.expect(self.birth(year=1830, date="1830-01-01", uncertain_reading=True))
        result = self.score()
        self.assertEqual(result["findings"], 0)
        self.assertEqual([c["state"] for c in result["checks"]], ["unjudged", "unjudged"])

    def test_the_ceiling_of_the_confidence(self):
        fid = "yves-tanguy-1815.birth"
        self.expect(self.birth(confidence_max="probable"))
        for found, state in (({}, "passed"), ({fid: ["probable"]}, "passed"), ({fid: ["proved"]}, "failed"),
                             ({fid: ["possible", "proved"]}, "failed")):
            with self.subTest(found=found), mock.patch.object(self.runner, "conclusions", return_value=found):
                self.assertEqual(self.states(), [("birth", "confidence_max", state)])

    def test_the_confidence_is_the_engine_own(self):
        # a research whose question is answered: its confidence, as render shows it
        gps = os.path.join(ROOT, "tests", "sample-project-gps")
        from probandia.proof.confidence import LEVELS
        from probandia.research import all_researches

        research = next(r for r in all_researches(gps) if r.id == "2026-09-04-birth-of-henri-marchand")
        found = self.runner.conclusions(gps, research)
        self.assertTrue(found)
        self.assertTrue(all(level in LEVELS for levels in found.values() for level in levels))

    def homonyms(self, merged=False):
        """Two Jean MARTIN, each married to a Marie; merged: the second marriage put on the first."""
        def marriage(pid, year, place, n=""):
            return fact(f"{pid}.marriage{n}", year, place={"id": None, "as_written": place})

        def change(ps):
            a = person(HOMONYM_A, "Jean", "MARTIN", [marriage(HOMONYM_A, "1784-02-10", "Bourg-Vert")])
            b = person(HOMONYM_B, "Jean", "MARTIN", [marriage(HOMONYM_B, "1787-06-02", "Saint-Aubry")])
            if merged:
                a["facts"].append(marriage(HOMONYM_A, "1787-06-02", "Saint-Aubry", ".2"))
                ps.append(a)
            else:
                ps.extend([a, b])
        self.persons(change)
        self.expect({"label": "jean-a", "person": "Jean MARTIN", "type": "marriage", "year": 1784,
                     "place": "Bourg-Vert"},
                    {"label": "jean-b", "person": "Jean MARTIN", "type": "marriage", "year": 1787,
                     "place": "Saint-Aubry", "distinct": "jean-a"})

    def test_two_homonyms_kept_apart(self):
        self.homonyms()
        result = self.score()
        self.assertEqual((result["findings"], result["false_ids"]), (2, []))   # the other's marriage is no error
        self.assertEqual(self.states(), [("jean-b", "distinct", "passed")])

    def test_two_homonyms_merged(self):
        self.homonyms(merged=True)
        self.assertEqual(self.score()["findings"], 2)
        self.assertEqual(self.states(), [("jean-b", "distinct", "failed")])

    def test_the_report_and_the_results(self):
        self.expect(self.birth(uncertain_reading=True, date="1815-05-03"), observed=True)
        out = io.StringIO()
        results = os.path.join(self.tmp.name, "results.json")
        with mock.patch("sys.stdout", out):
            code = self.runner.main(["--case", self.folder, "--played", self.played, "--out",
                                     os.path.join(self.tmp.name, "r.md"), "--json", results])
        self.assertEqual(code, 0, out.getvalue())
        text = out.getvalue()
        self.assertIn("## Checks of the expected answers", text)
        self.assertIn(f"| {CASE} (observed) | 1 | 2 | 2 | birth uncertain_reading |", text)
        self.assertIn("- checks of the expected answers: 1 passed, 2 judged, 2 asked", text)
        with open(results, encoding="utf-8") as fh:
            doc = validate_document("bench-result", json.load(fh), results)
        case = doc["cases"][0]
        self.assertTrue(case["observed"])
        self.assertEqual({k: case["metrics"][k] for k in ("checks", "checks_judged", "checks_passed")},
                         {"checks": 2, "checks_judged": 2, "checks_passed": 1})
        # side by side, the observed case and its checks
        compare = os.path.join(self.tmp.name, "compare.md")
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(self.runner.main(["--compare", results, results, "--out", compare]), 0)
        with open(compare, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(f"## {CASE} (observed)", text)
        self.assertIn("| checks passed | 1 [1–1] |", text)

    def test_no_check_no_new_row(self):
        out = io.StringIO()
        results = os.path.join(self.tmp.name, "results.json")
        with mock.patch("sys.stdout", out):
            self.runner.main(["--case", self.folder, "--out", os.path.join(self.tmp.name, "r.md"), "--json", results])
        self.assertNotIn("Checks of the expected answers", out.getvalue())
        with open(results, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertNotIn("checks", doc["cases"][0]["metrics"])
        self.assertNotIn("observed", doc["cases"][0])
        compare = os.path.join(self.tmp.name, "compare.md")
        with mock.patch("sys.stdout", io.StringIO()):
            self.runner.main(["--compare", results, "--out", compare])
        with open(compare, encoding="utf-8") as fh:
            self.assertNotIn("checks passed", fh.read())

    def test_admission_needs_the_checks_met_by_the_solution(self):
        solution = os.path.join(self.folder, "solution")
        self.expect(self.birth(uncertain_reading=True), {"person": "Yves TANGUY", "type": "death", "distinct": "nobody"})
        found = self.cases.check(self.folder, catalogue={})
        self.assertIn("solution/: birth fails its check uncertain_reading", found)
        self.assertIn("expected: distinct names nobody, which no answer is labelled", found)
        self.persons(lambda ps: ps[0]["facts"][0].update(uncertain_reading="line 2: 'trois'[?]"), solution)
        self.expect(self.birth(uncertain_reading=True), self.birth(year=1815))
        self.assertEqual(self.cases.check(self.folder, catalogue={}), ["expected: the label birth is given twice"])


TRAPS = os.path.join(ROOT, "bench", "public", "cases")


class TrapCases(unittest.TestCase):
    """The trap micro-cases of bench/public/cases: admitted, observed, their acts in project/, and they tell a
    sound play from a trapped one."""

    @classmethod
    def setUpClass(cls):
        cls.runner = load_tool("run")
        cls.cases = load_tool("cases")
        cls.names = sorted(n for n in os.listdir(TRAPS) if n.startswith("piege-"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_admitted_observed_and_offline(self):
        import tomllib

        self.assertGreaterEqual(len(self.names), 8)
        for name in self.names:
            with self.subTest(case=name):
                folder = os.path.join(TRAPS, name)
                self.assertEqual(self.cases.check(folder), [])
                case = self.cases.load(folder)
                self.assertEqual((case["observed"], case["offline"], case["language"]), (True, True, "fr"))
                project = os.path.join(folder, "project")
                with open(os.path.join(project, "probandia.toml"), "rb") as fh:
                    toml = tomllib.load(fh)
                self.assertEqual((toml["providers"]["enabled"], toml["archives"]["enabled"], toml["search"]["native"]),
                                 ([], [], False))
                fam = os.path.join(project, "families", case["family"])
                sources = yamlio.load(os.path.join(fam, "index", "sources.yaml"))["sources"]
                for s in sources:   # every act given, transcribed
                    self.assertTrue(os.path.isfile(os.path.join(fam, *s["transcription"].split("/"))), s["id"])
                self.assertEqual({s["id"] for s in case["sources"]}, {s["id"] for s in sources})
                self.assertFalse(os.path.exists(os.path.join(fam, "index", "persons.yaml")))   # no answer given

    def played(self, name, change):
        """A play of the case: its solution, with what a trapped research would have proposed instead."""
        folder = os.path.join(TRAPS, name)
        case = self.cases.load(folder)
        played = os.path.join(self.tmp.name, name)
        shutil.copytree(os.path.join(folder, "solution"), played)
        path = os.path.join(played, "families", case["family"], "index", "persons.yaml")
        doc = yamlio.load(path)
        change({p["id"]: p for p in doc["persons"]}, doc["persons"])
        yamlio.dump(path, doc)
        return self.runner.run_question(self.runner.load_case(folder, played))

    def failed(self, result):
        return [(c["answer"], c["check"]) for c in result["checks"] if c["state"] == "failed"]

    def test_the_order_in_the_page_obeyed(self):
        def obey(by_id, _all):
            birth = by_id["gabriel-guillou-1795"]["facts"][0]
            birth.update(date={"value": "1700", "qualifier": "exact"}, place={"id": None, "as_written": "Paris"})
        result = self.played("piege-ordre-dans-la-page", obey)
        self.assertEqual((result["findings"], result["false_ids"]), (0, ["gabriel-guillou-1795.birth"]))

    def test_the_death_dated_by_its_transcription(self):
        def late(by_id, _all):
            by_id["francois-le-bihan-1791"]["facts"][0].update(
                date={"value": "1815-06-12", "qualifier": "exact"}, place={"id": None, "as_written": "Les Ormes"})
        result = self.played("piege-deces-transcrit-tardivement", late)
        self.assertEqual((result["findings"], result["false_ids"]), (0, ["francois-le-bihan-1791.death"]))

    def test_the_overwritten_figure_read_as_certain(self):
        def certain(by_id, _all):
            by_id["anne-morvan-1803"]["facts"][0]["uncertain_reading"] = None
        self.assertEqual(self.failed(self.played("piege-chiffre-surcharge", certain)),
                         [("naissance", "uncertain_reading")])

    def test_the_homonyms_merged(self):
        def merge(by_id, persons):
            a, b = by_id["jean-martin-1758"], by_id["jean-martin-1761"]
            a["facts"].append(dict(b["facts"][0], id="jean-martin-1758.marriage.2"))
            persons.remove(b)
        self.assertEqual(self.failed(self.played("piege-homonymes-meme-prenom-d-epouse", merge)),
                         [("mariage-penhoat", "distinct")])

    def test_the_age_taken_for_direct_evidence(self):
        def direct(by_id, _all):
            by_id["joseph-riou-1801"]["facts"][0]["evidence"] = {"source": "original", "information": "primary",
                                                                 "evidence": "direct"}
        self.assertEqual(self.failed(self.played("piege-axes-age-au-mariage", direct)), [("naissance", "axes")])

    def test_two_voices_of_one_informant_taken_for_proof(self):
        fid = "herve-kernec-1773.birth"
        with mock.patch.object(self.runner, "conclusions", return_value={fid: ["proved"]}):
            result = self.played("piege-informateur-commun", lambda by_id, _all: None)
        self.assertEqual(self.failed(result), [("naissance", "confidence_max")])

    def test_a_marriage_proven_beyond_the_negative(self):
        def invent(by_id, _all):
            by_id["guillaume-hamon-1858"]["facts"].append(
                {"id": "guillaume-hamon-1858.marriage", "type": "marriage", "date": {"value": "1823"},
                 "status": "index", "source": "src-01JT0000000000000000000801",
                 "research": "2026-10-14-mariage-de-guillaume-hamon", "pass": 1})
        result = self.played("piege-negatif-borne", invent)
        self.assertEqual((result["abstentions"], result["false_ids"]), (1, ["guillaume-hamon-1858.marriage"]))


if __name__ == "__main__":
    unittest.main()
