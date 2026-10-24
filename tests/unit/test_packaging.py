import os
import re
import tomllib
import unittest

from tests import ROOT


def pyproject():
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)


class Wheel(unittest.TestCase):
    """The wheel carries the engine's data, which stays at the repository root for the plugin."""

    def test_data_folders_are_copied_into_the_package(self):
        include = pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        for folder in ("catalogues", "locales", "schemas", "vendor-js"):
            self.assertEqual(include.get(folder), f"probandia/_data/{folder}")
            self.assertTrue(os.path.isdir(os.path.join(ROOT, folder)), folder)

    def test_one_version(self):
        # pyproject.toml reads the version from __init__.py: no second copy to forget
        project = pyproject()["project"]
        self.assertNotIn("version", project)
        self.assertIn("version", project["dynamic"])
        source = pyproject()["tool"]["hatch"]["version"]["path"]
        with open(os.path.join(ROOT, source), encoding="utf-8") as fh:
            found = re.search(r'^__version__ = "([^"]+)"$', fh.read(), re.M)
        from probandia import __version__
        self.assertEqual(found.group(1), __version__)

    def test_no_dependency(self):
        self.assertEqual(pyproject()["project"]["dependencies"], [])


class Sdist(unittest.TestCase):
    """The sdist takes what git tracks at the root, never a local note left in a working copy."""

    def test_it_takes_the_tracked_root_entries_only(self):
        import subprocess

        try:
            out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        tracked = {p.split("/", 1)[0] for p in out.stdout.decode("utf-8").split("\0") if p}
        tracked.discard("private")   # tools/ci_local.py's copies commit the local list there; never packaged
        only = pyproject()["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
        self.assertEqual(sorted(only), sorted(tracked), "add the new root entry to only-include, or remove it")
        for local in (".remember", ".claude", ".cursor", "private"):
            self.assertNotIn(local, only)


class Release(unittest.TestCase):
    """release.yml (version-1.0.0 T210): what tools/check_wheel.py checked is what gets published, by trusted
    publishing, to TestPyPI by hand and to PyPI on a tag only."""

    def setUp(self):
        from probandia._vendor import yaml

        with open(os.path.join(ROOT, ".github", "workflows", "release.yml"), encoding="utf-8") as fh:
            self.text = fh.read()
        self.flow = yaml.safe_load(self.text)

    def test_actions_are_pinned(self):
        uses = re.findall(r"uses: (\S+)", self.text)
        self.assertTrue(uses)
        for use in uses:
            self.assertRegex(use, r"@[0-9a-f]{40}$")

    def test_the_checked_packages_are_published(self):
        jobs = self.flow["jobs"]
        build = [s.get("run", "") for s in jobs["build"]["steps"]]
        self.assertIn("python tools/check_wheel.py --dist dist", build)
        for name, index in (("testpypi", "https://test.pypi.org/legacy/"), ("pypi", None)):
            job = jobs[name]
            self.assertEqual(job["needs"], "build")
            self.assertEqual(job["environment"]["name"], name)
            self.assertEqual(job["permissions"], {"id-token": "write"})
            publish = job["steps"][-1]
            self.assertTrue(publish["uses"].startswith("pypa/gh-action-pypi-publish@"))
            self.assertEqual((publish.get("with") or {}).get("repository-url"), index)
        self.assertIn("workflow_dispatch", jobs["testpypi"]["if"])
        self.assertIn("github.ref_type == 'tag'", jobs["pypi"]["if"])
        self.assertEqual(self.flow["permissions"], {})


class Fonts(unittest.TestCase):
    """The fonts embedded in report-templates/ are subsets, so modified versions: under the OFL 1.1, none may
    bear a Reserved Font Name its licence declares (version-1.0.0 T203; IBM Plex Mono became Probandia Mono)."""

    TEMPLATES = os.path.join(ROOT, "report-templates")

    def setUp(self):
        self.reserved = set()
        licenses = os.path.join(self.TEMPLATES, "licenses")
        for name in os.listdir(licenses):
            with open(os.path.join(licenses, name), encoding="utf-8") as fh:
                self.reserved.update(re.findall(r'Reserved Font Names? "([^"]+)"', fh.read()))
        self.assertIn("Plex", self.reserved)   # the reading works: the test is not vacuous
        self.css = {}
        for name in sorted(os.listdir(self.TEMPLATES)):
            if name.endswith(".html"):
                with open(os.path.join(self.TEMPLATES, name), encoding="utf-8") as fh:
                    self.css[name] = fh.read()

    def bears_reserved(self, family):
        return [r for r in self.reserved if re.search(rf"\b{re.escape(r)}\b", family, re.I)]

    def test_no_template_names_a_reserved_font(self):
        for name, text in self.css.items():
            text = re.sub(r"/\*.*?\*/|base64,[A-Za-z0-9+/=]+", "", text, flags=re.S)
            # font-family declarations, and the custom properties that hold a font stack (--mono:"…",monospace)
            for stack in re.findall(r"(?:font-family|--[\w-]+)\s*:\s*([^;}]+)", text):
                for family in stack.split(","):
                    family = family.strip().strip("'\"")
                    self.assertEqual(self.bears_reserved(family), [], f"{name}: {family}")

    def test_embedded_fonts_do_not_bear_a_reserved_name(self):
        try:
            import brotli  # noqa: F401  (fontTools reads WOFF2 through it)
            from fontTools.ttLib import TTFont
        except ImportError:
            self.skipTest("fontTools or brotli is not installed")
        import base64
        import io

        seen = 0
        for name, text in self.css.items():
            for data in re.findall(r"data:font/[\w-]+;base64,([A-Za-z0-9+/=]+)", text):
                seen += 1
                for record in TTFont(io.BytesIO(base64.b64decode(data)))["name"].names:
                    if record.nameID in (1, 3, 4, 6, 16, 17, 21, 22):   # the names, not the copyright
                        value = record.toUnicode()
                        self.assertEqual(self.bears_reserved(value), [], f"{name}: name {record.nameID} {value}")
        self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()
