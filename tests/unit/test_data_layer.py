import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from probandia import cli, events
from probandia.known import parse_window
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now
from probandia.util.ids import ulid
from tests import ROOT, SRC

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
RID = "2026-09-30-parents-of-victor-hugo"
SRC1 = "src-01J9ZK3M4X0000000000000001"
SRC2 = "src-01J9ZK3M4X0000000000000002"
SRC3 = "src-01J9ZK3M4X0000000000000003"


class Project(unittest.TestCase):
    """A fresh copy of the fixture family project for each test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.family = os.path.join(self.dir, "families", "hugo")
        self.rdir = os.path.join(self.family, "research", RID)
        self.log = os.path.join(self.rdir, "events.jsonl")
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"),
                    "PROBANDIA_SESSION": "test"}

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def index(self, name):
        return yamlio.load(os.path.join(self.family, "index", f"{name}.yaml"))

    def snapshot(self):
        out = {}
        for folder, _dirs, files in os.walk(self.family):
            for f in files:
                if f.endswith(".result"):
                    continue
                with open(os.path.join(folder, f), "rb") as fh:
                    out[os.path.relpath(os.path.join(folder, f), self.family)] = fh.read()
        return out

    def proposal(self, **parts):
        doc = {"schema": 1, "id": ulid(), "research": RID, "pass": 2,
               "author": {"harness": "claude-code", "agent": "researcher"}}
        doc.update(parts)
        path = os.path.join(self.tmp.name, f"{doc['id']}.yaml")
        yamlio.dump(path, doc)
        return doc, path

    def propose_and_apply(self, **parts):
        doc, path = self.proposal(**parts)
        code, out = self.call("propose", RID, path, "--agent", "researcher")
        self.assertEqual(code, 0, out)
        return self.call("apply", doc["id"], "--agent", "orchestrator"), doc


# events


class Events(Project):
    def write_payload(self, obj):
        path = os.path.join(self.tmp.name, "payload.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    def test_append_twice_keeps_the_chain(self):
        p = self.write_payload({"text": "Look at the parish registers too."})
        for _ in range(2):
            code, out = self.call("event", "append", RID, "--type", "instruction.added",
                                  "--payload-file", p)
            self.assertEqual(code, 0, out)
        self.assertIsNone(events.check_chain(self.log))
        lines = events.read(self.log)
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[-1]["prev"], events.line_hash(events.read_lines(self.log)[-2]))
        self.assertIsNone(lines[0]["prev"])
        self.assertEqual(self.call("event", "check", RID)[0], 0)

    def test_editing_a_past_line_is_detected(self):
        lines = events.read_lines(self.log)
        lines[1] = lines[1].replace("1802-02-26", "1801-02-26")
        with open(self.log, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        self.assertEqual(events.check_chain(self.log)[0], 3)
        code, out = self.call("event", "check", RID)
        self.assertEqual(code, 1)
        self.assertIn("LINE=3", out)
        p = self.write_payload({"text": "x"})
        code, out = self.call("event", "append", RID, "--type", "instruction.added",
                              "--payload-file", p)
        self.assertEqual(code, 1)
        self.assertIn("REASON=chain-broken", out)
        self.assertEqual(len(events.read_lines(self.log)), 3)

    def test_deleting_a_line_is_detected(self):
        lines = events.read_lines(self.log)
        del lines[0]
        with open(self.log, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        self.assertEqual(events.check_chain(self.log)[0], 1)

    def test_invalid_event_is_refused(self):
        p = self.write_payload({"x": 1})
        code, out = self.call("event", "append", RID, "--type", "fact.invented", "--payload-file", p)
        self.assertEqual(code, 1)
        self.assertEqual(len(events.read_lines(self.log)), 3)

    def test_event_type_of_a_newer_version_asks_for_an_update(self):
        from probandia.errors import SchemaVersionError
        from probandia.util.schema import validate_document

        last = events.read(self.log)[-1]
        newer = dict(last, id=ulid(), type="future.added", payload={}, prev=events.last_hash(self.log))
        with open(self.log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(events.encode(newer) + "\n")
        with open(self.log, "rb") as fh:
            before = fh.read()
        with self.assertRaises(SchemaVersionError):
            validate_document("event", newer)
        for args in (("event", "check", RID), ("verify", RID), ("render", RID)):
            code, out = self.call(*args)
            self.assertEqual(code, 2, (args, out))
            self.assertIn("REASON=schema-version", out)
            self.assertIn("future.added", out)
            self.assertIn("update Probandia", out)
        with open(self.log, "rb") as fh:
            self.assertEqual(fh.read(), before)   # nothing of the log is rewritten


# indexes

WRITER = r"""
import sys, time, json, os
sys.path.insert(0, sys.argv[1])
from probandia.indexes import FamilyIndexes, locked
project, tag, trace = sys.argv[2], sys.argv[3], sys.argv[4]
idx = FamilyIndexes(project, "hugo")
with locked(project, "family:hugo", {"harness": "cli", "session": "same", "agent": tag}):
    with open(trace, "a") as fh:
        fh.write(f"start {tag} {time.monotonic()}\n")
    gaps = idx.load("gaps")
    gaps["gaps"].append({"archive": tag, "reference": None, "window": {"from": 1, "to": 2},
                         "kind": "missing", "source": None})
    time.sleep(0.6)
    idx.write({"gaps": gaps}, {"harness": "cli", "agent": tag}, "test")
    with open(trace, "a") as fh:
        fh.write(f"end {tag} {time.monotonic()}\n")
