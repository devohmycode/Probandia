"""The test package refuses to run under a Probandia project (tests/__init__.py)."""
import os
import subprocess
import sys
import tempfile
import unittest

from tests import ROOT


class ParentProject(unittest.TestCase):
    def test_a_project_above_the_temporary_folder_stops_the_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "probandia.toml"), "w", encoding="utf-8").close()
            inner = os.path.join(tmp, "tmp")
            os.mkdir(inner)
            env = dict(os.environ, TMP=inner, TEMP=inner, TMPDIR=inner)
            done = subprocess.run([sys.executable, "-c", "import tests"], cwd=ROOT, env=env,
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("the tests would write into it", done.stderr)


if __name__ == "__main__":
    unittest.main()
