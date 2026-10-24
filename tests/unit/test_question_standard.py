"""T249: a question says what will count as its answer; a negative that serves as proof says why the record
was expected."""
import io
import json
import os
import shutil
import tempfile
import unittest

from probandia import cli, digest, events, i18n
from probandia.research import Research
from probandia.util import yamlio
from tests import ROOT
from tests.unit.test_data_layer import Project, negative

RID2 = "2026-09-04-birth-of-henri-marchand"
STANDARD = "his birth act, naming both parents"


class Standard(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.addCleanup(i18n.activate, "en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "gps")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project-gps"), self.dir)
        self.research = Research(self.dir, "marchand", RID2)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"), "PROBANDIA_SESSION": "test"}

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env), cwd=self.dir, stdin=io.StringIO())
        return code, out.getvalue()

    def questions(self):
        return {q["id"]: q for q in self.research.meta()["questions"]}

    def test_add_and_edit_keep_the_standard(self):
        code, out = self.call("question", "add", "Où est mort Henri MARCHAND ?", "--research", RID2,
                              "--standard", "his death act,  or his burial")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.questions()["Q3"]["standard"], "his death act, or his burial")
        self.assertEqual(events.read(self.research.events_path)[-1]["payload"]["standard"],
                         "his death act, or his burial")
        code, out = self.call("question", "edit", "Q3", "--research", RID2, "--standard", "his death act")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.questions()["Q3"]["standard"], "his death act")
        code, out = self.call("question", "edit", "Q3", "--research", RID2, "--window", "1925-1935")
        self.assertEqual(self.questions()["Q3"]["standard"], "his death act")   # only what is given changes
        code, out = self.call("--json", "question", "list", "--research", RID2)
        rows = {r["id"]: r for r in json.loads(out)["data"]["questions"]}
        self.assertEqual(rows["Q3"]["standard"], "his death act")

    def test_plan_and_digest_show_the_standard_of_an_open_question(self):
        self.call("question", "add", "Où est mort Henri MARCHAND ?", "--research", RID2, "--standard", STANDARD)
        self.call("question", "edit", "Q1", "--research", RID2, "--standard", "an answered question's")
        lines = digest.build(self.dir, self.research)
        at = lines.index("STANDARDS:")
        self.assertEqual(lines[at + 1], f"  Q3: {STANDARD}")
        self.assertNotIn("an answered question's", "\n".join(lines))   # the answered ones are settled
        code, out = self.call("plan", RID2)
        self.assertEqual(code, 0, out)
        self.assertIn(f"- standard=Q3: {STANDARD}\n", out)
        self.assertNotIn("standard=Q1", out)

    def test_the_report_shows_it_in_the_table_of_the_questions(self):
        code, out = self.call("render", RID2, "--formats", "md")
        with open(os.path.join(self.research.folder, "report", "report.md"), encoding="utf-8") as fh:
            self.assertNotIn("Ce qui vaudra réponse", fh.read())   # no column when no question says it
        self.call("question", "edit", "Q2", "--research", RID2, "--standard", "l'acte de naissance")
        code, out = self.call("render", RID2, "--formats", "md")
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.research.folder, "report", "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("| N° | Question | Ce qui vaudra réponse | Statut | Conclusion ou raison | Confiance |", md)
        self.assertIn("| Q2 | Qui sont les parents d'Henri MARCHAND ? | l'acte de naissance | répondue |", md)
        self.assertIn("| Q1 | Quand et où est né Henri MARCHAND ? |  | répondue |", md)


class NegativeAsProof(Project):
    def test_p3_refuses_a_proof_that_does_not_say_why_the_record_was_expected(self):
        (code, out), _doc = self.propose_and_apply(searches=[negative(proves="proof")])
        self.assertEqual(code, 1, out)
        self.assertIn("serves as proof, but does not say why the record should exist there (expected)", out)
        (code, out), _doc = self.propose_and_apply(searches=[negative(proves="proof", expected="  ")])
        self.assertEqual(code, 1, out)
        found = negative(proves="proof", expected="the family lived in Besançon from 1765 to 1780, and the "
                                                  "baptisms of Saint-Jean are whole for those years")
        (code, out), _doc = self.propose_and_apply(searches=[found])
        self.assertEqual(code, 0, out)
        kept = {s["id"]: s for s in yamlio.load(os.path.join(self.family, "index", "searches.yaml"))["searches"]}
        self.assertTrue(kept[found["id"]]["expected"].startswith("the family lived in Besançon"))

    def test_a_negative_of_a_result_needs_none(self):
        (code, out), _doc = self.propose_and_apply(searches=[negative(proves="result")])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
