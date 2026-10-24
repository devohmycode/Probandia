import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from probandia.util import fs


class AtomicWrites(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_utf8_lf_no_bom(self):
        p = os.path.join(self.tmp.name, "sub", "a.txt")
        fs.atomic_write_text(p, "é\r\nb\rc\n")
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), "é\nb\nc\n".encode("utf-8"))

    def test_replaces_whole_file(self):
        p = os.path.join(self.tmp.name, "a.json")
        fs.atomic_write_json(p, {"a": 1})
        fs.atomic_write_json(p, {"b": "é"})
        self.assertEqual(fs.read_text(p), '{\n  "b": "é"\n}\n')

    def test_failure_keeps_old_content_and_leaves_no_temp(self):
        p = os.path.join(self.tmp.name, "a.txt")
        fs.atomic_write_text(p, "old\n")
        with mock.patch("os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                fs.atomic_write_text(p, "new\n")
        self.assertEqual(fs.read_text(p), "old\n")
        self.assertEqual(os.listdir(self.tmp.name), ["a.txt"])

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_mode_of_new_and_replaced_files(self):
        p = os.path.join(self.tmp.name, "m.txt")
        old = os.umask(0o022)
        try:
            fs.atomic_write_text(p, "a")
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o644)
            os.chmod(p, 0o640)
            fs.atomic_write_text(p, "b")
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o640)
        finally:
            os.umask(old)

    def test_read_text_drops_bom(self):
        p = os.path.join(self.tmp.name, "b.txt")
        with open(p, "wb") as fh:
            fh.write(b"\xef\xbb\xbfhello")
        self.assertEqual(fs.read_text(p), "hello")


class Timestamps(unittest.TestCase):
    def test_iso_round_trip(self):
        dt = datetime(2026, 9, 30, 18, 34, 12, 999, tzinfo=timezone.utc)
        self.assertEqual(fs.iso(dt), "2026-09-30T18:34:12Z")
        self.assertEqual(fs.parse_iso("2026-09-30T18:34:12Z"), dt.replace(microsecond=0))
