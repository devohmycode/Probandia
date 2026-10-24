"""Engine commands of providers and quotas: plan, quota, search."""
import os

from probandia.cli.output import Result
from probandia.errors import EXIT_STOP, UsageError
from probandia.i18n import _


def _ledger(ctx):
    from probandia.ledger import Ledger
    from probandia.providers import catalogue

    return Ledger(ctx.project, catalogue.load(), environ=ctx.environ, config=ctx.config)


def _client(ctx):
    from probandia.util.http import Client, contact

    return Client(os.path.join(ctx.project, ".probandia"), contact(ctx.environ, ctx.config), ctx.config)


# plan


def plan_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--question-type", choices=("birth", "marriage", "death", "parents", "children",
                                               "residence", "migration", "identity", "negative",
                                               "general"))
    p.add_argument("--focus", help=_("what this pass aims at, instead of the open hypothesis or the question"))
    p.add_argument("--window", help=_("years: 1840-1860, 1851 or 1851+-5"))
    from probandia.cli.lifecycle_cmd import parallel_option

    parallel_option(p)


def _need(doc):
    axes = doc.get("axes") or {}
    w = axes.get("window") or {}
    return " ".join([doc.get("question") or "", " ".join(axes.get("places") or []),
                     " ".join(axes.get("record_types") or []), f"{w.get('from', '')} {w.get('to', '')}"])


def _browser_archives(ctx, doc):
    """The archives without a connector that match the plan, read in a browser."""
    from probandia.archives.finder import find

    try:
        return find(_need(doc), ctx.project)[1]
    except Exception:   # noqa: BLE001 — the plan never fails on the catalogue
        return []


def browser_guided(ctx, doc):
    """The browser archives of the pass whose way of reading is known (``guide``), only
    when the plan names a place they cover: without one, every browser archive matches."""
    from probandia.archives.coverage import covers, places_in

    codes = places_in(_need(doc))
    if not codes:
        return []
    return [e["id"] for e in _browser_archives(ctx, doc)
            if e.get("guide") and covers((e.get("coverage") or {}).get("places", []), codes)]


def signin_only(cat, doc):
    """The archives that alone hold one of the question's record types for its places
    and years, all behind a sign-in (Luxembourg's civil births and deaths: FamilySearch;
    Matricula has the parish registers only): the pass reaches no such act without
    them, though the plan calls none. A free archive of that type, connector or browser
    (the Manche's, the Doubs'), and nothing is asked."""
    from probandia.archives.coverage import covers, places_in
    from probandia.planner import RECORDS, _outside

    axes = doc.get("axes") or {}
    codes = list(dict.fromkeys((axes.get("place_codes") or []) + places_in(_need(doc))))
    if not codes:
        return []
    w = axes.get("window") or {}
    wanted = set(axes.get("record_types") or []) & RECORDS or RECORDS
    holders = {}
    for archive, e in cat.items():
        cov = e.get("coverage") or {}
        places = cov.get("places") or []
        # a country's own archives cover it as well: FR-50 covers a question in France
        if (not _outside(cov, (w.get("from"), w.get("to")), None, None)
                and (covers(places, codes) or any(p.startswith(c + "-") for p in places for c in codes))
                and not covers(cov.get("absent") or [], codes)):
            for t in wanted & set(cov.get("types") or []):
                holders.setdefault(t, []).append(archive)
    out = []
    for t in sorted(holders):
        if all((cat[a].get("login") or {}).get("required") for a in holders[t]):
            out += [a for a in holders[t] if a not in out]
    return out


def login_needed(ctx, doc):
    """optimize 3.7: the archives the pass may use that need the user's session, not
    yet confirmed: ask for them all at once, before the field agents start. Only those
    the plan really calls or hands to the browser (token-economy C6), and those without
    which no record of the question's places can be read (``signin_only``)."""
    from probandia import logins
    from probandia.archives.finder import load_catalogue

    cat = load_catalogue(ctx.project)
    planned = {c.get("engine") for c in doc.get("calls") or []}
    planned |= set(browser_guided(ctx, doc))
    planned |= set(signin_only(cat, doc))
    out = []
    for archive in sorted(a for a in planned if a in cat):
        block = cat[archive].get("login") or {}
        if block.get("required") and not logins.valid(logins.state(ctx.project, archive), block.get("session_hours")):
            out.append(archive)
    return out


def quota_low(low):
    """QUOTA_LOW=: ``tavily:12%,exa:5%``."""
    return ",".join(f"{p}:{n}%" for p, n in low)


