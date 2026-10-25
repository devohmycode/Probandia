"""``read <url>``: the reading ladder, and the passages that answer a question."""
import os

from probandia.cli.output import Result
from probandia.errors import EXIT_FAIL, UsageError
from probandia.i18n import _



def read_args(p, common):
    p.add_argument("url", help=_("the page; one robots.txt disallows is not fetched by the engine, but goes to "
                                 "the readers"))
    p.add_argument("--question", help=_("the question the passages must answer"))
    p.add_argument("--fresh", action="store_true", help=_("bypass the cache"))
    p.add_argument("--max-step", type=int, choices=range(0, 8), metavar="<0-7>",
                   help=_("the last step of the ladder to try"))
    p.add_argument("--research", help=_("research id: details and short-lived cache go to its work/"))
    p.add_argument("--interactive", action="store_true",
                   help=_("a skill is running: the user's browser may be asked for"))
    p.add_argument("--login", choices=("connected", "skip", "stop"),
                   help=_("the user's answer to login_required: signed in, leave this source, or stop"))
    p.add_argument("--quote", type=int, metavar="<n>",
                   help=_("the excerpt of passage n, ready for the fact that cites the page"))
    only = p.add_mutually_exclusive_group()
    only.add_argument("--links", metavar="<pattern>",
                      help=_("only the links whose text or address holds the pattern"))
    only.add_argument("--grep", metavar="<pattern>",
                      help=_("only the lines that hold the pattern, with one line of context"))
    only.add_argument("--select", metavar="<selector>",
                      help=_("only one block of the page: a tag, .class, #id or tag.class"))
    # what the providers' MCP servers offered (T229-T231); --links filters the map
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--map", action="store_true",
                      help=_("the map of the site: its sitemap, else the page's links, a third party last; "
                             "robots.txt obeyed"))
    mode.add_argument("--crawl", type=int, metavar="<n>",
                      help=_("read n pages of the site from this one, following --links; robots.txt obeyed; "
                             "a third party last"))
    mode.add_argument("--extract", metavar="<instruction>",
                      help=_("the page turned into JSON after the instruction, by a third party (Firecrawl, "
                             "ScrapeGraph): when --select and --grep are not enough"))
    p.add_argument("--schema", metavar="<file.json>", help=_("with --extract: the JSON schema of the answer"))


# T229-T231: the options each mode refuses
MODE_REFUSES = {"map": ("grep", "select"), "crawl": ("grep", "select"),
                "extract": ("grep", "select", "links", "question")}
MAP_LIMIT = 200          # the URLs asked of a third party
SHOWN = 25               # the URLs or passages the contract shows


def _mode(ctx):
    for name, refused in MODE_REFUSES.items():
        value = getattr(ctx.args, name, None)
        if value is not None and value is not False:
            bad = [k for k in refused if getattr(ctx.args, k, None) is not None]
            if bad:
                raise UsageError(_("--{mode} does not go with --{option}").format(mode=name, option=bad[0]),
                                 values={"REASON": "options"})
            if name == "crawl" and value < 1:
                raise UsageError(_("--crawl needs a number of pages, 1 or more"), values={"REASON": "options"})
            if name != "extract" and getattr(ctx.args, "schema", None):
                break
            return name
    if getattr(ctx.args, "schema", None):
        raise UsageError(_("--schema goes with --extract only"), values={"REASON": "options"})
    return None


def _tried(steps):
    return " ".join(f"{s}:{v}" for s, v in steps)


EXTRACT_SHOWN = 10   # the first items of an extraction the contract shows
EXTRACT_CHARS = 200  # of each


def _items(found):
    """The records of an extraction: the list itself, the one list an object holds,
    else the object alone."""
    if isinstance(found, list):
        return found
    if isinstance(found, dict):
        lists = [v for v in found.values() if isinstance(v, list)]
        if len(lists) == 1 and len(found) == 1:
            return lists[0]
    return [found]


