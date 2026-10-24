import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest

from probandia import paths
from probandia.ledger import Ledger, fingerprint
from probandia.project import create_project
from probandia.providers import catalogue
from tests import REUSE, ROOT

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)


class DataFolder(unittest.TestCase):
    """The user's data folder (cli.md § 4.4)."""

    def test_order(self):
        self.assertEqual(paths.user_data_dir({"PROBANDIA_DATA_DIR": "D", "PROBANDIA_CONFIG_DIR": "C"}), "D")
        self.assertEqual(paths.user_data_dir({"PROBANDIA_CONFIG_DIR": "C"}), os.path.join("C", "data"))

    def test_the_tests_never_reach_the_user_folder(self):
        self.assertTrue(paths.user_data_dir({}).startswith(tempfile.gettempdir()))


class Fingerprint(unittest.TestCase):
    def test_same_key_same_fingerprint(self):
        self.assertEqual(fingerprint("abc"), fingerprint("abc"))
        self.assertNotEqual(fingerprint("abc"), fingerprint("abd"))
        self.assertEqual(len(fingerprint("abc")), 8)

    def test_never_the_key(self):
        key = "sk-1234567890abcdef"
        self.assertNotIn(fingerprint(key), key)
        self.assertEqual(fingerprint(""), "public")
        self.assertEqual(fingerprint(None), "public")


