"""``search``: provider searches, web negatives, and the logging of native searches."""
from probandia.cli.output import Result
from probandia.cli import search_cmd
from probandia.errors import EXIT_FAIL, UsageError
from probandia.i18n import _
from probandia.lifecycle import current_pass


def search_args(p, common):
    p.add_argument("query", nargs="?", help=_("the query; for --negative, the surname then the place"))
    p.add_argument("--engine", default="auto", help=_("a provider id, or auto"))
    p.add_argument("--negative", action="store_true", help=_("prove an absence across index families"))
    p.add_argument("--exact", action="store_true")
    p.add_argument("--site")
    p.add_argument("--filetype")
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--depth", choices=("standard", "advanced"), default="standard",
                   help=_("advanced: a deeper search, at a higher cost (Tavily, Exa, Parallel, Linkup)"))
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--research")
    p.add_argument("--pass", dest="pass_no", type=int)
    p.add_argument("--log-native", action="store_true", help=_("record a search the harness ran"))
    p.add_argument("--query", dest="query_option", help=_("the query of a native search"))
    p.add_argument("--results", type=int, help=_("number of results of a native search"))
    p.add_argument("--urls-file", help=_("the URLs a native search returned, one per line"))


def _research_or_none(ctx):
    from probandia.errors import ProbandiaError
    from probandia.research import find_research

    try:
        return find_research(ctx.project, ctx.args.research, ctx.environ)
    except ProbandiaError:
        return None


def _actor(ctx):
    from probandia.cli.data_cmd import actor

    return actor(ctx)


def _native_first(ctx, research):
    """The first salvo is free: while the harness's own web search has not run in the pass and may still
    run, the engine's search, which spends a provider's quota, waits. A negative needs the providers."""
    from probandia.budget import native_budget
    from probandia.harness import CAPABILITIES

    harness = _actor(ctx)["harness"]
    if research is None or ctx.args.negative or not ctx.config.get("search.native") \
            or not (CAPABILITIES.get(harness) or {}).get("web_search"):
        return None
    b = native_budget(ctx.project, research, ctx.config, ctx.environ, harness)
    if b["used"] or b["left"] <= 0:
        return None
    return Result("WARN", {"QUERY": ctx.args.query, "REASON": "native-first", "RESULTS": 0,
                           "NATIVE_PARALLEL": b["parallel"]},
                  [_("nothing searched: the first salvo is free; run the native web searches first, then search "
                     "again where they fall short")])


def search(ctx):
    from probandia.providers import searchlog

    research = _research_or_none(ctx)
    pass_no = ctx.args.pass_no if ctx.args.pass_no is not None else (
        current_pass(research) if research else None)

    if ctx.args.log_native:
        query = ctx.args.query_option or ctx.args.query
        if not query:
            raise UsageError(_("--log-native needs the query"))
        engine = ctx.args.engine if ctx.args.engine != "auto" else "native:" + _actor(ctx)["harness"]
        urls = []
        if ctx.args.urls_file:
            with open(ctx.args.urls_file, encoding="utf-8") as fh:
                urls = searchlog.urls_in_text(fh.read())
        count = ctx.args.results if ctx.args.results is not None else len(urls)
        if research is None:
            return Result("WARN", {"QUERY": query}, [_("no research in progress: nothing recorded")])
        from probandia.budget import native_budget
        from probandia.util.locks import session_id

        # an MCP server's search (mcp:<server>), logged by hand where no hook does it, is a provider call
        mcp = engine.startswith("mcp:")
        e = searchlog.entry(query, "provider" if mcp else "native", engine, "opaque",
                            "positive" if count else "negative", research.id, pass_no, count,
                            filters={"session": session_id(ctx.environ)})
        sid = searchlog.append(ctx.project, research.family, [e], _actor(ctx),
                               "MCP search" if mcp else "native search")[0]
        b = native_budget(ctx.project, research, ctx.config, ctx.environ, _actor(ctx)["harness"])
        r = Result("OK", {"SEARCH": sid, "FAMILY": "opaque", "RESULTS": count, "NATIVE_LEFT": b["left"]})
        if sid != e["id"]:   # T51: the hook logged it already
            r.line(_("this search was already logged (by the hook): counted once"))
        if mcp:
            return r
        if b["left"] <= 0:
            r.status = "WARN"
            r.set("REASON", "native-budget")
            r.line(_("the native search budget of this pass is used up: continue with the engine's search"))
        return r

    if not ctx.args.query:
        raise UsageError(_("give a query"))
    waiting = _native_first(ctx, research)
    if waiting:
        return waiting
    from probandia.cli import asking

    if ctx.asks:
        engines, usable = _engines(ctx, negative=ctx.args.negative)
        chosen = [p for p in engines if p in usable]
        if ctx.args.engine == "auto" and not ctx.args.negative:   # the one auto will ask: the first that fits
            ledger, reserve = search_cmd._ledger(ctx), ctx.config.get("budget.reserve_percent")
            chosen = [p for p in chosen if _fits(ledger, reserve, p, _operation(ctx))][:1]
        if chosen and not asking.confirm(ctx, _('Search "{query}"? It uses the free quotas: {costs}.').format(
                query=ctx.args.query, costs=asking.spend_question(ctx, chosen, _operation(ctx)))):
            return asking.declined({"QUERY": ctx.args.query})
    living = _living_names(ctx, research, ctx.args.query)
    if ctx.args.negative:
        r = _negative(ctx, research, pass_no)
    else:
        r = _search(ctx, research, pass_no, refuse_reuse=bool(living))
    if living:
        if r.status == "OK":
            r.status = "WARN"
        if "REASON" not in r.values or r.values["REASON"] == "provider-error":
            r.set("REASON", "living-person-name")
        r.line(_("the query holds the name of a person presumed living; providers that reuse "
                 "content were not asked"))
    return r