def plan(ctx):
    from probandia.known import parse_window
    from probandia.research import find_research

    years = parse_window(ctx.args.window)
    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    return plan_result(ctx, research, ctx.args.question_type, ctx.args.focus, years)[1]


def plan_result(ctx, research, question_type=None, focus=None, years=None):
    """(plan document, Result) of ``plan``; ``new`` runs it too (token-economy B1)."""
    from probandia import planner
    from probandia.providers import catalogue

    from probandia.budget import native_budget
    from probandia.cli.data_cmd import actor
    from probandia.guard import FIELD_ROLES

    usable = catalogue.usable(ctx.config, ctx.environ)
    # A field agent reads the orchestrator's plan; it neither rewrites it nor writes plan.made.
    field = actor(ctx)["agent"] in FIELD_ROLES
    doc, path = planner.plan(ctx.project, research, ctx.config, ctx.environ, question_type,
                             _ledger(ctx), usable, write=not field, focus=focus, years=years)
    if not field:
        _plan_made(ctx, research, doc, path)

    native = native_budget(ctx.project, research, ctx.config, ctx.environ, actor(ctx)["harness"])
    axes = doc["axes"]
    w = axes["window"]
    r = Result("OK", {"RESEARCH": research.id, "PASS": doc["pass"], "TYPE": doc["question_type"],
                      "NAMES": len(axes["names"]), "PLACES": len(axes["places"]),
                      "WINDOW": f"{w['from']}-{w['to']}", "WINDOW_BASIS": w.get("basis"), "CALLS": len(doc["calls"]),
                      "REMOVED": len(doc["removed"]), "NATIVE_LEFT": native["left"],
                      "NATIVE_PARALLEL": native["parallel"]},
               details=os.path.relpath(path, ctx.project).replace(os.sep, "/") if path else "")
    if axes.get("place_codes"):
        r.set("PLACE_CODES", ",".join(axes["place_codes"]))
    if axes.get("places_unknown"):   # C3: a place the question names, found nowhere, is said
        r.set("PLACES_UNKNOWN", "; ".join(axes["places_unknown"]))
        from probandia.lang import places as pl

        if not pl.cog_installed(os.path.join(pl.data_dir(ctx.environ), "insee")):
            r.line(_("insee: the COG files are not installed (places --update-cog)"))
    anchors = axes.get("anchors") or []
    if anchors:   # C1: the facts the question gives to place the person, not the event it seeks
        r.set("ANCHOR", "; ".join(" ".join(str(x) for x in (a["type"], "about" if a["qualifier"] == "about" else "",
                                                               a["year"], a.get("place") or "") if x)
                                  for a in anchors))
    focus = doc.get("focus") or {}
    r.set("FOCUS", focus.get("source", "question"))
    low = _ledger(ctx).low(usable, ctx.config.get("budget.reserve_percent"))
    if low:   # T62: before the STOP, under 20 % of a quota left (none: the key is left out, E6)
        r.set("QUOTA_LOW", quota_low(low))
    from probandia import complexity

    r.set("LOGIN_NEEDED", ",".join(login_needed(ctx, doc)) or "none")
    guided = browser_guided(ctx, doc)
    if guided:
        # the token analysis of 6 Oct. 2026: ~50 browser calls read in the session's own context
        r.set("BROWSER_GUIDED", ",".join(guided))
        r.line(_("registers to read in a browser ({ids}): archive find <need> gives the way; in session mode, "
                 "hand the reading to one researcher subagent, so that the views stay out of your context").format(
            ids=", ".join(guided)))
    guess = complexity.estimate(ctx.project, research.family, doc["question"])
    r.set("DIFFICULTY", guess["level"])
    r.data("difficulty", f"score={guess['score']} {' '.join(guess['reasons']) or '-'} "
                         f"suggests {guess['mode']}, effort {guess['effort']}")
    r.data("focus", doc["question"] + (f" [{focus['person']}]" if focus.get("person") else ""))
    from probandia.proof import questions as Q

    for q in Q.unsettled(research.meta() or {}):   # T249: what will count as an answer, for each open question
        if q.get("standard"):
            r.data("standard", f"{q['id']}: {q['standard']}")
    r.data("names", ", ".join(axes["names"]))
    if axes["places"]:
        r.data("places", ", ".join(axes["places"]))
    if axes["record_types"]:
        r.data("record_types", ", ".join(axes["record_types"]))
    for provider, units in sorted(doc["estimate"].items()):
        r.data("estimate", f"{provider} {units:g}")
    reads = doc.get("reads") or {}
    r.set("READS", reads.get("pages", 0))
    for provider, units in sorted((reads.get("estimate") or {}).items()):
        r.data("estimate", f"{provider} {units:g} read")
    todo = [t for t in doc.get("matrix") or [] if t["state"] == "todo"]
    r.set("MATRIX_TODO", len(todo))
    for t in doc.get("matrix") or []:
        r.data("matrix", f"{t['question']}.{t['type']} {t['state']} "
                         f"{','.join(t['repositories']) or '-'} {t['years'][0]}-{t['years'][1]}")
    outside = {}
    for c in doc["removed"]:
        if c["reason"] == "out-of-coverage":   # one line per archive, not one per record type
            outside.setdefault((c["engine"], c.get("detail", "")), []).append(c.get("record_type") or "-")
            continue
        if c["reason"] == "unusable":   # C6: no key; counted in REMOVED=, listed in DETAILS= only
            continue
        r.data("removed", f"{c['engine']} \"{c['query']}\" {c.get('record_type') or '-'} "
                          f"{c['reason']} {c.get('detail', '')}".rstrip())
    for (engine, detail), types in outside.items():
        r.data("removed", f"{engine} {','.join(dict.fromkeys(types))} out-of-coverage {detail}")
    return doc, r


