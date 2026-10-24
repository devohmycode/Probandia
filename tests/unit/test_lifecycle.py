import builtins
import datetime
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from probandia import cli, events, lifecycle, verify
from probandia.research import Research
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now
from probandia.util.ids import ulid
from tests import REUSE, ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
WORKSHOP = os.path.join(ROOT, "tests", "fixtures", "workshop")
RID = "2026-09-30-parents-of-victor-hugo"
ACTOR = {"harness": "cli", "agent": "session", "session": "test"}
SRC1 = "src-01J9ZK3M4X0000000000000001"


def tree_hash(folder):
    out = {}
    for base, _dirs, files in os.walk(folder):
        for f in files:
            path = os.path.join(base, f)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, folder)] = hashlib.sha256(fh.read()).hexdigest()
    return out


class Base(unittest.TestCase):
    fixture = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        if self.fixture:
            shutil.copytree(FIXTURE, self.dir)
        else:
            os.makedirs(self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "PROBANDIA_SESSION": "test",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"), "LANG": "en_US.UTF-8"}

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        for line in out.splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    def research(self, rid=RID, family="hugo"):
        return Research(self.dir, family, rid)

    def log(self, rid=RID, family="hugo"):
        return events.read(self.research(rid, family).events_path)

    def index(self, name, family="hugo"):
        return yamlio.load(os.path.join(self.dir, "families", family, "index", f"{name}.yaml"))

    def write_index(self, name, doc, family="hugo"):
        yamlio.dump(os.path.join(self.dir, "families", family, "index", f"{name}.yaml"), doc)


class DefaultResearch(Base):
    def test_the_research_whose_pass_this_session_holds_comes_before_the_newest(self):
        from probandia.research import find_research
        from probandia.util.locks import Locks

        newer = "2026-10-10-another-question"
        shutil.copytree(self.research().folder, self.research(newer).folder)
        meta = self.research(newer).meta()
        meta.update(id=newer, created="2099-01-01T00:00:00Z")
        yamlio.dump(os.path.join(self.research(newer).folder, "research.yaml"), meta)
        Locks(self.dir).take(f"research:{RID}", {"harness": "cli", "session": "s1", "agent": "session"})
        self.assertEqual(find_research(self.dir, environ={"PROBANDIA_SESSION": "s1"}).id, RID)
        self.assertEqual(find_research(self.dir, newer, environ={"PROBANDIA_SESSION": "s1"}).id, newer)
        # several open and none held by this session (an expired lock, another session): name it, never guess
        self.assertEqual(find_research(self.dir, environ={"PROBANDIA_SESSION": "s2"}, fallback=True).id, newer)
        code, out = self.call("render", env={"PROBANDIA_SESSION": "s2"})
        self.assertEqual(code, 2, out)
        self.assertEqual((self.value(out, "REASON"), self.value(out, "OPEN")), ("research-not-named", "2"))
        self.assertIn(f"- open={newer}", out)
        self.assertIn(f"- open={RID}", out)
        code, out = self.call("render", env={"PROBANDIA_SESSION": "s1"})   # the session's own pass: no need
        self.assertEqual(code, 0, out)


class NewResearch(Base):
    Q = "Who were the parents of Victor Hugo, born about 1802 in Besançon?"

    def test_asks_who_runs_the_research(self):
        code, out = self.call("new", self.Q, "--family", "hugo")
        self.assertEqual(code, 3, out)
        self.assertIn("QUESTION=run_mode", out)
        self.assertIn("CHOICES=session|subagent|team", out)

    def test_records_the_choices(self):
        code, out = self.call("--lang", "fr", "new", self.Q, "--family", "hugo", "--report-mode", "living",
                              "--format", "md,html,json", "--mode", "session", "--instructions",
                              "Start with the Besançon sources")
        self.assertEqual(code, 0, out)
        rid = self.value(out, "RESEARCH")
        meta = self.research(rid).meta()
        self.assertEqual((meta["mode"], meta["formats"], meta["run"]["mode"], meta["language"]),
                         ("living", ["md", "html", "json"], "session", "fr"))
        self.assertEqual(meta["instructions"][0]["text"], "Start with the Besançon sources")
        # token-economy B1: in session mode, new runs the plan of the pass
        self.assertEqual([e["type"] for e in self.log(rid)], ["pass.started", "plan.made"])
        with open(os.path.join(self.dir, ".probandia", "locks", f"research-{rid}.json"), encoding="utf-8") as fh:
            lock = json.load(fh)
        self.assertEqual(lock["owner"]["session"], "test")

    def test_infers_a_known_family(self):
        code, out = self.call("new", "Qui étaient les parents de Victor Hugot ?", "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "FAMILY"), "hugo")
        self.assertEqual(self.value(out, "FAMILY_CREATED"), "false")

    def test_asks_the_family_only_when_it_cannot_infer_it(self):
        code, out = self.call("new", "Who were the parents of Marie LAFONTAINE?", "--mode", "session")
        self.assertEqual(code, 3, out)
        self.assertIn("QUESTION=family", out)
        self.assertIn("CHOICES=lafontaine", out)

    def test_run_mode_from_the_settings(self):
        self.call("config", "set", "run.mode", "session")
        code, out = self.call("new", self.Q, "--family", "hugo")
        self.assertEqual(code, 0, out)

    def test_team_asks_its_size(self):
        code, out = self.call("new", self.Q, "--family", "hugo", "--mode", "team")
        self.assertIn("QUESTION=team_agents", out)
        code, out = self.call("new", self.Q, "--family", "hugo", "--mode", "team", "--agents", "3",
                              "--effort", "high", "--passes", "2")
        self.assertEqual(code, 0, out)
        run = self.research(self.value(out, "RESEARCH")).meta()["run"]
        self.assertEqual(run, {"mode": "team", "max_agents": 3, "max_passes": 2, "effort": "high"})


class NewProject(Base):
    fixture = False

    def test_creates_the_project_and_the_family(self):
        code, out = self.call("new", "Who were the parents of Victor HUGO?", "--mode", "session",
                              "--prompt-lang", "fr")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "probandia.toml")))
        self.assertEqual(self.value(out, "FAMILY"), "hugo")
        self.assertEqual(self.value(out, "FAMILY_CREATED"), "true")
        self.assertEqual((self.value(out, "LANG"), self.value(out, "LANG_SOURCE")), ("fr", "prompt"))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "families", "hugo", "family.yaml")))
        self.assertTrue(self.value(out, "RESEARCH").endswith("who-were-the-parents-of-victor-hugo"))