def _extract(ctx, reader, work):
    """T231: a page turned into JSON after an instruction, by Firecrawl then
    ScrapeGraph. Never on a local URL nor on a host forbidden to third parties
    (``read --select`` reads it instead), and never to a provider that may reuse
    what it is sent when the instruction names a person presumed living."""
    import json

    from probandia.cli.search_exec import _living_names
    from probandia.errors import ProbandiaError
    from probandia.reading import thirdparty
    from probandia.reading.cache import make_key, ttl_for
    from probandia.research import find_research

    url, instruction = ctx.args.url, ctx.args.extract
    schema = None
    if ctx.args.schema:
        try:
            with open(ctx.args.schema, encoding="utf-8") as fh:
                schema = json.load(fh)
        except (OSError, ValueError) as err:
            raise UsageError(_("cannot read the schema {path}: {error}").format(path=ctx.args.schema, error=err),
                             values={"REASON": "schema"}) from None
    try:
        research = find_research(ctx.project, ctx.args.research, ctx.environ)
    except ProbandiaError:   # no research open: the project's default family
        research = None
    living = _living_names(ctx, research, instruction)
    key = make_key("extract", url, {"instruction": " ".join(instruction.split()), "schema": schema})
    payload = reader.cache.get("extract", key, ctx.args.fresh)
    tried, units, cache = [], 0.0, "hit" if payload else "miss"
    if payload:
        found, source = payload["json"], payload["source"]
    else:
        out = thirdparty.call(reader, "extract", url, ("firecrawl", "scrapegraph"),
                              lambda ad: ad.extract(url, instruction, schema), reuse=not living)
        tried = out.tried
        if out.refused:
            r = Result("FAIL", {"URL": url, "REASON": out.refused, "FAILURE": out.refused,
                                "NEXT": f"read {url} --select <selector>"}, exit_code=EXIT_FAIL)
            r.set("TRIED", _tried(tried))
            r.line(_("this page never goes to a third party: read it with --select or --grep instead"))
            return r
        if not out.ok:
            if out.quota and not out.error:
                r = _stopped(ctx, out, "extract", {"URL": url})
                alt = r.values.get("ALTERNATIVE")
                if living and alt and (reader.meter.ledger.catalogue if reader.meter else {}).get(alt, {}) \
                        .get("content_reuse"):
                    del r.values["ALTERNATIVE"]   # the one left may not hear of a living person
            else:
                why = "provider-error" if out.error else ("living-person-name" if living else "no-provider")
                r = Result("FAIL", {"URL": url, "REASON": why, "FAILURE": why}, exit_code=EXIT_FAIL)
                r.line(str(out.error) if out.error else
                       _("no extraction provider can be used: set FIRECRAWL_API_KEY or SGAI_API_KEY"))
            if tried:
                r.set("TRIED", _tried(tried))
            if living:
                r.line(_("the instruction holds the name of a person presumed living; providers that reuse "
                         "content were not asked"))
            return r
        found, source, units = out.value, out.provider, out.units
        reader.cache.put("extract", key, {"json": found, "source": source}, "ok", ttl_for("http", ctx.config),
                         units=units)
    path = _details(ctx, work, "extract", json.dumps(found, ensure_ascii=False, indent=2) + "\n", ext="json")
    items = _items(found)
    r = Result("OK", {"URL": url, "SOURCE": source, "CACHE": cache, "EXTRACT": path, "ITEMS": len(items)},
               details=path)
    if units:
        r.set("UNITS", round(units, 4))
    if tried:
        r.set("TRIED", _tried(tried))
    for item in items[:EXTRACT_SHOWN]:
        text = json.dumps(item, ensure_ascii=False)
        r.data("item", text if len(text) <= EXTRACT_CHARS else text[:EXTRACT_CHARS - 1] + "…")
    if len(items) > EXTRACT_SHOWN:
        r.line(_("{n} more items in EXTRACT").format(n=len(items) - EXTRACT_SHOWN))
    if living:
        r.line(_("the instruction holds the name of a person presumed living; providers that reuse "
                 "content were not asked"))
    r.table("items", [i if isinstance(i, dict) else {"value": i} for i in items])
    return r


