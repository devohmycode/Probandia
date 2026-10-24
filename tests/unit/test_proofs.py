"""Proof arguments and their review by the contradictor (GPS5)."""
import os
import unittest

from probandia import events
from probandia.research import Research
from probandia.util import yamlio
from tests.unit import test_data_layer
from tests.unit.test_data_layer import RID, Project

PARTS = {"question": "Who were the parents of Victor Hugo?", "sources": "The birth record of 1802.",
         "analysis": "An original, made by the father.", "correlation": "No other evidence disagrees.",
         "conflicts": "None.", "conclusion": "Léopold Hugo is the father."}


def proof(state="submitted", rounds=(), **extra):
    p = {"id": "pf-q1-" + RID, "research": RID, "question": "Q1", "conclusion": ["victor-hugo-1802.birth"],
         "parts": dict(PARTS), "review": {"state": state, "rounds": list(rounds)}}
    p.update(extra)
    return p


class Apply(Project):
    """GPS5-T1: a proof argument goes through apply, into index/proofs.yaml, with its event."""

    assertRejected = test_data_layer.Apply.assertRejected

    def test_recorded_then_updated(self):
        (code, out), _doc = self.propose_and_apply(proofs=[proof()])
        self.assertEqual(code, 0, out)
        reviewed = proof("objected", [{"date": "2026-10-04T10:00:00Z", "reviewer": "contradictor", "objections": [
            {"n": 1, "text": "A namesake in Nancy.", "state": "open"}]}])
        self.assertEqual(self.propose_and_apply(proofs=[reviewed])[0][0], 0)
        found = self.index("proofs")["proofs"]
        self.assertEqual((len(found), found[0]["review"]["state"]), (1, "objected"))
        log = events.read(Research(self.dir, "hugo", RID).events_path)
        self.assertEqual([e["payload"]["state"] for e in log if e["type"] == "proof.recorded"],
                         ["submitted", "objected"])

    def test_rejections(self):
        self.assertRejected("no fact victor-hugo-1802.death",
                            proofs=[proof(conclusion=["victor-hugo-1802.death"])])
        self.assertRejected("no analysis an-x", proofs=[proof(analyses=["an-x"])])
        self.assertRejected("accepted with objection(s) still open: 1", proofs=[proof("accepted", [
            {"date": "2026-10-04T10:00:00Z", "reviewer": "contradictor", "objections": [{"n": 1, "text": "x", "state": "open"}]}])])

    def test_no_file_until_a_proof(self):
        from probandia.indexes import FamilyIndexes

        self.assertFalse(os.path.exists(os.path.join(self.family, "index", "proofs.yaml")))
        self.assertEqual(FamilyIndexes(self.dir, "hugo").items("proofs"), [])


