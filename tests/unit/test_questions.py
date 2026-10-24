"""The questions of a research and how a research is closed (GPS1)."""
import os

from probandia import verify
from probandia.errors import UsageError
from probandia.proof import questions as Q
from probandia.util import yamlio
from probandia.util.schema import validate_document
from tests.unit.test_human import golden
from tests.unit.test_lifecycle import RID, Base
from tests.unit.test_views import Terminal, ViewCase

PERSONS = [{"id": "victor-hugo-1802", "names": {"given": "Victor", "surname": "Hugo"}},
           {"id": "sophie-trebuchet-1772", "names": {"given": "Sophie", "surname": "Trébuchet"}}]
PLACES = [{"id": "besancon", "current_name": "Besançon", "names_as_written": ["Bisanz"]},
          {"id": "nancy", "current_name": "Nancy", "names_as_written": ["Nanzig"]}]
FAMILY = {"surnames": ["Hugo"], "places": ["Besançon"], "period": [1750, 1950]}


class Reading(Base):
    fixture = False

    def test_the_free_text_question_stands_as_q1(self):
        meta = {"question": "Who were the parents of Victor Hugo, born about 1802?"}
        self.assertEqual(Q.of(meta), [{"id": "Q1", "text": meta["question"], "type": "parents",
                                       "status": "open"}])
        self.assertEqual(Q.of({}), [])
        self.assertEqual(Q.get(meta, "q1")["id"], "Q1")
        with self.assertRaises(UsageError):
            Q.get(meta, "Q2")

    def test_questions_written_win_over_the_free_text(self):
        meta = {"question": "x", "questions": [{"id": "Q1", "text": "y", "type": "death", "status": "answered",
                                                "conclusion": ["a.death"]}]}
        self.assertEqual(Q.of(meta)[0]["text"], "y")
        self.assertEqual(Q.unsettled(meta), [])

    def test_an_old_research_stays_valid(self):
        path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "project", "families", "hugo",
                            "research", RID, "research.yaml")
        meta = yamlio.load(path)
        self.assertNotIn("questions", meta)
        validate_document("research", meta)


class FromText(Base):
    """GPS1-T2: three sample questions give the expected questions."""

    fixture = False

    def test_birth(self):
        qs = Q.from_text("When was Victor Hugo born in Besançon, about 1802?", FAMILY, PERSONS, PLACES)
        self.assertEqual(qs, [{"id": "Q1", "text": qs[0]["text"], "type": "birth", "status": "open",
                               "persons": ["victor-hugo-1802"], "window": {"from": 1797, "to": 1807},
                               "places": ["besancon"]}])

    def test_parents_then_a_question_about_the_same_man(self):
        qs = Q.from_text("Who were the parents of Victor Hugo? Where did he die?", FAMILY, PERSONS, PLACES)
        self.assertEqual([(q["id"], q["type"], q.get("persons")) for q in qs],
                         [("Q1", "parents", ["victor-hugo-1802"]), ("Q2", "death", ["victor-hugo-1802"])])
        self.assertNotIn("window", qs[0])   # no year: the family's period is not a window

    def test_identity(self):
        qs = Q.from_text("Is the Victor Hugot of Nancy the same person as the one of Besançon in 1802",
                         FAMILY, PERSONS, PLACES)
        self.assertEqual(qs[0]["type"], "identity")
        self.assertEqual(qs[0]["places"], ["besancon", "nancy"])
        self.assertEqual(qs[0]["window"], {"from": 1800, "to": 1804})

    def test_split(self):
        self.assertEqual(Q.split("A? B; C\nD"), ["A?", "B", "C", "D"])
        self.assertEqual(Q.split("Only one"), ["Only one"])
        self.assertEqual(Q.split("When did he die? The act is in the project (evidence/images)."),
                         ["When did he die? The act is in the project (evidence/images)."])
        self.assertEqual(Q.split("When did he die? Where; why"), ["When did he die?", "Where", "why"])

    def test_every_question_validates(self):
        meta = yamlio.load(os.path.join(os.path.dirname(__file__), "..", "fixtures", "research", "valid",
                                        "full.yaml"))
        meta["questions"] = Q.from_text("Who were the parents of Victor Hugo? Where did he die; and when?",
                                        FAMILY, PERSONS, PLACES)
        validate_document("research", meta)


