"""The HTTP client: every network call of the engine and of learned scripts goes through it.

- **Identification.** ``User-Agent: Probandia/<version> (+<contact>)``; the contact
  comes from ``PROBANDIA_CONTACT``, then ``http.contact``, then the project's site.
- **Timeouts and retries.** 10 s to connect, 30 s to read. ``429`` or ``503``:
  ``Retry-After`` is followed when it is at most 120 s, otherwise the client
  stops; without it, it waits 2, 4, then 8 s. At most 3 retries. Any other
  ``5xx`` gets one retry; a ``4xx`` gets none.
- **Limits per host.** One token bucket per host, shared between processes in
  ``.probandia/rate/<host>.json`` (``host_port.json`` with a port) under a file lock, and one connection per host
  at a time.
- **robots.txt**, read once per host and kept 24 hours. A disallowed page is
  refused (``REASON=robots``); a robots.txt out of reach (``5xx``, ``429``, a network
  error) refuses the whole host for one hour (``REASON=robots-unreachable``, RFC 9309 § 2.3.1.4): ``read <url>`` hands it to the readers instead
  (``reading/ladder.py``). Endpoints a provider documents for automated use are exempt.
- **Conditional requests** (``ETag``, ``Last-Modified``) for pages already cached.
- **Allowlists.** A learned script may only reach the hosts it declares.
- **A cookie set by a plain redirect page** (detector D4: a short page that sets a cookie
  and sends the browser on by script) is kept for its host and replayed, under the
  engine's own identity (token-economy A1). A challenge (D2) or a refusal is never forced.
"""
import email.utils
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from probandia import SITE, __version__
from probandia.errors import NetworkError, ProbandiaError
from probandia.i18n import _
from probandia.util.fs import _replace

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
MAX_RETRIES = 3
BACKOFF = (2, 4, 8)
MAX_RETRY_AFTER = 120
ROBOTS_HOURS = 24
ROBOTS_UNREACHABLE_HOURS = 1   # then asked again
DEFAULT_RATE = (1, 2.0)  # 1 request every 2 s
DEFAULT_CONTACT = SITE
SCRIPT_REDIRECT = re.compile(rb"window\.location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]")
SCRIPT_REDIRECT_MAX = 2000   # bytes: a redirect page, not a page of content

# Built-in rates per host: (requests, seconds).
HOST_RATES = {
    "gallica.bnf.fr": (5, 60.0),
    "www.loc.gov": (20, 60.0), "chroniclingamerica.loc.gov": (20, 60.0),
    "api.openarch.nl": (4, 1.0), "www.openarchieven.nl": (4, 1.0),
    "deces.matchid.io": (1, 1.0), "nominatim.openstreetmap.org": (1, 1.0),
    "api.wikitree.com": (1, 1.0), "gov.genealogy.net": (1, 1.0),
    "api.geonames.org": (1000, 3600.0), "secure.geonames.org": (1000, 3600.0),
    "web.archive.org": (60, 60.0),
}


# The query parameters that carry a key (SerpApi, ScraperAPI: api_key; ZenRows: apikey).
SECRET_PARAM = re.compile(r"(?i)\b((?:api_?key|key|token|access_token|auth)=)[^&\s\"'<>]+")


def redact(text):
    """``text`` with the value of every key parameter of a URL masked: what an error,
    a log or a cache may keep of an address that carries a key."""
    return SECRET_PARAM.sub(r"\1***", text) if text else text


class RobotsDenied(ProbandiaError):
    reason = "robots"


class RobotsUnreachable(RobotsDenied):
    reason = "robots-unreachable"


def robots_unreachable(status):
    return status == 0 or status == 429 or status >= 500


class HostNotAllowed(ProbandiaError):
    reason = "host-not-allowed"


class Response:
    def __init__(self, status, headers, body, url, final_url=None, from_cache=False):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body or b""
        self.url = url
        self.final_url = final_url or url
        self.from_cache = from_cache

    @property
    def text(self):
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


