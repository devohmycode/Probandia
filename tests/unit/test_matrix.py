import os
import shutil
import unittest

from probandia.proof import matrix
from probandia.research import Research
from probandia.util import yamlio
from tests import ROOT
from tests.integration import test_sample_project as sample
from tests.unit.test_data_layer import RID, Project

FIX = os.path.join(ROOT, "tests", "fixtures")
S1, S2, S3, S4, S5, S6 = (f"s-01JB{n:022d}" for n in range(1, 7))


def auxon_dessous():
    return yamlio.load(os.path.join(FIX, "places", "valid", "guide.yaml"))["places"][0]


def question(qtype, start, end=None, places=("auxon-dessous",)):
    return {"id": "Q1", "text": "…", "type": qtype, "status": "open", "places": list(places),
            "window": {"from": start, "to": end or start}}


def types(found):
    return [r["type"] for r in found["rows"]]


class Expected(unittest.TestCase):
    def setUp(self):
        self.places = {"auxon-dessous": auxon_dessous(),
                       "chambery": {"id": "chambery", "insee": {"code": "73065"}},
                       "paris": {"id": "paris", "insee": {"code": "75056"}},
                       "vianden": {"id": "vianden", "jurisdictions": [
                           {"level": "country", "name": "LU", "from": None, "to": None}]},
                       "nowhere": {"id": "nowhere"}}

    def expected(self, q):
        return matrix.expected(q, self.places, archives={})

    def test_a_birth_in_1780_expects_the_parish_registers(self):
        found = self.expected(question("birth", 1780))
        self.assertEqual(types(found), ["parish_registers"])
        row = found["rows"][0]
        self.assertEqual((row["places"], row["years"]), (["auxon-dessous"], [1780, 1780]))
        self.assertEqual(row["repositories"], [{"name": "Archives départementales du Doubs", "archive": "ad25"}])
        self.assertTrue(row["references"])

    def test_a_birth_in_1850(self):
        found = self.expected(question("birth", 1850))
        self.assertEqual(types(found), ["civil_registers", "decennial_tables", "census"])
        repos = {r["type"]: r["repositories"] for r in found["rows"]}
        self.assertEqual([r["archive"] for r in repos["civil_registers"]], ["ad25"])
        self.assertEqual(repos["decennial_tables"], [])  # the guide lists no holding of tables
        self.assertEqual(found["unknown"], [])

    def test_parents_in_1890_add_the_military_registers_and_the_estates(self):
        found = self.expected(question("parents", 1890))
        self.assertEqual(types(found), ["civil_registers", "decennial_tables", "census", "notarial",
                                        "military_registers", "registration"])

    def test_savoy_under_sardinian_rule(self):
        found = self.expected(question("birth", 1830, places=["chambery"]))
        self.assertEqual(types(found), ["parish_registers"])
        self.assertEqual(found["rows"][0]["notes"][0]["effect"], "extended")
        found = self.expected(question("birth", 1855, 1865, places=["chambery"]))
        civil = found["rows"][types(found).index("civil_registers")]
        self.assertEqual(civil["years"], [1861, 1865])
        self.assertEqual(civil["notes"][0]["by"], "parish_registers")

    def test_paris_before_1860_is_expected_with_its_loss(self):
        found = self.expected(question("birth", 1850, places=["paris"]))
        civil = found["rows"][0]
        self.assertEqual(civil["type"], "civil_registers")
        self.assertEqual(civil["notes"][0]["effect"], "destroyed")

    def test_a_census_year_not_taken(self):
        found = self.expected(question("residence", 1916, places=["paris"]))
        self.assertNotIn("census", types(found))
        found = self.expected(question("residence", 1914, 1918, places=["paris"]))
        census = found["rows"][types(found).index("census")]
        self.assertEqual(census["notes"][0]["years"], [1916, 1916])

    def test_without_window_or_places(self):
        q = question("birth", 1850)
        del q["window"]
        self.assertEqual(self.expected(q)["unknown"], ["window"])
        found = self.expected(question("birth", 1850, places=["nowhere"]))
        self.assertEqual((found["unknown"], found["rows"]), (["places"], []))

    def test_a_country_not_in_the_catalogue(self):
        found = self.expected(question("birth", 1850, places=["vianden"]))
        self.assertEqual(found["notes"], [{"country": "LU"}])
        # T235: a row that no search settles, until matrix justify names the source types searched
        self.assertEqual(types(found), ["catalogue_lu"])
        self.assertEqual((found["rows"][0]["places"], found["rows"][0]["years"]), (["vianden"], [1850, 1850]))
        filled = matrix.fill(found, "birth", self.places, [], [], archives={})
        self.assertEqual(matrix.holes({"unknown": [], "rows": filled}), ["catalogue_lu"])
        said = [{"question": "Q1", "type": "catalogue_lu", "reason": "état civil de Vianden, ANLux"}]
        filled = matrix.fill(found, "birth", self.places, [], [], said, archives={})
        self.assertEqual(matrix.holes({"unknown": [], "rows": filled}), [])

    def test_a_place_without_guide_falls_back_on_the_archives(self):
        found = matrix.expected(question("birth", 1850, places=["paris"]), self.places)
        civil = found["rows"][0]
        self.assertIn("familysearch", [r["archive"] for r in civil["repositories"]])
        self.assertNotIn("openarchives", [r["archive"] for r in civil["repositories"]])   # C5: no French register
        self.assertIn("Archives de Paris", [r["name"] for r in civil["repositories"]])   # A2: its catalogue entry

    def test_regions(self):
        self.assertEqual(matrix.regions(auxon_dessous()), ["FR-25", "FR"])
        self.assertEqual(matrix.regions({"insee": {"code": "2A004"}}), ["FR-2A", "FR"])
        self.assertEqual(matrix.regions({"jurisdictions": [{"level": "department", "name": "Doubs",
                                                            "note": "department 25"}]}), ["FR-25", "FR"])
        self.assertEqual(matrix.regions({}), [])


