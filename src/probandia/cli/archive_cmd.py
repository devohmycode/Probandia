"""``archive find "<need>"`` and ``archive run <archive>.<operation> --args <json>``."""
import json
import os
import re

from probandia.cli.output import Result
from probandia.errors import EXIT_FAIL, UsageError
from probandia.i18n import _
from probandia.lifecycle import current_pass


# The keys a connector reads, when it has one (none is required but Europeana's,
# which falls back on a public demonstration key).
CONNECTOR_KEYS = {"europeana": "EUROPEANA_API_KEY", "geonames": "GEONAMES_USERNAME",
                  "wayback": "IA_ACCESS_KEY", "matchid": None}
DEPARTMENTAL = re.compile(r"^ad(\d{2,3}|2a|2b)$")   # catalogues/archives-fr-ad.yaml
MAIN_ROLES = ("session", "orchestrator")   # token-economy A7: they hand a register's views to a reader


def archive_args(p, common):
    p.add_argument("action", choices=("find", "run", "list", "coverage", "stale"))
    p.add_argument("target", nargs="?", help=_("the need (find), <archive>.<operation> (run), a place (coverage)"))
    p.add_argument("--from", dest="year_from", type=int, help=_("coverage: from this year"))
    p.add_argument("--to", dest="year_to", type=int, help=_("coverage: to this year"))
    p.add_argument("--args", dest="op_args", default="{}", help=_("the operation's parameters, as JSON"))
    p.add_argument("--research", help=_("research id: the run goes to its search log"))
    p.add_argument("--days", type=int, help=_("stale: older than this many days (catalogues.max_age_days, 90)"))
    p.add_argument("--all", action="store_true",
                   help=_("find: every operation, and the browser archives of other places; list: every "
                          "departmental archive"))


def _context(ctx):
    from probandia.archives import Context
    from probandia.lang.places import data_dir
    from probandia.util.http import Client, contact

    project = ctx.project
    client = Client(os.path.join(project, ".probandia"), contact(ctx.environ, ctx.config), ctx.config)
    return Context(client, project, ctx.environ, data_dir(ctx.environ))


def archive(ctx, context=None):
    from probandia import archives
    from probandia.archives.finder import find

    if ctx.args.action == "list":
        return _list(ctx)
    if ctx.args.action == "coverage":
        return _coverage(ctx)
    if ctx.args.action == "stale":
        return stale(ctx)
    if not ctx.args.target:
        raise UsageError(_("archive {action} needs a target").format(action=ctx.args.action))
    if ctx.args.action == "find":
        # F3: three operations, and the browser archives of the place asked; --all for the rest
        best, browser = find(ctx.args.target, ctx.project, limit=None if ctx.args.all else 3,
                             place_only=not ctx.args.all)
        r = Result("OK", {"NEED": ctx.args.target, "OPERATIONS": len(best)})
        for score, archive_id, name, op, _entry in best:
            params = ", ".join(f"{p}:{t.__name__}" for p, t in op.params.items())
            r.data("operation", f"{archive_id}.{name} ({params}) score={score} — {op.doc}")
        for entry in browser[:3]:
            login = " login-required" if (entry.get("login") or {}).get("required") else ""
            r.data("browser", f"{entry['id']} {entry.get('name', '')} — "
                              f"{(entry.get('access') or {}).get('mode', '')}{login}")
            # how to read the site, found once (optimize, token analysis of 6 Oct. 2026): never again by trial
            for step in (entry.get("guide") or [])[:6]:
                r.data("guide", f"{entry['id']}: {step}")
        if any(entry.get("guide") for entry in browser[:3]):
            r.line(_("reading registers in a browser: hand it to one researcher subagent (this archive, the "
                     "register, the acts sought), the guide lines in its brief, so that the views stay out of "
                     "your context"))
        return r

    archive_id, operation = archives.parse_address(ctx.args.target)
    module = archives.load(archive_id, ctx.project)
    context = context or _context(ctx)
    research = _research(ctx)
    if context.work is None and research is not None:
        context.work = research.work
    if operation == "witness":
        return _witness(ctx, module, context, research)
    try:
        args = json.loads(ctx.args.op_args)
    except ValueError:
        raise UsageError(_("--args must be a JSON object"))
    if not isinstance(args, dict):
        raise UsageError(_("--args must be a JSON object"))
    from probandia.cli import asking

    ask = getattr(module, "question", None)   # T158: a connector may say what the run costs (a download's size)
    if not asking.confirm(ctx, (ask and asking.will_ask(ctx) and ask(operation, args, context)) or _(
            "Run {archive}.{operation} on the archive's site?").format(archive=archive_id, operation=operation)):
        return asking.declined({"ARCHIVE": archive_id, "OPERATION": operation})
    result = archives.run(module, operation, args, context)
    _log(ctx, research, archive_id, operation, args, result)
    return _render(ctx, archive_id, operation, result, research)


