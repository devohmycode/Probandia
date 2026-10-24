"""Conformity to the Genealogical Proof Standard, question by question (GPS8)."""
import json
import unittest
import unittest.mock

from probandia.proof import standard as S
from tests.integration import test_sample_project as sample

RID = "2026-10-05-roy"
DIRECT = {"source": "original", "information": "primary", "evidence": "direct"}
TYPED = {"id": "s-birth", "type": "civil-registration", "jurisdiction": "Nancy", "register": "Births 1800",
         "repository": "AD 56"}


def fact(fid, value="1800", status="record", source="s-birth", **extra):
    return dict({"id": fid, "type": fid.split(".")[1], "status": status, "date": {"value": value},
                 "source": source, "research": RID, "evidence": dict(DIRECT)}, **extra)


def docs(facts=(), sources=(TYPED,), analyses=(), proofs=()):
    persons = [{"id": "jean-roy-1800", "names": {"given": "Jean", "surname": "ROY"}, "sex": "M",
                "facts": [fact("jean-roy-1800.birth")] if not facts else list(facts)}]
    return {"persons": {"persons": persons}, "sources": {"sources": list(sources)}, "places": {"places": []},
            "analyses": {"analyses": list(analyses)}, "proofs": {"proofs": list(proofs)}}


def question(qid="Q1", kind="birth", status="answered", conclusion=("jean-roy-1800.birth",), **extra):
    q = {"id": qid, "text": "When was Jean ROY born?", "type": kind, "status": status, "persons": ["jean-roy-1800"],
         "window": {"from": 1795, "to": 1805}, "places": ["nancy"]}
    if status == "answered":
        q["conclusion"] = list(conclusion)
    return dict(q, **extra)


def matrix(*states, qid="Q1", unknown=()):
    rows = [{"type": f"type{n}", "state": s, "places": ["nancy"], "years": [1795, 1805], "repositories": []}
            for n, s in enumerate(states)]
    return {"questions": [{"id": qid, "unknown": list(unknown), "rows": rows}]}


def assess(questions, d=None, m=None):
    return S.assess({"id": RID, "questions": list(questions)}, d or docs(), m or matrix("consulted"))


def states(found, n=0):
    return {k: v["state"] for k, v in found[n]["elements"].items()}


def contradictor(state="accepted", reviewer="contradictor"):
    return {"id": "pf-q1-" + RID, "research": RID, "question": "Q1", "conclusion": ["jean-roy-1800.birth"],
            "parts": {}, "review": {"state": state, "rounds": [{"date": "2026-10-05T10:00:00Z", "reviewer": reviewer,
                                                                "objections": []}]}}


class Levels(unittest.TestCase):
    """GPS8-T1: a conform question, a partial one and one that does not conform."""

    def test_conform(self):
        found = assess([question()])
        self.assertEqual(states(found), {"exhaustive": "established", "citations": "established",
                                         "analysis": "established", "conflicts": "established",
                                         "argument": "not_applicable"})
        self.assertEqual(found[0]["level"], "conform")

    def test_partial(self):
        untyped = {"id": "s-birth", "title": "Births of Nancy"}
        found = assess([question()], docs(sources=[untyped]), matrix("consulted", "todo"))
        self.assertEqual(found[0]["level"], "partial")
        self.assertEqual(states(found)["exhaustive"], "partial")
        self.assertEqual(found[0]["elements"]["exhaustive"]["lacks"], [{"why": "holes", "ids": ["type1"]}])
        self.assertEqual(found[0]["elements"]["citations"]["lacks"], [{"why": "untyped", "ids": ["s-birth"]}])

    def test_not_conform(self):
        q = question(status="open", persons=[])
        del q["window"]
        found = assess([q], m=matrix(unknown=["window"]))
        self.assertEqual(found[0]["level"], "not_conform")
        self.assertEqual(states(found), {"exhaustive": "missing", "citations": "missing", "analysis": "established",
                                         "conflicts": "established", "argument": "missing"})
        self.assertEqual([x["why"] for e in found[0]["elements"].values() for x in e["lacks"]],
                         ["unknown", "no-facts", "no-conclusion"])

    def test_counts(self):
        found = assess([question(), question("Q2", status="open")], m={"questions": matrix("consulted")["questions"]
                                                                        + matrix("todo", qid="Q2")["questions"]})
        self.assertEqual(S.counts(found), {"conform": 1, "partial": 0, "not_conform": 1})


