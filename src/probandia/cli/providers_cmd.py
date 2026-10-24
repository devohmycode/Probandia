"""``providers``: the free-tier catalogue, read and switched on or off (cli.md 5.4).

- ``providers``: every entry, its role, index family, free tier, state and age;
- ``providers show <id>``: one entry in full;
- ``providers stale [--days N]``: the entries checked more than N days ago (90);
- ``providers enable|disable <id>``: ``disable`` adds the id to
  ``providers.disabled``; ``enable`` takes it out, and adds it to
  ``providers.enabled`` only when the default list leaves it off (Bing). In the
  project's ``probandia.toml`` (``--user``: the user's file), as ``config set``.
  The full list is never frozen: a provider added to the catalogue later is on.
"""
import datetime

from probandia.cli.output import Result
from probandia.errors import NotInProject, UsageError
from probandia.i18n import _

ACTIONS = ("list", "show", "stale", "enable", "disable")


def configure(p, common):
    p.add_argument("action", nargs="?", default="list", choices=ACTIONS)
    p.add_argument("provider", nargs="?", help=_("a provider id, such as serper"))
    p.add_argument("--days", type=int, help=_("stale: older than this many days (catalogues.max_age_days, 90)"))
    p.add_argument("--user", action="store_true", help=_("enable, disable: the user's file, not the project's"))


def _today():
    return datetime.date.today()


def _config(ctx):
    from probandia import config as cfgmod

    try:
        ctx.project
        return ctx.config
    except NotInProject:
        return cfgmod.load(None, ctx.environ, args=ctx.arg_settings)


def _provider(ctx, cat):
    p = ctx.args.provider
    if not p:
        raise UsageError(_("providers {action} needs a provider id").format(action=ctx.args.action))
    if p not in cat:
        from probandia.suggest import lines

        raise UsageError(_("unknown provider {provider}").format(provider=p), lines=lines(p, cat))
    return p


def _row(pid, e, config, environ, today):
    from probandia.providers import catalogue

    free = e.get("free") or {}
    checked = e.get("checked")
    age = (today - checked).days if isinstance(checked, datetime.date) else None
    return {"provider": pid, "name": e.get("name", pid), "kind": e.get("kind"), "family": e.get("family"),
            "unit": e.get("unit"), "amount": free.get("amount"), "period": free.get("period"),
            "state": catalogue.why_unusable(e, config, environ) or "ready",
            "card_required": bool(e.get("card_required")), "content_reuse": bool(e.get("content_reuse")),
            "key": catalogue.key_env(e), "checked": checked.isoformat() if hasattr(checked, "isoformat") else None,
            "age_days": age}


def run(ctx):
    return {"list": _list, "show": _show, "stale": _stale, "enable": _switch, "disable": _switch}[ctx.args.action](ctx)


def _list(ctx):
    from probandia.providers import catalogue

    cat, config, today = catalogue.load(), _config(ctx), _today()
    rows = [_row(pid, e, config, ctx.environ, today) for pid, e in cat.items()]
    r = Result("OK", {"PROVIDERS": len(rows), "READY": sum(1 for x in rows if x["state"] == "ready")})
    for x in rows:
        r.data("provider", f"{x['provider']} {x['kind']} family={x['family'] or '-'} {x['state']} "
                           f"free={x['amount']} {x['unit']}/{x['period']} checked={x['checked']}")
    r.table("providers", rows)
    r.view = "providers"
    return r


def _show(ctx):
    from probandia.providers import catalogue

    cat = catalogue.load()
    p = _provider(ctx, cat)
    e = cat[p]
    x = _row(p, e, _config(ctx), ctx.environ, _today())
    free = e.get("free") or {}
    r = Result("OK", {"PROVIDER": p, "NAME": x["name"], "KIND": x["kind"], "FAMILY": x["family"] or "none",
                      "STATE": x["state"], "UNIT": x["unit"], "FREE": f"{free.get('amount')} {x['unit']}",
                      "PERIOD": free.get("period"), "RESET": free.get("reset") or "",
                      "CARD_REQUIRED": x["card_required"], "CONTENT_REUSE": x["content_reuse"],
                      "KEY": x["key"] or "none", "CHECKED": x["checked"] or "never",
                      "AGE_DAYS": "" if x["age_days"] is None else x["age_days"]})
    for op, cost in (e.get("costs") or {}).items():
        r.data("cost", f"{op} {cost}")
    for key in ("source_url", "terms_url"):
        if e.get(key):
            r.data(key.split("_")[0], e[key])
    if e.get("notes"):
        r.line(str(e["notes"]))
    r.view, r.extra = "provider", {"costs": dict(e.get("costs") or {}), "source": e.get("source_url"),
                                   "terms": e.get("terms_url")}
    return r


