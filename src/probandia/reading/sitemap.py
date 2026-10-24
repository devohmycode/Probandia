"""The map of a site from what it publishes itself, at no cost (T229): the
``Sitemap:`` lines of its ``robots.txt``, otherwise ``/sitemap.xml``.

- A sitemap index is followed, sitemap by sitemap, at most ``MAX_SITEMAPS``.
- Only the URLs of the same host are kept (``www.`` aside), at most ``limit``.
- A gzipped sitemap is opened; anything that is not a sitemap gives no URL.
- Every request goes through the engine's HTTP client: polite, ``robots.txt``
  obeyed, one host at its own pace.
"""
import gzip
import urllib.parse
import xml.etree.ElementTree as ET

from probandia.util.http import NetworkError, RobotsDenied

MAX_SITEMAPS = 10
MAX_BYTES = 20_000_000


def same_host(a, b):
    """True when two URLs name the same host, ``www.`` aside."""
    def host(u):
        return (urllib.parse.urlsplit(u).hostname or "").lower().removeprefix("www.")
    return host(a) == host(b)


def from_robots(text):
    """The sitemaps a ``robots.txt`` names (``Sitemap:`` lines), in order."""
    out = []
    for line in (text or "").splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "sitemap" and value.strip() and value.strip() not in out:
            out.append(value.strip())
    return out


def parse(body):
    """``(urls, sitemaps)`` of a sitemap (``<urlset>``) or a sitemap index
    (``<sitemapindex>``); ``([], [])`` for anything else."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            return [], []
    if len(body) > MAX_BYTES:
        return [], []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return [], []

    def local(tag):
        return tag.rsplit("}", 1)[-1].lower()

    locs = [el.text.strip() for el in root.iter() if local(el.tag) == "loc" and el.text and el.text.strip()]
    kind = local(root.tag)
    if kind == "urlset":
        return locs, []
    if kind == "sitemapindex":
        return [], locs
    return [], []


def site_map(client, url, limit=5000):
    """``(urls, sitemaps read)``: the URLs the site publishes for itself, same host."""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    try:
        robots, _status = client._robots(parts.scheme, parts.netloc)
    except (NetworkError, OSError):
        robots = ""
    queue = [s for s in from_robots(robots) if same_host(s, url)] or [origin + "/sitemap.xml"]
    seen, urls, kept = [], [], set()
    while queue and len(seen) < MAX_SITEMAPS and len(urls) < limit:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.append(sm)
        try:
            resp = client.get(sm)
        except (RobotsDenied, NetworkError):
            continue
        if resp.status != 200:
            continue
        found, nested = parse(resp.body)
        queue += [s for s in nested if same_host(s, url) and s not in seen]
        for u in found:
            if same_host(u, url) and u not in kept:
                kept.add(u)
                urls.append(u)
    return urls[:limit], seen
