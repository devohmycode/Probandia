import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, i18n
from probandia.cli import search_cmd, usage_cmd
from probandia.ledger import Ledger
from probandia.providers import catalogue
from probandia.util.http import Client
from tests import REUSE, ROOT
from tests.unit.test_adapters import fixture
from tests.unit.test_human import golden

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)
KEYS = {"SERPAPI_API_KEY": "k", "SERPER_API_KEY": "k", "OPENWEBNINJA_API_KEY": "k", "TAVILY_API_KEY": "k",
        "EXA_API_KEY": "k", "FIRECRAWL_API_KEY": "k", "ZENROWS_API_KEY": "k", "SCRAPERAPI_API_KEY": "k",
        "APIFY_TOKEN": "k", "BRAVE_API_KEY": "k"}


class Terminal(io.StringIO):
    def isatty(self):
        return True


class Usage(unittest.TestCase):
    """probandia -u: the free tiers account by account (cli.md § 4)."""

    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = dict(KEYS, PROBANDIA_CONFIG_DIR=os.path.join(self.tmp.name, "u"), NO_COLOR="1",
                        PROBANDIA_PAGER="none", **REUSE)   # T217: Tavily, Exa
        for patcher in (mock.patch.object(usage_cmd, "_now", return_value=NOW),
                        mock.patch("probandia.i18n.formats.local_time", return_value="2026-10-02 18:30")):
            patcher.start()
            self.addCleanup(patcher.stop)
        ledger = Ledger(self.dir, catalogue.load(), clock=lambda: NOW)
        for provider, units in (("serpapi", 26), ("openwebninja_search", 12), ("tavily", 85), ("exa", 0.42),
                                ("jina", 186000), ("firecrawl", 47), ("zenrows", 4), ("apify", 0.31),
                                ("openwebninja_books", 3)):
            ledger.record(provider, "search", units)

    def call(self, *argv, terminal=False, routes=None):
        def transport(method, url, headers, body, timeout):
            for prefix, (provider, name) in (routes or {}).items():
                if url.startswith(prefix):
                    fx = fixture(provider, name)
                    b = fx["body"]
                    raw = b.encode() if isinstance(b, str) else json.dumps(b).encode()
                    return fx["status"], fx.get("headers", {}), raw, url
            return 404, {}, b"no route", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        out = Terminal() if terminal else io.StringIO()
        with mock.patch.object(search_cmd, "_client", make_client):
            code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.dir)
        return code, out.getvalue()

    def test_readable_screen(self):
        code, out = self.call("-u", "--width", "110", terminal=True)
        self.assertEqual(code, 0, out)
        golden(self, "usage", out)
        self.assertEqual(out.count("Apify"), 1)          # one line per account
        self.assertIn("Out of service", out)
        self.assertIn("Web negatives: 2 index families usable (G, Ma)", out)

    def test_shortcut(self):
        self.assertEqual(self.call("-u"), self.call("usage"))

    def test_contract(self):
        code, out = self.call("usage")
        self.assertEqual(code, 0, out)
        self.assertIn("COUNTER=user", out)
        self.assertIn("- account=serpapi ready left=199 searches=199 renews=2026-11-01", out.splitlines())
        # quota show is the agents' command, unchanged
        self.assertTrue(self.call("quota", "show")[1].startswith("STATUS=OK\nPROVIDERS=23\n"))

    def test_filters(self):
        rows = json.loads(self.call("usage", "--ready", "--json")[1])["data"]["accounts"]
        self.assertTrue(all(r["state"] == "ready" for r in rows))
        rows = json.loads(self.call("usage", "--role", "last-resort", "--json")[1])["data"]["accounts"]
        self.assertEqual([r["account"] for r in rows], ["zenrows", "scraperapi", "apify"])
        everything = self.call("-u", "--all", "--width", "110", terminal=True)[1]
        self.assertIn("✗ Staan", everything)
        self.assertNotIn("Out of service", everything)

    def test_one_provider(self):
        code, out = self.call("usage", "serper")
        self.assertIn("RENEWS=first-use", out)
        self.assertIn("- source=https://serper.dev", out.replace("www.", ""))
        code, out = self.call("usage", "serpap")
        self.assertEqual(code, 2)
        self.assertIn("did you mean serpapi?", out)

    def test_families(self):
        code, out = self.call("usage", "--families")
        self.assertIn("FAMILIES=G,Ma", out)
        self.assertIn("- missing=Br brave (card-required: providers.allow_card_required)", out.splitlines())

    def test_csv_and_markdown(self):
        out = self.call("usage", "--csv")[1]
        self.assertTrue(out.startswith("account,name,section,state,"))
        self.assertIn("\napify,Apify,last-resort,ready,", out)
        self.assertTrue(self.call("usage", "--md")[1].startswith("| account | name |"))

    def test_sync_with_recorded_answers(self):
        routes = {"https://api.tavily.com/usage": ("tavily", "usage.json")}
        code, out = self.call("usage", "--sync", "--json", routes=routes)
        rows = {r["account"]: r for r in json.loads(out)["data"]["accounts"]}
        self.assertEqual(rows["tavily"]["source"], "provider")

    def test_advice(self):
        out = self.call("usage")[1]
        self.assertIn("- a key for Staan (STAAN_API_KEY) would add the index family E", out.splitlines())
        self.assertIn("- probandia -u --sync reads the balances from the accounts, at no cost", out.splitlines())

    def test_outside_a_project(self):
        out = io.StringIO()
        code = cli.main(["usage"], stdout=out, environ=self.env, cwd=self.tmp.name)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("COUNTER=user", out.getvalue())

    # T62: under 20 % of a quota left, the agents are told before the STOP

    RESEARCH = "2026-09-01-ancestors-of-louis-marchand"

    def tavily_at_12_percent(self):
        # 1,000 credits, 100 kept in reserve, 85 used: 695 more leave 120, 12 %
        Ledger(self.dir, catalogue.load(), clock=lambda: NOW).record("tavily", "search", 695)

    def test_a_quota_under_twenty_percent_is_said(self):
        self.tavily_at_12_percent()
        code, out = self.call("plan", self.RESEARCH)
        self.assertEqual(code, 0, out)
        self.assertIn("\nQUOTA_LOW=tavily:12%\n", out)
        code, out = self.call("digest", self.RESEARCH)
        self.assertIn("\n-   low: tavily 12% left\n", out)

    def test_nothing_is_said_above_it(self):
        code, out = self.call("plan", self.RESEARCH)
        self.assertEqual(code, 0, out)
        self.assertNotIn("QUOTA_LOW", out)
        self.assertNotIn("low:", self.call("digest", self.RESEARCH)[1])

    def test_alert(self):
        code, out = self.call("usage", "--alert", "20%")
        self.assertEqual(code, 0, out)
        self.assertEqual(out, "STATUS=OK\nTHRESHOLD=20%\n")
        self.tavily_at_12_percent()
        code, out = self.call("usage", "--alert", "20%")
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP\nTHRESHOLD=20%\nQUOTA_LOW=tavily:12%\nREASON=quota-low\n", out)
        self.assertEqual(self.call("usage", "--alert", "10")[0], 0)   # 12 % is above 10 %
        self.assertEqual(self.call("usage", "--alert")[0], 4)         # 20 % by default
        data = json.loads(self.call("usage", "--alert", "--json")[1])["data"]
        self.assertEqual(data["low"], [{"account": "tavily", "percent_left": 12}])
        self.assertEqual(self.call("usage", "--alert", "120%")[0], 2)

    def test_status_shows_the_lowest_accounts(self):
        code, out = self.call("status", "--json")
        lowest = json.loads(out)["data"]["lowest_accounts"]
        self.assertNotIn("Jina Reader", [r["account"] for r in lowest[:1]])
        self.assertEqual(lowest[0]["account"], "OpenWeb Ninja Real-Time Web Search")


