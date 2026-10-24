import io
import os
import sys
import tempfile
import unittest

from tests import ROOT

sys.path.insert(0, os.path.join(ROOT, "tools"))
import replay_pass  # noqa: E402


class Replay(unittest.TestCase):
    def test_the_log_is_cut_then_written_back_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "p")
            out = io.StringIO()
            n = replay_pass.replay(folder, 0, out)
            with open(os.path.join(folder, replay_pass.LOG), "rb") as fh:
                replayed = fh.read()
        with open(os.path.join(replay_pass.SAMPLE, replay_pass.LOG), "rb") as fh:
            self.assertEqual(replayed, fh.read())
        self.assertGreater(n, 0)
        self.assertIn(f"{n}/{n}", out.getvalue())

    def test_an_existing_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            replay_pass.main([tmp])
