"""Index families, web negatives and rank fusion.

**Negatives.** A web negative holds only when the exact query ran, for the name
and each variant, on keyword engines of at least ``web.negative_families``
distinct families among G, B, Br, E, M and Ma; every engine answered without a
failure; and none returned a hit. A hit is a result whose title or snippet
holds the surname or a variant (without accents or case) and, when the query
names a place, that place or one of its old names.

**Unrelated answers.** An engine that returns results, none of which holds the
name, a variant or the place asked for, has not answered the query (Bing, through
SerpApi, did so for 4 queries out of 5 on 2 October 2026): its family does not
count, as if it had not run, and never as an engine without a hit. The negative
then needs its families from the other engines; ``search --negative`` tries the
engines of the families still missing.

**Rank fusion.** ``score(url) = Σ 1 / (60 + rank)`` over the engines that
returned it. URLs are normalised first, and the same item under several
addresses (Gallica ARK, IIIF identifier, eluxemburgensia ARK) is one result.
"""
import re
import urllib.parse

from probandia.lang.places import key as fold
from probandia.providers.catalogue import KEYWORD_FAMILIES

RRF_K = 60


def normalise_url(url):
    p = urllib.parse.urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    path = p.path.rstrip("/") or ""
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(query), ""))


ITEM_PATTERNS = (
    re.compile(r"(ark:/\d+/[a-z0-9]+)", re.I),                       # Gallica, eluxemburgensia
    re.compile(r"/iiif/([^/]+(?:/[^/]+)?)/(?:full|info\.json|\d)", re.I),
)


def item_key(url):
    """One key for the several addresses of one item."""
    for rx in ITEM_PATTERNS:
        m = rx.search(url)
        if m:
            return m.group(1).lower()
    return normalise_url(url)


def fuse(result_lists):
    """``result_lists``: {provider: [Result…]} (rank from 1). Returns merged
    results, best first, each with ``providers`` and ``score``."""
    merged = {}
    for provider, results in result_lists.items():
        for r in results:
            k = item_key(r.url)
            m = merged.get(k)
            if m is None:
                m = merged[k] = {"url": r.url, "title": r.title, "snippet": r.snippet, "date": r.date,
                                 "providers": [], "families": [], "score": 0.0}
            if provider not in m["providers"]:
                m["providers"].append(provider)
                m["score"] += 1.0 / (RRF_K + r.rank)
            if r.family not in m["families"]:
                m["families"].append(r.family)
    return sorted(merged.values(), key=lambda m: (-m["score"], m["url"]))


def is_hit(result, names, places=()):
    text = fold(f"{result.title} {result.snippet}")
    words = set(text.split())
    names_ok = any(set(fold(n).split()) <= words for n in names if n.strip())
    if not names_ok:
        return False
    if places:
        return any(fold(p) in text for p in places if p.strip())
    return True


def related(results, names, places=()):
    """True when no result is given, or one at least holds a word of the names or
    places asked for (three letters or more, without accents or case)."""
    if not results:
        return True
    words = {w for n in list(names) + list(places) for w in fold(n).split() if len(w) >= 3}
    if not words:
        return True
    for r in results:
        text = set(fold(f"{r.title} {r.snippet}").split())
        if words & text:
            return True
    return False


class NegativeCheck:
    """The verdict of a web negative over the engines that ran."""

    def __init__(self, required_families):
        self.required = required_families
        self.engines = []
        self.failures = []   # (engine, reason)
        self.hits = []       # (engine, result)
        self.unrelated = []  # engines whose answer was unrelated to the query: not counted
        self._families = {}  # engine -> keyword family

    @property
    def families(self):
        """The keyword families searched: an engine counts only if each of its
        answers related to the query."""
        return {f for e, f in self._families.items() if e not in self.unrelated}

    def add(self, engine, family, keyword, results=None, failure=None, names=(), places=()):
        self.engines.append(engine)
        if failure:
            self.failures.append((engine, failure))
            return
        if not related(results, names, places):
            if engine not in self.unrelated:
                self.unrelated.append(engine)
            return
        if keyword and family in KEYWORD_FAMILIES:
            self._families[engine] = family
        for r in results or []:
            if is_hit(r, names, places):
                self.hits.append((engine, r))

    @property
    def result(self):
        """``negative``, ``positive``, or ``failed``."""
        if self.hits:
            return "positive"
        if self.failures or len(self.families) < self.required:
            return "failed"
        return "negative"

    def reasons(self):
        out = []
        if len(self.families) < self.required:
            out.append(f"keyword families: {len(self.families)} of {self.required} "
                       f"({', '.join(sorted(self.families)) or 'none'})")
        for engine, why in self.failures:
            out.append(f"{engine}: {why}")
        for engine in self.unrelated:
            out.append(f"{engine}: unrelated answer, not counted")
        return out
