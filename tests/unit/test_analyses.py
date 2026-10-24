"""The analyses of disputed conclusions: format, apply, conflicts, correlate, V-15, report, GEDCOM (GPS4)."""
import os
import unittest

from probandia import events
from probandia.research import Research
from tests.unit.test_data_layer import RID, Project
from tests.unit import test_data_layer

SRC1 = "src-01J9ZK3M4X0000000000000001"


def analysis(status="open", **extra):
    a = {"id": "an-victor-hugo-1802-birth", "person": "victor-hugo-1802", "fact_kind": "birth",
         "items": [{"source": SRC1, "fact": "victor-hugo-1802.birth", "asserts": "1802-02-26",
                    "axes": {"source": "original", "information": "primary", "evidence": "direct"}},
                   {"asserts": "1801", "informant": "the declarant of the death", "note": "age at death 83"}],
         "status": status}
    a.update(extra)
    return a


class Apply(Project):
    """GPS4-T1: an analysis goes through apply, into index/analyses.yaml, with its event."""

    assertRejected = test_data_layer.Apply.assertRejected

    def test_open_then_resolved(self):
        (code, out), _doc = self.propose_and_apply(analyses=[analysis()])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.index("analyses")["analyses"][0]["status"], "open")
        resolved = analysis("resolved", resolution={"value": "1802-02-26", "fact": "victor-hugo-1802.birth",
                                                    "reasoning": "the birth record, made by the father"})
        (code, out), _doc = self.propose_and_apply(analyses=[resolved])
        self.assertEqual(code, 0, out)
        found = self.index("analyses")["analyses"]
        self.assertEqual(len(found), 1)   # the same id: updated, not added
        self.assertEqual(found[0]["resolution"]["value"], "1802-02-26")
        log = events.read(Research(self.dir, "hugo", RID).events_path)
        self.assertEqual([e["payload"]["status"] for e in log if e["type"] == "analysis.recorded"],
                         ["open", "resolved"])

    def test_rejections(self):
        self.assertRejected("no person nobody-1800", analyses=[analysis(person="nobody-1800")])
        self.assertRejected("no fact victor-hugo-1802.death",
                            analyses=[analysis(items=[{"fact": "victor-hugo-1802.death", "asserts": "x"}])])
        self.assertRejected("resolved, but without its resolution", analyses=[analysis("resolved")])

    def test_an_empty_family_reads_no_analysis(self):
        from probandia.indexes import FamilyIndexes

        path = os.path.join(self.dir, "families", "hugo", "index", "analyses.yaml")
        self.assertFalse(os.path.exists(path))
        self.assertEqual(FamilyIndexes(self.dir, "hugo").items("analyses"), [])


def fact(fid, kind, value=None, status="record", place=None, source=SRC1, **date):
    out = {"id": fid, "type": kind, "status": status, "source": source,
           "date": dict({"value": value}, **date) if value else None}
    if place:
        out["place"] = place
    return out


PLACES = [{"id": "ornans", "current_name": "Ornans", "type": "commune", "parent": "doubs"},
          {"id": "ornans-saint-laurent", "current_name": "Saint-Laurent d'Ornans", "type": "parish", "parent": "ornans"},
          {"id": "besancon", "current_name": "Besançon", "type": "commune", "parent": "doubs"},
          {"id": "doubs", "current_name": "Doubs", "type": "county", "parent": None}]