class Passes(Base):
    def open_pass(self):
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        return int(self.value(out, "PASS"))

    def test_a_full_pass(self):
        n = self.open_pass()
        self.assertEqual(n, 2)
        code, out = self.call("plan", RID)
        self.assertEqual(code, 0, out)
        code, out = self.call("search", "--log-native", "--query", "Hugo Besançon 1802", "--results", "0")
        self.assertEqual(code, 0, out)
        code, out = self.call("pass", "end", RID, "--summary", "nothing new; ask the parish")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "NATIVE_SEARCHES"), "1")
        types = [e["type"] for e in self.log() if e["pass"] == 2]
        self.assertEqual(types, ["pass.started", "plan.made", "search.logged", "verify.run", "pass.ended"])
        self.assertEqual((self.value(out, "RENDERED"), self.value(out, "VERIFY")), ("OK", "OK"))   # B7
        self.assertEqual(self.research().meta()["passes"], 2)
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".probandia", "locks", f"research-{RID}.json")))
        self.assertEqual(verify.v1(verify.Context(self.dir, self.research()))[0], "FAIL")  # pass 1 has no plan

    def test_the_searcher_s_native_searches_hold_fl_d1(self):
        # T77: the first salvo's native searches go to a searcher; logged under its role, they count for the pass
        self.open_pass()
        self.call("plan", RID)
        for query in ("Hugo Besançon 1802", "Hugo Nancy 1800"):
            code, out = self.call("search", "--log-native", "--query", query, "--results", "0", "--agent", "searcher")
            self.assertEqual(code, 0, out)
        self.assertEqual({e["actor"]["agent"] for e in self.log() if e["type"] == "search.logged"}, {"searcher"})
        code, out = self.call("pass", "end", RID, "--summary", "nothing new; ask the parish")
        self.assertEqual((code, self.value(out, "STATUS"), self.value(out, "TOOLS_WEB")), (0, "OK", "2"), out)
        self.assertNotIn("no web search", out)

    def test_pass_end_counts_the_engine_calls_of_the_pass(self):
        # token-economy H2: a pass an agent runs from the command line; its engine calls, archive ones apart
        agent = {"CLAUDECODE": "1"}
        self.call("known", RID, env=agent)   # before the pass: not counted
        self.assertEqual(self.call("resume", RID, "--mode", "session", env=agent)[0], 0)   # 1
        self.call("plan", RID, env=agent)                                                  # 2
        self.call("known", RID, "--names", "Hugo", env=agent)                              # 3
        self.call("archive", "list", env=agent)                                            # 4, archive 1
        self.call("archive", "coverage", "Morbihan", env=agent)                            # 5, archive 2
        self.call("search", "--log-native", "--query", "Hugo Besançon", "--results", "0", env=agent)   # 6
        self.call("status")   # a person's, with no harness: not counted
        code, out = self.call("pass", "end", RID, "--summary", "a lead in Vianden; the 1801 census to read",
                              env=agent)
        self.assertEqual(code, 0, out)
        self.assertEqual([self.value(out, k) for k in ("TOOLS_WEB", "TOOLS_ARCHIVE", "TOOLS_ENGINE")], ["1", "2", "6"])
        self.assertEqual((self.value(out, "LEARN_CANDIDATES"), self.value(out, "MEMORY_CANDIDATES")), ("0", "0"))
        self.assertNotIn("ask the user once", out)   # no question without a candidate
        self.assertEqual(self.log()[-1]["payload"]["tools"]["engine"], 6)
        code, out = self.call("digest", RID)   # the summary's leads open the next digest
        self.assertIn("- LEADS:\n-   a lead in Vianden\n-   the 1801 census to read\n", out)
        self.call("known", RID, env=agent)   # after the pass: not counted, the lock is released
        with open(os.path.join(self.dir, lifecycle.CALLS), encoding="utf-8") as fh:
            self.assertEqual(len(fh.readlines()), 6)

    def test_the_tokens_of_the_pass_so_far(self):
        # token-economy I2: what log_tokens recorded for the open pass, in pass status and in the digest
        self.open_pass()
        code, out = self.call("pass", "status", RID)
        self.assertIsNone(self.value(out, "TOKENS"), out)   # nothing recorded yet: no key
        rows = [{"research": RID, "pass": 2, "role": "session", "input": 1000, "output": 200, "cache_read": 50000,
                 "cache_write": 3000},
                {"research": RID, "pass": 2, "role": "reader", "input": 10, "output": 0, "cache_read": 0,
                 "cache_write": 0},
                {"research": RID, "pass": 1, "role": "session", "input": 99999, "output": 0, "cache_read": 0,
                 "cache_write": 0}]
        with open(os.path.join(self.dir, ".probandia", "tokens.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))
        code, out = self.call("pass", "status", RID)
        self.assertEqual(self.value(out, "TOKENS"), "13010", out)   # 1000 + 5 × 200 + 0.1 × 50000 + 2 × 3000 + 10
        code, out = self.call("digest", RID)
        self.assertIn("\n- TOKENS=13010\n", out)

    def test_pass_end_tidies_work(self):
        # token-economy H4: the images of work/ no source and no transcription cites go; a cited one stays
        self.open_pass()
        self.call("plan", RID)
        work = self.research().work

        def write(rel, data=b"\xff\xd8\xff\xe0 image"):
            path = os.path.join(work, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            return path

        kept = [write("images/ad50-607643-0012.jpg"), write("dl/View-7.PNG")]
        gone = [write("images/band-12.jpg"), write("images/sheet-4-24.jpg"), write("dl/View-7-crop.png")]
        write("transcriptions/src-x.md", "| Image | work/dl/view-7.png |\n".encode())   # a reader's transcription
        doc = self.index("sources")
        doc["sources"][1]["image"] = f"research/{RID}/work/images/ad50-607643-0012.jpg"   # a source of the family
        self.write_index("sources", doc)
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual((code, self.value(out, "WORK_PURGED")), (0, "3"), out)
        self.assertEqual([os.path.exists(p) for p in kept + gone], [True, True, False, False, False])
        self.assertTrue(os.path.exists(os.path.join(work, "transcriptions", "src-x.md")))

    def unwitnessed_negative(self, pass_no):
        """A negative without its witness, logged in pass ``pass_no``: V-3 fails on it."""
        doc = self.index("searches")
        bad = dict(doc["searches"][1], id=f"s-01J9ZK5A00000000000000009{pass_no}", witness=None, **{"pass": pass_no})
        doc["searches"].append(bad)
        self.write_index("searches", doc)
        return bad["id"]

    def test_pass_end_tells_the_report_labels_still_in_english(self):
        # T70: the pass's report asks for labels its language's catalogue lacks; pass end says which file has them
        self.open_pass()
        self.call("plan", RID)
        self.call("search", "--log-native", "--query", "Hugo Besançon 1802", "--results", "0")
        po = os.path.join(self.dir, "locales", "de", "LC_MESSAGES", "probandia.po")
        os.makedirs(os.path.dirname(po))
        with open(po, "w", encoding="utf-8") as fh:
            fh.write('msgid "Contents"\nmsgstr "Inhalt"\n')
        code, out = self.call("-l", "de", "pass", "end", RID, "--summary", "done")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "RENDERED"), "WARN")
        self.assertGreater(int(self.value(out, "LABELS_MISSING")), 0)
        self.assertEqual((self.value(out, "POT"), self.value(out, "TARGET")),
                         ("locales/de/LC_MESSAGES/report-labels.pot", "locales/de/LC_MESSAGES/probandia.po"))

    def test_a_pass_whose_own_check_fails_stays_open(self):
        # B7: pass end renders, runs verify --light, and closes only when what the pass brought passes
        self.open_pass()
        self.call("plan", RID)
        sid = self.unwitnessed_negative(2)
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual(code, 1, out)
        self.assertEqual((self.value(out, "REASON"), self.value(out, "VERIFY"), self.value(out, "RENDERED")),
                         ("verify", "FAIL", "OK"))
        self.assertIn(f"- V-3=FAIL 1 negatives without a witness or their proof: {sid}", out)
        self.assertNotIn("V-2=", out)   # only the rules that fail
        self.assertEqual(self.value(self.call("pass", "status", RID)[1], "OPEN"), "true")
        self.assertTrue(os.path.exists(os.path.join(self.dir, ".probandia", "locks", f"research-{RID}.json")))

    def test_an_earlier_pass_left_wrong_is_told_but_does_not_hold_the_pass(self):
        self.open_pass()
        self.call("plan", RID)
        sid = self.unwitnessed_negative(1)
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=WARN"), out)
        self.assertEqual((self.value(out, "VERIFY"), self.value(out, "EARLIER_FAILED")), ("OK", "1"))
        self.assertIn(sid, out)
        self.assertEqual(self.value(self.call("pass", "status", RID)[1], "OPEN"), "false")
        run = [e for e in self.log() if e["type"] == "verify.run"][-1]
        self.assertEqual(run["payload"]["results"]["V-3"], "FAIL")   # the log keeps the research's state

    def test_a_pass_with_no_plan_does_not_close(self):
        # T226, criterion 11 at the bench: a second pass updated its question and closed with no plan, and only a
        # later verify said V-1. Its close says it now; an earlier pass's V-1 cannot be mended and holds nothing
        self.open_pass()
        code, out = self.call("pass", "end", RID, "--summary", "nothing to search")
        self.assertEqual((code, self.value(out, "REASON")), (1, "verify"), out)
        self.assertIn("V-1=FAIL pass ", out)
        self.assertEqual(self.value(self.call("pass", "status", RID)[1], "OPEN"), "true")
        self.call("plan", RID)
        code, out = self.call("pass", "end", RID, "--summary", "nothing to search")
        self.assertEqual(code, 0, out)
        self.assertNotIn("V-1", out)

    def test_interrupted_pass_closed(self):
        self.open_pass()
        self.call("plan", RID)
        self.call("search", "--log-native", "--query", "Hugo", "--results", "0")
        # the session dies here: no pass end
        code, out = self.call("resume", RID)
        self.assertEqual(code, 3, out)
        self.assertIn("QUESTION=interrupted_pass", out)
        code, out = self.call("resume", RID, "--interrupted", "close")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "PASS"), "3")
        ended = [e for e in self.log() if e["type"] == "pass.ended" and e["pass"] == 2]
        self.assertEqual(ended[0]["payload"]["summary"], "interrupted")
        self.assertEqual(events.check_chain(self.research().events_path), None)

    def test_interrupted_pass_continued(self):
        self.open_pass()
        code, out = self.call("resume", RID, "--interrupted", "continue", "--instructions", "go on")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "PASS"), self.value(out, "CONTINUED")), ("2", "true"))
        self.assertEqual([e["type"] for e in self.log()].count("pass.started"), 2)
        self.assertEqual(self.research().meta()["instructions"][-1], {
            "pass": 2, "ts": self.research().meta()["instructions"][-1]["ts"], "text": "go on"})

    def propose(self, pid, name):
        doc = {"schema": 1, "id": pid, "research": RID, "pass": 2,
               "author": {"harness": "cli", "agent": "researcher"},
               "hypotheses": [{"id": f"h-{name}", "question": "Who was Victor's wife?",
                               "hypotheses": [{"id": "a", "statement": "Adèle Foucher", "status": "open"}]}]}
        draft = os.path.join(self.research().work, "proposals", f"{name}.yaml")
        os.makedirs(os.path.dirname(draft), exist_ok=True)
        yamlio.dump(draft, doc)  # a field agent's draft, in the same folder: not a pending proposal
        code, out = self.call("propose", RID, draft, "--agent", "researcher")
        self.assertEqual(code, 0, out)

    def test_a_pass_ends_only_when_every_proposal_is_settled(self):
        self.open_pass()
        self.call("plan", RID)
        self.propose("01J9ZM00000000000000000071", "web-p2")
        self.propose("01J9ZM00000000000000000072", "archives-p2")
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual(code, 2, out)
        self.assertEqual((self.value(out, "REASON"), self.value(out, "PENDING")), ("pending-proposals", "2"))
        self.assertIn("- pending=01J9ZM00000000000000000072", out)
        code, out = self.call("apply", "01J9ZM00000000000000000071")
        self.assertEqual(code, 0, out)
        code, out = self.call("apply", "01J9ZM00000000000000000072", "--drop", "duplicate", "--agent",
                              "researcher")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-allowed"))
        code, out = self.call("apply", "01J9ZM00000000000000000072", "--drop", "duplicate of the web proposal")
        self.assertEqual((code, self.value(out, "STATE")), (0, "dropped"), out)
        result = yamlio.load(os.path.join(self.research().work, "proposals", "01J9ZM00000000000000000072.result"))
        self.assertEqual((result["status"], result["reasons"]), ("dropped", ["duplicate of the web proposal"]))
        code, out = self.call("apply", "01J9ZM00000000000000000071", "--drop", "too late")
        self.assertEqual((code, self.value(out, "REASON")), (2, "applied"))
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual(code, 0, out)
        self.assertEqual([e["type"] for e in self.log() if e["pass"] == 2].count("hypothesis.opened"), 1)

    def test_a_proposal_its_dry_run_rejected_ends_the_pass_only_once_replaced_or_dropped(self):
        # J10: since J8 it no longer waits; left so, its findings would never be recorded
        self.open_pass()
        self.call("plan", RID)
        fact = {"id": "nobody-1820.birth", "type": "birth", "date": {"value": "1820", "qualifier": "about"},
                "place": None, "status": "hypothesis", "source": None, "note": ""}
        draft = os.path.join(self.research().work, "pass2.yaml")
        yamlio.dump(draft, {"facts": [fact]})
        code, out = self.call("propose", draft, "--apply")
        self.assertIn("- verdict=would-reject", out)
        first = self.value(out, "PROPOSAL")
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual((code, self.value(out, "REASON")), (2, "pending-proposals"), out)
        self.assertIn(f"- pending={first} rejected", out)
        # a field agent's proposal applied since replaces nothing of the session's
        self.propose("01J9ZM00000000000000000073", "web-p2")
        self.assertEqual(self.call("apply", "01J9ZM00000000000000000073")[0], 0)
        self.assertIn(f"- pending={first} rejected", self.call("pass", "end", RID, "--summary", "done")[1])
        # the session's corrected proposal, applied: the rejected one is settled
        yamlio.dump(draft, {"hypotheses": [{"id": "h-corrected", "question": "Who was Victor's mother?",
                                            "hypotheses": [{"id": "a", "statement": "Sophie Trébuchet", "status": "open"}]}]})
        code, out = self.call("propose", draft, "--apply")
        self.assertIn("APPLIED=true", out)
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual(code, 0, out)

    def test_an_act_transcribed_in_the_pass_and_never_proposed_keeps_it_open(self):
        # J12: a pass closed at the bench of I3 with two acts read and no fact recorded
        def transcribe():
            code, out = self.call("transcribe", "new", "--image", "work/images/ad50-607650-0020.jpg")
            self.assertEqual(code, 0, out)
            return self.value(out, "SOURCE")

        before = transcribe()   # made before the pass: not this pass's
        self.open_pass()
        self.call("plan", RID)
        recorded, left = transcribe(), transcribe()
        index = os.path.join(self.dir, "families", "hugo", "index", "sources.yaml")
        sources = yamlio.load(index)
        sources["sources"].append(dict(sources["sources"][0], id=recorded))   # as an applied proposal does
        yamlio.dump(index, sources)
        code, out = self.call("pass", "end", RID, "--summary", "done")
        self.assertEqual((code, self.value(out, "REASON"), self.value(out, "UNRECORDED")),
                         (2, "unrecorded-transcriptions", "1"), out)
        self.assertIn(f"- transcription={left}\n", out)
        self.assertNotIn(before, out)
        # T84: the reason excuses an act too many, not a pass that applied no proposal at all
        code, out = self.call("pass", "end", RID, "--summary", "done", "--unrecorded", "the act of a namesake")
        self.assertEqual((code, self.value(out, "REASON")), (2, "nothing-recorded"), out)
        self.propose("01J9ZM00000000000000000074", "web-p2")
        self.assertEqual(self.call("apply", "01J9ZM00000000000000000074")[0], 0)
        code, out = self.call("pass", "end", RID, "--summary", "done", "--unrecorded", "the act of a namesake")
        self.assertEqual(code, 0, out)
        ended = [e for e in self.log() if e["type"] == "pass.ended"][-1]
        self.assertIn(f"transcriptions not recorded ({left}): the act of a namesake", ended["payload"]["summary"])

    def test_a_draft_applied_by_its_path_settles_its_stored_copy(self):
        self.open_pass()
        self.call("plan", RID)
        folder = os.path.join(self.research().work, "proposals")
        os.makedirs(folder, exist_ok=True)
        draft = os.path.join(folder, "pass2-parents.yaml")
        yamlio.dump(draft, {"schema": 1, "research": RID, "pass": 2,
                            "author": {"harness": "cli", "agent": "session"},
                            "hypotheses": [{"id": "h-mother", "question": "Who was Victor's mother?",
                                            "hypotheses": [{"id": "a", "statement": "Sophie Trébuchet"}]}]})
        code, out = self.call("apply", draft)  # propose was skipped, and the draft has no id
        self.assertEqual(code, 0, out)
        pid = self.value(out, "PROPOSAL")
        self.assertEqual(yamlio.load(draft)["id"], pid)
        self.assertFalse(os.path.exists(os.path.join(folder, "pass2-parents.result")))
        self.assertEqual(yamlio.load(os.path.join(folder, f"{pid}.result"))["status"], "accepted")
        code, out = self.call("apply", draft)
        self.assertIn("already applied", out)
        self.assertEqual(self.call("pass", "end", RID, "--summary", "done")[0], 0)
        self.assertEqual([e["type"] for e in self.log()].count("hypothesis.opened"), 1)

    def test_nothing_is_logged_after_pass_end(self):
        from probandia.providers import searchlog

        self.open_pass()
        self.call("plan", RID)
        real = verify.run
        ended = []

        def closing(*args, **kw):  # a pass end run at the same time as verify; it runs verify itself
            if not ended:
                ended.append(True)
                self.assertEqual(self.call("pass", "end", RID, "--summary", "done")[0], 0)
            return real(*args, **kw)

        with mock.patch.object(verify, "run", closing):
            code, out = self.call("verify", RID, "--light")
        entry = searchlog.entry("Hugo Vianden", "native", "claude-code", "-", "negative", RID, 2, 0)
        searchlog.append(self.dir, "hugo", [entry], ACTOR)
        self.assertEqual([e["type"] for e in self.log() if e["pass"] == 2][-1], "pass.ended")
        self.assertIn(entry["id"], [s["id"] for s in self.index("searches")["searches"]])
        self.assertNotIn("pass 2", " ".join(str(x) for x in verify.v1(verify.Context(self.dir, self.research()))))

    def test_a_field_agent_reads_the_plan_without_making_it(self):
        self.open_pass()
        code, out = self.call("plan", RID, "--agent", "researcher")
        self.assertEqual(code, 0, out)
        plan = os.path.join(self.research().work, "plan-2.yaml")
        self.assertFalse(os.path.exists(plan))
        self.assertNotIn("plan.made", [e["type"] for e in self.log()])
        code, out = self.call("plan", RID, "--agent", "orchestrator")
        self.assertEqual(code, 0, out)
        with open(plan, "rb") as fh:
            before = fh.read()
        code, out = self.call("plan", RID, "--agent", "researcher", "--question-type", "death")
        self.assertEqual((code, self.value(out, "TYPE")), (0, "parents"), out)  # the orchestrator's plan
        with open(plan, "rb") as fh:
            self.assertEqual(fh.read(), before)
        made = [e["actor"]["agent"] for e in self.log() if e["type"] == "plan.made"]
        self.assertEqual(made, ["orchestrator"])

    def test_the_lock_keeps_other_sessions_out(self):
        from probandia.errors import LockHeld

        self.open_pass()
        other = dict(ACTOR, session="other")
        with self.assertRaises(LockHeld):
            lifecycle.take_research_lock(self.dir, self.research(), other, 30)
        # the same session, another agent: the pass's own writes go through
        same = dict(ACTOR, agent="orchestrator")
        lifecycle.take_research_lock(self.dir, self.research(), same, 30)