def _plan_made(ctx, research, doc, path):
    """Step 4 of a pass: ``plan.made``, in the open pass only."""
    from probandia import events
    from probandia.cli.data_cmd import actor
    from probandia.indexes import locked
    from probandia.lifecycle import pass_state

    last, open_ = pass_state(events.read(research.events_path))
    if not open_ or doc["pass"] != last:
        return None
    payload = {"plan": os.path.relpath(path, research.folder).replace(os.sep, "/"),
               "question_type": doc["question_type"], "calls": len(doc["calls"]),
               "estimate": doc["estimate"]}
    with locked(ctx.project, f"research:{research.id}", actor(ctx), ctx.config.get("locks.expiry_minutes")):
        if pass_state(events.read(research.events_path)) != (last, True):  # closed while we waited
            return None
        return events.append(research.events_path, [events.make("plan.made", payload, actor(ctx), last)])


# quota


def quota_args(p, common):
    p.add_argument("action", nargs="?", default="show", choices=("show", "sync", "add", "estimate"))
    p.add_argument("provider", nargs="?")
    p.add_argument("units", nargs="?", type=float)
    p.add_argument("--note", help=_("what the manual use was, for quota add"))
    p.add_argument("--calls", type=int, default=1, help=_("planned calls, for quota estimate"))
    p.add_argument("--operation", default="search")


