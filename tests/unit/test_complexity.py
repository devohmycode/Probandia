"""optimize 2.12: the run mode and the effort follow how hard the question looks."""
import io
import os
import shutil
import tempfile
import unittest

from probandia import cli, complexity
from probandia.util import yamlio
from tests import ROOT

HYPOTHESES = os.path.join("families", "marchand", "index", "hypotheses.yaml")


class Complexity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d")}

    def close_hypotheses(self):
        path = os.path.join(self.dir, HYPOTHESES)
        doc = yamlio.load(path)
        for h in doc["hypotheses"]:
            h["closed"] = "2026-09-20"
        yamlio.dump(path, doc)

    def new(self, question):
        out = io.StringIO()
        code = cli.main(["new", question], stdout=out, environ=self.env, cwd=self.dir, stdin=io.StringIO())
        return code, out.getvalue()

    def test_a_simple_question_runs_in_the_session(self):
        self.close_hypotheses()
        guess = complexity.estimate(self.dir, "marchand", "When was Louis MARCHAND born?")
        self.assertEqual((guess["level"], guess["mode"], guess["effort"]), ("simple", "session", "medium"))
        code, out = self.new("When was Louis MARCHAND born?")
        self.assertEqual(code, 3, out)
        self.assertIn("DEFAULT=session\n", out)
        self.assertIn("DIFFICULTY=simple\n", out)

    def test_a_hard_question_suggests_a_team(self):
        question = "Was Louis MARCHAND the same person as Louis MARCHANT?"
        guess = complexity.estimate(self.dir, "marchand", question)
        self.assertEqual(guess["mode"], "team")
        self.assertIn("type:identity", guess["reasons"])
        self.assertIn("conflict", guess["reasons"])
        code, out = self.new(question)
        self.assertIn("DEFAULT=team\n", out)
        self.assertIn("OPTION=--mode\n", out)
        self.assertIn("- difficulty=complex", out)

    def test_an_unknown_person_and_open_hypotheses_count(self):
        guess = complexity.estimate(self.dir, "marchand", "When was Paul MARCHAND born?")
        self.assertIn("unknown-person", guess["reasons"])
        self.assertIn("open-hypotheses:1", guess["reasons"])

    def test_new_suggests_sonnet_for_a_simple_or_medium_question_only(self):
        # T80: the session's model is the person's; new suggests, in Claude Code only
        self.close_hypotheses()
        simple = "When was Louis MARCHAND born?"
        cases = ((simple, "claude-code", "simple", True), (simple, "codex", "simple", False),
                 (simple, "cli", "simple", False))
        for question, harness, level, suggested in cases:
            out = io.StringIO()
            cli.main(["new", question, "--harness", harness], stdout=out, environ=self.env, cwd=self.dir,
                     stdin=io.StringIO())
            self.assertIn(f"DIFFICULTY={level}\n", out.getvalue())
            self.assertEqual("SUGGESTED_MODEL=sonnet\n" in out.getvalue(), suggested, (harness, out.getvalue()))
            self.assertEqual(", model sonnet" in out.getvalue(), suggested, harness)

    def test_new_suggests_sonnet_for_a_medium_question_and_nothing_for_a_complex_one(self):
        for question, level, model in (("When was Paul MARCHAND born?", "medium", "sonnet"),
                                       ("Was Louis MARCHAND the same person as Louis MARCHANT?", "complex", None)):
            self.assertEqual(complexity.estimate(self.dir, "marchand", question)["model"], model)
            out = io.StringIO()
            cli.main(["new", question, "--harness", "claude-code"], stdout=out, environ=self.env, cwd=self.dir,
                     stdin=io.StringIO())
            self.assertIn(f"DIFFICULTY={level}\n", out.getvalue())
            self.assertEqual("SUGGESTED_MODEL=sonnet\n" in out.getvalue(), model == "sonnet", out.getvalue())

    def test_the_team_effort_follows(self):
        question = "Was Louis MARCHAND the same person as Louis MARCHANT?"
        out = io.StringIO()
        cli.main(["new", question, "--mode", "team", "--harness", "claude-code"], stdout=out, environ=self.env,
                 cwd=self.dir, stdin=io.StringIO())
        self.assertIn("DEFAULT_TEAM_EFFORT=high\n", out.getvalue())

    def test_plan_says_the_difficulty(self):
        out = io.StringIO()
        cli.main(["plan", "2026-09-01-ancestors-of-louis-marchand"], stdout=out, environ=self.env, cwd=self.dir)
        self.assertIn("DIFFICULTY=", out.getvalue())
        self.assertIn("- difficulty=score=", out.getvalue())

    def test_the_contradictor_comes_before_a_conclusion_only(self):
        for rel in ("agents/orchestrator.md", "skills/research/team.md"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
                self.assertIn("only before promoting a conclusion", text, rel)
                self.assertIn("proofs.md", text, rel)   # GPS5-T5: the review of a proof argument
                self.assertIn("--by contradictor", text, rel)


if __name__ == "__main__":
    unittest.main()