def _stale(ctx):
    from probandia.providers import catalogue

    cat, today, config = catalogue.load(), _today(), _config(ctx)
    days = ctx.args.days if ctx.args.days is not None else catalogue.max_age_days(config)
    old = [_row(pid, e, config, ctx.environ, today) for pid, e in cat.items()]
    old = [x for x in old if x["age_days"] is None or x["age_days"] > days]
    r = Result("WARN" if old else "OK", {"DAYS": days, "STALE": len(old)})
    for x in old:
        r.data("stale", f"{x['provider']} checked={x['checked'] or 'never'} source={cat[x['provider']].get('source_url', '-')}")
    r.table("stale", [dict(x, source=cat[x["provider"]].get("source_url")) for x in old],
            ["provider", "name", "checked", "age_days", "source"])
    r.view = "providers-stale"
    return r


def _switch(ctx):
    """providers.disabled (and providers.enabled for an entry off by default), as
    config set writes them: the project's file, or --user."""
    from probandia import config as cfgmod
    from probandia.cli.config_cmd import USER_HEADER
    from probandia.config import tomlfile
    from probandia.providers import catalogue

    cat = catalogue.load()
    p = _provider(ctx, cat)
    project = None if ctx.args.user else ctx.project
    config = _config(ctx)
    on = ctx.args.action == "enable"
    paths = cfgmod.layer_paths(project, ctx.environ)
    layer = "user" if ctx.args.user else "project"
    path = paths[layer]
    header = USER_HEADER if layer == "user" else None
    disabled = list(config.get("providers.disabled") or [])
    enabled = list(config.get("providers.enabled") or [])
    was_on = catalogue.why_unusable(cat[p], config, ctx.environ) != "not-enabled"
    changed = was_on != on
    if on:
        if p in disabled:
            rest = [q for q in disabled if q != p]
            if rest:
                tomlfile.set_value(path, "providers.disabled", rest, header=header)
            else:
                tomlfile.unset_value(path, "providers.disabled")
        if p not in enabled:   # off by default (Bing): the enabled list must name it
            tomlfile.set_value(path, "providers.enabled", [q for q in cat if q in enabled or q == p], header=header)
    elif p not in disabled:
        tomlfile.set_value(path, "providers.disabled", [q for q in cat if q in disabled or q == p], header=header)
    after = cfgmod.load(None if ctx.args.user else project, ctx.environ, strict=False)
    r = Result("OK" if changed else "WARN", {"PROVIDER": p, "ENABLED": on, "LAYER": layer, "FILE": path,
                                             "STATE": catalogue.why_unusable(cat[p], after, ctx.environ) or "ready"})
    if not changed:
        r.line(_("{provider} was already {state}").format(provider=p, state=_("enabled") if on else _("disabled")))
    origin = after.origin("providers.disabled" if not on else "providers.enabled")
    if changed and origin.layer not in (layer, "default"):
        r.status = "WARN"
        r.line(_("{layer} ({source}) overrides this value").format(layer=origin.layer, source=origin.source))
    if on:
        e = cat[p]
        if e.get("card_required") and not after.get("providers.allow_card_required"):
            r.status = "WARN"
            r.line(_("its free tier asks for a credit card: it stays off until providers.allow_card_required "
                     "is true; Probandia never pays"))
        if e.get("content_reuse") and not after.get("providers.allow_content_reuse"):
            r.status = "WARN"
            r.line(_("it may reuse the content sent to it: it stays off until providers.allow_content_reuse is true"))
        if p == "serpapi_bing":
            r.status = "WARN"
            r.line(_("on 2 October 2026, Bing answered 4 exact genealogical queries out of 5 with unrelated pages"))
        if not catalogue.has_key(e, ctx.environ) and catalogue.key_env(e):
            r.line(_("no key yet: probandia keys set {var}").format(var=catalogue.key_env(e)))
    return r