class Digest(Base):
    def negative(self, recheck_if=None, recheck_after=None, ts=None, count=1):
        doc = self.index("searches")
        for _ in range(count):   # the index is written once, however many searches are added
            entry = {"id": f"s-{ulid()}", "ts": ts or iso(utc_now()), "research": RID, "pass": 1,
                     "kind": "archive", "engine": "socface", "family": None, "query": "HUGO Manche 1906",
                     "variants": ["Hugo"], "filters": None, "window": {"from": 1906, "to": 1906, "places": ["FR-50"]},
                     "results": 0, "result": "negative", "failure": None, "support": "index", "witness": None,
                     "source_state": "ok", "recheck_if": recheck_if, "recheck_after": recheck_after, "units": None,
                     "proves": None}
            doc["searches"].append(entry)
        self.write_index("searches", doc)
        return entry["id"]

    def digest(self):
        code, out = self.call("digest", RID)
        self.assertEqual(code, 0, out)
        path = os.path.join(self.dir, self.value(out, "DETAILS"))
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_fixed_order_and_size(self):
        lines = self.digest()
        self.assertLessEqual(len(lines), 60)
        heads = [line.split("=")[0].split(":")[0].split(" ")[0] for line in lines if not line.startswith("  ")]
        order = ["RESEARCH", "QUESTION", "INSTRUCTION", "LEADS", "HYPOTHESES", "ERRATA_PENDING", "NEGATIVES_DUE",
                 "NEW_FACTS", "MANUAL_TASKS", "QUOTAS", "LOCKS", "NEXT"]
        self.assertEqual(heads, [h for h in order if h in heads])
        self.assertIn("  h-father-of-victor Who was the father of Victor Hugo?", "\n".join(lines))
        # E6: a section with nothing under it is left out (no pending erratum, no new fact, no lock here)
        self.assertEqual([h for h in ("ERRATA_PENDING", "NEW_FACTS", "LOCKS") if h in heads], [])
        empty = [x for i, x in enumerate(lines[:-1]) if x.endswith(":") and not lines[i + 1].startswith("  ")]
        self.assertEqual(empty, [])

    def test_recheck_if_met_after_a_catalogue_change(self):
        sid = self.negative(recheck_if="socface covers FR-50")
        self.assertNotIn(sid, "\n".join(self.digest()))  # the Manche is absent from SocFace
        from probandia.archives.finder import load_catalogue

        entry = dict(load_catalogue()["socface"])
        entry["coverage"] = dict(entry["coverage"], absent=["FR-2A", "FR-2B"])
        os.makedirs(os.path.join(self.dir, "library"), exist_ok=True)
        yamlio.dump(os.path.join(self.dir, "library", "archives.yaml"), {"archives": [entry]})
        lines = self.digest()
        due = lines[lines.index("NEGATIVES_DUE:") + 1]
        self.assertIn(sid, due)
        self.assertIn("recheck_if met: socface covers FR-50", due)

    def test_recheck_after_and_age(self):
        old = self.negative(recheck_after="2020-01-01")
        fresh = self.negative(recheck_after="2999-01-01")
        text = "\n".join(self.digest())
        self.assertIn(old, text)
        self.assertNotIn(fresh, text)

    def test_capped_lines(self):
        self.negative(recheck_after="2020-01-01", count=80)
        doc = self.index("hypotheses")   # enough sections filled to pass the cap
        doc["hypotheses"] += [dict(doc["hypotheses"][0], id=f"h-copy-{i}") for i in range(8)]
        self.write_index("hypotheses", doc)
        self.call("config", "set", "digest.max_lines", "20")
        lines = self.digest()
        self.assertEqual(len(lines), 20)
        self.assertTrue(lines[-1].startswith("NEXT="))

    def test_resume_reads_no_report(self):
        self.call("render", RID)
        opened = []
        real = builtins.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)
        with mock.patch("builtins.open", spy):
            code, out = self.call("resume", RID, "--mode", "session", "--instructions", "Now the Doubs")
        self.assertEqual(code, 0, out)
        self.assertFalse([p for p in opened if os.sep + "report" + os.sep in os.path.normpath(p)])
        self.assertLessEqual(int(self.value(out, "DIGEST_LINES")), 60)
        self.assertIn("- INSTRUCTION=Now the Doubs", out)


