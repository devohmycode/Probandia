"""T266: libyaml's parser, when this Python has it, reads every YAML file as the pure Python one does."""
import glob
import os
import unittest

import yaml

from probandia.util import yamlio
from tests import ROOT


@unittest.skipUnless(yamlio.fast_loader(), "PyYAML's compiled _yaml is not installed at the vendored version")
class Fast(unittest.TestCase):
    def test_the_same_documents(self):
        files = [p for pattern in ("tests/**/*.yaml", "catalogues/*.yaml", "bench/public/**/*.yaml")
                 for p in glob.glob(os.path.join(ROOT, pattern), recursive=True)]
        self.assertGreater(len(files), 200)
        for path in files:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(os.path.relpath(path, ROOT)):
                try:
                    pure = yaml.load(text, Loader=yamlio.Loader)
                except yaml.YAMLError:   # an invalid fixture: both refuse it
                    with self.assertRaises(yaml.YAMLError):
                        yaml.load(text, Loader=yamlio.fast_loader())
                    continue
                self.assertEqual(yaml.load(text, Loader=yamlio.fast_loader()), pure)

    def test_timestamps_stay_strings(self):
        self.assertEqual(yamlio.loads("ts: 2026-09-30T18:40:00Z\nd: 1851-03-02\n"),
                         {"ts": "2026-09-30T18:40:00Z", "d": "1851-03-02"})


class Pure(unittest.TestCase):
    def test_without_libyaml_the_pure_loader_reads(self):
        saved = list(yamlio._FAST)
        self.addCleanup(lambda: yamlio._FAST.__setitem__(slice(None), saved))
        yamlio._FAST[:] = []
        os.environ["PROBANDIA_YAML_PURE"] = "1"
        self.addCleanup(os.environ.pop, "PROBANDIA_YAML_PURE", None)
        self.assertIsNone(yamlio.fast_loader())
        self.assertEqual(yamlio.loads("a: [1, 2]\nd: 1851-03-02\n"), {"a": [1, 2], "d": "1851-03-02"})