RENEWED_COOKIE = "X-Probandia-Cookie"   # the replayed cookie as a redirect of the call renewed it


class _CarryCookie(urllib.request.HTTPRedirectHandler):
    """For a request that replays a cookie: a cookie a redirect sets on the same host goes with the
    next request of the chain, as a browser's would (the site renews it on its 307)."""

    renewed = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        sets = headers.get_all("Set-Cookie") or []
        if new is None or not sets or urllib.parse.urlsplit(newurl).netloc not in ("", urllib.parse.urlsplit(
                req.full_url).netloc):
            return new
        jar = dict(p.split("=", 1) for p in (req.get_header("Cookie") or "").split("; ") if "=" in p)
        for s in sets:
            name, sep, value = s.split(";", 1)[0].strip().partition("=")
            if name and sep:
                jar[name] = value
        self.renewed = "; ".join(f"{k}={v}" for k, v in jar.items())
        new.add_header("Cookie", self.renewed)
        return new


def urllib_transport(method, url, headers, body, timeout):
    """(status, headers, body, final url). HTTP errors are answers, not exceptions."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    carry = _CarryCookie() if any(k.lower() == "cookie" for k in headers) else None
    opener = urllib.request.build_opener(carry) if carry else None
    try:
        with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as resp:
            out = dict(resp.headers.items())
            if carry and carry.renewed:
                out[RENEWED_COOKIE] = carry.renewed
            return resp.status, out, resp.read(), resp.geturl()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()) if err.headers else {}, err.read() or b"", url


def state_name(host):
    """A file name for a host's state: ``127.0.0.1:8080`` -> ``127.0.0.1_8080``. On NTFS a colon would
    open a hidden alternate data stream instead of a file."""
    return re.sub(r"[^A-Za-z0-9.-]", "_", host)


class FileLock:
    """An exclusive lock between processes: a file created with O_EXCL."""

    def __init__(self, path, stale_seconds=120, poll=0.02):
        self.path = path
        self.stale = stale_seconds
        self.poll = poll

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except (FileExistsError, PermissionError):
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.unlink(self.path)  # left by a process that died
                except OSError:
                    pass
                time.sleep(self.poll)

    def __exit__(self, *exc):
        try:
            os.unlink(self.path)
        except OSError:
            pass


def parse_rate(text):
    """``"5/min"`` -> (5, 60.0)."""
    n, _sep, unit = text.partition("/")
    seconds = {"s": 1.0, "min": 60.0, "h": 3600.0, "day": 86400.0}[unit]
    return int(n), seconds


class Client:
    def __init__(self, state_dir, contact=None, config=None, transport=None, sleep=time.sleep,
                 clock=time.time, allow_hosts=None):
        self.state = os.path.join(state_dir, "rate")
        self.config = config
        self.contact = contact or DEFAULT_CONTACT
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self.clock = clock
        self.allow_hosts = set(allow_hosts) if allow_hosts is not None else None
        self.waits = []  # every pause taken, for the logs and the tests
        self.cookies = {}  # {host: {name: value}}, from plain redirect pages only
        self.opener = urllib.request.urlopen   # download's streaming opener; tests replace it

    @property
    def user_agent(self):
        return f"Probandia/{__version__} (+{self.contact})"

    def base_headers(self):
        return {"User-Agent": self.user_agent, "Accept-Language": "fr,en;q=0.8,de;q=0.6"}

    # limits

    def rate(self, host):
        if self.config is not None:
            try:
                value = self.config.get(f"hosts.{host}.rate")
            except KeyError:
                value = None
            if value:
                return parse_rate(value)
        return HOST_RATES.get(host, DEFAULT_RATE)

    def _slot(self, host):
        """Waits for the host's next slot. The slot times are shared between
        processes: one interval of ``seconds / n`` between two requests."""
        n, seconds = self.rate(host)
        interval = seconds / n
        path = os.path.join(self.state, f"{state_name(host)}.json")
        with FileLock(path + ".lock"):
            try:
                with open(path, encoding="utf-8") as fh:
                    nxt = json.load(fh).get("next", 0.0)
            except (FileNotFoundError, ValueError):
                nxt = 0.0
            now = self.clock()
            start = max(now, nxt)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"next": start + interval, "interval": interval}, fh)
        wait = start - now
        if wait > 0:
            self.waits.append(wait)
            self.sleep(wait)

    # robots.txt

    def _robots(self, scheme, host):
        path = os.path.join(self.state, f"{state_name(host)}.robots.json")
        try:
            with open(path, encoding="utf-8") as fh:
                saved = json.load(fh)
            hours = ROBOTS_UNREACHABLE_HOURS if robots_unreachable(saved["status"]) else ROBOTS_HOURS
            if self.clock() - saved["fetched"] < hours * 3600:
                return saved["text"], saved["status"]
        except (FileNotFoundError, ValueError, KeyError):
            pass
        status, _h, body, _u = self._send("GET", f"{scheme}://{host}/robots.txt", self.base_headers(),
                                          None, host)
        text = body.decode("utf-8", errors="replace") if status == 200 else ""
        os.makedirs(self.state, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fetched": self.clock(), "status": status, "text": text}, fh)
        return text, status

    def allowed_by_robots(self, url):
        return self.robots_refusal(url) is None

    def robots_refusal(self, url):
        """None when robots.txt lets the engine fetch ``url``; else the exception class of the refusal."""
        parts = urllib.parse.urlsplit(url)
        text, status = self._robots(parts.scheme, parts.netloc)
        if robots_unreachable(status):
            return RobotsUnreachable
        if status in (401, 403):
            return RobotsDenied
        if not text:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(text.splitlines())
        return None if parser.can_fetch("Probandia", url) else RobotsDenied

    # requests

    def _send(self, method, url, headers, body, host, timeout=None):
        answer = self._exchange(method, url, headers, body, host, timeout)
        target = self._script_redirect(url, answer, host) if method == "GET" else None
        if target:   # once: the page is asked again with its cookie
            answer = self._exchange("GET", target, headers, None, host)
        return answer

    def _exchange(self, method, url, headers, body, host, timeout=None):
        if self.cookies.get(host):
            headers = dict(headers, Cookie="; ".join(f"{k}={v}" for k, v in self.cookies[host].items()))
        self._slot(host)
        with FileLock(os.path.join(self.state, f"{state_name(host)}.conn")):
            try:
                answer = self.transport(method, url, headers, body, timeout or READ_TIMEOUT)
            except (OSError, http.client.HTTPException) as err:   # a truncated body, a bad URL: the network's fault
                return 0, {}, redact(str(err) or type(err).__name__).encode(), url
        renewed = (answer[1] or {}).get(RENEWED_COOKIE)
        if renewed and self.cookies.get(host):
            self.cookies[host].update(dict(p.split("=", 1) for p in renewed.split("; ") if "=" in p))
        return answer

    def _script_redirect(self, url, answer, host):
        """The address a plain redirect page sends on to, its cookie kept for the host; else None."""
        status, headers, body, _final = answer
        if status != 200 or len(body) > SCRIPT_REDIRECT_MAX:
            return None
        cookie = next((v for k, v in headers.items() if k.lower() == "set-cookie"), "")
        name, sep, value = cookie.split(";", 1)[0].strip().partition("=")
        m = SCRIPT_REDIRECT.search(body)
        if not (m and sep and name):
            return None
        self.cookies.setdefault(host, {})[name] = value
        return urllib.parse.urljoin(url, m.group(1).decode("utf-8", "replace"))

    def _admit(self, url, api):
        """The host of ``url``, once its script may reach it and robots.txt lets the engine in."""
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc.lower()
        if self.allow_hosts is not None and host not in self.allow_hosts                 and (parts.hostname or "").lower() not in self.allow_hosts:  # a declared host, any port
            raise HostNotAllowed(_("{host} is not among the hosts this script may reach").format(host=host),
                                 values={"HOST": host})
        refusal = None if api else self.robots_refusal(url)
        if refusal is RobotsUnreachable:
            raise refusal(_("robots.txt of {host} cannot be read: the host is left alone for an hour").format(
                host=host), values={"URL": url})
        if refusal:
            raise refusal(_("robots.txt of {host} disallows this page").format(host=host), values={"URL": url})
        return host

    def download(self, url, path, api=False, chunk=1 << 20):
        """Streams ``url`` into ``path`` a chunk at a time (a package too big for memory); the bytes written.
        A failure leaves no file; NetworkError, as for a request."""
        host = self._admit(url, api)
        self._slot(host)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        part, written = path + ".part", 0
        req = urllib.request.Request(url, headers=self.base_headers())
        try:
            with (FileLock(os.path.join(self.state, f"{state_name(host)}.conn")),
                  self.opener(req, timeout=READ_TIMEOUT) as resp, open(part, "wb") as fh):
                while block := resp.read(chunk):
                    fh.write(block)
                    written += len(block)
            _replace(part, path)   # retried while Windows lets a reader hold the file
        except (OSError, http.client.HTTPException) as err:   # HTTPError included: a download has no retry
            if os.path.exists(part):
                os.unlink(part)
            raise NetworkError(_("network error on {host}: {error}").format(host=host, error=redact(str(err))),
                               values={"HOST": host, "URL": redact(url)}) from None
        return written

    def request(self, method, url, headers=None, body=None, api=False, cached=None, timeout=None):
        """A response. ``api``: a documented endpoint, exempt from robots.txt.
        ``timeout``: seconds to wait for the answer, for a slow API (default ``READ_TIMEOUT``).
        ``cached``: a cache entry with ``etag`` / ``last_modified``, for a
        conditional request; a ``304`` answer returns it."""
        host = self._admit(url, api)
        h = self.base_headers()
        h.update(headers or {})
        if cached:
            if cached.get("etag"):
                h["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                h["If-Modified-Since"] = cached["last_modified"]
        retries_5xx = 0
        for attempt in range(MAX_RETRIES + 1):
            status, rh, rbody, final = self._send(method, url, h, body, host, timeout)
            if status >= 400 and SECRET_PARAM.search(url):   # an error page may echo the address, key and all
                rbody = redact(rbody.decode("utf-8", "replace")).encode("utf-8")
            resp = Response(status, rh, rbody, url, final)
            if status == 304 and cached:
                return Response(200, cached.get("headers", {}), cached["body"].encode("utf-8"), url,
                                cached.get("final_url"), from_cache=True)
            if status in (429, 503):
                if attempt == MAX_RETRIES:
                    return resp
                wait = retry_after(resp.headers.get("retry-after"), self.clock())
                if wait is None:
                    wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
                elif wait > MAX_RETRY_AFTER:
                    return resp  # the host asks for too long a pause: stop
                self.waits.append(wait)
                self.sleep(wait)
                continue
            if status >= 500 or status == 0:
                if retries_5xx >= 1 or attempt == MAX_RETRIES:
                    if status == 0:
                        raise NetworkError(_("network error on {host}: {error}").format(
                            host=host, error=rbody.decode("utf-8", "replace")), values={"HOST": host})
                    return resp
                retries_5xx += 1
                self.sleep(BACKOFF[0])
                continue
            return resp
        return resp

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


def retry_after(value, now):
    """Seconds to wait, from a ``Retry-After`` header (seconds or an HTTP date)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = email.utils.parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return None
    return max(0, int(when - now))


def contact(environ, config=None):
    if environ.get("PROBANDIA_CONTACT"):
        return environ["PROBANDIA_CONTACT"]
    if config is not None and config.get("http.contact"):
        return config.get("http.contact")
    return DEFAULT_CONTACT
