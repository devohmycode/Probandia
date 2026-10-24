import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from probandia import cli
from probandia.cli import reading_cmd
from probandia.ledger import Ledger
from probandia.providers import catalogue
from probandia.providers.meter import Meter
from probandia.reading import detector
from probandia.reading.cache import Cache, make_key, ttl_for
from probandia.reading.ladder import Reader, blocks, passages
from probandia.util import yamlio
from probandia.util.http import Client, HostNotAllowed, RobotsDenied, retry_after
from tests import REUSE, ROOT, SRC

PAGES = os.path.join(ROOT, "tests", "fixtures", "pages")
FIXTURE_PROJECT = os.path.join(ROOT, "tests", "fixtures", "project")


def page(name):
    with open(os.path.join(PAGES, name), "rb") as fh:
        return fh.read()


class Transport:
    """Recorded responses: {url or url prefix: (status, headers, body)}. robots.txt
    is empty unless given. Every call is recorded."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.bodies = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers)))
        self.bodies.append(body)
        if url in self.routes:
            route = self.routes[url]
        else:
            route = next((v for k, v in self.routes.items() if url.startswith(k)), None)
            if route is None:
                route = (200, {}, b"") if url.endswith("/robots.txt") else (404, {}, b"not found")
        if callable(route):
            route = route()
        status, h, b = route
        return status, h, b if isinstance(b, bytes) else b.encode("utf-8"), url


class Config:
    def __init__(self, values=None):
        self.values = {"cache.days": 7, "reading.ladder": ["cache", "api", "http", "extract",
                                                          "reader", "browser", "user-browser",
                                                          "archive"]}
        self.values.update(values or {})

    def get(self, key):
        if key in self.values:
            return self.values[key]
        raise KeyError(key)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, ".probandia")
        self.sleeps = []

    def client(self, routes=None, config=None, **kw):
        self.transport = Transport(routes)
        return Client(self.state, "genealogist@example.org", config or Config(), self.transport,
                      sleep=self.sleeps.append, **kw)


# HTTP client

RATE_WORKER = r"""
import sys, time, json
sys.path.insert(0, sys.argv[1])
from probandia.util.http import Client
state, out = sys.argv[2], sys.argv[3]
class Cfg:
    def get(self, key):
        if key == "hosts.archive.example.rate":
            return "4/s"
        raise KeyError(key)
last = {"now": 0.0, "slot": 0.0}
def clock():
    last["now"] = last["slot"] = time.time()
    return last["now"]
def sleep(seconds):
    last["slot"] = last["now"] + seconds   # the slot the client was given: the time it read, plus its wait
    time.sleep(seconds)
def transport(method, url, headers, body, timeout):
    if not url.endswith("robots.txt"):
        with open(out, "a") as fh:
            fh.write(f"{last['slot']} {time.time()}\n")
    return 200, {}, b"ok", url
c = Client(state, None, Cfg(), transport, sleep=sleep, clock=clock)
for _ in range(4):
    c.get("https://archive.example/page")
