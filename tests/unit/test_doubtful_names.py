"""T258: a name the reader marked doubtful ([?]) reaches the reply of pass end, with its reserve."""
import io
import os
import re
import shutil
import tempfile
import unittest

from probandia import cli
from probandia import transcription as T
from probandia.util import yamlio
from tests import ROOT

RESEARCH = "2026-09-01-ancestors-of-louis-marchand"
SOURCE = "src-01JA0000000000000000000001"   # the birth of Louis, son of Henri and Jeanne
LINES = ["Le quinze mars est né Louis", "fils de Henri Marchand et de Jeanne roussal[?] son épouse"]


def person(pid, given, surname, **more):
    return dict({"id": pid, "names": {"given": given, "surname": surname}}, **more)


class DoubtfulNames(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name
        os.makedirs(os.path.dirname(T.path_for(self.folder, SOURCE)))
        with open(T.path_for(self.folder, SOURCE), "w", encoding="utf-8") as fh:
            fh.write(T.template(SOURCE, "v14.jpg", lines=LINES))
        fact = {"id": "louis.birth", "type": "birth", "source": SOURCE, "research": "r", "pass": 2}
        self.persons = [person("louis", "Louis", "MARCHAND", parents={"father": "henri", "mother": "jeanne"},
                               facts=[fact]),
                        person("henri", "Henri", "MARCHAND"), person("jeanne", "Jeanne", "ROUSSEL")]

    def test_the_mother_written_from_a_doubtful_reading(self):
        self.assertEqual(T.doubtful_names(self.persons, self.folder, "r", 2),
                         [f"Jeanne ROUSSEL: 'roussal'[?] ({SOURCE})"])

    def test_only_this_pass(self):
        self.assertEqual(T.doubtful_names(self.persons, self.folder, "r", 1), [])

    def second(self, *lines):
        with open(T.second_path(self.folder, SOURCE), "w", encoding="utf-8") as fh:
            fh.write(T.template(SOURCE, "v14.jpg", lines=list(lines)))

    def test_a_second_reading_that_settles_the_doubt(self):
        self.second(LINES[0], "fils de Henri Marchand et de Jeanne roussal son épouse")
        self.assertEqual(T.doubtful_names(self.persons, self.folder, "r", 2), [])

    def test_a_second_reading_that_reads_otherwise(self):
        self.second(LINES[0], "fils de Henri Marchand et de Jeanne roussel son épouse")
        self.assertEqual(T.doubtful_names(self.persons, self.folder, "r", 2),
                         [f"Jeanne ROUSSEL: 'roussal[?]' or 'roussel' ({SOURCE})"])

    def test_a_second_reading_that_doubts_too(self):
        self.second(LINES[0], "fils de Henri Marchand[?] et de Jeanne roussal[?] son épouse")
        self.assertEqual(sorted(T.doubtful_names(self.persons, self.folder, "r", 2)),
                         [f"Henri MARCHAND: 'Marchand'[?] ({SOURCE})", f"Jeanne ROUSSEL: 'roussal'[?] ({SOURCE})",
                          f"Louis MARCHAND: 'Marchand'[?] ({SOURCE})"])

    def test_no_transcription(self):
        os.remove(T.path_for(self.folder, SOURCE))
        self.assertEqual(T.doubtful_names(self.persons, self.folder, "r", 2), [])


class PassEnd(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(tmp.name, "d"), "PROBANDIA_SESSION": "s1"}

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--harness", "claude-code"], stdout=out, environ=dict(self.env), cwd=self.dir,
                        stdin=io.StringIO())
        return code, out.getvalue()

    def test_pass_end_names_the_doubt(self):
        code, out = self.call("resume", RESEARCH, "--mode", "session")
        self.call("plan", RESEARCH)
        self.assertEqual(code, 0, out)
        n = int(re.search(r"^PASS=(\d+)", out, re.M).group(1))
        family = os.path.join(self.dir, "families", "marchand")
        path = os.path.join(family, "index", "persons.yaml")
        doc = yamlio.load(path)
        for p in doc["persons"]:
            for f in p.get("facts") or []:
                if f.get("source") == SOURCE:
                    f["pass"] = n
        yamlio.dump(path, doc)
        os.makedirs(os.path.dirname(T.path_for(family, SOURCE)), exist_ok=True)
        with open(T.path_for(family, SOURCE), "w", encoding="utf-8") as fh:
            fh.write(T.template(SOURCE, "v14.jpg", lines=LINES))
        code, out = self.call("pass", "end", RESEARCH, "--summary", "the birth of Louis")
        self.assertIn("DOUBTFUL_NAMES=", out)
        self.assertIn("'roussal'[?]", out)


if __name__ == "__main__":
    unittest.main()
