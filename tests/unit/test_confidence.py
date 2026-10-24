"""The confidence of a conclusion (TRUST3)."""
import unittest

from probandia.proof import standard as S
from tests.unit.test_standard import RID, TYPED, contradictor, docs, fact, matrix, question

QUOTED = {"kind": "transcription", "lines": [1, 1], "text": "x", "sha256": "0" * 64}
SECONDARY = {"source": "original", "information": "secondary", "evidence": "direct"}
INDIRECT = {"source": "original", "information": "primary", "evidence": "indirect"}


def confidence(facts=None, q=None, m=None, state="ok", **more):
    d = docs(facts=facts or [fact("jean-roy-1800.birth", excerpt=QUOTED)], **more)
    found = S.assess({"id": RID, "questions": [q or question()]}, d, m or matrix("consulted"),
                     excerpt_state=(lambda f: state) if state else None)
    return found[0]["confidence"]


def whys(found):
    return [r["why"] for r in found["reasons"]]


class Levels(unittest.TestCase):
    def test_proved(self):
        self.assertEqual(confidence(), {"level": 3, "name": "proved", "reasons": []})

    def test_from_the_weakest_fact(self):
        found = confidence(facts=[fact("jean-roy-1800.birth", status="index")])
        self.assertEqual((found["name"], whys(found)), ("probable", ["index"]))
        found = confidence(facts=[fact("jean-roy-1800.birth", status="hypothesis", source=None)])
        self.assertEqual(found["name"], "possible")

    def test_only_an_answered_question(self):
        self.assertIsNone(confidence(q=question(status="open")))
        self.assertIsNone(confidence(q=question(status="unresolved", reason="x")))

    def test_without_its_excerpt_at_most_probable(self):
        found = confidence(facts=[fact("jean-roy-1800.birth")])   # the GPS citations element is partial
        self.assertEqual((found["name"], whys(found)), ("probable", ["gps-partial"]))
        self.assertEqual(confidence(state="broken")["name"], "possible")   # the GPS citations element is missing
        self.assertEqual(confidence(state="unseen")["name"], "proved")
        self.assertEqual(confidence(facts=[fact("jean-roy-1800.birth")], state=None)["name"], "proved")

    def test_an_uncertain_reading_at_most_probable(self):
        # T236: the year was overwritten, 1800 or 1806: the transcription marked it, the conclusion rests on it
        doubt = fact("jean-roy-1800.birth", excerpt=QUOTED, uncertain_reading="1800[?] (the last digit overwritten)")
        found = confidence(facts=[doubt])
        self.assertEqual((found["name"], whys(found)), ("probable", ["uncertain-reading"]))
        self.assertEqual(found["reasons"][0]["effect"], "cap")
        # the reading checked against the image again, the revision clears it
        self.assertEqual(confidence(facts=[dict(doubt, uncertain_reading=None)])["name"], "proved")
        self.assertEqual(confidence(facts=[dict(doubt, uncertain_reading=" ")])["name"], "proved")
        # with another reason down, the cap adds nothing below probable
        found = confidence(facts=[dict(doubt, status="index")])
        self.assertEqual((found["name"], whys(found)), ("probable", ["index", "uncertain-reading"]))


