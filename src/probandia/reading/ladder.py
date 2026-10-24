"""The reading ladder: ``read <url>`` tries each step in order, and stops at the
first one the detector reports as ``ok``.

| Step | Name | When | What |
|---|---|---|---|
| 0 | cache | a live entry, judged by the current detector rules | served |
| 1 | api | the URL matches a connector pattern | the connector operation |
| 2 | http | ``robots.txt`` allows the page | a polite ``GET`` through the HTTP client |
| 3 | extract | HTML from step 2 | trafilatura if installed, otherwise the built-in extractor |
| 4 | reader | the host does not forbid third-party readers | ``reading.readers`` (Firecrawl, Tavily, Jina, Parallel), then the unblocking readers |
| 5 | browser | Playwright is installed, ``robots.txt`` allows the page | headless Chromium, one cookie jar per host |
| 6 | user-browser | a skill is running and the browser lock is free | ``STATUS=ASK``, ``QUESTION=use_browser`` |
| 7 | archive | the page is gone (404, 410) or refused | the latest Wayback capture, read raw |

``robots.txt`` rules the crawlers, not one page asked for the user (T66): when it
disallows the page, the engine does not fetch it itself, neither by HTTP nor by its
headless browser (``http:robots``, ``browser:robots``), but the ladder goes on to the
readers, the user's browser and the web archives, as for a page the site refused. ``read --map`` and ``--crawl`` read by the free steps only
(``max_step`` 3): there, ``robots.txt`` stays the rule, for every page they follow,
and a page it disallows is never handed to a third party. A local or private URL
(``is_local``: loopback, private network, ``.local``) skips the reader and archive
steps, noted ``local-url:skipped``: it never leaves for a third party (T58).

The readers come in the order of ``reading.readers`` (T256): by default Firecrawl and
Tavily, whose free tiers come back each month, before Jina, whose grant of tokens is
given once per key, and Parallel last, slow on a page it has not cached; a reader left out of the setting is not used by the ladder.

With a ``Meter``, the reader step draws on the free quotas like ``search``: a
reader that is not enabled or has no key is skipped; one whose quota left cannot
pay for the read is not called (``reader:<name>`` tried as ``quota``); every call
made is counted, and an answer saying that the quota is used up marks the reader
exhausted (tried as ``quota`` too). A page left unread while every reader was
held back by its quota ends as ``quota``, unless the site said the page is gone.

A reader reads at its cheapest tier first (``catalogue.TIERS``). It goes one tier
up (``read_js``, a longer wait for scripts) only when the detector finds the page
unrendered: an application shell, too little text, or a script redirect. A page
blocked or behind a challenge never goes up: the anti-bot tiers are not used.

The unblocking readers (ZenRows, ScraperAPI, Apify's reader: ``unblocker = true``
in the catalogue) come after those of ``reading.readers``, and never on an archive portal
or a genealogy database (decision 1.1): the hosts of the archive catalogues
(package and project), the known portals of ``PORTALS``, and any host whose name
starts with ``archives``. They are tried as ``archive-portal`` there. They read
once, at their plain tier: never their JavaScript tier by themselves.
"""
import json
import os
import re
import urllib.parse

from probandia.config.registry import READERS
from probandia.reading import detector
from probandia.reading.cache import make_key, ttl_for
from probandia.reading.extract import extract
from probandia.util.http import FileLock, RobotsDenied

STEPS = ("cache", "api", "http", "extract", "reader", "browser", "user-browser", "archive")
GONE = {404, 410}
REFUSED = {detector.BLOCKED, detector.CHALLENGE, "robots"}
# Verdicts a higher reading tier may cure: the page's scripts had not run.
UNRENDERED = {detector.TEMPLATE, detector.EMPTY, detector.REDIRECT}
FIRECRAWL_WAIT_MS = 5000
# Archive portals and genealogy databases outside the archive catalogues: no
# unblocking reader there (decision 1.1). A host matches itself and its subdomains.
PORTALS = frozenset((
    "geneanet.org", "ancestry.com", "ancestry.fr", "ancestry.co.uk", "ancestry.de", "ancestry.ca",
    "ancestry.com.au", "myheritage.com", "myheritage.fr", "myheritage.de", "filae.com", "geni.com",
    "findagrave.com", "billiongraves.com", "familysearch.org", "wikitree.com", "francearchives.gouv.fr",
    "archives-nationales.culture.gouv.fr", "anlux.lu", "matricula-online.eu", "archive.org",
))
ARCHIVE_HOST = re.compile(r"(^|\.)archives?[-.]")