def _living_names(ctx, research, query):
    """Names of presumed-living persons of the family that the query holds."""
    from probandia.errors import ProbandiaError
    from probandia.indexes import FamilyIndexes
    from probandia.report.living import names_in_query
    from probandia.research import default_family

    try:
        family = research.family if research else default_family(ctx.project)
        persons = FamilyIndexes(ctx.project, family).items("persons")
    except (ProbandiaError, OSError):
        return []
    return names_in_query(query, persons, ctx.config.get("privacy.living_years"))


def _query(ctx, text, exact=None):
    """The query; its language is the global --lang, when given."""
    from probandia.providers.base import Query

    return Query(text=text, exact=ctx.args.exact if exact is None else exact, site=ctx.args.site,
                 filetype=ctx.args.filetype, lang=ctx.args.lang or None, date_from=ctx.args.date_from,
                 date_to=ctx.args.date_to, max=ctx.args.max, depth=getattr(ctx.args, "depth", "standard"))


def _operation(ctx):
    """What one search costs in the catalogue: ``search``, or ``search_advanced`` for --depth advanced."""
    return "search_advanced" if getattr(ctx.args, "depth", "standard") == "advanced" else "search"


class Run:
    """Calls to providers, with quota, cache and ledger."""

    def __init__(self, ctx, research, pass_no):
        from probandia.providers import catalogue
        from probandia.reading.cache import Cache

        self.ctx = ctx
        self.cat = catalogue.load()
        self.ledger = search_cmd._ledger(ctx)
        self.reserve = ctx.config.get("budget.reserve_percent")
        self.client = search_cmd._client(ctx)
        self.cache = Cache(ctx.project, research.work if research else None)
        self.research = research
        self.pass_no = pass_no

    def fits(self, provider):
        return _fits(self.ledger, self.reserve, provider, _operation(self.ctx))

    def call(self, provider, query):
        """(results, failure or None, units)."""
        from probandia.providers import adapters
        from probandia.providers.base import ProviderError
        from probandia.providers.base import Result as R
        from probandia.reading.cache import make_key, ttl_for

        entry = self.cat[provider]
        params = {"site": query.site, "from": query.date_from, "to": query.date_to, "max": query.max}
        if query.depth != "standard":   # the standard searches keep the keys they had
            params["depth"] = query.depth
        key = make_key(provider, query.compose(), params)
        cached = self.cache.get(provider, key, self.ctx.args.fresh)
        if cached is not None:
            return [R(**r) for r in cached["results"]], None, 0
        ad = adapters.make(provider, self.client, entry, self.ctx.environ)
        try:
            results, usage = ad.search(query)
        except ProviderError as err:
            if adapters.exhausted_status(provider, err.status, err.excerpt):
                self.ledger.mark_exhausted(provider, err.retry_after)
            return [], f"http-{err.status}" if err.status else "error", 0
        self.ledger.record(provider, "search", usage.units, "response",
                           self.research.id if self.research else None, self.pass_no)
        report_balance(self.ledger, provider, usage.reported)
        ttl = ttl_for(provider, self.ctx.config, entry.get("cache_ttl"))
        self.cache.put(provider, key, {"results": [r.__dict__ for r in results]}, "ok", ttl, by=provider,
                       units=usage.units)
        return results, None, usage.units


def _fits(ledger, reserve, provider, operation="search"):
    left = ledger.left(provider, reserve)
    return left is None or left >= ledger.cost(provider, operation)


def report_balance(ledger, provider, reported):
    """What an answer says is left goes to the ledger. Brave gives the month's count
    left; Marginalia what its shared key may still do today, and nothing is left at 0."""
    if reported.get("left") is not None:
        ledger.update_reported(provider, left=reported["left"])
    daily = reported.get("daily_left")
    if daily is not None:
        ledger.update_reported(provider, left=daily)
        if daily <= 0:
            ledger.mark_exhausted(provider)