class Elements(unittest.TestCase):
    def test_a_country_without_catalogue_is_not_exhaustive(self):
        # T235: Vianden (Luxembourg): the catalogue expects nothing there, the orchestrator says what was searched
        row = {"type": "catalogue_lu", "state": "todo", "places": ["vianden"], "years": [1795, 1805],
               "repositories": []}
        m = {"questions": [{"id": "Q1", "unknown": [], "rows": [row]}]}
        found = assess([question(places=["vianden"])], m=m)
        self.assertEqual(states(found)["exhaustive"], "missing")
        self.assertEqual(found[0]["elements"]["exhaustive"]["lacks"], [{"why": "holes", "ids": ["catalogue_lu"]}])
        m["questions"][0]["rows"] = [dict(row, state="not_applicable", reason="civil registers of Vianden, ANLux")]
        self.assertEqual(states(assess([question(places=["vianden"])], m=m))["exhaustive"], "established")

    def test_citations(self):
        incomplete = dict(TYPED, repository="")
        self.assertEqual(states(assess([question()], docs(sources=[incomplete])))["citations"], "partial")
        lost = docs(facts=[fact("jean-roy-1800.birth", source="s-unknown")])
        found = assess([question()], lost)
        self.assertEqual(found[0]["elements"]["citations"],
                         {"state": "missing", "lacks": [{"why": "no-citation", "ids": ["jean-roy-1800.birth"]}]})
        hypothesis = docs(facts=[fact("jean-roy-1800.birth", status="hypothesis", source=None)])
        self.assertEqual(states(assess([question()], hypothesis))["citations"], "established")

    def test_the_excerpt_of_a_concluding_record(self):
        """TRUST2-T3: without its excerpt, partial (missing in strict); an excerpt not found, missing."""
        def run(state, strict=False, **extra):
            d = docs(facts=[fact("jean-roy-1800.birth", **extra)])
            return S.assess({"id": RID, "questions": [question()]}, d, matrix("consulted"),
                            excerpt_state=lambda f: state, strict=strict)[0]["elements"]["citations"]

        self.assertEqual(run("ok"), {"state": "partial",
                                     "lacks": [{"why": "no-excerpt", "ids": ["jean-roy-1800.birth"]}]})
        self.assertEqual(run("ok", strict=True)["state"], "missing")
        quoted = {"kind": "transcription", "lines": [1, 1], "text": "x", "sha256": "0" * 64}
        self.assertEqual(run("ok", excerpt=quoted)["state"], "established")
        self.assertEqual(run("unseen", excerpt=quoted)["state"], "established")
        self.assertEqual(run("broken", excerpt=quoted),
                         {"state": "missing", "lacks": [{"why": "excerpt-broken", "ids": ["jean-roy-1800.birth"]}]})

    def test_a_question_not_answered_rests_on_the_research_facts(self):
        found = assess([question(status="unresolved", reason="no act")])
        self.assertEqual(states(found)["citations"], "established")
        self.assertEqual(states(found)["argument"], "not_applicable")

    def test_conflicts(self):
        clash = [fact("jean-roy-1800.birth"), fact("jean-roy-1800.birth2", "1803", type="birth")]
        found = assess([question()], docs(facts=clash))
        self.assertEqual((states(found)["analysis"], states(found)["conflicts"]), ("missing", "missing"))
        self.assertEqual(found[0]["elements"]["analysis"]["lacks"],
                         [{"why": "unanalysed", "ids": ["jean-roy-1800.birth"]}])
        a = {"id": "an-jean-roy-1800-birth", "person": "jean-roy-1800", "fact_kind": "birth", "status": "open",
             "items": [{"fact": "jean-roy-1800.birth", "asserts": "1800", "source": "s-birth"},
                       {"fact": "jean-roy-1800.birth2", "asserts": "1803", "source": "s-birth"}]}
        found = assess([question()], docs(facts=clash, analyses=[a]))
        self.assertEqual((states(found)["analysis"], states(found)["conflicts"]), ("partial", "missing"))
        self.assertEqual(found[0]["elements"]["analysis"]["lacks"], [{"why": "axes", "ids": [a["id"]]}])
        a = dict(a, status="resolved", items=[dict(i, axes=dict(DIRECT)) for i in a["items"]],
                 resolution={"fact": "jean-roy-1800.birth", "reasoning": "the act itself"})
        found = assess([question(status="open", persons=["jean-roy-1800"])], docs(facts=clash, analyses=[a]))
        self.assertEqual((states(found)["analysis"], states(found)["conflicts"]), ("established", "established"))
        found = assess([question()], docs(facts=clash, analyses=[a]))
        self.assertEqual(states(found)["argument"], "missing")   # the evidence disagrees: GPS-D8
        self.assertEqual(found[0]["elements"]["argument"]["lacks"], [{"why": "no-argument", "ids": ["conflict"]}])

    def test_argument(self):
        q = question(kind="identity")
        self.assertEqual(states(assess([q]))["argument"], "missing")
        self.assertEqual(states(assess([q], docs(proofs=[contradictor("submitted")])))["argument"], "partial")
        self.assertEqual(states(assess([q], docs(proofs=[contradictor(reviewer="session")])))["argument"], "partial")
        self.assertEqual(states(assess([q], docs(proofs=[contradictor()])))["argument"], "established")

    def test_chronology(self):
        late = docs(facts=[fact("jean-roy-1800.birth"), fact("jean-roy-1800.death", "1790", type="death")])
        found = assess([question(conclusion=["jean-roy-1800.birth", "jean-roy-1800.death"])], late)
        self.assertEqual(states(found)["analysis"], "partial")
        self.assertEqual(found[0]["elements"]["analysis"]["lacks"][0]["why"], "chronology")
        noted = docs(facts=[fact("jean-roy-1800.birth"),
                            fact("jean-roy-1800.death", "1790", type="death", note="the year is misread")])
        self.assertEqual(states(assess([question(conclusion=["jean-roy-1800.birth", "jean-roy-1800.death"])],
                                       noted))["analysis"], "established")

    def test_a_concluding_fact_without_its_three_axes(self):
        # T243: a fact that concludes an answered question gives its three axes; until then, element 3 is partial
        bare = docs(facts=[fact("jean-roy-1800.birth", evidence=None)])
        found = assess([question()], bare)
        self.assertEqual(found[0]["elements"]["analysis"],
                         {"state": "partial", "lacks": [{"why": "unclassified", "ids": ["jean-roy-1800.birth"]}]})
        self.assertEqual(found[0]["level"], "partial")
        two = docs(facts=[fact("jean-roy-1800.birth", evidence={"source": "original", "information": "primary"})])
        self.assertEqual(assess([question()], two)[0]["elements"]["analysis"]["lacks"],
                         [{"why": "unclassified", "ids": ["jean-roy-1800.birth"]}])
        # its three axes given, the element is established again
        self.assertEqual(states(assess([question()]))["analysis"], "established")
        # a question not answered asks nothing of the facts it may rest on
        self.assertEqual(states(assess([question(status="open")], bare))["analysis"], "established")
        from probandia.i18n import Translator

        lack = found[0]["elements"]["analysis"]["lacks"][0]
        self.assertEqual(S.describe(lack, Translator("en")), "concluding facts without their three axes "
                                                             "(source, information, evidence): jean-roy-1800.birth")
        self.assertIn("trois axes", S.describe(lack, Translator("fr")))

    def test_a_general_question(self):
        general = question(kind="general")
        del general["window"], general["places"]
        found = assess([general], m=matrix(unknown=["window", "places"]))
        self.assertEqual(states(found)["exhaustive"], "missing")   # it carries the conclusion alone
        self.assertEqual(found[0]["elements"]["exhaustive"]["lacks"], [{"why": "general-alone", "ids": []}])
        found = assess([general, question("Q2")], m={"questions": matrix(unknown=["window", "places"])["questions"]
                                                     + matrix("consulted", qid="Q2")["questions"]})
        self.assertEqual(states(found)["exhaustive"], "established")

    def test_the_report_claims_no_conformity(self):
        # T239: in English, the count of the elements established, and what the engine does not judge
        from probandia.report import content

        found = assess([question()])[0]
        md = content.standard_md(found, set(), lambda s: s)
        self.assertTrue(md.startswith("**Elements of the Genealogical Proof Standard established: 4 of 4**"), md)
        self.assertIn("is the genealogist's judgement", md)
        self.assertNotIn("onformity", md)
        self.assertTrue(content.method_md([], lambda s: s).startswith("Written with the help of AI agents"))

    def test_describe(self):
        from probandia.i18n import Translator

        lack = {"why": "no-argument", "ids": ["identity", "conflict"]}
        self.assertEqual(S.describe(lack, Translator("en")),
                         "no proof argument accepted, though one is required (identity, conflict)")
        self.assertEqual(S.short(lack), "no-argument:identity,conflict")
        self.assertIn("identité", S.describe(lack, Translator("fr")))


