import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import indexes, verify
from probandia.research import find_research
from probandia.util import yamlio
from tests import ROOT

SAMPLE = os.path.join(ROOT, "tests", "sample-project")


class IndexCache(unittest.TestCase):
    """T147: each index is read once per process, and read again once written."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.project = os.path.join(tmp, "p")
        shutil.copytree(SAMPLE, self.project)
        indexes._CACHE.clear()
        self.reads = []
        real = yamlio.load

        def counted(path):
            self.reads.append(os.path.basename(path))
            return real(path)

        patcher = mock.patch.object(indexes.yamlio, "load", side_effect=counted)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_verify_reads_persons_once(self):
        verify.run(self.project, find_research(self.project))
        self.assertEqual(self.reads.count("persons.yaml"), 1, self.reads)
        verify.run(self.project, find_research(self.project))
        self.assertEqual(self.reads.count("persons.yaml"), 1, self.reads)

    def test_a_write_then_a_read_gives_the_new_value(self):
        idx = indexes.FamilyIndexes(self.project, "marchand")
        doc = idx.load("persons")
        doc["persons"][0]["names"]["given"] = "Victor"
        self.assertNotEqual(idx.load("persons")["persons"][0]["names"]["given"], "Victor")   # a copy
        idx.write({"persons": doc}, {"harness": "cli", "agent": "session"}, "test")
        self.assertEqual(idx.load("persons")["persons"][0]["names"]["given"], "Victor")

    def test_a_file_changed_by_another_process_is_read_again(self):
        idx = indexes.FamilyIndexes(self.project, "marchand")
        doc = idx.load("persons")
        doc["persons"][0]["names"]["given"] = "Hugo"
        yamlio.dump(idx.path("persons"), doc)   # not through FamilyIndexes.write
        self.assertEqual(idx.load("persons")["persons"][0]["names"]["given"], "Hugo")


if __name__ == "__main__":
    unittest.main()