def _engines(ctx, negative=False):
    from probandia.providers import catalogue

    cat = catalogue.load()
    usable = catalogue.usable(ctx.config, ctx.environ, "search") + [
        p for p in catalogue.usable(ctx.config, ctx.environ, "read") if p in ("jina", "firecrawl")]
    advanced = _operation(ctx) == "search_advanced"
    if advanced:   # only the providers that price and make a deeper search
        usable = [p for p in usable if catalogue.does(cat[p], "search_advanced")]
    if ctx.args.engine != "auto":
        engines = [e.strip() for e in ctx.args.engine.split(",")]
        for e in engines:
            if e not in cat:
                from probandia.suggest import lines

                raise UsageError(_("unknown provider {provider}").format(provider=e), lines=lines(e, cat))
            if advanced and not catalogue.does(cat[e], "search_advanced"):
                _refuse_advanced(cat, e)
        return engines, usable
    if negative and advanced:   # a negative asks the keyword indexes, none of which goes deeper
        _refuse_advanced(cat, "--negative")
    if negative:
        return [p for p in usable if cat[p].get("keyword")], usable
    # T61: every free provider of routing.general, in its order; _search asks the first whose quota pays
    route = [p for p in ctx.config.get("routing.general") if p in usable]
    return (route or usable), usable


def _refuse_advanced(cat, what):
    from probandia.providers import catalogue

    offer = ", ".join(cat[p].get("name", p) for p in cat if catalogue.does(cat[p], "search_advanced"))
    raise UsageError(_("--depth advanced is not offered by {provider}; it is offered by {providers}").format(
        provider=what, providers=offer), values={"REASON": "no-advanced-search"})


EXCERPT_CHARS = 160   # T66: what a result line shows of the provider's snippet