"""


class HttpClient(Base):
    def test_user_agent_names_the_contact(self):
        c = self.client({"https://a.example/x": (200, {}, "hello")})
        c.get("https://a.example/x")
        ua = self.transport.calls[-1][2]["User-Agent"]
        self.assertRegex(ua, r"^Probandia/\d+\.\d+\.\d+ \(\+genealogist@example\.org\)$")
        robots = next(h for _m, u, h in self.transport.calls if u.endswith("robots.txt"))
        self.assertEqual(robots["User-Agent"], ua)  # robots.txt is asked for politely too

    def test_rate_per_host_across_two_processes(self):
        out = os.path.join(self.tmp.name, "times.txt")
        procs = [subprocess.Popen([sys.executable, "-c", RATE_WORKER, SRC, self.state, out])
                 for _ in range(2)]
        for p in procs:
            self.assertEqual(p.wait(timeout=60), 0)
        with open(out) as fh:
            pairs = sorted(tuple(float(t) for t in line.split()) for line in fh)
        self.assertEqual(len(pairs), 8)
        # 4 per second, shared between the processes: the slots the client hands out
        # are a quarter of a second apart, whatever the load, and no request leaves
        # before its slot. The times the requests leave are not checked against each
        # other: on a loaded machine (the suite shared out between processes) a
        # process stalled for 3 s, then two requests left within a millisecond.
        slots = [slot for slot, _sent in pairs]
        gaps = [b - a for a, b in zip(slots, slots[1:])]
        self.assertGreaterEqual(min(gaps), 0.25 - 1e-6, gaps)
        self.assertGreaterEqual(slots[-1] - slots[0], 7 * 0.25 - 1e-6, gaps)
        for slot, sent in pairs:
            self.assertGreaterEqual(sent, slot - 0.01, pairs)

    def test_retry_after_is_honoured(self):
        answers = iter([(429, {"Retry-After": "3"}, ""), (200, {}, "fine")])
        c = self.client({"https://a.example/x": lambda: next(answers)})
        r = c.get("https://a.example/x")
        self.assertEqual(r.status, 200)
        self.assertIn(3, self.sleeps)

    def test_too_long_retry_after_stops(self):
        c = self.client({"https://a.example/x": (503, {"Retry-After": "600"}, "")})
        self.assertEqual(c.get("https://a.example/x").status, 503)
        self.assertNotIn(600, self.sleeps)

    def test_backoff_then_give_up(self):
        c = self.client({"https://a.example/x": (429, {}, "")})
        self.assertEqual(c.get("https://a.example/x").status, 429)
        pages = [u for _m, u, _h in self.transport.calls if not u.endswith("robots.txt")]
        self.assertEqual(len(pages), 4)  # one call and 3 retries
        self.assertEqual([s for s in self.sleeps if s in (2, 4, 8)], [2, 4, 8])

    def test_one_retry_on_5xx_none_on_4xx(self):
        c = self.client({"https://a.example/500": (500, {}, ""), "https://a.example/400": (400, {}, "")})
        c.get("https://a.example/500")
        c.get("https://a.example/400")
        pages = [u for _m, u, _h in self.transport.calls if not u.endswith("robots.txt")]
        self.assertEqual(pages.count("https://a.example/500"), 2)
        self.assertEqual(pages.count("https://a.example/400"), 1)

    def test_robots_disallow(self):
        c = self.client({"https://a.example/robots.txt": (200, {}, "User-agent: *\nDisallow: /private\n"),
                         "https://a.example/": (200, {}, "page")})
        with self.assertRaises(RobotsDenied):
            c.get("https://a.example/private/record")
        self.assertEqual(c.get("https://a.example/public").status, 200)
        robots = [u for _m, u, _h in self.transport.calls if u.endswith("robots.txt")]
        self.assertEqual(len(robots), 1)  # kept, not read again
        c.get("https://a.example/private/api", api=True)  # documented endpoints are exempt

    def test_host_outside_the_allowlist(self):
        c = self.client({}, allow_hosts=["gallica.bnf.fr"])
        with self.assertRaises(HostNotAllowed):
            c.get("https://evil.example/x")
        self.assertEqual(self.transport.calls, [])

    def test_conditional_request(self):
        c = self.client({"https://a.example/x": (304, {}, "")})
        cached = {"etag": '"abc"', "last_modified": "Wed, 30 Sep 2026 10:00:00 GMT", "body": "old page"}
        r = c.get("https://a.example/x", cached=cached)
        self.assertTrue(r.from_cache)
        self.assertEqual(r.text, "old page")
        sent = self.transport.calls[-1][2]
        self.assertEqual(sent["If-None-Match"], '"abc"')

    def test_retry_after_dates(self):
        self.assertEqual(retry_after("12", 0), 12)
        self.assertEqual(retry_after("Thu, 01 Jan 1970 00:01:00 GMT", 30), 30)
        self.assertIsNone(retry_after(None, 0))


# detector


class Detector(unittest.TestCase):
    def test_fixtures(self):
        for case in yamlio.load(os.path.join(PAGES, "cases.yaml")):
            with self.subTest(page=case["file"]):
                login = None
                if case.get("login"):
                    from probandia.archives.finder import load_catalogue

                    login = load_catalogue()[case["login"]]["login"]
                status, rule = detector.classify(case["status"], page(case["file"]), case["url"],
                                                 case.get("final_url"), kind=case.get("kind", "http"), login=login)
                self.assertEqual(status, case["expect"], rule)

    def test_codes(self):
        for code in (401, 403, 407, 429, 451, 503):
            self.assertEqual(detector.classify(code, b"x" * 5000, "https://a/x")[0], "blocked")

    def test_any_other_error_answer_is_a_failure(self):
        for code in (400, 402, 404, 500, 502):
            for kind in ("http", "reader", "browser"):
                with self.subTest(code=code, kind=kind):
                    self.assertEqual(detector.classify(code, b"x" * 5000, "https://a/x", kind=kind)[0],
                                     "blocked")

    def test_challenge_cookie_and_header(self):
        body = ("<html><body>" + "<p>text</p>" * 400 + "</body></html>").encode()
        self.assertEqual(detector.classify(200, body, "https://a/x",
                                           headers={"Set-Cookie": "techaro.lol-anubis-auth=1"})[0],
                         "challenge")
        self.assertEqual(detector.classify(200, body, "https://a/x",
                                           headers={"cf-mitigated": "challenge"})[0], "challenge")

    def test_empty(self):
        self.assertEqual(detector.classify(200, b"<html><body><p>Hello</p></body></html>",
                                           "https://a/x")[0], "empty")

    def test_wrong_page(self):
        body = ("<html><head><title>Accueil</title></head><body>" + "<p>Bienvenue</p>" * 300
                + "</body></html>").encode()
        self.assertEqual(detector.classify(200, body, "https://a/fonds/12")[0], "wrong_page")
        self.assertEqual(detector.classify(200, body, "https://a/")[0], "ok")
        normal = ("<html><body>" + "<p>Acte de naissance</p>" * 300 + "</body></html>").encode()
        self.assertEqual(detector.classify(200, normal, "https://a/x", "https://b/y")[0], "wrong_page")
        self.assertEqual(detector.classify(200, normal, "http://a/x", "https://a/x/")[0], "ok")

    def test_expected_markers(self):
        normal = ("<html><body>" + "<p>Acte de naissance</p>" * 300 + "</body></html>").encode()
        self.assertEqual(detector.classify(200, normal, "https://a/x", expect=["Hugo"])[0], "unknown")
        self.assertEqual(detector.classify(200, normal, "https://a/x", expect=["naissance"])[0], "ok")
        self.assertEqual(detector.classify(200, normal + b"<p>Aucun resultat</p>", "https://a/x",
                                           expect=["Hugo"], no_results="aucun resultat")[0], "ok")


# cache


class CacheTest(Base):
    def test_three_times_to_live(self):
        now = [1000.0]
        work = os.path.join(self.tmp.name, "work")
        c = Cache(self.tmp.name, work, clock=lambda: now[0])
        c.put("serpapi", "k1", {"r": 1}, "ok", 3600)
        c.put("brave", "k2", {"r": 2}, "ok", 0)
        self.assertEqual(c.get("serpapi", "k1"), {"r": 1})
        self.assertEqual(c.get("brave", "k2"), {"r": 2})
        self.assertTrue(os.path.exists(os.path.join(work, "cache", "brave", "k2.json")))
        now[0] += 3601
        self.assertIsNone(c.get("serpapi", "k1"))  # expired
        self.assertEqual(c.get("brave", "k2"), {"r": 2})  # still this pass
        c.end_pass()
        self.assertIsNone(c.get("brave", "k2"))

    def test_ttl_sources(self):
        cfg = Config({"cache.days": 3, "providers.exa.cache_ttl": 1})
        self.assertEqual(ttl_for("exa", cfg), 86400)
        self.assertEqual(ttl_for("tavily", cfg), 3 * 86400)
        self.assertEqual(ttl_for("brave", cfg, catalogue_ttl=0), 0)

    def test_failures_are_never_cached_nor_served(self):
        c = Cache(self.tmp.name)
        self.assertIsNone(c.put("http", "k", {"text": "x"}, "challenge", 3600))
        path = os.path.join(self.tmp.name, ".probandia", "cache", "http", "k.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            json.dump({"created": 9e12, "ttl": 3600, "status": "empty", "payload": {"text": ""}}, fh)
        self.assertIsNone(c.get("http", "k"))

    def test_fresh(self):
        c = Cache(self.tmp.name)
        c.put("http", "k", {"t": 1}, "ok", 3600)
        self.assertIsNone(c.get("http", "k", fresh=True))

    def test_keys(self):
        self.assertEqual(make_key("serpapi", " Hugo  Besançon"), make_key("serpapi", "hugo besançon"))
        self.assertNotEqual(make_key("serpapi", "x", {"from": 1850}), make_key("serpapi", "x"))


# the ladder

URL = "https://archives.example.org/ec/1802/112"
WIKI = page("wikipedia-octeville.html")
CDX = json.dumps([["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
                  ["org,example,archives)/ec/1802/112", "20240102030405", URL, "text/html", "200", "X", "1"]])


class Ladder(Base):
    def reader(self, routes, **kw):
        client = self.client(routes)
        return Reader(client, Cache(self.tmp.name, os.path.join(self.tmp.name, "work")), Config(),
                      kw.pop("environ", {}), **kw)

    def test_http_and_extraction_then_cache(self):
        r = self.reader({URL: (200, {}, WIKI)})
        first = r.read(URL)
        self.assertEqual((first.status, first.step), ("ok", "extract"))
        self.assertIn("Octeville", first.text)
        again = r.read(URL)
        self.assertEqual((again.step, again.cache), ("cache", "hit"))
        self.assertEqual(r.read(URL, fresh=True).step, "extract")

    def test_a_page_cached_by_older_detector_rules_is_read_again(self):
        cache = Cache(self.tmp.name, os.path.join(self.tmp.name, "work"))
        # what version 1 of the rules let into the cache: a 502 page taken for the page
        cache.put("http", make_key("http", URL), {"text": "502 Bad Gateway nginx", "final_url": URL,
                                                  "step": "extract", "extractor": None}, "ok", 3600)
        r = self.reader({URL: (200, {}, WIKI)})
        first = r.read(URL)
        self.assertEqual((first.step, first.cache), ("extract", "miss"))
        self.assertIn("Octeville", first.text)
        self.assertEqual(r.read(URL).cache, "hit")  # judged again, and stored under the current rules

    def test_connector_pattern(self):
        hit = {}

        def gallica(url):
            hit["url"] = url
            return 200, WIKI.decode(), {}, "http"
        r = self.reader({}, connectors=[(re.compile(r"gallica\.bnf\.fr/ark:"), gallica)])
        res = r.read("https://gallica.bnf.fr/ark:/12148/bpt6k123")
        self.assertEqual(res.step, "api")
        self.assertIn("ark:", hit["url"])

    def test_reader_api_after_a_challenge(self):
        r = self.reader({URL: (200, {}, page("anubis-challenge.html")),
                         "https://r.jina.ai/" + URL: (200, {}, page("jina-ok.md").replace(
                             b"https://example.org/besancon/ec-1802-n/45", URL.encode()))})
        res = r.read(URL)
        self.assertEqual((res.status, res.step, res.extractor), ("ok", "reader", "jina"))
        self.assertEqual(res.tried[0], ("http", "challenge"))
        self.assertTrue(res.text.startswith("Registre des naissances"))

    def test_reader_apis_skipped_on_a_forbidden_host(self):
        r = self.reader({URL: (200, {}, page("anubis-challenge.html")),
                         "https://web.archive.org/cdx/": (200, {}, CDX),
                         "https://web.archive.org/web/20240102030405id_/": (200, {}, WIKI)},
                        forbidden={"archives.example.org"})
        res = r.read(URL)
        self.assertIn(("reader", "forbidden-host"), res.tried)
        self.assertFalse(any("r.jina.ai" in u for _m, u, _h in self.transport.calls))
        self.assertEqual(res.step, "archive")  # refused, so the web archives are tried

    def test_jina_after_firecrawl(self):   # T256: the monthly free tiers first
        fc = json.dumps({"data": {"markdown": page("jina-faq.md").decode().split("Markdown Content:\n")[1],
                                  "metadata": {"title": "Foire aux questions", "sourceURL": "https://anlux.lu/fr/faq"}}})
        r = self.reader({URL: (200, {}, page("anubis-challenge.html")),
                         "https://api.firecrawl.dev/v2/scrape": (200, {}, fc),
                         "https://r.jina.ai/": (200, {}, page("jina-ok.md").replace(
                             b"https://example.org/besancon/ec-1802-n/45", URL.encode()))},
                        environ={"FIRECRAWL_API_KEY": "fc-test"})
        res = r.read(URL)
        self.assertEqual((res.step, res.extractor), ("reader", "jina"))
        self.assertEqual(res.tried[1:], [("reader:firecrawl", "wrong_page"), ("reader:jina", "ok")])

    def test_local_browser(self):
        def browser(url, profile):
            return 200, WIKI.decode(), url
        r = self.reader({URL: (200, {}, page("eluxemburgensia-search.html"))}, browser=browser,
                        forbidden={"archives.example.org"}, state_dir=self.state)
        res = r.read(URL)
        self.assertEqual((res.status, res.step), ("ok", "browser"))
        self.assertEqual(res.tried[0], ("http", "template"))

    def test_a_browser_that_cannot_start_is_a_step_tried(self):
        def browser(url, profile):   # Playwright installed without its browser (seen on 3 October 2026)
            raise RuntimeError("BrowserType.launch_persistent_context: Executable doesn't exist")
        r = self.reader({URL: (200, {}, page("eluxemburgensia-search.html"))}, browser=browser,
                        forbidden={"archives.example.org"}, state_dir=self.state)
        res = r.read(URL)
        self.assertIn(("browser", "unavailable"), res.tried)
        self.assertNotEqual(res.status, "ok")

    def test_the_browser_build_playwright_expects(self):
        from unittest import mock

        from probandia.reading import browser

        pkg = os.path.join(self.state, "site", "playwright")
        os.makedirs(os.path.join(pkg, "driver", "package"))
        with open(os.path.join(pkg, "driver", "package", "browsers.json"), "w", encoding="utf-8") as fh:
            json.dump({"browsers": [{"name": "chromium", "revision": "1243"},
                                    {"name": "chromium-headless-shell", "revision": "1243"}]}, fh)
        spec = mock.Mock(origin=os.path.join(pkg, "__init__.py"))
        store = os.path.join(self.state, "ms-playwright")
        os.makedirs(os.path.join(store, "chromium_headless_shell-1234"))   # an older build only
        env = {"PLAYWRIGHT_BROWSERS_PATH": store}
        with mock.patch("importlib.util.find_spec", return_value=spec):
            self.assertEqual(browser.browser_state(env), "no-browser")
            os.makedirs(os.path.join(store, "chromium_headless_shell-1243"))
            self.assertEqual(browser.browser_state(env), "ready")
        with mock.patch("importlib.util.find_spec", return_value=None):
            self.assertEqual(browser.browser_state(env), "missing")
        self.assertIn("-m playwright install chromium", browser.install_command())

    def test_user_browser_is_asked_for(self):
        r = self.reader({URL: (200, {}, page("eluxemburgensia-search.html"))}, interactive=True,
                        forbidden={"archives.example.org"}, state_dir=self.state)
        self.assertEqual(r.read(URL).status, "ask")
        r = self.reader({URL: (200, {}, page("eluxemburgensia-search.html"))}, interactive=False,
                        forbidden={"archives.example.org"})
        self.assertEqual(r.read(URL).status, "template")

    def test_page_gone_read_from_the_archive(self):
        r = self.reader({URL: (410, {}, "gone"),
                         "https://web.archive.org/cdx/": (200, {}, CDX),
                         "https://web.archive.org/web/20240102030405id_/": (200, {}, WIKI)},
                        forbidden={"archives.example.org"})
        res = r.read(URL)
        self.assertEqual((res.status, res.step), ("ok", "archive"))
        self.assertEqual(res.final_url, "https://web.archive.org/web/20240102030405id_/" + URL)

    def test_a_site_error_page_is_never_read_as_the_page(self):
        bad_gateway = ("<html><head><title>502 Bad Gateway</title></head><body><h1>502 Bad Gateway</h1>"
                       "<p>nginx</p></body></html>")
        r = self.reader({URL: (502, {}, bad_gateway),
                         "https://web.archive.org/cdx/": (200, {}, CDX),
                         "https://web.archive.org/web/20240102030405id_/": (200, {}, WIKI)},
                        forbidden={"archives.example.org"})
        res = r.read(URL)
        self.assertEqual(res.tried[0], ("http", "blocked"))
        self.assertEqual((res.status, res.step), ("ok", "archive"))  # refused, so the web archives

    ROBOTS = {"https://archives.example.org/robots.txt": (200, {}, "User-agent: *\nDisallow: /ec/\n")}

    def test_robots_leaves_the_page_to_the_readers(self):   # T66: robots.txt rules crawlers, not one page
        jina = page("jina-ok.md").replace(b"https://example.org/besancon/ec-1802-n/45", URL.encode())
        r = self.reader(dict(self.ROBOTS, **{"https://r.jina.ai/" + URL: (200, {}, jina)}))
        res = r.read(URL)
        self.assertEqual((res.status, res.step, res.extractor), ("ok", "reader", "jina"))
        self.assertEqual(res.tried[0], ("http", "robots"))
        self.assertFalse([u for _m, u, _h in self.transport.calls if u == URL])   # never fetched by the engine

    def test_robots_with_no_reader_says_robots(self):
        r = self.reader(self.ROBOTS)
        res = r.read(URL)
        self.assertEqual(res.status, "robots")
        self.assertEqual(res.tried[:2], [("http", "robots"), ("reader:jina", "gone-404")])
        self.assertFalse([u for _m, u, _h in self.transport.calls if u == URL])

    def test_robots_skips_the_headless_browser_not_the_user_nor_the_archives(self):   # T66: decision (c)
        opened = []

        def browser(url, profile):
            opened.append(url)
            return 200, WIKI.decode(), url
        r = self.reader(dict(self.ROBOTS, **{"https://web.archive.org/cdx/": (200, {}, CDX),
                                             "https://web.archive.org/web/20240102030405id_/": (200, {}, WIKI)}),
                        browser=browser)
        res = r.read(URL)
        self.assertEqual((res.status, res.step), ("ok", "archive"))   # Wayback, read raw
        self.assertIn(("browser", "robots"), res.tried)
        self.assertEqual(opened, [])   # the engine's own browser never opened it
        asked = self.reader(self.ROBOTS, browser=browser, interactive=True).read(URL, fresh=True)
        self.assertEqual((asked.status, asked.step), ("ask", "user-browser"))   # a person may read it
        self.assertIn(("browser", "robots"), asked.tried)
        self.assertEqual(opened, [])

    def test_robots_never_opens_a_forbidden_host_to_the_readers(self):
        r = self.reader(self.ROBOTS, forbidden={"archives.example.org"})
        res = r.read(URL)
        self.assertEqual(res.status, "robots")
        self.assertIn(("reader", "forbidden-host"), res.tried)
        self.assertFalse(any("r.jina.ai" in u for _m, u, _h in self.transport.calls))

    def test_robots_on_the_free_steps_only_stops_there(self):   # read --map and --crawl
        res = self.reader(self.ROBOTS).read(URL, max_step=3)
        self.assertEqual((res.status, res.tried), ("robots", [("http", "robots")]))
        self.assertFalse(any("r.jina.ai" in u or "archive.org" in u for _m, u, _h in self.transport.calls))

    def test_failures_are_not_cached(self):
        r = self.reader({URL: (200, {}, page("anubis-challenge.html"))}, forbidden={"archives.example.org"})
        self.assertEqual(r.read(URL).status, "challenge")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, ".probandia", "cache")))


# read and passages

LONG = "\n\n".join(
    [f"Paragraphe {i} sur l'histoire du port de Cherbourg et de sa rade, sans rapport avec la famille." * 3
     for i in range(60)]
    + ["Le 26 février 1802 naît Victor Hugo, fils de Léopold Hugo, officier à Besançon."]
    + [f"Paragraphe {i} sur la marine." * 4 for i in range(60, 120)])


class Read(Base):
    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE_PROJECT, self.project)

    def run_read(self, routes, *argv):
        def build(ctx, work=None, transport=None):
            client = Client(os.path.join(self.project, ".probandia"), None, ctx.config,
                            Transport(routes), sleep=lambda s: None)
            return Reader(client, Cache(self.project, work), ctx.config, {}, forbidden={"archives.example.org"})
        out = io.StringIO()
        with mock.patch.object(reading_cmd, "build_reader", build):
            code = cli.main(["read", URL, *argv], stdout=out,
                            environ={"PROBANDIA_CONFIG_DIR": self.tmp.name}, cwd=self.project)
        return code, out.getvalue()

    def test_long_page_gives_only_matching_passages(self):
        html_page = "<html><body><article>" + "".join(f"<p>{p}</p>" for p in LONG.split("\n\n")) + \
            "</article></body></html>"
        code, out = self.run_read({URL: (200, {}, html_page)}, "--question", "naissance de Victor Hugo")
        self.assertEqual(code, 0, out)
        self.assertLessEqual(len(out.splitlines()), 40)
        lines = [l for l in out.splitlines() if l.startswith("- passage=")]
        self.assertTrue(lines[0].startswith("- passage=Le 26 février 1802 naît Victor Hugo"))
        details = re.search(r"^DETAILS=(.+)$", out, re.M).group(1)
        with open(os.path.join(self.project, details), encoding="utf-8") as fh:
            self.assertIn("Paragraphe 119", fh.read())

    def test_quote_a_passage(self):
        """TRUST1-T3: each passage has its place in the page and its digest; --quote gives the excerpt."""
        from probandia import excerpt as X

        html_page = "<html><body><article>" + "".join(f"<p>{p}</p>" for p in LONG.split("\n\n")) + \
            "</article></body></html>"
        code, out = self.run_read({URL: (200, {}, html_page)}, "--question", "naissance de Victor Hugo",
                                  "--quote", "1", "--json")
        self.assertEqual(code, 0, out)
        doc = json.loads(out)
        rows = doc["data"]["passages"]
        self.assertGreaterEqual(len(rows), 1)
        quoted = json.loads(next(x for x in doc["lines"] if x.startswith("excerpt="))[len("excerpt="):])
        self.assertEqual((quoted["kind"], quoted["offset"], quoted["sha256"]), ("page", rows[0]["offset"],
                                                                               rows[0]["sha256"]))
        self.assertEqual(doc["values"]["DIGEST"], quoted["sha256"])
        self.assertEqual(quoted["url"], URL)
        cached = Cache(self.project).entry("http", make_key("http", URL))["payload"]["text"]
        self.assertEqual(X.locate(quoted, text=cached), [])   # the page read holds it
        code, out = self.run_read({URL: (200, {}, html_page)}, "--quote", "40")
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=no-passage", out)

    def test_passages(self):
        self.assertLessEqual(max(len(b) for b in blocks(LONG)), 500)
        found = passages(LONG, "Victor Hugo Besançon", limit=12)
        self.assertTrue(found[0].startswith("Le 26 février 1802"))
        self.assertLessEqual(len(found), 12)


class Acceptance(Read):
    """An Anubis challenge page is reported "not consulted (challenge)", and no
    negative can be recorded from it."""

    def test(self):
        code, out = self.run_read({URL: (200, {}, page("anubis-challenge.html"))})
        self.assertEqual(code, 1)
        self.assertIn("REASON=challenge", out)
        self.assertIn("- not consulted (challenge)", out)
        failure = re.search(r"^FAILURE=(.+)$", out, re.M).group(1)
        from probandia.proposals import check_negatives
        from probandia.util.fs import iso, utc_now
        search = {"id": "s-01J9ZK5A000000000000000009", "ts": iso(utc_now()), "kind": "archive",
                  "query": "Hugo", "result": "negative", "failure": failure,
                  "variants": ["Hugo", "Hugot"], "window": {"from": 1797, "to": 1807},
                  "witness": {"passed": True, "ts": iso(utc_now())}}
        reasons = check_negatives([search], 24, utc_now())
        self.assertEqual(len(reasons), 1)
        self.assertIn("failed access (challenge)", reasons[0])


# the reader step and the free quotas

RECORD_MD = page("jina-ok.md").decode().split("Markdown Content:\n")[1]
FIRECRAWL = "https://api.firecrawl.dev/v2/scrape"


def firecrawl_answer(**extra):
    return json.dumps(dict({"success": True, "data": {"markdown": RECORD_MD,
                                                      "metadata": {"title": "Acte", "sourceURL": URL}}},
                           **extra))


def jina_answer(tokens):
    return json.dumps({"code": 200, "data": {"title": "Naissance de Victor Hugo", "url": URL,
                                             "content": RECORD_MD, "usage": {"tokens": tokens}}})


class ReaderQuota(Base):
    def setUp(self):
        super().setUp()
        self.ledger = Ledger(self.tmp.name, catalogue.load())

    def reader(self, routes, environ, enabled, ladder=("reader",)):
        cfg = Config({"reading.ladder": list(ladder), "providers.enabled": enabled,
                      "providers.allow_card_required": False, "providers.allow_content_reuse": True,
                      "budget.reserve_percent": 10})
        meter = Meter(self.ledger, cfg, environ, "r-1", 2)
        return Reader(self.client(routes, cfg), Cache(self.tmp.name), cfg, environ, meter=meter)

    def entries(self, provider):
        return [e for e in self.ledger.entries() if e["provider"] == provider]

    def test_a_firecrawl_read_is_counted(self):
        r = self.reader({FIRECRAWL: (200, {}, firecrawl_answer())}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        res = r.read(URL)
        self.assertEqual((res.status, res.step, res.extractor), ("ok", "reader", "firecrawl"))
        self.assertEqual([(e["operation"], e["units"], e["source"], e["research"], e["pass"])
                          for e in self.entries("firecrawl")], [("read", 1, "response", "r-1", 2)])
        self.assertEqual(self.ledger.left("firecrawl", 10), 1000 - 1 - 100)

    def test_a_reader_whose_terms_forbid_keeping_is_not_cached(self):
        """TRUST1-T4: the page a reader read is kept as long as the reader's terms allow."""
        key = make_key("http", URL)
        r = self.reader({FIRECRAWL: (200, {}, firecrawl_answer())}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        self.assertEqual(r.read(URL).status, "ok")
        self.assertIsNotNone(Cache(self.tmp.name).entry("http", key))
        os.remove(os.path.join(self.tmp.name, ".probandia", "cache", "http", f"{key}.json"))
        self.ledger.catalogue["firecrawl"]["cache_ttl"] = 0   # the terms forbid keeping results
        r = self.reader({FIRECRAWL: (200, {}, firecrawl_answer())}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        self.assertEqual(r.read(URL).status, "ok")
        self.assertIsNone(Cache(self.tmp.name).entry("http", key))

    def test_the_credits_firecrawl_reports_are_counted(self):
        r = self.reader({FIRECRAWL: (200, {}, firecrawl_answer(creditsUsed=5))}, {"FIRECRAWL_API_KEY": "k"},
                        ["firecrawl"])
        r.read(URL)
        self.assertEqual([e["units"] for e in self.entries("firecrawl")], [5])

    def test_jina_with_a_key_counts_its_tokens(self):
        r = self.reader({"https://r.jina.ai/": (200, {"Content-Type": "application/json"}, jina_answer(29727))},
                        {"JINA_API_KEY": "k"}, ["jina"])
        res = r.read(URL)
        self.assertEqual((res.status, res.step, res.extractor), ("ok", "reader", "jina"))
        self.assertTrue(res.text.startswith("Registre des naissances"))
        sent = next(h for _m, u, h in self.transport.calls if u.startswith("https://r.jina.ai/"))
        self.assertEqual(sent["Accept"], "application/json")
        self.assertEqual([e["units"] for e in self.entries("jina")], [29727])

    def test_jina_without_a_key_draws_on_no_quota(self):
        self.ledger.record("jina", "manual", 10_000_000, "manual")  # the key's tokens are all used
        r = self.reader({"https://r.jina.ai/": (200, {}, page("jina-ok.md").replace(
            b"https://example.org/besancon/ec-1802-n/45", URL.encode()))}, {}, ["jina"])
        self.assertEqual(r.read(URL).step, "reader")
        self.assertEqual([e["operation"] for e in self.entries("jina")], ["manual"])

    def test_a_read_beyond_the_quota_is_not_made(self):
        self.ledger.record("firecrawl", "manual", 1000, "manual")
        r = self.reader({}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        res = r.read(URL)
        self.assertEqual((res.status, res.quota, res.tried), ("quota", ["firecrawl"],
                                                              [("reader:firecrawl", "quota")]))
        self.assertEqual(self.transport.calls, [])

    def test_a_disabled_reader_is_skipped(self):
        r = self.reader({}, {"FIRECRAWL_API_KEY": "k"}, ["serpapi"])
        res = r.read(URL)
        self.assertEqual((res.tried, res.quota), ([], []))
        self.assertEqual(self.transport.calls, [])

    def test_an_answer_saying_the_quota_is_used_up_marks_the_reader(self):
        r = self.reader({FIRECRAWL: (402, {}, '{"error": "Insufficient credits"}')}, {"FIRECRAWL_API_KEY": "k"},
                        ["firecrawl"])
        self.assertEqual(r.read(URL).status, "quota")
        self.assertTrue(self.ledger.exhausted("firecrawl"))
        self.assertEqual(self.entries("firecrawl"), [])  # an error answer costs nothing
        calls = len(self.transport.calls)
        self.assertEqual(r.read(URL).status, "quota")
        self.assertEqual(len(self.transport.calls), calls)

    def two_tiers(self):
        """The real catalogue gives Firecrawl no second tier: a test entry does."""
        cat = dict(catalogue.load())
        cat["firecrawl"] = dict(cat["firecrawl"], costs={"read": 1, "read_js": 1, "search": 2})
        self.ledger = Ledger(self.tmp.name, cat)

    def test_an_unrendered_page_is_read_again_one_tier_up(self):
        self.two_tiers()
        answers = iter([(200, {}, json.dumps({"success": True, "data": {
                            "markdown": "Loading…", "metadata": {"title": "Acte", "sourceURL": URL}}})),
                        (200, {}, firecrawl_answer())])
        r = self.reader({FIRECRAWL: lambda: next(answers)}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        res = r.read(URL)
        self.assertEqual((res.status, res.extractor), ("ok", "firecrawl"))
        self.assertEqual(res.tried, [("reader:firecrawl", "empty"), ("reader:firecrawl:read_js", "ok")])
        sent = [json.loads(b) for b in self.transport.bodies if b]
        self.assertEqual([b.get("waitFor") for b in sent], [None, 5000])
        self.assertEqual([e["operation"] for e in self.entries("firecrawl")], ["read", "read_js"])

    def test_firecrawl_reads_each_page_once(self):
        empty = json.dumps({"success": True, "data": {
            "markdown": "Loading…", "metadata": {"title": "Acte", "sourceURL": URL}}})
        r = self.reader({FIRECRAWL: (200, {}, empty)}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        self.assertEqual(r.read(URL).tried, [("reader:firecrawl", "empty")])
        self.assertEqual([e["units"] for e in self.entries("firecrawl")], [1])

    def test_a_page_behind_a_challenge_never_goes_up(self):
        challenge = json.dumps({"success": True, "data": {
            "markdown": "Just a moment... Enable JavaScript and cookies to continue",
            "metadata": {"title": "Just a moment", "sourceURL": URL}}})
        self.two_tiers()
        r = self.reader({FIRECRAWL: (200, {}, challenge)}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"])
        res = r.read(URL)
        self.assertEqual(res.tried, [("reader:firecrawl", "challenge")])
        self.assertEqual(len([b for b in self.transport.bodies if b]), 1)

    def test_the_unblocking_readers_come_after_jina_and_firecrawl(self):
        page = "https://families.example.org/hugo"     # not an archive portal, unlike archives.example.org
        zr = (200, {"X-Request-Credits": "1", "Zr-Final-Url": page}, RECORD_MD)
        r = self.reader({"https://r.jina.ai/": (451, {}, "Unavailable For Legal Reasons"),
                         "https://api.zenrows.com/": zr},
                        {"ZENROWS_API_KEY": "k"}, ["jina", "zenrows", "scraperapi"])
        res = r.read(page)
        self.assertEqual((res.status, res.extractor), ("ok", "zenrows"))
        self.assertEqual([st for st, _s in res.tried], ["reader:jina", "reader:zenrows"])
        self.assertEqual([(e["operation"], e["units"]) for e in self.entries("zenrows")], [("read", 1.0)])
        self.assertFalse(any("scraperapi" in u for _m, u, _h in self.transport.calls))   # no key

    def test_an_unblocking_reader_reads_once_plain(self):
        empty = (200, {"X-Request-Credits": "1", "Zr-Final-Url": "https://families.example.org/hugo"}, "Loading…")
        r = self.reader({"https://r.jina.ai/": (451, {}, "x"), "https://api.zenrows.com/": empty},
                        {"ZENROWS_API_KEY": "k"}, ["zenrows"])
        res = r.read("https://families.example.org/hugo")
        self.assertEqual([t for t in res.tried if t[0] != "reader:jina"], [("reader:zenrows", "empty")])
        zr = [u for _m, u, _h in self.transport.calls if "zenrows" in u]
        self.assertEqual(len(zr), 1)
        self.assertNotIn("js_render", zr[0])
        self.assertEqual([e["units"] for e in self.entries("zenrows")], [1.0])

    def test_never_on_an_archive_portal_or_a_genealogy_database(self):
        env = {"ZENROWS_API_KEY": "k", "SCRAPERAPI_API_KEY": "k", "APIFY_TOKEN": "k"}
        for url in ("https://www.geneanet.org/fonds/individus/?nom=Hugo",
                    "https://archives.calvados.fr/ark:/52329/x", "https://anlux.lu/fr/recherche",
                    "https://www.familysearch.org/ark:/61903/1:1:X"):
            with self.subTest(url=url):
                r = self.reader({"https://r.jina.ai/": (451, {}, "x")}, env,
                                ["jina", "zenrows", "scraperapi", "apify_reader"])
                res = r.read(url)
                self.assertEqual([t for t in res.tried if t[0] != "reader:jina"],
                                 [("reader:zenrows", "archive-portal"), ("reader:scraperapi", "archive-portal"),
                                  ("reader:apify_reader", "archive-portal")])
                hosts = {u.split("/")[2] for _m, u, _h in self.transport.calls}
                self.assertFalse(hosts & {"api.zenrows.com", "api.scraperapi.com", "api.apify.com"})

    def test_a_page_gone_that_a_reader_bills_is_counted(self):
        gone = (404, {"X-Request-Credits": "1"}, '{"code": "RESP002", "status": 404}')
        r = self.reader({"https://r.jina.ai/": (451, {}, "x"), "https://api.zenrows.com/": gone},
                        {"ZENROWS_API_KEY": "k"}, ["zenrows"])
        res = r.read("https://families.example.org/hugo-gone")
        self.assertNotEqual(res.status, "ok")
        self.assertEqual([e["units"] for e in self.entries("zenrows")], [1.0])

    def test_a_reader_error_is_a_failure_not_a_page(self):
        r = self.reader({FIRECRAWL: (500, {}, '{"error": "Internal error"}')}, {"FIRECRAWL_API_KEY": "k"},
                        ["firecrawl"])
        res = r.read(URL)
        self.assertEqual((res.status, res.tried), ("blocked", [("reader:firecrawl", "blocked")]))
        self.assertFalse(self.ledger.exhausted("firecrawl"))
        self.assertEqual(self.entries("firecrawl"), [])

    def test_a_quota_does_not_hide_what_a_reader_answered(self):
        self.ledger.record("firecrawl", "manual", 1000, "manual")
        r = self.reader({"https://r.jina.ai/": (200, {}, page("jina-faq.md"))}, {"FIRECRAWL_API_KEY": "k"},
                        ["jina", "firecrawl"])
        res = r.read(URL)
        self.assertEqual(res.status, "wrong_page")
        self.assertEqual(res.tried, [("reader:firecrawl", "quota"), ("reader:jina", "wrong_page")])

    def test_a_gone_page_stays_gone(self):
        self.ledger.record("firecrawl", "manual", 1000, "manual")
        r = self.reader({URL: (404, {}, "not found")}, {"FIRECRAWL_API_KEY": "k"}, ["firecrawl"],
                        ladder=("http", "reader"))
        self.assertEqual(r.read(URL).status, "gone")


class ReadQuotaCommand(Base):
    """Optimisation 1.3: a read through a reader API lowers its free quota, and a
    read the quota cannot pay for stops before the call."""

    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE_PROJECT, self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "FIRECRAWL_API_KEY": "k",
                    "PROBANDIA_READING_LADDER": "reader", "PROBANDIA_PROVIDERS_ENABLED": "firecrawl"}

    def call(self, *argv, routes=None):
        self.transport = Transport(routes)
        build = reading_cmd.build_reader
        out = io.StringIO()
        with mock.patch.object(reading_cmd, "build_reader",
                               lambda ctx, work=None, transport=None: build(ctx, work, self.transport)):
            code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.project)
        return code, out.getvalue()

    def test_a_firecrawl_read_lowers_quota_show(self):
        line = "- provider=firecrawl ready used={} of=1000 left={} period=monthly"
        self.assertIn(line.format(0, 900), self.call("quota", "show", "firecrawl")[1])
        code, out = self.call("read", URL, routes={FIRECRAWL: (200, {}, firecrawl_answer())})
        self.assertEqual(code, 0, out)
        self.assertIn("STEP=reader", out)
        self.assertIn(line.format(1, 899), self.call("quota", "show", "firecrawl")[1])
        entry = Ledger(self.project, catalogue.load()).entries()[-1]
        self.assertEqual((entry["operation"], entry["research"]),
                         ("read", "2026-09-30-parents-of-victor-hugo"))

    def test_a_read_beyond_the_quota_stops_before_the_call(self):
        self.assertEqual(self.call("quota", "add", "firecrawl", "1000")[0], 0)
        code, out = self.call("read", URL)
        self.assertEqual(code, 4, out)
        for expected in ("STATUS=STOP", "REASON=free-quota:firecrawl", "FAILURE=quota",
                         "TRIED=reader:firecrawl:quota", "- not consulted (quota)"):
            self.assertIn(expected, out)
        self.assertNotIn("ALTERNATIVE=", out)
        self.assertEqual(self.transport.calls, [])


# Tavily's extract, a reader of the ladder (T232)

FAMILY_PAGE = "https://families.example.org/hugo"
TAVILY_EXTRACT = "https://api.tavily.com/extract"


def tavily_answer(name="extract-ok.json"):
    with open(os.path.join(ROOT, "tests", "fixtures", "http", "tavily", name), encoding="utf-8") as fh:
        return json.dumps(json.load(fh)["body"])


class TavilyReader(Base):
    reader, entries = ReaderQuota.reader, ReaderQuota.entries

    def setUp(self):
        super().setUp()
        self.ledger = Ledger(self.tmp.name, catalogue.load())
    ALL = ["jina", "firecrawl", "tavily", "zenrows"]
    ENV = {"JINA_API_KEY": "k", "FIRECRAWL_API_KEY": "k", **REUSE, "TAVILY_API_KEY": "k"}

    def spend(self, *providers):
        for p in providers:
            self.ledger.record(p, "manual", (self.ledger.catalogue[p].get("free") or {})["amount"], "manual")

    def test_tavily_reads_when_firecrawl_is_spent(self):   # T256: before Jina
        self.spend("firecrawl")
        r = self.reader({TAVILY_EXTRACT: (200, {}, tavily_answer())}, self.ENV, self.ALL)
        res = r.read(FAMILY_PAGE)
        self.assertEqual((res.status, res.step, res.extractor), ("ok", "reader", "tavily"))
        self.assertEqual(res.tried, [("reader:firecrawl", "quota"), ("reader:tavily", "ok")])
        self.assertFalse(any("r.jina.ai" in u for _m, u, _h in self.transport.calls))
        self.assertIn("Victor Marie Hugo", res.text)
        # Tavily reports 0 until five pages are read: the catalogue's 0.2 a page is counted
        self.assertEqual([(e["operation"], e["units"], e["research"]) for e in self.entries("tavily")],
                         [("read", 0.2, "r-1")])
        sent = json.loads(next(b for b in self.transport.bodies if b))
        self.assertEqual((sent["urls"], sent["extract_depth"]), (FAMILY_PAGE, "basic"))

    def test_never_on_a_host_forbidden_to_third_parties(self):
        self.spend("jina", "firecrawl")
        cfg = Config({"reading.ladder": ["reader"], "providers.enabled": self.ALL,
                      "providers.allow_card_required": False, "providers.allow_content_reuse": True,
                      "budget.reserve_percent": 10})
        r = Reader(self.client({TAVILY_EXTRACT: (200, {}, tavily_answer())}, cfg), Cache(self.tmp.name), cfg,
                   self.ENV, meter=Meter(self.ledger, cfg, self.ENV), forbidden={"families.example.org"})
        res = r.read(FAMILY_PAGE)
        self.assertEqual(res.tried, [("reader", "forbidden-host")])
        self.assertFalse(any("api.tavily.com" in u for _m, u, _h in self.transport.calls))
        self.assertEqual(self.entries("tavily"), [])

    def test_tavily_spent_leaves_the_page_to_the_next_readers(self):
        self.spend("jina", "firecrawl", "tavily")
        zr = (200, {"X-Request-Credits": "1", "Zr-Final-Url": FAMILY_PAGE}, RECORD_MD)
        r = self.reader({"https://api.zenrows.com/": zr}, dict(self.ENV, ZENROWS_API_KEY="k"), self.ALL)
        res = r.read(FAMILY_PAGE)
        self.assertEqual((res.status, res.extractor), ("ok", "zenrows"))
        self.assertEqual([t for t in res.tried if t[0] == "reader:tavily"], [("reader:tavily", "quota")])
        self.assertFalse(any("api.tavily.com" in u for _m, u, _h in self.transport.calls))

    def test_a_page_tavily_could_not_read_is_not_a_page(self):
        self.spend("jina", "firecrawl")
        r = self.reader({TAVILY_EXTRACT: (200, {}, tavily_answer("extract-failed.json"))}, self.ENV, self.ALL)
        res = r.read(FAMILY_PAGE)
        self.assertNotEqual(res.status, "ok")
        self.assertEqual(self.entries("tavily"), [])   # a failed extraction is not billed


class TavilyReadCommand(Base):
    call = ReadQuotaCommand.call

    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE_PROJECT, self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "FIRECRAWL_API_KEY": "k",
                    "PROBANDIA_READING_LADDER": "reader", "PROBANDIA_PROVIDERS_ENABLED": "firecrawl"}

    def test_read_by_tavily_says_so_and_counts_it(self):
        self.env.update({"JINA_API_KEY": "k", **REUSE, "TAVILY_API_KEY": "k",
                         "PROBANDIA_PROVIDERS_ENABLED": "jina,firecrawl,tavily"})
        self.assertEqual(self.call("quota", "add", "firecrawl", "1000")[0], 0)
        code, out = self.call("read", FAMILY_PAGE, routes={TAVILY_EXTRACT: (200, {}, tavily_answer())})
        self.assertEqual(code, 0, out)
        self.assertIn("TRIED=reader:firecrawl:quota reader:tavily:ok", out)
        entry = Ledger(self.project, catalogue.load()).entries()[-1]
        self.assertEqual((entry["provider"], entry["operation"], entry["units"]), ("tavily", "read", 0.2))

    def test_read_by_parallel_last_and_counted(self):
        text = json.loads(tavily_answer())["results"][0]["raw_content"]
        answer = json.dumps({"extract_id": "x", "results": [{"url": FAMILY_PAGE, "title": "Hugo",
                                                              "full_content": text}], "errors": []})
        self.env.update({**REUSE, "PARALLEL_API_KEY": "k", "PROBANDIA_PROVIDERS_ENABLED": "firecrawl,parallel"})
        self.assertEqual(self.call("quota", "add", "firecrawl", "1000")[0], 0)
        code, out = self.call("read", FAMILY_PAGE,
                              routes={"https://api.parallel.ai/v1/extract": (200, {}, answer)})
        self.assertEqual(code, 0, out)
        self.assertIn("TRIED=reader:firecrawl:quota reader:parallel:ok", out)
        entry = Ledger(self.project, catalogue.load()).entries()[-1]
        self.assertEqual((entry["provider"], entry["operation"], entry["units"]), ("parallel", "read", 0.001))


class ReaderOrder(Base):
    """T256: ``read <url>`` tries Firecrawl and Tavily, whose free tiers come back each
    month, before Jina, whose tokens are given once per key; ``reading.readers`` sets
    another order. Every reader is simulated: nothing leaves the machine."""

    call = ReadQuotaCommand.call
    ROUTES = {FIRECRAWL: (500, {}, '{"error": "Internal error"}'),
              TAVILY_EXTRACT: (200, {}, tavily_answer("extract-failed.json")),
              "https://r.jina.ai/": (200, {"Content-Type": "application/json"}, jina_answer(3000))}

    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE_PROJECT, self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "FIRECRAWL_API_KEY": "k",
                    **REUSE, "TAVILY_API_KEY": "k", "JINA_API_KEY": "k", "PROBANDIA_READING_LADDER": "reader",
                    "PROBANDIA_PROVIDERS_ENABLED": "jina,firecrawl,tavily"}

    def read(self):
        code, out = self.call("read", URL, routes=self.ROUTES)
        tried = next((line for line in out.splitlines() if line.startswith("TRIED=")), "")
        hosts = {u.split("/")[2] for _m, u, _h in self.transport.calls}
        return code, out, tried, hosts

    def test_firecrawl_then_tavily_then_jina(self):
        code, out, tried, _hosts = self.read()
        self.assertEqual(code, 0, out)
        self.assertEqual(tried, "TRIED=reader:firecrawl:blocked reader:tavily:blocked reader:jina:ok")

    def test_the_order_follows_reading_readers(self):
        self.env["PROBANDIA_READING_READERS"] = "tavily,jina,firecrawl"
        code, out, tried, hosts = self.read()
        self.assertEqual(code, 0, out)
        self.assertEqual(tried, "TRIED=reader:tavily:blocked reader:jina:ok")
        self.assertNotIn("api.firecrawl.dev", hosts)   # Jina read the page first

    def test_a_reader_whose_quota_cannot_pay_is_skipped_without_a_call(self):
        self.assertEqual(self.call("quota", "add", "firecrawl", "1000")[0], 0)
        code, out, tried, hosts = self.read()
        self.assertEqual(code, 0, out)
        self.assertEqual(tried, "TRIED=reader:firecrawl:quota reader:tavily:blocked reader:jina:ok")
        self.assertNotIn("api.firecrawl.dev", hosts)

    def test_the_next_free_reader_follows_the_order(self):   # the ALTERNATIVE= of a read stopped by a quota
        from types import SimpleNamespace

        from probandia import config
        from probandia.cli.search_cmd import next_free

        ctx = SimpleNamespace(project=self.project, environ=self.env, config=config.load(self.project, self.env))
        self.assertEqual(next_free(ctx, "firecrawl", "opaque", "read"), "tavily")   # not Jina, catalogue order
        self.env["PROBANDIA_READING_READERS"] = "firecrawl,jina,tavily"
        ctx.config = config.load(self.project, self.env)
        self.assertEqual(next_free(ctx, "firecrawl", "opaque", "read"), "jina")


# local and private URLs (T58)


class LocalUrls(Base):
    def test_is_local(self):
        from probandia.reading.ladder import is_local

        for url in ("http://127.0.0.1:1/x", "http://localhost:8000/", "http://[::1]/x", "http://10.0.0.5/a",
                    "http://192.168.1.20/registre", "http://172.16.3.4/", "http://169.254.10.1/",
                    "http://0.0.0.0/", "http://[fe80::1]/", "http://[fd12::1]/", "http://nas/x",
                    "http://imprimante.local/", "http://app.localhost/", "http://[::ffff:127.0.0.1]/"):
            with self.subTest(url=url):
                self.assertTrue(is_local(url))
        for url in ("https://gallica.bnf.fr/ark:/12148/x", "https://registres.example.org/", "http://8.8.8.8/",
                    "https://[2001:4860:4860::8888]/", "not a url"):
            with self.subTest(url=url):
                self.assertFalse(is_local(url))

    def test_local_url_never_leaves(self):
        url = "http://127.0.0.1:1/x"
        ledger = Ledger(self.tmp.name, catalogue.load())
        env = {"JINA_API_KEY": "k", "FIRECRAWL_API_KEY": "k", **REUSE, "TAVILY_API_KEY": "k", "ZENROWS_API_KEY": "k",
               "SCRAPERAPI_API_KEY": "k", "APIFY_TOKEN": "k"}
        cfg = Config({"providers.enabled": ["jina", "firecrawl", "tavily", "zenrows", "scraperapi", "apify_reader"],
                      "providers.allow_card_required": False, "providers.allow_content_reuse": True,
                      "budget.reserve_percent": 10})
        client = self.client({url: (200, {}, "<html><body><p>court</p></body></html>")}, cfg)
        r = Reader(client, Cache(self.tmp.name), cfg, env, meter=Meter(ledger, cfg, env, "r-1", 1))
        res = r.read(url)
        self.assertNotEqual(res.status, "ok")
        steps = [step for step, _s in res.tried]
        self.assertFalse([s for s in steps if s.startswith(("reader", "archive"))], res.tried)
        self.assertIn(("local-url", "skipped"), res.tried)
        hosts = {u.split("/")[2] for _m, u, _h in self.transport.calls}
        self.assertEqual(hosts, {"127.0.0.1:1"})   # only the page itself, and its robots.txt
        self.assertEqual(ledger.entries(), [])


# read --map, --crawl, --extract (T229-T231): the command, its transport recorded


SITE = "https://registres.example.org/"
FC_MAP = "https://api.firecrawl.dev/v2/map"
TV_MAP = "https://api.tavily.com/map"


def http_fixture(provider, name):
    with open(os.path.join(ROOT, "tests", "fixtures", "http", provider, name), encoding="utf-8") as fh:
        return json.dumps(json.load(fh)["body"])


class Operation(Base):
    """``read <url> --map`` and its siblings, through the real reader of the command,
    every answer recorded."""

    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE_PROJECT, self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "FIRECRAWL_API_KEY": "k",
                    **REUSE, "TAVILY_API_KEY": "k", "SGAI_API_KEY": "k",
                    "PROBANDIA_PROVIDERS_ENABLED": "jina,firecrawl,tavily,scrapegraph"}

    def call(self, *argv, routes=None):
        self.transport = Transport(routes)
        build = reading_cmd.build_reader

        def built(ctx, work=None, transport=None):
            reader = build(ctx, work, self.transport)
            reader.client.sleep = lambda seconds: None   # the pace per host, not waited for here
            return reader
        out = io.StringIO()
        with mock.patch.object(reading_cmd, "build_reader", built):
            code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.project)
        return code, out.getvalue()

    def ledger(self):
        return Ledger(self.project, catalogue.load()).entries()

    def hosts(self):
        return {u.split("/")[2] for _m, u, _h in self.transport.calls}

    def spend(self, *providers):
        for p in providers:
            amount = (catalogue.load()[p].get("free") or {})["amount"]
            self.assertEqual(self.call("quota", "add", p, str(amount))[0], 0)

    def value(self, out, key):
        m = re.search(rf"^{key}=(.*)$", out, re.M)
        return m.group(1) if m else None