class MatrixProject(Project):
    """The fixture project, with Auxon-Dessous and its guide, and one question of parents in 1890.
    T27: an apply takes half a second; the project is made once per class, then copied for each test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        maker = Project("setUp")
        maker.setUp()
        cls.addClassCleanup(maker.doCleanups)
        (code, out), _doc = maker.propose_and_apply(places=[auxon_dessous()])
        maker.assertEqual(code, 0, out)
        research = Research(maker.dir, "hugo", RID)
        meta = research.meta()
        meta["questions"] = [{"id": "Q1", "text": "Who were the parents of Jean, born in 1890 at Auxon-Dessous?",
                              "type": "parents", "status": "open", "places": ["auxon-dessous"],
                              "window": {"from": 1890, "to": 1890}}]
        yamlio.dump(os.path.join(research.folder, "research.yaml"), meta)
        cls.made = maker.tmp.name

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.dir)   # the fixture, replaced by the project made for the class
        shutil.copytree(self.made, self.tmp.name, dirs_exist_ok=True)
        self.research = Research(self.dir, "hugo", RID)

    def add(self, name, *items):
        doc = self.index(name)
        doc[name] += list(items)
        yamlio.dump(os.path.join(self.family, "index", f"{name}.yaml"), doc)

    def search(self, sid, engine, types=None, window=(1885, 1895), result="positive"):
        base = dict(self.index("searches")["searches"][0])
        return dict(base, id=sid, engine=engine, query="Hugot Auxon-Dessous", result=result, results=1,
                    filters={"types": types} if types else None,
                    window={"from": window[0], "to": window[1], "places": ["Auxon-Dessous"]})

    def states(self, not_applicable=()):
        built = matrix.build(self.research, not_applicable=list(not_applicable))
        return {r["type"]: r for r in built["questions"][0]["rows"]}, built


class Filling(MatrixProject):
    """GPS3-T4: each state of the matrix."""

    def test_the_four_states(self):
        self.add("searches", self.search(S1, "ad25", types=["civil_registers"]),
                 self.search(S2, "ad25", types=["census"], result="failed"))
        self.add("gaps", {"id": "G1", "archive": "ad25", "reference": "6 M 260", "kind": "missing",
                          "window": {"from": 1886, "to": 1891}, "place": "auxon-dessous", "types": ["census"],
                          "justification": "the finding aid of 6 M lists no census of Auxon-Dessous for 1886 and 1891"},
                 {"id": "G2", "archive": "ad25", "reference": None, "kind": "lacunary",
                  "window": {"from": 1880, "to": 1900}, "types": ["registration"]})
        rows, built = self.states([{"question": "Q1", "type": "notarial", "ts": "2026-10-04T12:00:00Z",
                                    "reason": "the family owned nothing: no notary would have been called"}])
        self.assertEqual({t: r["state"] for t, r in rows.items()},
                         {"civil_registers": "consulted", "decennial_tables": "todo", "census": "gap",
                          "notarial": "not_applicable", "military_registers": "todo",
                          "registration": "unjustified_gap"})
        self.assertEqual(rows["civil_registers"]["searches"], [S1])
        self.assertEqual(rows["census"]["gaps"], ["G1"])
        self.assertEqual(matrix.holes(built["questions"][0]),
                         ["decennial_tables", "military_registers", "registration"])
        matrix.write(self.research, built)
        self.assertEqual(matrix.read(self.research)["questions"], built["questions"])

    def test_a_search_without_types_counts_for_what_its_archive_covers(self):
        self.add("searches", self.search(S6, "ad25"))
        rows, _built = self.states()
        self.assertEqual(rows["civil_registers"]["state"], "consulted")
        self.assertEqual(rows["census"]["state"], "consulted")
        self.assertEqual(rows["decennial_tables"]["state"], "todo")  # ad25 lists no tables

    def test_the_window_and_the_coverage_must_cross(self):
        self.add("searches", self.search(S3, "ad25", window=(1700, 1780)),
                 self.search(S4, "gallica", types=["civil_registers"]),
                 self.search(S5, "serpapi"))
        rows, _built = self.states()
        self.assertEqual(rows["civil_registers"]["state"], "todo")

    def test_a_not_applicable_without_reason_stays_a_hole(self):
        rows, built = self.states([{"question": "Q1", "type": "notarial", "ts": "2026-10-04T12:00:00Z"}])
        self.assertEqual(rows["notarial"]["state"], "not_applicable")
        self.assertIn("notarial", matrix.holes(built["questions"][0]))

    def test_a_question_without_window(self):
        meta = self.research.meta()
        del meta["questions"][0]["window"]
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        _rows, built = self.states()
        self.assertEqual(matrix.holes(built["questions"][0]), ["unknown:window"])


class Command(MatrixProject):
    """GPS3-T5: matrix shows and writes the matrix; matrix justify says why a type does not apply."""

    def human(self, *argv):
        return self.call(*argv, "--output-format", "human", "--width", "120", env={"NO_COLOR": "1"})[1]

    def test_an_incomplete_matrix(self):
        from tests.unit.test_human import golden

        self.add("searches", self.search(S1, "ad25", types=["civil_registers"]))
        self.add("gaps", {"id": "G1", "archive": "ad25", "reference": "6 M 260", "kind": "missing",
                          "window": {"from": 1886, "to": 1891}, "place": "auxon-dessous", "types": ["census"],
                          "justification": "the finding aid of 6 M lists no census of Auxon-Dessous for 1886 and 1891"})
        code, out = self.call("matrix", RID)
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("HOLES=4", out)
        self.assertIn("Q1=holes: decennial_tables, notarial, military_registers, registration", out)
        self.assertEqual(matrix.read(self.research)["questions"][0]["rows"][0]["state"], "consulted")
        golden(self, "matrix", self.human("matrix", RID))

    def test_justify(self):
        before = self.call("verify", RID, "--rule", "V-1")[1]
        code, out = self.call("matrix", "justify", "q1", "notarial", "--research", RID, "--agent", "orchestrator",
                              "--reason", "the family owned nothing: no notary would have been called")
        self.assertEqual(code, 0, out)
        self.assertIn("JUSTIFIED=Q1.notarial", out)
        stored = matrix.read(self.research)
        self.assertEqual(stored["not_applicable"][0]["agent"], "orchestrator")
        row = {r["type"]: r for r in stored["questions"][0]["rows"]}["notarial"]
        self.assertEqual(row["state"], "not_applicable")
        from probandia import events

        log = events.read(self.research.events_path)
        self.assertEqual(log[-1]["type"], "matrix.justified")
        self.assertEqual(log[-1]["payload"]["type"], "notarial")
        # said again, it replaces; a later matrix keeps what was said
        self.call("matrix", "justify", "Q1", "notarial", "--research", RID, "--reason", "no estate")
        self.assertEqual(len(matrix.read(self.research)["not_applicable"]), 1)
        self.call("matrix", RID)
        self.assertEqual(matrix.read(self.research)["not_applicable"][0]["reason"], "no estate")
        self.assertEqual(self.call("verify", RID, "--rule", "V-1")[1], before)   # written outside a pass

    def test_justify_refuses(self):
        code, out = self.call("matrix", "justify", "Q1", "notarial", "--research", RID)
        self.assertEqual(code, 2)
        self.assertIn("REASON=no-reason", out)
        code, out = self.call("matrix", "justify", "Q1", "parish_registers", "--research", RID, "--reason", "x")
        self.assertEqual(code, 2)
        self.assertIn("REASON=not-expected", out)
        code, out = self.call("matrix", "justify", "Q9", "notarial", "--research", RID, "--reason", "x")
        self.assertIn("REASON=no-question", out)
        self.assertEqual(self.call("matrix", "justify", "Q1", "--research", RID, "--reason", "x")[0], 2)

    def test_one_question(self):
        meta = self.research.meta()
        meta["questions"].append({"id": "Q2", "text": "When did he die?", "type": "death", "status": "open"})
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        code, out = self.call("matrix", RID, "--question", "Q2")
        self.assertEqual(code, 0, out)
        self.assertIn("QUESTIONS=1", out)
        self.assertIn("Q2=holes: unknown:window, unknown:places", out)
        self.assertIn("question edit Q2", out)


class Rule(MatrixProject):
    """GPS3-T6: V-18 refuses a settled question with a hole in its matrix: a warning, a failure in strict."""

    def v18(self, standard="off"):
        from probandia import verify

        class Config:
            def get(self, key):
                return standard if key == "proof.standard" else None

        return verify.run(self.dir, self.research, Config(), ["V-18"])[0][1:]

    def settle(self, status="answered"):
        meta = self.research.meta()
        meta["questions"][0]["status"] = status
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)

    def test_an_open_question_is_not_checked(self):
        self.assertEqual(self.v18("strict"), ("PASS", ""))

    def test_a_country_the_catalogue_does_not_know(self):
        # T235: a question at Vianden (Luxembourg) is not exhaustive for want of a catalogue rule
        self.add("places", {"id": "vianden", "current_name": "Vianden",
                            "jurisdictions": [{"level": "country", "name": "LU", "from": None, "to": None}]})
        meta = self.research.meta()
        meta["questions"][0]["places"] = ["vianden"]
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.settle()
        status, detail = self.v18("strict")
        self.assertEqual(status, "FAIL")
        self.assertIn("catalogue_lu", detail)
        code, out = self.call("matrix", RID)
        self.assertIn("matrix justify Q1 catalogue_lu", out)
        code, out = self.call("matrix", "justify", "Q1", "catalogue_lu", "--research", RID, "--reason",
                              "civil registers of Vianden (ANLux), parish registers (diocese), census lists")
        self.assertEqual(code, 0, out)
        self.assertIn("JUSTIFIED=Q1.catalogue_lu", out)
        self.assertEqual(self.v18("strict"), ("PASS", ""))

    def test_holes_of_a_settled_question(self):
        self.settle()
        status, message = self.v18()
        self.assertEqual(status, "WARN")
        self.assertTrue(message.startswith("Q1 (answered): civil_registers, decennial_tables"), message)
        self.assertEqual(self.v18("strict")[0], "FAIL")
        self.settle("unresolved")
        self.assertEqual(self.v18("strict")[0], "FAIL")

    def test_a_general_question_may_stay_without_window_or_place(self):
        meta = self.research.meta()
        q = meta["questions"][0]
        del q["window"], q["places"]
        q["status"] = "unresolved"
        q["reason"] = "a broad question"
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.assertEqual(self.v18("strict")[0], "FAIL")   # unknown:window, unknown:places of a parents question
        q["type"] = "general"
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.assertEqual(self.v18("strict"), ("PASS", ""))

    def test_a_general_question_does_not_carry_a_conclusion_alone(self):
        meta = self.research.meta()
        general = {"id": "Q2", "text": "Who were the ancestors of Jean?", "type": "general", "status": "answered",
                   "conclusion": ["victor-hugo-1802.birth"]}
        meta["questions"].append(general)
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.assertEqual(self.v18(), ("WARN", "Q2 (general): answered with a conclusion, but no specific "
                                              "question of the research is"))
        self.assertEqual(self.v18("strict")[0], "FAIL")
        general["status"], general["conclusion"], general["reason"] = "unresolved", [], "too broad"
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.assertEqual(self.v18("strict"), ("PASS", ""))   # Q1 open, Q2 unresolved: nothing to refuse
        general.update(status="answered", conclusion=["victor-hugo-1802.birth"])
        meta["questions"][0]["status"] = "answered"
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.add("searches", self.search(S1, "ad25"))
        self.add("gaps", {"id": "G1", "archive": "ad25", "reference": None, "kind": "missing",
                          "window": {"from": 1880, "to": 1900}, "place": "auxon-dessous",
                          "types": ["decennial_tables", "notarial", "registration", "military_registers"],
                          "justification": "the series are not in the finding aids of ad25 for Auxon-Dessous"})
        self.assertEqual(self.v18("strict"), ("PASS", ""))   # Q1, specific, answered and searched in full

    def test_every_type_settled(self):
        self.settle()
        self.add("searches", self.search(S1, "ad25"))
        self.add("gaps", {"id": "G1", "archive": "ad25", "reference": None, "kind": "missing",
                          "window": {"from": 1880, "to": 1900}, "place": "auxon-dessous",
                          "types": ["decennial_tables", "notarial", "registration"],
                          "justification": "the series are not in the finding aids of ad25 for Auxon-Dessous"})
        self.assertEqual(self.v18("strict")[0], "FAIL")   # the military registers are left
        code, out = self.call("matrix", "justify", "Q1", "military_registers", "--research", RID,
                              "--reason", "Jean was born in 1890: his class was called after the question's window")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.v18("strict"), ("PASS", ""))


class Planning(MatrixProject):
    """GPS3-T7: a source type to do gives a search task in the plan, before the routing's."""

    def test_a_type_to_do_is_planned_first(self):
        self.add("searches", self.search(S1, "ad25"))
        code, out = self.call("plan", RID, "--agent", "orchestrator")
        self.assertEqual(code, 0, out)
        self.assertIn("MATRIX_TODO=4", out)
        self.assertIn("- matrix=Q1.decennial_tables todo - 1890-1890", out)
        (name,) = [f for f in os.listdir(self.research.work) if f.startswith("plan-")]
        doc = yamlio.load(os.path.join(self.research.work, name))
        first = doc["calls"][0]
        self.assertEqual((first["kind"], first["matrix"]), ("matrix", "Q1.decennial_tables"))
        self.assertEqual(first["record_types"], ["decennial_table"])
        self.assertEqual(first["window"], {"from": 1890, "to": 1890})
        self.assertIn("Auxon-Dessous", first["query"])
        planned = [c["matrix"] for c in doc["calls"] if c["kind"] == "matrix"]
        self.assertEqual(planned, ["Q1.decennial_tables", "Q1.notarial", "Q1.military_registers",
                                   "Q1.registration"])
        self.assertNotIn("Q1.civil_registers", planned)   # consulted

    def test_a_settled_question_plans_nothing(self):
        meta = self.research.meta()
        meta["questions"][0]["status"] = "answered"
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        code, out = self.call("plan", RID, "--agent", "orchestrator")
        self.assertEqual(code, 0, out)
        self.assertIn("MATRIX_TODO=0", out)


