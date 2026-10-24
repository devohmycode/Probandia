"""``cache``: what the cache of responses holds and saves the quotas, and its purge (T64, CLI11-T1).

- ``cache stats``: by provider (the native searches' URLs as ``native``, pages read directly as
  ``http``), the entries, their size, the oldest and the newest, the expired ones, the answers served
  and the units they saved;
- ``cache clear [--provider <id>] [--older-than 30d] [--expired]``: removes those entries, and nothing
  else, after a ``[y/N]`` (``--yes`` answers it). The counts of what was served stay.

The cache is ``.probandia/cache/`` and the open research's ``work/cache/`` (``reading/cache.py``).
"""
import os
import re
import time

from probandia.cli.output import Result
from probandia.errors import ProbandiaError, UsageError
from probandia.i18n import _

ACTIONS = ("stats", "clear")
DAY = 86400


def configure(p, common):
    p.add_argument("action", nargs="?", default="stats", choices=ACTIONS)
    p.add_argument("--provider", metavar="<id>", help=_("only the entries paid to this provider (native, http, tavily…)"))
    p.add_argument("--older-than", dest="older_than", metavar="<age>", help=_("clear: entries older than this: 30d, 12h"))
    p.add_argument("--expired", action="store_true", help=_("clear: only the entries past their time to live"))


def _age(text):
    """Seconds of ``30d``, ``12h`` or ``30`` (days)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([dh]?)\s*", str(text or ""))
    if not m:
        raise UsageError(_("--older-than takes a number of days or hours: 30d, 12h"), values={"REASON": "options"})
    return float(m.group(1)) * (3600 if m.group(2) == "h" else DAY)


def _days(seconds):
    return round(seconds / DAY, 1)


def _expired(entry, now):
    ttl = entry.get("ttl", 0)
    return ttl > 0 and now - entry.get("created", 0) >= ttl


def _cache(ctx):
    from probandia.reading.cache import Cache
    from probandia.research import find_research

    try:
        work = find_research(ctx.project, None, ctx.environ).work
    except ProbandiaError:
        work = None
    return Cache(ctx.project, work)


def _entries(ctx, now):
    from probandia.reading.cache import entries, paid_by

    out = [(path, paid_by(folder, entry), entry, size) for path, folder, entry, size in entries(_cache(ctx))]
    if ctx.args.provider:
        out = [e for e in out if e[1] == ctx.args.provider]
    return out


def stats(ctx):
    from probandia.reading.cache import stats_of

    now = time.time()
    rows = {}
    for _path, by, entry, size in _entries(ctx, now):
        row = rows.setdefault(by, {"provider": by, "entries": 0, "bytes": 0, "expired": 0, "oldest_days": 0.0,
                                   "newest_days": None, "served": 0, "saved": 0})
        age = _days(max(0.0, now - entry.get("created", now)))
        row["entries"] += 1
        row["bytes"] += size
        row["expired"] += _expired(entry, now)
        row["oldest_days"] = max(row["oldest_days"], age)
        row["newest_days"] = age if row["newest_days"] is None else min(row["newest_days"], age)
    for by, counted in stats_of(ctx.project).items():
        if ctx.args.provider and by != ctx.args.provider:
            continue
        row = rows.setdefault(by, {"provider": by, "entries": 0, "bytes": 0, "expired": 0, "oldest_days": None,
                                   "newest_days": None, "served": 0, "saved": 0})
        row["served"], row["saved"] = counted.get("served", 0), round(counted.get("saved", 0), 4)
    table = sorted(rows.values(), key=lambda r: (-r["entries"], r["provider"]))
    r = Result("OK", {"ENTRIES": sum(x["entries"] for x in table), "BYTES": sum(x["bytes"] for x in table),
                      "EXPIRED": sum(x["expired"] for x in table), "SERVED": sum(x["served"] for x in table),
                      "PROVIDERS": len(table)})
    for x in table[:30]:
        r.data("provider", f"{x['provider']} entries={x['entries']} bytes={x['bytes']} expired={x['expired']} "
                           f"oldest={x['oldest_days'] if x['oldest_days'] is not None else '-'}d "
                           f"served={x['served']} saved={x['saved']:g}")
    r.table("cache", table)
    if not table:
        r.line(_("the cache is empty"))
    elif any(x["saved"] for x in table):
        r.line(_("saved: the units of each provider's own quota the answers served from the cache did not spend"))
    return r


def clear(ctx):
    from probandia.cli import asking

    now = time.time()
    found = _entries(ctx, now)
    if ctx.args.older_than:
        limit = _age(ctx.args.older_than)
        found = [e for e in found if now - e[2].get("created", now) > limit]
    if ctx.args.expired:
        found = [e for e in found if _expired(e[2], now)]
    values = {"PROVIDER": ctx.args.provider or "all", "OLDER_THAN": ctx.args.older_than or "",
              "ENTRIES": len(found), "BYTES": sum(e[3] for e in found)}
    if not found:
        return Result("OK", dict(values, REMOVED=0), [_("nothing in the cache matches")])
    question = _("Remove {n} cache entries ({size} bytes)? Those answers will be paid for again if asked "
                 "again.").format(n=len(found), size=values["BYTES"])
    if not asking.confirm(ctx, question):
        return asking.declined(values)
    removed = 0
    for path, _by, _entry, _size in found:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    r = Result("OK", dict(values, REMOVED=removed))
    by = {}
    for _path, who, _entry, _size in found:
        by[who] = by.get(who, 0) + 1
    for who, n in sorted(by.items()):
        r.data("removed", f"{who} {n}")
    return r


def run(ctx):
    ctx.project   # NotInProject: exit 6
    if ctx.args.action == "clear":
        return clear(ctx)
    if ctx.args.older_than or ctx.args.expired:
        raise UsageError(_("--older-than and --expired go with cache clear"), values={"REASON": "options"})
    return stats(ctx)