class ReadMap(Operation):
    SITEMAPS = {SITE + "robots.txt": (200, {}, "User-agent: *\nDisallow: /prive/\n"
                                              "Sitemap: https://registres.example.org/sitemap-index.xml\n"),
                SITE + "sitemap-index.xml": (200, {}, page("sitemap-index.xml")),
                SITE + "sitemap-naissances.xml": (200, {}, page("sitemap-naissances.xml")),
                SITE + "sitemap-mariages.xml": (200, {}, page("sitemap-mariages.xml"))}

    def test_a_published_sitemap_needs_no_third_party(self):
        code, out = self.call("read", SITE, "--map", routes=self.SITEMAPS)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "SOURCE"), self.value(out, "URLS")), ("sitemap", "5"))
        self.assertIn("- url=https://registres.example.org/naissances/besancon/1802", out)
        self.assertIn("- url=https://www.registres.example.org/naissances/nancy/1802", out)   # www. aside
        self.assertNotIn("other.example.net", out)   # same host only, the foreign index not followed
        self.assertLessEqual(len(out.splitlines()), 40)
        self.assertEqual(self.hosts(), {"registres.example.org"})
        self.assertEqual(self.ledger(), [])
        with open(os.path.join(self.project, self.value(out, "DETAILS")), encoding="utf-8") as fh:
            self.assertIn("mariages/les-auxons/1797", fh.read())

    def test_links_filter_the_map(self):
        code, out = self.call("read", SITE, "--map", "--links", "besancon", routes=self.SITEMAPS)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "URLS"), self.value(out, "MATCHED")), ("5", "3"))
        self.assertNotIn("nancy", out.split("DETAILS=")[0])

    def test_sitemap_xml_when_robots_names_none(self):
        routes = {SITE + "sitemap.xml": (200, {}, page("sitemap-mariages.xml"))}
        code, out = self.call("read", SITE + "mariages", "--map", routes=routes)
        self.assertEqual((code, self.value(out, "SOURCE"), self.value(out, "URLS")), (0, "sitemap", "2"), out)

    def test_the_links_of_the_page_when_there_is_no_sitemap(self):
        html = ("<html><body><article>" + "<p>Les registres paroissiaux et d'état civil de Besançon.</p>" * 40
                + '<a href="/naissances/1802">Naissances 1802</a> <a href="mariages/1822#haut">Mariages</a>'
                + '<a href="https://other.example.net/x">Ailleurs</a></article></body></html>')
        code, out = self.call("read", SITE + "registres", "--map", routes={SITE + "registres": (200, {}, html)})
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "SOURCE"), self.value(out, "URLS")), ("links", "2"))
        self.assertIn("- url=https://registres.example.org/mariages/1822", out)
        self.assertNotIn("api.firecrawl.dev", self.hosts())

    def test_without_a_plan_firecrawl_then_tavily_then_stop(self):
        routes = {FC_MAP: (200, {}, http_fixture("firecrawl", "map-ok.json")),
                  TV_MAP: (200, {}, http_fixture("tavily", "map-ok.json"))}
        code, out = self.call("read", SITE, "--map", routes=routes)
        self.assertEqual((code, self.value(out, "SOURCE"), self.value(out, "URLS")), (0, "firecrawl", "4"), out)
        self.assertIn("TRIED=sitemap:none links:gone map:firecrawl:ok", out)
        self.assertEqual([(e["provider"], e["operation"], e["units"]) for e in self.ledger()],
                         [("firecrawl", "map", 1.0)])
        self.spend("firecrawl")
        code, out = self.call("read", SITE, "--map", "--fresh", routes=routes)
        self.assertEqual((code, self.value(out, "SOURCE")), (0, "tavily"), out)
        self.assertIn("map:firecrawl:quota map:tavily:ok", out)
        self.assertEqual([(e["provider"], e["operation"]) for e in self.ledger()][-1], ("tavily", "map"))
        self.spend("tavily")
        code, out = self.call("read", SITE, "--map", "--fresh", routes=routes)
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP", out)
        self.assertIn("REASON=free-quota:firecrawl", out)
        self.assertNotIn("ALTERNATIVE=", out)
        self.assertFalse(self.hosts() & {"api.firecrawl.dev", "api.tavily.com"})

    def test_an_archive_host_is_never_given_to_a_third_party(self):
        url = "https://archives.aisne.fr/recherche"   # third_party: forbidden in archives-fr-ad.yaml
        code, out = self.call("read", url, "--map", routes={FC_MAP: (200, {}, http_fixture("firecrawl", "map-ok.json"))})
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=no-map", out)
        self.assertIn("third-party:forbidden-host", out)
        self.assertNotIn("api.firecrawl.dev", self.hosts())
        self.assertEqual(self.ledger(), [])

    def test_a_page_robots_disallows_is_never_given_to_a_third_party(self):   # T66
        routes = {SITE + "robots.txt": (200, {}, "User-agent: *\nDisallow: /prive/\n"),
                  FC_MAP: (200, {}, http_fixture("firecrawl", "map-ok.json"))}
        code, out = self.call("read", SITE + "prive/notes", "--map", routes=routes)
        self.assertEqual(code, 1, out)
        self.assertIn("TRIED=sitemap:none links:robots third-party:robots", out)
        self.assertFalse(self.hosts() & {"api.firecrawl.dev", "api.tavily.com", "r.jina.ai"})
        self.assertFalse([u for _m, u, _h in self.transport.calls if "/prive/" in u])
        self.assertEqual(self.ledger(), [])

    def test_a_local_url_is_never_given_to_a_third_party(self):
        code, out = self.call("read", "http://127.0.0.1:1/", "--map",
                              routes={FC_MAP: (200, {}, http_fixture("firecrawl", "map-ok.json"))})
        self.assertEqual(code, 1, out)
        self.assertIn("third-party:local-url", out)
        self.assertEqual(self.hosts(), {"127.0.0.1:1"})

    def test_a_second_call_is_served_by_the_cache(self):
        routes = {FC_MAP: (200, {}, http_fixture("firecrawl", "map-ok.json"))}
        self.assertEqual(self.call("read", SITE, "--map", routes=routes)[0], 0)
        entries = len(self.ledger())
        code, out = self.call("read", SITE, "--map", routes=routes)
        self.assertEqual((code, self.value(out, "CACHE"), self.value(out, "SOURCE")), (0, "hit", "firecrawl"), out)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(self.ledger()), entries)   # 0 unit

    def test_map_refuses_grep_and_select(self):
        for option in ("--grep", "--select"):
            with self.subTest(option=option):
                code, out = self.call("read", SITE, "--map", option, "x")
                self.assertEqual(code, 2, out)


