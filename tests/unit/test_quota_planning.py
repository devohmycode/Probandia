import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, hooks
from probandia.ledger import Ledger, fit
from probandia.providers import catalogue
from probandia.providers.base import Result as R
from probandia.providers.fusion import NegativeCheck, fuse, is_hit, item_key, normalise_url
from probandia.providers.meter import Meter
from probandia.util import yamlio
from tests import REUSE, ROOT

FIXTURE_PROJECT = os.path.join(ROOT, "tests", "fixtures", "project")
RID = "2026-09-30-parents-of-victor-hugo"
UTC = datetime.timezone.utc


class Config:
    def __init__(self, **values):
        self.values = {"providers.enabled": list(catalogue.load()), "budget.reserve_percent": 10,
                       "providers.allow_card_required": False, "providers.allow_content_reuse": False}
        self.values.update({k.replace("__", "."): v for k, v in values.items()})

    def get(self, key):
        return self.values[key]


ALL_KEYS = {"SERPAPI_API_KEY": "k", "SERPER_API_KEY": "k", "SEARCHAPI_API_KEY": "k",
            "BRAVE_API_KEY": "k", "STAAN_API_KEY": "k", "EXA_API_KEY": "k", "PARALLEL_API_KEY": "k",
            "TAVILY_API_KEY": "k", "LINKUP_API_KEY": "k", "GEMINI_API_KEY": "k",
            "FIRECRAWL_API_KEY": "k", "OPENROUTER_API_KEY": "k",
            **REUSE}   # T217: Exa, Parallel, Tavily, Linkup


class Catalogue(unittest.TestCase):
    def test_values(self):
        cat = catalogue.load()
        self.assertEqual(cat["serpapi"]["free"], {"amount": 250, "period": "monthly", "reset": "billing"})
        self.assertEqual(cat["tavily"]["introspection"]["url"], "https://api.tavily.com/usage")
        self.assertEqual(cat["brave"]["cache_ttl"], 0)
        for pid, e in cat.items():
            self.assertIn(e["family"], catalogue.FAMILIES, pid)
            self.assertIsInstance(e["checked"], datetime.date, pid)

    def test_card_and_reuse_are_left_out_by_default(self):
        usable = catalogue.usable(Config(), ALL_KEYS)
        self.assertNotIn("brave", usable)
        self.assertNotIn("gemini_grounding", usable)
        self.assertIn("serpapi", usable)

    def test_and_put_back_by_the_settings(self):
        cfg = Config(providers__allow_card_required=True, providers__allow_content_reuse=True)
        usable = catalogue.usable(cfg, ALL_KEYS)
        self.assertIn("brave", usable)
        self.assertIn("gemini_grounding", usable)

    def test_missing_keys(self):
        usable = catalogue.usable(Config(), {})
        self.assertEqual(sorted(usable), ["jina", "marginalia"])  # keys optional

    def test_doctor_warns_past_ninety_days(self):
        from probandia import doctor
        r = doctor.run("claude-code", {})
        self.assertIn("CATALOGUE=", r.render_text())
        old = [(p, a) for p, a in catalogue.ages(today=datetime.date(2027, 2, 15)) if a > 90]
        self.assertEqual(len(old), len(catalogue.load()))


