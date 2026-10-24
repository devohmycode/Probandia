"""The cache of responses: ``.probandia/cache/<provider>/<sha256>.json``.

- The key hashes the provider id, the normalised query or URL, and the filters.
- An entry holds ``created``, ``ttl`` (seconds), ``status`` and ``payload``.
- Time to live: the provider's ``cache_ttl``, otherwise ``cache.days``.
- A time to live of 0 keeps the entry in the research's ``work/cache/`` folder,
  for the current pass only: ``end_pass`` removes it.
- A failure (any detector status but ``ok``) is never stored, and never served.
  ``read <url>`` only notes that it failed, its status and when, in
  ``.probandia/read-failures.json`` for ``cache.days``: the guard's G-17 then lets
  the harness's own fetch try that page (T66).
- ``fresh`` bypasses the cache.
- ``read --map``, ``--crawl`` and ``--extract`` keep their answers under their own
  name (``map``, ``crawl``, ``extract``), keyed by the URL and what was asked: a
  second identical call is served for 0 unit (T229-T231).
- An entry may name who was paid for it (``by``: a provider, ``http``, ``native``)
  and the units it cost; each answer served counts in ``.probandia/cache-stats.json``
  with the units it saved: ``cache stats`` shows them, ``cache clear`` purges (T64).
"""
import hashlib
import json
import os
import shutil
import time

from probandia.util.fs import atomic_write_json

DAY = 86400
STATS = "cache-stats.json"   # in .probandia/: {by: {"served": n, "saved": units}}


def normalise(text):
    return " ".join(str(text).strip().split()).lower() if text is not None else ""


def make_key(provider, query, filters=None):
    raw = json.dumps([provider, normalise(query), filters or {}], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, project, work=None, clock=time.time):
        self.root = os.path.join(project, ".probandia", "cache")
        self.work = os.path.join(work, "cache") if work else None
        self.clock = clock

    def _path(self, provider, key, ttl):
        base = self.work if ttl == 0 else self.root
        if base is None:
            return None
        return os.path.join(base, provider, f"{key}.json")

    def get(self, provider, key, fresh=False):
        """The payload of a live entry, or None. An entry served is counted (``served``)."""
        found = None if fresh else self.live(provider, key)
        if found:
            self.served(provider, found[0])
        return found[0]["payload"] if found else None

    def served(self, folder, entry):
        """One more answer served from the cache, with the units its call had cost (T64).
        Never fails the command that serves it."""
        path = os.path.join(os.path.dirname(self.root), STATS)
        try:
            with open(path, encoding="utf-8") as fh:
                stats = json.load(fh)
        except (OSError, ValueError):
            stats = {}
        if not isinstance(stats, dict):
            stats = {}
        row = stats.setdefault(paid_by(folder, entry), {"served": 0, "saved": 0})
        row["served"] = row.get("served", 0) + 1
        row["saved"] = round(row.get("saved", 0) + float(entry.get("units") or 0), 6)
        try:
            atomic_write_json(path, stats)
        except OSError:
            pass

    def live(self, provider, key):
        """(entry, path) of a live entry, or None."""
        for base in (self.root, self.work):
            if not base:
                continue
            path = os.path.join(base, provider, f"{key}.json")
            try:
                with open(path, encoding="utf-8") as fh:
                    entry = json.load(fh)
            except (FileNotFoundError, ValueError):
                continue
            if entry.get("status") != "ok":
                continue  # never serve a failure, even one written by hand
            ttl = entry.get("ttl", 0)
            if ttl == 0 and base == self.work:
                return entry, path
            if ttl > 0 and self.clock() - entry.get("created", 0) < ttl:
                return entry, path
        return None

    def entry(self, provider, key):
        """The stored entry even if expired (for conditional requests), or None."""
        for base in (self.root, self.work):
            if base:
                try:
                    with open(os.path.join(base, provider, f"{key}.json"), encoding="utf-8") as fh:
                        return json.load(fh)
                except (FileNotFoundError, ValueError):
                    pass
        return None

    def put(self, provider, key, payload, status, ttl, by=None, units=None):
        """Stores an entry, with who was paid for it and the units it cost when known. A failure,
        or a ttl of 0 without a research, is not stored."""
        if status != "ok":
            return None
        path = self._path(provider, key, ttl)
        if path is None:
            return None
        entry = {"created": self.clock(), "ttl": ttl, "status": status, "payload": payload}
        if by:
            entry["by"] = by
        if units:
            entry["units"] = units
        atomic_write_json(path, entry)
        return path

    def end_pass(self):
        """Removes the entries kept for the pass only."""
        if self.work and os.path.isdir(self.work):
            shutil.rmtree(self.work)


