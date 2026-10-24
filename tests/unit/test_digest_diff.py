"""optimize 2.13: a second resume in the same session gets only what changed."""
import io
import json
import os
import shutil
import tempfile
import unittest

from probandia import cli, digest
from tests import ROOT

RESEARCH = "2026-09-01-ancestors-of-louis-marchand"


class Differential(unittest.TestCase):
    def test_only_what_changed_under_its_section(self):
        before = ["RESEARCH=r PASS=2", "QUESTION=q", "LEADS:", "  a", "  b", "QUOTAS:", "  jina 9 left", "NEXT=x"]
        after = ["RESEARCH=r PASS=3", "QUESTION=q", "LEADS:", "  a", "  c", "QUOTAS:", "  jina 9 left", "NEXT=y"]
        self.assertEqual(digest.differential(before, after),
                         ["RESEARCH=r PASS=3", "LEADS:", "  c", "  gone: b", "NEXT=y"])

    def test_nothing_new(self):
        lines = ["RESEARCH=r", "LEADS:", "  a", "NEXT=x"]
        self.assertEqual(digest.differential(lines, lines),
                         ["RESEARCH=r", "UNCHANGED: nothing new since your last digest", "NEXT=x"])

    def test_fifteen_lines_at_most(self):
        after = ["RESEARCH=r", "LEADS:"] + [f"  lead {n}" for n in range(30)] + ["NEXT=x"]
        out = digest.differential(["RESEARCH=r", "LEADS:", "NEXT=x"], after)
        self.assertEqual(len(out), 15)
        self.assertTrue(out[-2].startswith("MORE: "))
        self.assertEqual(out[-1], "NEXT=x")


class SecondResume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"), "PROBANDIA_SESSION": "s1"}

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--harness", "claude-code"], stdout=out, environ=dict(self.env, **(env or {})),
                        cwd=self.dir, stdin=io.StringIO())
        return code, out.getvalue()

    def lines(self, out):
        return [line for line in out.splitlines() if line.startswith("- ")]

    def test_the_second_resume_holds_in_fifteen_lines(self):
        code, first = self.call("resume", RESEARCH, "--mode", "session")
        self.call("plan", RESEARCH)
        self.assertEqual(code, 0, first)
        self.assertIn("DIGEST=full\n", first)
        self.call("pass", "end", RESEARCH, "--summary", "a new lead in Les Ormes; the 1872 census to read")
        code, second = self.call("resume", RESEARCH, "--mode", "session")
        self.assertEqual(code, 0, second)
        self.assertIn("DIGEST=changes\n", second)
        self.assertLessEqual(len(self.lines(second)), 15, second)
        self.assertIn("- RESEARCH=" + RESEARCH, second)
        self.assertIn("a new lead in Les Ormes", second)
        self.assertNotIn("QUESTION=", second)               # unchanged: not repeated
        with open(os.path.join(self.dir, second.split("DETAILS=")[1].strip()), encoding="utf-8") as fh:
            self.assertIn("QUESTION=", fh.read())            # DETAILS keeps the whole digest

    def test_another_session_gets_the_whole_digest(self):
        self.call("resume", RESEARCH, "--mode", "session")
        self.call("plan", RESEARCH)
        self.call("pass", "end", RESEARCH, "--summary", "done")
        code, out = self.call("resume", RESEARCH, "--mode", "session", env={"PROBANDIA_SESSION": "s2"})
        self.assertEqual(code, 0, out)
        self.assertIn("DIGEST=full\n", out)
        self.assertIn("QUESTION=", out)

    def test_the_digest_command_stays_whole(self):
        self.call("digest", RESEARCH)
        code, out = self.call("digest", RESEARCH)
        self.assertIn("DIGEST=full\n", out)


class AfterACompaction(unittest.TestCase):
    """T71: SessionStart with ``"source": "compact"`` gives back the digest of the pass this session holds, as
    ``hookSpecificOutput.additionalContext`` (https://code.claude.com/docs/en/hooks, SessionStart, 14 Oct. 2026)."""

    setUp = SecondResume.setUp
    call = SecondResume.call

    def session_start(self, source, env=None):
        from probandia import hooks

        payload = {"session_id": "abc123", "cwd": self.dir, "hook_event_name": "SessionStart", "source": source}
        out = hooks.run("session", io.StringIO(json.dumps(payload)), dict(self.env, **(env or {})), "claude-code")
        return json.loads(out) if out.strip() else None

    def test_the_digest_after_a_compaction_only(self):
        self.assertIsNone(self.session_start("compact"))   # no pass held
        code, out = self.call("resume", RESEARCH, "--mode", "session")
        self.call("plan", RESEARCH)
        self.assertEqual(code, 0, out)
        found = self.session_start("compact")
        self.assertEqual(found["hookSpecificOutput"]["hookEventName"], "SessionStart")
        context = found["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(context.startswith("Probandia state digest:\nRESEARCH=" + RESEARCH), context)
        self.assertIn("\nQUESTION=", context)
        self.assertLessEqual(len(context.splitlines()), 61)   # the digest holds in 60 lines
        for source in ("startup", "resume", "clear"):
            self.assertIsNone(self.session_start(source), source)
        self.assertIsNone(self.session_start("compact", env={"PROBANDIA_SESSION": "s2"}))   # not its pass
        self.assertIsNone(self.session_start("compact", env={"PROBANDIA_WORKER": "1"}))
        code, out = self.call("pass", "end", RESEARCH, "--summary", "done")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.session_start("compact"))   # no pass open


if __name__ == "__main__":
    unittest.main()
