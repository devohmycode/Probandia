"""``usage`` (``probandia -u``): the free tiers account by account (cli.md § 4).

``quota show`` stays the agents' command, unchanged. ``usage`` reads the ledger
and the catalogue only; ``--sync`` first reads the balances the providers
report, at no cost.
"""
import csv
import datetime
import io

from probandia.cli.output import Result
from probandia.errors import EXIT_STOP, NotInProject, UsageError
from probandia.i18n import N_, _
from probandia.ledger import LOW   # the gauge's threshold, as QUOTA_LOW= and --alert's default

ROLE_CHOICES = ("search", "answer", "read", "last-resort", "model")
SYNC_STALE = datetime.timedelta(days=1)


def _now():
    """The time of the screen; tests set it."""
    return datetime.datetime.now(datetime.timezone.utc)


def usage_args(p, common):
    from probandia.cli.human import watch_option

    p.add_argument("provider", nargs="?", help=_("one provider: its full record"))
    watch_option(p)
    p.add_argument("--sync", action="store_true", help=_("read the balances from the accounts first, at no cost"))
    p.add_argument("--all", action="store_true", help=_("every account, the ones out of service included"))
    p.add_argument("--ready", action="store_true", help=_("only the accounts ready to use"))
    p.add_argument("--role", choices=ROLE_CHOICES, help=_("only the accounts of one role"))
    p.add_argument("--families", action="store_true", help=_("the index families a web negative can count on"))
    p.add_argument("--csv", action="store_true", help=_("the accounts as CSV"))
    p.add_argument("--md", action="store_true", help=_("the accounts as a Markdown table"))
    p.add_argument("--forecast", action="store_true",
                   help=_("the day each quota runs out, at the pace of the last 7 days"))
    p.add_argument("--short", action="store_true",
                   help=_("one line for a status bar: the ready accounts with the least left"))
    p.add_argument("--alert", nargs="?", const="20%", metavar="<n>%",
                   help=_("exit 4 when a usable account has less than this percentage left, 20 by default"))


def _sources(ctx):
    """(project or None, ledger, config)."""
    from probandia import config as config_mod
    from probandia.ledger import Ledger
    from probandia.providers import catalogue

    try:
        project = ctx.project
    except NotInProject:
        project = None
    if project:
        return project, Ledger(project, catalogue.load(), clock=_now, environ=ctx.environ,
                               config=ctx.config), ctx.config
    # outside a project: the user's counter, with the keys of the user's .env
    return None, Ledger(None, catalogue.load(), clock=_now, environ=ctx.environ),         config_mod.load(None, ctx.environ, args=ctx.arg_settings)


def _row(a):
    pays = a["pays"]
    return {"account": a["account"], "name": a["name"], "section": a["section"], "state": a["state"],
            "unit": a["unit"], "amount": a["amount"], "used": a["used"], "reserve": a["reserve"],
            "left": a["left"], "searches": pays.get("search", ""), "pages": pays.get("read", ""),
            "renews": a["renewal"]["kind"],
            "renews_at": a["renewal"]["at"].date().isoformat() if a["renewal"].get("at") else "",
            "source": a["source"], "synced_at": a["synced_at"] or "", "entries": ",".join(a["entries"])}


def _count(v):
    return "unlimited" if v is None else (round(v, 4) if isinstance(v, float) else v)


def remedy(cat, p, why):
    """What brings an entry back: a setting, or the key it lacks."""
    from probandia.providers.accounts import REMEDY

    return REMEDY.get(why) or (cat[p].get("auth") or {}).get("env") or why