"""


class Indexes(Project):
    def test_two_writers_are_serialised(self):
        trace = os.path.join(self.tmp.name, "trace.txt")
        procs = [subprocess.Popen([sys.executable, "-c", WRITER, SRC, self.dir, tag, trace])
                 for tag in ("w1", "w2")]
        for p in procs:
            self.assertEqual(p.wait(timeout=60), 0)
        with open(trace) as fh:
            steps = [line.split() for line in fh]
        self.assertEqual([s[0] for s in steps], ["start", "end", "start", "end"])
        self.assertEqual(steps[0][1], steps[1][1])  # each writer ends before the other starts
        archives = [g["archive"] for g in self.index("gaps")["gaps"]]
        self.assertIn("w1", archives)
        self.assertIn("w2", archives)  # no write was lost
        with open(os.path.join(self.dir, ".probandia", "index-changes.jsonl"), encoding="utf-8") as fh:
            log = [json.loads(line) for line in fh]
        self.assertEqual(sorted(e["actor"]["agent"] for e in log), ["w1", "w2"])
        self.assertTrue(all(e["files"] == ["gaps.yaml"] for e in log))


# proposals

WITNESS_OK = {"operation": "openarchives.search", "args": {"name": "Hugo"}, "expected": "1+",
              "passed": True}


def negative(witness_ts=None, **changes):
    s = {"id": f"s-{ulid()}", "ts": iso(utc_now()), "kind": "archive", "engine": "openarchives",
         "query": "Trébuchet Besançon", "variants": ["Trébuchet", "Trebuchet"],
         "window": {"from": 1767, "to": 1777, "places": ["Besançon"]}, "results": 0,
         "result": "negative", "failure": None,
         "witness": dict(WITNESS_OK, ts=witness_ts or iso(utc_now()))}
    s.update(changes)
    return s


MOTHER = {"id": "sophie-trebuchet-1772", "names": {"given": "Sophie", "surname": "TRÉBUCHET"}, "sex": "F",
          "living": False, "parents": {"father": None, "mother": None}, "spouses": [], "facts": []}


def birth(pid, value, status="index", source=SRC2):
    return {"id": f"{pid}.birth", "type": "birth", "date": {"value": value, "qualifier": "exact"},
            "status": status, "source": source}


class Apply(Project):
    def test_valid_proposal_writes_indexes_and_events(self):
        source = {"id": f"src-{ulid()}", "repository": "Archives municipales de Nantes",
                  "collection": "État civil", "reference": "E-1772-N", "accessed": "2026-10-01",
                  "transcription": "work/transcriptions/e-1772.md"}
        (code, out), doc = self.propose_and_apply(
            persons=[MOTHER], facts=[birth("sophie-trebuchet-1772", "1772-06-19", "record", source["id"])],
            sources=[source], searches=[negative()],
            sections=[{"kind": "chapter", "title": "The mother", "body_md": "…",
                       "facts": ["sophie-trebuchet-1772.birth"]}],
            variants=[{"kind": "surname", "name": "TRÉBUCHET", "form": "Trebuchet", "source": None}])
        self.assertEqual(code, 0, out)
        persons = {p["id"]: p for p in self.index("persons")["persons"]}
        fact = persons["sophie-trebuchet-1772"]["facts"][0]
        self.assertEqual((fact["research"], fact["pass"]), (RID, 2))
        stored = {s["id"]: s for s in self.index("sources")["sources"]}[source["id"]]
        self.assertTrue(stored["citation"].startswith("Archives municipales de Nantes, État civil"))
        self.assertIn("Trebuchet", [f["form"] for f in self.index("variants")["surnames"]["TRÉBUCHET"]])
        log = events.read(self.log)
        types = [e["type"] for e in log[3:]]
        self.assertEqual(types, ["evidence.recorded", "search.logged", "negative.recorded",
                                 "branch.added", "fact.asserted", "section.added"])
        self.assertEqual(fact["event"], next(e["id"] for e in log if e["type"] == "fact.asserted"
                                             and e["refs"] == ["sophie-trebuchet-1772.birth"]))
        self.assertIsNone(events.check_chain(self.log))
        result = yamlio.load(os.path.join(self.rdir, "work", "proposals", f"{doc['id']}.result"))
        self.assertEqual(result["status"], "accepted")
        code, out = self.call("apply", doc["id"], "--agent", "orchestrator")
        self.assertTrue(out.startswith("STATUS=WARN"))  # applied once only

    def assertRejected(self, reason_part, **parts):
        before = self.snapshot()
        (code, out), doc = self.propose_and_apply(**parts)
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=rejected", out)
        self.assertIn(reason_part, out)
        after = self.snapshot()
        after.pop(os.path.join("research", RID, "work", "proposals", f"{doc['id']}.yaml"))
        self.assertEqual(after, before)  # nothing changed but the .result file
        result = yamlio.load(os.path.join(self.rdir, "work", "proposals", f"{doc['id']}.result"))
        self.assertEqual(result["status"], "rejected")
        return out

    def test_record_without_source(self):
        self.assertRejected("P-1", persons=[MOTHER],
                            facts=[birth("sophie-trebuchet-1772", "1772", "record", None)])

    def test_record_without_image_or_transcription(self):
        self.assertRejected("P-2", persons=[MOTHER],
                            facts=[birth("sophie-trebuchet-1772", "1772", "record", SRC2)])

    def test_a_fact_from_an_online_tree(self):
        # T238: a tree found online is a lead, as an imported one: neither record nor index
        tree = {"id": f"src-{ulid()}", "type": "online-tree", "title": "Famille Trébuchet", "publisher": "Geneanet",
                "url": "https://gw.geneanet.org/x", "accessed": "2026-10-14"}
        out = self.assertRejected("is an online tree", persons=[MOTHER], sources=[tree],
                                  facts=[birth("sophie-trebuchet-1772", "1772", "index", tree["id"])])
        self.assertIn("P-2", out)
        (code, out), _doc = self.propose_and_apply(persons=[MOTHER], sources=[tree],
                                                   facts=[birth("sophie-trebuchet-1772", "1772", "hypothesis",
                                                                tree["id"])])
        self.assertEqual(code, 0, out)

    def test_negative_without_witness(self):
        self.assertRejected("P-3", searches=[negative(witness=None)])

    def test_negative_with_an_old_witness(self):
        self.assertRejected("older than 24 hours", searches=[negative("2026-01-01T00:00:00Z")])

    def test_negative_without_variants_or_window(self):
        out = self.assertRejected("records no variants", searches=[negative(variants=[], window=None)])
        self.assertIn("records no window", out)

    def test_negative_from_a_failed_access(self):
        self.assertRejected("failed access", searches=[negative(failure="anubis")])

    def test_chronology(self):
        child = dict(MOTHER, id="paul-hugot-1768", names={"given": "Paul", "surname": "HUGOT"},
                     parents={"father": "leopold-hugo-1773", "mother": None})   # an invented son
        self.assertRejected("P-9", persons=[child], facts=[birth("paul-hugot-1768", "1768")])

    def test_a_fact_against_the_date_of_its_act(self):
        # T244: dated after the act that records it, refused; more than a year before, refused until a note explains
        source = {"id": f"src-{ulid()}", "type": "civil-registration", "jurisdiction": "Nantes",
                  "register": "Naissances, 1772", "repository": "Archives municipales de Nantes", "act": "naissance",
                  "act_date": "1772-06-20", "accessed": "2026-10-14", "transcription": "work/transcriptions/e-1772.md"}
        fact = birth("sophie-trebuchet-1772", "1772-06-21", "record", source["id"])
        out = self.assertRejected("comes after the act that records it", persons=[MOTHER], sources=[source],
                                  facts=[fact])
        self.assertIn("P-9: sophie-trebuchet-1772.birth (1772-06-21)", out)
        judged = dict(source, act_date="1790-01-08")
        fact = birth("sophie-trebuchet-1772", "1772-06-19", "record", source["id"])
        self.assertRejected("more than a year later", persons=[MOTHER], sources=[judged], facts=[fact])
        (code, out), _doc = self.propose_and_apply(persons=[MOTHER], sources=[judged], facts=[dict(
            fact, note="declared by a judgement of the court of Nantes, 8 January 1790")])
        self.assertEqual(code, 0, out)

    def test_death_before_birth(self):
        death = dict(birth("sophie-trebuchet-1772", "1767"), id="sophie-trebuchet-1772.death", type="death")
        self.assertRejected("death before birth", persons=[MOTHER],
                            facts=[birth("sophie-trebuchet-1772", "1772"), death])

    def test_non_link(self):
        jean = {"id": "victor-hugo-1802", "names": {"given": "Victor", "surname": "HUGO"},
                "parents": {"father": "jean-martin-1849", "mother": None}}
        self.assertRejected("non-link", persons=[jean])

    def test_unknown_person_and_existing_fact(self):
        self.assertRejected("no person", facts=[birth("nobody-1800", "1800")])
        self.assertRejected("already exists", facts=[birth("victor-hugo-1802", "1802")])

    def test_only_orchestrator_or_session(self):
        doc, path = self.proposal(persons=[MOTHER])
        self.call("propose", RID, path)
        code, out = self.call("apply", doc["id"], "--agent", "researcher")
        self.assertEqual(code, 2)
        self.assertIn("REASON=not-allowed", out)

    def test_propose_apply(self):
        # token-economy B2: stored and applied in one call when the dry run finds no refusal
        doc, path = self.proposal(persons=[MOTHER], facts=[birth("sophie-trebuchet-1772", "1772", "index", SRC2)])
        code, out = self.call("propose", RID, path, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("- verdict=would-apply", out)
        self.assertIn("APPLIED=true\n", out)
        self.assertIn("sophie-trebuchet-1772", {p["id"] for p in self.index("persons")["persons"]})
        result = yamlio.load(os.path.join(self.rdir, "work", "proposals", f"{doc['id']}.result"))
        self.assertEqual(result["status"], "accepted")
        # refused by the dry run: the summary as without --apply, nothing applied
        before = self.snapshot()
        doc, path = self.proposal(persons=[dict(MOTHER, id="jeanne-hugot-1774", names={"given": "Jeanne", "surname": "HUGOT"})],
                                  facts=[birth("jeanne-hugot-1774", "1774", "record", None)])
        code, out = self.call("propose", RID, path, "--apply")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=WARN\n"), out)
        self.assertIn("APPLIED=false\n", out)
        self.assertIn("- reason=P-1: fact jeanne-hugot-1774.birth (record) has no source\n", out)
        after = self.snapshot()
        after.pop(os.path.join("research", RID, "work", "proposals", f"{doc['id']}.yaml"))
        self.assertEqual(after, before)
        # J8: rejected, so that the corrected one proposed next leaves nothing waiting
        result = yamlio.load(os.path.join(self.rdir, "work", "proposals", f"{doc['id']}.result"))
        self.assertEqual((result["status"], result["events"]), ("rejected", []))
        # a field agent may propose, never apply
        doc, path = self.proposal(persons=[dict(MOTHER, id="eva-hugot-1775", names={"given": "Eva", "surname": "HUGOT"})])
        code, out = self.call("propose", RID, path, "--apply", "--agent", "researcher")
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=not-allowed", out)
        self.assertFalse(os.path.exists(os.path.join(self.rdir, "work", "proposals", f"{doc['id']}.yaml")))

    def test_a_refutation_says_what_rested_on_the_fact(self):
        # T242: one line for each question, analysis and proof argument that the refuted fact held up
        from probandia import verify
        from probandia.research import Research
        from tests.unit.test_analyses import analysis
        from tests.unit.test_proofs import proof

        resolved = analysis("resolved", resolution={"value": "1802-02-26", "fact": "victor-hugo-1802.birth",
                                                    "reasoning": "the birth record, made by the father"})
        (code, out), _doc = self.propose_and_apply(analyses=[resolved], proofs=[proof()])
        self.assertEqual(code, 0, out)
        code, out = self.call("question", "answer", "Q1", "--conclusion", "victor-hugo-1802.birth", "--research", RID)
        self.assertEqual(code, 0, out)

        def v20():
            return verify.run(self.dir, Research(self.dir, "hugo", RID), rules=["V-20"])[0][1:]

        self.assertEqual(v20(), ("PASS", ""))
        refute = {"fact": "victor-hugo-1802.birth", "reason": "the record of another Victor", "cause": "homonym"}
        (code, out), _doc = self.propose_and_apply(refutations=[refute])
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=WARN\n"), out)
        lines = [line for line in out.splitlines() if line.startswith("- refuted fact victor-hugo-1802.birth: ")]
        self.assertEqual(lines, [
            f"- refuted fact victor-hugo-1802.birth: question Q1 of {RID} rests on it; reopen it, or answer it "
            "with another fact (V-20)",
            "- refuted fact victor-hugo-1802.birth: analysis an-victor-hugo-1802-birth cites it; record it again "
            "without it, or resolve it anew",
            f"- refuted fact victor-hugo-1802.birth: proof argument pf-q1-{RID} (Q1) rests on it; draft it again"])
        self.assertEqual(v20(), ("FAIL", "Q1 is answered on refuted facts: victor-hugo-1802.birth"))
        self.assertEqual(self.call("question", "reopen", "Q1", "--research", RID)[0], 0)
        self.assertEqual(v20(), ("PASS", ""))
        self.call("question", "answer", "Q1", "--conclusion", "leopold-hugo-1773.birth", "--research", RID)
        self.assertEqual(v20(), ("PASS", ""))
        # a refutation that nothing rests on warns of nothing
        (code, out), _doc = self.propose_and_apply(refutations=[dict(refute, fact="jean-martin-1849.birth")])
        self.assertEqual((code, out.startswith("STATUS=OK\n")), (0, True), out)

    def test_presumed_living_is_flagged(self):
        young = dict(MOTHER, id="camille-vernier-1988", names={"given": "Camille", "surname": "VERNIER"},
                     living="auto")   # an invented person, presumed living
        (code, out), doc = self.propose_and_apply(persons=[young],
                                                  facts=[birth("camille-vernier-1988", "1988")])
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=WARN"))
        self.assertIn("presumed living: camille-vernier-1988", out)

    def test_whom_no_date_places_is_presumed_living(self):
        # T240: a name alone may be anyone's; each dated fact bounds the birth, less the youngest age it allows
        import datetime

        from probandia.report.living import latest_birth, presumed_living

        today = datetime.date(2026, 10, 14)

        def person(*facts, **more):
            return dict({"id": "x", "names": {"given": "Louise", "surname": "VERNIER"}, "facts": list(facts)}, **more)

        def fact(kind, value, **more):
            return dict({"id": f"x.{kind}", "type": kind, "date": {"value": value}, "status": "index"}, **more)

        def living(p, others=()):
            return presumed_living(p, {x["id"]: x for x in (p, *others)}, 100, today)

        self.assertTrue(living(person()))
        self.assertTrue(living(person(fact("occupation", None))))   # a fact without a date places no one
        self.assertTrue(living(person(fact("census", "1851", status="refuted"))))   # nor a refuted one
        self.assertFalse(living(person(fact("census", "1851"))))   # born in 1851 at the latest
        self.assertFalse(living(person(fact("residence", "1925"))))
        self.assertEqual(latest_birth(person(fact("marriage", "1950")), {}), 1936)
        self.assertTrue(living(person(fact("marriage", "1950"))))   # born after 1926 maybe: still living
        self.assertFalse(living(person(fact("marriage", "1930"))))
        child = {"id": "y", "parents": {"father": None, "mother": "x"}, "facts": [fact("birth", "1960")]}
        self.assertEqual(latest_birth(person(), {"y": child}), 1948)
        self.assertTrue(living(person(), [child]))
        self.assertFalse(living(person(living=False)))   # living: false always wins
        self.assertFalse(living(person(living=False), [child]))

    def test_a_gap_receives_an_id_and_is_added_once(self):
        gap = {"archive": "Archives municipales de Besançon", "reference": "EC-1801", "kind": "missing",
               "window": {"from": 1800, "to": 1802}, "place": "besancon", "types": ["civil_registers"]}
        (code, out), _doc = self.propose_and_apply(gaps=[gap])
        self.assertEqual(code, 0, out)
        gaps = self.index("gaps")["gaps"]
        self.assertEqual(len(gaps), 3)
        self.assertNotIn("id", gaps[0])  # the old gaps stay as they were
        self.assertEqual(gaps[2], {"id": "G1", **gap})
        (code, out), _doc = self.propose_and_apply(gaps=[gap])
        self.assertEqual(len(self.index("gaps")["gaps"]), 3)
        justified = dict(gap, id="G1", justification="the archivist's answer of 2 October 2026")
        (code, out), _doc = self.propose_and_apply(gaps=[justified, dict(gap, reference="EC-1803")])
        self.assertEqual(code, 0, out)
        gaps = self.index("gaps")["gaps"]
        self.assertEqual([g.get("id") for g in gaps], [None, None, "G1", "G2"])
        self.assertEqual(gaps[2]["justification"], "the archivist's answer of 2 October 2026")

    def test_a_gap_names_a_known_place_and_known_types(self):
        gap = {"archive": "ad25", "kind": "missing", "window": {"from": 1793, "to": 1802},
               "place": "auxon-dessous", "types": ["decennial_tables", "tables"]}
        out = self.assertRejected("no place auxon-dessous", gaps=[gap])
        self.assertIn("unknown source type tables", out)

    def test_propose_refuses_an_invalid_file(self):
        doc, path = self.proposal(facts=[{"id": "Bad.Id", "type": "birth", "status": "record"}])
        code, out = self.call("propose", RID, path)
        self.assertEqual(code, 1)
        self.assertIn("$.facts[0].id", out)
        self.assertIn("- example=propose --example facts", out)   # H3: the sample of the part at fault

    def test_propose_puts_a_short_spouse_in_the_schemas_form(self):
        # H3: the bench's refusal of 9 Oct. 2026 (spouses: [<id>]) is now a normalisation
        person = {"id": "sophie-trebuchet-1772", "names": {"given": "Sophie", "surname": "TRÉBUCHET"}, "sex": "F",
                  "living": False, "parents": {"father": None, "mother": None},
                  "spouses": ["leopold-hugo-1773"], "facts": []}
        _doc, path = self.proposal(persons=[person])
        code, out = self.call("propose", RID, path)
        self.assertEqual(code, 0, out)
        self.assertIn("- normalized=persons[0].spouses[0] leopold-hugo-1773 -> {person: leopold-hugo-1773}",
                      out)
        details = next(x.split("=", 1)[1] for x in out.splitlines() if x.startswith("DETAILS="))
        stored = yamlio.load(os.path.join(self.dir, details))
        self.assertEqual(stored["persons"][0]["spouses"], [{"person": "leopold-hugo-1773"}])

    def test_propose_reads_support_record_as_image(self):
        # I1, 11 Oct. 2026: `support: record` (the fact's level) refused on every pass at the bench
        search = {"id": "s-01J9ZM0000000000000000000D", "ts": "2026-09-30T10:00:00Z", "kind": "archive",
                  "engine": "ad25", "query": "HUGO naissance Besançon", "result": "positive",
                  "filters": {"register": "Besançon, naissances an X", "views": "3-30"}, "support": "record"}
        _doc, path = self.proposal(searches=[search])
        code, out = self.call("propose", RID, path)
        self.assertEqual(code, 0, out)
        self.assertIn("- normalized=searches[0].support record -> image", out)
        details = next(x.split("=", 1)[1] for x in out.splitlines() if x.startswith("DETAILS="))
        self.assertEqual(yamlio.load(os.path.join(self.dir, details))["searches"][0]["support"], "image")

    def test_propose_gives_a_search_its_id(self):
        # A7, 11 Oct. 2026: a proposal refused for searches written with no id
        search = {"ts": "2026-09-30T10:00:00Z", "kind": "archive", "engine": "ad25",
                  "query": "HUGO naissance Besançon", "result": "positive"}
        _doc, path = self.proposal(searches=[search])
        code, out = self.call("propose", RID, path)
        self.assertEqual(code, 0, out)
        line = next(x for x in out.splitlines() if x.startswith("- normalized=searches[0].id"))
        details = next(x.split("=", 1)[1] for x in out.splitlines() if x.startswith("DETAILS="))
        given = yamlio.load(os.path.join(self.dir, details))["searches"][0]["id"]
        self.assertRegex(given, r"^s-[0-7][0-9A-HJKMNP-TV-Z]{25}$")
        self.assertEqual(line, f"- normalized=searches[0].id (none) -> {given}")

    def test_propose_fills_what_the_engine_knows(self):
        # J2-J3 bench, 11 Oct. 2026: a proposal of four parts, no head; made-up search ids, no ts
        search = {"id": "s-lafontaine-deces-1876", "kind": "archive", "engine": "ad50",
                  "query": "LAFONTAINE décès 1876", "result": "positive"}   # Pierre LAFONTAINE, invented
        path = os.path.join(self.tmp.name, "pass1.yaml")
        yamlio.dump(path, {"author": "main", "searches": [search]})
        code, out = self.call("propose", RID, path)
        self.assertEqual(code, 0, out)
        self.assertIn(f"- normalized=research, pass, author (none) -> {RID}, ", out)
        self.assertIn("- normalized=searches[0].id s-lafontaine-deces-1876 -> s-", out)
        self.assertIn("- normalized=searches[0].ts (none) -> ", out)
        details = next(x.split("=", 1)[1] for x in out.splitlines() if x.startswith("DETAILS="))
        stored = yamlio.load(os.path.join(self.dir, details))
        self.assertEqual((stored["research"], stored["author"]["agent"]), (RID, "session"))
        self.assertIsInstance(stored["pass"], int)

    def test_propose_takes_a_persons_facts_named_by_their_ids(self):
        # J7 bench, 12 Oct. 2026: `facts: [<id>]` under a new person, refused in each session
        person = {"id": "sophie-trebuchet-1772", "names": {"given": "Sophie", "surname": "TRÉBUCHET"}, "sex": "F",
                  "living": False, "parents": {"father": None, "mother": None}, "spouses": [],
                  "facts": ["sophie-trebuchet-1772.birth"]}
        fact = {"id": "sophie-trebuchet-1772.birth", "type": "birth", "date": {"value": "1772", "qualifier": "about"},
                "place": None, "status": "hypothesis", "source": None, "note": ""}
        _doc, path = self.proposal(persons=[person], facts=[fact])
        code, out = self.call("propose", RID, path, "--agent", "researcher")
        self.assertEqual(code, 0, out)
        self.assertIn("- normalized=persons[0].facts sophie-trebuchet-1772.birth -> facts", out)
        details = next(x.split("=", 1)[1] for x in out.splitlines() if x.startswith("DETAILS="))
        stored = yamlio.load(os.path.join(self.dir, details))
        self.assertEqual((stored["persons"][0]["facts"], [f["id"] for f in stored["facts"]]),
                         ([], ["sophie-trebuchet-1772.birth"]))
        # an id that no fact of the proposal bears is no short form: the schema refuses it, with the example
        _doc, path = self.proposal(persons=[dict(person, facts=["sophie-trebuchet-1772.death"])], facts=[fact])
        code, out = self.call("propose", RID, path, "--agent", "researcher")
        self.assertEqual(code, 1, out)
        self.assertIn("- example=propose --example persons", out)

    def test_the_proposal_of_who_applies_is_rejected_when_its_dry_run_refuses_it(self):
        # J7 bench, 12 Oct. 2026: refused, proposed again under a new id, it stopped `pass end` until dropped
        fact = {"id": "nobody-1820.birth", "type": "birth", "date": {"value": "1820", "qualifier": "about"},
                "place": None, "status": "hypothesis", "source": None, "note": ""}
        from probandia.proposals import pending
        from probandia.research import Research

        research = Research(self.dir, "hugo", RID)
        before = pending(research)
        for agent, waits in (("researcher", True), ("session", False), ("orchestrator", False)):
            doc, path = self.proposal(facts=[fact])
            code, out = self.call("propose", RID, path, "--agent", agent)
            self.assertIn("verdict=would-reject", out)
            self.assertEqual(doc["id"] in pending(research), waits, agent)
        result = yamlio.load(os.path.join(self.rdir, "work", "proposals", f"{doc['id']}.result"))
        self.assertEqual(result["status"], "rejected")
        self.assertIn("fact nobody-1820.birth: no person nobody-1820 in the family or the proposal", result["reasons"])
        self.assertEqual(len(pending(research)), len(before) + 1)   # the researcher's waits for the orchestrator


# cite


class ProposalSummary(Project):
    """optimize 2.9: propose answers a summary of 10 lines at most, from a dry run of apply."""

    def summary(self, **parts):
        doc, path = self.proposal(**parts)
        before = self.snapshot()
        code, out = self.call("propose", RID, path, "--agent", "researcher")
        lines = [line for line in out.splitlines() if line.startswith("- ")]
        self.assertLessEqual(len(lines), 10, out)
        after = self.snapshot()
        after.pop(os.path.join("research", RID, "work", "proposals", f"{doc['id']}.yaml"))
        self.assertEqual(after, before)   # the dry run writes nothing but the stored copy
        return code, out

    def test_a_proposal_that_would_apply(self):
        code, out = self.summary(persons=[MOTHER], facts=[birth("sophie-trebuchet-1772", "1772", "index", SRC2)],
                                 searches=[negative()])
        self.assertEqual(code, 0, out)
        self.assertIn("- facts=index:1\n", out)
        self.assertIn("- adds=persons:1 sources:0 searches:1 negatives:1 hypotheses:0 errata:0 sections:0\n", out)
        self.assertIn("- verdict=would-apply reasons=0 conflicts=0 citations=0 negatives=0", out)

    def test_conflicts_and_missing_citations(self):
        code, out = self.summary(persons=[MOTHER], facts=[
            birth("sophie-trebuchet-1772", "1772", "record", None), birth("victor-hugo-1802", "1802")])
        self.assertIn("STATUS=WARN", out)
        self.assertIn("verdict=would-reject reasons=2 conflicts=1 citations=1", out)
        self.assertIn("- reason=P-1: fact sophie-trebuchet-1772.birth (record) has no source\n", out)
        self.assertIn("already exists", out)

    def test_a_record_fact_without_its_search(self):
        # token-economy H1: the search that found a record, and the negative it proves, are asked for
        code, out = self.summary(persons=[MOTHER], facts=[birth("sophie-trebuchet-1772", "1772", "record", SRC1)])
        self.assertIn("\n- missing_search=sophie-trebuchet-1772.birth record facts without the search that found them: "
                      "add it to searches (the archive, the call number, the views read", out)
        _code, out = self.summary(persons=[MOTHER], facts=[birth("sophie-trebuchet-1772", "1772", "record", SRC1)],
                                  searches=[negative()])
        self.assertNotIn("missing_search=", out)
        _code, out = self.summary(persons=[MOTHER], facts=[birth("sophie-trebuchet-1772", "1772", "index", SRC2)])
        self.assertNotIn("missing_search=", out)   # an index is a lead, not a register read

    def test_the_skills_read_the_summary_not_the_file(self):
        from tests import ROOT

        for rel in ("skills/research/SKILL.md", "skills/research/team.md",
                    "agents/orchestrator.md", "cursor/agents/orchestrator.md", "droids/orchestrator.md"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("Read the proposal", text, rel)
            self.assertNotIn("and its proposal.", text, rel)
        with open(os.path.join(ROOT, "skills", "research", "team.md"), encoding="utf-8") as fh:
            self.assertIn("`propose` summary", fh.read())

    def test_one_proposal_per_pass_in_session_mode(self):
        # token-economy B2 and B3: facts, sources, searches and sections together, proposed and applied at once
        from tests import ROOT

        with open(os.path.join(ROOT, "skills", "research", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("One proposal per pass in session mode", text)
        self.assertIn("`propose <file> --apply`", text)
        with open(os.path.join(ROOT, "skills", "report", "SKILL.md"), encoding="utf-8") as fh:
            self.assertIn("a pass's sections go in its one proposal", fh.read())

    def test_ten_lines_at_most(self):
        facts = [birth(f"nobody-{n}", "1800") for n in range(12)]
        code, out = self.summary(facts=facts)
        self.assertIn("- reason=… 7 more: apply lists them all\n", out)


class Draft(Project):
    """T76: the session read propose --example (3.1 k characters, J8), then wrote the whole proposal; the engine knows
    its header, the sources the pass transcribed, the registers it read and the subject."""

    def archive_run(self, operation, args, result):
        from unittest import mock

        with mock.patch("probandia.archives.run", lambda module, op, a, ctx: result):   # no site is called
            code, out = self.call("archive", "run", f"ad50.{operation}", "--args", json.dumps(args))
        self.assertEqual(code, 0, out)

    def value(self, out, key):
        return next((line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "=")), None)

    def test_the_draft_with_its_facts_added_would_apply(self):
        from probandia import transcription
        from probandia.archives import OperationResult

        self.assertEqual(self.call("resume", RID, "--mode", "session")[0], 0)   # pass 2
        self.archive_run("registers", {"commune": "Octeville", "type": "birth", "from": 1802, "to": 1802},
                         OperationResult(rows=[{"detail": 702, "cote": "5 Mi 1/7", "types": "naissances",
                                                "from": 1802, "to": 1802}]))
        images = os.path.join(self.rdir, "work", "images")
        os.makedirs(images)
        for view in (11, 12, 13, 15):   # the views a reader looked at, the act on view 12
            path = os.path.join(images, f"ad50-702-{view:04d}.jpg")
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8\xff\xe0 view")
            self.archive_run("view", {"detail": 702, "view": view}, OperationResult(path=path))
        image = f"families/hugo/research/{RID}/work/images/ad50-702-0012-crop.jpg"
        code, out = self.call("transcribe", "new", "--image", image, "--agent", "reader")
        sid = self.value(out, "SOURCE")
        path = transcription.path_for(self.family, sid)
        with open(path, "w", encoding="utf-8") as fh:   # the reader's lines
            fh.write(transcription.template(sid, image, lines=["Victor Marie fils de Joseph Léopold Sigisbert Hugo",
                                                               "baptisé le onze ventôse an dix"]))
        code, out = self.call("propose", "--draft", RID)
        self.assertEqual(code, 0, out)
        draft = os.path.join(self.dir, *self.value(out, "DRAFT").split("/"))
        self.assertEqual(draft, os.path.join(self.rdir, "work", "proposals", "draft-2.yaml"))
        self.assertEqual([self.value(out, k) for k in ("SUBJECT", "SOURCES", "SEARCHES")],
                         ["victor-hugo-1802", "1", "1"])
        doc = yamlio.load(draft)
        self.assertEqual((doc["research"], doc["pass"], doc["author"]["agent"]), (RID, 2, "session"))
        self.assertEqual(doc["sources"], [{"id": sid, "image": image, "transcription": f"evidence/transcriptions/{sid}.md",
                                           "repository": "Archives départementales de la Manche",
                                           "reference": "5 Mi 1/7"}])
        self.assertEqual(doc["searches"], [{"kind": "archive", "engine": "ad50", "query": "5 Mi 1/7",
                                            "filters": {"register": "5 Mi 1/7", "views": "11-13, 15"},
                                            "result": "positive", "support": "image"}])
        with open(draft, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("# subject: victor-hugo-1802\n", text)
        self.assertTrue(text.endswith("facts:\n  # one per fact (propose --example facts); its excerpt {source, lines} "
                                      "as the reader returned them\n"), text)
        with open(draft, "a", encoding="utf-8") as fh:   # the session adds its fact lines, nothing else
            fh.write(f"  - id: victor-hugo-1802.baptism\n    type: baptism\n"
                     f"    date: {{value: '1802-03-02', qualifier: exact, original: \"onze ventôse an dix\"}}\n"
                     f"    place: {{id: besancon, as_written: Besançon}}\n    status: record\n    source: {sid}\n"
                     f"    excerpt: {{source: {sid}, lines: 1-2}}\n")
        code, out = self.call("propose", draft)
        self.assertEqual(code, 0, out)
        self.assertIn("verdict=would-apply", out)
        self.assertNotIn("missing_search", out)
        code, out = self.call("propose", "--draft", RID)   # a draft being filled is never written over
        self.assertEqual((code, self.value(out, "STATUS")), (0, "WARN"), out)
        with open(draft, encoding="utf-8") as fh:
            self.assertIn("victor-hugo-1802.baptism", fh.read())

    def test_a_subject_the_family_lacks_is_named_for_the_agent_to_add(self):
        def draft(question):
            meta = yamlio.load(os.path.join(self.rdir, "research.yaml"))
            yamlio.dump(os.path.join(self.rdir, "research.yaml"), dict(meta, question=question))
            shutil.rmtree(os.path.join(self.rdir, "work", "proposals"), ignore_errors=True)
            code, out = self.call("propose", "--draft", RID)
            self.assertEqual(code, 0, out)
            path = os.path.join(self.dir, *self.value(out, "DRAFT").split("/"))
            with open(path, encoding="utf-8") as fh:
                return self.value(out, "SUBJECT"), fh.read(), path

        subject, text, path = draft("Who were the parents of Eugène Hugo, born in 1800 in Nancy?")
        self.assertEqual(subject, "Eugène Hugo")
        self.assertIn("# subject: Eugène Hugo, not in the family: add them to persons\nfacts:\n", text)
        self.assertNotIn("persons:", text)   # the agent adds them at the end, with the persons the act names
        code, out = self.call("propose", path)
        self.assertEqual(code, 0, out)   # proposed as it is: its facts: left empty is no fault
        # a person whose surname is not the family's: no subject, rather than the family's surname
        subject, text, _path = draft("Who were the parents of Adèle Foucher, born in 1803 in Paris?")
        self.assertIsNone(subject)
        self.assertNotIn("subject", text)

    def test_a_part_given_twice_is_refused_rather_than_the_first_dropped(self):
        # a second sources: added at the end of a draft would replace the first silently
        doc, path = self.proposal(sources=[{"id": SRC1, "repository": "Archives municipales de Besançon"}])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"sources:\n- id: {SRC2}\n  repository: Archives municipales de Nancy\n")
        code, out = self.call("propose", RID, path, "--agent", "researcher")
        self.assertEqual((code, self.value(out, "REASON"), self.value(out, "LINE")), (1, "yaml", "11"), out)
        self.assertIn("the key 'sources' is given twice", out)


class Cite(Project):
    FIELDS = ["--repository", "Archives départementales du Doubs", "--collection",
              "Registres paroissiaux de Besançon", "--reference", "3 E 260/12", "--item",
              "baptême de Jean Martin", "--page", "14", "--image", "27", "--url",
              "https://example.org/ad25/27", "--accessed", "2026-10-01"]

    def test_form(self):
        code, out = self.call("cite", "--form", *self.FIELDS)
        self.assertEqual(code, 0)
        self.assertIn("CITATION=Archives départementales du Doubs, Registres paroissiaux de Besançon, "
                      "3 E 260/12, baptême de Jean Martin, page 14, image 27, "
                      "https://example.org/ad25/27 (consulted on 2026-10-01).", out)

    def test_a_type_written_as_an_agent_guesses_it(self):
        # token-economy J9: civil_record and civil_register, refused in each session of the bench of J8
        for guessed in ("civil_record", "civil_register", "Civil-Registration", "parish_register"):
            code, out = self.call("cite", "--form", "--type", guessed, *self.FIELDS)
            self.assertEqual(code, 0, (guessed, out))
        code, out = self.call("cite", "--form", "--type", "birth_certificate", *self.FIELDS)
        self.assertEqual(code, 2, out)   # no alias for it: the choices are listed

    def test_form_needs_a_repository(self):
        self.assertEqual(self.call("cite", "--form", "--reference", "x")[0], 2)

    def test_stored_sentence(self):
        code, out = self.call("cite", SRC1)
        self.assertIn("CITATION=Archives municipales de Besançon, État civil, Besançon, "
                      "E-1802-N, acte 112, image 45", out)

    def test_built_when_missing(self):
        code, out = self.call("cite", SRC3)
        self.assertIn("CITATION=Archives départementales du Doubs, Registres paroissiaux, 3 E 260 (consulted on 2026-09-30).", out)

    def test_unknown(self):
        self.assertEqual(self.call("cite", "src-01J9ZK3M4X0000000000000099")[0], 1)


# known


class Known(Project):
    def values(self, out):
        return dict(line.split("=", 1) for line in out.splitlines() if not line.startswith("- "))

    def test_spelling_variant_finds_the_fact(self):
        code, out = self.call("known", RID, "--names", "Hugot", "--window", "1797-1807")
        self.assertEqual(code, 0, out)
        self.assertIn("- fact=victor-hugo-1802.birth birth 1802-02-26 besancon [record]", out)
        self.assertNotIn("leopold", out)  # outside the window
        self.assertNotIn("jean-martin", out)

    def test_phonetic_and_attested_forms(self):
        for name in ("Hugo", "Hugaud", "Hugues", "HUGOT"):
            code, out = self.call("known", RID, "--names", name)
            self.assertIn("victor-hugo-1802.birth", out, name)
            self.assertIn("leopold-hugo-1773.birth", out, name)

    def test_old_place_names(self):
        code, out = self.call("known", RID, "--places", "Vesontio")
        self.assertIn("victor-hugo-1802.birth", out)
        self.assertNotIn("jean-martin", out)
        code, out = self.call("known", RID, "--places", "Nanzig")
        self.assertIn("leopold-hugo-1773.birth", out)  # its place is only written

    def test_negatives_valid_and_due(self):
        code, out = self.call("known", RID, "--names", "Hugo")
        v = self.values(out)
        self.assertEqual((v["NEGATIVES"], v["NEGATIVES_DUE"]), ("2", "1"))
        self.assertIn('negative=s-01J9ZK5A000000000000000001 valid "Hugo Besançon"', out)
        self.assertIn("negative=s-01J9ZK5A000000000000000002 due", out)
        self.assertNotIn("s-01J9ZK5A000000000000000003", out)  # positive

    def test_open_hypotheses_and_overlapping_gaps(self):
        code, out = self.call("known", RID, "--window", "1790-1800")
        v = self.values(out)
        self.assertEqual((v["HYPOTHESES"], v["GAPS"]), ("1", "1"))
        self.assertIn("hypothesis=h-father-of-victor", out)
        self.assertNotIn("h-closed-one", out)
        self.assertIn("gap=Archives municipales de Besançon EC-1799 1797-1799 destroyed", out)

    def test_at_most_forty_lines(self):
        persons = self.index("persons")
        base = persons["persons"][2]
        for i in range(60):
            p = copy.deepcopy(base)
            p["id"] = f"pierre-martin-{1900 + i}"
            p["facts"][0]["id"] = f"pierre-martin-{1900 + i}.birth"
            persons["persons"].append(p)
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), persons)
        code, out = self.call("known", RID, "--names", "Martin")
        self.assertLessEqual(len(out.splitlines()), 40)
        self.assertIn("FACTS=61", out)
        self.assertIn("DETAILS=", out)

    def test_windows(self):
        self.assertEqual(parse_window("1802+-5"), (1797, 1807))
        self.assertEqual(parse_window("1802±2"), (1800, 1804))
        self.assertEqual(parse_window("1860-1840"), (1840, 1860))
        self.assertEqual(parse_window("1802"), (1802, 1802))
        self.assertIsNone(parse_window(None))


class Acceptance(Project):
    """On the fixture family: a valid proposal is applied, an invalid one is
    rejected with its reasons, a tampered line is detected, and known finds a
    fact through a spelling variant."""

    def test(self):
        (code, out), _doc = self.propose_and_apply(persons=[MOTHER],
                                                   facts=[birth("sophie-trebuchet-1772", "1772")])
        self.assertEqual(code, 0, out)
        (code, out), _doc = self.propose_and_apply(
            facts=[birth("victor-hugo-1802", "1802", "record", None)])
        self.assertEqual(code, 1)
        self.assertIn("P-1", out)
        lines = events.read_lines(self.log)
        lines[2] = lines[2].replace('"n":1', '"n":2')
        with open(self.log, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        code, out = self.call("event", "check", RID)
        self.assertEqual(code, 1)
        self.assertIn("LINE=4", out)
        code, out = self.call("known", RID, "--names", "Hugot")
        self.assertIn("victor-hugo-1802.birth", out)