class Conflicts(unittest.TestCase):
    """GPS4-T2: three real conflicts, two false ones."""

    def find(self, *facts):
        from probandia.proof import conflicts

        return conflicts.find([{"id": "rose-roy-1700", "facts": list(facts)}], PLACES)

    def test_two_birth_years(self):
        found = self.find(fact("rose-roy-1700.birth", "birth", "1700-03-12"),
                          fact("rose-roy-1700.birth.2", "birth", "1702"))
        self.assertEqual([(c["on"], c["values"]) for c in found], [("date", ["1700-03-12", "1702"])])

    def test_an_about_date_far_away(self):
        found = self.find(fact("rose-roy-1700.death", "death", "1760", qualifier="about"),
                          fact("rose-roy-1700.death.2", "death", "1771-05-02"))
        self.assertEqual(found[0]["values"], ["about 1760", "1771-05-02"])
        self.assertEqual(self.find(fact("rose-roy-1700.death", "death", "1760", qualifier="about"),
                                   fact("rose-roy-1700.death.2", "death", "1762-05-02")), [])

    def test_two_places(self):
        found = self.find(fact("rose-roy-1700.birth", "birth", "1700", place={"id": "ornans"}),
                          fact("rose-roy-1700.birth.2", "birth", "1700", place={"id": "besancon"}))
        self.assertEqual([(c["on"], c["facts"]) for c in found],
                         [("place", ["rose-roy-1700.birth", "rose-roy-1700.birth.2"])])

    def test_false_conflict_julian_old_style_year(self):
        # February 1700 by the gregorian count, written 1699 in the Julian old style
        self.assertEqual(self.find(fact("rose-roy-1700.baptism", "baptism", "1700-02-19"),
                                   fact("rose-roy-1700.baptism.2", "baptism", "1699", calendar="julian")), [])
        self.assertEqual(len(self.find(fact("rose-roy-1700.baptism", "baptism", "1700-02-19"),
                                       fact("rose-roy-1700.baptism.2", "baptism", "1699"))), 1)

    def test_false_conflict_parish_and_commune(self):
        self.assertEqual(self.find(fact("rose-roy-1700.baptism", "baptism", "1700", place={"id": "ornans-saint-laurent"}),
                                   fact("rose-roy-1700.baptism.2", "baptism", "1700", place={"id": "ornans"})), [])

    def test_hypotheses_and_lone_facts_do_not_conflict(self):
        self.assertEqual(self.find(fact("rose-roy-1700.birth", "birth", "1700"),
                                   fact("rose-roy-1700.birth.2", "birth", "1720", status="hypothesis")), [])
        self.assertEqual(self.find(fact("rose-roy-1700.birth", "birth", "1700"),
                                   fact("rose-roy-1700.death", "death", "1690")), [])   # P-9's matter

    def test_an_open_analysis_filled_in(self):
        from probandia.proof import conflicts

        persons = [{"id": "rose-roy-1700", "facts": [
            dict(fact("rose-roy-1700.birth", "birth", "1700-03-12"),
                 evidence={"source": "original", "information": "primary", "evidence": "direct"}),
            fact("rose-roy-1700.birth.2", "birth", "1702", source=None)]}]
        groups = conflicts.unanalysed(persons, PLACES, [])
        a = conflicts.open_analysis(groups[("rose-roy-1700", "birth")], persons, question="Q1", research="r1")
        self.assertEqual(a["id"], "an-rose-roy-1700-birth")
        self.assertEqual([(i["fact"], i["asserts"], i.get("axes", {}).get("information")) for i in a["items"]],
                         [("rose-roy-1700.birth", "1700-03-12", "primary"), ("rose-roy-1700.birth.2", "1702", None)])
        from probandia.util.schema import validate_document

        validate_document("analyses", {"schema": 1, "analyses": [a]})
        self.assertEqual(conflicts.unanalysed(persons, PLACES, [a]), {})   # covered once analysed


class Correlate(Project):
    """GPS4-T3: correlate lists the conflicts, opens their analyses and resolves one, through proposals."""

    def second_birth(self):
        (code, out), _doc = self.propose_and_apply(
            facts=[fact("victor-hugo-1802.birth.2", "birth", "1800", status="index")])
        self.assertEqual(code, 0, out)

    def value(self, out, key):
        return next(line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "="))

    def human(self, *argv):
        return self.call(*argv, "--output-format", "human", "--width", "100", env={"NO_COLOR": "1"})[1]

    def test_list_open_resolve(self):
        from tests.unit.test_human import golden

        code, out = self.call("correlate", "--research", RID)
        self.assertIn("CONFLICTS=0", out)
        self.second_birth()
        code, out = self.call("correlate", "--research", RID)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("conflict=victor-hugo-1802 birth date: 1802-02-26 / 1800", out)
        code, out = self.call("correlate", "open", "--research", RID, "--question", "q1")
        self.assertEqual(code, 0, out)
        code, out = self.call("apply", self.value(out, "PROPOSAL"), "--agent", "orchestrator")
        self.assertEqual(code, 0, out)
        a = self.index("analyses")["analyses"][0]
        self.assertEqual((a["id"], a["status"], a["question"], len(a["items"])),
                         ("an-victor-hugo-1802-birth", "open", "Q1", 2))
        golden(self, "correlate-open", self.human("correlate", "--research", RID))
        code, out = self.call("correlate", "resolve", "an-victor-hugo-1802-birth", "--research", RID,
                              "--value", "1802-02-26", "--fact", "victor-hugo-1802.birth",
                              "--reasoning", "the birth record, declared by the father the day after the birth")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.call("apply", self.value(out, "PROPOSAL"), "--agent", "orchestrator")[0], 0)
        self.assertEqual(self.index("analyses")["analyses"][0]["resolution"]["fact"], "victor-hugo-1802.birth")
        golden(self, "correlate-resolved", self.human("correlate", "--research", RID))
        self.assertIn("OPENED=0", self.call("correlate", "open", "--research", RID)[1])

    def test_refusals(self):
        self.assertEqual(self.call("correlate", "resolve", "--research", RID)[0], 2)
        self.assertIn("REASON=no-analysis", self.call("correlate", "resolve", "an-x", "--research", RID,
                                                      "--value", "1", "--reasoning", "r")[1])
        self.assertEqual(self.call("correlate", "--research", RID, "--question", "Q9")[0], 2)


