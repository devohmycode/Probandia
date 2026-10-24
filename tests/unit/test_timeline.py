"""The chronology as findings, rule V-18 and the timelines of the report (GPS7)."""
import glob
import os
import unittest

from probandia import chronology
from probandia.util import yamlio
from tests import ROOT

FIX = os.path.join(ROOT, "tests", "fixtures", "chronology")
CODES = {"born-after-mothers-death.yaml": ("born-after-death", "error"),
         "death-before-birth.yaml": ("death-before-birth", "error"),
         "impossible-date.yaml": ("date-invalid", "error"),
         "married-before-twelve.yaml": ("married-young", "warning"),
         "parent-younger-than-child.yaml": ("parent-young", "error"),
         "too-old.yaml": ("age-over", "warning")}


class Findings(unittest.TestCase):
    """GPS7-T1: each check gives a structured finding; apply keeps its P-9 lines."""

    def test_each_fixture_gives_its_finding(self):
        for path in sorted(glob.glob(os.path.join(FIX, "*.yaml"))):
            doc = yamlio.load(path)
            name = os.path.basename(path)
            with self.subTest(case=name):
                found = chronology.all_findings(doc["persons"])
                if not doc["expect"]:
                    self.assertEqual(found, [])
                    continue
                self.assertEqual(len(found), 1, found)
                f = found[0]
                self.assertEqual((f["code"], f["severity"]), CODES[name])
                self.assertLessEqual(set(doc["expect"]), set(f["facts"]))
                self.assertIn(f["person"], [p["id"] for p in doc["persons"]])
                self.assertEqual(chronology.check(doc["persons"]), ["P-9: " + f["message"]])

    def test_years_of_a_finding(self):
        doc = yamlio.load(os.path.join(FIX, "born-after-mothers-death.yaml"))
        f = chronology.all_findings(doc["persons"])[0]
        self.assertEqual(f["years"], [1830, 1825])
        self.assertEqual(f["person"], "rose-hugot-1830")

    def test_a_hypothesis_is_checked_only_when_asked(self):
        doc = yamlio.load(os.path.join(FIX, "death-before-birth.yaml"))
        for p in doc["persons"]:
            for f in p["facts"]:
                if f["type"] == "death":
                    f["status"] = "hypothesis"
        self.assertEqual(chronology.all_findings(doc["persons"]), [])   # apply and V-14: proven facts only
        found = chronology.all_findings(doc["persons"], counted=("record", "index", "hypothesis"))
        self.assertEqual([f["code"] for f in found], ["death-before-birth"])

    def test_selection_takes_parents_and_children(self):
        doc = yamlio.load(os.path.join(FIX, "born-after-mothers-death.yaml"))
        self.assertEqual(chronology.selection(doc["persons"], {"anne-hugot-1790"}),
                         {"anne-hugot-1790", "rose-hugot-1830"})


class Rule(unittest.TestCase):
    """GPS7-T2: V-14 warns of a clash among the research's facts; a note explains it; strict fails it when it
    touches a question's conclusion."""

    def setUp(self):
        import shutil
        import tempfile

        from probandia.research import Research
        from tests.unit.test_lifecycle import FIXTURE, RID

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.res = Research(self.dir, "hugo", RID)
        self.path = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")

    def add_death(self, year, note=""):
        """A fact written past apply (an old import): apply itself refuses the clash."""
        doc = yamlio.load(self.path)
        jean = next(p for p in doc["persons"] if p["id"] == "jean-martin-1849")
        death = dict(jean["facts"][0], id="jean-martin-1849.death", type="death", note=note,
                     date=dict(jean["facts"][0]["date"], value=str(year)))
        jean["facts"].append(death)
        yamlio.dump(self.path, doc)

    def v14(self, standard="off"):
        from probandia import verify

        class Config:
            def get(self, key):
                return standard if key == "proof.standard" else None

        return verify.run(self.dir, self.res, Config(), ["V-14"])[0][1:]

    def test_pass_warn_explained_strict(self):
        self.assertEqual(self.v14(), ("PASS", ""))
        self.add_death(1840)
        status, message = self.v14()
        self.assertEqual(status, "WARN")
        self.assertIn("jean-martin-1849.death (1840) comes before jean-martin-1849.birth", message)
        self.assertEqual(self.v14("strict")[0], "WARN")   # no question's conclusion is touched
        from probandia import lifecycle
        from probandia.proof import questions as Q

        qs, _q = Q.settle(Q.of(self.res.meta()), "Q1", "answered", conclusion=["jean-martin-1849.birth"])
        lifecycle.update_meta(self.res, questions=qs)
        self.assertEqual(self.v14("strict")[0], "FAIL")
        self.assertEqual(self.v14("warn")[0], "WARN")

    def test_a_note_explains_the_clash(self):
        self.add_death(1840, note="the death record gives 1840; the register is misdated, see the margin")
        self.assertEqual(self.v14(), ("PASS", ""))

    def test_a_fact_against_the_date_of_its_act(self):
        # T244: the birth of 1802-02-26, whose act the index says was drawn up on 1802-02-25
        path = os.path.join(self.dir, "families", "hugo", "index", "sources.yaml")
        doc = yamlio.load(path)
        doc["sources"][0].update(act="naissance", act_date="1802-02-25")
        yamlio.dump(path, doc)
        status, message = self.v14()
        self.assertEqual(status, "WARN")
        self.assertIn("victor-hugo-1802.birth (1802-02-26) comes after the act that records it", message)
        doc["sources"][0].update(act_date="1830-07-02")   # a judgement, long after: a note explains it
        yamlio.dump(path, doc)
        self.assertIn("more than a year later", self.v14()[1])
        persons = yamlio.load(self.path)
        persons["persons"][0]["facts"][0]["note"] = "declared by a judgement of the court of Besançon, 1830"
        yamlio.dump(self.path, persons)
        self.assertEqual(self.v14(), ("PASS", ""))


