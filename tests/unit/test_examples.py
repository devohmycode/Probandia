"""The real records of examples/hugo/ and their manifest (version-1.0.0 T255): every image is listed, with
its rights, its credit and a fingerprint that matches; nothing is in the folder that the manifest leaves out."""
import hashlib
import os
import struct
import unittest

from probandia.util import yamlio
from tests import ROOT

FOLDER = os.path.join(ROOT, "examples", "hugo")
RIGHTS = ("public domain", "CC0")   # what a public repository may carry without asking anyone


def jpeg_size(data):
    """(width, height) from the frame header of a JPEG."""
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise ValueError("no frame header")


class Records(unittest.TestCase):
    def setUp(self):
        self.manifest = yamlio.load(os.path.join(FOLDER, "manifest.yaml"))

    def test_the_manifest_lists_every_image(self):
        listed = sorted(r["file"] for r in self.manifest["records"])
        found = sorted(f for f in os.listdir(FOLDER) if f.endswith((".jpg", ".jpeg", ".png", ".tif")))
        self.assertEqual(listed, found)
        self.assertGreaterEqual(len(listed), 2)

    def test_each_image_is_the_one_downloaded(self):
        for r in self.manifest["records"]:
            with self.subTest(file=r["file"]):
                with open(os.path.join(FOLDER, r["file"]), "rb") as fh:
                    data = fh.read()
                self.assertEqual(hashlib.sha256(data).hexdigest(), r["sha256"])
                self.assertEqual(len(data), r["bytes"])
                self.assertEqual(jpeg_size(data), (r["width"], r["height"]))

    def test_each_record_says_its_rights_its_credit_and_what_to_check(self):
        for r in self.manifest["records"]:
            with self.subTest(file=r["file"]):
                self.assertTrue(r["rights"].startswith(RIGHTS), r["rights"])
                self.assertTrue(r["credit"])
                self.assertTrue(r["source"].startswith("https://") and r["url"].startswith("https://"))
                self.assertIn(r["kind"], ("original register", "facsimile"))
                self.assertTrue(r["check"])

    def test_the_guide_names_each_file(self):
        with open(os.path.join(FOLDER, "README.md"), encoding="utf-8") as fh:
            guide = fh.read()
        for r in self.manifest["records"]:
            self.assertIn(f"`{r['file']}`", guide)
        self.assertIn('probandia dates "7 ventôse an X"', guide)


if __name__ == "__main__":
    unittest.main()