class Required(unittest.TestCase):
    """GPS5-T2: identity, indirect evidence and disagreeing evidence each require an argument; direct evidence
    without conflict does not."""

    PERSONS = [{"id": "jean-roy-1800", "facts": [
        {"id": "jean-roy-1800.birth", "type": "birth", "status": "record",
         "evidence": {"source": "original", "information": "primary", "evidence": "direct"}},
        {"id": "jean-roy-1800.death", "type": "death", "status": "record",
         "evidence": {"source": "original", "information": "secondary", "evidence": "indirect"}}]}]

    def q(self, kind="birth", conclusion=("jean-roy-1800.birth",)):
        return {"id": "Q1", "text": "x", "type": kind, "status": "answered", "conclusion": list(conclusion)}

    def test_each_case(self):
        from probandia.proof import arguments as A

        agree = {"id": "an-1", "person": "jean-roy-1800", "fact_kind": "birth", "status": "resolved",
                 "items": [{"fact": "jean-roy-1800.birth", "asserts": "1800"}, {"asserts": " 1800 "}]}
        clash = dict(agree, id="an-2", items=[{"fact": "jean-roy-1800.birth", "asserts": "1800"}, {"asserts": "1802"}])
        self.assertEqual(A.required(self.q(), self.PERSONS, []), [])
        self.assertEqual(A.required(self.q(), self.PERSONS, [agree]), [])
        self.assertEqual(A.required(self.q("identity"), self.PERSONS, []), ["identity"])
        self.assertEqual(A.required(self.q(conclusion=["jean-roy-1800.death"]), self.PERSONS, []), ["indirect"])
        self.assertEqual(A.required(self.q(), self.PERSONS, [clash]), ["conflict"])
        named = dict(clash, items=[{"asserts": "1800"}, {"asserts": "1802"}], question="Q1")
        self.assertEqual(A.required(self.q(conclusion=[]), self.PERSONS, [named]), ["conflict"])

    def test_negative_evidence(self):
        # T237: "died before the census of 1851, where he no longer appears": an absence argues, it does not show
        from probandia.proof import arguments as A

        persons = [{"id": "jean-roy-1800", "facts": [
            {"id": "jean-roy-1800.death", "type": "death", "status": "index",
             "evidence": {"source": "derivative", "information": "indeterminate", "evidence": "negative"}}]}]
        self.assertEqual(A.required(self.q("death", conclusion=["jean-roy-1800.death"]), persons, []), ["negative"])

    def test_ids_and_states(self):
        from probandia.proof import arguments as A

        self.assertEqual(A.proof_id("Q2", "2026-09-30-x"), "pf-q2-2026-09-30-x")
        p = proof("objected", [{"date": "2026-10-04T10:00:00Z", "reviewer": "contradictor", "objections": [
            {"n": 1, "text": "a", "state": "answered"}, {"n": 2, "text": "b", "state": "open"}]}])
        self.assertEqual([o["n"] for o in A.open_objections(p)], [2])
        self.assertIsNone(A.accepted([p], RID, "Q1"))
        self.assertIs(A.accepted([dict(p, review={"state": "accepted", "rounds": []})], RID, "Q1")["question"], "Q1")


RETURNED = """1. objection: A namesake, Victor Hugot, was born in Nancy in 1801.
   fact: victor-hugo-1802.birth
   settle: the Nancy birth record, and his death

- Objection: The father's name is spelled Hugot in the birth record.
  What would settle it: the father's own signature
"""


class Objections(unittest.TestCase):
    def test_parse(self):
        from probandia.cli.proof_cmd import parse_objections

        found = parse_objections(RETURNED)
        self.assertEqual(found[0], {"text": "A namesake, Victor Hugot, was born in Nancy in 1801.",
                                    "fact": "victor-hugo-1802.birth",
                                    "would_settle": "the Nancy birth record, and his death"})
        self.assertEqual(found[1]["would_settle"], "the father's own signature")
        self.assertEqual(parse_objections("None."), [])
        self.assertEqual(parse_objections("A plain remark\non two lines"), [{"text": "A plain remark on two lines"}])