class ActDates(unittest.TestCase):
    """T244: a fact against the date of the act of its source, when that act is of the fact's own type."""

    def found(self, kind="birth", value="1850-03-14", act="naissance", act_date="1850-03-14", **fact):
        f = dict({"id": f"jean-martin-1850.{kind}", "type": kind, "status": "record", "source": "src-1",
                  "date": {"value": value, "qualifier": "exact"}}, **fact)
        sources = {"src-1": {"id": "src-1", "type": "civil-registration", "act": act, "act_date": act_date}}
        persons = [{"id": "jean-martin-1850", "names": {"given": "Jean", "surname": "MARTIN"}, "facts": [f]}]
        self.assertEqual(chronology.all_findings(persons), [])   # without the sources, as the timelines
        return [(x["code"], x["severity"]) for x in chronology.all_findings(persons, sources=sources)]

    def test_after_its_act(self):
        error = [("after-its-act", "error")]
        self.assertEqual(self.found(), [])
        self.assertEqual(self.found(value="1850-03-15"), error)
        self.assertEqual(self.found(value="1851"), error)
        self.assertEqual(self.found(value="1850"), [])   # the same year: no telling
        self.assertEqual(self.found(value="1850-03-13", act="Acte de baptême"), [])   # baptised the day after
        self.assertEqual(self.found(value="1850-03-15", act="baptism"), error)
        self.assertEqual(self.found("marriage", "1850-03-15", act="mariage"), error)
        self.assertEqual(self.found("death", "1850-03-15", act="décès"), error)
        self.assertEqual(self.found("death", "1850-03-15", act="acte d'inhumation"), error)
        self.assertEqual(self.found("burial", "1850-03-15", act="sépulture"), error)

    def test_more_than_a_year_before(self):
        late = [("late-act", "warning")]
        self.assertEqual(self.found(value="1849-03-13"), late)
        self.assertEqual(self.found(value="1849-03-14"), [])   # a year exactly
        self.assertEqual(self.found(value="1849"), [])   # 1849-12-31 is less than a year before
        self.assertEqual(self.found(value="1848"), late)
        self.assertEqual(self.found(value="1849-02", act_date="1850-03"), late)
        self.assertEqual(self.found(value="1849-03", act_date="1850-03"), [])
        self.assertEqual(self.found("death", "1840-05-02", act="death"), late)   # a death declared by a judgement

    def test_only_an_act_of_the_facts_own_type(self):
        # a date of birth that an act of death or of marriage gives is no clash, nor a mention in the margin
        self.assertEqual(self.found("birth", "1790", act="décès"), [])
        self.assertEqual(self.found("birth", "1790", act="marriage"), [])
        self.assertEqual(self.found("marriage", "1875-06-01", act="naissance"), [])
        self.assertEqual(self.found("death", "1901-02-11", act="naissance"), [])
        self.assertEqual(self.found("marriage", "1850-04-01", act="contrat de mariage"), [])
        self.assertEqual(self.found("marriage", "1850-04-01", act="banns"), [])
        self.assertEqual(self.found("baptism", "1850-03-16", act="naissance"), [])   # the civil act came first
        self.assertEqual(self.found("burial", "1850-03-16", act="décès"), [])
        # nor an act or a date not given, a date not exact, or a fact that is not proven
        self.assertEqual(self.found(value="1851", act=None), [])
        self.assertEqual(self.found(value="1851", act_date=None), [])
        self.assertEqual(self.found(value="1851", date={"value": "1851", "qualifier": "about"}), [])
        self.assertEqual(self.found(value="1851", status="hypothesis"), [])

    def test_apply_refuses_what_no_note_explains(self):
        persons = [{"id": "jean-martin-1850", "facts": [
            {"id": "jean-martin-1850.birth", "type": "birth", "status": "record", "source": "src-1",
             "date": {"value": "1850-03-14"}}]}]
        sources = {"src-1": {"id": "src-1", "act": "birth", "act_date": "1880-01-02"}}
        self.assertEqual(len(chronology.check(persons, sources=sources)), 1)
        persons[0]["facts"][0]["note"] = "a declaratory judgement of 1880"
        self.assertEqual(chronology.check(persons, sources=sources), [])
        sources["src-1"]["act_date"] = "1850-03-13"   # after its act: no note makes it true
        self.assertTrue(chronology.check(persons, sources=sources)[0].startswith("P-9: jean-martin-1850.birth"))

    def test_the_samples_give_no_finding(self):
        from probandia.indexes import FamilyIndexes

        for name in ("sample-project", "sample-project-gps"):
            idx = FamilyIndexes(os.path.join(ROOT, "tests", name), "marchand")
            sources = {s["id"]: s for s in idx.items("sources")}
            with self.subTest(sample=name):
                self.assertEqual(chronology.all_findings(idx.items("persons"), sources=sources), [])