class Fork(Base):
    def test_fork_keeps_the_chain_and_leaves_the_original(self):
        original = self.research()
        before = tree_hash(original.folder)
        code, out = self.call("fork", RID, "--name", "other-father", "--instructions", "Try Nancy")
        self.assertEqual(code, 0, out)
        child = self.research(self.value(out, "RESEARCH"))
        self.assertTrue(child.id.endswith("-other-father"))
        meta = child.meta()
        self.assertEqual(meta["forked_from"], {"research": RID, "pass": 1})
        self.assertEqual(meta["instructions"][-1]["text"], "Try Nancy")
        self.assertEqual(events.read_lines(child.events_path)[:3], events.read_lines(original.events_path)[:3])
        self.assertIsNone(events.check_chain(child.events_path))
        self.assertTrue(os.path.isfile(os.path.join(child.folder, "report", "report.json")))
        self.assertFalse(os.path.exists(os.path.join(child.folder, "work", "proposals")))
        # a pass in the fork
        self.assertEqual(self.value(out, "PASS"), "2")
        self.call("plan", child.id)
        code, out = self.call("pass", "end", child.id, "--summary", "done")
        self.assertEqual(code, 0, out)
        self.assertEqual(tree_hash(original.folder), before)

    def test_a_fork_keeps_the_native_searches_of_its_passes(self):
        # T262: the passes a fork inherits keep the native searches the origin logged (V-12)
        self.assertEqual(self.call("resume", RID, "--mode", "session")[0], 0)
        self.call("plan", RID)
        self.call("search", "--log-native", "--query", "Hugo Besançon 1802", "--results", "0")
        code, out = self.call("pass", "end", RID, "--summary", "a lead")
        self.assertEqual(code, 0, out)
        code, out = self.call("fork", RID, "--no-pass")
        self.assertEqual(code, 0, out)
        child = self.value(out, "RESEARCH")
        code, out = self.call("verify", child)
        self.assertNotIn("V-12=FAIL", out)
        code, out = self.call("verify", RID)
        self.assertNotIn("V-12=FAIL", out)

    def test_default_name_and_new_family(self):
        code, out = self.call("fork", RID, "--new-family", "hugo-nancy", "--no-pass")
        self.assertEqual(code, 0, out)
        rid = self.value(out, "RESEARCH")
        self.assertTrue(rid.endswith("parents-of-victor-hugo-fork-1"))
        self.assertEqual(self.value(out, "FAMILY"), "hugo-nancy")
        fam = os.path.join(self.dir, "families", "hugo-nancy")
        self.assertEqual(yamlio.load(os.path.join(fam, "family.yaml"))["id"], "hugo-nancy")
        self.assertTrue(os.path.isfile(os.path.join(fam, "index", "persons.yaml")))
        self.assertTrue(os.path.isdir(os.path.join(fam, "research", rid)))

    def test_a_pass_not_completed(self):
        code, out = self.call("fork", RID, "--at", "4")
        self.assertEqual(code, 2, out)