class ReadResult:
    def __init__(self, url):
        self.url = url
        self.status = None      # ok, a detector status, robots, ask
        self.step = None
        self.text = ""
        self.html = None        # the page's HTML when a step had it: read --links, --select (D1)
        self.final_url = url
        self.tried = []         # (step name, status)
        self.cache = "miss"
        self.extractor = None
        self.quota = []         # readers held back by their free quota
        self.login = None       # the archive's login block when a sign-in screen stopped the read
        self.spent = []         # (reader, tier, units) charged to a free quota

    @property
    def ok(self):
        return self.status == detector.OK


def archive_hosts(project, data_root):
    """Every host of the archive catalogues (package and project), with ``PORTALS``."""
    from probandia.util import yamlio

    hosts = set(PORTALS)
    from probandia.archives.finder import catalogue_paths

    for path in catalogue_paths(project, data_root):
        if path and os.path.isfile(path):
            data = yamlio.load(path) or []
            entries = data.get("archives", []) if isinstance(data, dict) else data
            for entry in entries:
                hosts.update(h.lower() for h in ((entry or {}).get("access") or {}).get("hosts", []))
    return hosts


def is_local(url):
    """True when ``url`` names a host of this machine or of a private network: a
    loopback, private, link-local or unspecified address (``ipaddress``),
    ``localhost``, a name in ``.local`` or ``.localhost``, or a name without a dot.
    Such a URL never goes to a third party (T58): not to a reader, not to the web
    archives, not to a map, a crawl or an extraction. No name is resolved."""
    import ipaddress

    try:
        host = (urllib.parse.urlsplit(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return host == "localhost" or host.endswith((".local", ".localhost")) or "." not in host
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified


def reader_order(config):
    """The readers of the reader step, in the order of ``reading.readers`` (T256)."""
    if config is not None:
        try:
            return [r for r in config.get("reading.readers") if r in READERS]
        except KeyError:   # a configuration that predates the setting
            pass
    return list(READERS)


def is_portal(host, portals=PORTALS):
    host = host.lower().removeprefix("www.")
    return bool(ARCHIVE_HOST.search(host)) or any(host == p or host.endswith("." + p) for p in portals)


def forbidden_hosts(project, data_root):
    """Hosts where third-party readers are forbidden, from the archive catalogues."""
    from probandia.util import yamlio

    hosts = set()
    from probandia.archives.finder import catalogue_paths

    for path in catalogue_paths(project, data_root):
        if path and os.path.isfile(path):
            data = yamlio.load(path) or []
            entries = data.get("archives", []) if isinstance(data, dict) else data
            for entry in entries:
                access = (entry or {}).get("access") or {}
                if access.get("third_party") == "forbidden":
                    hosts.update(h.lower() for h in access.get("hosts", []))
    return hosts


class _LoginWall(Exception):
    """A sign-in screen stopped the ladder (D8)."""


def login_sites(project, root):
    """{host: login block with its archive id} of the archives that need a session."""
    from probandia.archives.finder import load_catalogue

    out = {}
    for archive_id, entry in load_catalogue(project).items():
        login = entry.get("login") or {}
        if login.get("required"):
            for h in (entry.get("access") or {}).get("hosts") or []:
                out[h.lower()] = dict(login, archive=archive_id)
    return out


class Reader:
    def __init__(self, client, cache, config=None, environ=None, connectors=(), browser=None,
                 forbidden=(), interactive=False, state_dir=None, meter=None, portals=PORTALS, logins=None):
        self.client = client
        self.cache = cache
        self.config = config
        self.environ = environ or {}
        self.connectors = list(connectors)      # [(compiled pattern, callable(url) -> (status, body, headers, kind))]
        self.browser = browser                  # callable(url, profile_dir) -> (status, body, final_url)
        self.forbidden = {h.lower() for h in forbidden}
        self.interactive = interactive
        self.state_dir = state_dir
        self.meter = meter                      # providers.meter.Meter: the free quotas of the readers
        self.portals = {h.lower() for h in portals}  # no unblocking reader on these hosts
        self.logins = dict(logins or {})        # host -> the archive's login block (optimize 3.2)

    def steps(self, max_step=None):
        order = list(STEPS)
        if self.config is not None:
            try:
                order = [s for s in self.config.get("reading.ladder") if s in STEPS]
            except KeyError:
                pass
        if max_step is not None:
            order = [s for s in order if STEPS.index(s) <= max_step]
        return order

    def login_for(self, url):
        """The login block of the archive that serves ``url``, or None."""
        host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
        for h, block in self.logins.items():
            if host == h or host.endswith("." + h):
                return block
        return None

    def _check(self, result, step, status, body, final_url=None, headers=None, kind="http",
               expect=(), no_results=None):
        login = self.login_for(result.url)
        verdict, _rule = detector.classify(status, body, result.url, final_url, headers, kind,
                                           expect, no_results, login=login)
        result.tried.append((step, verdict if status not in GONE else f"gone-{status}"))
        if verdict == detector.LOGIN:
            result.login = login or {}
            raise _LoginWall()
        return verdict

    def read(self, url, fresh=False, max_step=None, expect=(), no_results=None):
        """Reads ``url`` down the ladder; a sign-in screen stops it (status ``login``):
        no other step could read what only the user's session opens."""
        result = ReadResult(url)
        try:
            return self._read(result, url, fresh, max_step, expect, no_results)
        except _LoginWall:
            result.status = detector.LOGIN
            return result

    def _read(self, result, url, fresh, max_step, expect, no_results):
        key = make_key("http", url)
        steps = self.steps(max_step)
        host = urllib.parse.urlsplit(url).netloc.lower()
        gone = refused = robots = False
        html_body = None
        local = is_local(url)

        for step in steps:
            if local and step in ("reader", "archive"):
                if ("local-url", "skipped") not in result.tried:   # T58: never sent to a third party
                    result.tried.append(("local-url", "skipped"))
                continue
            if step == "cache":
                payload = self.cache.get("http", key, fresh)
                if payload and payload.get("detector") == detector.VERSION:
                    result.cache = "hit"
                    result.html = payload.get("html")
                    return self._done(result, "cache", payload["text"], payload.get("final_url"),
                                      payload.get("extractor"), store=False)
            elif step == "api":
                for pattern, run in self.connectors:
                    if pattern.search(url):
                        status, body, headers, kind = run(url)
                        if self._check(result, "api", status, body, None, headers, kind, expect,
                                       no_results) == detector.OK:
                            text = body if isinstance(body, str) else body.decode("utf-8", "replace")
                            if kind == "http":
                                result.html = text
                                text, result.extractor = extract(text)
                            return self._done(result, "api", text)
                        break
            elif step == "http":
                try:
                    resp = self.client.get(url)
                except RobotsDenied:   # T66: not fetched by the engine; the next steps may read it
                    result.tried.append(("http", "robots"))
                    robots = True
                    continue
                if resp.status in GONE:
                    gone = True
                    result.tried.append(("http", f"gone-{resp.status}"))
                    continue
                verdict = self._check(result, "http", resp.status, resp.body, resp.final_url,
                                      resp.headers, "http", expect, no_results)
                if verdict == detector.OK:
                    html_body = result.html = resp.text
                    result.final_url = resp.final_url
                    if "extract" not in steps:
                        return self._done(result, "http", html_body)
                elif verdict in REFUSED:
                    refused = True
            elif step == "extract":
                if html_body is not None:
                    text, result.extractor = extract(html_body)
                    return self._done(result, "extract", text, result.final_url, result.extractor)
            elif step == "reader":
                if host in self.forbidden:
                    result.tried.append(("reader", "forbidden-host"))
                    continue
                for name, fetch in self._readers():
                    if self._catalogue()[name].get("unblocker") and is_portal(host, self.portals):
                        result.tried.append((f"reader:{name}", "archive-portal"))
                        continue
                    for tier in self._tiers(name):
                        label = f"reader:{name}" if tier == "read" else f"reader:{name}:{tier}"
                        if self.meter is not None:
                            why = self.meter.refusal(name, tier)
                            if why == "quota":
                                result.tried.append((label, "quota"))
                                result.quota.append(name)
                            if why:
                                break
                        got = fetch(url, tier)
                        if got is None:
                            break
                        status, body, units, wait = got
                        if self.meter is not None:
                            if status == 200 or units is not None:   # a 404 some readers bill
                                self.meter.record(name, units, tier)
                                result.spent.append((name, tier, units))
                            elif self.meter.refused(name, status, body, wait):
                                result.tried.append((label, "quota"))
                                result.quota.append(name)
                                break
                        verdict = self._check(result, label, status, body, None, None, "reader",
                                              expect, no_results)
                        if verdict == detector.OK:
                            return self._done(result, "reader", _strip_reader(body), extractor=name)
                        if verdict not in UNRENDERED:
                            break
            elif step == "browser":
                if robots:   # T66: the headless browser is the engine reading too
                    result.tried.append(("browser", "robots"))
                    continue
                if self.browser is None:
                    continue
                profile = os.path.join(self.state_dir or ".", "browser", host)
                try:
                    with FileLock(profile + ".lock", stale_seconds=600):
                        status, body, final = self.browser(url, profile)
                except Exception:   # Playwright without its browser (playwright install chromium), a crash
                    result.tried.append(("browser", "unavailable"))
                    continue
                if self._check(result, "browser", status, body, final, None, "browser", expect,
                               no_results) == detector.OK:
                    result.html = body
                    text, result.extractor = extract(body)
                    return self._done(result, "browser", text, final, result.extractor)
            elif step == "user-browser":
                if self.interactive and not self._browser_lock_held():
                    result.status = "ask"
                    result.step = "user-browser"
                    return result
            elif step == "archive":
                if not (gone or refused or any(s in REFUSED or s.startswith("gone") for _st, s in result.tried)):
                    continue
                got = self._wayback(url)
                if got is None:
                    result.tried.append(("archive", "no-capture"))
                    continue
                capture_url, resp = got
                if self._check(result, "archive", resp.status, resp.body, None, resp.headers,
                               "http") == detector.OK:
                    result.html = resp.text
                    text, result.extractor = extract(resp.text)
                    return self._done(result, "archive", text, capture_url, result.extractor)
        # A reader might have read the page, had its free quota allowed it.
        answered = any(st.startswith("reader:") and s != "quota" for st, s in result.tried)
        if result.quota and not answered and not gone:
            result.status = "quota"
            return result
        # The status that says why the page was not read: the first answer of the
        # site itself, not a step that had nothing to offer, nor a reader held back
        # by its quota before another one answered.
        failures = [s for _step, s in result.tried
                    if s not in ("forbidden-host", "no-capture", "skipped", "quota")]
        result.status = failures[0] if failures else detector.EMPTY
        if result.status.startswith("gone-"):
            result.status = "gone"
        return result

    def _done(self, result, step, text, final_url=None, extractor=None, store=True):
        result.status = detector.OK
        result.step = step
        result.text = text
        result.final_url = final_url or result.final_url
        result.extractor = extractor or result.extractor
        if store and step != "cache":
            ttl = ttl_for("http", self.config)
            if step == "reader":   # TRUST1-T4: a reader's terms decide how long its page is kept
                entry = self._catalogue().get(result.extractor) or {}
                if entry.get("cache_ttl") is not None:
                    ttl = ttl_for(result.extractor, self.config, entry["cache_ttl"])
            paid = result.spent[-1] if step == "reader" and result.spent else None   # T64: what it saves
            self.cache.put("http", make_key("http", result.url),
                           {"text": text, "final_url": result.final_url, "step": step,
                            "extractor": result.extractor, "detector": detector.VERSION,
                            "html": result.html}, "ok", ttl, by=paid[0] if paid else "http",
                           units=paid[2] if paid else None)
        return result

    def _browser_lock_held(self):
        if not self.state_dir:
            return False
        return os.path.exists(os.path.join(self.state_dir, "locks", "browser.json"))

    # reader APIs: (status, text in Jina's reader format, units used or None, Retry-After)

    def _catalogue(self):
        from probandia.providers import catalogue

        return self.meter.ledger.catalogue if self.meter is not None else catalogue.load()

    def _tiers(self, name):
        """The tiers the ladder reads at. An unblocking reader reads once, plain: it
        never goes up to its JavaScript tier by itself (the user's decision, 2 October
        2026), which stays for an explicit call to its adapter."""
        from probandia.providers import catalogue

        entry = self._catalogue()[name]
        return ["read"] if entry.get("unblocker") else catalogue.tiers(entry)

    def _readers(self):
        """The readers of ``reading.readers`` in its order (Firecrawl, Tavily's
        ``/extract`` (T232), Jina: T256, Parallel's ``/v1/extract``), then the unblocking readers whose key is
        set, in catalogue order."""
        readers = []
        for name in reader_order(self.config):
            if name == "firecrawl":
                readers.append((name, self._firecrawl))
            elif name == "jina":
                readers.append((name, self._jina))
            else:   # Tavily's /extract, Parallel's /v1/extract: their adapter's read
                entry = self._catalogue().get(name) or {}
                env = (entry.get("auth") or {}).get("env")
                if env and self.environ.get(env):
                    readers.append((name, self._unblocker(name)))
        for pid, entry in self._catalogue().items():
            env = (entry.get("auth") or {}).get("env")
            if entry.get("unblocker") and env and self.environ.get(env):
                readers.append((pid, self._unblocker(pid)))
        return readers

    def _unblocker(self, pid):
        """A reader of ``providers.adapters`` (Tavily, the unblocking readers), its
        page given in Jina's format."""
        from probandia.providers import adapters
        from probandia.providers.base import ProviderError

        def fetch(url, tier="read"):
            ad = adapters.make(pid, self.client, self._catalogue()[pid], self.environ)
            try:
                page, usage = ad.read(url, tier)
            except ProviderError as err:
                if not err.status:      # refused before any call
                    return None
                return err.status, err.excerpt, None, err.retry_after
            text = f"Title: {page.title}\n\nURL Source: {page.final_url}\n\nMarkdown Content:\n{page.text}"
            return page.status, text, usage.units, None
        return fetch

    def _jina(self, url, tier="read"):
        """Without a key, the plain Markdown answer. With one, the JSON answer,
        which says how many tokens the read used."""
        key = self.environ.get("JINA_API_KEY")
        headers = {"X-Return-Format": "markdown"}
        if key:
            headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})
        resp = self.client.get("https://r.jina.ai/" + url, headers=headers, api=True)
        wait = resp.headers.get("retry-after")
        if not key or resp.status != 200:
            return resp.status, resp.text, None, wait
        try:
            data = resp.json().get("data") or {}
        except (ValueError, AttributeError):
            return resp.status, resp.text, None, wait
        text = f"Title: {data.get('title') or ''}\n\nURL Source: {data.get('url') or url}\n\n" \
               f"Markdown Content:\n{data.get('content') or ''}"
        tokens = (data.get("usage") or {}).get("tokens") or resp.headers.get("x-usage-tokens")
        return 200, text, _units(tokens), wait

    def _firecrawl(self, url, tier="read"):
        """``read_js`` waits for the page's scripts before taking the page."""
        key = self.environ.get("FIRECRAWL_API_KEY")
        if not key:
            return None
        payload = {"url": url, "formats": ["markdown"]}
        if tier == "read_js":
            payload["waitFor"] = FIRECRAWL_WAIT_MS
        body = json.dumps(payload).encode("utf-8")
        resp = self.client.request("POST", "https://api.firecrawl.dev/v2/scrape",
                                   headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"},
                                   body=body, api=True)
        wait = resp.headers.get("retry-after")
        if resp.status != 200:
            return resp.status, resp.text, None, wait
        try:
            answer = resp.json()
            data = answer.get("data") or {}
        except (ValueError, AttributeError):
            return resp.status, resp.text, None, wait
        meta = data.get("metadata", {})
        md = data.get("markdown", "")
        text = f"Title: {meta.get('title', '')}\n\nURL Source: {meta.get('sourceURL', url)}\n\n" \
               f"Markdown Content:\n{md}"
        return 200, text, _units(answer.get("creditsUsed", meta.get("creditsUsed"))), wait

    # web archives

    def _wayback(self, url):
        resp = self.client.get("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(
            {"url": url, "output": "json", "filter": "statuscode:200", "limit": "-1"}), api=True)
        if resp.status != 200:
            return None
        try:
            rows = resp.json()
        except ValueError:
            return None
        if len(rows) < 2:
            return None
        header, last = rows[0], rows[-1]
        stamp = last[header.index("timestamp")]
        capture = f"https://web.archive.org/web/{stamp}id_/{url}"
        return capture, self.client.get(capture, api=True)