def _raw(rows, markdown):
    columns = list(rows[0]) if rows else []
    if markdown:
        lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        lines += ["| " + " | ".join("" if r[c] is None else str(r[c]) for c in columns) + " |" for r in rows]
        return "\n".join(lines) + "\n"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def usage(ctx):
    from probandia.providers import accounts as acc
    from probandia.providers import catalogue

    cat = catalogue.load()
    project, ledger, cfg = _sources(ctx)
    reserve = cfg.get("budget.reserve_percent")
    if ctx.args.provider and ctx.args.provider not in cat:
        from probandia.suggest import lines

        raise UsageError(_("unknown provider {provider}").format(provider=ctx.args.provider),
                         lines=lines(ctx.args.provider, cat))
    synced = []
    if ctx.args.sync:
        if project is None:
            raise UsageError(_("--sync reads the keys of a project: run it inside one"))
        from probandia.cli.search_cmd import sync_providers

        ctx._config = cfg
        synced = sync_providers(ctx, catalogue.usable(cfg, ctx.environ), cat, ledger)
    if ctx.args.alert is not None:
        return _alert(ctx, ledger, cfg, reserve)
    if ctx.args.short:
        return short(cat, ledger, cfg, ctx.environ)
    if ctx.args.forecast:
        return _forecast(ctx, cat, ledger, cfg, reserve)
    found = acc.accounts(cat, ledger, cfg, ctx.environ, reserve)
    if ctx.args.provider:
        return _one(ctx, cat, ledger, found, reserve)
    usable_fams, missing = acc.families(cat, ledger, cfg, ctx.environ, reserve)
    needed = cfg.get("web.negative_families")
    if ctx.args.families:
        return _families(usable_fams, missing, needed, cat)

    shown = found
    if ctx.args.role:
        shown = [a for a in shown if a["section"] == ctx.args.role or ctx.args.role in a["roles"]]
    if ctx.args.ready:
        shown = [a for a in shown if a["state"] == "ready"]
    rows = [_row(a) for a in shown]
    ready = [a for a in found if a["state"] == "ready"]
    r = Result("OK", {"COUNTER": "user", "ACCOUNTS": len(shown), "READY": len(ready),
                      "RESERVE_PERCENT": reserve, "FAMILIES": ",".join(usable_fams), "FAMILIES_NEEDED": needed})
    if len(usable_fams) < needed:
        r.status = "WARN"
    for a in shown:
        parts = [a["account"], a["state"], f"left={_count(a['left'])}"]
        parts += [f"{word}={_count(a['pays'][op])}" for op, word in (("search", "searches"), ("read", "pages"))
                  if op in a["pays"]]
        parts.append(f"renews={_row(a)['renews_at'] or a['renewal']['kind']}")
        r.data("account", " ".join(parts))
    r.table("accounts", rows)
    out = [{"entry": p, "name": cat[p].get("name", p), "reason": why,
            "remedy": remedy(cat, p, why)}
           for a in found for p, why in a["out"].items()]
    r.table("out_of_service", out)
    for line in _advice(ctx, project, cat, found, missing, cfg, synced, ledger):
        r.line(line)
    if ctx.args.csv or ctx.args.md:
        r.raw = _raw(rows, ctx.args.md)
    r.view = "usage"
    r.extra = {"accounts": shown if (ctx.args.all or ctx.args.role or ctx.args.ready) else found,
               "show_out": not ctx.args.ready and not ctx.args.all, "all": ctx.args.all, "families": usable_fams, "missing": missing,
               "needed": needed, "project": project, "synced": synced}
    return r


SHORT_ACCOUNTS = 3


def short(cat, ledger, cfg, environ):
    """``usage --short`` (cli.md 5.2.10): one line for a status bar, never the network."""
    from probandia import board
    from probandia.providers import accounts as acc

    shown = board.lowest(acc.accounts(cat, ledger, cfg, environ, cfg.get("budget.reserve_percent")))[:SHORT_ACCOUNTS]
    r = Result("OK", {"ACCOUNTS": len(shown)})
    r.raw = " · ".join(board.account_text(a) for a in shown) + "\n"
    return r.table("accounts", [{"account": a["account"], "name": a["name"], "left": a["left"], "unit": a["unit"]}
                                for a in shown])


def _threshold(text):
    """``20%`` or ``20``: a share of 0 to 100 %."""
    try:
        n = float(str(text).strip().rstrip("%").strip())
    except ValueError:
        n = -1
    if not 0 <= n <= 100:
        raise UsageError(_("--alert takes a percentage from 0 to 100, such as 20%"))
    return n


def _alert(ctx, ledger, cfg, reserve):
    """T62: ``usage --alert 20%``, for a script or a scheduled task: code 4 when a usable
    account has less than the share left, 0 otherwise."""
    from probandia.cli.search_cmd import quota_low
    from probandia.providers import catalogue

    n = _threshold(ctx.args.alert)
    low = ledger.low(catalogue.usable(cfg, ctx.environ), reserve, n / 100)
    values = {"THRESHOLD": f"{n:g}%"}
    if not low:
        return Result("OK", values)
    r = Result.stop("quota-low", values=dict(values, QUOTA_LOW=quota_low(low)))
    r.exit_code = EXIT_STOP
    for p, pct in low:
        r.data("low", f"{p} {pct}% left")
    r.table("low", [{"account": p, "percent_left": pct} for p, pct in low])
    return r