def site_of_30_pages():
    """A site of 30 list pages: each links to the next three, to a page that robots.txt
    forbids and to a page outside the lists; page 7 names Victor Hugo."""
    routes = {SITE + "robots.txt": (200, {}, "User-agent: *\nDisallow: /prive/\n")}
    for k in range(1, 31):
        body = "".join(f"<p>Registre {k}, acte {i} : naissance à Nancy, sans rapport avec la famille.</p>"
                       for i in range(40))
        if k == 7:
            body += "<p>Le 26 février 1802 naît Victor Hugo, fils de Léopold Hugo, à Besançon.</p>"
        links = "".join(f'<a href="/liste?page={j}">page {j}</a>' for j in range(k + 1, min(k + 4, 31)))
        links += '<a href="/prive/notes?page=99">notes</a><a href="/mentions">mentions légales</a>'
        routes[SITE + f"liste?page={k}"] = (200, {}, f"<html><head><title>Liste des registres, page {k}</title>"
                                                     f"</head><body><article>{body}</article>{links}</body></html>")
    return routes


class ReadCrawl(Operation):
    def test_the_engine_crawls_by_itself(self):
        code, out = self.call("read", SITE + "liste?page=1", "--crawl", "10", "--links", "page=",
                              "--question", "naissance de Victor Hugo à Besançon", routes=site_of_30_pages())
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "SOURCE"), self.value(out, "PAGES")), ("http", "10"))
        self.assertLessEqual(len(out.splitlines()), 40)
        first = next(line for line in out.splitlines() if line.startswith("- passage="))
        self.assertTrue(first.startswith("- passage=https://registres.example.org/liste?page=7 Le 26 février 1802"),
                        first)
        self.assertEqual(self.hosts(), {"registres.example.org"})   # no third party
        pages = [u for _m, u, _h in self.transport.calls if "liste?page=" in u]
        self.assertEqual(len(pages), 10)
        self.assertFalse([u for _m, u, _h in self.transport.calls if "/prive/" in u])   # robots.txt obeyed
        self.assertFalse([u for _m, u, _h in self.transport.calls if "/mentions" in u])  # --links chooses
        self.assertEqual(self.ledger(), [])
        with open(os.path.join(self.project, self.value(out, "DETAILS")), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("<!-- https://registres.example.org/liste?page="), 10)

    def test_a_crawl_beyond_the_ceiling_is_brought_back_to_it(self):
        code, out = self.call("read", SITE + "liste?page=1", "--crawl", "50", "--links", "page=",
                              routes=site_of_30_pages())
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "PAGES"), self.value(out, "ASKED")), ("20", "50"))
        self.assertIn("- 50 pages asked, 20 read at most (read.crawl_max_pages)", out)
        self.assertLessEqual(len(out.splitlines()), 40)

    FC_CRAWL = "https://api.firecrawl.dev/v2/crawl"
    FC_JOB = FC_CRAWL + "/0b6e1f9a-3c41-4d2e-9b7a-5f2c8d1e4a10"

    def firecrawl_routes(self, start_url):
        return {start_url: (200, {}, page("eluxemburgensia-search.html")),   # an empty application shell
                self.FC_CRAWL: (200, {}, http_fixture("firecrawl", "crawl-start.json")),
                self.FC_JOB: (200, {}, http_fixture("firecrawl", "crawl-completed.json"))}

    def test_an_empty_start_page_goes_to_a_third_party(self):
        self.env["PROBANDIA_PROVIDERS_ENABLED"] = "firecrawl"
        start = SITE + "naissances"
        code, out = self.call("read", start, "--crawl", "3", "--question", "Victor Hugo",
                              routes=self.firecrawl_routes(start))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "SOURCE"), self.value(out, "PAGES")), ("firecrawl", "2"))  # the 404 left out
        self.assertIn("TRIED=http:template crawl:0-pages crawl:firecrawl:ok", out)
        self.assertIn("- passage=https://registres.example.org/naissances/1802 ", out)
        self.assertEqual([(e["provider"], e["operation"], e["units"]) for e in self.ledger()],
                         [("firecrawl", "crawl", 3.0)])
        # the quota left cannot pay for the crawl announced: stopped before the call
        self.assertEqual(self.call("quota", "add", "firecrawl", "895")[0], 0)   # 2 left, reserve kept
        code, out = self.call("read", start, "--crawl", "5", "--fresh", routes=self.firecrawl_routes(start))
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP", out)
        self.assertNotIn("api.firecrawl.dev", self.hosts())

    def test_an_archive_host_is_never_given_to_a_third_party(self):
        start = "https://archives.aisne.fr/recherche"   # third_party: forbidden in archives-fr-ad.yaml
        code, out = self.call("read", start, "--crawl", "3", routes=self.firecrawl_routes(start))
        self.assertEqual(code, 1, out)
        self.assertIn("third-party:forbidden-host", out)
        self.assertIn("- not consulted (template)", out)
        self.assertNotIn("api.firecrawl.dev", self.hosts())
        self.assertEqual(self.ledger(), [])

    def test_a_start_page_robots_disallows_is_never_given_to_a_third_party(self):   # T66
        start = SITE + "prive/notes"
        routes = dict(self.firecrawl_routes(start), **{SITE + "robots.txt": (200, {}, "User-agent: *\nDisallow: /prive/\n")})
        code, out = self.call("read", start, "--crawl", "3", routes=routes)
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=robots", out)
        self.assertFalse(self.hosts() & {"api.firecrawl.dev", "api.tavily.com", "r.jina.ai"})
        self.assertFalse([u for _m, u, _h in self.transport.calls if "/prive/" in u])
        self.assertEqual(self.ledger(), [])

    def test_crawl_refuses_grep_and_a_count_below_one(self):
        self.assertEqual(self.call("read", SITE, "--crawl", "3", "--grep", "x")[0], 2)
        self.assertEqual(self.call("read", SITE, "--crawl", "0")[0], 2)
        self.assertEqual(self.call("read", SITE, "--crawl", "3", "--map")[0], 2)