def quota(ctx):
    from probandia.providers import catalogue

    cat = catalogue.load()
    ledger = _ledger(ctx)
    reserve = ctx.config.get("budget.reserve_percent")
    action = ctx.args.action
    if ctx.args.provider and ctx.args.provider not in cat:
        from probandia.suggest import lines

        raise UsageError(_("unknown provider {provider}").format(provider=ctx.args.provider),
                         lines=lines(ctx.args.provider, cat))

    if action == "add":
        if ctx.args.provider is None or ctx.args.units is None:
            raise UsageError(_("quota add needs a provider and a number of units"))
        from probandia.cli import asking

        if not asking.confirm(ctx, _("Record {units} units used on {provider}? The ledger is only ever "
                                     "added to.").format(units=ctx.args.units, provider=ctx.args.provider)):
            return asking.declined({"PROVIDER": ctx.args.provider})
        ledger.record(ctx.args.provider, "manual", ctx.args.units, "manual", note=ctx.args.note)
        return Result("OK", {"PROVIDER": ctx.args.provider, "UNITS": ctx.args.units,
                             "LEFT": _fmt(ledger.left(ctx.args.provider, reserve))})

    if action == "estimate":
        if ctx.args.provider is None:
            raise UsageError(_("quota estimate needs a provider"))
        p = ctx.args.provider
        needed = ledger.cost(p, ctx.args.operation, ctx.args.calls)
        left = ledger.left(p, reserve)
        values = {"PROVIDER": p, "OPERATION": ctx.args.operation, "NEEDED": needed,
                  "LEFT": _fmt(left), "RESERVE": ledger.reserve(p, reserve)}
        if left is not None and needed > left:
            return stop_result(ctx, p, values, ctx.args.operation)
        return Result("OK", values)

    if action == "sync":
        targets = [ctx.args.provider] if ctx.args.provider else catalogue.usable(ctx.config, ctx.environ)
        r = Result("OK", {"SYNCED": 0})
        synced, drifts, rows = 0, {}, []
        for p, outcome, left in sync_providers(ctx, targets, cat, ledger, drifts):
            rows.append({"provider": p, "outcome": outcome, "left": left})
            if outcome == "ok":
                synced += 1
                r.data("sync", f"{p} left={_fmt(left)}")
            else:
                if outcome.startswith("failed"):
                    r.status = "WARN"
                r.data("sync", f"{p} {outcome}")
        r.set("SYNCED", synced)
        r.table("sync", rows, hidden=True)
        if drifts:
            r.set("QUOTA_DRIFT", ",".join(f"{p}:{d['percent']}%" for p, d in drifts.items()))
            r.lines += [drift_line(p, d) for p, d in drifts.items()]
        return r

    r = Result("OK", {"PROVIDERS": 0})
    shown, rows = 0, []
    # The entries that share a key are listed together, under their platform.
    shared = {p: (env, ids) for env, ids in catalogue.shared_keys(cat).items() for p in ids}
    order, headed = [], set()
    for p in cat:
        if p in shared:
            if shared[p][0] not in headed:
                headed.add(shared[p][0])
                order.extend(shared[p][1])
        else:
            order.append(p)
    headed = set()
    for p in order:
        entry = cat[p]
        if ctx.args.provider and p != ctx.args.provider:
            continue
        if p in shared and shared[p][0] not in headed:
            env, ids = shared[p]
            headed.add(env)
            r.data("platform", f"{catalogue.platform(entry)} key={env} entries={','.join(ids)}")
        why = catalogue.why_unusable(entry, ctx.config, ctx.environ)
        free = entry.get("free") or {}
        used, warning = ledger.used(p)
        left = ledger.left(p, reserve)
        state = ("exhausted" if ledger.exhausted(p) else "expired" if ledger.expired(p)
                 else (why or "ready"))
        parts = [f"{p} {state} used={used:g} of={_fmt(free.get('amount'))}"]
        cap = ledger.monthly_cap(p)
        if cap is not None:   # T53: the user's lower cap, counted in the month
            parts.append(f"cap={cap}/month")
        parts += [f"left={_fmt(left)}", f"period={free.get('period', '?')}"]
        parts += [f"{OP_WORDS[op]}={_fmt(n)}" for op, n in ledger.operations(p, reserve).items()]
        parts += [f"source={ledger.source(p)}", f"reset={_reset(ledger, p)}"]
        r.data("provider", " ".join(parts))
        rows.append({"provider": p, "platform": catalogue.platform(entry) if p in shared else None,
                     "state": state, "used": used, "amount": free.get("amount"), "cap": cap, "left": left,
                     "period": free.get("period"), "operations": ledger.operations(p, reserve),
                     "source": ledger.source(p), "reset": _reset(ledger, p)})
        if warning and why is None:
            r.status = "WARN"
            r.line(_("gap of more than 10 %: {detail}").format(detail=warning))
        shown += 1
    r.set("PROVIDERS", shown)
    r.table("providers", rows, hidden=True)
    return r


def sync_providers(ctx, targets, cat, ledger, drifts=None):
    """Reads the balances the providers report, at no cost: ``[(provider, outcome,
    left)]`` with ``ok``, ``skipped no-key``, ``no-introspection`` or ``failed <error>``.
    ``drifts`` receives {provider: drift} for the readings the ledger does not explain."""
    from probandia.providers import adapters, catalogue

    client = _client(ctx)
    out = []
    for p in targets:
        if catalogue.why_unusable(cat[p], ctx.config, ctx.environ) == "no-key":
            out.append((p, "skipped no-key", None))
            continue
        before = ledger.reading(p)
        try:
            info = adapters.sync(p, client, cat[p], ctx.environ, ledger)
        except Exception as err:  # one provider failing does not stop the others
            ledger.synced(p, before, ok=False)
            out.append((p, f"failed {type(err).__name__}", None))
            continue
        if info is None:
            out.append((p, "no-introspection", None))
            continue
        drift = ledger.synced(p, before)
        if drift and drifts is not None:
            drifts[p] = drift
        out.append((p, "ok", info.get("left")))
    return out


# The commands that read every balance once a day (decision T7). The others of
# cli.SYNC_COMMANDS read one after 20 calls counted on it; never a hook, which must
# answer in seconds.
SYNC_DAILY_COMMANDS = ("new", "resume")