def _forecast(ctx, cat, ledger, cfg, reserve):
    """T63: ``usage --forecast``, the day each usable quota runs out at the pace of the
    last 7 days (``Ledger.forecast``), soonest first."""
    from probandia.ledger import FORECAST_DAYS
    from probandia.providers import catalogue

    rows = []
    for pool in dict.fromkeys(ledger.pool(p) for p in catalogue.usable(cfg, ctx.environ)):
        f = ledger.forecast(pool, reserve)
        if f is None:
            continue
        rows.append({"account": pool, "name": cat[pool].get("name", pool), "unit": cat[pool].get("unit"),
                     "left": _count(max(0, f["left"])), "per_day": round(f["rate"], 4 if f["rate"] < 1 else 1),
                     "verdict": f["verdict"],
                     "date": f["date"].date().isoformat() if f["date"] else None})
    order = {"spent": 0, "out": 1, "renews": 2, "expires": 2, "idle": 3}
    rows.sort(key=lambda r: (order[r["verdict"]], r["date"] or "", r["account"]))
    r = Result("OK", {"DAYS": FORECAST_DAYS, "ACCOUNTS": len(rows)})
    soon = [row for row in rows if row["verdict"] in ("spent", "out")]
    if soon:
        r.set("SOONEST", f"{soon[0]['account']}:{soon[0]['date'] or 'now'}")
    for row in rows:
        when = f" {row['date']}" if row["date"] else ""
        r.data("forecast", f"{row['account']} {row['verdict']}{when} left={row['left']:g} per_day={row['per_day']:g}")
    r.table("forecast", rows)
    r.view = "usage-forecast"
    return r


def render_forecast(result, style):
    from probandia.cli import human as h
    from probandia.i18n import formats

    now = _now()
    rows = result.tables["forecast"]["rows"]
    out = [style.bold(_("When the free quotas run out")) + " · " + _("at the pace of the last {n} days").format(
        n=result.values["DAYS"]), style.dim(formats.local_time(now) + " · " + _("the reserve is kept"))]
    if not rows:
        return "\n".join(out + ["", _("no usable account with a counted quota")]) + "\n"
    wn = min(30, max(len(r["name"]) for r in rows))
    def amount(row, key):
        return formats.money(row[key]) if row["unit"] == "dollar" else formats.number(row[key])

    shown = [(amount(r, "left"), amount(r, "per_day")) for r in rows]
    wl = max([len(left) for left, _d in shown] + [len(_("left"))])
    wr = max([len(day) for _l, day in shown] + [len(_("a day"))])
    out += ["", style.dim(f"   {'':{wn}}  {_('left'):>{wl}}  {_('a day'):>{wr}}  {_('runs out')}")]
    words = {"spent": _("used up"), "renews": _("not before it starts again, {date}"),
             "expires": _("not before it expires, {date}"), "idle": _("no use in these days"),
             "out": _("on {date}")}
    for row, (left, per_day) in zip(rows, shown):
        status = {"spent": "FAIL", "out": "WARN"}.get(row["verdict"], "OK")
        date = row["date"] and datetime.date.fromisoformat(row["date"])
        when = words[row["verdict"]].format(date=formats.long_date(date.isoformat()) if date else "")
        out.append(f" {style.paint(style.symbol(status), h.COLORS[status])} {h.cut(row['name'], wn, style):{wn}}  "
                   f"{left:>{wl}}  {per_day:>{wr}}  {when}")
    return "\n".join(out) + "\n"


def _one(ctx, cat, ledger, found, reserve):
    p = ctx.args.provider
    pool = ledger.pool(p)
    a = next(x for x in found if x["account"] == pool)
    entry = cat[p]
    r = Result("OK", {"PROVIDER": p, "NAME": entry.get("name", p), "ACCOUNT": pool, "STATE": a["state"],
                      "UNIT": a["unit"], "AMOUNT": a["amount"], "USED": a["used"], "RESERVE": a["reserve"],
                      "LEFT": "unlimited" if a["left"] is None else a["left"], "PERIOD": a["period"],
                      "RENEWS": _row(a)["renews_at"] or a["renewal"]["kind"], "SOURCE": a["source"],
                      "BALANCE": a["balance"], "KEY": a["key"] or "none"})
    if a["out"].get(p):
        r.set("OUT", a["out"][p])
    for op, n in a["pays"].items():
        r.data("pays", f"{op} {'unlimited' if n is None else n}")
    for op, cost in (entry.get("costs") or {}).items():
        r.data("cost", f"{op} {cost}")
    for key in ("terms_url", "source_url"):
        if entry.get(key):
            r.data(key.split("_")[0], entry[key])
    recent = [e for e in ledger.entries() if e.get("provider") in a["entries"] and e.get("source") != "sync"][-5:]
    for e in recent:
        r.data("used", f"{e['ts']} {e['provider']} {e['operation']} {e['units']}")
    return r