class Sample(Base):
    """A copy of tests/sample-project."""
    fixture = False
    SAMPLE = "2026-09-01-ancestors-of-louis-marchand"

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.dir)
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)


class ForkReport(Sample):
    """PRD criterion 8, as T226 made it precise: a pass in the fork changes no file of the original; rendered
    again, the original keeps its passes byte for byte, and only its timelines, which show the family's shared
    index (R-5), take the fork's facts."""

    def test_the_fork_shows_only_in_the_timelines(self):
        original = self.research(self.SAMPLE, "marchand")
        self.assertEqual(self.call("report", "render", self.SAMPLE)[0], 0)
        report = os.path.join(original.folder, "report", "report.md")
        with open(report, encoding="utf-8") as fh:
            before = fh.read()
        files = tree_hash(original.folder)
        code, out = self.call("fork", self.SAMPLE)
        self.assertEqual(code, 0, out)
        fork, n = self.value(out, "RESEARCH"), self.value(out, "PASS")
        path = os.path.join(self.tmp.name, "fork.yaml")
        yamlio.dump(path, {"schema": 1, "research": fork, "pass": int(n),
                           "author": {"harness": "cli", "agent": "session"},
                           "facts": [{"id": "louis-marchand-1898.residence", "type": "residence",
                                      "date": {"value": "1920", "qualifier": "about"},
                                      "place": {"id": None, "as_written": "Bourg-Vert"}, "status": "index",
                                      "source": "src-01JA0000000000000000000001"}],
                           "sections": [{"parent": None, "kind": "chapter", "title": "Fork",
                                         "body_md": "Bourg-Vert [[f:louis-marchand-1898.residence]].",
                                         "facts": ["louis-marchand-1898.residence"]}]})
        code, out = self.call("propose", fork, path, "--apply")
        self.assertEqual(code, 0, out)
        self.call("pass", "end", fork, "--summary", "a residence")
        self.assertEqual(tree_hash(original.folder), files)   # no file of the original changed
        self.assertEqual(self.call("report", "render", self.SAMPLE)[0], 0)
        with open(report, encoding="utf-8") as fh:
            after = fh.read()
        timelines = after.index('<a id="s-timelines">')
        self.assertEqual(after[:timelines], before[:timelines])   # its passes, byte for byte
        added = [line for line in after.splitlines() if line not in before.splitlines()]
        self.assertEqual(added, ["| 1920 | 22 | résidence | Bourg-Vert |  |"])