def _crawl(ctx, reader, work):
    """T230: the engine follows the links itself, page by page, by the free steps of
    the ladder; a third party (Firecrawl, then Tavily) only when the start page came
    back empty or blocked, never on a local URL, on a host forbidden to third parties, nor
    for a page ``robots.txt`` disallows (T66): the crawl obeys it for every page it follows."""
    from probandia.reading import crawl as C
    from probandia.reading import thirdparty
    from probandia.reading.cache import make_key, ttl_for

    url, asked = ctx.args.url, ctx.args.crawl
    ceiling = ctx.config.get("read.crawl_max_pages")
    n = min(asked, ceiling)
    notes = []
    if asked > ceiling:
        notes.append(_("{asked} pages asked, {n} read at most (read.crawl_max_pages)").format(asked=asked, n=n))
    done = C.crawl(reader, url, n, ctx.args.links, ctx.args.fresh)
    pages, source, units, tried, cache = done.pages, "http", 0.0, [], "miss"
    tried.append(("crawl", f"{len(pages)}-pages"))
    if not pages and C.needs_help(done.start):
        tried.insert(0, ("http", done.start.status))
        key = make_key("crawl", url, {"n": n, "links": ctx.args.links or ""})
        payload = reader.cache.get("crawl", key, ctx.args.fresh)
        if payload:
            pages, source, cache = [tuple(p) for p in payload["pages"]], payload["source"], "hit"
        else:
            include = C.include_pattern(ctx.args.links)
            out = thirdparty.call(reader, "crawl", url, ("firecrawl", "tavily"),
                                  lambda ad: ad.crawl(url, limit=n, include=include),
                                  units=lambda ad: ad.cost("crawl", n))
            tried += out.tried
            if out.ok:
                pages = [(p.final_url, p.title, p.text) for p in out.value if p.status == 200 and p.text.strip()]
                source, units = out.provider, out.units
                if pages:
                    reader.cache.put("crawl", key, {"pages": [list(p) for p in pages], "source": source}, "ok",
                                     ttl_for("http", ctx.config), units=units)
            elif out.quota and not out.error:
                r = _stopped(ctx, out, "crawl", {"URL": url})
                r.set("TRIED", _tried(tried))
                return r
    values = {"URL": url, "SOURCE": source, "CACHE": cache, "PAGES": len(pages), "ASKED": asked}
    if done.skipped:
        values["SKIPPED"] = len(done.skipped)
    if not pages:
        status = done.start.status if done.start is not None else "empty"
        r = Result("FAIL", dict(values, REASON=status, FAILURE=status), exit_code=EXIT_FAIL)
        r.set("TRIED", _tried(tried))
        for note in notes:
            r.line(note)
        r.line(_("not consulted ({status}): no negative can be recorded from this page").format(status=status))
        return r
    folder = _details(ctx, work, "crawl", "".join(
        f"<!-- {u} -->\n\n{text}\n\n---\n\n" for u, _t, text in pages), ext="md")
    found = C.passages(pages, ctx.args.question, ctx.config.get("reading.max_passages"),
                       ctx.config.get("reading.passage_chars"))
    r = Result("OK", dict(values, PASSAGES=len(found)), details=folder)
    if units:
        r.set("UNITS", round(units, 4))
    r.set("TRIED", _tried(tried))
    for note in notes:
        r.line(note)
    if ctx.args.question:
        for u, p in found[:SHOWN]:
            r.data("passage", f"{u} {p}")
        if not found:
            r.status = "WARN"
            r.line(_("no passage matches the question; the pages are in DETAILS"))
    else:
        for u, title, _text in pages[:SHOWN]:
            r.data("page", f"{u} {title}".strip())
    r.table("pages", [{"url": u, "title": t, "chars": len(text)} for u, t, text in pages])
    r.table("passages", [{"url": u, "passage": p} for u, p in found])
    return r


def _details(ctx, work, name, text, ext="txt"):
    """Writes ``text`` in the research's ``work/details/`` (else the project's) and
    returns its path relative to the project."""
    from probandia.util.fs import atomic_write_text
    from probandia.util.ids import ulid

    folder = os.path.join(work, "details") if work else os.path.join(ctx.project, ".probandia", "details")
    path = os.path.join(folder, f"{name}-{ulid()}.{ext}")
    atomic_write_text(path, text)
    return os.path.relpath(path, ctx.project).replace(os.sep, "/")


