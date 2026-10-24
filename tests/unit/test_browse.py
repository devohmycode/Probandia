"""Reading the work of the agents from a terminal (CLI8): researches, families,
persons, the indexes and the proposals, on a copy of the sample project."""
import json
import os
import shutil
from unittest import mock

from probandia.util import yamlio
from tests.unit.test_human import golden
from tests.unit.test_views import ViewCase

RID = "2026-09-01-ancestors-of-louis-marchand"


class Browse(ViewCase):
    def family_dir(self, family="marchand"):
        return os.path.join(self.dir, "families", family)

    def clone_research(self, rid, family="marchand", **meta):
        """A copy of the sample research under another id (and family), with ``meta`` changed."""
        if not os.path.isdir(self.family_dir(family)):
            os.makedirs(self.family_dir(family))
            doc = yamlio.load(os.path.join(self.family_dir(), "family.yaml"))
            yamlio.dump(os.path.join(self.family_dir(family), "family.yaml"), dict(doc, id=family))
        target = os.path.join(self.family_dir(family), "research", rid)
        shutil.copytree(os.path.join(self.family_dir(), "research", RID), target)
        path = os.path.join(target, "research.yaml")
        yamlio.dump(path, dict(yamlio.load(path), id=rid, family=family, **meta))
        return target

    def json(self, *argv):
        code, out = self.call(*argv, "--json", terminal=False)
        self.assertEqual(code, 0, out)
        return json.loads(out)


class ResearchList(Browse):
    """research list (cli.md 5.6.2)."""

    def ids(self, *options):
        return [x["research"] for x in self.json("research", "list", *options)["data"]["researches"]]

    def test_readable(self):
        code, out = self.call("research", "list")
        self.assertEqual(code, 0, out)
        golden(self, "research-list", out)

    def test_list_is_the_default_action(self):
        self.assertEqual(self.call("research")[1], self.call("research", "list")[1])

    def test_family(self):
        self.clone_research("2026-09-03-roussel", family="roussel")
        self.assertEqual(self.ids("--family", "roussel"), ["2026-09-03-roussel"])
        self.assertEqual(self.ids("--family", "marchand"), [RID])

    def test_status(self):
        self.clone_research("2026-09-03-paused", status="paused")
        self.assertEqual(self.ids("--status", "paused"), ["2026-09-03-paused"])
        self.assertEqual(self.ids("--status", "closed"), [])

    def test_since(self):
        self.assertEqual(self.ids("--since", "2026-09-02"), [RID])
        self.assertEqual(self.ids("--since", "2026-09-03"), [])
        code, out = self.call("research", "list", "--since", "yesterday", terminal=False)
        self.assertEqual(code, 2, out)


class ResearchShow(Browse):
    """research show (cli.md 5.6.3)."""

    def test_readable(self):
        agent = {"CLAUDECODE": "1"}
        self.assertEqual(self.call("resume", RID, terminal=False, env=agent)[0], 0)
        self.assertEqual(self.call("verify", RID, terminal=False, env=agent)[0], 1)   # V-8: no trees
        os.makedirs(os.path.join(self.dir, ".probandia"), exist_ok=True)
        with open(os.path.join(self.dir, ".probandia", "tokens.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"research": RID, "pass": 2, "role": "researcher", "input": 1200, "output": 300,
                                 "cache_read": 0, "cache_write": 0}) + "\n")
        code, out = self.call("research", "show", RID)
        self.assertEqual(code, 0, out)
        golden(self, "research-show", out)
        for text in ("Who were the ancestors of Louis MARCHAND?", "grandparents found; the Perrin line is open",
                     "pierre-marchand-1841.birth", "s-01JA00000000000000000SRC02", "h-father-of-louise-perrin",
                     "3 E 41", "V-8", "researcher"):
            self.assertIn(text, out)

    def test_contract(self):
        code, out = self.call("research", "show", terminal=False)
        self.assertIn("\nVERIFY=never\n", out)
        self.assertIn("- pass=2 900s units=— native=0 grandparents found; the Perrin line is open\n", out)