class JournalReport(Sample):
    """PRD criterion 6 (T226): an error of pass 1 found at pass 3 adds an erratum; the text pass 1 shows, its
    tree and its notes, stays the same, its fingerprint (report/passes.json) with it."""

    def passes(self, folder):
        with open(os.path.join(folder, "report", "passes.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_an_erratum_leaves_the_earlier_pass_as_it_was(self):
        original = self.research(self.SAMPLE, "marchand")
        self.assertEqual(self.call("report", "render", self.SAMPLE)[0], 0)
        report = os.path.join(original.folder, "report", "report.md")
        with open(report, encoding="utf-8") as fh:
            before = fh.read()
        prints = self.passes(original.folder)
        self.assertEqual(self.call("resume", self.SAMPLE, "--mode", "session")[0], 0)
        path = os.path.join(self.tmp.name, "refute.yaml")
        yamlio.dump(path, {"schema": 1, "research": self.SAMPLE, "pass": 3,
                           "author": {"harness": "cli", "agent": "session"},
                           "refutations": [{"fact": "louis-marchand-1898.birth", "cause": "homonym",
                                            "reason": "the act read at pass 1 is a namesake's"}],
                           "sections": [{"parent": None, "kind": "chapter", "title": "Correction",
                                         "body_md": "Refuted: [[f:louis-marchand-1898.birth]].",
                                         "facts": ["louis-marchand-1898.birth"]}]})
        code, out = self.call("propose", self.SAMPLE, path, "--apply")
        self.assertEqual(code, 0, out)
        code, out = self.call("report", "render", self.SAMPLE)
        self.assertEqual(code, 0, out)
        self.assertNotIn("pass-text-changed", out)
        with open(report, encoding="utf-8") as fh:
            after = fh.read()
        start, end = before.index('<a id="s-pass-1">'), before.index('<a id="s-pass-2">')
        first = after[after.index('<a id="s-pass-1">'):after.index('<a id="s-pass-2">')]
        erratum = [line for line in first.splitlines() if line.startswith("> **†**")]
        self.assertEqual(len(erratum), 1)   # the erratum's notice, after the section
        self.assertEqual(first.replace(" †E1", "").replace(erratum[0] + "\n\n", ""), before[start:end])
        self.assertEqual({p: h for p, h in self.passes(original.folder).items() if p in prints}, prints)
        # a change made outside the log (the index edited by hand) is caught by the fingerprint
        persons = os.path.join(self.dir, "families", "marchand", "index", "persons.yaml")
        doc = yamlio.load(persons)
        for person in doc["persons"]:
            for f in person.get("facts") or []:
                if f["id"] == "louis-marchand-1898.death":
                    f["date"] = {"value": "1971", "qualifier": "exact"}
        yamlio.dump(persons, doc)
        code, out = self.call("report", "render", self.SAMPLE)
        self.assertIn("REASON=pass-text-changed", out)


class Rules(Base):
    """Each rule has a case that fails it and one that passes it."""

    def ev(self, type_, payload, p=1, ts=None):
        e = events.make(type_, payload, ACTOR, p, now=ts)
        return e

    def append(self, *evs):
        events.append(self.research().events_path, list(evs))

    def check(self, rule, today=None):
        return verify.run(self.dir, self.research(), rules=[rule], today=today)[0][1]

    def set_mode(self, mode):
        path = os.path.join(self.research().folder, "research.yaml")
        meta = yamlio.load(path)
        meta["mode"] = mode
        yamlio.dump(path, meta)

    def section(self, body="", facts=(), sid=None):
        return {"section": {"id": sid or ulid(), "parent": None, "kind": "chapter", "title": "T",
                            "body_md": body, "facts": list(facts)}}

    def test_v1(self):
        self.append(self.ev("pass.started", {"n": 2}, 2), self.ev("plan.made", {}, 2),
                    self.ev("search.logged", {"search": "s-x"}, 2), self.ev("section.added", self.section(), 2),
                    self.ev("pass.ended", {"n": 2}, 2))
        c = verify.Context(self.dir, self.research())
        c.log = [e for e in c.log if e["pass"] == 2]
        self.assertEqual(verify.v1(c)[0], "PASS")
        self.append(self.ev("pass.started", {"n": 3}, 3), self.ev("section.added", self.section(), 3),
                    self.ev("plan.made", {}, 3))
        self.assertEqual(self.check("V-1"), "FAIL")

    def test_v2_an_online_tree_is_a_hypothesis_at_most(self):
        # T238: an index written before P-2 refused it still holds a fact that an online tree founds
        tree = "src-01J9ZK3M4X0000000000000098"
        sources = self.index("sources")
        sources["sources"].append({"id": tree, "type": "online-tree", "title": "Hugo", "publisher": "Geneanet"})
        self.write_index("sources", sources)
        doc = self.index("persons")
        doc["persons"][0]["facts"].append({"id": "victor-hugo-1802.death", "type": "death", "status": "index",
                                            "source": tree, "research": RID})
        self.write_index("persons", doc)
        found = verify.run(self.dir, self.research(), rules=["V-2"])[0]
        self.assertEqual(found[1], "FAIL")
        self.assertIn("victor-hugo-1802.death (index on an online tree)", found[2])
        doc["persons"][0]["facts"][-1]["status"] = "hypothesis"
        self.write_index("persons", doc)
        self.assertEqual(self.check("V-2"), "PASS")

    def test_v2(self):
        self.assertEqual(self.check("V-2"), "PASS")
        doc = self.index("persons")
        doc["persons"][0]["facts"].append({"id": "victor-hugo-1802.death", "type": "death", "status": "record",
                                            "source": "src-01J9ZK3M4X0000000000000099", "research": RID})
        self.write_index("persons", doc)
        self.assertEqual(self.check("V-2"), "FAIL")
        # B7: scoped to a pass, a rule looks at what that pass brought only
        doc["persons"][0]["facts"][-1]["pass"] = 1
        self.write_index("persons", doc)
        scoped = {p: verify.run(self.dir, self.research(), rules=["V-2"], pass_no=p)[0][1] for p in (1, 2)}
        self.assertEqual(scoped, {1: "FAIL", 2: "PASS"})
        self.append(self.ev("fact.revised", {"cause": "nonsense"}, 1))
        self.assertEqual(verify.run(self.dir, self.research(), rules=["V-4"], pass_no=2)[0][1], "PASS")
        self.assertEqual(self.check("V-4"), "FAIL")

    def negative(self, witness):
        doc = self.index("searches")
        doc["searches"] = [s for s in doc["searches"] if s.get("result") != "negative"]
        doc["searches"].append({"id": "s-01J9ZM00000000000000000001", "ts": "2026-09-30T19:00:00Z",
                                "research": RID, "pass": 1, "kind": "archive", "engine": "ad56", "family": None,
                                "query": "Hugo", "variants": ["Hugo", "Hugot"],
                                "window": {"from": 1880, "to": 1895, "places": ["FR-56"]}, "result": "negative",
                                "failure": None, "witness": witness, "source_state": "ok"})
        self.write_index("searches", doc)

    def test_v3(self):
        self.negative({"operation": "search", "passed": True, "ts": "2026-09-30T18:30:00Z"})
        self.assertEqual(self.check("V-3"), "PASS")
        self.negative({"operation": "search", "passed": True, "ts": "2026-09-25T18:30:00Z"})
        self.assertEqual(self.check("V-3"), "FAIL")
        self.negative(None)
        self.assertEqual(self.check("V-3"), "FAIL")

    def test_v4(self):
        self.assertEqual(self.check("V-4"), "PASS")
        self.append(self.ev("erratum.recorded", {"erratum": "E1", "target": {}, "wrong": "a", "correction": "b",
                                                 "cause": "misreading"}))
        self.assertEqual(self.check("V-4"), "PASS")
        self.append(self.ev("section.replaced", {"section": "x", "reason": "r"}))
        self.assertEqual(self.check("V-4"), "FAIL")

    def test_v5(self):
        self.set_mode("living")
        sid = ulid()
        self.append(self.ev("section.added", self.section(sid=sid)),
                    self.ev("section.replaced", {"section": sid, "body_md": "b", "reason": "a new record"}))
        self.assertEqual(self.check("V-5"), "PASS")
        self.append(self.ev("section.moved", {"section": sid, "parent": None}))
        self.assertEqual(self.check("V-5"), "FAIL")

    def test_v6(self):
        sid = ulid()
        self.append(self.ev("section.added", self.section(f"See [[s:{sid}]].", sid=sid)))
        self.assertEqual(self.check("V-6"), "PASS")
        self.append(self.ev("section.added", self.section("See [[s:01J9ZM99999999999999999999]].")))
        self.assertEqual(self.check("V-6"), "FAIL")

    def test_v7(self):
        self.assertEqual(self.check("V-7"), "FAIL")  # the fixture's pass 1 asserts a fact no section cites
        self.append(self.ev("section.added", self.section("Born [[f:victor-hugo-1802.birth]].")))
        self.assertEqual(self.check("V-7"), "PASS")
        self.append(self.ev("section.added", self.section("[[f:nobody-1900.birth]]")))
        self.assertEqual(self.check("V-7"), "FAIL")

    def test_v8(self):
        self.assertEqual(self.check("V-8"), "PASS")
        self.append(self.ev("branch.added", {"root": "victor-hugo-1802", "persons": ["victor-hugo-1802"]},
                            ts=datetime.datetime(2026, 9, 30, 19, 0, tzinfo=datetime.timezone.utc)))
        self.assertEqual(self.check("V-8"), "FAIL")
        trees = os.path.join(self.research().folder, "trees")
        os.makedirs(trees)
        with open(os.path.join(trees, "pass-1.svg"), "w", encoding="utf-8") as fh:
            fh.write("<svg/>")
        self.assertEqual(self.check("V-8"), "PASS")

    def test_v9(self):
        doc = self.index("persons")
        doc["persons"].append({"id": "camille-vernier-1966", "names": {"given": "Camille", "surname": "VERNIER"},
                               "living": "auto", "facts": [{"id": "camille-vernier-1966.birth", "type": "birth",
                                                            "status": "record", "date": {"value": "1966-05-02"}}]})
        self.write_index("persons", doc)
        folder = os.path.join(self.research().folder, "report")
        os.makedirs(folder)
        with open(os.path.join(folder, "report.md"), "w", encoding="utf-8") as fh:
            fh.write("Personne vivante, née en 1966.\n")
        self.assertEqual(self.check("V-9", today=datetime.date(2026, 10, 1)), "PASS")
        with open(os.path.join(folder, "report.md"), "w", encoding="utf-8") as fh:
            fh.write("Camille Vernier, née le 1966-05-02.\n")
        self.assertEqual(self.check("V-9", today=datetime.date(2026, 10, 1)), "FAIL")

    def test_v9_reads_the_gedcom_exports(self):
        # T241: an export of the family, written before the export masked her, names a person presumed living
        import zipfile

        doc = self.index("persons")
        doc["persons"].append({"id": "camille-vernier-1966", "names": {"given": "Camille", "surname": "VERNIER"},
                               "living": "auto", "facts": [{"id": "camille-vernier-1966.birth", "type": "birth",
                                                            "status": "record", "date": {"value": "1966-05-02"}}]})
        self.write_index("persons", doc)
        exports = os.path.join(self.dir, "exports")
        os.makedirs(exports)
        with open(os.path.join(exports, "hugo-2026-10-01.ged"), "w", encoding="utf-8") as fh:
            fh.write("0 HEAD\n0 @S1@ SOUR\n1 TITL Mairie de Nancy\n0 TRLR\n")
        with open(os.path.join(exports, "other-2026-10-01.ged"), "w", encoding="utf-8") as fh:
            fh.write("1 NOTE Camille VERNIER\n")   # another family's export: not this research's
        found = verify.run(self.dir, self.research(), rules=["V-9"], today=datetime.date(2026, 10, 1))[0]
        self.assertEqual(found[1], "PASS", found)
        with zipfile.ZipFile(os.path.join(exports, "hugo-2026-10-02.gdz"), "w") as z:
            z.writestr("gedcom.ged", "0 HEAD\n1 NOTE acte de naissance de Camille VERNIER, 2 MAY 1966\n0 TRLR\n")
        found = verify.run(self.dir, self.research(), rules=["V-9"], today=datetime.date(2026, 10, 1))[0]
        self.assertEqual(found[1], "FAIL")
        self.assertIn("hugo-2026-10-02.gdz (name)", found[2])
        self.assertIn("hugo-2026-10-02.gdz (date)", found[2])

    def ledger(self, units):
        path = os.path.join(self.dir, ".probandia", "ledger.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": iso(utc_now()), "provider": "tavily", "operation": "search", "units": units,
                                 "research": RID, "pass": 1, "source": "response"}) + "\n")

    def test_v10(self):
        self.ledger(5)
        self.assertEqual(self.check("V-10"), "PASS")
        self.ledger(1001)
        self.assertEqual(self.check("V-10"), "FAIL")

    def test_v11(self):
        lib = os.path.join(self.dir, "library")
        os.makedirs(lib)
        script = {"id": "ad25-anubis-client", "kind": "connector", "purpose": "p", "status": "draft", "version": 1,
                  "runs": {"ok": 1, "failed": 0, "last_ok": "2026-09-30T18:50:00Z"}}
        yamlio.dump(os.path.join(lib, "manifest.yaml"), {"schema": 1, "scripts": [script]})
        used = datetime.datetime(2026, 9, 30, 19, 0, tzinfo=datetime.timezone.utc)
        self.append(self.ev("library.used", {"script": "ad25-anubis-client", "version": 1}, ts=used))
        self.assertEqual(self.check("V-11"), "FAIL")
        script["status"] = "tested"
        yamlio.dump(os.path.join(lib, "manifest.yaml"), {"schema": 1, "scripts": [script]})
        self.assertEqual(self.check("V-11"), "PASS")

    def test_v12(self):
        self.assertEqual(self.check("V-12"), "PASS")
        self.append(self.ev("pass.started", {"n": 2}, 2), self.ev("pass.ended", {"n": 2, "native_searches": 2}, 2))
        self.assertEqual(self.check("V-12"), "FAIL")

    def test_v20(self):
        # T242: an answered question whose concluding fact was refuted fails, until reopened or answered anew
        path = os.path.join(self.research().folder, "research.yaml")
        meta = yamlio.load(path)
        q1 = {"id": "Q1", "text": "Who were the parents of Victor Hugo?", "type": "parents", "status": "answered",
              "persons": ["victor-hugo-1802"], "conclusion": ["victor-hugo-1802.birth"]}
        yamlio.dump(path, dict(meta, questions=[q1]))
        self.assertEqual(self.check("V-20"), "PASS")
        doc = self.index("persons")
        doc["persons"][0]["facts"][0]["status"] = "refuted"
        self.write_index("persons", doc)
        found = verify.run(self.dir, self.research(), rules=["V-20"])[0]
        self.assertEqual(found, ("V-20", "FAIL", "Q1 is answered on refuted facts: victor-hugo-1802.birth"))
        # an analysis named in the conclusion stands for the fact it retained
        self.write_index("analyses", {"schema": 1, "analyses": [{
            "id": "an-victor-hugo-1802-birth", "person": "victor-hugo-1802", "fact_kind": "birth", "status": "resolved",
            "items": [{"fact": "victor-hugo-1802.birth", "asserts": "1802"}],
            "resolution": {"value": "1802", "fact": "victor-hugo-1802.birth", "reasoning": "the record"}}]})
        yamlio.dump(path, dict(meta, questions=[dict(q1, conclusion=["an-victor-hugo-1802-birth"])]))
        self.assertEqual(self.check("V-20"), "FAIL")
        yamlio.dump(path, dict(meta, questions=[dict(q1, conclusion=["leopold-hugo-1773.birth"])]))
        self.assertEqual(self.check("V-20"), "PASS")   # answered with another fact
        reopened = {k: v for k, v in q1.items() if k != "conclusion"}
        yamlio.dump(path, dict(meta, questions=[dict(reopened, status="open")]))
        self.assertEqual(self.check("V-20"), "PASS")

    def test_light_and_exit_code(self):
        code, out = self.call("verify", RID, "--light")
        self.assertEqual(out, "STATUS=OK\nRULES=5\nFAILED=0\n")   # F2: a check that passes, in 3 lines
        code, out = self.call("verify", RID, "--light", "--all")
        self.assertIn("V-2=PASS", out)
        self.assertNotIn("V-1=", out)
        self.assertIn("V-4=", out)
        code, out = self.call("verify", RID, "--rule", "V-7")
        self.assertEqual(code, 1, out)
        self.assertIn("V-7=FAIL", out)
        code, out = self.call("verify", RID, "--rule", "V-99")
        self.assertEqual(code, 2)