class Reporting(MatrixProject):
    """GPS3-T8: the method chapter gives each question's source coverage, with its gaps and how they are known."""

    def report(self, ext="md"):
        code, out = self.call("render", RID)
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.research.folder, "report", "report." + ext), encoding="utf-8") as fh:
            return fh.read()

    def test_the_coverage_of_a_question(self):
        from tests.unit.test_human import golden

        self.add("searches", self.search(S1, "ad25", types=["civil_registers"]))
        self.add("gaps", {"id": "G1", "archive": "ad25", "reference": "6 M 260", "kind": "missing",
                          "window": {"from": 1886, "to": 1891}, "place": "auxon-dessous", "types": ["census"],
                          "justification": "the finding aid of 6 M lists no census of Auxon-Dessous for 1886 and 1891"},
                 {"id": "G2", "archive": "ad25", "reference": None, "kind": "lacunary",
                  "window": {"from": 1880, "to": 1900}, "types": ["registration"]})
        self.call("matrix", "justify", "Q1", "notarial", "--research", RID,
                  "--reason", "the family owned nothing: no notary would have been called")
        md = self.report()
        start = md.index('<a id="s-coverage-q1">')
        section = md[start:]
        section = section[:section.index("[^")] if "[^" in section else section
        section = section[:section.index('<a id="s-', 1)] if '<a id="s-' in section[1:] else section
        golden(self, "coverage-report", section)
        self.assertLess(md.index('<a id="s-method">'), start)
        self.assertIn("ad25: “Hugot Auxon-Dessous”", section)
        self.assertIn("the finding aid of 6 M lists no census", section)
        self.assertIn("**G2**", section)
        self.assertIn('<section id="s-coverage-q1">', self.report("html"))

    def test_a_free_text_question_has_no_coverage(self):
        meta = self.research.meta()
        del meta["questions"]
        yamlio.dump(os.path.join(self.research.folder, "research.yaml"), meta)
        self.assertNotIn("s-coverage", self.report())