class ResearchLog(Browse):
    """research log (cli.md 5.6.4, § 7.3)."""

    def test_readable(self):
        code, out = self.call("research", "log", "--since", "2026-09-02")
        self.assertEqual(code, 0, out)
        golden(self, "research-log", out)

    def test_jsonl(self):
        code, out = self.call("research", "log", "--jsonl", terminal=False)
        lines = out.splitlines()
        self.assertEqual(len(lines), 28)
        self.assertEqual(json.loads(lines[-1])["type"], "pass.ended")

    def test_follow_sees_the_events_written_meanwhile(self):
        from probandia import events
        from probandia.cli import browse_cmd

        path = os.path.join(self.family_dir(), "research", RID, "events.jsonl")
        actor = {"harness": "cli", "agent": "session"}
        ticks = []

        def sleep(seconds):
            ticks.append(seconds)
            if len(ticks) == 1:
                events.append(path, [events.make("instruction.added", {"text": "first"}, actor, 2)])
            elif len(ticks) == 2:   # a line half written waits for its end
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write('{"half":')
            elif len(ticks) == 3:
                with open(path, "rb+") as fh:   # the writer finishes: drop the half line, write two events
                    fh.truncate(os.path.getsize(path) - len('{"half":'))
                events.append(path, [events.make("instruction.added", {"text": "second"}, actor, 2),
                                     events.make("instruction.added", {"text": "third"}, actor, 2)])
            else:
                raise KeyboardInterrupt

        with mock.patch.object(browse_cmd, "_sleep", sleep):
            code, out = self.call("research", "log", "--follow", terminal=False)
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertEqual(len(lines), 31)
        self.assertEqual([x.split()[-1] for x in lines[-3:]], ["first", "second", "third"])
        self.assertEqual(ticks, [1, 1, 1, 1])


class ResearchStatus(Browse):
    """research pause, close and reopen (cli.md 5.6.6)."""

    def status(self):
        return yamlio.load(os.path.join(self.family_dir(), "research", RID, "research.yaml"))["status"]

    def test_pause_close_reopen(self):
        code, out = self.call("research", "pause", RID, terminal=False)
        self.assertEqual(code, 0, out)
        self.assertIn("RESEARCH_STATUS=paused\nWAS=open\n", out)
        self.assertEqual(self.status(), "paused")
        code, out = self.call("research", "reopen", RID, terminal=False)
        self.assertEqual((code, self.status()), (0, "open"), out)
        self.assertEqual(self.call("question", "unresolved", "Q1", "--research", RID, "--reason", "no record",
                                   terminal=False)[0], 0)
        code, out = self.call("research", "close", RID, terminal=False)
        self.assertEqual(code, 0, out)
        self.assertIn("CLOSED=true", out)
        self.assertEqual(self.status(), "closed")
        code, out = self.call("research", "pause", RID, terminal=False)
        self.assertEqual((code, self.status()), (2, "closed"), out)
        code, out = self.call("research", "reopen", RID, terminal=False)
        self.assertEqual((code, self.status()), (0, "open"), out)

    def test_close_asks_first(self):
        import io

        from probandia import cli
        from tests.unit.test_views import Terminal

        class Keyboard(io.StringIO):
            def isatty(self):
                return True

        out = Terminal()
        code = cli.main(["research", "close", RID], stdout=out, environ=self.env, cwd=self.dir,
                        stdin=Keyboard("n\n"))
        self.assertEqual(code, 4, out.getvalue())
        self.assertIn("Close the research", out.getvalue())
        self.assertEqual(self.status(), "open")

    def test_refused_while_an_agent_holds_the_lock(self):
        agent = {"CLAUDECODE": "1", "PROBANDIA_SESSION": "agent-session"}
        self.assertEqual(self.call("lock", "take", f"research:{RID}", terminal=False, env=agent)[0], 0)
        for action in ("pause", "reopen"):
            code, out = self.call("research", action, RID, terminal=False)
            self.assertEqual(code, 5, out)
            self.assertIn("REASON=lock-held", out)
        self.assertEqual(self.status(), "open")