class Status(Base):
    def test_fast_and_without_reports(self):
        self.call("render", RID)
        opened = []
        real = builtins.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)
        start = time.monotonic()
        with mock.patch("builtins.open", spy):
            code, out = self.call("status")
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(code, 0, out)
        self.assertIn(f"- research={RID} [open] 1 passes journal fr", out)
        self.assertFalse([p for p in opened if os.sep + "report" + os.sep in os.path.normpath(p)])


class Import(Base):
    def setUp(self):
        super().setUp()
        self.workshop = os.path.join(self.tmp.name, "workshop")
        shutil.copytree(WORKSHOP, self.workshop)
        os.remove(os.path.join(self.dir, "families", "hugo", "family.yaml"))
        shutil.rmtree(os.path.join(self.dir, "families", "hugo"))

    def test_import_and_workshop_unchanged(self):
        before = tree_hash(self.workshop)
        code, out = self.call("import", self.workshop, "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "families", "hugo")))
        code, out = self.call("import", self.workshop)
        self.assertEqual(code, 0, out)
        self.assertEqual(tree_hash(self.workshop), before)
        self.assertEqual((self.value(out, "PERSONS"), self.value(out, "RESEARCHES")), ("3", "1"))
        persons = {p["id"]: p for p in self.index("persons")["persons"]}
        birth = persons["victor-hugo-1802"]["facts"][0]
        self.assertEqual((birth["status"], birth["date"]["value"]), ("record", "1802-02-26"))
        death = persons["victor-hugo-1802"]["facts"][1]
        self.assertEqual((death["status"], death["date"]["qualifier"]), ("index", "about"))
        self.assertIn("ligne 4", death["uncertain_reading"])
        self.assertEqual(persons["victor-hugo-1802"]["parents"]["father"], "leopold-hugo-1773")
        self.assertEqual(persons["leopold-hugo-1773"]["spouses"][0]["person"], "sophie-trebuchet-1772")
        sources = self.index("sources")["sources"]
        self.assertEqual(len(sources), 3)
        self.assertTrue(any(s.get("image") == "evidence/ec-1802-112.jpg" for s in sources))
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "families", "hugo", "evidence", "ec-1802-112.jpg")))
        hyp = self.index("hypotheses")["hypotheses"][0]
        self.assertEqual(len(hyp["hypotheses"]), 2)
        searches = self.index("searches")["searches"]
        self.assertEqual([s["result"] for s in searches], ["negative", "positive"])
        self.assertEqual(searches[0]["window"], {"from": 1880, "to": 1895, "places": ["Besançon"]})
        self.assertEqual([v["form"] for v in self.index("variants")["surnames"]["Hugo"]],
                         ["Hugot", "Hügo", "Hugues"])
        manifest = yamlio.load(os.path.join(self.dir, "library", "manifest.yaml"))
        self.assertEqual((manifest["scripts"][0]["id"], manifest["scripts"][0]["status"]), ("ad25", "draft"))
        rid = os.listdir(os.path.join(self.dir, "families", "hugo", "research"))[0]
        meta = self.research(rid).meta()
        self.assertEqual((meta["status"], meta["mode"], meta["question"]),
                         ("closed", "journal", "Les parents de Victor Hugo"))
        sections = [e["payload"]["section"] for e in self.log(rid) if e["type"] == "section.added"]
        self.assertEqual([s["title"] for s in sections], ["L'acte de naissance", "Le père présumé"])
        self.assertNotIn("alert", sections[0]["body_md"])
        self.assertIn("**26 février 1802**", sections[0]["body_md"])
        self.assertEqual(birth["research"], rid)
        with open(os.path.join(self.dir, "work", "import-report.md"), encoding="utf-8") as fh:
            report = fh.read()
        self.assertRegex(report, r"leopold-hugo-1773: fields not imported: (.*, )?surnom")
        self.assertIn("search without a known result", report)
        code, out = self.call("render", rid)
        self.assertEqual(code, 0, out)

    def test_not_a_workshop(self):
        code, out = self.call("import", self.dir)
        self.assertEqual(code, 2, out)

    def test_an_image_named_alone_is_found_in_sources(self):
        # the workshop's convention: scans go to sources/, and a fact often names the file alone
        os.makedirs(os.path.join(self.workshop, "sources"))
        shutil.move(os.path.join(self.workshop, "images", "ec-1802-112.jpg"), os.path.join(self.workshop, "sources"))
        people = os.path.join(self.workshop, "commun", "personnes.yaml")
        with open(people, encoding="utf-8") as fh:
            text = fh.read()
        with open(people, "w", encoding="utf-8") as fh:
            fh.write(text.replace("image: images/ec-1802-112.jpg", "image: ec-1802-112.jpg"))
        code, out = self.call("import", self.workshop)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "families", "hugo", "evidence", "ec-1802-112.jpg")))
        with open(os.path.join(self.dir, "work", "import-report.md"), encoding="utf-8") as fh:
            self.assertNotIn("image not found", fh.read())

    Q = "Who were the parents of Victor Hugo?"

    def test_new_in_a_workshop_asks_then_imports(self):
        self.dir = self.workshop
        code, out = self.call("new", self.Q, "--mode", "session")
        self.assertEqual(code, 3, out)
        self.assertEqual(self.value(out, "QUESTION"), "workshop")
        self.assertEqual(self.value(out, "CHOICES"), "import|ignore")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "families", "hugo")))
        code, out = self.call("new", self.Q, "--mode", "session", "--workshop", "import")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "WORKSHOP"), self.value(out, "IMPORTED_PERSONS"),
                          self.value(out, "FAMILY"), self.value(out, "FAMILY_CREATED")),
                         ("imported", "3", "hugo", "false"))
        self.assertEqual(len(os.listdir(os.path.join(self.dir, "families", "hugo", "research"))), 2)
        code, out = self.call("new", "Where did Victor Hugo die?", "--mode", "session")
        self.assertEqual(code, 0, out)   # imported once: not asked again
        self.assertIsNone(self.value(out, "WORKSHOP"))

    def test_new_in_a_workshop_headless_imports_nothing_and_says_so(self):
        self.dir = self.workshop
        code, out = self.call("new", self.Q, "--mode", "session", env={"PROBANDIA_HEADLESS": "1"})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "WORKSHOP"), "ignored")
        self.assertIn("probandia import .", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "work", "import-report.md")))

    def test_doctor_flags_a_workshop_never_imported(self):
        self.dir = self.workshop
        code, out = self.call("doctor", env={"PWD": self.workshop})   # before the first new: not a project yet
        self.assertEqual(self.value(out, "WORKSHOP"), "pending", out)
        code, out = self.call("new", self.Q, "--mode", "session", "--family", "hugo", "--workshop", "ignore")
        self.assertEqual(code, 0, out)
        code, out = self.call("doctor", env={"PWD": self.workshop})
        self.assertEqual(self.value(out, "WORKSHOP"), "pending", out)
        self.assertEqual(self.value(out, "STATUS"), "WARN")