def person(pid, facts, father=None, mother=None, spouses=(), given="Jean", surname="MARTIN"):
    return {"id": pid, "names": {"given": given, "surname": surname}, "parents": {"father": father, "mother": mother},
            "spouses": [{"person": s} for s in spouses],
            "facts": [{"id": f"{pid}.{kind}", "type": kind, "date": {"value": str(y)} if y else None,
                       "status": status, "place": {"as_written": place} if place else None,
                       "research": "r1"} for kind, y, status, place in facts]}


class Model(unittest.TestCase):
    """GPS7-T3: a full life, a life with gaps, a person presumed living."""

    def family(self):
        mother = person("anne-hugot-1790", [("birth", 1790, "record", "Nancy"), ("death", 1825, "record", "")],
                        given="Anne", surname="HUGOT")
        child = person("rose-martin-1820", [("birth", 1820, "record", "Nancy"), ("marriage", 1842, "index", "Lunéville"),
                                            ("death", 1890, "hypothesis", ""), ("burial", None, "record", "")],
                       mother="anne-hugot-1790", spouses=["paul-roy-1815"], given="Rose")
        late = person("luc-martin-1830", [("birth", 1830, "hypothesis", "")], mother="anne-hugot-1790", given="Luc")
        spouse = person("paul-roy-1815", [("death", 1860, "record", "")], given="Paul", surname="ROY")
        grandchild = person("jean-roy-1845", [("birth", 1845, "record", "")], mother="rose-martin-1820",
                            father="paul-roy-1815")
        return [mother, child, late, spouse, grandchild]

    def test_a_full_life_with_its_landmarks(self):
        from probandia.report import timeline

        tl = timeline.model("rose-martin-1820", self.family())
        self.assertEqual([(e["type"], e["year"], e["age"]) for e in tl["events"]],
                         [("birth", 1820, None), ("marriage", 1842, 22), ("death", 1890, 70)])
        self.assertEqual([(r["role"], r["type"], r["year"]) for r in tl["relatives"]],
                         [("mother", "death", 1825), ("child", "birth", 1845), ("spouse", "death", 1860)])
        self.assertEqual(tl["span"], [1820, 1890])
        self.assertTrue(all(e["severity"] is None for e in tl["events"]))

    def test_a_hypothesis_that_clashes_is_marked(self):
        from probandia.report import timeline

        tl = timeline.model("luc-martin-1830", self.family())
        self.assertEqual(tl["events"][0]["severity"], "error")
        self.assertIn("after the mother's death", tl["events"][0]["findings"][0])
        self.assertEqual(chronology.all_findings(self.family()), [])   # nothing for apply: a hypothesis
        anne = timeline.model("anne-hugot-1790", self.family())   # the proven death it hits is not marked
        self.assertTrue(all(e["severity"] is None for e in anne["events"]))

    def test_gaps_and_living(self):
        from probandia.report import timeline

        fam = self.family()
        self.assertIsNone(timeline.model("rose-martin-1820", fam, living={"rose-martin-1820"}))
        tl = timeline.model("rose-martin-1820", fam, living={"jean-roy-1845"})
        self.assertNotIn("child", [r["role"] for r in tl["relatives"]])
        self.assertIsNone(timeline.model("nobody", fam))
        fam.append(person("x-1900", [("birth", None, "record", "")]))
        self.assertIsNone(timeline.model("x-1900", fam))   # no dated fact

    def test_markdown(self):
        from probandia.report import timeline

        tl = timeline.model("luc-martin-1830", self.family())
        text = timeline.markdown(tl, lambda s: s)
        self.assertIn("| 1830 |  | birth (hypothesis) |  | ✗ luc-martin-1830.birth (1830) comes after", text)
        self.assertIn("| 1825 |  | mother — Anne HUGOT: death |", text)

    def test_who_gets_one(self):
        from probandia.report import timeline

        fam = self.family()
        meta = {"id": "r1"}
        self.assertEqual(timeline.chosen(meta, fam, "off"), [])
        self.assertEqual(len(timeline.chosen(meta, fam, "all")), 5)
        self.assertEqual(len(timeline.chosen(meta, fam, "main")), 5)   # no questions: the research's persons
        meta["questions"] = [{"id": "Q1", "text": "x", "type": "death", "status": "answered", "persons": ["luc-martin-1830"],
                              "conclusion": ["paul-roy-1815.death"]}]
        self.assertEqual(timeline.chosen(meta, fam, "main"), ["luc-martin-1830", "paul-roy-1815"])