def _families(usable, missing, needed, cat):
    r = Result("OK" if len(usable) >= needed else "WARN",
               {"FAMILIES": ",".join(usable), "USABLE": len(usable), "NEEDED": needed})
    for fam, entries in missing.items():
        r.data("missing", f"{fam} " + ", ".join(f"{p} ({why}: {remedy(cat, p, why)})" for p, why in entries))
    return r


def _advice(ctx, project, cat, found, missing, cfg, synced, ledger):
    """What the screen suggests (cli.md § 4.5)."""
    from probandia.doctor import catalogue_ages

    lines = []
    for a in found:
        n = ledger.projects_sharing(a["account"]) if a["state"] == "ready" else 0
        if n >= 2:
            lines.append(_("{name}: one key for {n} projects, one count for all").format(name=a["name"], n=n))
    for fam, entries in missing.items():
        for p, why in entries:
            if why == "no-key" and (cat[p].get("auth") or {}).get("env"):
                lines.append(_("a key for {name} ({var}) would add the index family {family}").format(
                    name=cat[p].get("name", p), var=cat[p]["auth"]["env"], family=fam))
    blind = [a["name"] for a in found if a["state"] == "ready" and a["balance"] in ("none", "response")
             and a["amount"] is not None]
    if blind:
        lines.append(_("{names}: no balance readable from the provider, local count only").format(
            names=", ".join(blind)))
    ages = catalogue_ages() or []
    from probandia.providers import catalogue as providers

    days = providers.max_age_days(cfg)
    old = providers.stale(ages, days)
    if old:
        lines.append(_("catalogue entries older than {days} days: {names}").format(
            days=days, names=", ".join(old)))
    if project:
        lines += _open_pass(ctx, project, cfg)
        now = _now()
        readable = [a for a in found if a["state"] == "ready" and a["balance"] == "endpoint"]
        stale = [a for a in readable if not a["synced_at"] or
                 now - datetime.datetime.fromisoformat(a["synced_at"].replace("Z", "+00:00")) > SYNC_STALE]
        if stale and not synced:
            lines.append(_("probandia -u --sync reads the balances from the accounts, at no cost"))
    return lines


def _open_pass(ctx, project, cfg):
    """The open pass of the newest research, with its native searches."""
    from probandia import events
    from probandia.budget import native_budget
    from probandia.harness import detect
    from probandia.lifecycle import pass_state
    from probandia.research import all_researches

    for res in sorted(all_researches(project), key=lambda x: (x.meta() or {}).get("created", ""), reverse=True):
        last, open_ = pass_state(events.read(res.events_path))
        if open_:
            b = native_budget(project, res, cfg, ctx.environ, detect(ctx.args.harness, ctx.environ)[0])
            return [_("open pass: {research}, pass {n}, native searches {used}/{max}").format(
                research=res.id, n=last, used=b["used"], max=b["per_pass"])]
    return []


# The readable screen (cli.md § 4.2)

SECTION_TITLES = {"search": N_("WEB SEARCH"), "answer": N_("ANSWERS WITH SOURCES"), "read": N_("READING PAGES"),
                  "last-resort": N_("LAST RESORT · no anti-bot option, never on an archive portal"),
                  "model": N_("MODELS")}
OUT_LABELS = {"no-key": N_("no key"), "card-required": N_("card required"),
              "content-reuse": N_("reuses the content"), "not-enabled": N_("disabled")}


def _compact(n):
    from probandia.i18n import formats

    return formats.number(n / 1e6, 1) + " M" if n >= 1e6 else formats.number(round(n))


def _units(a):
    from probandia.i18n import formats

    if a["left"] is None:
        return _("unlimited")
    left, top = max(0, a["left"]), a.get("ceiling", a["amount"])
    if top is None:
        return formats.number(round(left))
    if a["unit"] == "dollar":
        return f"{formats.money(left)} / {formats.money(top)}"
    if a["unit"] == "token":
        return f"{_compact(left)} / {_compact(top)} " + _("tokens")
    return f"{formats.number(round(left))} / {formats.number(top)}"


def _pays(a):
    from probandia.i18n import formats

    parts = []
    for op, word, endless in (("search", _("{n} searches"), _("unlimited searches")),
                              ("read", _("{n} pages"), _("unlimited pages"))):
        if op in a["pays"]:
            n = a["pays"][op]
            parts.append(endless if n is None else word.format(n=formats.number(n)))
    return _(" or ").join(parts)


