"""The silent-failure detector: is this response really the page asked for?

Every response goes through it: HTTP, reader API or browser. The rules run in
the order D8, D7, D2, D4, D3, D1, D5, D6; the first that matches gives the status,
otherwise the status is ``ok``.

| Rule | Status |
|---|---|
| D8 a sign-in screen: a redirection to an identification host, a password form in a page that has little else, or a "logged out" marker of the archive | ``login`` |
| D7 codes: 401, 403, 407, 429, 451, 503, and any other error answer (400 and up) | ``blocked`` |
| D2 a challenge page or cookie (Anubis, Cloudflare, DataDome, Incapsula, ALTCHA, captcha…) | ``challenge`` |
| D4 a script or meta redirect in a small body | ``redirect`` |
| D3 an application shell whose content never arrived | ``template`` |
| D1 too little: visible text under 500 characters, or a body under 2,048 bytes | ``empty`` |
| D5 another page than the one asked for | ``wrong_page`` |
| D6 none of the expected markers, and no "no results" phrase | ``unknown`` |

A response that fails is never cached, is logged as ``failed`` with its
status, and can never support a negative.
"""
import hashlib
import re
import urllib.parse

from probandia.reading.extract import main_text, title, visible_text

# The version of the rules. A page judged under another version is not served
# from the cache: it is read and judged again. 2 (2 October 2026): D7 counts every
# error answer, where version 1 let a 402, a 500 or a 502 page pass as the page.
VERSION = 3   # 3 (3 October 2026): D8, a sign-in screen
LOGIN = "login"
# Hosts that only ever sign people in; an archive adds its own (catalogue, login.hosts).
LOGIN_HOST = re.compile(r"^(login|logon|signin|sign-in|auth|sso|ident|accounts)\.", re.I)
PASSWORD_FIELD = re.compile(r"<input[^>]+type\s*=\s*[\"']?password", re.I)
LOGIN_TEXT = 1500   # a password form in a page with less main text than this is a sign-in screen
BLOCKED_CODES = {401, 403, 407, 429, 451, 503}
CHALLENGE_COOKIES = ("techaro.lol-anubis-auth", "cf_clearance", "datadome", "incap_ses",
                     "visid_incap")
# Markers of one challenge tool: they count on any page.
CHALLENGE_MARKERS = (
    "making sure you're not a bot", "making sure you&#39;re not a bot", "/.within.website/",
    "techaro.lol-anubis-auth", "/cdn-cgi/challenge-platform/", "captcha-delivery.com",
    "_incapsula_resource",
)
# Common words: they count only on a page with almost no text of its own, since
# a normal page may mention them in its scripts or its help.
WEAK_CHALLENGE_MARKERS = ("just a moment", "altcha", "enable javascript", "access denied", "captcha")
WEAK_TEXT_LIMIT = 1500
APP_ROOTS = ('id="app"', 'id="root"', 'id="__next"', 'id="__nuxt"', 'id="___gatsby"',
             "id='app'", "id='root'")
LOADING = ("loading", "chargement", "wird geladen", "laden")
WRONG_TITLE = re.compile(r"\b(home|accueil|faq|404|not found|page introuvable|erreur|"
                         r"foire aux questions|startseite)\b", re.I)

EMPTY_TEXT = 500
EMPTY_BYTES = 2048
TEMPLATE_TEXT = 300
REDIRECT_BYTES = 5 * 1024

OK, BLOCKED, CHALLENGE, REDIRECT, TEMPLATE, EMPTY, WRONG, UNKNOWN = (
    "ok", "blocked", "challenge", "redirect", "template", "empty", "wrong_page", "unknown")


def _same_url(a, b):
    def norm(u):
        p = urllib.parse.urlsplit(u.strip())
        path = p.path.rstrip("/") or "/"
        return (p.netloc.lower().removeprefix("www."), path, p.query)
    return norm(a) == norm(b)


def _deeper(url):
    return urllib.parse.urlsplit(url).path.strip("/") != ""


def fingerprint(text):
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()[:16]


def _host(url):
    return (urllib.parse.urlsplit(url or "").hostname or "").lower()


def is_login(page, url, final_url=None, login=None, kind="http"):
    """D8: a sign-in screen instead of the page. ``login``: the archive's block of
    the catalogue (``hosts``, ``logged_out``, ``logged_in``)."""
    login = login or {}
    low = page.lower()
    final_host, asked = _host(final_url), _host(url)
    hosts = {h.lower() for h in login.get("hosts") or []}
    if final_host and final_host != asked and (final_host in hosts or LOGIN_HOST.match(final_host)):
        return True
    if any(m.lower() in low for m in login.get("logged_out") or []) and \
            not any(m.lower() in low for m in login.get("logged_in") or []):
        return True
    if kind != "reader" and PASSWORD_FIELD.search(page) and len(main_text(page)) < LOGIN_TEXT:
        return True
    return False


# What a WebFetch's answer says of a page that did not load (T59): its ``result`` is a small model's answer
# about the page, not the page, so the markers are the words it describes a challenge or a shell with.
FETCH_CHALLENGE = re.compile(r"anubis|proof[- ]of[- ]work|not a bot|bot[- ]protection|cloudflare|captcha|altcha|"
                             r"datadome|verify (?:that )?you(?:'re| are) (?:a )?human|just a moment|access denied",
                             re.I)
