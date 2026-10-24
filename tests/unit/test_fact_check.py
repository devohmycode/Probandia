"""T248: a person records that they looked at the record a fact rests on; the report and the digest say so."""
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, digest, events, i18n
from probandia.research import Research
from tests import ROOT

RID2 = "2026-09-04-birth-of-henri-marchand"
FACT = "henri-marchand-1870.birth"
CHECK = ["fact", "check", FACT, "--by", "Marie Durand", "--looked", "the image of act 31, view 12",
         "--research", RID2]


class TTY(io.StringIO):
    def isatty(self):
        return True


class FactCheck(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.addCleanup(i18n.activate, "en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "gps")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project-gps"), self.dir)
        self.research = Research(self.dir, "marchand", RID2)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "NO_COLOR": "1",
                    "PROBANDIA_PAGER": "none", "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"),
                    "PROBANDIA_SESSION": "test"}

    def call(self, *argv, terminal=True, env=None):
        out = TTY() if terminal else io.StringIO()
        stdin = TTY("") if terminal else io.StringIO("")
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir, stdin=stdin)
        return code, out.getvalue()

    def log(self):
        return events.read(self.research.events_path)

    def digest(self):
        return digest.build(self.dir, self.research)

    def test_refused_when_no_one_is_at_the_keyboard(self):
        before = self.log()
        code, out = self.call(*CHECK, terminal=False)   # an agent: the contract, no terminal
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=needs-person", out)
        code, out = self.call(*CHECK, env={"PROBANDIA_HEADLESS": "1"})   # a terminal, but a headless run
        self.assertEqual(code, 2, out)
        self.assertIn("run it yourself", out)
        self.assertEqual(self.log(), before)

    def test_event_append_cannot_write_it(self):
        payload = os.path.join(self.tmp.name, "payload.json")
        with open(payload, "w", encoding="utf-8") as fh:
            fh.write('{"fact": "%s", "by": "an agent", "looked": "nothing"}' % FACT)
        code, out = self.call("event", "append", RID2, "--type", "fact.checked", "--payload-file", payload,
                              terminal=False)
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=needs-person", out)
        self.assertNotIn("fact.checked", [e["type"] for e in self.log()])

    def test_a_person_records_the_check_under_the_research_lock(self):
        self.assertIn(f"UNCHECKED=1 ({FACT})", self.digest())
        from probandia import indexes

        with mock.patch.object(indexes, "locked", wraps=indexes.locked) as lock:
            code, out = self.call(*CHECK)
        self.assertEqual(code, 0, out)
        self.assertEqual(lock.call_args[0][1], f"research:{RID2}")
        last = self.log()[-1]
        self.assertEqual(last["type"], "fact.checked")
        self.assertEqual(last["payload"], {"fact": FACT, "by": "Marie Durand",
                                           "looked": "the image of act 31, view 12"})
        self.assertEqual(last["refs"], [FACT])
        self.assertIsNone(events.check_chain(self.research.events_path))
        self.assertFalse([x for x in self.digest() if x.startswith("UNCHECKED=")])   # the digest counts no more
        from probandia import verify

        self.assertEqual(verify.run(self.dir, self.research, rules=["V-1"])[0][1], "PASS")   # outside a pass

    def test_the_fact_and_the_check_are_given(self):
        for argv, said in ((["fact", "check", FACT, "--looked", "x", "--research", RID2], "(--by)"),
                           (["fact", "check", FACT, "--by", "M", "--research", RID2], "(--looked)"),
                           (["fact", "check", "--by", "M", "--looked", "x", "--research", RID2], "name the fact")):
            code, out = self.call(*argv)
            self.assertEqual(code, 2, out)
            self.assertIn(said, out)
        code, out = self.call("fact", "check", "henri-marchand-1870.emigration", "--by", "M", "--looked", "x",
                              "--research", RID2)
        self.assertEqual(code, 2, out)
        self.assertIn("is not a fact of the family", out)
        self.assertNotIn("fact.checked", [e["type"] for e in self.log()])

    def test_the_report_says_who_checked(self):
        code, out = self.call(*CHECK)
        self.assertEqual(code, 0, out)
        code, out = self.call("render", RID2, "--formats", "md", terminal=False)
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.research.folder, "report", "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        from probandia.report.content import format_day

        day = format_day(self.log()[-1]["ts"][:10], "fr")
        self.assertIn(f"Vérifié par Marie Durand le {day}, sur the image of act 31, view 12.", md)

    def test_tab_completes_the_facts(self):
        out = io.StringIO()
        cli.main(["__complete", "fact", "check", "henri-marchand-1870.b"], stdout=out, environ=self.env, cwd=self.dir)
        self.assertEqual(out.getvalue().splitlines(), ["henri-marchand-1870.birth", "henri-marchand-1870.birth.2"])

    def test_a_check_in_another_research_of_the_family_counts(self):
        code, out = self.call(*CHECK[:-1], "2026-09-01-ancestors-of-louis-marchand")
        self.assertEqual(code, 0, out)
        self.assertFalse([x for x in self.digest() if x.startswith("UNCHECKED=")])


if __name__ == "__main__":
    unittest.main()