class Chart(unittest.TestCase):
    """GPS7-T4: the SVG timeline, against its reference; a clash reads without colour."""

    def chart(self, pid):
        from probandia import svg
        from probandia.report import timeline

        tl = timeline.model(pid, Model().family())
        return svg.timeline(tl, "Timeline of " + tl["name"], lambda e: e["type"], lambda r: f"{r['role']} {r['type']}")

    def test_reference(self):
        import xml.dom.minidom

        text = self.chart("rose-martin-1820")
        xml.dom.minidom.parseString(text)
        path = os.path.join(ROOT, "tests", "golden", "timeline.svg")
        if os.environ.get("PROBANDIA_UPDATE_GOLDEN"):
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(text, fh.read())
        self.assertIn("<title>Timeline of Rose MARTIN</title>", text)
        self.assertIn("<desc>birth 1820; marriage 1842; death 1890; mother death 1825", text)
        self.assertIn('<g class="hypothesis">', text)

    def test_a_clash_is_a_shape_and_a_sign(self):
        text = self.chart("luc-martin-1830")
        self.assertIn('<g class="hypothesis clash error">', text)
        self.assertIn("<polygon class=\"mark\"", text)
        self.assertIn('text-anchor="middle">!</text>', text)
        self.assertNotIn("clash", self.chart("anne-hugot-1790").split("<style>")[1].split("</style>")[1])


class InTheReport(unittest.TestCase):
    """GPS7-T5: report.timeline puts the main persons' timelines in the report: a table in Markdown, the chart
    then the table in HTML; off leaves them out."""

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u")}

    def call(self, *argv):
        import io

        from probandia import cli

        out = io.StringIO()
        return cli.main(list(argv), stdout=out, environ=self.env, cwd=self.dir), out.getvalue()

    def report(self, ext):
        from probandia.research import find_research

        self.assertEqual(self.call("render", "2026-09")[0], 0)
        with open(os.path.join(find_research(self.dir, "2026-09").folder, "report", "report." + ext),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_main_then_off(self):
        md = self.report("md")
        # an old research: the person its free-text question names, not every person of the research
        headings = [line for line in md.splitlines() if line.startswith("#") and "Chronologie de" in line]
        self.assertEqual(len(headings), 1, headings)
        self.assertIn("Chronologie de Louis MARCHAND", headings[0])
        self.assertIn("| 1970 | 72 | décès |", md)
        html = self.report("html")
        figure = html.index('<figure class="timeline">')
        self.assertLess(figure, html.index("<table>", figure))   # the chart, then its table
        self.assertEqual(self.call("verify", "2026-09", "--rule", "V-6")[0], 0)
        self.call("config", "set", "report.timeline", "off")
        self.assertNotIn("Chronologie", self.report("md"))

    def test_main_follows_the_questions(self):
        self.call("question", "add", "When did Henri Marchand die?", "--person", "henri-marchand-1870",
                  "--research", "2026-09")
        md = self.report("md")
        headings = [line for line in md.splitlines() if line.startswith("#") and "Chronologie de" in line]
        self.assertEqual(len(headings), 1, headings)   # the person the question names, and no one else
        self.assertIn("Chronologie de Henri MARCHAND", headings[0])


class Designer(unittest.TestCase):
    """GPS7-T6: the designer's sample holds timelines, so a template can be styled for them offline."""

    def test_the_sample_has_timelines(self):
        with open(os.path.join(ROOT, "designer", "sample.json"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('<figure class=\\"timeline\\">', text)
        self.assertIn("Chronologie de", text)
        with open(os.path.join(ROOT, "skills", "report", "templates.md"), encoding="utf-8") as fh:
            self.assertIn("figure.timeline svg", fh.read())