class Changes(Base):
    fixture = False

    def test_add_edit_settle(self):
        qs = Q.of({"question": "Who were the parents of Victor Hugo?"})
        qs, q = Q.add(qs, "Where did he die?", persons=["victor-hugo-1802"], window="1880-1890")
        self.assertEqual((q["id"], q["type"], q["window"]), ("Q2", "death", {"from": 1880, "to": 1890}))
        qs, q = Q.edit(qs, "Q2", kind="residence", places=["nancy,besancon"])
        self.assertEqual((q["type"], q["places"]), ("residence", ["nancy", "besancon"]))
        qs, q = Q.settle(qs, "Q1", "answered", conclusion=["victor-hugo-1802.birth"])
        self.assertEqual(q["conclusion"], ["victor-hugo-1802.birth"])
        qs, q = Q.settle(qs, "Q1", "unresolved", reason="registers lost")
        self.assertNotIn("conclusion", q)
        self.assertEqual([x["id"] for x in Q.unsettled({"questions": qs})], ["Q2"])

    def test_refusals(self):
        qs = Q.of({"question": "x"})
        for call in (lambda: Q.add(qs, " "), lambda: Q.add(qs, "y", kind="weather"),
                     lambda: Q.add(qs, "y", window="1900-1890"), lambda: Q.add(qs, "y", window="soon"),
                     lambda: Q.settle(qs, "Q1", "answered"), lambda: Q.settle(qs, "Q1", "unresolved"),
                     lambda: Q.edit(qs, "Q9", text="z")):
            with self.assertRaises(UsageError):
                call()

    def test_missing_facts(self):
        q = {"conclusion": ["victor-hugo-1802.birth", "nobody.death", "an-analysis"]}
        self.assertEqual(Q.missing_facts(q, [{"facts": [{"id": "victor-hugo-1802.birth"}]}]),
                         ["nobody.death"])


class OutsideThePass(Base):
    fixture = False

    def test_v1_leaves_question_events_out_of_the_pass_order(self):
        import shutil

        from probandia.research import find_research
        from tests import ROOT

        shutil.rmtree(self.dir)
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        res = find_research(self.dir, "2026-09")
        self.assertEqual(verify.v1(verify.Context(self.dir, res))[0], "PASS")
        Q.write(self.dir, res, {"harness": "cli", "agent": "session", "session": "test"}, 30,
                Q.of(res.meta()), "question.added", {"question": "Q1"})
        status, message = verify.v1(verify.Context(self.dir, res))
        self.assertEqual(status, "PASS", message)
        self.assertEqual(self.log(res.id, res.family)[-1]["type"], "question.added")


class Command(ViewCase):
    """GPS1-T3: question list, add, edit, answer, unresolved, reopen; a reference rendering."""

    RES = "2026-09-01-ancestors-of-louis-marchand"

    def meta(self):
        from probandia.research import find_research

        return find_research(self.dir, self.RES).meta()

    def contract(self, *argv):
        return self.call("question", *argv, "--research", "2026-09", terminal=False)

    def test_each_action(self):
        code, out = self.contract("list")
        self.assertEqual(code, 0, out)
        self.assertIn("Q1=open general Who were the ancestors of Louis MARCHAND?", out)
        self.assertNotIn("questions", self.meta())   # listing writes nothing
        code, out = self.contract("add", "Where was Louis Marchand buried?")
        self.assertEqual(code, 0, out)
        q2 = self.meta()["questions"][1]
        self.assertEqual((q2["id"], q2["type"], q2["persons"]), ("Q2", "death", ["louis-marchand-1898"]))
        self.assertEqual(self.contract("edit", "q2", "--window", "1940-1975")[0], 0)
        self.assertEqual(self.meta()["questions"][1]["window"], {"from": 1940, "to": 1975})
        code, out = self.contract("answer", "Q2", "--conclusion", "nobody.death")
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=unknown-fact", out)
        code, out = self.contract("unresolved", "Q2", "--reason", "the registers of 1940-1975 are closed")
        self.assertIn("QUESTION_STATUS=unresolved", out)
        code, out = self.contract("reopen", "Q2")
        self.assertIn("QUESTION_STATUS=open", out)
        self.assertNotIn("reason", self.meta()["questions"][1])
        from probandia import events
        from probandia.research import find_research

        log = events.read(find_research(self.dir, self.RES).events_path)
        self.assertEqual([e["type"] for e in log[-4:]],
                         ["question.added", "question.updated", "question.updated", "question.updated"])
        self.assertEqual(self.contract("answer", "Q9", "--conclusion", "x.birth")[0], 2)
        self.assertEqual(self.contract("answer")[0], 2)

    def test_readable(self):
        self.contract("add", "Where was Louis Marchand buried?")
        self.contract("unresolved", "Q2", "--reason", "the registers of 1940-1975 are closed")
        code, out = self.call("question", "--research", "2026-09")
        self.assertEqual(code, 0, out)
        golden(self, "question", out)