def paid_by(folder, entry):
    """Who an entry was paid to: its ``by``, else the ``source`` of a map, a crawl or an
    extraction, else its folder (``native`` for the native searches' URLs)."""
    if entry.get("by"):
        return entry["by"]
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    if folder in ("map", "crawl", "extract") and payload.get("source"):
        return payload["source"]
    return "native" if folder.startswith("native") else folder


def entries(cache):
    """[(path, folder, entry, size)] of every entry of ``cache``, the pass's own included."""
    out = []
    for base in (cache.root, cache.work):
        if not base or not os.path.isdir(base):
            continue
        for folder in sorted(os.listdir(base)):
            sub = os.path.join(base, folder)
            if not os.path.isdir(sub):
                continue
            for name in sorted(os.listdir(sub)):
                path = os.path.join(sub, name)
                if not name.endswith(".json"):
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        entry = json.load(fh)
                    size = os.path.getsize(path)
                except (OSError, ValueError):
                    continue
                if isinstance(entry, dict):
                    out.append((path, folder, entry, size))
    return out


def stats_of(project):
    """{by: {"served": n, "saved": units}}: what the cache served since it was counted."""
    try:
        with open(os.path.join(project, ".probandia", STATS), encoding="utf-8") as fh:
            stats = json.load(fh)
    except (OSError, ValueError):
        return {}
    return stats if isinstance(stats, dict) else {}


def page_read(cache, url):
    """(entry, path) of the page ``read`` keeps for ``url`` (the ladder's ``http`` entries), or None."""
    return cache.live("http", make_key("http", url))


FAILURES = "read-failures.json"   # in .probandia/: {key: {"url", "status", "at", "ttl"}}


def _failure_key(url):
    return make_key("http", str(url).split("#")[0])


def _failures(project):
    path = os.path.join(project, ".probandia", FAILURES)
    try:
        with open(path, encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        found = {}
    return path, found if isinstance(found, dict) else {}


def note_failure(project, url, status, ttl, clock=time.time):
    """T66: ``read <url>`` could not read the page; kept ``ttl`` seconds (the cache's),
    so that G-17 lets the harness's own fetch try it. Never fails the command."""
    path, found = _failures(project)
    now = clock()
    found = {k: v for k, v in found.items() if isinstance(v, dict) and now - v.get("at", 0) < v.get("ttl", 0)}
    found[_failure_key(url)] = {"url": url, "status": status, "at": now, "ttl": ttl}
    try:
        atomic_write_json(path, found)
    except OSError:
        pass


def forget_failure(project, url):
    """The page was read after all: its failure is no longer news."""
    path, found = _failures(project)
    if found.pop(_failure_key(url), None) is not None:
        try:
            atomic_write_json(path, found)
        except OSError:
            pass


def failure_of(project, url, clock=time.time):
    """{"url", "status", "at", "ttl"} of read's last failure on ``url`` while it lives, or None."""
    entry = _failures(project)[1].get(_failure_key(url))
    if isinstance(entry, dict) and clock() - entry.get("at", 0) < entry.get("ttl", 0):
        return entry
    return None


def ttl_for(provider, config=None, catalogue_ttl=None):
    """Seconds: the provider's own setting, then the catalogue, then cache.days."""
    if config is not None and provider not in ("http",):
        try:
            days = config.get(f"providers.{provider}.cache_ttl")
        except KeyError:
            days = None
        if days is not None:
            return int(days) * DAY
    if catalogue_ttl is not None:
        return int(catalogue_ttl)
    days = config.get("cache.days") if config is not None else 7
    return int(days) * DAY