class Commands(unittest.TestCase):
    """``verify --standard`` shows the table by question; ``status`` sums it up."""

    setUp = sample.Sample.setUp
    call = sample.Sample.call
    value = sample.Sample.value

    def test_verify_standard(self):
        code, out = self.call("question", "add", "When was Louis MARCHAND born?", "--research", sample.RID)
        self.assertEqual(code, 0, out)
        code, out = self.call("verify", sample.RID, "--standard")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "QUESTIONS"), self.value(out, "NOT_CONFORM")), ("2", "2"))
        self.assertIn("Q2=not_conform exhaustive=missing citations=", out)
        self.assertIn("Q2.argument=no-conclusion", out)
        code, out = self.call("verify", sample.RID, "--standard", "--json")
        data = json.loads(out)["data"]
        self.assertEqual([q["question"] for q in data["questions"]], ["Q1", "Q2"])
        self.assertIn("no conclusion yet: the question is open", [x["lacks"] for x in data["lacks"]])
        code, out = self.call("verify", sample.RID, "--standard", env={"PROBANDIA_OUTPUT": "human"})
        self.assertIn("0 of 2 questions conform", out)
        self.assertIn("Reasonably exhaustive search", out)

    def test_strict(self):
        """GPS-D13: with proof.standard strict, a question that does not conform fails verify --standard and keeps
        the research open."""
        self.call("question", "add", "When was Louis MARCHAND born?", "--research", sample.RID)
        self.assertEqual(self.call("config", "set", "proof.standard", "strict")[0], 0)
        code, out = self.call("verify", sample.RID, "--standard")
        self.assertEqual((code, out.splitlines()[0]), (1, "STATUS=FAIL"))
        for q in ("Q1", "Q2"):
            self.call("question", "unresolved", q, "--reason", "no act found yet", "--research", sample.RID)
        self.call("render", sample.RID)
        with unittest.mock.patch("probandia.verify.run", return_value=[("V-1", "PASS", "")]):
            code, out = self.call("close", sample.RID)
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=not-conform", out)
        self.assertIn("Q2=exhaustive=missing", out)
        self.assertEqual(self.research.meta()["status"], "open")

    def test_the_box_in_the_report(self):
        """GPS8-T2: a box at the head of each question, in Markdown and in each shipped template."""
        import os

        self.call("question", "add", "When was Louis MARCHAND born?", "--research", sample.RID)
        folder = os.path.join(self.research.folder, "report")
        for tid in ("default", "print", "family-book", "high-contrast", "habillage"):
            code, out = self.call("render", sample.RID, "--template", tid)
            self.assertEqual(code, 0, out)
            with open(os.path.join(folder, "report.html"), encoding="utf-8") as fh:
                html = fh.read()
            box = html[html.index('<aside class="standard" role="note"'):]
            # T239: the elements the data establish, counted; no claim of conformity, which a genealogist judges
            self.assertIn("Éléments du Genealogical Proof Standard établis : 3 sur 5", box[:box.index("</aside>")])
            self.assertIn("relève du jugement du généalogiste", box[:box.index("</aside>")])
            self.assertIn("pas encore de conclusion : la question est ouverte", box)
            self.assertNotIn("onformité au Genealogical Proof Standard", html)
        with open(os.path.join(folder, "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertNotIn("onformité au Genealogical Proof Standard", md)
        self.assertIn("Rédigé avec l'aide d'agents d'IA", md[md.index('<a id="s-method">'):])
        q2 = md[md.index('<a id="s-standard-q2">'):]
        self.assertIn("Q2 : les éléments du Genealogical Proof Standard", q2)
        self.assertIn("| Recherche raisonnablement exhaustive | manquant |", q2)
        self.assertLess(md.index('<a id="s-standard-q1">'), md.index('<a id="s-standard-q2">'))

    def test_status(self):
        code, out = self.call("status")
        self.assertNotIn("standard=", out)   # a research without structured questions
        self.call("question", "add", "When was Louis MARCHAND born?", "--research", sample.RID)
        code, out = self.call("status")
        self.assertIn(f"standard={sample.RID} conform=0 partial=0 not_conform=2", out)
