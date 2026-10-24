import datetime
import json
import os
import tempfile
import unittest
import urllib.parse

from probandia.ledger import Ledger
from probandia.providers import fusion
from probandia.providers import adapters, catalogue
from probandia.providers.base import ProviderError, Query
from probandia.util.http import Client
from tests import REUSE, ROOT

HTTP = os.path.join(ROOT, "tests", "fixtures", "http")
SEARCH_PROVIDERS = ["serpapi", "serpapi_bing", "serper", "searchapi", "brave", "staan", "marginalia", "exa",
                    "parallel", "tavily", "linkup", "gemini_grounding", "jina", "firecrawl",
                    "openwebninja_search", "openwebninja_news", "openwebninja_books"]
SYNC_PROVIDERS = {"serpapi_bing": "account.json", "zenrows": "details.json",
                  "scraperapi": "account.json", "apify": "limits.json", "tavily": "usage.json", "linkup": "usage.json", "firecrawl": "usage.json",
                  "openrouter": "key.json", "serpapi": "account.json", "serper": "account.json",
                  "searchapi": "account.json", "openwebninja_search": "usage.json",
                  "openwebninja_news": "usage.json", "openwebninja_books": "usage.json"}


def fixture(provider, name):
    with open(os.path.join(HTTP, provider, name), encoding="utf-8") as fh:
        return json.load(fh)


class Replay:
    """Answers every call with one recorded response, and keeps what was sent."""

    def __init__(self, fx):
        self.fx = fx
        self.sent = []

    def __call__(self, method, url, headers, body, timeout):
        if url.endswith("/robots.txt"):
            return 200, {}, b"", url
        self.sent.append((method, url, headers, body))
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
        b = self.fx["body"]
        raw = b.encode("utf-8") if isinstance(b, str) else json.dumps(b).encode("utf-8")
        return self.fx["status"], self.fx.get("headers", {}), raw, url


def client(fx, tmp):
    return Client(tmp, None, None, Replay(fx), sleep=lambda s: None)


ENV = {k: "test-key" for k in ("SERPAPI_API_KEY", "SERPER_API_KEY", "SEARCHAPI_API_KEY",
                               "BRAVE_API_KEY", "STAAN_API_KEY", "MARGINALIA_API_KEY", "EXA_API_KEY",
                               "PARALLEL_API_KEY", "TAVILY_API_KEY", "LINKUP_API_KEY",
                               "GEMINI_API_KEY", "JINA_API_KEY", "FIRECRAWL_API_KEY",
                               "OPENROUTER_API_KEY", "OPENWEBNINJA_API_KEY", "ZENROWS_API_KEY",
                               "SCRAPERAPI_API_KEY", "APIFY_TOKEN")}
QUERY = Query(text='"Hugo" Besançon 1802', max=5)


def available(provider):
    return provider in adapters.REGISTRY and os.path.isdir(os.path.join(HTTP, provider))


class Adapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def run_search(self, provider, name):
        fx = fixture(provider, name)
        c = client(fx, self.tmp.name)
        ad = adapters.make(provider, c, self.cat[provider], ENV)
        ad.now = lambda: 0.0
        return ad.search(QUERY), c.transport.sent, fx

    def test_every_provider_has_an_adapter_and_fixtures(self):
        for p in SEARCH_PROVIDERS:
            with self.subTest(provider=p):
                self.assertIn(p, adapters.REGISTRY)
                for name in ("search-ok.json", "error-401.json", "error-429.json"):
                    self.assertTrue(os.path.isfile(os.path.join(HTTP, p, name)), name)

    def test_results(self):
        for p in SEARCH_PROVIDERS:
            if not available(p):
                continue
            with self.subTest(provider=p):
                (results, usage), sent, fx = self.run_search(p, "search-ok.json")
                self.assertGreater(len(results), 0)
                for i, r in enumerate(results, start=1):
                    self.assertTrue(r.url.startswith("http"), r)
                    self.assertEqual((r.provider, r.family, r.rank), (p, self.cat[p]["family"], i))
                self.assertGreater(usage.units, 0)
                method, url, headers, body = sent[0]
                expected = fx["request"]
                self.assertEqual(method, expected["method"])
                self.assertEqual(urllib.parse.urlsplit(url)[:3],
                                 urllib.parse.urlsplit(expected["url"])[:3])

    def test_empty_answers_are_empty_lists(self):
        for p in SEARCH_PROVIDERS:
            if not available(p) or not os.path.isfile(os.path.join(HTTP, p, "search-empty.json")):
                continue
            with self.subTest(provider=p):
                (results, usage), _s, _f = self.run_search(p, "search-empty.json")
                self.assertEqual(results, [])

    def test_errors_raise(self):
        for p in SEARCH_PROVIDERS:
            if not available(p):
                continue
            for name in ("error-401.json", "error-429.json", "error-402.json", "error-503.json"):
                if not os.path.isfile(os.path.join(HTTP, p, name)):
                    continue
                with self.subTest(provider=p, case=name):
                    with self.assertRaises(ProviderError) as cm:
                        self.run_search(p, name)
                    self.assertEqual(cm.exception.status, fixture(p, name)["status"])
                    self.assertLessEqual(len(cm.exception.excerpt), 200)

    def test_an_unexpected_answer_is_an_error_not_an_empty_list(self):
        for p in SEARCH_PROVIDERS:
            if not available(p):
                continue
            with self.subTest(provider=p):
                fx = {"status": 200, "headers": {"Content-Type": "application/json"},
                      "body": {"unexpected": True}}
                ad = adapters.make(p, client(fx, self.tmp.name), self.cat[p], ENV)
                with self.assertRaises(ProviderError):
                    ad.search(QUERY)

    def test_readers(self):
        for p, name in (("jina", "read-ok.json"), ("firecrawl", "scrape-ok.json")):
            with self.subTest(provider=p):
                fx = fixture(p, name)
                ad = adapters.make(p, client(fx, self.tmp.name), self.cat[p], ENV)
                page, usage = ad.read(fx["request"]["json"]["url"] if fx["request"].get("json")
                                      else "https://example.org/")
                self.assertGreater(len(page.text), 100)
                self.assertGreater(usage.units, 0)