class Skills(unittest.TestCase):
    def test_under_300_lines(self):
        for name in ("research", "report"):
            with open(os.path.join(ROOT, "skills", name, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertLess(len(text.splitlines()), 300, name)
            self.assertTrue(text.startswith(f"---\nname: {name}\n"), name)
            self.assertIn("research's language", text)


class Acceptance(Base):
    """PRD acceptance criteria 2, 5, 8 and 9 on the sample project."""

    def test_five_passes_resume_fork_verify(self):
        for n in range(2, 6):
            code, out = self.call("resume", RID, "--mode", "session", "--instructions", f"pass {n}")
            self.assertEqual((code, self.value(out, "PASS")), (0, str(n)), out)
            self.call("plan", RID)
            self.call("search", "--log-native", "--query", f"Hugo {n}", "--results", "0")
            code, out = self.call("pass", "end", RID, "--summary", f"lead {n}")
            self.assertEqual(code, 0, out)
        self.call("render", RID)
        before = events.read_lines(self.research().events_path)
        opened = []
        real = builtins.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)
        with mock.patch("builtins.open", spy):
            code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "PASS"), "6")
        self.assertLessEqual(int(self.value(out, "DIGEST_LINES")), 60)
        self.assertLessEqual(len(out.splitlines()), 60, out)   # T226: what the agent is given, not the count it is told
        self.assertIn("lead 5", out)
        self.assertFalse([p for p in opened if os.sep + "report" + os.sep in os.path.normpath(p)])
        after = events.read_lines(self.research().events_path)
        self.assertEqual(after[:len(before)], before)  # the new pass only adds its own events
        self.assertEqual([json.loads(line)["pass"] for line in after[len(before):]], [6])
        self.call("pass", "end", RID, "--summary", "done")
        ended = events.read_lines(self.research().events_path)   # T226: and still once the pass is over
        self.assertEqual(ended[:len(before)], before)
        self.assertEqual({json.loads(line)["pass"] for line in ended[len(before):]}, {6})

        code, out = self.call("fork", RID, "--at", "3", "--name", "branch-b")
        self.assertEqual(code, 0, out)
        child = self.research(self.value(out, "RESEARCH"))
        self.assertEqual(child.meta()["forked_from"], {"research": RID, "pass": 3})
        self.assertIsNone(events.check_chain(child.events_path))

        # one fact without a citation, one negative without a witness
        doc = self.index("persons")
        doc["persons"][0]["facts"].append({"id": "victor-hugo-1802.death", "type": "death", "status": "index",
                                            "source": None, "research": RID})
        self.write_index("persons", doc)
        doc = self.index("searches")
        doc["searches"].append({"id": "s-01J9ZM00000000000000000002", "ts": "2026-09-30T19:00:00Z", "research": RID,
                                "pass": 2, "kind": "archive", "engine": "ad56", "family": None, "query": "Hugo",
                                "variants": ["Hugo"], "window": {"from": 1880, "to": 1895, "places": []},
                                "result": "negative", "failure": None, "witness": None, "source_state": "ok"})
        self.write_index("searches", doc)
        code, out = self.call("verify", RID)
        self.assertEqual(code, 1, out)
        self.assertIn("V-2=FAIL", out)
        self.assertIn("V-3=FAIL", out)


class BalancesRead(Base):
    """T52: the balances read without being asked (decision T7), with a recorded client:
    once a day at new or resume, then every 20 calls counted on one provider; never in a hook."""

    KEYS = {**REUSE, "TAVILY_API_KEY": "k", "SERPAPI_API_KEY": "k"}
    USAGE = {"https://api.tavily.com/usage": "tavily", "https://serpapi.com/account": "serpapi"}

    def setUp(self):
        super().setUp()
        self.env = dict(self.env, **self.KEYS)
        self.sent, self.offline = [], False
        from probandia.cli import search_cmd
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        def transport(method, url, headers, body, timeout):
            self.sent.append(url.split("?")[0])
            if self.offline:
                raise OSError("network unreachable")
            for prefix, provider in self.USAGE.items():
                if url.startswith(prefix):
                    fx = fixture(provider, "account.json" if provider == "serpapi" else "usage.json")
                    return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url
            return 404, {}, b"no route", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        patcher = mock.patch.object(search_cmd, "_client", make_client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ledger(self, hours_ago=0):
        from probandia.ledger import Ledger
        from probandia.providers import catalogue

        when = utc_now() - datetime.timedelta(hours=hours_ago)
        return Ledger(self.dir, catalogue.load(), clock=lambda: when, environ=self.env)

    def read_at(self, hours_ago, tavily_left=None):
        """The balances last read ``hours_ago`` hours ago."""
        ledger = self.ledger(hours_ago)
        for p in ("tavily", "serpapi"):
            before = ledger.reading(p)
            if p == "tavily" and tavily_left is not None:
                ledger.update_reported(p, left=tavily_left)
            ledger.synced(p, before)

    def test_the_first_resume_of_the_day_reads_every_balance(self):
        self.read_at(25)
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "QUOTA_SYNC"), "2")
        self.assertEqual(sorted(self.sent), ["https://api.tavily.com/usage", "https://serpapi.com/account.json"])
        self.assertIsNone(self.value(out, "QUOTA_DRIFT"))

    def test_new_reads_them_too(self):
        code, out = self.call("new", "Who were the parents of Adèle Foucher?", "--family", "hugo",
                              "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "QUOTA_SYNC"), "2")   # never read: due

    def test_two_hours_after_resume_reads_nothing(self):
        self.read_at(2)
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sent, [])
        self.assertNotIn("QUOTA_SYNC=", out)

    def test_the_twentieth_call_makes_one_balance_due(self):
        from probandia import hooks

        self.read_at(2)
        ledger = self.ledger(1)
        for _i in range(19):
            ledger.record("tavily", "search", 1)
        self.assertEqual(self.call("plan", RID)[1].count("QUOTA_SYNC="), 0)   # 19: not due yet
        payload = {"session_id": "s", "cwd": self.dir, "hook_event_name": "PostToolUse",
                   "tool_name": "mcp__tavily__tavily_search", "tool_input": {"query": "Hugo"}, "tool_response": {}}
        hooks.run("log", io.StringIO(json.dumps(payload)), dict(self.env, CLAUDECODE="1"))   # the 20th, by a hook
        self.assertEqual(self.sent, [])   # no hook reads a balance
        code, out = self.call("plan", RID)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.sent, ["https://api.tavily.com/usage"])   # Tavily's balance alone
        self.assertEqual(self.value(out, "QUOTA_SYNC"), "1")
        self.call("plan", RID)
        self.assertEqual(len(self.sent), 1)   # read: no longer due

    def test_a_drop_the_ledger_did_not_count_is_a_drift(self):
        # 14 Oct. 2026, on the bench: Tavily's counter rose by 27 credits during a run that made none
        self.read_at(25, tavily_left=527)
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "QUOTA_DRIFT"), "tavily:100%")
        self.assertIn("tavily drift 100%: provider 27, ledger 0 since", out)   # the digest's line
        self.assertIn("- tavily: the provider counted 27 units since", out)

    def test_a_drop_the_ledger_explains_is_no_drift(self):
        self.read_at(25, tavily_left=527)
        ledger = self.ledger(3)
        for _i in range(25):
            ledger.record("tavily", "search", 1)
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(self.value(out, "QUOTA_SYNC"), "2")
        self.assertNotIn("QUOTA_DRIFT", out)   # 27 against 25: under 10 %
        self.assertNotIn("drift", out)

    def test_a_network_failure_is_a_warning(self):
        self.offline = True
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=OK"), out)
        self.assertIn("- balances not read (serpapi NetworkError, tavily NetworkError): the local count stands",
                      out)
        tried = len(self.sent)
        self.call("plan", RID)
        self.assertEqual(len(self.sent), tried)   # a failed reading waits an hour