def _stopped(ctx, out, operation, values):
    """Every third party held back by its free quota: STATUS=STOP, code 4, nothing called."""
    from probandia.cli.search_cmd import stop_result

    return stop_result(ctx, out.quota[0], dict(values, FAILURE="quota"), operation=operation)


def _map(ctx, reader, work):
    """T229: the cache; the sitemap of the site; the links of the page, same host
    (read by the ladder's free steps only); a third party last, Firecrawl then
    Tavily, never on a local URL, on a host forbidden to third parties, nor for a page
    ``robots.txt`` disallows (T66)."""
    from probandia.reading import extract as E
    from probandia.reading import sitemap, thirdparty
    from probandia.reading.cache import make_key, ttl_for

    url = ctx.args.url
    key = make_key("map", url)
    payload = reader.cache.get("map", key, ctx.args.fresh)
    tried, units, cache, error = [], 0.0, "hit" if payload else "miss", None
    if payload:
        urls, source = payload["urls"], payload["source"]
    else:
        urls, _sitemaps = sitemap.site_map(reader.client, url)
        source = "sitemap"
        tried.append(("sitemap", "ok" if urls else "none"))
        if not urls:
            page = reader.read(url, fresh=ctx.args.fresh, max_step=3)   # cache, api, http, extract
            if page.ok and page.html:
                urls = []
                for _text, href in E.links(page.html, "", page.final_url or url):
                    href = href.split("#")[0]
                    if href.startswith("http") and sitemap.same_host(href, url) and href not in urls:
                        urls.append(href)
            source = "links"
            tried.append(("links", "ok" if urls else (page.status or "none")))
            if not urls and page.status == "robots":   # T66: a map obeys robots.txt, never a third party's
                tried.append(("third-party", "robots"))
        if not urls and ("third-party", "robots") not in tried:
            out = thirdparty.call(reader, "map", url, ("firecrawl", "tavily"),
                                  lambda ad: ad.map(url, limit=MAP_LIMIT),
                                  units=lambda ad: ad.cost("map", MAP_LIMIT))
            tried += out.tried
            if out.ok:
                urls, source, units = out.value, out.provider, out.units
            elif out.quota and not out.error:
                r = _stopped(ctx, out, "map", {"URL": url})
                r.set("TRIED", _tried(tried))
                return r
            error = out.error
        if urls:
            reader.cache.put("map", key, {"urls": urls, "source": source}, "ok", ttl_for("http", ctx.config),
                             units=units)
    shown = urls
    if ctx.args.links:
        want = ctx.args.links.casefold()
        shown = [u for u in urls if want in u.casefold()]
    values = {"URL": url, "SOURCE": source if urls else "none", "CACHE": cache, "URLS": len(urls)}
    if ctx.args.links:
        values["MATCHED"] = len(shown)
    if not urls:
        r = Result("FAIL", dict(values, REASON="no-map", FAILURE="no-map"), exit_code=EXIT_FAIL)
        if tried:
            r.set("TRIED", _tried(tried))
        r.line(_("no map: the site publishes no sitemap, the page gives no link, and no third party could map it"))
        if error:
            r.line(str(error))
        return r
    details = _details(ctx, work, "map", f"<!-- {url} ({source}) -->\n" + "\n".join(urls) + "\n")
    r = Result("OK", values, details=details)
    if units:
        r.set("UNITS", round(units, 4))
    if tried:
        r.set("TRIED", _tried(tried))
    for u in shown[:SHOWN]:
        r.data("url", u)
    if len(shown) > SHOWN:
        r.line(_("{n} more URLs: narrow them with --links, or open DETAILS").format(n=len(shown) - SHOWN))
    if not shown:
        r.status = "WARN"
        r.line(_("no URL matches; the whole map is in DETAILS"))
    r.table("urls", [{"url": u} for u in shown[:SHOWN]])
    return r


# token-economy D1: what --links, --grep and --select print at most, so the answer stays under 40 lines
FILTER_LINES = 25