class Sync(unittest.TestCase):
    def test_introspection(self):
        cat = catalogue.load()
        for p, name in SYNC_PROVIDERS.items():
            if p not in adapters.SYNC:
                continue
            with self.subTest(provider=p):
                tmp = tempfile.mkdtemp()
                fx = fixture(p, name)
                ledger = Ledger(tmp, cat)
                info = adapters.sync(p, client(fx, tmp), cat[p], ENV, ledger)
                self.assertIsNotNone(info["left"])
                self.assertEqual(ledger.state()[ledger.pool(p)]["reported_left"], info["left"])

    def test_values(self):
        cat = catalogue.load()
        tmp = tempfile.mkdtemp()
        tavily = adapters.sync("tavily", client(fixture("tavily", "usage.json"), tmp), cat["tavily"],
                               ENV, Ledger(tmp, cat))
        self.assertEqual(tavily["left"], 500)  # plan_limit 1000 - plan_usage 500
        fc = adapters.sync("firecrawl", client(fixture("firecrawl", "usage.json"), tmp),
                           cat["firecrawl"], ENV, Ledger(tmp, cat))
        self.assertEqual((fc["left"], fc["period_start"]), (1000.0, "2026-10-01T00:00:00Z"))

    def test_exhausted_answers(self):
        self.assertTrue(adapters.exhausted_status("tavily", 432, ""))
        self.assertTrue(adapters.exhausted_status("linkup", 429, '{"code": "INSUFFICIENT_FUNDS_CREDITS"}'))
        self.assertTrue(adapters.exhausted_status("firecrawl", 402, ""))
        self.assertFalse(adapters.exhausted_status("serpapi", 401, ""))