class Family(Browse):
    """family list and family show (cli.md 5.6.7)."""

    def test_list(self):
        self.clone_research("2026-09-03-roussel", family="roussel")
        code, out = self.call("family", "list")
        self.assertEqual(code, 0, out)
        golden(self, "family-list", out)

    def test_show(self):
        code, out = self.call("family", "show", "marchand")
        self.assertEqual(code, 0, out)
        golden(self, "family-show", out)

    def test_unknown_family(self):
        code, out = self.call("family", "show", "marchant", terminal=False)
        self.assertEqual(code, 2, out)
        self.assertIn("marchand", out)


class Lock(Browse):
    """lock list and lock release <scope> --expired (cli.md 5.6.8)."""

    SCOPE = f"research:{RID}"
    AGENT = {"CLAUDECODE": "1", "PROBANDIA_SESSION": "agent-session"}

    def expire(self):
        path = os.path.join(self.dir, ".probandia", "locks", f"research-{RID}.json")
        with open(path, encoding="utf-8") as fh:
            info = json.load(fh)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dict(info, expires="2026-01-01T00:00:00Z"), fh)

    def test_list(self):
        self.assertEqual(self.call("lock", "take", self.SCOPE, terminal=False, env=self.AGENT)[0], 0)
        self.assertEqual(self.call("lock", "take", "family:marchand", terminal=False, env=self.AGENT)[0], 0)
        self.expire()
        data = self.json("lock", "list")
        self.assertEqual(data["values"], {"LOCKS": 2, "EXPIRED": 1})
        self.assertEqual([(x["scope"], x["state"]) for x in data["data"]["locks"]],
                         [("family-marchand", "held"), (f"research-{RID}", "expired")])

    def test_never_a_live_lock_always_an_expired_one(self):
        self.assertEqual(self.call("lock", "take", self.SCOPE, terminal=False, env=self.AGENT)[0], 0)
        code, out = self.call("lock", "release", self.SCOPE, "--expired", terminal=False)
        self.assertEqual(code, 5, out)
        self.assertIn("REASON=lock-held", out)
        self.expire()
        code, out = self.call("lock", "release", self.SCOPE, "--expired", terminal=False)
        self.assertEqual(code, 0, out)
        self.assertIn("STATE=released", out)
        self.assertEqual(self.json("lock", "list")["values"]["LOCKS"], 0)

    def test_a_scope_is_needed(self):
        self.assertEqual(self.call("lock", "release", terminal=False)[0], 2)


class Find(Browse):
    """find (cli.md 5.7.1)."""

    def found(self, *argv):
        return [(x["person"], x["match"]) for x in self.json("find", *argv)["data"]["persons"]]

    def test_marchant_finds_the_marchand(self):
        code, out = self.call("find", "Marchant")
        self.assertEqual(code, 0, out)
        golden(self, "find", out)
        found = self.found("Marchant")
        self.assertEqual(len(found), 5)
        self.assertTrue(all(p.split("-")[1] == "marchand" and how == "variant" for p, how in found), found)

    def test_ranking(self):
        found = self.found("Louis Marchand")
        self.assertEqual(found[0], ("louis-marchand-1898", "exact"))   # the given name too comes first
        self.assertEqual(self.found("Marchan")[0][1], "phonetic")
        self.assertEqual(self.found("Louise"), [("louise-perrin-1818", "given name")])

    def test_family_filter_and_nothing_found(self):
        self.assertEqual(self.found("Marchand", "--family", "roussel"), [])
        code, out = self.call("find", "Zzyzx")
        self.assertIn("nobody of that name", out)