def _filtered(r, result, args):
    """Replaces the passages by the links, lines or block asked for; the whole page stays in DETAILS."""
    from probandia.reading import extract as E

    if args.links is not None:
        found = E.links(result.html or result.text, args.links, result.final_url or args.url)
        r.set("LINKS", len(found))
        rows = [f"{text} {href}".strip() for text, href in found]
        key = "link"
    elif args.grep is not None:
        rows = E.grep(result.text, args.grep)
        r.set("LINES", len([x for x in rows if x != "…"]))
        key = "line"
    else:
        if not result.html:
            raise UsageError(_("--select needs the page's HTML; this step gave text only: use --grep"),
                             values={"REASON": "no-html"})
        try:
            block = E.select(result.html, args.select)
        except ValueError:
            raise UsageError(_("unknown selector {selector}: a tag, .class, #id or tag.class")
                             .format(selector=args.select)) from None
        rows = block.splitlines() if block else []
        r.set("LINES", len(rows))
        key = "line"
    for row in rows[:FILTER_LINES]:
        r.data(key, row)
    if len(rows) > FILTER_LINES:
        r.line(_("{n} more lines: narrow the pattern, or open DETAILS").format(n=len(rows) - FILTER_LINES))
    if not rows:
        r.status = "WARN"
        r.line(_("nothing matches; the full text is in DETAILS"))


def build_reader(ctx, work=None, transport=None):
    from probandia.paths import data_root
    from probandia.ledger import Ledger
    from probandia.providers import catalogue
    from probandia.providers.meter import Meter
    from probandia.reading import browser
    from probandia.reading.cache import Cache
    from probandia.reading.ladder import Reader, archive_hosts, forbidden_hosts, login_sites
    from probandia.util.http import Client, contact

    project = ctx.project
    state = os.path.join(project, ".probandia")
    client = Client(state, contact(ctx.environ, ctx.config), ctx.config, transport=transport)
    research, pass_no = _research_and_pass(ctx)
    meter = Meter(Ledger(project, catalogue.load(), environ=ctx.environ), ctx.config, ctx.environ, research, pass_no)
    return Reader(client, Cache(project, work), ctx.config, ctx.environ,
                  browser=browser.fetch if browser.available() else None,
                  forbidden=forbidden_hosts(project, data_root()),
                  interactive=ctx.args.interactive, state_dir=state, meter=meter,
                  portals=archive_hosts(project, data_root()), logins=login_sites(project, data_root()))


def _research_and_pass(ctx):
    """The research and the pass a read counts against: those of ``--research``,
    else of the open research; (None, None) when there is none."""
    from probandia.errors import ProbandiaError
    from probandia.lifecycle import current_pass
    from probandia.research import find_research

    try:
        research = find_research(ctx.project, ctx.args.research, ctx.environ)
    except ProbandiaError:
        return None, None
    return research.id, current_pass(research)


def _login_archive(ctx, project, block=None):
    """The archive id of the page: from the sign-in block, else from the catalogue."""
    if block and block.get("archive"):
        return block["archive"]
    from probandia.paths import data_root
    from probandia.reading.ladder import login_sites

    import urllib.parse

    host = (urllib.parse.urlsplit(ctx.args.url).hostname or "").lower()
    for h, b in login_sites(project, data_root()).items():
        if host == h or host.endswith("." + h):
            return b["archive"]
    return host or "unknown"


def _research_id(ctx, project):
    research, _pass = _research_and_pass(ctx)
    return research


