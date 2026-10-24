"""tools/check_wheel.py: the frozen contents of the packages and the private names inside them
(version-1.0.0 T253). Building stays out of the suite; these tests use small archives."""
import importlib.util
import io
import os
import tarfile
import tempfile
import unittest
import zipfile

from tests import ROOT


def load():
    spec = importlib.util.spec_from_file_location("check_wheel", os.path.join(ROOT, "tools", "check_wheel.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CW = load()


class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def wheel(self, files):
        path = os.path.join(self.tmp.name, "probandia-1.2.3-py3-none-any.whl")
        with zipfile.ZipFile(path, "w") as z:
            for name, text in files.items():
                z.writestr(name, text)
        return path

    def sdist(self, files):
        path = os.path.join(self.tmp.name, "probandia-1.2.3.tar.gz")
        with tarfile.open(path, "w:gz") as t:
            for name, text in files.items():
                data = text.encode("utf-8")
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
            folder = tarfile.TarInfo("probandia-1.2.3/empty")
            folder.type = tarfile.DIRTYPE
            t.addfile(folder)
        return path

    def test_the_contents_write_the_version_as_a_placeholder(self):
        wheel = self.wheel({"probandia/__init__.py": "", "probandia-1.2.3.dist-info/METADATA": "Version: 1.2.3"})
        self.assertEqual(CW.contents(wheel, "1.2.3"),
                         ["probandia-{version}.dist-info/METADATA", "probandia/__init__.py"])
        sdist = self.sdist({"probandia-1.2.3/PKG-INFO": "", "probandia-1.2.3/src/probandia/__init__.py": ""})
        self.assertEqual(CW.contents(sdist, "1.2.3"),   # files only, not folders
                         ["probandia-{version}/PKG-INFO", "probandia-{version}/src/probandia/__init__.py"])

    def test_the_list_is_written_then_read_back(self):
        path = os.path.join(self.tmp.name, "contents.txt")
        lists = {"wheel": ["b", "a"], "sdist": ["probandia-{version}/PKG-INFO"]}
        CW.write_list(lists, path)
        self.assertEqual(CW.read_list(path), {"wheel": {"a", "b"}, "sdist": {"probandia-{version}/PKG-INFO"}})
        self.assertEqual(CW.read_list(os.path.join(self.tmp.name, "none.txt")), {"wheel": set(), "sdist": set()})

    def test_a_file_more_or_missing_is_named(self):
        self.assertEqual(CW.differences({"a", "b"}, ["a", "c"]), (["c"], ["b"]))
        self.assertEqual(CW.differences({"a"}, ["a"]), ([], []))

    def test_private_names_are_looked_for_in_both_packages(self):
        word = "ab" + "c"
        wheel = self.wheel({"probandia/a.py": f"# {word.title()}\n", "probandia/b.png": word})
        sdist = self.sdist({f"probandia-1.2.3/tests/{word}.txt": "", "probandia-1.2.3/README.md": "nothing"})
        found = CW.private_names([wheel, sdist], {word})
        self.assertEqual(found, [f"probandia-1.2.3-py3-none-any.whl:probandia/a.py: {word}",
                                 f"probandia-1.2.3.tar.gz:probandia-1.2.3/tests/{word}.txt: {word}"])
        self.assertEqual(CW.private_names([wheel, sdist], set()), [])

    def test_the_frozen_list_is_in_the_repository(self):
        frozen = CW.read_list()
        self.assertIn("probandia/_data/catalogues/providers.toml", frozen["wheel"])
        self.assertIn("probandia-{version}/tools/package-contents.txt", frozen["sdist"])
        for member in CW.REQUIRED:
            self.assertIn(member, frozen["wheel"])
        # every module of the engine is in the wheel: a new one needs the list rewritten
        missing = []
        for here, _dirs, names in os.walk(os.path.join(ROOT, "src", "probandia")):
            for name in names:
                rel = os.path.relpath(os.path.join(here, name), os.path.join(ROOT, "src")).replace(os.sep, "/")
                if name.endswith(".py") and rel not in frozen["wheel"]:
                    missing.append(rel)
        self.assertEqual(missing, [], "python tools/check_wheel.py --update, then read the diff of the list")

    def test_relative_links_of_the_description(self):
        """T190: PyPI shows the README; only a URL or an anchor works there."""
        text = "[a](guides/x.md) [b](https://github.com/x) [c](#install) [d](mailto:x@example.org) [e](../y)"
        self.assertEqual(CW.relative_links(text), ["guides/x.md", "../y"])
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            self.assertEqual(CW.relative_links(fh.read()), [])


if __name__ == "__main__":
    unittest.main()