def _research(ctx):
    from probandia.errors import ProbandiaError
    from probandia.research import find_research

    try:
        return find_research(ctx.project, ctx.args.research, ctx.environ)
    except ProbandiaError:
        return None


def _render(ctx, archive_id, operation, result, research):
    from probandia.util.fs import atomic_write_text
    from probandia.util.ids import ulid

    if result.status != "ok":
        r = Result("FAIL", {"REASON": "connector", "ARCHIVE": archive_id, "OPERATION": operation,
                            "FAILURE": result.failure_code}, [result.failure or _("the archive did not answer")],
                   exit_code=EXIT_FAIL)
        if result.url:
            r.set("URL", result.url)
        return r
    folder = os.path.join(research.work, "details") if research else os.path.join(
        ctx.project, ".probandia", "details")
    path = os.path.join(folder, f"archive-{archive_id}-{operation}-{ulid()}.json")
    atomic_write_text(path, json.dumps({"url": result.url, "count": result.count, "rows": result.rows,
                                        "text": result.text, "path": result.path},
                                       ensure_ascii=False, indent=2) + "\n")
    r = Result("OK", {"ARCHIVE": archive_id, "OPERATION": operation, "COUNT": result.n,
                      "ROWS": len(result.rows)}, details=os.path.relpath(path, ctx.project).replace(os.sep, "/"))
    if result.path:
        r.set("FILE", result.path)
        from probandia import images

        size = images.size_of(result.path)   # A5, I2: what reading the image costs, with or without Pillow
        if size:
            r.set("PX", f"{size[0]}x{size[1]}")
            r.set("TOKENS_EST", images.tokens_est(*size))
    for row in result.rows[:12]:
        bits = [str(row.get(k)) for k in ("title", "date", "place", "page", "snippet") if row.get(k)]
        if not bits:   # a register of a departmental archive (A4): what the next call needs
            bits = [f"{k}={row[k]}" for k in ("detail", "cote", "types", "from", "to", "view", "views", "viewer",
                                               "region") if row.get(k) is not None]
        r.data("row", f"{row.get('url') or row.get('id') or ''} | {' | '.join(bits)}"[:300])
    if result.text and not result.rows:
        r.data("text", result.text[:300].replace("\n", " "))
    if _views(result) and (getattr(getattr(ctx, "args", None), "agent", None) or "session") in MAIN_ROLES \
            and _first_advice(research):
        r.line(_("a register's views go to a reader subagent, one per register or act (its brief: "
                 "skills/research/reader.md): it finds the act, transcribes it and returns its lines; read a view "
                 "yourself only to check a doubt it marked"))
    return r


def _views(result):
    """True when an operation saved a view or listed registers or their views: the reader's work."""
    return bool(result.path) or any(row.get("viewer") or row.get("views") or (row.get("detail") and row.get("cote"))
                                    for row in result.rows)


def _first_advice(research):
    """T67: the reader's advice is given once a pass (it came with every run that saw views, read again at each
    turn); a marker in ``work/details/`` says it was. Without a research, there is no pass: always."""
    if research is None:
        return True
    path = os.path.join(research.work, "details", f"reader-advice-{current_pass(research)}")
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8"):
        pass
    return True