class OpenWebNinja(unittest.TestCase):
    """Answers built from the documentation, not recorded live: see their ``note``."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def search(self, provider, fx):
        c = client(fx, self.tmp.name)
        return adapters.make(provider, c, self.cat[provider], ENV).search(QUERY), c.transport.sent

    def test_one_key_sent_as_x_api_key(self):
        for p in ("openwebninja_search", "openwebninja_news", "openwebninja_books"):
            with self.subTest(provider=p):
                (results, usage), sent = self.search(p, fixture(p, "search-ok.json"))
                self.assertEqual(sent[0][2].get("x-api-key"), "test-key")
                self.assertEqual(usage.units, 1)
                # web and news recorded live; books built from the documentation (it answered no book live)
                self.assertTrue(fixture(p, "search-ok.json")["note"].startswith(
                    "not a live answer" if p == "openwebninja_books" else "recorded live"))

    def test_fields_of_each_api(self):
        (web, _u), sent = self.search("openwebninja_search", fixture("openwebninja_search", "search-ok.json"))
        self.assertEqual(web[0].url, "https://familytree.example.org/wiki/Hugo-1802")
        self.assertIn("q=%22Hugo%22", sent[0][1])
        (news, _u), sent = self.search("openwebninja_news", fixture("openwebninja_news", "search-ok.json"))
        self.assertEqual(news[0].date, "2026-08-10T07:00:00.000Z")
        self.assertIn("query=", sent[0][1])
        (books, _u), _s = self.search("openwebninja_books", fixture("openwebninja_books", "search-ok.json"))
        self.assertEqual((books[0].url, books[0].snippet),
                         ("https://books.google.com/books?id=V_l_CwAAQBAJ", "P. Durand · 1895"))

    def test_an_empty_books_answer_is_a_failure(self):
        fx = fixture("openwebninja_books", "search-empty-live.json")    # live: no book for "genealogy"
        self.assertEqual(fx["body"]["data"], [])
        with self.assertRaises(ProviderError) as cm:
            self.search("openwebninja_books", fx)
        self.assertIn("empty answer is not trusted", str(cm.exception))

    def test_books_as_a_bare_list(self):
        # the API page shows the books answer without its envelope
        fx = fixture("openwebninja_books", "search-ok.json")
        fx = dict(fx, body=fx["body"]["data"])
        (books, _u), _s = self.search("openwebninja_books", fx)
        self.assertEqual(len(books), 1)

    def test_an_error_status_in_a_200_is_an_error(self):
        fx = {"status": 200, "headers": {}, "body": {"status": "ERROR", "error": {"message": "x"}}}
        with self.assertRaises(ProviderError):
            self.search("openwebninja_news", fx)

    def test_usage_of_one_api(self):
        ledger = Ledger(self.tmp.name, self.cat)
        fx = fixture("openwebninja_news", "usage.json")
        c = client(fx, self.tmp.name)
        info = adapters.sync("openwebninja_news", c, self.cat["openwebninja_news"], ENV, ledger)
        # recorded live, the day the free plan was taken
        self.assertEqual((info["left"], info["used"], info["period_start"], info["period_end"]),
                         (100.0, 0, "2026-10-02T13:32:00.000Z", "2026-11-02T13:32:00.000Z"))
        self.assertEqual(c.transport.sent[0][1], "https://api.openwebninja.com/usage?api_id=realtime_news_data")
        self.assertNotIn("openwebninja_search", ledger.state())   # the other APIs are untouched

    def test_an_exceeded_quota_has_nothing_left(self):
        ledger = Ledger(self.tmp.name, self.cat)
        info = adapters.sync("openwebninja_news", client(fixture("openwebninja_news", "usage-exceeded.json"),
                                                          self.tmp.name),
                             self.cat["openwebninja_news"], ENV, ledger)
        self.assertEqual(info["left"], 0)
        self.assertLessEqual(ledger.left("openwebninja_news", 10), 0)
        self.assertEqual(ledger.left("openwebninja_search", 10), 90)

    def test_an_api_not_subscribed_says_so(self):
        fx = fixture("openwebninja_search", "error-403-not-subscribed.json")     # recorded live
        with self.assertRaises(ProviderError) as cm:
            self.search("openwebninja_search", fx)
        self.assertIn("not subscribed", str(cm.exception))
        self.assertFalse(adapters.exhausted_status("openwebninja_search", 403, json.dumps(fx["body"])))
        ledger = Ledger(self.tmp.name, self.cat)
        with self.assertRaises(ProviderError) as cm:
            adapters.sync("openwebninja_news", client(fixture("openwebninja_news", "usage-not-subscribed.json"),
                                                      self.tmp.name), self.cat["openwebninja_news"], ENV, ledger)
        self.assertIn("app.openwebninja.com", str(cm.exception))

    def test_exhausted_answers(self):
        body = json.dumps(fixture("openwebninja_search", "error-429.json")["body"])
        self.assertTrue(adapters.exhausted_status("openwebninja_search", 429, body))
        self.assertTrue(adapters.exhausted_status("openwebninja_books", 403, '{"message": "Quota exceeded"}'))
        self.assertFalse(adapters.exhausted_status("openwebninja_books", 403, '{"message": "Forbidden"}'))
        self.assertFalse(adapters.exhausted_status("openwebninja_news", 401, body))


def epoch(text):
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=datetime.timezone.utc).timestamp()


class SerpApiEngines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def units_at(self, provider, now, name="search-ok.json"):
        ad = adapters.make(provider, client(fixture(provider, name), self.tmp.name),
                           self.cat[provider], ENV)
        ad.now = lambda: now
        return ad.search(QUERY)[1].units

    def test_a_search_served_from_the_cache_is_free(self):
        made = epoch("2026-10-01 08:12:44")    # search_metadata.created_at of the fixture
        self.assertEqual(self.units_at("serpapi", made + 5), 1)          # just made
        self.assertEqual(self.units_at("serpapi", made + 600), 0)        # kept by the cache
        self.assertEqual(self.units_at("serpapi", made + 2 * 3600), 1)   # past the hour

    def test_the_live_repeat_of_a_search_was_free(self):
        # recorded live: asked again 72 s later, SerpApi counted one search only
        fx = fixture("serpapi_bing", "search-cached.json")
        self.assertEqual(fx["body"]["search_metadata"]["created_at"], "2026-10-02 11:06:18 UTC")
        self.assertEqual(self.units_at("serpapi_bing", epoch("2026-10-02 11:06:18") + 72, "search-cached.json"), 0)

    def test_bing_is_a_family_of_its_own_on_the_same_account(self):
        c = client(fixture("serpapi_bing", "search-ok.json"), self.tmp.name)
        ad = adapters.make("serpapi_bing", c, self.cat["serpapi_bing"], ENV)
        ad.now = lambda: 0.0
        results, usage = ad.search(QUERY)
        self.assertIn("engine=bing", c.transport.sent[0][1])
        # live: Bing answered this exact query with pages about ChatGPT, none naming Hugo
        self.assertEqual(results[0].url, "https://chatgpt.com/")
        self.assertEqual({r.family for r in results}, {"B"})
        self.assertIn("B", fusion.KEYWORD_FAMILIES)
        ledger = Ledger(self.tmp.name, self.cat)
        ledger.record("serpapi_bing", "search", 10)
        ledger.record("serpapi", "search", 5)
        self.assertEqual(ledger.left("serpapi", 10), 250 - 15 - 25)
        self.assertEqual(ledger.left("serpapi_bing", 10), 250 - 15 - 25)
        ledger.mark_exhausted("serpapi_bing", retry_after=60)
        self.assertTrue(ledger.exhausted("serpapi"))


class ZenRows(unittest.TestCase):
    """Answers built from the documentation, not recorded live: see their ``note``."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def reader(self, name):
        c = client(fixture("zenrows", name), self.tmp.name)
        return adapters.make("zenrows", c, self.cat["zenrows"], ENV), c.transport.sent

    def test_plain_read(self):
        ad, sent = self.reader("read-ok.json")
        page, usage = ad.read("https://en.wikipedia.org/wiki/Luxembourg_City")
        self.assertIn("Luxembourg City", page.text)
        self.assertEqual((page.status, usage.units, page.final_url),
                         (200, 1, "https://en.wikipedia.org/wiki/Luxembourg_City"))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(sent[0][1]).query)
        self.assertEqual((query["response_type"], query.get("js_render")), (["markdown"], None))

    def test_javascript_tier(self):
        ad, sent = self.reader("read-js-ok.json")
        _page, usage = ad.read("https://example.org/registre-1851", "read_js")
        self.assertEqual(usage.units, 5)
        self.assertIn("js_render=true", sent[0][1])

    def test_a_page_gone_is_billed(self):
        ad, _sent = self.reader("read-404.json")
        page, usage = ad.read("https://example.org/registre-1851")
        self.assertEqual((page.status, usage.units), (404, 1))

    def test_a_blocked_page_is_an_error(self):
        ad, _sent = self.reader("error-422.json")
        with self.assertRaises(ProviderError) as cm:
            ad.read("https://example.org/registre-1851")
        self.assertEqual(cm.exception.status, 422)

    def test_anti_bot_options_are_refused_before_any_call(self):
        ad, sent = self.reader("read-ok.json")
        for kw in ({"premium_proxy": True}, {"proxy_country": "fr"}, {"mode": "auto"}):
            with self.subTest(option=kw), self.assertRaises(adapters.AntiBotRefused):
                ad.read("https://example.org/", **kw)
        with self.assertRaises(adapters.AntiBotRefused):
            ad.read("https://example.org/", "read_premium")
        self.assertEqual(sent, [])

    def test_quota(self):
        body = json.dumps(fixture("zenrows", "error-402.json")["body"])
        self.assertTrue(adapters.exhausted_status("zenrows", 402, body))
        body = json.dumps(fixture("zenrows", "error-429.json")["body"])
        self.assertFalse(adapters.exhausted_status("zenrows", 429, body))   # concurrency
        ledger = Ledger(self.tmp.name, self.cat)
        info = adapters.sync("zenrows", client(fixture("zenrows", "details.json"), self.tmp.name),
                             self.cat["zenrows"], ENV, ledger)
        self.assertEqual((info["left"], info["period_start"]), (4998.0, "2026-10-02T05:51:02Z"))