class ReadExtract(Operation):
    RESEARCH = "2026-09-30-parents-of-victor-hugo"
    FC_SCRAPE = "https://api.firecrawl.dev/v2/scrape"
    SG_EXTRACT = "https://v2-api.scrapegraphai.com/api/extract"
    INVENTORY = SITE + "inventaire"
    ASK = "the registers: cote, commune, years"

    def setUp(self):
        super().setUp()
        self.env["PROBANDIA_PROVIDERS_ALLOW_CONTENT_REUSE"] = "true"   # ScrapeGraph's free plan

    def routes(self):
        return {self.FC_SCRAPE: (200, {}, http_fixture("firecrawl", "extract-ok.json")),
                self.SG_EXTRACT: (200, {}, http_fixture("scrapegraph", "extract-ok.json"))}

    def extract(self, *extra, url=None):
        return self.call("read", url or self.INVENTORY, "--extract", self.ASK, "--research", self.RESEARCH,
                         *extra, routes=self.routes())

    def test_firecrawl_gives_the_json_written_to_work(self):
        code, out = self.extract()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "SOURCE"), self.value(out, "ITEMS")), ("firecrawl", "3"))
        path = self.value(out, "EXTRACT")
        self.assertTrue(path.startswith(f"families/hugo/research/{self.RESEARCH}/work/"), path)
        with open(os.path.join(self.project, path), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["registres"][2]["commune"], "Les Auxons")
        self.assertIn('- item={"cote": "3E 56/1", "commune": "Besançon", "years": "1800-1802"}', out)
        self.assertLessEqual(len(out.splitlines()), 40)
        self.assertEqual([(e["provider"], e["operation"], e["units"]) for e in self.ledger()],
                         [("firecrawl", "extract", 5.0)])
        sent = json.loads(next(b for b in self.transport.bodies if b))
        self.assertEqual(sent["formats"][0], {"type": "json", "prompt": self.ASK})

    def test_a_schema_goes_with_the_instruction(self):
        schema = os.path.join(self.tmp.name, "schema.json")
        with open(schema, "w", encoding="utf-8") as fh:
            json.dump({"type": "object", "properties": {"registres": {"type": "array"}}}, fh)
        self.assertEqual(self.extract("--schema", schema)[0], 0)
        sent = json.loads(next(b for b in self.transport.bodies if b))
        self.assertEqual(sent["formats"][0]["schema"]["properties"], {"registres": {"type": "array"}})
        self.assertEqual(self.call("read", SITE, "--map", "--schema", schema)[0], 2)

    def test_scrapegraph_when_firecrawl_is_spent_then_stop(self):
        self.spend("firecrawl")
        code, out = self.extract()
        self.assertEqual((code, self.value(out, "SOURCE"), self.value(out, "ITEMS")), (0, "scrapegraph", "2"), out)
        self.assertIn("TRIED=extract:firecrawl:quota extract:scrapegraph:ok", out)
        self.assertEqual([(e["provider"], e["operation"], e["units"]) for e in self.ledger()][-1],
                         ("scrapegraph", "extract", 5.0))
        self.assertEqual(self.transport.calls[-1][2].get("SGAI-APIKEY"), "k")
        self.spend("scrapegraph")
        code, out = self.extract("--fresh")
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP", out)
        self.assertFalse(self.hosts() & {"api.firecrawl.dev", "v2-api.scrapegraphai.com"})

    def test_a_host_forbidden_to_third_parties_is_refused(self):
        url = "https://archives.aisne.fr/inventaire"   # third_party: forbidden in archives-fr-ad.yaml
        code, out = self.extract(url=url)
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=forbidden-host", out)
        self.assertIn(f"NEXT=read {url} --select <selector>", out)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.ledger(), [])

    def test_a_living_person_never_goes_to_a_provider_that_reuses_content(self):
        from tests.unit.test_report import LIVING_PERSON

        persons = os.path.join(self.project, "families", "hugo", "index", "persons.yaml")
        doc = yamlio.load(persons)
        doc["persons"].append(LIVING_PERSON)
        yamlio.dump(persons, doc)
        self.spend("firecrawl")
        code, out = self.call("read", self.INVENTORY, "--extract", "the acts that name Camille Vernier",
                              "--research", self.RESEARCH, routes=self.routes())
        self.assertEqual(code, 4, out)
        self.assertIn("extract:scrapegraph:living-person-name", out)
        self.assertNotIn("ALTERNATIVE=scrapegraph", out)
        self.assertIn("presumed living", out)
        self.assertNotIn("v2-api.scrapegraphai.com", self.hosts())
        self.assertFalse([e for e in self.ledger() if e["provider"] == "scrapegraph"])

    def test_a_second_identical_call_is_served_by_the_cache(self):
        self.assertEqual(self.extract()[0], 0)
        entries = len(self.ledger())
        code, out = self.extract()
        self.assertEqual((code, self.value(out, "CACHE"), self.value(out, "SOURCE")), (0, "hit", "firecrawl"), out)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(self.ledger()), entries)
        # another instruction is another extraction
        code, out = self.call("read", self.INVENTORY, "--extract", "the communes only", "--research", self.RESEARCH,
                              routes=self.routes())
        self.assertEqual(self.value(out, "CACHE"), "miss")

    def test_extract_refuses_the_options_of_a_reading(self):
        for option in ("--grep", "--select", "--links", "--question"):
            with self.subTest(option=option):
                self.assertEqual(self.call("read", SITE, "--extract", "x", option, "y")[0], 2)