class Forecast(unittest.TestCase):
    """T63: usage --forecast, on a ledger of 30 days at a simulated clock (CLI12-T4)."""

    NOW = datetime.datetime(2026, 10, 25, 12, 0, tzinfo=datetime.timezone.utc)

    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"SERPAPI_API_KEY": "k", **REUSE, "TAVILY_API_KEY": "k", "EXA_API_KEY": "k",
                    "PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "NO_COLOR": "1",
                    "PROBANDIA_PAGER": "none"}
        for patcher in (mock.patch.object(usage_cmd, "_now", return_value=self.NOW),
                        mock.patch("probandia.i18n.formats.local_time", return_value="2026-10-25 14:00")):
            patcher.start()
            self.addCleanup(patcher.stop)
        # 30 days: SerpApi at 2 searches a day, then 20 a day over the last 7; Tavily at 1 a day
        for back in range(30, 0, -1):
            day = self.NOW.replace(hour=9) - datetime.timedelta(days=back - 1)
            ledger = Ledger(self.dir, catalogue.load(), clock=lambda day=day: day, environ=self.env)
            ledger.record("serpapi", "search", 20 if back <= 7 else 2)
            ledger.record("tavily", "search", 1)

    def call(self, *argv, terminal=False):
        out = Terminal() if terminal else io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.dir)
        return code, out.getvalue()

    def test_serpapi_runs_out_on_the_right_day(self):
        # in October: 18 days at 2, then 7 at 20 = 176 used; 250 less 25 kept in reserve leaves 49,
        # at 20 a day: 2.45 days after 25 October at noon, the 27th
        code, out = self.call("usage", "--forecast")
        self.assertEqual(code, 0, out)
        self.assertIn("\nSOONEST=serpapi:2026-10-27\n", out)
        self.assertIn("- forecast=serpapi out 2026-10-27 left=49 per_day=20", out)
        # 875 left at 1 a day: it starts again first, on 1 November
        self.assertIn("- forecast=tavily renews 2026-11-01 left=875 per_day=1", out)
        self.assertIn("- forecast=exa idle left=9 per_day=0", out)

    def test_readable_and_json(self):
        code, out = self.call("usage", "--forecast", "--width", "100", terminal=True)
        self.assertEqual(code, 0, out)
        golden(self, "usage-forecast", out)
        rows = json.loads(self.call("usage", "--forecast", "--json")[1])["data"]["forecast"]
        self.assertEqual(rows[0], {"account": "serpapi", "name": "SerpApi", "unit": "search", "left": 49,
                                   "per_day": 20.0, "verdict": "out", "date": "2026-10-27"})


if __name__ == "__main__":
    unittest.main()