class Person(Browse):
    """person (cli.md 5.7.2)."""

    def test_readable(self):
        code, out = self.call("person", "henri-marchand-1870")
        self.assertEqual(code, 0, out)
        golden(self, "person", out)
        facts = self.json("person", "henri-marchand-1870")["data"]["facts"]   # the facts with their sources
        self.assertTrue(facts[0]["citation"].startswith("Archives départementales de Valombre, État civil"))

    def test_hypotheses_negatives_and_a_prefix(self):
        data = self.json("person", "louise-perrin")
        self.assertEqual(data["values"]["PERSON"], "louise-perrin-1818")
        self.assertEqual([x["hypothesis"] for x in data["data"]["hypotheses"]], ["h-father-of-louise-perrin"])
        self.assertEqual([x["search"] for x in data["data"]["negatives"]], ["s-01JA00000000000000000SRC02"])
        self.assertEqual([x["relation"] for x in data["data"]["relatives"]], ["spouse", "child"])

    def test_presumed_living_is_flagged(self):
        path = os.path.join(self.family_dir(), "index", "persons.yaml")
        doc = yamlio.load(path)
        doc["persons"][0]["living"] = True
        yamlio.dump(path, doc)
        code, out = self.call("person", "louis-marchand-1898", terminal=False)
        self.assertIn("\nLIVING=true\n", out)
        self.assertIn("presumed living: louis-marchand-1898", out)
        self.assertNotIn("presumed living", self.call("person", "henri-marchand-1870", terminal=False)[1])

    def test_unknown_person(self):
        code, out = self.call("person", "henri-marchant-1870", terminal=False)
        self.assertEqual(code, 2, out)
        self.assertIn("did you mean henri-marchand-1870?", out)
        self.assertEqual(self.call("person", "marie", terminal=False)[0], 2)   # several persons


class IndexLists(Browse):
    """searches, sources, negatives, hypotheses and gaps (cli.md 5.7.4, 5.7.5)."""

    def ids(self, name, *options):
        key = {"searches": "search", "sources": "source", "negatives": "search", "hypotheses": "hypothesis",
               "gaps": "reference"}[name]
        return [x[key] for x in self.json(name, *options)["data"][name]]

    def test_readable(self):
        for name in ("searches", "sources", "negatives", "hypotheses", "gaps"):
            code, out = self.call(name)
            self.assertEqual(code, 0, out)
            golden(self, name, out)

    def test_searches_by_engine_date_and_person(self):
        both = ["s-01JA00000000000000000SRC01", "s-01JA00000000000000000SRC02"]
        self.assertEqual(self.ids("searches", "--engine", "ad-valombre"), both)
        self.assertEqual(self.ids("searches", "--engine", "gallica"), [])
        self.assertEqual(self.ids("searches", "--since", "2026-09-02"), both[1:])
        self.assertEqual(self.ids("searches", "--person", "louise-perrin"), both[1:])
        self.assertEqual(self.ids("searches", "--person", "louis-marchand"), both[:1])

    def test_by_person(self):
        self.assertEqual(self.ids("sources", "--person", "henri-marchand"),
                         ["src-01JA0000000000000000000002", "src-01JA0000000000000000000004",
                          "src-01JA0000000000000000000005"])
        self.assertEqual(self.ids("negatives", "--person", "louise-perrin"), ["s-01JA00000000000000000SRC02"])
        self.assertEqual(self.ids("negatives", "--person", "henri-marchand"), [])
        self.assertEqual(self.ids("hypotheses", "--person", "louise-perrin"), ["h-father-of-louise-perrin"])
        self.assertEqual(self.ids("hypotheses", "--person", "henri-marchand"), [])
        self.assertEqual(self.ids("gaps", "--person", "henri-marchand"), ["3 E 41"])
        self.assertEqual(self.ids("gaps", "--person", "francois-marchand"), [])

    def test_by_family(self):
        self.clone_research("2026-09-03-roussel", family="roussel")
        self.assertEqual(self.ids("sources", "--family", "roussel"), [])
        self.assertEqual(len(self.ids("sources", "--family", "marchand")), 6)


