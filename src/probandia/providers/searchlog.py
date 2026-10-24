"""Writing the search log of a family: ``families/<family>/index/searches.yaml``.

The search log records what was searched, never a conclusion. ``search`` and
the hook of native searches append to it directly, under the family lock, and
each write goes to the index change log like any other. A negative recorded
here is what the engines answered; it becomes proof only through ``apply`` and
``verify`` (witness, detector, families).
"""
import re

from probandia.indexes import FamilyIndexes, locked
from probandia.util.fs import iso, utc_now
from probandia.util.ids import ulid


def entry(query, kind, engine, family, result, research=None, pass_no=None, results=None,
          variants=(), window=None, failure=None, filters=None, units=None, proves=None):
    return {"id": f"s-{ulid()}", "ts": iso(utc_now()), "research": research, "pass": pass_no,
            "kind": kind, "engine": engine, "family": family, "query": query,
            "variants": list(variants), "filters": filters, "window": window, "results": results,
            "result": result, "failure": failure, "support": "index" if kind != "native" else None,
            "witness": None, "source_state": None, "recheck_if": None, "recheck_after": None,
            "units": units, "proves": proves}


def normalize(query):
    """A query as two searches compare it: case and spacing aside, quotes kept (an exact phrase)."""
    return " ".join(str(query or "").casefold().split())


def _sessions_differ(a, b):
    a, b = (a.get("filters") or {}).get("session"), (b.get("filters") or {}).get("session")
    return bool(a and b and a != b)


def logged_native(searches, e):
    """The native entry already logged for ``e``: same query, research, pass and session (a proposal's
    entry names no session). In Claude Code the hook logs each ``WebSearch``; the agent's
    ``search --log-native`` or its proposal would log it a second time, and the budget count it twice."""
    if e.get("kind") != "native":
        return None
    q = normalize(e.get("query"))
    return next((s for s in searches if s.get("kind") == "native" and s.get("id") != e.get("id")
                 and s.get("research") == e.get("research") and s.get("pass") == e.get("pass")
                 and normalize(s.get("query")) == q and not _sessions_differ(s, e)), None)


def native_cache(harness):
    """The cache folder of a harness's native searches, ``native:<harness>`` with a dash: no colon in a
    Windows file name."""
    return f"native-{harness}"


def native_key(harness, family, query, tool_input=None):
    """The cache key of a native search (T55): the family, the normalised query, the same domains."""
    from probandia.reading.cache import make_key

    tool_input = tool_input or {}
    domains = {k: sorted(str(d).strip().lower() for d in tool_input.get(k) or [])
               for k in ("allowed_domains", "blocked_domains")}
    return make_key(f"native:{harness}", query, dict(domains, family=family))


def keep_native(project, research, harness, e, tool_input, urls, days):
    """The URLs a native search returned, kept ``days`` days in the project's cache, so that the guard
    can refuse the same search once (T55, G-16). Returns the cache file's path."""
    from probandia.reading.cache import DAY, Cache

    payload = {"query": e["query"], "search": e["id"], "research": research.id, "pass": e.get("pass"),
               "ts": e["ts"], "results": len(urls), "urls": list(urls)}
    return Cache(project, research.work).put(native_cache(harness),
                                             native_key(harness, research.family, e["query"], tool_input),
                                             payload, "ok", int(days) * DAY, by="native")


def append(project, family, entries, actor, reason="search", dedupe=True):
    """Appends entries to the family's search log, under the family lock. A native search already
    logged (``logged_native``) is not added again: the id returned for it is the logged one's. The
    hook passes ``dedupe=False``: it sees each call the harness made, a repeated one included, and the
    session cap counts calls."""
    idx = FamilyIndexes(project, family)
    ids, new = [], []
    with locked(project, f"family:{family}", actor, wait_seconds=10):
        doc = idx.load("searches")
        for e in entries:
            same = logged_native(doc["searches"] + new, e) if dedupe else None
            ids.append(same["id"] if same else e["id"])
            if same is None:
                new.append(e)
        if new:
            doc["searches"].extend(new)
            idx.write({"searches": doc}, actor, reason)
    _logged(project, family, new, actor)
    return ids


def _logged(project, family, entries, actor):
    """Step 6 of a pass: one ``search.logged`` event per entry, in its research's log."""
    import os

    from probandia import events
    from probandia.errors import LockHeld
    from probandia.lifecycle import pass_state
    from probandia.research import Research

    by_research = {}
    for e in entries:
        if e.get("research"):
            by_research.setdefault(e["research"], []).append(e)
    for rid, items in by_research.items():
        research = Research(project, family, rid)
        if not os.path.isfile(os.path.join(research.folder, "research.yaml")):
            continue
        new = [events.make("search.logged", {"search": e["id"], "kind": e.get("kind"), "engine": e.get("engine")},
                           actor, e.get("pass") or 0, [e["id"]]) for e in items]
        try:
            # the search log entry is written; the event waits a little for the research lock
            with locked(project, f"research:{rid}", actor, wait_seconds=2):
                # only into the open pass: a search made after pass end stays in the search log alone
                last, open_ = pass_state(events.read(research.events_path))
                new = [n for n in new if open_ and n["pass"] == last]
                if new:
                    events.append(research.events_path, new)
        except LockHeld:
            pass


def urls_in(obj):
    """Every URL in a nested structure: what a native search returned."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("url", "uri", "link") and isinstance(v, str) and v.startswith("http"):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.startswith("http") and " " not in x:
            found.append(x)
    walk(obj)
    seen, out = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def urls_in_text(text):
    return list(dict.fromkeys(re.findall(r"https?://[^\s\"'<>)\]]+", text or "")))
