"""The source watch (TRUST4-T3), on recorded answers."""
import datetime
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from probandia import cli
from probandia.archives.finder import load_catalogue
from probandia.cli import watch_cmd
from tests.unit import test_archives as TA


class Witnesses(TA.Base):
    def context_for(self, overrides=None):
        return lambda archive_id: self.context(archive_id, overrides.get(archive_id) if overrides else None)

    def test_passed_failed_not_run(self):
        cat = load_catalogue()
        environ = {"GEONAMES_USERNAME": "USER"}
        broken = {"matchid": {"*": {"status": 200, "body": {"response": {"persons": [], "total": 0}}}}}
        rows = {r["archive"]: r for r in watch_cmd.witnesses(None, environ, self.data,
                                                             self.context_for(broken), cat)}
        self.assertEqual(rows["wikitree"]["state"], "passed")
        self.assertEqual(rows["matchid"]["state"], "failed")
        self.assertTrue(rows["matchid"]["failure"])
        # T121: a site that refuses its witness is not run, the date and the reason in its state
        for archive in ("gallica", "loc", "gov"):
            self.assertEqual((rows[archive]["state"], rows[archive]["reason"]), ("not-run", "refused"))
            self.assertRegex(cat[archive]["state"]["witness_refused"], r"^2026-\d\d-\d\d: ")
        self.assertEqual(rows["iiif"]["state"], "passed")
        self.assertNotIn("gallica", cat["iiif"]["witness"]["args"]["url"])
        self.assertEqual((rows["geonames"]["state"], rows["geonames"]["reason"]), ("passed", None))
        self.assertEqual(rows["ad56"]["reason"], "browser")
        self.assertEqual(rows["familysearch"]["reason"], "session")
        self.assertEqual(rows["socface"]["reason"], "no-connector")
        # without a key, or without the downloaded files, a witness is not run: never a failure
        rows = {r["archive"]: r for r in watch_cmd.witnesses(None, {}, os.path.join(self.tmp.name, "none"),
                                                             self.context_for(), cat)}
        self.assertEqual((rows["geonames"]["state"], rows["geonames"]["reason"]), ("not-run", "key"))
        self.assertEqual(rows["insee_cog"]["reason"], "files")
        self.assertEqual(rows["bnl"]["reason"], "files")
        self.assertEqual(rows["europeana"]["state"], "passed")   # its public demonstration key


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user")}

    def call(self, *argv, cwd=None):
        out = io.StringIO()
        fake = [{"archive": "gallica", "operation": "search", "state": "failed", "reason": None, "count": 0,
                 "failure": "HTTP 503"},
                {"archive": "wikitree", "operation": "search", "state": "passed", "reason": None, "count": 3,
                 "failure": None},
                {"archive": "geonames", "operation": "search", "state": "not-run", "reason": "key", "count": None,
                 "failure": None}]
        with mock.patch.object(watch_cmd, "witnesses", lambda *a, **k: fake):
            code = cli.main(list(argv), stdout=out, environ=self.env, cwd=cwd or self.tmp.name)
        return code, out.getvalue()

    def test_outside_a_project(self):
        out_dir = os.path.join(self.tmp.name, "out")
        code, out = self.call("watch", "--out", out_dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[0], "STATUS=WARN")
        self.assertIn("FAILED=1", out)
        self.assertIn("NOT_RUN=1", out)
        self.assertIn("- witness=gallica failed", out)
        self.assertIn("- witness=geonames not-run key", out)
        with open(os.path.join(out_dir, "watch.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual([w["state"] for w in doc["witnesses"]], ["failed", "passed", "not-run"])
        with open(os.path.join(out_dir, "watch.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("- `gallica.search`: HTTP 503", md)

    def test_print_schedule(self):
        """TRUST4-T4: the command that runs the watch every Monday; Probandia schedules nothing itself."""
        code, out = self.call("watch", "--print-schedule")
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAILED=", out)   # no witness was run
        line = next(x for x in out.splitlines() if x.startswith("- schedule="))
        self.assertIn("-m probandia watch", line)
        self.assertIn("schtasks /Create /SC WEEKLY /D MON" if os.name == "nt" else "0 8 * * 1 cd ", line)
        win = watch_cmd.schedule(r"C:\Users\Me\proj", r"C:\Py\python.exe", True)
        self.assertEqual(win, r'schtasks /Create /SC WEEKLY /D MON /ST 08:00 /TN "Probandia watch" /TR "cmd /c cd /d '
                              r'\"C:\Users\Me\proj\" && \"C:\Py\python.exe\" -m probandia watch"')
        self.assertEqual(watch_cmd.schedule("/home/me/p", "/usr/bin/python3", False),
                         "0 8 * * 1 cd '/home/me/p' && \"/usr/bin/python3\" -m probandia watch")

    def test_failures_in_a_row(self):
        """TRUST-D7, made precise: each watch counts the failures in a row of a witness."""
        out_dir = os.path.join(self.tmp.name, "out")
        for n in (1, 2, 3):
            code, out = self.call("watch", "--out", out_dir)
            with open(os.path.join(out_dir, "watch.json"), encoding="utf-8") as fh:
                rows = {w["archive"]: w for w in json.load(fh)["witnesses"]}
            self.assertEqual((rows["gallica"]["streak"], rows["wikitree"]["streak"]), (n, 0))

    def test_issues_after_three_failures(self):
        """TRUST4-T5: the plan of issues, printed by --dry-run, sends nothing."""
        import importlib.util

        from tests import ROOT

        spec = importlib.util.spec_from_file_location("watch_issues", os.path.join(ROOT, "tools", "watch_issues.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        doc = {"date": "2026-10-05", "version": "x", "days": 90,
               "witnesses": [{"archive": "loc", "operation": "search", "state": "failed", "failure": "HTTP 403",
                              "streak": 2},
                             {"archive": "gallica", "operation": "search", "state": "failed", "failure": "HTTP 503",
                              "streak": 3},
                             {"archive": "wikitree", "operation": "search", "state": "passed", "streak": 0},
                             {"archive": "geonames", "operation": "search", "state": "not-run", "reason": "key"}],
               "stale": [{"catalogue": "archives", "entry": "ad56", "checked": "2026-01-01", "age_days": 277}]}
        todo = tool.plan(doc)
        self.assertEqual([i["title"] for i in todo["open"]],
                         ["watch: gallica witness failed", "watch: archives entry ad56 is stale"])
        self.assertIn("3 watches in a row", todo["open"][0]["body"])
        self.assertIn("probandia archive run gallica.witness", todo["open"][0]["body"])
        self.assertEqual(todo["close"], ["watch: wikitree witness failed"])
        self.assertEqual([i["title"] for i in tool.plan(doc, after=2)["open"]][:2],
                         ["watch: loc witness failed", "watch: gallica witness failed"])
        path = os.path.join(self.tmp.name, "watch.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        printed = io.StringIO()
        with mock.patch("sys.stdout", printed), mock.patch.object(tool.subprocess, "run") as run:
            self.assertEqual(tool.main([path, "--dry-run"]), 0)
        run.assert_not_called()
        self.assertEqual(json.loads(printed.getvalue()), todo)

    def test_an_entry_checked_again_closes_its_issue(self):
        """T122: an entry stale at watch N, up to date at watch N+1: its issue closes (a fake gh)."""
        import importlib.util

        from tests import ROOT

        spec = importlib.util.spec_from_file_location("watch_issues", os.path.join(ROOT, "tools", "watch_issues.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        issues, calls = {}, []

        def gh(*args):
            calls.append(args[:2])
            if args[:2] == ("issue", "list"):
                return json.dumps([{"number": n, "title": t} for t, n in issues.items()])
            if args[:2] == ("issue", "create"):
                issues[args[args.index("--title") + 1]] = len(issues) + 1
            if args[:2] == ("issue", "close"):
                issues.pop(next(t for t, n in issues.items() if str(n) == args[2]))
            return ""

        def watch(day, stale):
            path = os.path.join(self.tmp.name, f"watch-{day}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"date": day, "version": "x", "days": 90, "witnesses": [
                    {"archive": "gallica", "operation": "search", "state": "failed", "failure": "HTTP 503",
                     "streak": 1}], "stale": stale}, fh)
            with mock.patch.object(tool, "gh", gh), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(tool.main([path, "--after", "1"]), 0)

        watch("2026-10-05", [{"catalogue": "archives", "entry": "ad56", "checked": "2026-01-01", "age_days": 277}])
        self.assertEqual(set(issues), {"watch: archives entry ad56 is stale", "watch: gallica witness failed"})
        watch("2026-10-12", [])
        self.assertEqual(set(issues), {"watch: gallica witness failed"})
        self.assertIn(("issue", "close"), calls)
        body = tool.plan({"date": "d", "witnesses": [{"archive": "a", "state": "failed", "streak": 1}]}, 1)
        self.assertIn("1 watch in a row", body["open"][0]["body"])

    def test_a_stale_entry(self):
        today = datetime.date.today() + datetime.timedelta(days=200)
        rows, days = watch_cmd.stale(None, None, today)
        self.assertEqual(days, 90)
        self.assertIn(("archives", "gallica"), {(x["catalogue"], x["entry"]) for x in rows})
        self.assertIn("providers", {x["catalogue"] for x in rows})
        self.assertEqual(watch_cmd.stale(None, None, datetime.date(2026, 10, 5))[0],
                         [x for x in watch_cmd.stale(None, None, datetime.date(2026, 10, 5))[0]
                          if x["checked"] is None])   # nothing checked is stale yet, but entries never checked


class Workflow(unittest.TestCase):
    """T213, TRUST4-T6: watch.yml, its steps replayed here: the previous watch.json comes back, the watch runs,
    its issues follow (a fake gh). Three failures open the issue; the witness passing again closes it."""

    def setUp(self):
        from probandia._vendor import yaml
        from tests import ROOT

        self.root = ROOT
        with open(os.path.join(ROOT, ".github", "workflows", "watch.yml"), encoding="utf-8") as fh:
            self.text = fh.read()
        self.steps = yaml.safe_load(self.text)["jobs"]["watch"]["steps"]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_pinned_and_in_order(self):
        import re

        for use in re.findall(r"uses: (\S+)", self.text):
            self.assertRegex(use, r"@[0-9a-f]{40}$")
        uses = [s.get("uses", "").split("@")[0] or s["name"] for s in self.steps]
        self.assertLess(uses.index("actions/cache/restore"), uses.index("Watch the sources"))
        self.assertLess(uses.index("Watch the sources"), uses.index("actions/cache/save"))
        restore, save = (next(s for s in self.steps if s.get("uses", "").startswith(a))
                         for a in ("actions/cache/restore", "actions/cache/save"))
        self.assertEqual(restore["with"]["path"], save["with"]["path"])
        self.assertEqual(restore["with"]["key"], save["with"]["key"])
        self.assertTrue(save["with"]["key"].startswith(restore["with"]["restore-keys"]))
        run = next(s["run"] for s in self.steps if s.get("name") == "Watch the sources")
        self.assertIn(f"--out {restore['with']['path']}", run)
        issues = next(s for s in self.steps if s.get("name") == "Open, update and close the issues")
        self.assertIn(f"tools/watch_issues.py {restore['with']['path']}/watch.json", issues["run"])
        self.assertIn("GH_TOKEN", issues["env"])

    def test_three_runs_open_the_issue_a_fourth_closes_it(self):
        import importlib.util
        import shutil

        spec = importlib.util.spec_from_file_location("watch_issues",
                                                      os.path.join(self.root, "tools", "watch_issues.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        issues = {}

        def gh(*args):
            if args[:2] == ("issue", "list"):
                return json.dumps([{"number": n, "title": t} for t, n in issues.items()])
            if args[:2] == ("issue", "create"):
                issues[args[args.index("--title") + 1]] = len(issues) + 1
            if args[:2] == ("issue", "close"):
                issues.pop(next(t for t, n in issues.items() if str(n) == args[2]))
            return ""

        cache = os.path.join(self.tmp.name, "cache")

        def run(state):
            work = os.path.join(self.tmp.name, "checkout")   # each run starts from a fresh checkout
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work)
            if os.path.isdir(cache):   # actions/cache/restore
                shutil.copytree(cache, os.path.join(work, "watch-state"))
            fake = [{"archive": "gallica", "operation": "search", "state": state, "reason": None, "count": 0,
                     "failure": "HTTP 503" if state == "failed" else None}]
            with mock.patch.object(watch_cmd, "witnesses", lambda *a, **k: fake):
                self.assertEqual(cli.main(["watch", "--out", "watch-state"], stdout=io.StringIO(), cwd=work,
                                          environ={"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u")}), 0)
            shutil.rmtree(cache, ignore_errors=True)   # actions/cache/save, under a new key
            shutil.copytree(os.path.join(work, "watch-state"), cache)
            with mock.patch.object(tool, "gh", gh), mock.patch("sys.stdout", io.StringIO()):
                tool.main([os.path.join(work, "watch-state", "watch.json")])
            return set(t for t in issues if "witness" in t)

        self.assertEqual(run("failed"), set())
        self.assertEqual(run("failed"), set())
        self.assertEqual(run("failed"), {"watch: gallica witness failed"})
        self.assertEqual(run("passed"), set())
