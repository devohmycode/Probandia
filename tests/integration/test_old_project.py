"""A project written by the 0.9.41 opens and checks in this version (version-1.0.0 T215).

``tests/fixtures/project-0.9.41/`` is ``tests/sample-project`` as the 0.9.41
wrote it (commit f1cb231), one surname since replaced; unlike the sample, it
is never regenerated.
"""
import io
import os
import shutil
import tempfile
import unittest

from probandia import cli
from tests import ROOT

OLD = os.path.join(ROOT, "tests", "fixtures", "project-0.9.41")
RID = "2026-09-01-ancestors-of-louis-marchand"


class OldProject(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "old")
        shutil.copytree(OLD, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "user"), "PROBANDIA_SESSION": "old",
                    "CLAUDE_CONFIG_DIR": os.path.join(tmp.name, "claude"), "LANG": "en_US.UTF-8"}
        for k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
            if k in os.environ:
                self.env[k] = os.environ[k]

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env), cwd=self.dir)
        return code, out.getvalue()

    def test_status_render_verify_and_export_succeed(self):
        for argv in (("status",), ("render", RID), ("verify", RID),
                     ("export", "gedcom7", "--family", "marchand")):
            with self.subTest(argv=argv):
                code, out = self.call(*argv)
                self.assertEqual(code, 0, out)
                self.assertIn("STATUS=OK", out)


if __name__ == "__main__":
    unittest.main()