class Reasons(unittest.TestCase):
    def test_indirect_and_secondary(self):
        indirect = [fact("jean-roy-1800.birth", excerpt=QUOTED, evidence=dict(INDIRECT))]
        # an argument the contradictor reviewed, accepted: argued indirect evidence establishes the conclusion
        self.assertEqual(confidence(facts=indirect, proofs=[contradictor()])["name"], "proved")
        found = confidence(facts=indirect, proofs=[contradictor(reviewer="session")])
        self.assertEqual((found["name"], whys(found)), ("possible", ["indirect", "gps-partial"]))
        found = confidence(facts=[fact("jean-roy-1800.birth", excerpt=QUOTED, evidence=dict(SECONDARY))])
        self.assertEqual((found["name"], whys(found)), ("probable", ["secondary"]))

    def test_negative_evidence_is_not_indirect(self):
        # T237: an absence says so, and an argument the contradictor reviewed establishes it, as for indirect
        negative = [fact("jean-roy-1800.birth", excerpt=QUOTED,
                         evidence={"source": "original", "information": "primary", "evidence": "negative"})]
        found = confidence(facts=negative, proofs=[contradictor(reviewer="session")])
        self.assertEqual(whys(found)[0], "negative")
        self.assertNotIn("indirect", whys(found))
        self.assertEqual(confidence(facts=negative, proofs=[contradictor()])["name"], "proved")

    def test_a_second_source_confirms_secondary_information(self):
        a = {"id": "an-1", "person": "jean-roy-1800", "fact_kind": "birth", "status": "resolved", "question": "Q1",
             "items": [{"fact": "jean-roy-1800.birth", "asserts": "1800", "source": "s-birth", "axes": dict(SECONDARY)},
                       {"asserts": "1800", "source": "s-census", "axes": dict(SECONDARY)}]}
        found = confidence(facts=[fact("jean-roy-1800.birth", excerpt=QUOTED, evidence=dict(SECONDARY))],
                           analyses=[a])
        self.assertEqual(found["name"], "proved")

    @staticmethod
    def two_pieces(first=None, second=None, sources=()):
        """The confidence of a birth that secondary information gives, with a second piece that agrees."""
        a = {"id": "an-1", "person": "jean-roy-1800", "fact_kind": "birth", "status": "resolved", "question": "Q1",
             "items": [dict({"fact": "jean-roy-1800.birth", "asserts": "1800", "source": "s-birth",
                             "axes": dict(SECONDARY)}, **(first or {})),
                       dict({"asserts": "1800", "source": "s-death", "axes": dict(SECONDARY)}, **(second or {}))]}
        return confidence(facts=[fact("jean-roy-1800.birth", excerpt=QUOTED, evidence=dict(SECONDARY))],
                          analyses=[a], sources=[TYPED, *sources])

    def test_one_informant_is_not_a_second_source(self):
        # T234: the son declares the death and gives the age, then tells the same to the priest
        found = self.two_pieces({"informant": "the son"}, {"informant": "The  Son"})
        self.assertEqual((found["name"], whys(found)), ("probable", ["same-informant"]))
        found = self.two_pieces({"informant": "Élise, the widow"}, {"informant": "elise, the widow"})
        self.assertEqual(found["name"], "probable")
        self.assertEqual(self.two_pieces({"informant": "the son"}, {"informant": "the widow"})["name"], "proved")
        self.assertEqual(self.two_pieces({"informant": "the son"})["name"], "proved")   # the other one not given

    def test_a_copy_or_the_same_act_is_not_a_second_source(self):
        index = {"id": "s-death", "type": "database", "derived_from": "s-birth"}
        found = self.two_pieces(sources=[index])
        self.assertEqual((found["name"], whys(found)), ("probable", ["same-original"]))
        chain = [{"id": "s-death", "type": "database", "derived_from": "s-copy"},
                 {"id": "s-copy", "type": "book", "derived_from": "s-birth"}]   # a copy of a copy
        self.assertEqual(whys(self.two_pieces(sources=chain)), ["same-original"])
        # two sources that name the same act: the register, and its duplicate kept at the court
        act = dict(TYPED, act_no="12")
        twin = dict(TYPED, id="s-death", repository="Greffe", act_no=" 12")
        a = {"id": "an-1", "person": "jean-roy-1800", "fact_kind": "birth", "status": "resolved", "question": "Q1",
             "items": [{"fact": "jean-roy-1800.birth", "asserts": "1800", "source": "s-birth", "axes": dict(SECONDARY)},
                       {"asserts": "1800", "source": "s-death", "axes": dict(SECONDARY)}]}
        found = confidence(facts=[fact("jean-roy-1800.birth", excerpt=QUOTED, evidence=dict(SECONDARY))],
                           analyses=[a], sources=[act, twin])
        self.assertEqual(whys(found), ["same-original"])
        self.assertEqual(self.two_pieces(sources=[dict(twin, act_no="13")])["name"], "proved")

    def test_an_open_objection(self):
        open_ = contradictor("objected")
        open_["review"]["rounds"][0]["objections"] = [{"n": 1, "text": "a homonym", "state": "open"}]
        found = confidence(proofs=[open_])
        self.assertEqual((found["name"], whys(found)), ("probable", ["objection"]))

    def test_dates_that_clash(self):
        late = [fact("jean-roy-1800.birth", excerpt=QUOTED), fact("jean-roy-1800.death", "1790", type="death")]
        found = confidence(facts=late, q=question(conclusion=["jean-roy-1800.birth", "jean-roy-1800.death"]))
        self.assertIn("chronology-error", whys(found))
        self.assertLessEqual(found["level"], 1)

    def test_the_gps(self):
        found = confidence(m=matrix("consulted", "todo"))
        self.assertEqual((found["name"], whys(found)), ("probable", ["gps-partial"]))
        q = question(status="answered")
        del q["window"]
        found = confidence(q=q, m=matrix(unknown=["window"]))
        self.assertEqual((found["name"], whys(found)), ("possible", ["gps-not-conform"]))

    def test_a_concluding_fact_without_its_axes(self):
        # T243: element 3 partial, the confidence follows through gps-partial, one step and no second one
        found = confidence(facts=[fact("jean-roy-1800.birth", excerpt=QUOTED, evidence=None)])
        self.assertEqual((found["name"], whys(found)), ("probable", ["gps-partial"]))

    def test_steps_add_up(self):
        found = confidence(facts=[fact("jean-roy-1800.birth", status="index",
                                       evidence={"source": "derivative", "information": "secondary",
                                                 "evidence": "indirect"})],
                           m=matrix("consulted", "todo"), proofs=[contradictor()])
        self.assertEqual((found["name"], whys(found)), ("possible", ["index", "secondary", "gps-partial"]))
        refuted = confidence(facts=[fact("jean-roy-1800.birth", status="refuted", excerpt=QUOTED)])
        self.assertEqual(refuted["name"], "unsupported")

    def test_describe(self):
        from probandia.i18n import Translator
        from probandia.proof.confidence import describe

        self.assertEqual(describe({"why": "index", "ids": ["a.birth"]}, Translator("fr")),
                         "repose sur un index, non sur l'acte lui-même : a.birth")


