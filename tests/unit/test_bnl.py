"""BnL open data (T158): a package is streamed to disk, and the question gives its size."""
import io
import os
import pathlib
import shutil
import tempfile
import tracemalloc
import unittest
import zipfile
from unittest import mock

from probandia import archives, cli
from probandia.archives import Context
from probandia.util.http import Client
from tests import ROOT

MB = 1_000_000


class TTY(io.StringIO):
    def isatty(self):
        return True


class Download(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")

    def context(self, transport=None):
        return Context(Client(os.path.join(self.tmp.name, ".probandia"), transport=transport, sleep=lambda s: None),
                       data_dir=self.data)

    def test_a_50_mb_package_keeps_the_memory_under_100_mb(self):
        package = os.path.join(self.tmp.name, "luxemburger-wort-1871.zip")
        line = b"Victor Hugo arrive a Vianden. " * 33 + b"\n"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_STORED) as z, z.open("1871/issue.txt", "w") as fh:
            for _ in range(50 * MB // len(line)):
                fh.write(line)
        self.assertGreater(os.path.getsize(package), 49 * MB)
        tracemalloc.start()
        try:
            result = archives.run(archives.load("bnl"), "download", {"url": pathlib.Path(package).as_uri()},
                                  self.context())
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual((result.status, result.count), ("ok", 1), result.failure)
        self.assertLess(peak, 100 * MB)
        self.assertGreater(os.path.getsize(os.path.join(self.data, "bnl", "issue.txt")), 49 * MB)
        self.assertEqual(os.listdir(os.path.join(self.data, "bnl")), ["issue.txt"])   # the package is gone
        found = archives.run(archives.load("bnl"), "search", {"query": "Vianden", "max": 2}, self.context())
        self.assertEqual(len(found.rows), 2)

    def test_a_failed_download_is_a_connector_failure_and_leaves_nothing(self):
        result = archives.run(archives.load("bnl"), "download",
                              {"url": pathlib.Path(self.tmp.name, "absent.zip").as_uri()}, self.context())
        self.assertEqual(result.status, "failed")
        self.assertEqual(os.listdir(os.path.join(self.data, "bnl")), [])

    def test_the_question_gives_the_size_and_a_no_downloads_nothing(self):
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append(method)
            return 200, {"Content-Length": str(125 * MB)}, b"", url
        context = self.context(transport)
        project = os.path.join(self.tmp.name, "project")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), project)
        out = TTY()
        with mock.patch("probandia.cli.archive_cmd._context", lambda ctx: context):
            code = cli.main(["archive", "run", "bnl.download", "--args",
                             '{"url": "https://data.bnl.lu/open-data/newspapers/export01.zip"}'],
                            stdout=out, stdin=TTY("n\n"), cwd=project,
                            environ={"PROBANDIA_CONFIG_DIR": self.tmp.name, "NO_COLOR": "1",
                                     "PROBANDIA_PAGER": "none"})
        out = out.getvalue()
        self.assertIn("Download 125.0 MB from data.bnl.lu", out)
        self.assertIn("[y/N]", out)
        self.assertEqual(code, 4, out)
        self.assertEqual(calls, ["HEAD"])   # the size asked, nothing downloaded


if __name__ == "__main__":
    unittest.main()
