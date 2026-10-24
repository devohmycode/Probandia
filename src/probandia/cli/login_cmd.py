"""``login check|confirm|skip <archive>`` and ``browser login <archive>`` (optimize.md § 3).

An agent that drives the browser itself (Claude in Chrome, Playwright MCP…)
says through ``login`` where the session stands: ``check`` reads it, ``confirm``
records that the user signed in and the agent saw the "logged in" marker,
``skip`` leaves the source. ``browser login`` opens a visible window of the
engine's own browser on the archive's profile (``.probandia/browser/<host>``),
for the user to sign in; the ``browser`` step of the reading ladder then reuses
that profile. Nothing here ever reads, types or keeps a password, a cookie or a
token: only a state and a time.
"""
import os

from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _


def login_args(p, common):
    p.add_argument("action", choices=("check", "confirm", "skip"))
    p.add_argument("archive", help=_("the archive's id, such as familysearch"))
    p.add_argument("--research", help=_("research id or unique prefix"))


def browser_args(p, common):
    p.add_argument("action", choices=("login",))
    p.add_argument("archive", help=_("the archive's id, such as familysearch"))


def _entry(ctx):
    from probandia.archives.finder import load_catalogue

    cat = load_catalogue(ctx.project)
    entry = cat.get(ctx.args.archive)
    if entry is None:
        from probandia.suggest import lines

        raise UsageError(_("no archive {id} in the catalogue").format(id=ctx.args.archive),
                         lines=lines(ctx.args.archive, cat))
    return entry


def login(ctx):
    from probandia import logins
    from probandia.cli.reading_cmd import _research_and_pass

    entry = _entry(ctx)
    block = entry.get("login") or {}
    archive = ctx.args.archive
    if ctx.args.action == "confirm":
        record = logins.set_state(ctx.project, archive, "confirmed", research=_research_and_pass(ctx)[0])
    elif ctx.args.action == "skip":
        record = logins.set_state(ctx.project, archive, "skipped", research=_research_and_pass(ctx)[0])
    else:
        record = logins.state(ctx.project, archive) or {}
    valid = logins.valid(record, block.get("session_hours"))
    r = Result("OK", {"ARCHIVE": archive, "REQUIRED": bool(block.get("required")),
                      "STATE": record.get("state") or "none", "VALID": valid,
                      "LOGIN_URL": block.get("url") or "", "CONFIRMED": record.get("confirmed") or ""})
    if record.get("expired"):
        r.set("EXPIRED", record["expired"])
    if block.get("logged_in"):
        r.data("logged_in_marker", " | ".join(block["logged_in"]))
    return r


def open_visible(url, profile_dir, wait):
    """A visible window of the local browser on ``profile_dir``, open on ``url``
    until ``wait()`` returns (the user's Enter); the profile keeps the session."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(profile_dir, headless=False)
        try:
            page = context.new_page()
            page.goto(url)
            wait()
        finally:
            context.close()


def browser(ctx):
    """``browser login <archive>``: the user signs in, in a visible window of the
    engine's browser, on the profile the ``browser`` step reads with."""
    from probandia import logins
    from probandia.reading.browser import browser_state, install_command

    entry = _entry(ctx)
    block = entry.get("login") or {}
    hosts = (entry.get("access") or {}).get("hosts") or []
    if not hosts:
        raise UsageError(_("{id} has no host to open").format(id=ctx.args.archive))
    if browser_state(ctx.environ) != "ready":
        raise UsageError(_("the local browser is not installed: {command}").format(command=install_command()))
    if not getattr(ctx, "asks", False):
        raise UsageError(_("browser login opens a window for you to sign in: run it at your terminal"))
    profile = os.path.join(ctx.project, ".probandia", "browser", hosts[0].lower())
    os.makedirs(profile, exist_ok=True)
    url = block.get("url") or f"https://{hosts[0]}/"

    def wait():
        from probandia.cli import asking

        text = _("Sign in to {archive} in the window, then press Enter here.").format(
            archive=entry.get("name", ctx.args.archive))
        if asking.given() is not None:   # the terminal application: its question, never its hidden input
            if not asking.given()("confirm", text):
                raise asking.Interrupted()
            return
        ctx.stdout.write(text + " ")
        ctx.stdout.flush()
        ctx.stdin.readline()

    open_visible(url, profile, wait)
    record = logins.set_state(ctx.project, ctx.args.archive, "confirmed")
    return Result("OK", {"ARCHIVE": ctx.args.archive, "STATE": record["state"], "PROFILE": profile})