def _login_required(ctx, project, result, tried):
    """A sign-in screen (D8): ask the user to sign in (QUESTION=login_required),
    or, with nobody to ask, leave the page to a manual task. Never a negative."""
    from probandia import logins, questions

    block = result.login or {}
    archive = _login_archive(ctx, project, block)
    before = logins.state(project, archive) or {}
    research = _research_id(ctx, project)
    if questions.headless(ctx.environ):
        logins.add_manual_task(project, research, archive, ctx.args.url)
        r = Result("FAIL", {"REASON": "login-required", "FAILURE": "login", "ARCHIVE": archive,
                            "URL": ctx.args.url}, exit_code=EXIT_FAIL)
        r.line(_("not consulted (login required): no negative can be recorded from this page; "
                 "it is listed among the manual tasks"))
        return r
    expired = before.get("state") == "confirmed"   # the session the user opened has ended: ask again
    logins.set_state(project, archive, "pending", ctx.args.url, research)
    login_url = block.get("url") or ctx.args.url
    r = Result.ask("login_required", _("{archive} needs you to sign in. Sign in, in the browser window, then "
                                       "say so here.").format(archive=archive),
                   ["connected", "skip", "stop"], "connected",
                   values={"ARCHIVE": archive, "LOGIN_URL": login_url, "URL": ctx.args.url})
    r.set("OPTION", "--login")
    # read uses the engine's own browser, whose cookies are its own: the user signs in there
    r.set("BROWSER_LOGIN", f"probandia browser login {archive}")
    if expired:
        r.set("EXPIRED", True)
    if tried:
        r.set("TRIED", tried)
    # T-08: Playwright is optional; an agent that drives the user's browser needs nothing more
    r.line(_("if you drive the user's own browser (Claude in Chrome, a browser MCP), open LOGIN_URL there, let the "
             "user sign in, run login confirm {archive} and read the page in that browser: nothing to install").format(
        archive=archive))
    r.line(_("read uses the engine's own browser, not the user's: ask the user to sign in with BROWSER_LOGIN at "
             "their terminal; wait for their answer, never sign in for them; then run the command again with "
             "--login connected, skip or stop"))
    return r


def _login_seen(ctx, project, reader):
    """``--login connected`` and the page read: the session is confirmed (a time, never an identifier)."""
    from probandia import logins

    block = reader.login_for(ctx.args.url) if hasattr(reader, "login_for") else None
    if block:
        logins.set_state(project, _login_archive(ctx, project, block), "confirmed", research=_research_id(ctx, project))


def _login_answer(ctx, project):
    """``--login skip``: the source is left, not consulted; ``--login stop``: the pass stops here."""
    from probandia import logins

    archive = _login_archive(ctx, project)
    logins.set_state(project, archive, "skipped", ctx.args.url, _research_id(ctx, project))
    if ctx.args.login == "stop":
        return Result.stop("login-stopped", values={"ARCHIVE": archive, "URL": ctx.args.url})
    r = Result("FAIL", {"REASON": "login-skipped", "FAILURE": "login", "ARCHIVE": archive, "URL": ctx.args.url},
               exit_code=EXIT_FAIL)
    r.line(_("not consulted (login required): no negative can be recorded from this page"))
    return r


def _browser_hint(r, result):
    """Says so when the local browser step could not start, with the command that
    installs it for the Python running the engine (the agents' one)."""
    if ("browser", "unavailable") in result.tried:
        from probandia.reading.browser import install_command

        r.line(_("the local browser could not start; to read such pages, install it: {command}").format(
            command=install_command()))


def _note_outcome(ctx, project, result):
    """T66: a page the whole ladder could not read is noted, with its status and the time, for the cache's
    lifetime, so that G-17 no longer sends the harness's fetch back to read; a page read forgets it. A
    sign-in screen or a question to the user is no failure of the ladder."""
    from probandia.reading.cache import forget_failure, note_failure, ttl_for

    if result.ok:
        forget_failure(project, ctx.args.url)
    elif result.status not in ("ask", "login") and ctx.args.max_step is None:
        note_failure(project, ctx.args.url, result.status, ttl_for("http", ctx.config))