def auto_sync(ctx):
    """T52: reads the balances that are due, before the command runs. A ``Result``
    to merge into the command's (``merge_sync``), or None when nothing was due.
    Never fails the command: a reading that fails is a warning."""
    command = getattr(ctx.args, "command", None)
    try:
        from probandia.providers import adapters, catalogue

        cat = catalogue.load()
        ledger = _ledger(ctx)
        readable = [p for p in catalogue.usable(ctx.config, ctx.environ) if p in adapters.SYNC]
        due = ledger.sync_due(readable, daily=command in SYNC_DAILY_COMMANDS)
        if not due:
            return None
        drifts = {}
        outcomes = sync_providers(ctx, due, cat, ledger, drifts)
    except Exception:   # noqa: BLE001 — outside a project, a bad setting: the command says it itself
        return None
    return sync_result(outcomes, drifts)


def sync_result(outcomes, drifts):
    """QUOTA_SYNC=, QUOTA_DRIFT= and their lines, for the outcomes of ``sync_providers``."""
    r = Result("OK")
    read = sum(1 for _p, outcome, _l in outcomes if outcome == "ok")
    if read:
        r.set("QUOTA_SYNC", read)
    if drifts:
        r.set("QUOTA_DRIFT", ",".join(f"{p}:{d['percent']}%" for p, d in drifts.items()))
        r.lines += [drift_line(p, d) for p, d in drifts.items()]
    failed = [(p, outcome.split(" ", 1)[1]) for p, outcome, _l in outcomes if outcome.startswith("failed")]
    if failed:   # one line for all: offline, every reading fails alike
        r.line(_("balances not read ({errors}): the local count stands").format(
            errors=", ".join(f"{p} {error}" for p, error in failed)))
    return r


def drift_line(provider, drift):
    return _("{provider}: the provider counted {provider_units:g} units since {since}, the ledger "
             "{counted:g} ({percent}% apart): another project, a connector or the provider's site").format(
        provider=provider, provider_units=drift["provider"], counted=drift["counted"],
        since=str(drift["since"])[:10], percent=drift["percent"])


def merge_sync(result, synced):
    """The keys and lines of ``auto_sync`` added to the command's result."""
    if synced is None or result is None or result.status == "ASK":   # a question stays a question
        return
    for key, value in synced.values.items():
        if key not in result.values:
            result.set(key, value)
    result.lines = synced.lines + result.lines   # first: the 40-line cap cuts the end


# What the quota left pays for, in plain words: searches, pages read.
OP_WORDS = {"search": "searches", "read": "pages"}


def _reset(ledger, provider):
    """The day the quota starts again, or ``never`` for a one-off tier."""
    free = ledger.catalogue[ledger.pool(provider)].get("free") or {}
    if free.get("period") == "once":
        if not free.get("expires_months"):
            return "never"
        if ledger.period_start(provider).year == 1970:   # never used: expires after the first use
            return f"first-use+{free['expires_months']}m"
    return ledger.period_end(provider).date().isoformat()


def _fmt(v):
    if v is None:
        return "unlimited"
    return f"{v:g}" if isinstance(v, float) else str(v)


def next_free(ctx, provider, family=None, operation="search"):
    """The next usable provider with free quota left, same family first: a search
    provider, a reader for ``operation="read"``, or one that makes ``map``, ``crawl``
    or ``extract``."""
    from probandia.providers import catalogue

    cat = catalogue.load()
    ledger = _ledger(ctx)
    reserve = ctx.config.get("budget.reserve_percent")
    if operation in ("map", "crawl", "extract"):   # read --map, --crawl, --extract (T229-T231)
        usable = [p for p in catalogue.usable(ctx.config, ctx.environ, operation=operation) if p != provider]
    elif operation.startswith("read"):   # T256: the ladder's readers in their order, then the unblocking ones
        from probandia.reading.ladder import reader_order

        order = reader_order(ctx.config)
        usable = [p for p in catalogue.usable(ctx.config, ctx.environ)
                  if p != provider and (p in order or cat[p].get("unblocker"))]
        usable.sort(key=lambda p: order.index(p) if p in order else len(order))
    else:
        usable = [p for p in catalogue.usable(ctx.config, ctx.environ, "search") if p != provider]
    if family:
        usable.sort(key=lambda p: cat[p].get("family") != family)
    for p in usable:
        left = ledger.left(p, reserve)
        if left is None or left >= ledger.cost(p, operation):
            return p
    return None


def stop_result(ctx, provider, values=None, operation="search"):
    from probandia.providers import catalogue

    alt = next_free(ctx, provider, catalogue.load()[provider].get("family"), operation)
    r = Result.stop(f"free-quota:{provider}", alt, values)
    r.exit_code = EXIT_STOP
    r.line(_("the free quota of {provider} is used up; nothing is paid").format(provider=provider))
    return r

