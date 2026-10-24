import os
import subprocess
import sys
import unittest

from tests import SRC

VENDOR = os.path.join(SRC, "probandia", "_vendor")

PROBE = r"""
import sys
sys.path.insert(0, sys.argv[1])
import probandia, yaml, tomlkit, markdown_it, mdurl
for m in (yaml, tomlkit, markdown_it, mdurl):
    print(m.__name__, m.__file__)
print(yaml.safe_load("a: [1, 2]"))
print(tomlkit.dumps({"x": 1}).strip())
print(markdown_it.MarkdownIt().render("*hi*").strip())
"""


class Vendored(unittest.TestCase):
    """The engine imports its four libraries with no package installed."""

    def test_imports_without_site_packages(self):
        # -I: isolated mode; -S: no site module, so no installed package is visible.
        r = subprocess.run([sys.executable, "-I", "-S", "-c", PROBE, SRC],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        for line in lines[:4]:
            name, path = line.split(" ", 1)
            self.assertTrue(os.path.normcase(path).startswith(os.path.normcase(VENDOR)), line)
        self.assertEqual(lines[4], "{'a': [1, 2]}")
        self.assertEqual(lines[5], "x = 1")
        self.assertEqual(lines[6], "<p><em>hi</em></p>")

    def test_no_compiled_files(self):
        for folder, _, files in os.walk(VENDOR):
            for f in files:
                self.assertFalse(f.endswith((".pyd", ".so", ".dll")), os.path.join(folder, f))

    def test_licences_listed(self):
        with open(os.path.join(VENDOR, "LICENSES.md"), encoding="utf-8") as fh:
            text = fh.read()
        for dist in ("PyYAML", "tomlkit", "markdown-it-py", "mdurl"):
            self.assertIn(f"| {dist} |", text)
        for name in os.listdir(os.path.join(VENDOR, "licenses")):
            self.assertIn(name, text)
