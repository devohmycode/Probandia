"""tools/run_tests.py: the modules found as discover finds them, shared out, the outputs whole."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from tests import ROOT

TOOL = os.path.join(ROOT, "tools", "run_tests.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("run_tests", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rt = load_tool()

FILES = {
    "t/__init__.py": "",
    "t/test_a.py": """
        import sys, unittest
        class A(unittest.TestCase):
            def test_one(self):
                for i in range(200):
                    print("A-line", i, file=sys.stderr, flush=True)
            @unittest.skip("not here")
            def test_two(self):
                pass
    """,
    "t/test_b.py": """
        import unittest
        class B(unittest.TestCase):
            def test_fails(self):
                self.assertEqual(1, 2)
            def test_passes(self):
                pass
    """,
    "t/sub/__init__.py": "",
    "t/sub/test_c.py": """
        import sys, unittest, warnings
        class C(unittest.TestCase):
            def test_warns(self):
                for i in range(200):
                    print("C-line", i, file=sys.stderr, flush=True)
                warnings.warn("unclosed file", ResourceWarning)
    """,
    "t/notpkg/test_d.py": "raise SystemExit('not a package: never imported')\n",
    "t/helper.py": "",
}


class FakeTree(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = tmp.name
        for path, text in FILES.items():
            full = os.path.join(self.top, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(text))

    def run_tool(self, *args):
        argv = [sys.executable, TOOL, "-s", "t", "--top", self.top,
                "--durations", os.path.join(self.top, "durations.json"), *args]
        r = subprocess.run(argv, capture_output=True)
        return r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")

    def test_discover_finds_what_unittest_finds(self):
        names = rt.discover("t", self.top)
        self.assertEqual(names, ["t.sub.test_c", "t.test_a", "t.test_b"])   # sorted names, folders among files
        suite = unittest.TestLoader().discover(os.path.join(self.top, "t"), top_level_dir=self.top)
        try:
            found = []

            def walk(s):
                for item in s:
                    if isinstance(item, unittest.TestSuite):
                        walk(item)
                    elif type(item).__module__ not in found:
                        found.append(type(item).__module__)
            walk(suite)
            self.assertEqual(found, names)
        finally:
            for name in list(sys.modules):
                if name == "t" or name.startswith("t."):
                    del sys.modules[name]
            sys.path[:] = [p for p in sys.path if os.path.normcase(p) != os.path.normcase(self.top)]

    def test_two_processes_one_red_outputs_whole(self):
        code, out = self.run_tool("-j", "2", "-v")
        self.assertEqual(code, 1, out)
        self.assertIn("Ran 5 tests in ", out)
        self.assertIn("FAILED (failures=1, skipped=1)", out)
        self.assertIn("ResourceWarning", out)
        self.assertIn("test_passes (t.test_b.B.test_passes) ... ok", out)
        self.assertEqual(out.count("===== process "), 2)
        lines = out.splitlines()
        for marker in ("A-line", "C-line"):
            where = [i for i, line in enumerate(lines) if marker in line]
            self.assertEqual(len(where), 200)
            self.assertEqual(where[-1] - where[0], 199, f"{marker} lines interleaved")

    def test_one_process_green(self):
        os.remove(os.path.join(self.top, "t", "test_b.py"))
        code, out = self.run_tool("-j", "1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("===== process "), 1)
        self.assertTrue(out.rstrip().endswith("OK (skipped=1)"), out)

    def test_measure_writes_one_duration_per_module(self):
        code, out = self.run_tool("--measure", "-j", "3")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("===== process "), 3)
        with open(os.path.join(self.top, "durations.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(sorted(data["modules"]), ["t.sub.test_c", "t.test_a", "t.test_b"])


class Sharing(unittest.TestCase):
    def test_the_heaviest_first_each_to_the_lightest_share(self):
        modules = ["m1", "m2", "m3", "m4", "m5"]
        weight = {"m1": 10, "m2": 6, "m3": 5, "m4": 4, "m5": 1}
        shares = rt.share(modules, weight, 2)
        self.assertEqual(sorted(sorted(s) for s in shares), [["m1", "m4"], ["m2", "m3", "m5"]])
        self.assertEqual(rt.share(modules, weight, 9), [[m] for m in ["m1", "m2", "m3", "m4", "m5"]])
        self.assertEqual(rt.share(modules, weight, 1), [modules])

    def test_an_unknown_module_weighs_its_size_at_the_pace_of_the_known(self):
        with tempfile.TemporaryDirectory() as top:
            for name, size in (("a", 100), ("b", 300)):
                with open(os.path.join(top, name + ".py"), "w") as fh:
                    fh.write("#" * size)
            self.assertEqual(rt.weights(["a", "b"], {"a": 2.0}, top), {"a": 2.0, "b": 6.0})
            self.assertEqual(rt.weights(["a", "b"], {}, top), {"a": 100.0, "b": 300.0})

    def test_the_real_suite(self):
        names = rt.discover()
        self.assertIn("tests.unit.test_run_tests", names)
        self.assertIn("tests.integration.test_sample_project", names)
        self.assertFalse([n for n in names if "fixtures" in n or "sample-project" in n])
        known = rt.read_durations()
        self.assertTrue(known, "tools/test_durations.json")
        self.assertLessEqual(rt.default_jobs(), rt.MAX_JOBS)


class Verdicts(unittest.TestCase):
    def test_counts_of_a_unittest_output(self):
        out = b"..s\n------\nRan 3 tests in 0.010s\n\nFAILED (failures=1, errors=2, skipped=1)\n"
        ran, found, complete = rt.counts_of(out)
        self.assertEqual((ran, found["failures"], found["errors"], found["skipped"], complete), (3, 1, 2, 1, True))
        self.assertEqual(rt.counts_of(b"Ran 1 test in 0.001s\n\nOK\n")[0], 1)
        self.assertFalse(rt.counts_of(b"Traceback (most recent call last):\n")[2])

    def test_summary_line(self):
        found = dict.fromkeys(rt.COUNTS, 0)
        self.assertEqual(rt.summary_line(found), "OK")
        found["skipped"] = 4
        self.assertEqual(rt.summary_line(found), "OK (skipped=4)")
        found["errors"] = 1
        self.assertEqual(rt.summary_line(found), "FAILED (errors=1, skipped=4)")


if __name__ == "__main__":
    unittest.main()