class CacheCommand(unittest.TestCase):
    """T64: cache stats shows what the cache holds and saved the quotas; cache clear purges what it says."""

    DAY = 86400

    def setUp(self):
        from tests.unit.test_keyboard import KeyboardCase

        self.kb = KeyboardCase()
        self.kb.setUp()
        self.addCleanup(self.kb.tmp.cleanup)
        self.dir, self.now = self.kb.dir, 1_800_000_000
        cache = Cache(self.dir, clock=lambda: self.now - 40 * self.DAY)
        cache.put("brave", make_key("brave", "hugo old"), {"results": []}, "ok", 90 * self.DAY, by="brave", units=1)
        cache.put("http", make_key("http", "https://example.org/old"), {"text": "x"}, "ok", 7 * self.DAY)
        cache = Cache(self.dir, clock=lambda: self.now - 2 * self.DAY)
        cache.put("brave", make_key("brave", "hugo new"), {"results": []}, "ok", 90 * self.DAY, by="brave", units=1)
        cache.put("tavily", make_key("tavily", "hugo"), {"results": []}, "ok", 90 * self.DAY, by="tavily", units=2)
        cache.put("http", make_key("http", "https://example.org/a"), {"text": "x"}, "ok", 90 * self.DAY,
                  by="firecrawl", units=1)
        cache.put("native-claude-code", make_key("native:claude-code", "hugo"), {"urls": []}, "ok", 90 * self.DAY,
                  by="native")
        served = Cache(self.dir, clock=lambda: self.now)
        for _ in range(3):   # three answers served, 2 credits each
            self.assertIsNotNone(served.get("tavily", make_key("tavily", "hugo")))
        served.get("http", make_key("http", "https://example.org/a"))
        self.files = lambda: sorted(os.path.relpath(os.path.join(r, f), self.dir).replace(os.sep, "/")
                                    for r, _d, fs in os.walk(os.path.join(self.dir, ".probandia", "cache"))
                                    for f in fs)

    def call(self, *argv, keys=None, terminal=False):
        with mock.patch("time.time", return_value=self.now):
            return self.kb.call(*argv, keys=keys, terminal=terminal)

    def test_stats_by_provider(self):
        code, out = self.call("cache", "stats")
        self.assertEqual(code, 0, out)
        self.assertIn("ENTRIES=6\n", out)
        self.assertIn("SERVED=4\n", out)
        self.assertIn("EXPIRED=1\n", out)   # the old page, past its 7 days
        rows = {x.split()[1].split("=")[1]: x for x in out.splitlines() if x.startswith("- provider=")}
        self.assertEqual(set(rows), {"brave", "http", "tavily", "firecrawl", "native"})
        self.assertIn("tavily entries=1 bytes=", rows["tavily"])
        self.assertIn("served=3 saved=6", rows["tavily"])
        self.assertIn("served=1 saved=1", rows["firecrawl"])
        self.assertIn("entries=2 ", rows["brave"])
        self.assertIn("oldest=40.0d served=0 saved=0", rows["brave"])
        data = json.loads(self.call("cache", "stats", "--provider", "tavily", "--json")[1])["data"]["cache"]
        self.assertEqual([(r["provider"], r["entries"], r["served"], r["saved"]) for r in data],
                         [("tavily", 1, 3, 6)])

    def test_clear_a_provider_after_confirmation(self):
        before = self.files()
        code, out = self.call("cache", "clear", "--provider", "brave", keys=["n"], terminal=True)
        self.assertEqual(code, 4, out)
        self.assertIn("Remove 2 cache entries", out)
        self.assertEqual(self.files(), before)   # declined: nothing removed
        code, out = self.call("cache", "clear", "--provider", "brave", keys=["y"], terminal=True)
        self.assertEqual(code, 0, out)
        self.assertEqual([f for f in before if f not in self.files()],
                         sorted(f for f in before if f.startswith(".probandia/cache/brave/")))
        self.assertEqual(len(self.files()), 4)

    def test_clear_older_than(self):
        code, out = self.call("cache", "clear", "--older-than", "30d", "--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("REMOVED=2\n", out)
        self.assertIn("- removed=brave 1", out)
        self.assertIn("- removed=http 1", out)
        code, out = self.call("cache", "stats")
        self.assertIn("ENTRIES=4\n", out)
        self.assertIn("SERVED=4\n", out)   # what was served stays counted
        self.assertEqual(self.call("cache", "clear", "--older-than", "soon")[0], 2)
        self.assertEqual(self.call("cache", "stats", "--older-than", "3d")[0], 2)