class Routes:
    """One recorded response per URL part, the first that matches; every call kept."""

    def __init__(self, routes):
        self.routes = routes
        self.sent = []

    def __call__(self, method, url, headers, body, timeout):
        if url.endswith("/robots.txt"):
            return 200, {}, b"", url
        self.sent.append((method, url, headers, body))
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
        fx = next(f for part, f in self.routes if part in url)
        b = fx["body"]
        raw = b.encode("utf-8") if isinstance(b, str) else json.dumps(b).encode("utf-8")
        return fx["status"], fx.get("headers", {}), raw, url


class ScraperApi(unittest.TestCase):
    """Answers built from the documentation, not recorded live: see their ``note``."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def adapter(self, name):
        c = client(fixture("scraperapi", name), self.tmp.name)
        return adapters.make("scraperapi", c, self.cat["scraperapi"], ENV), c.transport.sent

    def test_read_carries_its_ceiling(self):
        ad, sent = self.adapter("read-ok.json")
        page, usage = ad.read("https://example.org/registre-1851")
        self.assertEqual((page.status, usage.units), (200, 1))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(sent[0][1]).query)
        self.assertEqual((query["max_cost"], query["output_format"], query.get("render")),
                         (["1"], ["markdown"], None))

    def test_render_only_as_the_javascript_tier(self):
        ad, sent = self.adapter("read-ok.json")
        ad.read("https://example.org/registre-1851", "read_js")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(sent[0][1]).query)
        self.assertEqual((query["render"], query["max_cost"]), (["true"], ["10"]))

    def test_a_page_gone_is_billed(self):
        ad, _s = self.adapter("read-404.json")
        page, usage = ad.read("https://example.org/registre-1851")
        self.assertEqual((page.status, usage.units), (404, 1))

    def test_premium_pools_are_refused(self):
        ad, sent = self.adapter("read-ok.json")
        for kw in ({"premium": True}, {"ultra_premium": "true"}):
            with self.subTest(option=kw), self.assertRaises(adapters.AntiBotRefused):
                ad.read("https://example.org/", **kw)
        self.assertEqual(sent, [])

    def test_cost_estimate(self):
        ad, sent = self.adapter("urlcost.json")     # live: free, requestCount did not move
        self.assertEqual(ad.urlcost("https://en.wikipedia.org/wiki/Luxembourg_City"), 1)
        self.assertIn("/account/urlcost?", sent[0][1])

    def test_quota(self):
        text = lambda name: fixture("scraperapi", name)["body"]
        self.assertTrue(adapters.exhausted_status("scraperapi", 403, text("error-403-credits.json")))
        self.assertFalse(adapters.exhausted_status("scraperapi", 403, text("error-403-max-cost.json")))
        self.assertFalse(adapters.exhausted_status("scraperapi", 429, text("error-429.json")))
        ledger = Ledger(self.tmp.name, self.cat)
        sync = lambda name: adapters.sync("scraperapi", client(fixture("scraperapi", name), self.tmp.name),
                                          self.cat["scraperapi"], ENV, ledger)
        self.assertEqual(sync("account.json")["left"], 412)
        # live, during the trial: ScraperAPI reports 5,000; only the plan's 1,000 counts
        info = sync("account-trial.json")
        self.assertEqual((info["left"], info["period_start"]), (999, "2026-10-02T05:51:47.000Z"))
        self.assertEqual(ledger.left("scraperapi", 0), 999)


class Apify(unittest.TestCase):
    """Answers built from the documentation, not recorded live: see their ``note``."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def adapter(self, provider, routes):
        transport = Routes([(part, fixture(d, name)) for part, d, name in routes])
        c = Client(self.tmp.name, None, None, transport, sleep=lambda s: None)
        return adapters.make(provider, c, self.cat[provider], ENV), transport.sent

    def test_a_search_run_and_its_real_cost(self):
        ad, sent = self.adapter("apify", [("/runs", "apify", "run-succeeded.json"),
                                          ("/datasets/", "apify", "items-search.json")])
        results, usage = ad.search(QUERY)
        self.assertEqual([r.url for r in results][:1], ["https://familytree.example.org/wiki/Hugo-1802"])
        self.assertEqual({r.family for r in results}, {"G"})
        self.assertEqual(usage.units, 0.001)        # the live run's usageTotalUsd
        method, url, headers, body = sent[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual((query["maxTotalChargeUsd"], query["maxItems"], query["timeout"], query["memory"]),
                         (["0.5"], ["1"], ["120"], ["1024"]))    # Apify's minimum cap is 0.50 $
        self.assertIn("/acts/apify~google-search-scraper/runs", url)
        self.assertEqual(headers.get("Authorization"), "Bearer test-key")

    def test_a_page_read_without_proxy(self):
        ad, sent = self.adapter("apify_reader", [("/runs", "apify_reader", "run-succeeded.json"),
                                                 ("/datasets/", "apify_reader", "items-read.json")])
        page, usage = ad.read("https://en.wikipedia.org/wiki/Luxembourg_City")
        self.assertIn("Luxembourg", page.text)
        self.assertEqual((page.status, usage.units), (200, 0.000225))
        body = json.loads(sent[0][3])
        self.assertEqual((body["query"], body["proxyConfiguration"], body["scrapingTool"]),
                         ("https://en.wikipedia.org/wiki/Luxembourg_City", {"useApifyProxy": False}, "raw-http"))

    def test_an_actor_off_the_list_is_refused(self):
        ad, sent = self.adapter("apify_reader", [("/runs", "apify_reader", "run-succeeded.json")])
        with self.assertRaises(adapters.ActorRefused):
            ad.read("https://www.geneanet.org/", actor="someone~geneanet-scraper")
        with self.assertRaises(adapters.AntiBotRefused):
            ad.read("https://example.org/", proxyConfiguration={"apifyProxyGroups": ["RESIDENTIAL"]})
        self.assertEqual(sent, [])

    def test_a_failed_run_is_an_error(self):
        ad, _s = self.adapter("apify", [("/runs", "apify", "run-failed.json")])
        with self.assertRaises(ProviderError) as cm:
            ad.search(QUERY)
        self.assertIn("FAILED", str(cm.exception))

    def test_quota(self):
        body = json.dumps(fixture("apify", "error-403.json")["body"])
        self.assertTrue(adapters.exhausted_status("apify", 403, body))
        self.assertFalse(adapters.exhausted_status("apify", 403, '{"error": {"type": "insufficient-permissions"}}'))
        ledger = Ledger(self.tmp.name, self.cat)
        info = adapters.sync("apify", client(fixture("apify", "limits.json"), self.tmp.name),
                             self.cat["apify"], ENV, ledger)
        # live: the account's limit is 10 $, but only the free plan's 5 $ counts
        self.assertAlmostEqual(info["left"], 5 - 0.003505772529029846)
        self.assertEqual(info["period_start"], "2026-10-02T00:00:00.000Z")
        self.assertAlmostEqual(ledger.left("apify_reader", 0), info["left"])   # one account for both


class Acceptance(unittest.TestCase):
    """The free-only stop, and quota sync against recorded answers."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), self.dir)

    def call(self, routes, *argv, env=None):
        import io
        from unittest import mock

        from probandia import cli
        from probandia.cli import search_cmd

        def transport(method, url, headers, body, timeout):
            if url.endswith("/robots.txt"):
                return 200, {}, b"", url
            for prefix, (provider, name) in routes.items():
                if url.startswith(prefix):
                    fx = fixture(provider, name)
                    b = fx["body"]
                    raw = b.encode() if isinstance(b, str) else json.dumps(b).encode()
                    return fx["status"], fx.get("headers", {}), raw, url
            return 404, {}, b"no route", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport,
                          sleep=lambda s: None)
        out = io.StringIO()
        environ = dict({"PROBANDIA_CONFIG_DIR": self.tmp.name, "PROBANDIA_SESSION": "t"}, **(env or {}))
        with mock.patch.object(search_cmd, "_client", make_client):
            code = cli.main(list(argv), stdout=out, environ=environ, cwd=self.dir)
        return code, out.getvalue()

    def test_an_unrelated_engine_hands_its_family_over(self):
        # Google through SerpApi answers beside the query (the live Bing answer, which
        # names no Hugo); Serper, the same family, takes over; Bing answers nothing.
        env = {"SERPAPI_API_KEY": "k", "SERPER_API_KEY": "k",
               "PROBANDIA_PROVIDERS_ENABLED": "serpapi,serpapi_bing,serper"}
        routes = {"https://serpapi.com/search.json?engine=google": ("serpapi_bing", "search-ok.json"),
                  "https://serpapi.com/search.json?engine=bing": ("serpapi", "search-empty.json"),
                  "https://google.serper.dev/search": ("serper", "search-empty.json")}
        code, out = self.call(routes, "search", "Hugo Besançon", "--negative", env=env)
        self.assertIn("NEGATIVE=negative", out)
        self.assertIn("FAMILIES=B,G", out)
        self.assertIn("ENGINES=serpapi,serpapi_bing,serper", out)
        self.assertIn("- reason=serpapi: unrelated answer, not counted", out)

    def test_free_only_stop(self):
        env = {**REUSE, "TAVILY_API_KEY": "k", "LINKUP_API_KEY": "k"}
        routes = {"https://api.tavily.com/search": ("tavily", "search-ok.json")}
        code, out = self.call(routes, "search", "Hugo Besançon", "--engine", "tavily", env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("[tavily]", out)
        self.call({}, "quota", "add", "tavily", "899", env=env)  # 1000 - 100 reserve - 1 used
        code, out = self.call(routes, "search", "Hugo Besançon 1803", "--engine", "tavily", env=env)
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=free-quota:tavily", out)
        self.assertIn("ALTERNATIVE=linkup", out)

    def test_advanced_depth_is_refused_before_any_call(self):
        env = {"SERPER_API_KEY": "k", **REUSE, "TAVILY_API_KEY": "k"}
        called = {"https://google.serper.dev/search": ("serper", "search-ok.json")}
        code, out = self.call(called, "search", "Hugo", "--engine", "serper", "--depth", "advanced", env=env)
        self.assertEqual(code, 2, out)
        self.assertIn("--depth advanced is not offered by serper", out)
        self.assertIn("Tavily", out)
        self.assertNotIn("[serper]", out)
        # auto: only the providers that price an advanced search are asked
        routes = {"https://api.tavily.com/search": ("tavily", "search-ok.json"),
                  "https://google.serper.dev/search": ("serper", "search-ok.json")}
        code, out = self.call(routes, "search", "Hugo Besançon", "--depth", "advanced",
                              env=dict(env, PROBANDIA_PROVIDERS_ENABLED="serper,tavily"))
        self.assertEqual(code, 0, out)
        self.assertIn("ENGINES=tavily", out)

    def test_an_exhausted_answer_stops_the_next_call(self):
        env = {**REUSE, "TAVILY_API_KEY": "k"}
        exhausted = {"https://api.tavily.com/search": ("tavily", "error-429.json")}
        code, out = self.call(exhausted, "search", "Hugo", "--engine", "tavily", env=env)
        self.assertEqual(code, 1)
        code, out = self.call(exhausted, "search", "Hugot", "--engine", "tavily", env=env)
        self.assertEqual(code, 4)

    def test_quota_sync_with_recorded_answers(self):
        env = {**REUSE, "TAVILY_API_KEY": "k", "FIRECRAWL_API_KEY": "k", "BRAVE_API_KEY": "k"}
        routes = {"https://api.tavily.com/usage": ("tavily", "usage.json"),
                  "https://api.firecrawl.dev/v2/team/credit-usage": ("firecrawl", "usage.json"),
                  "https://api.search.brave.com/": ("brave", "search-ok.json")}
        code, out = self.call(routes, "quota", "sync", "tavily", env=env)
        self.assertIn("- sync=tavily left=500", out)
        code, out = self.call(routes, "quota", "sync", "firecrawl", env=env)
        self.assertIn("- sync=firecrawl left=1000", out)
        # Brave has no endpoint: every answer carries the monthly count left
        env_brave = dict(env, PROBANDIA_PROVIDERS_ALLOW_CARD_REQUIRED="true")
        code, out = self.call(routes, "search", "Hugo", "--engine", "brave", env=env_brave)
        self.assertEqual(code, 0, out)
        from probandia.ledger import Ledger
        # the user's counter, under the keys the commands used (cli.md § 4.4)
        state = Ledger(self.dir, catalogue.load(), environ=dict(env_brave, PROBANDIA_CONFIG_DIR=self.tmp.name)).state()
        self.assertEqual(state["brave"]["reported_left"], 14523.0)
        self.assertEqual(state["tavily"]["reported_left"], 500)

    def test_marginalia_daily_capacity(self):
        # Marginalia's answers say what its shared key may still do today
        routes = {"https://api2.marginalia-search.com/": ("marginalia", "search-ok.json")}
        code, out = self.call(routes, "search", "Hugo", "--engine", "marginalia")
        self.assertEqual(code, 0, out)
        from probandia.ledger import Ledger
        ledger = Ledger(self.dir, catalogue.load(), environ={"PROBANDIA_CONFIG_DIR": self.tmp.name})
        self.assertEqual(ledger.state()["marginalia"]["reported_left"], 998.0)
        self.assertFalse(ledger.exhausted("marginalia"))
        from probandia.cli.search_exec import report_balance
        report_balance(ledger, "marginalia", {"daily_left": 0.0})
        self.assertTrue(ledger.exhausted("marginalia"))
        self.assertEqual(ledger.left("marginalia", 10), 0)


class BraveHeaders(unittest.TestCase):
    def test_monthly_count_left(self):
        from probandia.providers.adapters import brave_left

        self.assertEqual(brave_left({"x-ratelimit-limit": "1, 2000", "x-ratelimit-remaining": "0, 1523"}), 1523.0)
        # credit plans (live answer of 1 October 2026): a monthly limit of 0 means no cap
        self.assertIsNone(brave_left({"x-ratelimit-limit": "50, 0", "x-ratelimit-remaining": "49, 0"}))
        self.assertIsNone(brave_left({"x-ratelimit-remaining": "49"}))
        self.assertIsNone(brave_left({}))


# map, crawl and extract (T228)

SITE = "https://registres.example.org/"


class Played:
    """Recorded answers by method and URL prefix, each a list played in turn (the last
    one repeats); every call is kept."""

    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.sent = []

    def __call__(self, method, url, headers, body, timeout):
        if url.endswith("/robots.txt"):
            return 200, {}, b"", url
        self.sent.append((method, url, headers, body))
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
        key = next((k for k in self.routes if k[0] == method and url.startswith(k[1])), None)
        if key is None:
            return 404, {}, b'{"error": "not found"}', url
        answers = self.routes[key]
        fx = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(fx, str):
            fx = fixture(*fx.split("/"))
        b = fx["body"]
        raw = b.encode("utf-8") if isinstance(b, str) else json.dumps(b).encode("utf-8")
        return fx["status"], fx.get("headers", {}), raw, url


class Operations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = catalogue.load()

    def make(self, provider, routes):
        self.transport = Played(routes)
        return adapters.make(provider, Client(self.tmp.name, None, None, self.transport, sleep=lambda s: None),
                             self.cat[provider], ENV)

    def bodies(self, method="POST"):
        return [json.loads(b) for m, _u, _h, b in self.transport.sent if m == method and b]

    def test_map_gives_urls_and_units(self):
        fc = self.make("firecrawl", {("POST", "https://api.firecrawl.dev/v2/map"): ["firecrawl/map-ok.json"]})
        urls, usage = fc.map(SITE)
        self.assertEqual(urls[1], "https://registres.example.org/naissances/1802")
        self.assertEqual((len(urls), usage.units), (4, 1.0))   # 1 credit a call
        self.assertEqual(self.bodies()[0]["url"], SITE)
        tv = self.make("tavily", {("POST", "https://api.tavily.com/map"): ["tavily/map-ok.json"]})
        urls, usage = tv.map(SITE)
        self.assertEqual(len(urls), 3)
        # Tavily reports 0 until ten pages are mapped: the catalogue's 0.1 a URL is counted
        self.assertAlmostEqual(usage.units, 0.3)
        self.assertEqual(self.transport.sent[0][2]["Authorization"], "Bearer test-key")

    def test_firecrawl_crawl_waits_for_its_job(self):
        sleeps = []
        fc = self.make("firecrawl", {
            ("POST", "https://api.firecrawl.dev/v2/crawl"): ["firecrawl/crawl-start.json"],
            ("GET", "https://api.firecrawl.dev/v2/crawl/"): ["firecrawl/crawl-scraping.json",
                                                             "firecrawl/crawl-completed.json"]})
        fc.sleep = sleeps.append
        fc.now = lambda: float(len(sleeps)) * 2
        pages, usage = fc.crawl(SITE + "naissances", limit=3, include=["naissances/.*"])
        self.assertEqual([(p.final_url.rsplit("/", 1)[1], p.status) for p in pages],
                         [("1802", 200), ("1803", 200), ("1804", 404)])
        self.assertIn("Victor Hugo", pages[0].text)
        self.assertEqual(pages[1].title, "Naissances 1803")
        self.assertEqual((usage.units, sleeps), (3.0, [2.0]))
        body = self.bodies()[0]
        self.assertEqual((body["limit"], body["includePaths"]), (3, ["naissances/.*"]))
        self.assertFalse([m for m, *_r in self.transport.sent if m == "DELETE"])

    def test_firecrawl_crawl_stops_at_the_pages_asked(self):
        fc = self.make("firecrawl", {
            ("POST", "https://api.firecrawl.dev/v2/crawl"): ["firecrawl/crawl-start.json"],
            ("GET", "https://api.firecrawl.dev/v2/crawl/"): ["firecrawl/crawl-completed.json"]})
        pages, usage = fc.crawl(SITE + "naissances", limit=2)
        self.assertEqual(len(pages), 2)
        self.assertEqual(usage.units, 3.0)   # what Firecrawl reports is what is counted

    def test_firecrawl_crawl_stops_at_its_wait(self):
        sleeps = []
        fc = self.make("firecrawl", {
            ("POST", "https://api.firecrawl.dev/v2/crawl"): ["firecrawl/crawl-start.json"],
            ("GET", "https://api.firecrawl.dev/v2/crawl/"): ["firecrawl/crawl-scraping.json"],
            ("DELETE", "https://api.firecrawl.dev/v2/crawl/"): [{"status": 200, "body": {"status": "cancelled"}}]})
        fc.sleep = sleeps.append
        fc.now = lambda: float(len(sleeps)) * 2
        pages, usage = fc.crawl(SITE + "naissances", limit=10, wait=7)
        self.assertEqual((len(pages), usage.units), (1, 1.0))   # the page read before the wait ran out
        self.assertLessEqual(sum(sleeps), 7)
        deleted = [u for m, u, *_r in self.transport.sent if m == "DELETE"]
        self.assertEqual(deleted, ["https://api.firecrawl.dev/v2/crawl/0b6e1f9a-3c41-4d2e-9b7a-5f2c8d1e4a10"])

    def test_tavily_crawl(self):
        tv = self.make("tavily", {("POST", "https://api.tavily.com/crawl"): ["tavily/crawl-ok.json"]})
        pages, usage = tv.crawl(SITE + "naissances", limit=2, include=["/naissances/.*"])
        self.assertEqual([(p.final_url, p.status) for p in pages],
                         [(SITE + "naissances/1802", 200), (SITE + "naissances/1803", 200)])
        self.assertEqual(usage.units, 1.0)
        body = self.bodies()[0]
        self.assertEqual((body["limit"], body["select_paths"], body["extract_depth"]),
                         (2, ["/naissances/.*"], "basic"))

    def test_firecrawl_extract_gives_json(self):
        fc = self.make("firecrawl", {("POST", "https://api.firecrawl.dev/v2/scrape"): ["firecrawl/extract-ok.json"]})
        schema = {"type": "object", "properties": {"registres": {"type": "array"}}}
        found, usage = fc.extract(SITE + "inventaire", "the registers: cote, commune, years", schema)
        self.assertEqual(found["registres"][2]["commune"], "Les Auxons")
        self.assertEqual(usage.units, 5.0)
        fmt = self.bodies()[0]["formats"][0]
        self.assertEqual((fmt["type"], fmt["schema"]), ("json", schema))

    def test_an_unexpected_answer_is_an_error_not_an_empty_list(self):
        odd = {"status": 200, "headers": {"Content-Type": "application/json"}, "body": {"unexpected": True}}
        cases = [("firecrawl", "map", ("POST", "https://api.firecrawl.dev/v2/map"), (SITE,)),
                 ("tavily", "map", ("POST", "https://api.tavily.com/map"), (SITE,)),
                 ("firecrawl", "crawl", ("POST", "https://api.firecrawl.dev/v2/crawl"), (SITE,)),
                 ("tavily", "crawl", ("POST", "https://api.tavily.com/crawl"), (SITE,)),
                 ("firecrawl", "extract", ("POST", "https://api.firecrawl.dev/v2/scrape"), (SITE, "x"))]
        for provider, op, route, args in cases:
            with self.subTest(provider=provider, operation=op):
                ad = self.make(provider, {route: [odd]})
                with self.assertRaises(ProviderError):
                    getattr(ad, op)(*args)
        # a job whose state is not one Firecrawl documents
        fc = self.make("firecrawl", {("POST", "https://api.firecrawl.dev/v2/crawl"): ["firecrawl/crawl-start.json"],
                                     ("GET", "https://api.firecrawl.dev/v2/crawl/"): [odd]})
        with self.assertRaises(ProviderError):
            fc.crawl(SITE)
        # an error status
        fc = self.make("firecrawl", {("POST", "https://api.firecrawl.dev/v2/map"): ["firecrawl/error-402.json"]})
        with self.assertRaises(ProviderError) as cm:
            fc.map(SITE)
        self.assertEqual(cm.exception.status, 402)

    def test_the_operations_each_adapter_makes(self):
        self.assertTrue(adapters.REGISTRY["firecrawl"].does("extract"))
        self.assertFalse(adapters.REGISTRY["tavily"].does("extract"))   # Tavily's extract is a read (T232)
        self.assertFalse(adapters.REGISTRY["exa"].does("map"))
        with self.assertRaises(NotImplementedError):
            self.make("exa", {}).map(SITE)

    def test_usable_for_an_operation(self):
        from tests.unit.test_catalogue import Config

        env = {"FIRECRAWL_API_KEY": "k", **REUSE, "TAVILY_API_KEY": "k", "EXA_API_KEY": "k"}
        reuse = Config(providers__allow_content_reuse=True)   # T217: Tavily may train on what it is sent
        self.assertEqual(catalogue.usable(reuse, env, operation="map"), ["tavily", "firecrawl"])
        self.assertEqual(catalogue.usable(reuse, env, operation="crawl"), ["tavily", "firecrawl"])
        self.assertEqual(catalogue.usable(Config(), env, operation="map"), ["firecrawl"])
        self.assertEqual(catalogue.usable(reuse, env, operation="extract"), ["firecrawl"])
        self.assertEqual(catalogue.usable(Config(), {}, operation="map"), [])
        self.assertEqual(catalogue.usable(Config(), {"FIRECRAWL_API_KEY": "k"}, operation="map"), ["firecrawl"])

    def test_tavily_reads_a_page_through_extract(self):
        """T232: Tavily's extract gives the page's text; a URL it could not read is an error."""
        tv = self.make("tavily", {("POST", "https://api.tavily.com/extract"): ["tavily/extract-ok.json"]})
        page, usage = tv.read("https://families.example.org/hugo")
        self.assertIn("Victor Marie Hugo", page.text)
        self.assertEqual((page.final_url, page.status, usage.units), ("https://families.example.org/hugo", 200, 0.2))
        self.assertEqual(self.bodies()[0]["urls"], "https://families.example.org/hugo")
        tv = self.make("tavily", {("POST", "https://api.tavily.com/extract"): ["tavily/extract-failed.json"]})
        with self.assertRaises(ProviderError) as cm:
            tv.read("https://families.example.org/hugo")
        self.assertIn("Failed to fetch url", str(cm.exception))

    def test_parallel_reads_a_page_through_extract(self):
        """Parallel's /v1/extract: full_content inside advanced_settings, a failed URL in errors."""
        route = ("POST", "https://api.parallel.ai/v1/extract")
        ok = {"status": 200, "body": {"extract_id": "x1", "results": [
            {"url": "https://families.example.org/hugo", "title": "Hugo", "publish_date": None,
             "excerpts": ["an excerpt"], "full_content": "# Victor Marie Hugo\n\nborn 1802"}],
            "errors": [], "usage": [{"name": "sku_extract_excerpts", "count": 1}]}}
        pa = self.make("parallel", {route: [ok]})
        page, usage = pa.read("https://families.example.org/hugo")
        self.assertIn("Victor Marie Hugo", page.text)
        self.assertEqual((page.title, page.status, usage.units), ("Hugo", 200, 0.001))
        body = self.bodies()[0]
        self.assertEqual(body, {"urls": ["https://families.example.org/hugo"],
                                "advanced_settings": {"full_content": True}})
        self.assertEqual(self.transport.sent[0][2]["x-api-key"], "test-key")
        # no full_content: the excerpts are the text
        only = json.loads(json.dumps(ok))
        only["body"]["results"][0]["full_content"] = None
        page, _u = self.make("parallel", {route: [only]}).read("https://families.example.org/hugo")
        self.assertEqual(page.text, "an excerpt")
        self.assertEqual(self.transport.timeouts[-1], 120)   # a live fetch takes 60 to 90 s
        failed = {"status": 200, "body": {"extract_id": "x2", "results": [], "errors": [
            {"url": "https://families.example.org/hugo", "error_type": "fetch_failed", "http_status_code": 404,
             "content": None}]}}
        with self.assertRaises(ProviderError) as cm:
            self.make("parallel", {route: [failed]}).read("https://families.example.org/hugo")
        self.assertEqual(cm.exception.status, 422)
        self.assertIn("fetch_failed, HTTP 404", str(cm.exception))
        self.assertTrue(catalogue.does(self.cat["parallel"], "read"))

    def test_advanced_depth_sends_each_provider_its_field(self):
        cases = {"tavily": ("https://api.tavily.com/search", "search_depth", "basic", "advanced"),
                 "parallel": ("https://api.parallel.ai/v1/search", "mode", "fast", "advanced"),
                 "exa": ("https://api.exa.ai/search", "type", "auto", "deep"),
                 "linkup": ("https://api.linkup.so/v1/search", "depth", "standard", "deep")}
        for pid, (url, field, standard, advanced) in cases.items():
            with self.subTest(provider=pid):
                for depth, expected in (("standard", standard), ("advanced", advanced)):
                    ad = self.make(pid, {("POST", url): [f"{pid}/search-ok.json"]})
                    q = Query(text="Hugo Besançon", max=5, depth=depth)
                    ad.search(q)
                    self.assertEqual(self.bodies()[0][field], expected)
                self.assertTrue(catalogue.does(self.cat[pid], "search_advanced"))
        for pid in ("jina", "firecrawl", "brave", "serper", "serpapi"):
            self.assertFalse(catalogue.does(self.cat[pid], "search_advanced"), pid)

    def test_estimate_charges_the_advanced_search(self):
        for pid, standard, advanced in (("tavily", 1, 2), ("parallel", 0.001, 0.005), ("exa", 0.017, 0.022),
                                        ("linkup", 0.005, 0.05)):
            ad = self.make(pid, {})
            self.assertEqual(ad.estimate(Query(text="x")), standard, pid)
            self.assertEqual(ad.estimate(Query(text="x", depth="advanced")), advanced, pid)
        self.assertEqual(self.make("serper", {}).estimate(Query(text="x", depth="advanced")),
                         self.cat["serper"]["costs"]["search"])

    def test_scrapegraph_extracts_json(self):
        """T231: ScrapeGraph's extract gives JSON; it reports tokens, so the catalogue's 5 credits are counted."""
        sg = self.make("scrapegraph", {("POST", "https://v2-api.scrapegraphai.com/api/extract"):
                                       ["scrapegraph/extract-ok.json"]})
        sg.environ = dict(ENV, SGAI_API_KEY="sg-key")
        found, usage = sg.extract(SITE + "inventaire", "the registers", {"type": "array"})
        self.assertEqual((found[1]["commune"], usage.units), ("Les Auxons", 5.0))
        method, url, headers, body = self.transport.sent[0]
        self.assertEqual((headers.get("SGAI-APIKEY"), json.loads(body)["schema"]), ("sg-key", {"type": "array"}))
        odd = {"status": 200, "body": {"id": "x", "raw": "not JSON"}}
        sg = self.make("scrapegraph", {("POST", "https://v2-api.scrapegraphai.com/api/extract"): [odd]})
        with self.assertRaises(ProviderError):
            sg.extract(SITE, "x")
        self.assertTrue(adapters.REGISTRY["scrapegraph"].does("extract"))
