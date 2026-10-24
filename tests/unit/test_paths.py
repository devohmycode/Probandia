import os
import re
import tempfile
import unittest

from probandia import paths
from tests import ROOT

DATA_FOLDERS = ("catalogues", "schemas", "vendor-js")


class DataRoot(unittest.TestCase):
    """The engine's data: inside the package of a wheel, else at the repository root."""

    def test_repository_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = os.path.join(tmp, "src", "probandia")
            os.makedirs(package)
            self.assertEqual(paths.data_root(package), tmp)
            self.assertEqual(paths.data("catalogues", "providers.toml", package_dir=package),
                             os.path.join(tmp, "catalogues", "providers.toml"))

    def test_wheel_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = os.path.join(tmp, "site-packages", "probandia")
            os.makedirs(os.path.join(package, "_data", "catalogues"))
            self.assertEqual(paths.data_root(package), os.path.join(package, "_data"))
            self.assertEqual(paths.data("schemas", package_dir=package),
                             os.path.join(package, "_data", "schemas"))

    def test_this_checkout_reads_the_repository(self):
        self.assertTrue(os.path.isfile(paths.data("catalogues", "providers.toml")))
        self.assertTrue(os.path.isdir(paths.data("locales")))

    def test_no_other_module_builds_these_paths(self):
        # every lookup of the data folders goes through probandia.paths
        literal = re.compile(r"os\.path\.join\([^)]*\"(%s)\"" % "|".join(DATA_FOLDERS))
        src = os.path.join(ROOT, "src", "probandia")
        offenders = []
        for folder, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in ("_vendor", "__pycache__")]
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as fh:
                        for n, line in enumerate(fh, 1):
                            if literal.search(line) and "data_root" not in line:
                                offenders.append(f"{os.path.relpath(path, src)}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
