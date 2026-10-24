"""``read <url> --crawl <n>``: the pages of a site, followed from a start page, by
the engine itself first (T230).

- Each page goes down the free steps of the reading ladder only (cache, archive
  connector, polite HTTP and extraction): ``robots.txt`` obeyed, the pace of each
  host kept, never a third-party reader page by page.
- The crawl stays on the host of the start page, and follows the links that hold
  ``pattern`` (any case; every link when there is none), breadth first.
- At most ``n`` pages are read; a page the site refuses or lacks is noted, not
  counted, and the attempts stop at three times ``n``.
- A third party's crawl (Firecrawl, then Tavily) is for a start page the detector
  finds empty, unrendered or blocked: the caller decides it with ``needs_help``.
"""
from probandia.reading import extract as E
from probandia.reading.ladder import REFUSED, UNRENDERED, _words, blocks
from probandia.reading.sitemap import same_host

FREE_STEPS = 3   # cache, api, http, extract: no third party


class Crawled:
    def __init__(self):
        self.pages = []     # [(url, title, text)] read
        self.skipped = []   # [(url, status)] not read
        self.start = None   # the ReadResult of the start page


def _clean(href):
    return href.split("#")[0]


def crawl(reader, url, n, pattern=None, fresh=False):
    """Reads at most ``n`` pages from ``url``, same host, following the links that hold ``pattern``."""
    out = Crawled()
    queue, seen = [url], {url}
    attempts = 0
    while queue and len(out.pages) < n and attempts < 3 * n:
        current = queue.pop(0)
        attempts += 1
        result = reader.read(current, fresh=fresh, max_step=FREE_STEPS)
        if out.start is None:
            out.start = result
        if not result.ok:
            out.skipped.append((current, result.status))
            continue
        out.pages.append((result.final_url or current, _title(result), result.text))
        for _text, href in E.links(result.html or "", pattern or "", result.final_url or current):
            href = _clean(href)
            if href.startswith(("http://", "https://")) and same_host(href, url) and href not in seen:
                seen.add(href)
                queue.append(href)
    return out


def needs_help(start):
    """True when a third party's crawl may do what the engine could not: the start
    page came back empty, unrendered or blocked (``detector.classify``). Never for a
    page ``robots.txt`` disallows, one that is gone, or a sign-in screen."""
    if start is None or start.ok:
        return False
    return start.status in UNRENDERED or (start.status in REFUSED and start.status != "robots")


def _title(result):
    for line in (result.text or "").splitlines():
        if line.strip():
            return line.strip().lstrip("# ")[:120]
    return ""


def passages(pages, question, limit=12, size=500):
    """``[(url, passage)]``: the blocks of every page that best match the question's
    words, best first; without a question, the first block of each page."""
    if not question:
        return [(u, (blocks(text, size) or [""])[0]) for u, _t, text in pages[:limit]]
    terms = set(_words(question))
    scored = []
    for p, (u, _t, text) in enumerate(pages):
        for i, b in enumerate(blocks(text, size)):
            score = sum(1 for w in _words(b) if w in terms)
            if score:
                scored.append((-score, p, i, u, b))
    return [(u, b) for _s, _p, _i, u, b in sorted(scored)[:limit]]


def include_pattern(pattern):
    """The regular expression a third party's crawl receives for ``--links``."""
    import re

    return [f".*{re.escape(pattern)}.*"] if pattern else None