def _renews(a, now):
    from probandia.i18n import formats

    r = a["renewal"]
    if r["kind"] == "reset":
        return formats.relative(r["at"], now)
    if r["kind"] == "expires":
        return _("expires {when}").format(when=formats.relative(r["at"], now))
    if r["kind"] == "first-use":
        return _("{n} months after the first use").format(n=r["months"])
    return _("one-off tier")


def render_usage(result, style):
    from probandia.cli import human as h
    from probandia.i18n import formats
    from probandia.providers.accounts import ROLES

    x, v = result.extra, result.values
    now = _now()
    head = _("Free quotas") + " · " + _("counted per key, across your projects")
    synced = [a["synced_at"] for a in x["accounts"] if a["synced_at"]]
    if synced:
        last = datetime.datetime.fromisoformat(max(synced).replace("Z", "+00:00"))
        head += " · " + _("balances read {when}").format(when=formats.relative(last, now))
    out = [style.bold(head), style.dim(formats.local_time(now) + " · " + _(
        "reserve kept: {p} % of each quota (budget.reserve_percent)").format(p=v["RESERVE_PERCENT"]))]
    shown = [a for a in x["accounts"] if x["all"] or a["state"] in ("ready", "exhausted", "expired")]
    rows = [(a, _units(a), _pays(a), _renews(a, now)) for a in shown]
    wn = min(30, max([len(a["name"]) for a, *_r in rows] + [10]))
    wu = max([len(u) for _a, u, *_r in rows] + [5])
    wp = max([len(p) for _a, _u, p, _r in rows] + [5])
    out += ["", style.dim(f"   {'':{wn}}  {_('left'):16}  {_('units'):{wu}}  {_('pays for'):{wp}}  {_('starts again')}")]
    for role in ROLES:
        in_section = [row for row in rows if row[0]["section"] == role]
        if not in_section:
            continue
        out.append(style.bold(_(SECTION_TITLES[role])))
        for a, units, pays, renews in in_section:
            if a["state"] != "ready":
                sym, color = style.symbol("FAIL"), h.COLORS["FAIL"]
            elif a["fraction"] is not None and a["fraction"] < LOW:
                sym, color = style.symbol("WARN"), h.COLORS["WARN"]
            else:
                sym, color = style.symbol("OK"), h.COLORS["OK"]
            gauge = h.bar(a["fraction"], style) if a["fraction"] is not None else " " * 16
            out.append(f" {style.paint(sym, color)} {h.cut(a['name'], wn, style):{wn}}  {gauge}  "
                       f"{units:{wu}}  {pays:{wp}}  {renews}".rstrip())
            if a["out"] and a["state"] == "ready":
                for p, why in a["out"].items():
                    out.append(style.dim(f"     └ {p}: {_(OUT_LABELS.get(why, why))}"))
    out_rows = result.tables.get("out_of_service", {}).get("rows", [])
    # entries of a ready account show under it; the others are listed here
    off = [r for r in out_rows if not any(r["entry"] in a["entries"] and a["state"] == "ready" for a in shown)]
    if off and x["show_out"]:
        out += ["", style.bold(_("Out of service"))]
        for reason in OUT_LABELS:
            names = [r["name"] for r in off if r["reason"] == reason]
            if names:
                fix = "" if reason == "no-key" else f" ({next(r['remedy'] for r in off if r['reason'] == reason)})"
                out.append(f"  {_(OUT_LABELS[reason])}: {', '.join(names)}{fix}")
    n, needed = len(x["families"]), x["needed"]
    verdict = (_("fewer than the {k} required") if n < needed else _("just the minimum required") if n == needed
               else _("more than the {k} required")).format(k=needed)
    out += ["", _("Web negatives: {n} index families usable ({list}), {verdict}").format(
        n=n, list=", ".join(x["families"]) or "—", verdict=verdict)]
    for line in result.lines:
        if h.DATA_LINE.match(line):   # account=… lines are the contract's
            continue
        if line.startswith("probandia "):
            out.append(style.paint("→ ", "1") + line)
        else:
            out += [style.paint(style.symbol("WARN"), h.COLORS["WARN"]) + " " + line]
    return "\n".join(out) + "\n"


def _register():
    from probandia.cli import human

    human.VIEWS["usage"] = render_usage
    human.VIEWS["usage-forecast"] = render_forecast


_register()
