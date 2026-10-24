"""One record per free-tier account, for the quota screen (cli.md § 4.2).

An entry that draws on another entry's quota (``quota = "<id>"``: SerpApi's Bing
engine, Apify's reader) shares that account; entries with quotas of their own
(OpenWeb Ninja's three APIs) stay apart. Each record says what is left, what it
still pays for (searches, pages), when it starts again, and why an entry is out
of service. It reads the ledger only: nothing is called.
"""
import re

from probandia.providers import catalogue as catmod

# Sections of the screen, in order.
ROLES = ("search", "answer", "read", "last-resort", "model")

# The setting that brings an entry back, by the reason it is out of service.
REMEDY = {"not-enabled": "probandia providers enable", "card-required": "providers.allow_card_required",
          "content-reuse": "providers.allow_content_reuse"}


def role(entry):
    """``search`` (an index), ``answer`` (answers with sources), ``read``,
    ``last-resort`` (the unblocking readers) or ``model``. An extraction entry
    (``kind = "extract"``) reads pages: it is shown with the readers."""
    kind = entry.get("kind")
    if kind == "extract":
        return "read"
    if kind == "read":
        return "last-resort" if entry.get("unblocker") else "read"
    if kind == "model":
        return "model"
    return "answer" if entry.get("family") == "opaque" else "search"


def display_name(entry, shared):
    """A shared account keeps the name of its platform: ``Apify (Google Search
    Scraper)`` becomes ``Apify``."""
    name = entry.get("name", entry.get("id", ""))
    return re.sub(r"\s*\(.*\)$", "", name) if shared else name


def renewal(ledger, pool):
    """``{"kind": "reset"|"expires"|"first-use"|"never", "at": datetime or None, "months": n}``."""
    free = ledger.catalogue[pool].get("free") or {}
    if free.get("period") == "once":
        months = free.get("expires_months")
        if not months:
            return {"kind": "never", "at": None}
        if ledger.period_start(pool).year == 1970:
            return {"kind": "first-use", "at": None, "months": months}
        return {"kind": "expires", "at": ledger.period_end(pool)}
    return {"kind": "reset", "at": ledger.period_end(pool)}


def accounts(cat, ledger, config, environ, reserve_percent):
    """The accounts, in catalogue order."""
    groups = {}
    for pid in cat:
        groups.setdefault(ledger.pool(pid), []).append(pid)
    out = []
    for pool, ids in groups.items():
        entry = cat[pool]
        free = entry.get("free") or {}
        reasons = {p: catmod.why_unusable(cat[p], config, environ) for p in ids}
        usable = [p for p in ids if reasons[p] is None]
        used, warning = ledger.used(pool)
        left = ledger.left(pool, reserve_percent)
        amount = free.get("amount")
        if ledger.exhausted(pool):
            state = "exhausted"
        elif ledger.expired(pool):
            state = "expired"
        else:
            state = "ready" if usable else reasons[ids[0]]
        pays = {}
        for p in usable or ids:
            for op, n in ledger.operations(p, reserve_percent).items():   # None: unlimited
                if op not in pays:
                    pays[op] = n
                elif pays[op] is not None:
                    pays[op] = None if n is None else max(pays[op], n)
        roles = sorted({role(cat[p]) for p in ids}, key=ROLES.index)
        st = ledger.state().get(pool, {})
        out.append({
            "account": pool, "name": display_name(entry, len(ids) > 1), "platform": catmod.platform(entry),
            "entries": ids, "usable": usable, "out": {p: reasons[p] for p in ids if reasons[p]},
            "roles": roles, "section": roles[-1], "state": state,
            "unit": entry.get("unit"), "amount": amount, "used": used,
            "reserve": ledger.reserve(pool, reserve_percent), "left": left,
            # the user's monthly_cap, when lower than the free tier, is the top of the gauge (T53)
            "cap": ledger.monthly_cap(pool), "ceiling": ledger.ceiling(pool),
            "fraction": ledger.fraction_left(pool, reserve_percent),
            "pays": pays, "period": free.get("period"), "renewal": renewal(ledger, pool),
            "source": ledger.source(pool), "synced_at": st.get("reported_at"), "gap": warning,
            "balance": (entry.get("introspection") or {}).get("method", "none"),
            "key": catmod.key_env(entry),
        })
    return out


def families(cat, ledger, config, environ, reserve_percent):
    """``(usable, missing)``: the keyword index families a web negative can count
    on now, and for each missing one the entries that would bring it, with why
    they are out."""
    usable, candidates = set(), {}
    for pid, entry in cat.items():
        fam = entry.get("family")
        if not entry.get("keyword") or fam not in catmod.KEYWORD_FAMILIES:
            continue
        why = catmod.why_unusable(entry, config, environ)
        left = ledger.left(pid, reserve_percent)
        if why is None and (left is None or left > 0):
            usable.add(fam)
        else:
            candidates.setdefault(fam, []).append((pid, why or ("exhausted" if left == 0 else "no-quota")))
    order = list(catmod.KEYWORD_FAMILIES)
    missing = {f: c for f, c in candidates.items() if f not in usable}
    return sorted(usable, key=order.index), dict(sorted(missing.items(), key=lambda kv: order.index(kv[0])))