FETCH_TEMPLATE = re.compile(r"(?:requires|needs|enable) javascript|javascript (?:is )?(?:required|disabled)|"
                            r"still loading|only (?:shows|contains|displays) (?:a )?(?:loading|navigation|menu|header)|"
                            r"no (?:visible|actual|main) content|(?:page|content) (?:is|appears to be|seems) "
                            r"(?:empty|blank)", re.I)


def classify_fetch(code, result, size=None):
    """(status, rule) of a page as ``WebFetch`` gave it (T59): its HTTP ``code``, the ``size`` in bytes of
    what it fetched, and its ``result``. ``ok`` unless they say the page did not load."""
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    if code is not None and (code in BLOCKED_CODES or code >= 400):
        return BLOCKED, "D7"
    text = str(result or "")
    if FETCH_CHALLENGE.search(text):
        return CHALLENGE, "D2"
    if FETCH_TEMPLATE.search(text):
        return TEMPLATE, "D3"
    if code == 200 and isinstance(size, int) and size < EMPTY_BYTES:
        return EMPTY, "D1"
    return OK, ""


def classify(status, body, url, final_url=None, headers=None, kind="http", expect=(),
             no_results=None, templates=(), login=None):
    """(status, rule) of one response. ``kind``: ``http``, ``reader`` (Jina,
    Firecrawl: Markdown) or ``browser``. ``templates``: fingerprints of the
    known empty template of the domain. ``login``: the archive's login block."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if isinstance(body, bytes):
        raw = body
        page = body.decode("utf-8", errors="replace")
    else:
        page = body or ""
        raw = page.encode("utf-8")
    low = page.lower()
    cookies = (headers.get("set-cookie") or "").lower()

    # D8 a sign-in screen: never the page, and the user may open the session
    if is_login(page, url, final_url, login, kind):
        return LOGIN, "D8"

    # D7 codes: the blocking ones, and any other error answer (an error page is
    # never the page asked for, whatever its size)
    if status in BLOCKED_CODES or (status or 0) >= 400:
        return BLOCKED, "D7"
    # D2 challenge
    head = low[:20000]
    strong = (headers.get("cf-mitigated", "").lower() == "challenge"
              or any(c in cookies for c in CHALLENGE_COOKIES[:1] + CHALLENGE_COOKIES[2:])
              or any(m in head for m in CHALLENGE_MARKERS))
    weak = any(m in head for m in WEAK_CHALLENGE_MARKERS) and         len(main_text(page) if kind != "reader" else page) < WEAK_TEXT_LIMIT
    if strong or weak:
        return CHALLENGE, "D2"
    is_html = kind != "reader" and ("<html" in low[:2000] or "<body" in low or "<div" in low)
    # D4 script or meta redirect
    if is_html and len(raw) < REDIRECT_BYTES:
        scripted = re.search(r"(?:window\.|document\.)?location(?:\.href)?\s*=|location\.(?:replace|assign|reload)\s*\(",
                             low)
        if re.search(r'<meta[^>]+http-equiv=["\']?refresh', low) or (
                scripted and ("document.cookie" in low or len(visible_text(page)) < 200)):
            return REDIRECT, "D4"
    # D3 application shell
    if is_html:
        scripts = len(re.findall(r"<script\b", low))
        modules = "type=\"module\"" in low or "type='module'" in low
        main = main_text(page)
        has_root = any(r in low for r in APP_ROOTS)
        asks_js = re.search(r"<noscript[^>]*>[^<]*(javascript|js enabled)", low)
        if has_root and len(main) < TEMPLATE_TEXT and (scripts >= 5 or modules or
                                                       any(w in main.lower() for w in LOADING)):
            return TEMPLATE, "D3"
        if asks_js and len(main) < TEMPLATE_TEXT:
            return TEMPLATE, "D3"
    # D1 size
    text = visible_text(page) if kind != "reader" else page.strip()
    if status == 200 and (len(text) < EMPTY_TEXT or len(raw) < EMPTY_BYTES):
        if kind != "reader" or len(text) < EMPTY_TEXT:
            return EMPTY, "D1"
    # D5 wrong page
    if final_url and not _same_url(final_url, url):
        return WRONG, "D5"
    if kind == "reader":
        m = re.search(r"^URL Source:\s*(\S+)", page, re.M)
        if m and not _same_url(m.group(1), url):
            return WRONG, "D5"
        t = re.search(r"^Title:\s*(.+)$", page, re.M)
        page_title = t.group(1) if t else ""
    else:
        page_title = title(page)
    if page_title and WRONG_TITLE.search(page_title) and _deeper(url):
        return WRONG, "D5"
    if templates and fingerprint(text) in set(templates):
        return WRONG, "D5"
    # D6 expected markers
    if expect:
        found = any(re.search(e, page, re.I) for e in expect)
        if not found and not (no_results and no_results.lower() in low):
            return UNKNOWN, "D6"
    return OK, ""