class Acceptance(unittest.TestCase):
    """GPS3 acceptance, on the sample project: a question of a birth in 1850 shows the decennial tables to do;
    close is refused in strict by V-18; after a logged search and a justified gap, close succeeds and the
    report shows the coverage."""

    setUp = sample.Sample.setUp
    call = sample.Sample.call

    def index(self, name):
        return os.path.join(self.dir, "families", "marchand", "index", f"{name}.yaml")

    def add(self, name, item):
        doc = yamlio.load(self.index(name))
        doc[name].append(item)
        yamlio.dump(self.index(name), doc)

    def close(self):
        self.assertEqual(self.call("render", sample.RID)[0], 0)
        return self.call("close", sample.RID)

    def test_a_birth_in_1850(self):
        places = yamlio.load(self.index("places"))
        places["places"][0]["insee"] = {"code": "25047"}   # Bourg-Vert, placed in the Doubs
        yamlio.dump(self.index("places"), places)
        for argv in (("add", "When was Jean MARCHAND born in Bourg-Vert?", "--place", "bourg-vert"),
                     ("edit", "Q2", "--window", "1850")):
            code, out = self.call("question", *argv, "--research", sample.RID)
            self.assertEqual(code, 0, out)
        code, out = self.call("matrix", sample.RID, "--question", "Q2")
        self.assertIn("Q2=holes: civil_registers, decennial_tables, census", out)
        q2 = next(q for q in matrix.read(self.research)["questions"] if q["id"] == "Q2")
        self.assertEqual({r["type"]: r["state"] for r in q2["rows"]}["decennial_tables"], "todo")

        for q in ("Q1", "Q2"):
            self.call("question", "unresolved", q, "--reason", "no act found yet", "--research", sample.RID)
        self.assertEqual(self.call("config", "set", "proof.standard", "strict")[0], 0)
        code, out = self.close()
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED=1", out)
        self.assertIn("V-18=FAIL Q2 (unresolved): civil_registers, decennial_tables, census", out)
        self.assertEqual(self.research.meta()["status"], "open")

        searches = yamlio.load(self.index("searches"))["searches"]
        self.add("searches", dict(searches[0], id="s-01JA00000000000000000SRC09", ts="2026-09-02T10:00:00Z",
                                  engine="ad25", query="MARCHAND Bourg-Vert 1850", result="negative",
                                  witness=searches[1].get("witness"), results=0,
                                  window={"from": 1849, "to": 1851, "places": ["Bourg-Vert"]}))
        self.add("gaps", {"id": "G1", "archive": "ad25", "reference": None, "kind": "missing",
                          "window": {"from": 1843, "to": 1852}, "place": "bourg-vert", "types": ["decennial_tables"],
                          "justification": "the finding aid of the 3 E series lists no decennial table for 1843-1852"})
        code, out = self.close()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.research.meta()["status"], "closed")
        with open(os.path.join(self.research.folder, "report", "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        coverage = md[md.index('<a id="s-coverage-q2">'):]
        for part in ("ad25: “MARCHAND Bourg-Vert 1850”", "the finding aid of the 3 E series"):
            self.assertIn(part, coverage)