class Axes(Project):
    """GPS4-T4: once proof.standard is not off, an analysis whose evidence lacks its axes is flagged."""

    def test_flagged_only_when_the_standard_is_checked(self):
        (code, out), _doc = self.propose_and_apply(analyses=[analysis()])
        self.assertEqual(code, 0, out)
        code, out = self.call("correlate", "--research", RID)
        self.assertIn("STATUS=OK", out)
        self.assertNotIn("WITHOUT_AXES", out)
        self.call("config", "set", "proof.standard", "warn")
        code, out = self.call("correlate", "--research", RID)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("WITHOUT_AXES=1", out)
        self.assertIn("three axes (source, information, evidence): an-victor-hugo-1802-birth", out)

    def test_the_researcher_is_told(self):
        from tests import ROOT

        with open(os.path.join(ROOT, "agents", "researcher.md"), encoding="utf-8") as fh:
            self.assertIn("`evidence` axes", fh.read())


class Rule(Project):
    """GPS4-T5: V-15 warns of an unanalysed conflict, of an open analysis whose question is answered, and (with
    the standard on) of evidence without its axes; strict fails."""

    def v15(self, standard="off"):
        from probandia import verify

        class Config:
            def get(self, key):
                return standard if key == "proof.standard" else None

        return verify.run(self.dir, Research(self.dir, "hugo", RID), Config(), ["V-15"])[0][1:]

    def test_each_case(self):
        self.assertEqual(self.v15(), ("PASS", ""))
        (code, out), _doc = self.propose_and_apply(
            facts=[fact("victor-hugo-1802.birth.2", "birth", "1800", status="index")])
        self.assertEqual(code, 0, out)
        status, message = self.v15()
        self.assertEqual((status, message), ("WARN", "victor-hugo-1802 birth: 1 conflict(s) without an analysis"))
        self.assertEqual(self.v15("strict")[0], "FAIL")
        full = analysis(question="Q1", items=[
            {"fact": "victor-hugo-1802.birth", "asserts": "1802-02-26",
             "axes": {"source": "original", "information": "primary", "evidence": "direct"}},
            {"fact": "victor-hugo-1802.birth.2", "asserts": "1800",
             "axes": {"source": "derivative", "information": "secondary", "evidence": "direct"}}])
        self.assertEqual(self.propose_and_apply(analyses=[full])[0][0], 0)
        self.assertEqual(self.v15("strict"), ("PASS", ""))
        from probandia import lifecycle
        from probandia.proof import questions as Q

        res = Research(self.dir, "hugo", RID)
        qs, _q = Q.settle(Q.of(res.meta()), "Q1", "answered", conclusion=["victor-hugo-1802.birth"])
        lifecycle.update_meta(res, questions=qs)
        self.assertEqual(self.v15(), ("WARN", "an-victor-hugo-1802-birth: open, but question Q1 is answered"))
        bare = dict(full, items=[dict(i, axes={}) for i in full["items"]], status="resolved",
                    resolution={"value": "1802-02-26", "reasoning": "the birth record"})
        self.assertEqual(self.propose_and_apply(analyses=[bare])[0][0], 0)
        self.assertEqual(self.v15(), ("PASS", ""))   # the axes are asked only once the standard is on
        self.assertEqual(self.v15("warn"),
                         ("WARN", "an-victor-hugo-1802-birth: 2 piece(s) of evidence without their three axes"))