def _excerpt(merged):
    """`` — <the snippet>`` on one line, cut at ``EXCERPT_CHARS`` on a word; empty when the provider gave
    none or only the title again. Often enough to leave a page unread."""
    text = " ".join(str(merged.get("snippet") or "").split())
    if not text or text == " ".join(str(merged.get("title") or "").split()):
        return ""
    if len(text) > EXCERPT_CHARS:
        cut = text[:EXCERPT_CHARS - 1]
        text = (cut.rsplit(" ", 1)[0] if " " in cut[EXCERPT_CHARS // 2:] else cut).rstrip(" ,;:.") + "…"
    return " — " + text


def _search(ctx, research, pass_no, refuse_reuse=False):
    from probandia.providers import searchlog
    from probandia.providers.fusion import fuse

    run = Run(ctx, research, pass_no)
    engines, usable = _engines(ctx)
    if not engines:
        return Result("FAIL", {"REASON": "no-provider"},
                      [_("no provider can be used: set a key, or enable one")], exit_code=EXIT_FAIL)
    auto = ctx.args.engine == "auto"
    if auto and not any(run.fits(p) for p in engines):   # every free quota used up: stop before any call
        return search_cmd.stop_result(ctx, engines[0])
    lists, failures, units, entries, spent, exhausted, asked = {}, [], 0, [], [], [], []
    exhausted_now = False
    for p in engines:
        if auto and asked and not exhausted_now:
            break   # auto: one provider answers; the next only when this one turned out used up
        if p not in usable:
            failures.append((p, "unusable"))
            continue
        if refuse_reuse and run.cat[p].get("content_reuse"):
            failures.append((p, "living-person-name"))
            continue
        if not run.fits(p):
            if len(engines) == 1:
                return search_cmd.stop_result(ctx, p)
            if auto:
                exhausted.append(p)
            else:
                failures.append((p, "free-quota"))
            continue
        q = _query(ctx, ctx.args.query)
        results, failure, used = run.call(p, q)
        asked.append(p)
        exhausted_now = bool(auto and failure and run.ledger.exhausted(p))
        if exhausted_now:   # the provider said its quota is used up: the next free one is asked
            exhausted.append(p)
        units += used
        spent.append({"engine": p, "name": run.cat[p].get("name", p), "results": None if failure else len(results),
                      "failure": failure, "units": used, "unit": run.cat[p].get("unit")})
        if failure and not exhausted_now:
            failures.append((p, failure))
        elif not failure:
            lists[p] = results
        if research:
            # nothing found is not a negative: only search --negative proves an absence, with its witness
            outcome = "failed" if failure else ("positive" if results else "empty")
            entries.append(searchlog.entry(q.compose(), "provider", p, run.cat[p]["family"], outcome,
                                           research.id, pass_no, None if failure else len(results),
                                           failure=failure, units=used))
    if research and entries:
        searchlog.append(ctx.project, research.family, entries, _actor(ctx))
    merged = fuse(lists)[: ctx.args.max]
    if auto and exhausted and not lists and not failures:   # each one asked said it was used up
        return search_cmd.stop_result(ctx, exhausted[0], {"EXHAUSTED": ",".join(exhausted)})
    r = Result("OK" if lists else "FAIL",
               {"ENGINES": ",".join(asked if auto else engines), "RESULTS": len(merged), "UNITS": f"{units:g}"},
               exit_code=None if lists else EXIT_FAIL)
    if exhausted:   # T61: the free quotas auto went past
        r.set("EXHAUSTED", ",".join(exhausted))
    if not lists:
        r.set("REASON", "provider-error")
    if entries:
        r.set("SEARCH", entries[0]["id"])
    for m in merged:
        r.data("result", f"{m['url']} [{'+'.join(m['providers'])}] {m['title']}{_excerpt(m)}")
    for p, why in failures:
        r.data("failed", f"{p} {why}")
    if failures and lists:
        r.status = "WARN"
    r.table("results", [{"title": m["title"], "url": m["url"], "engines": "+".join(m["providers"]),
                         "snippet": " ".join(str(m.get("snippet") or "").split())} for m in merged])
    r.table("engines", spent + [{"engine": p, "name": run.cat[p].get("name", p), "results": None,
                                 "failure": why, "units": 0, "unit": None}
                                for p, why in failures + [(p, "free-quota") for p in exhausted]
                                if not any(x["engine"] == p for x in spent)])
    r.view = "search"
    return r


def _negative(ctx, research, pass_no):
    from probandia.lang.variants import surname_forms
    from probandia.providers import searchlog
    from probandia.providers.fusion import NegativeCheck

    words = ctx.args.query.split()
    name, place = words[0], " ".join(words[1:])
    attested = {}
    if research:
        from probandia.indexes import FamilyIndexes
        attested = FamilyIndexes(ctx.project, research.family).load("variants").get("surnames", {})
    forms = [name] + [f for f, kind, _d in surname_forms(name, attested) if kind == "attested"][:3]
    forms += [f for f, _k, _d in surname_forms(name)][:2]
    forms = list(dict.fromkeys(forms))
    places = [place] if place else []
    run = Run(ctx, research, pass_no)
    engines, usable = _engines(ctx, negative=True)
    chosen, families = [], set()
    for p in engines:  # one engine per keyword family, in catalogue order
        fam = run.cat[p]["family"]
        if p in usable and run.cat[p].get("keyword") and fam not in families:
            chosen.append(p)
            families.add(fam)
    check = NegativeCheck(ctx.config.get("web.negative_families"))
    calls = 0

    def ask(p):
        nonlocal calls
        for form in forms:
            # PRD criterion 3: the free quota is looked at before every call, not once for the whole wave;
            # a wave cut short is a failure of the negative (some spelling was not asked), never a proof
            if not run.fits(p):
                check.add(p, run.cat[p]["family"], True, failure="free-quota")
                return
            q = _query(ctx, f'"{form}" {place}'.strip(), exact=False)
            results, failure, _u = run.call(p, q)
            calls += 1
            check.add(p, run.cat[p]["family"], True, results, failure, forms, places)
            if failure or p in check.unrelated:
                break

    for p in chosen:
        ask(p)
    # An engine that answered beside the query leaves its family uncounted: the
    # engines of the families still missing take over, one per family.
    for p in engines:
        if len(check.families) >= check.required or check.failures:
            break
        fam = run.cat[p]["family"]
        if (p in usable and p not in chosen and run.cat[p].get("keyword") and fam not in check.families
                and not any(run.cat[c]["family"] == fam and c not in check.unrelated for c in chosen)):
            chosen.append(p)
            ask(p)
    result = check.result
    if research:
        window = None
        if ctx.args.date_from and ctx.args.date_to:
            window = {"from": int(ctx.args.date_from[:4]), "to": int(ctx.args.date_to[:4]),
                      "places": places}
        e = searchlog.entry(ctx.args.query, "provider", "+".join(chosen),
                            ",".join(sorted(check.families)) or None, result, research.id, pass_no,
                            len(check.hits), variants=forms, window=window,
                            # an unrelated engine not counted is no failure of a negative that holds
                            failure=("; ".join(check.reasons()) or None) if result == "failed" else None,
                            proves="result" if result == "negative" else None)
        searchlog.append(ctx.project, research.family, [e], _actor(ctx), "negative search")
    r = Result("OK" if result == "negative" else "WARN",
               {"NEGATIVE": result, "FAMILIES": ",".join(sorted(check.families)),
                "ENGINES": ",".join(chosen), "VARIANTS": ",".join(forms), "CALLS": calls})
    for why in check.reasons():
        r.data("reason", why)
    for engine, hit in check.hits[:10]:
        r.data("hit", f"{hit.url} [{engine}] {hit.title}")
    return r