class Cycle(Project):
    """GPS5-T3: draft, submit, review, accept refused, answer, accept; a reference rendering of an objected
    argument."""

    def value(self, out, key):
        return next(line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "="))

    def test_full_cycle(self):
        from probandia.util import yamlio
        from tests.unit.test_human import golden

        code, out = self.call("proof", "--research", RID)
        self.assertIn("question=Q1 needs=- proof=-", out)
        self.call("question", "answer", "Q1", "--conclusion", "victor-hugo-1802.birth", "--research", RID)
        code, out = self.call("proof", "draft", "Q1", "--research", RID)
        self.assertEqual(code, 0, out)
        pid, path = self.value(out, "PROOF"), os.path.join(self.dir, self.value(out, "FILE"))
        doc = yamlio.load(path)
        self.assertIn("Archives municipales de Besançon", doc["parts"]["sources"])
        self.assertIn("incomplete-proof", self.call("proof", "submit", pid, "--research", RID)[1])
        doc["parts"].update(analysis="The birth record is an original, declared by the father.",
                            conflicts="None.", conclusion="Léopold Hugo is the father of Victor Hugo.",
                            correlation="No other evidence names a father.",
                            sources=doc["parts"]["sources"] or "The birth record.")
        doc["conclusion"] = ["victor-hugo-1802.birth"]
        yamlio.dump(path, doc)
        code, out = self.call("proof", "submit", pid, "--research", RID)
        self.assertEqual(code, 0, out)
        self.assertIn("STATE=submitted", out)
        returned = os.path.join(self.tmp.name, "objections.txt")
        with open(returned, "w", encoding="utf-8") as fh:
            fh.write(RETURNED)
        self.assertEqual(self.call("proof", "review", pid, "--research", RID, "--objections", returned)[0], 2)  # --by
        code, out = self.call("proof", "review", pid, "--research", RID, "--objections", returned,
                              "--by", "contradictor")
        self.assertIn("STATE=objected", out)
        self.assertIn("REVIEWED_BY=contradictor", out)
        golden(self, "proof-objected", self.call("proof", "show", pid, "--research", RID, "--output-format",
                                                 "human", "--width", "100", env={"NO_COLOR": "1"})[1])
        code, out = self.call("proof", "accept", pid, "--research", RID)
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=open-objections", out)
        self.call("proof", "answer", pid, "1", "--research", RID, "--text",
                  "The Nancy Victor Hugot died in 1803 (death record, act 14).")
        self.assertEqual(self.call("proof", "answer", pid, "2", "--research", RID, "--dismiss")[0], 2)  # no reason
        self.call("proof", "answer", pid, "2", "--research", RID, "--dismiss", "--reason", "a known variant")
        code, out = self.call("proof", "accept", pid, "--research", RID)
        self.assertEqual(code, 0, out)
        stored = self.index("proofs")["proofs"][0]
        self.assertEqual(stored["review"]["state"], "accepted")
        self.assertEqual(stored["review"]["rounds"][0]["returned"], RETURNED.strip())
        self.assertEqual([o["state"] for o in stored["review"]["rounds"][0]["objections"]], ["answered", "dismissed"])

    def test_only_the_orchestrator_or_the_session_records(self):
        from probandia.util import yamlio

        code, out = self.call("proof", "draft", "Q1", "--research", RID)
        path = os.path.join(self.dir, self.value(out, "FILE"))
        doc = yamlio.load(path)
        doc["parts"].update({k: "x" for k in doc["parts"]})
        yamlio.dump(path, doc)
        code, out = self.call("proof", "submit", self.value(out, "PROOF"), "--research", RID, "--agent", "researcher")
        self.assertIn("REASON=not-allowed", out)

    def test_accept_needs_a_review(self):
        self.propose_and_apply(proofs=[proof()])
        code, out = self.call("proof", "accept", "pf-q1-" + RID, "--research", RID)
        self.assertIn("REASON=not-reviewed", out)


class Contradictor(unittest.TestCase):
    """GPS5-T4: the contradictor returns its review in the blocks proof review reads; it stays read-only."""

    def test_the_format_it_is_given_is_the_one_read(self):
        import re

        from probandia.cli.proof_cmd import parse_objections
        from tests import ROOT

        with open(os.path.join(ROOT, "agents", "contradictor.md"), encoding="utf-8") as fh:
            text = fh.read()
        for key in ("objection:", "fact:", "settle:", "`none`", "proof show"):
            self.assertIn(key, text)
        self.assertNotIn("Write", re.search(r"^tools: (.*)$", text, re.M).group(1))
        sample = "objection: a homonym\nfact: a.birth\nsettle: his death record\n\nobjection: b\n"
        self.assertEqual([o["text"] for o in parse_objections(sample)], ["a homonym", "b"])