def read(ctx, reader=None):
    import json

    from probandia import excerpt as X
    from probandia.reading.ladder import passages
    from probandia.research import find_research
    from probandia.util.fs import atomic_write_text
    from probandia.util.ids import ulid

    from probandia.cli import asking

    project = ctx.project
    if not asking.confirm(ctx, _("Read {url}? A reading service may use its free quota.").format(url=ctx.args.url)):
        return asking.declined({"URL": ctx.args.url})
    work = find_research(project, ctx.args.research).work if ctx.args.research else None
    if ctx.args.login in ("skip", "stop"):
        return _login_answer(ctx, project)
    mode = _mode(ctx)
    reader = reader or build_reader(ctx, work)
    if mode == "map":
        return _map(ctx, reader, work)
    if mode == "crawl":
        return _crawl(ctx, reader, work)
    if mode == "extract":
        return _extract(ctx, reader, work)
    # an answer "connected" reads again, fresh: the session is checked by reading
    result = reader.read(ctx.args.url, fresh=ctx.args.fresh or ctx.args.login == "connected",
                         max_step=ctx.args.max_step)
    _note_outcome(ctx, project, result)
    tried = " ".join(f"{step}:{status}" for step, status in result.tried)
    if result.status == "login":
        return _login_required(ctx, project, result, tried)
    if ctx.args.login == "connected":
        _login_seen(ctx, project, reader)

    if result.status == "ask":
        r = Result.ask("use_browser", "Open this page in your browser?", ["yes", "no"], "yes",
                       values={"URL": ctx.args.url, "STEP": 6})
        if tried:
            r.set("TRIED", tried)
        return r
    if result.status == "quota":
        from probandia.cli.search_cmd import stop_result

        r = stop_result(ctx, result.quota[0], {"URL": ctx.args.url, "FAILURE": "quota"}, operation="read")
        if tried:
            r.set("TRIED", tried)
        r.line(_("not consulted ({status}): no negative can be recorded from this page")
               .format(status="quota"))
        return r
    if not result.ok:
        r = Result("FAIL", {"REASON": result.status, "FAILURE": result.status, "URL": ctx.args.url},
                   exit_code=EXIT_FAIL)
        if tried:
            r.set("TRIED", tried)
        r.line(_("not consulted ({status}): no negative can be recorded from this page")
               .format(status=result.status))
        _browser_hint(r, result)
        return r

    folder = os.path.join(work, "details") if work else os.path.join(project, ".probandia", "details")
    path = os.path.join(folder, f"read-{ulid()}.md")
    atomic_write_text(path, f"<!-- {result.final_url} -->\n\n{result.text}\n")
    filtering = any(getattr(ctx.args, k, None) is not None for k in ("links", "grep", "select"))
    found = [] if filtering else passages(result.text, ctx.args.question, ctx.config.get("reading.max_passages"),
                                          ctx.config.get("reading.passage_chars"))
    r = Result("OK", {"URL": ctx.args.url, "STEP": result.step, "CACHE": result.cache,
                      "CHARS": len(result.text), "PASSAGES": len(found)},
               details=os.path.relpath(path, project).replace(os.sep, "/"))
    if result.final_url != ctx.args.url:
        r.set("FINAL_URL", result.final_url)
    if tried:
        r.set("TRIED", tried)
    for p in found:
        r.data("passage", p)
    # TRUST1-T3: where each passage is in the page, and its digest; --quote gives a fact's excerpt
    rows = []
    for n, p in enumerate(found, 1):
        at = X.offset_of(result.text, p)
        rows.append({"n": n, "offset": at, "length": len(X.normalise(p)), "sha256": X.digest(p)})
    r.table("passages", rows)
    if ctx.args.quote is not None:
        if not 1 <= ctx.args.quote <= len(rows) or rows[ctx.args.quote - 1]["offset"] < 0:
            raise UsageError(_("no passage {n}: the page gives {count}").format(n=ctx.args.quote, count=len(rows)),
                             values={"REASON": "no-passage"})
        row = rows[ctx.args.quote - 1]
        quoted = X.from_page(result.text, row["offset"], row["length"], url=result.final_url or ctx.args.url)
        r.set("DIGEST", quoted["sha256"])
        r.data("excerpt", json.dumps(quoted, ensure_ascii=False))
    if filtering:
        _filtered(r, result, ctx.args)
    elif ctx.args.question and not found:
        r.status = "WARN"
        r.line(_("no passage matches the question; the full text is in DETAILS"))
    _browser_hint(r, result)
    r.view = "read"
    r.extra = {"step_name": result.step, "extractor": result.extractor, "passages": found,
               "spent": [{"reader": n, "tier": t, "units": u} for n, t, u in result.spent]}
    return r