class UserCounter(unittest.TestCase):
    """One count per key, whatever the project (decision D-1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        self.cat = catalogue.load()
        self.a = self.project("a")
        self.b = self.project("b")

    def project(self, name):
        path = os.path.join(self.tmp.name, name)
        create_project(path)
        return path

    def ledger(self, project, key="k1"):
        env = {"PROBANDIA_DATA_DIR": self.data, **REUSE, "TAVILY_API_KEY": key}
        return Ledger(project, self.cat, clock=lambda: NOW, environ=env)

    def test_two_projects_with_one_key_share_the_count(self):
        self.ledger(self.a).record("tavily", "search", 40)
        self.assertEqual(self.ledger(self.b).used("tavily")[0], 40)
        self.assertEqual(self.ledger(self.b).left("tavily", 10), 1000 - 40 - 100)
        self.assertEqual(self.ledger(self.b).projects_sharing("tavily"), 1)
        self.ledger(self.b).record("tavily", "search", 1)
        self.assertEqual(self.ledger(self.a).projects_sharing("tavily"), 2)

    def test_a_key_of_its_own_counts_apart(self):
        self.ledger(self.a).record("tavily", "search", 40)
        self.assertEqual(self.ledger(self.b, key="k2").used("tavily")[0], 0)

    def test_the_project_keeps_its_lines(self):
        self.ledger(self.a).record("tavily", "search", 3, research="r1", pass_no=2)
        with open(os.path.join(self.a, ".probandia", "ledger.jsonl"), encoding="utf-8") as fh:
            line = json.loads(fh.readline())
        self.assertEqual((line["research"], line["pass"]), ("r1", 2))
        self.assertNotIn("key", line)

    def test_exhaustion_is_shared(self):
        self.ledger(self.a).mark_exhausted("tavily")
        self.assertTrue(self.ledger(self.b).exhausted("tavily"))
        self.assertFalse(self.ledger(self.b, key="k2").exhausted("tavily"))

    def test_existing_lines_are_taken_over_once(self):
        legacy = Ledger(self.a, self.cat, clock=lambda: NOW)       # before the user's counter
        legacy.record("tavily", "search", 7)
        self.assertEqual(self.ledger(self.a).used("tavily")[0], 7)
        self.assertEqual(self.ledger(self.a).used("tavily")[0], 7)   # no second import
        self.assertEqual(self.ledger(self.b).used("tavily")[0], 7)

    def test_an_older_engine_is_caught_up(self):
        # an older plugin keeps writing to the project's ledger only, after the first import
        self.ledger(self.a).record("tavily", "search", 5)
        legacy = Ledger(self.a, self.cat, clock=lambda: NOW)
        legacy.record("tavily", "search", 7)
        self.assertEqual(self.ledger(self.b).used("tavily")[0], 5)    # B does not read A's ledger
        self.assertEqual(self.ledger(self.a).used("tavily")[0], 12)   # A catches its line up
        self.assertEqual(self.ledger(self.a).used("tavily")[0], 12)   # once
        self.assertEqual(self.ledger(self.b).used("tavily")[0], 12)

    def test_two_processes_lose_no_line(self):
        script = (
            "import sys, datetime\n"
            f"sys.path.insert(0, {os.path.join(ROOT, 'src')!r})\n"
            "from probandia.ledger import Ledger\n"
            "from probandia.providers import catalogue\n"
            f"env = {{'PROBANDIA_DATA_DIR': {self.data!r}, 'TAVILY_API_KEY': 'k1'}}\n"
            "led = Ledger(sys.argv[1], catalogue.load(), environ=env)\n"
            "for _ in range(50):\n"
            "    led.record('tavily', 'search', 1)\n")
        procs = [subprocess.Popen([sys.executable, "-c", script, p]) for p in (self.a, self.b)]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=120), 0)
        with open(os.path.join(self.data, "quotas", "ledger.jsonl"), encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(lines), 100)


if __name__ == "__main__":
    unittest.main()


class AcrossProjects(unittest.TestCase):
    """A search in one project lowers what another shows (cli-plan.md, CLI4 acceptance)."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = os.path.join(self.tmp.name, "a")
        self.b = os.path.join(self.tmp.name, "b")
        for path in (self.a, self.b):
            shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), path)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), **REUSE, "TAVILY_API_KEY": "k",
                    "PROBANDIA_SESSION": "t"}

    def call(self, project, *argv, env=None):
        import io
        from unittest import mock

        from probandia import cli
        from probandia.cli import search_cmd
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        def transport(method, url, headers, body, timeout):
            if url.endswith("/robots.txt"):
                return 200, {}, b"", url
            if url.startswith("https://api.tavily.com/search"):
                fx = fixture("tavily", "search-ok.json")
                return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url
            return 404, {}, b"", url

        def make_client(ctx):
            return Client(os.path.join(project, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        out = io.StringIO()
        with mock.patch.object(search_cmd, "_client", make_client):
            code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=project)
        return code, out.getvalue()

    def tavily_left(self, project, cwd=None):
        code, out = self.call(cwd or project, "usage", "--json")
        rows = {r["account"]: r for r in json.loads(out)["data"]["accounts"]}
        return rows["tavily"]["left"]

    def test_a_search_in_a_lowers_b(self):
        before = self.tavily_left(self.b)
        code, out = self.call(self.a, "search", "Hugo Besançon", "--engine", "tavily")
        self.assertEqual(code, 0, out)
        self.assertLess(self.tavily_left(self.b), before)
        self.assertLess(self.tavily_left(None, cwd=self.tmp.name), before)   # outside any project too

    def test_the_hard_stop_holds_across_projects(self):
        self.assertEqual(self.call(self.a, "quota", "add", "tavily", "899")[0], 0)   # 1000 - 100 reserve - 1
        code, out = self.call(self.b, "search", "Hugo Besançon 1803", "--engine", "tavily")
        self.assertEqual(code, 0, out)
        code, out = self.call(self.b, "search", "Hugo 1804", "--engine", "tavily")
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=free-quota:tavily", out)

    def test_a_shared_key_is_said(self):
        self.call(self.a, "quota", "add", "tavily", "1")
        self.call(self.b, "quota", "add", "tavily", "1")
        out = self.call(self.b, "usage")[1]
        self.assertIn("- Tavily: one key for 2 projects, one count for all", out.splitlines())


class ReadOnce(unittest.TestCase):
    """T148: a ledger file is parsed once while it does not change; each caller gets its own lines."""

    def test_a_line_appended_is_read_and_a_line_changed_by_a_caller_is_not_kept(self):
        from probandia import ledger

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.jsonl")
            ledger._append(path, {"provider": "jina", "units": 1})
            first = ledger._read_lines(path)
            first[0]["units"] = 99
            self.assertEqual(ledger._read_lines(path), [{"provider": "jina", "units": 1}])
            ledger._append(path, {"provider": "tavily", "units": 2})
            self.assertEqual([e["provider"] for e in ledger._read_lines(path)], ["jina", "tavily"])
            self.assertEqual(ledger._read_lines(os.path.join(tmp, "none.jsonl")), [])