class Rule(Project):
    """GPS5-T6: V-16 asks an accepted argument of an answered question that needs one; a review by the same
    session only is not independent."""

    def v16(self, standard="off"):
        from probandia import verify

        class Config:
            def get(self, key):
                return standard if key == "proof.standard" else None

        return verify.run(self.dir, Research(self.dir, "hugo", RID), Config(), ["V-16"])[0][1:]

    def answer_as_identity(self):
        from probandia import lifecycle
        from probandia.proof import questions as Q

        res = Research(self.dir, "hugo", RID)
        qs, _q = Q.edit(Q.of(res.meta()), "Q1", kind="identity")
        qs, _q = Q.settle(qs, "Q1", "answered", conclusion=["victor-hugo-1802.birth"])
        lifecycle.update_meta(res, questions=qs)

    def test_each_case(self):
        self.assertEqual(self.v16(), ("PASS", ""))   # Q1 open: nothing asked yet
        self.answer_as_identity()
        self.assertEqual(self.v16(), ("WARN", "Q1 needs a proof argument (identity): none accepted"))
        self.assertEqual(self.v16("strict")[0], "FAIL")
        round_ = {"date": "2026-10-04T10:00:00Z", "reviewer": "session", "objections": []}
        self.assertEqual(self.propose_and_apply(proofs=[proof("accepted", [round_])])[0][0], 0)
        self.assertEqual(self.v16(),
                         ("WARN", f"Q1: pf-q1-{RID} was reviewed by the same session only, not independently"))
        self.assertEqual(self.v16("strict")[0], "FAIL")
        independent = dict(round_, reviewer="contradictor")
        self.assertEqual(self.propose_and_apply(proofs=[proof("accepted", [round_, independent])])[0][0], 0)
        self.assertEqual(self.v16("strict"), ("PASS", ""))

    def test_a_conclusion_drawn_from_an_absence(self):
        # T237: a birth question answered by a fact whose evidence is negative needs an argument
        from probandia import lifecycle
        from probandia.proof import questions as Q

        doc = self.index("persons")
        for p in doc["persons"]:
            for f in p.get("facts") or []:
                if f["id"] == "victor-hugo-1802.birth":
                    f["evidence"] = {"source": "original", "information": "primary", "evidence": "negative"}
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), doc)
        res = Research(self.dir, "hugo", RID)
        qs, _q = Q.settle(Q.of(res.meta()), "Q1", "answered", conclusion=["victor-hugo-1802.birth"])
        lifecycle.update_meta(res, questions=qs)
        self.assertEqual(self.v16(), ("WARN", "Q1 needs a proof argument (negative): none accepted"))
        self.assertEqual(self.v16("strict")[0], "FAIL")


class InTheReport(Project):
    """GPS5-T7: an accepted argument is a section of the report, with its six parts, a link to its correlation
    table, who reviewed it and the objections raised, set apart; one not accepted never enters."""

    def setUp(self):
        super().setUp()
        from tests.unit.test_analyses import analysis

        self.assertEqual(self.propose_and_apply(analyses=[analysis()])[0][0], 0)

    def report(self, ext="md"):
        self.assertEqual(self.call("render", RID)[0], 0)
        with open(os.path.join(self.rdir, "report", "report." + ext), encoding="utf-8") as fh:
            return fh.read()

    def test_only_accepted_and_with_its_review(self):
        from tests.unit.test_human import golden

        rounds = [{"date": "2026-10-04T10:00:00Z", "reviewer": "contradictor", "objections": [
            {"n": 1, "text": "A namesake was born in Nancy in 1801.", "fact": "victor-hugo-1802.birth",
             "state": "answered", "answer": "He died in 1803 (death record, act 14)."},
            {"n": 2, "text": "The father's name is spelled Hugot.", "state": "dismissed", "reason": "a known variant"}]}]
        self.assertEqual(self.propose_and_apply(proofs=[proof("objected", rounds,
                                                             analyses=["an-victor-hugo-1802-birth"])])[0][0], 0)
        self.assertNotIn("Arguments de preuve", self.report())
        self.assertEqual(self.propose_and_apply(proofs=[proof("accepted", rounds,
                                                             analyses=["an-victor-hugo-1802-birth"])])[0][0], 0)
        md = self.report()
        start = md.index("## 4 Arguments de preuve")
        chapter = md[start:md.index("<a id=\"s-evidence\">", start)]
        golden(self, "proof-report", chapter)
        self.assertIn("*Relu par le contradicteur, de façon indépendante.*", chapter)
        self.assertIn("[§ 5.1](#s-analysis-an-victor-hugo-1802-birth)", chapter)   # its correlation table
        self.assertEqual(self.call("verify", RID, "--rule", "V-6")[0], 0)
        html = self.report("html")
        self.assertIn("<blockquote>", html)
        from probandia import lifecycle

        lifecycle.update_meta(Research(self.dir, "hugo", RID), mode="living")
        self.assertIn("Argument de preuve pour Q1", self.report())