def _units(value):
    """The units an answer says it used, or None when it says nothing readable."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _strip_reader(body):
    """The Markdown content of a reader API answer, without its header lines."""
    m = re.search(r"^Markdown Content:\s*\n", body, re.M)
    return body[m.end():] if m else body


# passages

STOPWORDS = {"the", "and", "les", "des", "une", "der", "die", "das", "und", "qui", "que", "pour",
             "with", "von", "est", "was", "who", "what", "where", "when", "dans", "sur", "par"}


def _words(text):
    from probandia.lang.places import key
    return [w for w in key(text).split() if len(w) >= 3 and w not in STOPWORDS]


def blocks(text, size=500):
    """The text cut into blocks of at most ``size`` characters, on paragraph
    and sentence boundaries."""
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        while len(para) > size:
            cut = max(para.rfind(". ", 0, size), para.rfind(" ", 0, size))
            cut = cut + 1 if cut > size // 3 else size
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def passages(text, question, limit=12, size=500):
    """The blocks that best match the question's words, at most ``limit``."""
    parts = blocks(text, size)
    if not question:
        return parts[:3]
    terms = set(_words(question))
    scored = []
    for i, b in enumerate(parts):
        words = _words(b)
        score = sum(1 for w in words if w in terms)
        if score:
            scored.append((-score, i, b))
    return [b for _s, _i, b in sorted(scored)[:limit]]