class Commands(unittest.TestCase):
    """TRUST3-T2: verify --standard gives each answered question its confidence."""

    def setUp(self):
        from tests.integration import test_sample_project as sample

        sample.SampleGPS.setUp(self)
        self.rid = sample.GPS_RID

    def call(self, *argv, env=None):
        from tests.integration import test_sample_project as sample

        return sample.Sample.call(self, *argv, env=env)

    def test_contract_and_view(self):
        code, out = self.call("verify", self.rid, "--standard")
        self.assertEqual(code, 0, out)
        self.assertIn("- Q1.confidence=proved", out)
        self.assertIn("- Q2.confidence=proved", out)
        import json

        code, out = self.call("verify", self.rid, "--standard", "--json")
        self.assertEqual([q["confidence"] for q in json.loads(out)["data"]["questions"]], ["proved", "proved"])
        code, out = self.call("verify", self.rid, "--standard", env={"PROBANDIA_OUTPUT": "human"})
        self.assertIn("Confidence of the conclusion: proved", out)


class InTheReport(unittest.TestCase):
    """TRUST3-T3: the box of a question gives the confidence and its reasons; the table of questions, its level."""

    def test_box_and_table(self):
        from probandia.i18n import Translator
        from probandia.report import content

        t = Translator("fr")
        found = S.assess({"id": RID, "questions": [question()]},
                         docs(facts=[fact("jean-roy-1800.birth", status="index", excerpt=QUOTED)]), matrix("consulted"))
        md = content.standard_md(found[0], set(), t)
        self.assertIn("Confiance dans la conclusion : probable", md)
        self.assertIn("- repose sur un index, non sur l'acte lui-même : jean-roy-1800.birth", md)
        hidden = content.standard_md(found[0], {"jean-roy-1800"}, t)
        self.assertIn("non sur l'acte lui-même : Personne vivante", hidden)
        table = content.questions_md([question()], t, {"Q1": "probable"})
        self.assertIn("| Confiance |", table)
        self.assertIn("| probable |", table)
        self.assertNotIn("Confiance", content.questions_md([question()], t))


class Gedcom(unittest.TestCase):
    """TRUST3-T4: the confidence in the GEDCOM export: _CONF, and QUAY when the conclusion is weaker."""

    setUp = Commands.setUp
    call = Commands.call

    def export(self, kind="gedcom7"):
        import os
        import zipfile

        code, out = self.call("export", kind, "--family", "marchand")
        self.assertEqual(code, 0, out)
        path = os.path.join(self.dir, out.split("FILE=")[1].split()[0])
        if kind == "gedcom7":
            with zipfile.ZipFile(path) as z:
                return z.read("gedcom.ged").decode("utf-8-sig")
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()

    def birth(self, text):
        start = text.index("2 SOUR @S7@")
        return text[start:text.index("\n1 ", start)]

    def test_proved_then_weaker(self):
        import os

        from probandia.util import yamlio

        text = self.export()
        self.assertIn("2 TAG _CONF https://probandia.replit.app/gedcom/v1/confidence", text)
        self.assertIn("3 QUAY 3", self.birth(text))
        self.assertIn("2 _CONF proved", self.birth(text))
        # without its arguments, the conflict has none: the questions do not conform, at most possible
        path = os.path.join(self.dir, "families", "marchand", "index", "proofs.yaml")
        yamlio.dump(path, {"schema": 1, "proofs": []})
        text = self.export()
        self.assertIn("3 QUAY 1", self.birth(text))
        self.assertIn("2 _CONF possible", self.birth(text))
        self.assertIn("confidence of the conclusion: possible", self.export("gedcom551"))