PROPOSAL = "01JB0000000000000000000P01"


class Proposals(Browse):
    """proposals, proposals show, apply and drop (cli.md 5.8.1 to 5.8.3)."""

    SESSION = {"CLAUDECODE": "1", "PROBANDIA_SESSION": "harness-session"}

    def propose(self, pid=PROPOSAL, pass_no=3, ref=RID, **changes):
        doc = {"schema": 1, "id": pid, "research": RID, "pass": pass_no,
               "author": {"harness": "claude-code", "agent": "researcher"},
               "facts": [{"id": "louise-perrin-1818.death", "type": "death",
                          "date": {"value": "1880", "qualifier": "exact"}, "status": "index",
                          "source": "src-01JA0000000000000000000005"}],
               "sections": [{"kind": "chapter", "title": "La mort de Louise", "body_md": "Louise meurt en 1880.",
                             "facts": ["louise-perrin-1818.death"]}]}
        doc.update(changes)
        path = os.path.join(self.tmp.name, f"{pid}.yaml")
        yamlio.dump(path, doc)
        code, out = self.call("propose", *([ref] if ref else []), path, "--agent", "researcher", terminal=False,
                              env=self.SESSION)
        self.assertEqual(code, 0, out)

    def session(self, *argv):
        code, out = self.call(*argv, terminal=False, env=self.SESSION)
        self.assertEqual(code, 0, out)
        return out

    def test_propose_read_apply_then_verify(self):
        self.assertIn(f"RESEARCH={RID}", self.session("resume", RID))   # B6: resume says which research
        self.session("plan", RID)
        self.propose(ref=None)   # B6: the research of the pass, unnamed
        code, out = self.call("proposals")
        self.assertEqual(code, 0, out)
        golden(self, "proposals", out)
        code, out = self.call("proposals", "show", PROPOSAL)
        self.assertEqual(code, 0, out)
        golden(self, "proposal-show", out)
        out = self.session("proposals", "apply", PROPOSAL)
        self.assertIn("EVENTS=", out)
        self.assertEqual(self.json("proposals")["values"]["PROPOSALS"], 0)
        self.assertNotIn("RESEARCH=", self.session("render"))          # ... the others do not repeat it
        self.session("pass", "end", "--summary", "the death of Louise")
        out = self.session("verify")
        self.assertIn("FAILED=0", out)

    def test_show_the_rules_that_fail(self):
        self.propose(facts=[{"id": "louise-perrin-1818.death", "type": "death",
                             "date": {"value": "1880", "qualifier": "exact"}, "status": "record",
                             "source": None}], sections=[])
        data = self.json("proposals", "show", PROPOSAL)
        self.assertEqual(data["values"]["VERDICT"], "would-reject")
        self.assertEqual([x["rule"] for x in data["data"]["rules"]], ["P-1"])

    def test_drop_needs_a_reason_and_asks(self):
        self.propose(pass_no=2)
        self.assertEqual(self.call("proposals", "drop", PROPOSAL, terminal=False)[0], 2)
        out = self.session("proposals", "drop", PROPOSAL, "--reason", "a duplicate")
        self.assertIn("STATE=dropped", out)
        self.assertEqual(self.json("proposals", "--research", RID)["values"]["PROPOSALS"], 0)

    def test_apply_asks_first(self):
        import io

        from probandia import cli
        from tests.unit.test_views import Terminal

        class Keyboard(io.StringIO):
            def isatty(self):
                return True

        self.propose(pass_no=2)
        out = Terminal()
        code = cli.main(["proposals", "apply", PROPOSAL], stdout=out, environ=self.env, cwd=self.dir,
                        stdin=Keyboard("n\n"))
        self.assertEqual(code, 4, out.getvalue())
        self.assertEqual(self.json("proposals")["values"]["PROPOSALS"], 1)