class Divergence(Project):
    """FL5-T2 (FL-D9): a divergence left unresolved on purpose, with its reason; V-15 accepts it while the
    question is open or unresolved, refuses it once the question is answered; the report says so."""

    def value(self, out, key):
        return next(line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "="))

    def v15(self):
        from probandia import verify

        class Config:
            def get(self, key):
                return "off" if key == "proof.standard" else None

        return verify.run(self.dir, Research(self.dir, "hugo", RID), Config(), ["V-15"])[0][1:]

    def settle(self, status, **kw):
        from probandia import lifecycle
        from probandia.proof import questions as Q

        res = Research(self.dir, "hugo", RID)
        qs, _q = Q.settle(Q.of(res.meta()), "Q1", status, **kw)
        lifecycle.update_meta(res, questions=qs)

    def test_left_unresolved_on_purpose(self):
        (code, out), _doc = self.propose_and_apply(
            facts=[fact("victor-hugo-1802.birth.2", "birth", "1800", status="index")])
        self.assertEqual(code, 0, out)
        code, out = self.call("correlate", "open", "--research", RID, "--question", "q1")
        self.assertEqual(self.call("apply", self.value(out, "PROPOSAL"), "--agent", "orchestrator")[0], 0)
        self.assertEqual(self.call("correlate", "diverge", "an-victor-hugo-1802-birth", "--research", RID)[0], 2)
        code, out = self.call("correlate", "diverge", "an-victor-hugo-1802-birth", "--research", RID,
                              "--reason", "two records disagree and no third decides")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.call("apply", self.value(out, "PROPOSAL"), "--agent", "orchestrator")[0], 0)
        a = self.index("analyses")["analyses"][0]
        self.assertEqual((a["status"], a["reason"]), ("divergent", "two records disagree and no third decides"))
        out = self.call("correlate", "--research", RID)[1]
        self.assertEqual((self.value(out, "DIVERGENT"), self.value(out, "RESOLVED")), ("1", "0"))
        self.assertEqual(self.v15(), ("PASS", ""))
        self.settle("unresolved", reason="the two records cannot be reconciled")
        self.assertEqual(self.v15(), ("PASS", ""))
        self.settle("answered", conclusion=["victor-hugo-1802.birth"])
        self.assertEqual(self.v15(), ("WARN", "an-victor-hugo-1802-birth: divergent, but question Q1 is answered"))
        self.assertEqual(self.call("render", RID)[0], 0)
        with open(os.path.join(self.rdir, "report", "report.md"), encoding="utf-8") as fh:
            self.assertIn("**Divergence non tranchée : two records disagree and no third decides**", fh.read())

    def test_a_divergent_analysis_needs_its_reason(self):
        (code, out), _doc = self.propose_and_apply(analyses=[analysis("divergent")])
        self.assertNotEqual(code, 0)
        self.assertIn("divergent, but without the reason", out)