class Clock:
    def __init__(self, when):
        self.now = when

    def __call__(self):
        return self.now


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock(datetime.datetime(2026, 10, 15, 12, 0, tzinfo=UTC))
        self.ledger = Ledger(self.tmp.name, catalogue.load(), self.clock)

    def test_reserve_and_left(self):
        self.ledger.record("tavily", "search", 100)
        self.assertEqual(self.ledger.reserve("tavily", 10), 100)
        self.assertEqual(self.ledger.left("tavily", 10), 1000 - 100 - 100)

    def test_monthly_period_resets(self):
        self.ledger.record("tavily", "search", 500)
        self.clock.now = datetime.datetime(2026, 11, 2, tzinfo=UTC)
        self.assertEqual(self.ledger.used("tavily")[0], 0)

    def test_daily_period(self):
        self.ledger.record("openrouter", "complete", 30)
        self.assertEqual(self.ledger.left("openrouter", 0), 20)
        self.clock.now += datetime.timedelta(days=1)
        self.assertEqual(self.ledger.left("openrouter", 0), 50)

    def test_once_never_resets(self):
        self.ledger.record("serper", "search", 2000)
        self.clock.now += datetime.timedelta(days=400)
        self.assertEqual(self.ledger.used("serper")[0], 2000)

    def test_billing_period_from_the_provider(self):
        self.ledger.update_reported("firecrawl", left=900, period_start="2026-10-10T00:00:00Z")
        self.assertEqual(self.ledger.period_start("firecrawl"),
                         datetime.datetime(2026, 10, 10, tzinfo=UTC))
        self.clock.now = datetime.datetime(2026, 11, 12, tzinfo=UTC)
        self.assertEqual(self.ledger.period_start("firecrawl"),
                         datetime.datetime(2026, 11, 10, tzinfo=UTC))

    def test_billing_period_with_milliseconds_or_offset(self):
        # Firecrawl's live answer of 1 October 2026 carried milliseconds
        self.clock.now = datetime.datetime(2026, 10, 1, tzinfo=UTC)
        for given in ("2026-09-06T16:57:22.339Z", "2026-09-06T18:57:22+02:00"):
            self.ledger.update_reported("firecrawl", left=668, period_start=given)
            self.assertEqual(self.ledger.period_start("firecrawl"),
                             datetime.datetime(2026, 9, 6, 16, 57, 22, tzinfo=UTC), given)

    def test_reconcile_takes_the_larger_count_and_warns(self):
        self.ledger.record("tavily", "search", 10)
        self.ledger.update_reported("tavily", left=700)
        used, warning = self.ledger.used("tavily")
        self.assertEqual(used, 300)
        self.assertIn("provider count 300", warning)

    def test_429_marks_exhausted(self):
        self.ledger.mark_exhausted("staan", retry_after=3600)
        self.assertEqual(self.ledger.left("staan", 10), 0)
        self.clock.now += datetime.timedelta(hours=2)
        self.assertFalse(self.ledger.exhausted("staan"))
        until = self.ledger.mark_exhausted("staan")
        self.assertEqual(until, datetime.datetime(2026, 11, 1, tzinfo=UTC))

    def test_fit_moves_calls_and_stops(self):
        self.ledger.record("serpapi", "search", 220)        # 250 - 25 reserve: 5 left
        alloc = fit(self.ledger, {"serpapi": 8}, ["serpapi", "serper"], 10, ["serpapi", "serper"])
        self.assertEqual(alloc.kept, {"serpapi": 5, "serper": 3})
        self.assertEqual(alloc.moved, [("serpapi", "serper", 3)])
        self.ledger.record("serper", "search", 2250)
        self.ledger.record("serpapi", "search", 5)
        alloc = fit(self.ledger, {"serpapi": 1}, ["serpapi", "serper", "staan"], 10,
                    ["serpapi", "serper", "staan"])
        self.assertEqual(alloc.kept, {"staan": 1})
        alloc = fit(self.ledger, {"serpapi": 1}, ["serpapi", "serper"], 10, ["serpapi", "serper"])
        self.assertEqual(alloc.stop, ("serpapi", None))


def entry(pid, **values):
    return dict({"id": pid, "name": pid, "family": "G", "kind": "search", "keyword": True,
                 "card_required": False, "content_reuse": False}, **values)


def extended():
    """The catalogue, with a reader priced by tier and a fourth OpenWeb Ninja API
    (decision 1.2) placed apart, to check that they are listed together."""
    cat = dict(catalogue.load())
    cat["zenrows"] = entry("zenrows", family="opaque", kind="read", keyword=False, unit="credit",
                           auth={"param": "apikey", "env": "ZENROWS_API_KEY"},
                           costs={"read": 1, "read_js": 5, "read_premium": 10},
                           free={"amount": 50, "period": "monthly"},
                           limits={"timeout": 60, "max_units": 30})
    cat["openwebninja_forums"] = dict(cat["openwebninja_news"], id="openwebninja_forums")
    return cat


OWN = ["openwebninja_search", "openwebninja_news", "openwebninja_books"]


class Tiers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = extended()
        self.ledger = Ledger(self.tmp.name, self.cat)

    def test_a_tier_not_priced_costs_the_one_below(self):
        self.assertEqual(self.ledger.cost("zenrows", "read_js", 3), 15)
        self.assertEqual(self.ledger.cost("jina", "read_js"), 3000)
        self.assertEqual(self.ledger.cost("serpapi", "read_js"), 1)    # then search
        self.assertEqual(catalogue.tiers(self.cat["zenrows"]), ["read", "read_js"])  # never premium
        self.assertEqual(catalogue.tiers(self.cat["jina"]), ["read"])

    def test_fit_counts_the_tier(self):
        # 50 credits, 5 kept in reserve: 45 left
        alloc = fit(self.ledger, {"zenrows": 20}, ["zenrows"], 10, ["zenrows"], operation="read")
        self.assertEqual(alloc.kept, {"zenrows": 20})
        alloc = fit(self.ledger, {"zenrows": 20}, ["zenrows"], 10, ["zenrows"], operation="read_js")
        self.assertEqual((alloc.kept, alloc.dropped), ({"zenrows": 9}, {"zenrows": 11}))

    def test_a_call_never_gets_a_ceiling_beyond_the_quota_left(self):
        cfg = Config(providers__enabled=list(self.cat))
        meter = Meter(self.ledger, cfg, {"ZENROWS_API_KEY": "k"})
        self.assertEqual(meter.limits("zenrows", "read_js"), {"timeout": 60, "max_units": 30})
        self.ledger.record("zenrows", "read_js", 40)
        self.assertEqual(meter.limits("zenrows", "read_js"), {"timeout": 60, "max_units": 5})
        self.assertEqual(meter.refusal("zenrows", "read_js"), None)
        self.ledger.record("zenrows", "read", 1)
        self.assertEqual(meter.refusal("zenrows", "read_js"), "quota")   # 4 left, 5 needed
        self.assertEqual(meter.refusal("zenrows", "read"), None)