def _log(ctx, research, archive_id, operation, args, result, witness=None):
    """Every archive run goes to the search log; a zero inherits the archive's
    witness of the day, so it can support a negative."""
    if research is None:
        return None
    from probandia.cli.data_cmd import actor
    from probandia.indexes import FamilyIndexes
    from probandia.providers import searchlog
    from probandia.util.fs import parse_iso, utc_now

    outcome = "failed" if result.status != "ok" else ("positive" if result.n else "negative")
    e = searchlog.entry(f"{operation} {json.dumps(args, ensure_ascii=False, sort_keys=True)}", "archive",
                        archive_id, None, outcome, research.id,
                        current_pass(research), None if result.status != "ok" else result.n,
                        failure=result.failure)
    if witness is not None:
        e["witness"] = witness
    elif outcome == "negative":
        hours = ctx.config.get("witness.max_age_hours")
        for s in reversed(FamilyIndexes(ctx.project, research.family).items("searches")):
            w = s.get("witness")
            if s.get("engine") == archive_id and w and w.get("passed") and \
                    (utc_now() - parse_iso(w["ts"])).total_seconds() < hours * 3600:
                e["witness"] = w
                break
    searchlog.append(ctx.project, research.family, [e], actor(ctx), "archive run")
    return e


def stale(ctx, today=None):
    """``archive stale [--days N]`` (TRUST4-T2): the archives of the catalogue whose ``state.checked`` is
    older than N days (catalogues.max_age_days), or missing."""
    import datetime

    from probandia.archives.finder import load_catalogue
    from probandia.providers import catalogue

    days = ctx.args.days if ctx.args.days is not None else catalogue.max_age_days(ctx.config)
    today = today or datetime.date.today()
    rows = []
    for archive_id, entry in sorted(load_catalogue(ctx.project).items()):
        checked = str((entry.get("state") or {}).get("checked") or "") or None
        try:
            age = (today - datetime.date.fromisoformat(checked)).days if checked else None
        except ValueError:
            age = None
        if age is None or age > days:
            rows.append({"archive": archive_id, "name": entry.get("name"), "checked": checked, "age_days": age})
    r = Result("WARN" if rows else "OK", {"DAYS": days, "STALE": len(rows)})
    for x in rows:
        r.data("stale", f"{x['archive']} checked={x['checked'] or 'never'}")
    r.table("stale", rows, ["archive", "name", "checked", "age_days"])
    r.view = "archive-stale"
    return r


def _witness(ctx, module, context, research):
    from probandia import archives
    from probandia.util.fs import iso, utc_now

    w = archives.witness_of(module, ctx.project)
    if not w:
        raise UsageError(_("{archive} declares no witness").format(archive=module.ARCHIVE))
    result = archives.run(module, w["operation"], dict(w.get("args") or {}), context)
    passed = archives.witness_passed(w, result)
    record = {"operation": f"{module.ARCHIVE}.{w['operation']}", "args": w.get("args") or {},
              "expected": json.dumps(w.get("expect") or {}), "passed": passed, "ts": iso(utc_now())}
    entry = _log(ctx, research, module.ARCHIVE, "witness", w.get("args") or {}, result, record)
    r = Result("OK" if passed else "FAIL", {"ARCHIVE": module.ARCHIVE, "WITNESS": w["operation"],
                                            "PASSED": passed, "COUNT": result.n},
               exit_code=None if passed else EXIT_FAIL)
    if not passed:
        r.set("REASON", "witness-failed")
        r.line(result.failure or _("the witness did not find what it expects"))
    if entry:
        r.set("SEARCH", entry["id"])
    return r


def _entry_row(ctx, archive_id, entry, enabled):
    access = entry.get("access") or {}
    cov = entry.get("coverage") or {}
    connector = access.get("connector")
    key = CONNECTOR_KEYS.get(connector) if connector else None
    years = cov.get("years") or [None, None]
    return {"archive": archive_id, "name": entry.get("name", archive_id), "nature": entry.get("nature"),
            "connector": bool(connector), "mode": access.get("mode"),
            "enabled": (archive_id in enabled) if connector else None,
            "key": key, "key_set": bool(key and ctx.environ.get(key)),
            "third_party": access.get("third_party") != "forbidden",
            "places": list(cov.get("places") or []), "absent": list(cov.get("absent") or []),
            "types": list(cov.get("types") or []), "from": years[0], "to": years[1],
            "checked": str((entry.get("state") or {}).get("checked") or "")}