class Close(ViewCase):
    """GPS1-T4: close refused with an open question or an open pass; strict refuses a failed rule; warn closes
    after asking; resume opens the research again."""

    RES = "2026-09-01-ancestors-of-louis-marchand"

    def run_(self, *argv, env=None):
        return self.call(*argv, terminal=False, env=env)

    def research(self):
        from probandia.research import find_research

        return find_research(self.dir, self.RES)

    def test_refusals_then_closing(self):
        code, out = self.run_("close", "2026-09")
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=open-questions", out)
        self.assertIn("open=Q1 Who were the ancestors of Louis MARCHAND?", out)
        self.run_("question", "unresolved", "Q1", "--reason", "a test", "--research", "2026-09")
        self.assertEqual(self.run_("config", "set", "proof.standard", "strict")[0], 0)
        code, out = self.run_("close", "2026-09")
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=verify-failed", out)
        self.assertIn("V-8=FAIL", out)
        self.assertEqual(self.research().meta()["status"], "open")
        self.run_("config", "set", "proof.standard", "warn")
        code, out = self.run_("close", "2026-09")
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("CLOSED=true", out.replace("True", "true"))
        res = self.research()
        self.assertEqual(res.meta()["status"], "closed")
        from probandia import events

        last = events.read(res.events_path)[-1]
        self.assertEqual((last["type"], last["payload"]["failed"], last["payload"]["questions"]),
                         ("research.closed", ["V-8"], {"Q1": "unresolved"}))
        self.assertEqual(verify.v1(verify.Context(self.dir, res))[0], "PASS")
        self.assertIn("already closed", self.run_("close", "2026-09")[1])
        code, out = self.run_("resume", "2026-09", env={"CLAUDECODE": "1"})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.research().meta()["status"], "open")
        code, out = self.run_("close", "2026-09")
        self.assertIn("REASON=pass-open", out)

    def test_warn_asks_the_person_at_the_keyboard(self):
        self.run_("question", "unresolved", "Q1", "--reason", "a test", "--research", "2026-09")
        self.run_("config", "set", "proof.standard", "warn")
        out = Terminal()
        from probandia import cli

        cli.main(["close", "2026-09", "--width", "100"], stdout=out, environ=self.env, cwd=self.dir,
                 stdin=Terminal("n\n"))
        self.assertIn("Close the research anyway?", out.getvalue())
        self.assertEqual(self.research().meta()["status"], "open")

    def test_a_new_project_checks_the_standard_with_warn(self):
        from probandia.config.tomlfile import template

        self.assertIn('\nproof.standard = "warn"', template(1))


class Report(ViewCase):
    """GPS1-T6: the report lists the questions, their status and their conclusion or reason."""

    def report(self):
        from probandia.research import find_research

        res = find_research(self.dir, "2026-09")
        code, out = self.call("render", "2026-09", terminal=False)
        self.assertEqual(code, 0, out)
        with open(os.path.join(res.folder, "report", "report.md"), encoding="utf-8") as fh:
            return res, fh.read()

    def test_without_questions_nothing_changes(self):
        _res, text = self.report()
        self.assertNotIn("| Q1 |", text)

    def test_journal_then_living(self):
        from probandia import lifecycle

        self.call("question", "add", "Where was Louis Marchand buried?", "--research", "2026-09", terminal=False)
        self.call("question", "unresolved", "Q1", "--reason", "too wide", "--research", "2026-09", terminal=False)
        res, text = self.report()
        self.assertIn("| Q1 | Who were the ancestors of Louis MARCHAND? | non résolue | too wide |", text)
        self.assertIn("| Q2 | Where was Louis Marchand buried? | ouverte |  |", text)
        self.assertLess(text.index("## III "), text.index("## IV Questions"))   # after the passes and the method
        self.assertEqual(verify.run(self.dir, res, None, ["V-6"])[0][1], "PASS")
        lifecycle.update_meta(res, mode="living")
        _res, text = self.report()
        chapter = text[text.index("Question"):]
        self.assertIn("| Q2 | Where was Louis Marchand buried? |", chapter)
        self.assertNotIn("\n\nWho were the ancestors of Louis MARCHAND?\n", text)   # the table stands for it