class Expiry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock(datetime.datetime(2026, 1, 10, 9, 0, tzinfo=UTC))
        self.ledger = Ledger(self.tmp.name, catalogue.load(), self.clock)

    def test_serper_credits_expire_six_months_after_the_first_use(self):
        self.assertFalse(self.ledger.expired("serper"))      # never used: no date yet
        self.ledger.record("serper", "search", 100)
        self.clock.now = datetime.datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
        self.assertEqual(self.ledger.left("serper", 10), 2500 - 100 - 250)
        self.assertEqual(self.ledger.period_end("serper"),
                         datetime.datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        self.clock.now = datetime.datetime(2026, 7, 10, 9, 0, tzinfo=UTC)
        self.assertTrue(self.ledger.expired("serper"))
        self.assertEqual(self.ledger.left("serper", 10), 0)

    def test_a_date_the_provider_reports_comes_first(self):
        self.ledger.update_reported("serper", period_start="2025-12-01T00:00:00Z")
        self.ledger.record("serper", "search", 1)
        self.clock.now = datetime.datetime(2026, 6, 1, tzinfo=UTC)
        self.assertTrue(self.ledger.expired("serper"))


class SharedKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = extended()
        self.ledger = Ledger(self.tmp.name, self.cat)
        self.meter = Meter(self.ledger, Config(providers__enabled=list(self.cat)),
                           {"OPENWEBNINJA_API_KEY": "k"})

    def test_the_entries_are_found_by_their_key(self):
        bing = {"SERPAPI_API_KEY": ["serpapi", "serpapi_bing"],   # one account, one quota
                "APIFY_TOKEN": ["apify", "apify_reader"]}
        self.assertEqual(catalogue.shared_keys(self.cat),
                         dict(bing, OPENWEBNINJA_API_KEY=OWN + ["openwebninja_forums"]))
        self.assertEqual(catalogue.shared_keys(), dict(bing, OPENWEBNINJA_API_KEY=OWN))

    def test_two_apis_run_out_apart(self):
        self.ledger.record("openwebninja_search", "search", 90)
        self.assertEqual(self.meter.refusal("openwebninja_search", "search"), "quota")
        self.assertIsNone(self.meter.refusal("openwebninja_news", "search"))
        self.assertEqual(self.ledger.left("openwebninja_news", 10), 90)
        self.ledger.mark_exhausted("openwebninja_news")
        self.assertTrue(self.ledger.exhausted("openwebninja_news"))
        self.assertFalse(self.ledger.exhausted("openwebninja_search"))
        self.assertEqual(self.ledger.used("openwebninja_news")[0], 0)

    def test_doctor_lists_the_balances_it_can_read(self):
        from probandia import doctor
        env = {"OPENWEBNINJA_API_KEY": "k", "ZENROWS_API_KEY": "k", "SCRAPERAPI_API_KEY": "k", "APIFY_TOKEN": "k"}
        r = doctor.run("claude-code", env)
        self.assertEqual(r.values["BALANCES"].split(","),
                         ["openwebninja_search", "openwebninja_news", "openwebninja_books", "zenrows",
                          "scraperapi", "apify", "apify_reader"])
        for key in env:
            self.assertIn(key, r.values["KEYS"])

    def test_doctor_checks_the_key_once(self):
        from probandia import doctor
        r = doctor.run("claude-code", {"OPENWEBNINJA_API_KEY": "k"}, cat=self.cat)
        self.assertEqual(r.values["KEYS"].split(",").count("OPENWEBNINJA_API_KEY"), 1)
        self.assertEqual(doctor.secret_variables(self.cat).count("OPENWEBNINJA_API_KEY"), 1)
        self.assertIn("OPENWEBNINJA_API_KEY: one key for 4 entries (openwebninja_search, "
                      "openwebninja_news, openwebninja_books, openwebninja_forums), present",
                      r.render_text())


class Project(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE_PROJECT, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_SESSION": "t"}

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def searches(self):
        return yamlio.load(os.path.join(self.dir, "families", "hugo", "index",
                                        "searches.yaml"))["searches"]


class HardStop(Project):
    def test_a_wave_beyond_the_free_quota_stops_before_the_call(self):
        env = {"SERPAPI_API_KEY": "k", "SERPER_API_KEY": "k"}
        self.assertEqual(self.call("quota", "add", "serpapi", "220", env=env)[0], 0)
        code, out = self.call("quota", "estimate", "serpapi", "--calls", "8", env=env)
        self.assertEqual(code, 4)
        self.assertIn("REASON=free-quota:serpapi", out)
        self.assertIn("ALTERNATIVE=serper", out)  # the next free provider, same family
        self.assertEqual(self.call("quota", "estimate", "serpapi", "--calls", "5", env=env)[0], 0)

    def test_show(self):
        code, out = self.call("quota", env={**REUSE, "TAVILY_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertIn("- provider=tavily ready used=0 of=1000 left=900 period=monthly", out)
        self.assertIn("- provider=brave card-required", out)


class NegativeStop(Project):
    """PRD criterion 3 for ``search --negative``: a negative asks one engine for several spellings of the
    name, one call each. The free quota is looked at before every call, not once before the wave."""

    ENV = {"SERPAPI_API_KEY": "k"}

    def setUp(self):
        super().setUp()
        from probandia.cli import search_cmd
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        self.sent = []

        def transport(method, url, headers, body, timeout):
            self.sent.append(url)
            if "serpapi.com" in url:
                fx = fixture("serpapi", "search-empty.json")
                return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url
            return 404, {}, b"", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        patcher = mock.patch.object(search_cmd, "_client", make_client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ledger(self):
        return Ledger(self.dir, catalogue.load(), environ=dict(self.env, **self.ENV))

    def serpapi_calls(self):
        return [u for u in self.sent if "serpapi.com" in u]

    def test_a_negative_stops_before_a_call_the_quota_does_not_pay(self):
        self.ledger().record("serpapi", "search", 224)    # 250 - 25 kept in reserve: 1 left
        self.assertEqual(self.ledger().left("serpapi", 10), 1)
        code, out = self.call("search", "Hugo Besançon", "--negative", env=self.ENV)
        self.assertEqual(len(self.serpapi_calls()), 1, out)   # the second spelling was not asked
        self.assertGreaterEqual(self.ledger().left("serpapi", 10), 0)   # the reserve is not eaten
        self.assertEqual(self.ledger().used("serpapi")[0], 225)
        self.assertNotIn("NEGATIVE=negative", out)   # a wave cut short proves no absence
        self.assertIn("free-quota", out)

    def test_two_units_left_and_a_wave_of_three(self):
        # PRD criterion 3 in its own numbers: 2 units left, a wave asks 3; it stops before the third call,
        # and the plan names the next free provider
        self.ledger().record("serpapi", "search", 223)    # 250 - 25 kept in reserve: 2 left
        env = dict(self.ENV, SERPER_API_KEY="k")
        code, out = self.call("quota", "estimate", "serpapi", "--calls", "3", env=env)
        self.assertEqual(code, 4, out)
        self.assertIn("ALTERNATIVE=serper", out)
        code, out = self.call("search", "Hugo Besançon", "--negative", env=self.ENV)
        self.assertEqual(len(self.serpapi_calls()), 2, out)
        self.assertEqual(self.ledger().left("serpapi", 10), 0)
        self.assertIn("free-quota", out)

    def test_a_negative_the_quota_pays_asks_every_spelling(self):
        code, out = self.call("search", "Hugo Besançon", "--negative", env=self.ENV)
        self.assertGreaterEqual(len(self.serpapi_calls()), 3, out)   # a wave of three spellings at least
        self.assertNotIn("free-quota", out)


class MonthlyCap(Project):
    """T53 (decision T7): providers.<id>.monthly_cap lowers the free tier; min of the two, stop in code 4."""

    ENV = {"SERPER_API_KEY": "k"}

    def setUp(self):
        super().setUp()
        self.assertEqual(self.call("config", "set", "providers.serper.monthly_cap", "2")[0], 0)
        ledger = Ledger(self.dir, catalogue.load(), environ=dict(self.env, **self.ENV))
        self.assertEqual(ledger.left("serper", 10), 2)   # 2500 credits once, 2 a month
        for _i in range(2):
            ledger.record("serper", "search", 1)

    def test_search_stops_before_the_call(self):
        code, out = self.call("search", "Hugo Besançon 1802", "--engine", "serper", env=self.ENV)
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP", out)
        self.assertIn("REASON=free-quota:serper", out)

    def test_quota_show_gives_the_cap(self):
        code, out = self.call("quota", "show", "serper", env=self.ENV)
        self.assertEqual(code, 0, out)
        self.assertIn("- provider=serper ready used=2 of=2500 cap=2/month left=0 period=once", out)

    def test_plan_removes_the_call(self):
        self.assertEqual(self.call("config", "set", "routing.birth", "serper")[0], 0)
        code, out = self.call("plan", RID, "--question-type", "birth", env=self.ENV)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"- removed=serper .* over-quota serper")
        self.assertNotIn("- estimate=serper", out)

    def test_the_usage_gauge_tops_at_the_cap(self):
        # the screen agrees with QUOTA_LOW and usage --alert: 0 left of the 2 the cap allows, not of 2,500
        from probandia import config
        from probandia.providers import accounts

        env = dict(self.env, **self.ENV)
        ledger = Ledger(self.dir, catalogue.load(), environ=env)
        cfg = config.load(self.dir, env, strict=False)
        serper = next(a for a in accounts.accounts(catalogue.load(), ledger, cfg, env, 10) if a["account"] == "serper")
        self.assertEqual((serper["cap"], serper["ceiling"], serper["fraction"]), (2, 2, 0.0))
        code, out = self.call("--output-format", "human", "usage", "--all", env=self.ENV)
        self.assertEqual(code, 0, out)
        line = next(x for x in out.splitlines() if "Serper" in x)
        self.assertIn(" 0 / 2 ", line)

    def test_whole_operations_left(self):
        # 900 credits of Tavily at 0.2 a page are 4,500 pages, not the 4,499 of a floating-point 900 // 0.2
        ledger = Ledger(self.dir, catalogue.load(), environ=self.env)
        self.assertEqual(ledger.operations("tavily", 10)["read"], 4500)
        self.assertEqual(ledger.operations("apify_reader", 10)["read"], 1730)   # 4.5 $ at 0.0026 (T217)
        self.assertEqual(fit(ledger, {"tavily": 4500}, ["tavily"], 10, ["tavily"], "read").kept, {"tavily": 4500})

    def test_a_cap_above_the_tier_changes_nothing(self):
        self.call("config", "set", "providers.serper.monthly_cap", "5000")
        ledger = Ledger(self.dir, catalogue.load(), environ=dict(self.env, **self.ENV))
        self.assertEqual(ledger.left("serper", 10), 2500 - 2 - 250)


class AutoSearch(Project):
    """T61: search --engine auto goes on to the next free provider of routing.general by itself."""

    ENV = {**REUSE, "TAVILY_API_KEY": "k", "EXA_API_KEY": "k"}

    def setUp(self):
        super().setUp()
        self.assertEqual(self.call("config", "set", "routing.general", "tavily,exa")[0], 0)
        self.sent, self.answers = [], {"https://api.tavily.com/search": ("tavily", "search-ok.json"),
                                       "https://api.exa.ai/search": ("exa", "search-ok.json")}
        from probandia.cli import search_cmd
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        def transport(method, url, headers, body, timeout):
            self.sent.append(url)
            provider, name = self.answers[url.split("?")[0]]
            fx = fixture(provider, name)
            b = fx["body"]
            return fx["status"], fx.get("headers", {}), (b if isinstance(b, str) else json.dumps(b)).encode(), url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        patcher = mock.patch.object(search_cmd, "_client", make_client)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ledger = Ledger(self.dir, catalogue.load(), environ=dict(self.env, **self.ENV))

    def search(self, *extra):
        return self.call("search", "Hugo Besançon 1802", "--max", "3", *extra, env=self.ENV)

    def test_a_used_up_quota_passes_to_the_next(self):
        self.ledger.record("tavily", "search", 1000)
        code, out = self.search()
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=OK\n"), out)
        self.assertIn("\nENGINES=exa\n", out)
        self.assertIn("\nEXHAUSTED=tavily\n", out)   # the contract says Tavily was used up
        self.assertEqual(self.sent, ["https://api.exa.ai/search"])

    def test_a_provider_that_answers_used_up_passes_too(self):
        self.answers["https://api.tavily.com/search"] = ("tavily", "error-429.json")
        code, out = self.search()
        self.assertEqual(code, 0, out)
        self.assertIn("\nENGINES=tavily,exa\n", out)
        self.assertIn("\nEXHAUSTED=tavily\n", out)
        self.assertEqual(self.sent[-1], "https://api.exa.ai/search")

    def test_the_first_with_quota_is_the_only_one_asked(self):
        code, out = self.search()
        self.assertIn("\nENGINES=tavily\n", out)
        self.assertNotIn("EXHAUSTED", out)
        self.assertEqual(self.sent, ["https://api.tavily.com/search"])

    def test_all_used_up_stops_before_any_call(self):
        self.ledger.record("tavily", "search", 1000)
        self.ledger.record("exa", "search", 10)
        code, out = self.search()
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP", out)
        self.assertIn("REASON=free-quota:tavily", out)
        self.assertEqual(self.sent, [])

    def test_a_named_engine_still_stops(self):
        self.ledger.record("tavily", "search", 1000)
        code, out = self.search("--engine", "tavily")
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=free-quota:tavily", out)
        self.assertEqual(self.sent, [])


class TiersAndPlatforms(Project):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(catalogue, "load", return_value=extended())
        patch.start()
        self.addCleanup(patch.stop)

    def test_estimate_by_tier(self):
        code, out = self.call("quota", "estimate", "zenrows", "--operation", "read_js", "--calls", "9")
        self.assertEqual(code, 0)
        self.assertIn("NEEDED=45", out)
        self.assertIn("OPERATION=read_js", out)
        code, out = self.call("quota", "estimate", "zenrows", "--operation", "read_js", "--calls", "10")
        self.assertEqual(code, 4)
        self.assertIn("REASON=free-quota:zenrows", out)
        self.assertEqual(self.call("quota", "estimate", "zenrows", "--operation", "read",
                                   "--calls", "10")[0], 0)

    def test_show_lists_the_apis_of_a_platform_together(self):
        code, out = self.call("quota", env={"OPENWEBNINJA_API_KEY": "k"})
        self.assertEqual(code, 0)
        lines = out.splitlines()
        head = lines.index("- platform=openwebninja key=OPENWEBNINJA_API_KEY entries="
                           "openwebninja_search,openwebninja_news,openwebninja_books,openwebninja_forums")
        for i, p in enumerate(OWN + ["openwebninja_forums"], start=1):
            self.assertTrue(lines[head + i].startswith(f"- provider={p} "), lines[head + i])
        self.assertEqual(out.count("platform=openwebninja"), 1)
        code, out = self.call("quota", "show", "openwebninja_news", env={"OPENWEBNINJA_API_KEY": "k"})
        self.assertIn("- platform=openwebninja", out)
        self.assertNotIn("provider=openwebninja_search", out)


class QuotaShow(Project):
    """What is left, in plain operations, with its source and its reset day."""

    def all_keys(self):
        return {e["auth"]["env"]: "k" for e in catalogue.load().values() if (e.get("auth") or {}).get("env")}

    def test_every_provider_fits_in_forty_lines(self):
        code, out = self.call("quota", env=self.all_keys())
        self.assertEqual(code, 0)
        self.assertLessEqual(len(out.splitlines()), 40)
        self.assertEqual(out.count("- provider="), len(catalogue.load()))

    def test_format(self):
        code, out = self.call("quota", env=self.all_keys())
        lines = out.splitlines()
        self.assertIn("- provider=firecrawl ready used=0 of=1000 left=900 period=monthly searches=450 pages=900 "
                      "source=local reset=", out)
        self.assertIn("- provider=zenrows ready used=0 of=5000 left=4500 period=monthly pages=4500 source=local", out)
        self.assertIn("- provider=searchapi ready used=0 of=100 left=90 period=once searches=90 source=local "
                      "reset=never", lines)
        # a one-off tier that expires: its day is known only after the first use
        self.assertIn("- provider=serper ready used=0 of=2500 left=2250 period=once searches=2250 source=local "
                      "reset=first-use+6m", lines)
        # in dollars the reserve is not rounded up: 10 % of 5 $ keeps 0.5 $
        self.assertIn("- provider=apify ready used=0 of=5 left=4.5 period=monthly searches=989 source=local", out)
        self.assertFalse(any("  " in line for line in lines))

    def test_the_providers_own_count_is_said(self):
        self.call("quota", "add", "zenrows", "100", env={"ZENROWS_API_KEY": "k"})
        ledger = Ledger(self.dir, catalogue.load(), environ=dict(self.env, ZENROWS_API_KEY="k"))
        ledger.update_reported("zenrows", left=4000)
        code, out = self.call("quota", "show", "zenrows", env={"ZENROWS_API_KEY": "k"})
        self.assertIn("left=3500 period=monthly pages=3500 source=provider", out)

    def test_a_plan_counts_the_pages_it_will_read(self):
        env = {"SERPAPI_API_KEY": "k", "FIRECRAWL_API_KEY": "k"}
        code, out = self.call("plan", RID, "--question-type", "birth", env=env)
        self.assertEqual(code, 0, out)
        # 6 searches (serpapi and marginalia, 3 each) × reading.per_search
        self.assertIn("READS=18", out)
        self.assertIn("- estimate=firecrawl 18 read", out)
        code, out = self.call("plan", RID, "--question-type", "birth", env=dict(env, JINA_API_KEY="k"))
        self.assertIn("- estimate=firecrawl 18 read", out)   # T256: the ladder's order, Jina after Firecrawl
        self.assertNotIn("estimate=jina", out)
        code, out = self.call("plan", RID, "--question-type", "birth", env={"SERPAPI_API_KEY": "k"})
        self.assertIn("READS=18", out)
        self.assertNotIn(" read\n", out)   # Jina without a key draws on no quota


class Fusion(unittest.TestCase):
    def r(self, url, provider, family, rank, title="x", snippet=""):
        return R(title, url, snippet, None, provider, family, rank)

    def test_urls(self):
        self.assertEqual(normalise_url("http://WWW.Example.org/a/?utm_source=x&b=1#top"),
                         "https://example.org/a?b=1")
        self.assertEqual(item_key("https://gallica.bnf.fr/ark:/12148/bpt6k123/f4.item"),
                         item_key("https://gallica.bnf.fr/iiif/ark:/12148/bpt6k123/f4/full/full/0/native.jpg"))

    def test_three_engines_come_first(self):
        lists = {
            "serpapi": [self.r("https://a.org/x", "serpapi", "G", 1), self.r("https://b.org/y", "serpapi", "G", 2)],
            "staan": [self.r("https://www.b.org/y/", "staan", "E", 3)],
            "marginalia": [self.r("http://b.org/y", "marginalia", "Ma", 5)],
        }
        merged = fuse(lists)
        self.assertEqual(normalise_url(merged[0]["url"]), "https://b.org/y")
        self.assertEqual(merged[0]["providers"], ["serpapi", "staan", "marginalia"])
        self.assertAlmostEqual(merged[0]["score"], 1 / 62 + 1 / 63 + 1 / 65)

    def test_hits(self):
        self.assertTrue(is_hit(self.r("u", "p", "G", 1, "Famille TRÉBUCHET", "née à Nantes"),
                               ["Trebuchet"], ["Nantes"]))
        self.assertFalse(is_hit(self.r("u", "p", "G", 1, "Famille Trebuchet", "Paris"), ["Trebuchet"],
                                ["Nantes"]))
        self.assertFalse(is_hit(self.r("u", "p", "G", 1, "Trebuchets", ""), ["Trebuchet"]))

    def test_negative_needs_two_keyword_families(self):
        n = NegativeCheck(2)
        n.add("serpapi", "G", True, [], names=["Hugo"])
        n.add("serper", "G", True, [], names=["Hugo"])
        self.assertEqual(n.result, "failed")  # one family only
        n.add("staan", "E", True, [], names=["Hugo"])
        self.assertEqual(n.result, "negative")
        n.add("tavily", "opaque", False, [], names=["Hugo"])
        self.assertEqual(n.result, "negative")

    def test_a_failure_prevents_the_negative(self):
        n = NegativeCheck(2)
        n.add("serpapi", "G", True, [], names=["Hugo"])
        n.add("staan", "E", True, [], names=["Hugo"])
        n.add("marginalia", "Ma", True, failure="503")
        self.assertEqual(n.result, "failed")
        self.assertIn("marginalia: 503", n.reasons())

    def test_a_hit_is_a_positive(self):
        n = NegativeCheck(2)
        n.add("serpapi", "G", True, [self.r("u", "serpapi", "G", 1, "Victor Hugot 1802")],
              names=["Hugo", "Hugot"])
        self.assertEqual(n.result, "positive")

    def test_an_unrelated_answer_is_a_failure_not_an_absence(self):
        # recorded live: Bing answered a name and a place with pages about ChatGPT
        with open(os.path.join(ROOT, "tests", "fixtures", "http", "serpapi_bing", "search-ok.json"),
                  encoding="utf-8") as fh:
            items = json.load(fh)["body"]["organic_results"]
        bing = [self.r(i["link"], "serpapi_bing", "B", i["position"], i["title"], i.get("snippet", ""))
                for i in items]
        n = NegativeCheck(2)
        n.add("serpapi", "G", True, [], names=["Hugo"], places=["Besançon"])
        n.add("serpapi_bing", "B", True, bing, names=["Hugo"], places=["Besançon"])
        self.assertEqual(n.result, "failed")       # one family left: G
        self.assertEqual(n.families, {"G"})
        self.assertIn("serpapi_bing: unrelated answer, not counted", n.reasons())
        n.add("staan", "E", True, [], names=["Hugo"], places=["Besançon"])
        self.assertEqual(n.result, "negative")     # another family carries it

    def test_an_answer_about_the_place_still_counts(self):
        n = NegativeCheck(2)
        n.add("serpapi", "G", True, [self.r("u", "serpapi", "G", 1, "Archives de Besançon")],
              names=["Hugo"], places=["Besançon"])
        n.add("staan", "E", True, [], names=["Hugo"], places=["Besançon"])
        self.assertEqual(n.result, "negative")


class NativeSearchHook(Project):
    def payload(self, query="Hugo Besançon 1802", urls=("https://a.org/1", "https://b.org/2")):
        return {"session_id": "s", "cwd": self.dir, "hook_event_name": "PostToolUse",
                "tool_name": "WebSearch", "tool_input": {"query": query},
                "tool_response": {"results": [{"content": [{"title": "t", "url": u} for u in urls]}]}}

    def test_each_native_search_is_logged_as_opaque(self):
        before = len(self.searches())
        for q in ("Hugo Besançon 1802", "Hugot Nancy"):
            out = hooks.run("log", io.StringIO(json.dumps(self.payload(q))),
                            {"CLAUDECODE": "1", "PROBANDIA_SESSION": "t"})
            self.assertEqual(out, "")
        entries = self.searches()[before:]
        self.assertEqual([e["query"] for e in entries], ["Hugo Besançon 1802", "Hugot Nancy"])
        for e in entries:
            self.assertEqual((e["kind"], e["family"], e["engine"]), ("native", "opaque", "native:claude-code"))
            self.assertEqual(e["results"], 2)

    def test_a_native_zero_is_never_a_negative(self):
        hooks.run("log", io.StringIO(json.dumps(self.payload("Zzyzx", ()))), {"CLAUDECODE": "1"})
        code, out = self.call("known", RID, "--names", "Zzyzx")
        self.assertIn("NEGATIVES=0", out)

    def test_other_tools_and_outside_a_project_are_ignored(self):
        before = len(self.searches())
        p = self.payload()
        p["tool_name"] = "Bash"
        hooks.run("log", io.StringIO(json.dumps(p)), {})
        p = self.payload()
        p["cwd"] = self.tmp.name
        self.assertEqual(hooks.run("log", io.StringIO(json.dumps(p)), {}), "")
        self.assertEqual(len(self.searches()), before)
        self.assertEqual(hooks.run("log", io.StringIO("not json"), {}), "")

    def test_log_native_command(self):
        urls = os.path.join(self.tmp.name, "urls.txt")
        with open(urls, "w") as fh:
            fh.write("https://a.org/1\nhttps://b.org/2\nhttps://c.org/3\n")
        code, out = self.call("search", "--log-native", "--engine", "native:codex", "--query",
                              "Hugo Nancy", "--results", "3", "--urls-file", urls)
        self.assertEqual(code, 0, out)
        last = self.searches()[-1]
        self.assertEqual((last["engine"], last["family"], last["results"]), ("native:codex", "opaque", 3))


class Planner(Project):
    def test_birth_in_besancon_around_1802(self):
        env = {k: "k" for k in ("SERPAPI_API_KEY", "STAAN_API_KEY")}
        code, out = self.call("plan", RID, "--question-type", "birth", env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("TYPE=birth", out)
        self.assertIn("WINDOW=1797-1807", out)
        self.assertIn("- names=Hugo, Hugot, Hugues, ", out)  # attested forms first
        self.assertIn("- places=Besançon, Bisanz, Vesontio", out)  # with its old names
        self.assertIn("- record_types=birth, baptism", out)
        self.assertIn("- estimate=serpapi 3", out)
        self.assertIn('- removed=openarchives "Hugo Besançon" birth known-fact victor-hugo-1802.birth', out)
        self.assertIn('- removed=openarchives "Hugo Besançon" baptism valid-negative '
                      's-01J9ZK5A000000000000000001', out)
        plan = yamlio.load(os.path.join(self.dir, "families", "hugo", "research", RID, "work", "plan-2.yaml"))
        reasons = {c["reason"] for c in plan["removed"]}
        self.assertIn("known-fact", reasons)
        self.assertIn("valid-negative", reasons)

    def test_providers_without_a_key_are_removed(self):
        code, out = self.call("plan", RID, "--question-type", "birth", env={"SERPAPI_API_KEY": "k"})
        # token-economy C6: counted in REMOVED=, listed only in the plan file (DETAILS=)
        self.assertNotIn("unusable", out)
        self.assertNotIn("REMOVED=0\n", out)
        plan = yamlio.load(os.path.join(self.dir, "families", "hugo", "research", RID, "work", "plan-2.yaml"))
        self.assertIn(("staan", "unusable"), {(c["engine"], c["reason"]) for c in plan["removed"]})
        self.assertIn("- estimate=serpapi 3", out)

    def test_the_plan_follows_the_open_hypothesis(self):
        # live, 2 October 2026: pass 3 of the sample research planned MARCHAND without a
        # place, while its open lead was the father of Louise PERRIN at Les Ormes
        sample = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), sample)
        rid = "2026-09-01-ancestors-of-louis-marchand"
        out = io.StringIO()
        cli.main(["plan", rid], stdout=out, environ=dict(self.env, SERPAPI_API_KEY="k"), cwd=sample)
        out = out.getvalue()
        self.assertIn("FOCUS=hypothesis h-father-of-louise-perrin", out)
        self.assertIn("TYPE=parents", out)
        self.assertIn("WINDOW=1813-1823", out)             # Louise's birth, about 1818
        self.assertIn("- names=PERRIN", out)
        self.assertIn("Les Ormes", out.split("- places=")[1].splitlines()[0])
        self.assertIn("[louise-perrin-1818]", out)
        # a hypothesis another research of the family opened is never this one's focus
        from probandia import events
        other = os.path.join(sample, "families", "marchand", "research", "2026-10-01-other", "events.jsonl")
        os.makedirs(os.path.dirname(other))
        with open(os.path.join(os.path.dirname(other), "research.yaml"), "w", encoding="utf-8") as fh:
            fh.write("schema: 1\nid: 2026-10-01-other\nfamily: marchand\nquestion: x\n")
        events.append(other, [events.make("hypothesis.opened", {"hypothesis": {"id": "h-father-of-louise-perrin"}},
                                          {"harness": "cli", "agent": "session"}, 1, ["h-father-of-louise-perrin"])])
        out = io.StringIO()
        cli.main(["plan", rid], stdout=out, environ=dict(self.env, SERPAPI_API_KEY="k"), cwd=sample)
        self.assertIn("FOCUS=question", out.getvalue())
        out = io.StringIO()
        cli.main(["plan", rid, "--focus", "Où est né Louis MARCHAND ?"], stdout=out,
                 environ=dict(self.env, SERPAPI_API_KEY="k"), cwd=sample)
        self.assertIn("FOCUS=argument", out.getvalue())
        self.assertIn("- names=MARCHAND", out.getvalue())

    def test_an_imported_hypothesis_about_someone_else_is_no_focus(self):
        # T175: a workshop's hypothesis on another person's death took the plan of a question on a burial
        sample = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), sample)
        rid = "2026-09-01-ancestors-of-louis-marchand"
        path = os.path.join(sample, "families", "marchand", "research", rid, "research.yaml")
        meta = yamlio.load(path)
        meta["questions"] = [{"id": "Q1", "text": meta["question"], "type": "parents", "status": "open",
                              "persons": ["louis-marchand-1898"]}]
        yamlio.dump(path, meta)
        path = os.path.join(sample, "families", "marchand", "index", "hypotheses.yaml")
        doc = yamlio.load(path)
        doc["hypotheses"].append({"id": "h-zoe-martin-1900-death", "question": "Where did Zoé MARTIN die?",
                                  "hypotheses": [{"id": "a", "statement": "Paris", "status": "open"}],
                                  "evidence": [{"ref": "zoe-martin-1900.death", "marks": {"a": "neutral"}}],
                                  "discriminating": None, "opened": "2026-09-30", "closed": None, "outcome": None})
        yamlio.dump(path, doc)
        out = io.StringIO()
        cli.main(["plan", rid], stdout=out, environ=dict(self.env, SERPAPI_API_KEY="k"), cwd=sample)
        self.assertIn("FOCUS=hypothesis h-father-of-louise-perrin", out.getvalue())

    def test_type_detection(self):
        from probandia.planner import detect_type
        self.assertEqual(detect_type("Who were the parents of Victor Hugo?"), "parents")
        self.assertEqual(detect_type("Quand est né Jean Martin ?"), "birth")
        self.assertEqual(detect_type("Wann ist er gestorben?"), "death")
        self.assertEqual(detect_type("Où habitait la famille en 1900 ?"), "residence")