def _list(ctx):
    """Every archive of the catalogue: its connector, key, whether it is enabled,
    and whether third-party readers are forbidden on its hosts."""
    from probandia.archives.finder import load_catalogue

    cat = load_catalogue(ctx.project)
    enabled = list(ctx.config.get("archives.enabled") or [])
    departmental = [a for a in cat if DEPARTMENTAL.match(a) and not (cat[a].get("access") or {}).get("connector")]
    if not ctx.args.all:   # A2: the 101 departmental archives in one line, each one with --all
        cat = {a: e for a, e in cat.items() if a not in departmental}
    rows = [_entry_row(ctx, a, e, enabled) for a, e in cat.items()]
    r = Result("OK", {"ARCHIVES": len(rows), "CONNECTORS": sum(1 for x in rows if x["connector"]),
                      "ENABLED": sum(1 for x in rows if x["enabled"])})
    if departmental and not ctx.args.all:
        r.set("DEPARTMENTAL", len(departmental))
        r.line(_("{n} departmental archives of France (ad01 to ad976), read in a browser: archive coverage "
                 "<department> gives one, archive list --all every one").format(n=len(departmental)))
    for x in rows:
        state = ("enabled" if x["enabled"] else "disabled") if x["connector"] else x["mode"]
        r.data("archive", f"{x['archive']} {x['nature']} {state} key={x['key'] or '-'}"
                          f"{' third-party=forbidden' if not x['third_party'] else ''}")
    r.table("archives", rows, ["archive", "name", "nature", "connector", "mode", "enabled", "key", "key_set",
                               "third_party", "checked"])
    r.view = "archive-list"
    return r


def _coverage(ctx):
    """The archives that cover a place, and a span of years."""
    from probandia.archives.coverage import covers, places_in
    from probandia.archives.finder import load_catalogue

    if not ctx.args.target:
        raise UsageError(_("archive coverage needs a place, such as Morbihan"))
    import re

    codes = places_in(ctx.args.target)
    if not codes:
        code = ctx.args.target.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}(-[0-9A-Z]{1,3})?", code):   # an ISO 3166 code, such as FR-56
            from probandia.archives.coverage import DEPARTMENTS
            from probandia.suggest import lines

            return Result("WARN", {"PLACE": ctx.args.target, "ARCHIVES": 0},
                          [_("place not recognised: name a French department, a country, or an ISO code such as "
                             "FR-56")] + lines(ctx.args.target, list(DEPARTMENTS.values())))
        codes = [code, code.split("-")[0]] if "-" in code else [code]
    cat = load_catalogue(ctx.project)
    enabled = list(ctx.config.get("archives.enabled") or [])
    lo, hi = ctx.args.year_from, ctx.args.year_to
    rows = []
    for a, e in cat.items():
        x = _entry_row(ctx, a, e, enabled)
        precise = [c for c in codes if "-" in c] or codes
        if not covers(x["places"], precise) or covers(x["absent"], precise):
            continue
        if (lo is not None and x["to"] is not None and x["to"] < lo) or \
                (hi is not None and x["from"] is not None and x["from"] > hi):
            continue
        rows.append(x)
    order = {"image": 0, "index": 1, "press": 2, "catalogue": 3, "tree": 4}
    rows.sort(key=lambda x: (order.get(x["nature"], 9), x["archive"]))
    r = Result("OK" if rows else "WARN", {"PLACE": ctx.args.target, "CODES": ",".join(codes),
                                          "FROM": lo if lo is not None else "", "TO": hi if hi is not None else "",
                                          "ARCHIVES": len(rows)})
    for x in rows:
        r.data("archive", f"{x['archive']} {x['nature']} {x['from']}-{x['to']} "
                          f"{'connector' if x['connector'] else x['mode']} {','.join(x['types'])}")
    if not rows:
        r.line(_("no archive of the catalogue covers this place and period"))
    r.table("archives", rows, ["archive", "name", "nature", "from", "to", "types", "connector", "mode"])
    r.view = "archive-coverage"
    return r