class InTheReport(Project):
    """GPS4-T6: each analysis is a correlation table in the report, its resolution under it; living mode puts
    them in its Evidence and analysis chapter; a person presumed living stays out."""

    def resolved(self):
        (code, out), _doc = self.propose_and_apply(
            facts=[fact("victor-hugo-1802.birth.2", "birth", "1800", status="index")],
            analyses=[analysis("resolved", question="Q1", items=[
                {"source": SRC1, "fact": "victor-hugo-1802.birth", "asserts": "1802-02-26",
                 "informant": "the father", "axes": {"source": "original", "information": "primary",
                                                     "evidence": "direct"}},
                {"source": SRC1, "fact": "victor-hugo-1802.birth.2", "asserts": "1800",
                 "informant": "the declarant of the death", "axes": {"source": "derivative", "information": "secondary",
                                                             "evidence": "direct"}, "note": "age at death"}],
                resolution={"value": "1802-02-26", "fact": "victor-hugo-1802.birth",
                            "reasoning": "the birth record was declared by the father"})])
        self.assertEqual(code, 0, out)

    def report(self, ext="md"):
        self.assertEqual(self.call("render", RID)[0], 0)
        with open(os.path.join(self.rdir, "report", "report." + ext), encoding="utf-8") as fh:
            return fh.read()

    def test_journal_living_and_html(self):
        from tests.unit.test_human import golden

        self.resolved()
        md = self.report()
        start = md.index("Preuves et analyse")
        chapter = md[md.index("### ", start):md.index("<a id=\"s-timelines\">", start)]
        golden(self, "analysis-report", chapter)
        self.assertIn("| 1802-02-26 | the father |", chapter)
        self.assertIn("| originale | primaire | directe |", chapter)
        self.assertIn("Résolution : 1802-02-26 (`victor-hugo-1802.birth`). the birth record", chapter)
        html = self.report("html")
        self.assertIn("<td>dérivée</td>", html)
        from probandia import lifecycle

        lifecycle.update_meta(Research(self.dir, "hugo", RID), mode="living")
        md = self.report()
        self.assertIn("Victor HUGO : naissance", md)
        self.assertEqual(self.call("verify", RID, "--rule", "V-6")[0], 0)

    def test_a_person_presumed_living_stays_out(self):
        from probandia.util import yamlio

        self.resolved()
        path = os.path.join(self.family, "index", "persons.yaml")
        doc = yamlio.load(path)
        doc["persons"][0]["living"] = True
        yamlio.dump(path, doc)
        md = self.report()
        self.assertNotIn("Preuves et analyse", md)
        self.assertNotIn("an-victor-hugo-1802-birth", md)


class Gedcom(unittest.TestCase):
    """GPS4-T7: the fact an analysis kept carries its summary as a NOTE, and the other evidence as citations whose
    QUAY comes from their axes; in GEDCOM 7 and 5.5.1."""

    SRC2 = "src-01J9ZK3M4X0000000000000002"

    def export(self, version):
        from probandia import gedcom

        persons = [{"id": "victor-hugo-1802", "names": {"given": "Victor", "surname": "HUGO"},
                    "living": False, "parents": {"father": None, "mother": None}, "facts": [
                        fact("victor-hugo-1802.birth", "birth", "1802-02-26"),
                        fact("victor-hugo-1802.birth.2", "birth", "1800", status="index", source=self.SRC2)]}]
        sources = [{"id": SRC1, "repository": "AMB", "reference": "E-1802-N"},
                   {"id": self.SRC2, "repository": "Archives de Paris", "reference": "D-1885"}]
        a = analysis("resolved", items=[
            {"source": SRC1, "fact": "victor-hugo-1802.birth", "asserts": "1802-02-26",
             "axes": {"source": "original", "information": "primary", "evidence": "direct"}},
            {"source": self.SRC2, "fact": "victor-hugo-1802.birth.2", "asserts": "1800",
             "axes": {"source": "original", "information": "secondary", "evidence": "direct"}}],
            resolution={"value": "1802-02-26", "fact": "victor-hugo-1802.birth",
                        "reasoning": "The birth record was declared by the father."})
        return gedcom.Export(persons, sources, version=version, analyses=[a]).text()

    def test_both_versions(self):
        for version in (7, 5):
            with self.subTest(version=version):
                text = self.export(version)
                birth = text[text.index("1 BIRT"):]
                birth = birth[:birth.index("\n1 BIRT", 1) if "\n1 BIRT" in birth[1:] else len(birth)]
                self.assertIn("2 NOTE Analysis an-victor-hugo-1802-birth: kept 1802-02-26. The birth record was "
                              "declared by the father. Evidence: 1802-02-26 (original, primary, direct); 1800 "
                              "(original, secondary, direct).", birth.replace("\n3 CONC ", ""))
                self.assertIn("2 SOUR @S2@\n3 PAGE 1800\n3 QUAY 2", birth)

    def test_quay_from_the_axes(self):
        from probandia.gedcom import axes_quay

        self.assertEqual(axes_quay({"source": "original", "information": "primary", "evidence": "direct"}), "3")
        self.assertEqual(axes_quay({"source": "derivative", "information": "primary", "evidence": "direct"}), "2")
        self.assertEqual(axes_quay({"evidence": "indirect"}), "1")
        self.assertEqual(axes_quay({}), "2")
