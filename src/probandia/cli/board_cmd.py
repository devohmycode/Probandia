"""``probandia`` alone: the welcome screen (cli.md § 6.6, decision D-11).

Readable output only. In the contract, ``probandia`` without a command stays a
usage error (code 2), as agents and scripts expect.
"""
from probandia.cli.output import Result


def _ledger(project, cat, environ):
    from probandia.ledger import Ledger

    return Ledger(project, cat, environ=environ)


def welcome(ctx):
    from probandia import __version__, board
    from probandia import config as cfgmod
    from probandia.errors import NotInProject
    from probandia.providers import catalogue

    try:
        project = ctx.project
        config = ctx.config
    except NotInProject:
        project = None
        config = cfgmod.load(None, ctx.environ, args=ctx.arg_settings)
    cat = catalogue.load()
    ledger = _ledger(project, cat, ctx.environ)
    b = board.board(project, config, ctx.environ, ledger, cat)
    r = Result("WARN" if b["alerts"] else "OK",
               {"VERSION": __version__, "PROJECT": project or "none", "FAMILIES": len(b["families"]),
                "RESEARCHES": len(b["researches"]), "ALERTS": len(b["alerts"])})
    r.view, r.extra = "board", b
    return r


# board (T116, cli.md § 7.2): the same view, for the status line, watch and the mod

SHOWN_RESEARCHES = 5   # the newest; the rest is counted, so the answer stays under 4 096 bytes


def board_args(p, common):
    from probandia.i18n import _

    p.add_argument("research", nargs="?", help=_("the research in focus (default: the latest active one)"))


def board_cmd(ctx):
    from probandia import board
    from probandia.cli.data_cmd import actor
    from probandia.errors import NotInProject
    from probandia.research import find_research

    r = welcome(ctx)
    b = r.extra
    focus = []
    try:
        project = ctx.project
    except NotInProject:
        project = None
    if project and (ctx.args.research or b["researches"]):
        research = find_research(project, ctx.args.research or b["researches"][0]["research"], ctx.environ)
        focus = [board.focus(project, research, ctx.config, ctx.environ, actor(ctx)["harness"])]
        r.set("RESEARCH", research.id)
    r.table("project", [{"families": b["families"], "counted_projects": b["counted_projects"]}])   # its path: PROJECT=
    r.table("research", focus)
    r.table("researches", b["researches"][:SHOWN_RESEARCHES])
    for name in ("accounts", "alerts", "next"):
        r.table(name, b[name])
    return r




# statusline (T146, cli.md 5.15.1): the board in one line, for Claude Code's status bar. Claude Code runs it
# at each change of the conversation: the line is kept in .probandia/statusline.json, and given again while
# the files it is read from are unchanged, for STATUSLINE_TTL seconds at most (the user's counter, settings
# and keys are not in its stamp)

STATUSLINE_CACHE = ".probandia/statusline.json"
STATUSLINE_TTL = 30


def statusline_args(p, common):
    pass


def _claude_code(text, cwd):
    """(cwd, session) from the JSON object Claude Code sends on stdin (``workspace.current_dir``, ``cwd``,
    ``session_id``)."""
    import json

    try:
        payload = json.loads(text or "{}")
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    return workspace.get("current_dir") or payload.get("cwd") or cwd, payload.get("session_id")


def _stamp(project):
    """Date and size of each file the line is read from, in the project."""
    import os

    names = ["probandia.toml", ".probandia/ledger.jsonl"]
    families = os.path.join(project, "families")
    for family in sorted(os.listdir(families)) if os.path.isdir(families) else []:
        names.append(f"families/{family}/index/searches.yaml")
        researches = os.path.join(families, family, "research")
        for rid in sorted(os.listdir(researches)) if os.path.isdir(researches) else []:
            names += [f"families/{family}/research/{rid}/events.jsonl", f"families/{family}/research/{rid}/research.yaml"]
    out = []
    for name in names:
        try:
            st = os.stat(os.path.join(project, name))
            out.append([name, st.st_mtime_ns, st.st_size])
        except OSError:
            out.append([name, None, None])
    return out


def cached_line(text, environ, cwd):
    """The line without the engine, before argparse: empty outside a project, the kept line when its files
    have not changed; None when it must be read again."""
    import json
    import os
    import time

    from probandia.errors import ProbandiaError
    from probandia.project import find_project

    cwd, _session = _claude_code(text, cwd)
    try:
        project = find_project(None, environ, cwd)
    except ProbandiaError:
        return ""
    try:
        with open(os.path.join(project, STATUSLINE_CACHE), encoding="utf-8") as fh:
            kept = json.load(fh)
        if 0 <= time.time() - kept["written"] < STATUSLINE_TTL and kept["stamp"] == _stamp(project):
            return kept["line"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def statusline(ctx):
    """``Probandia · marchand · pass 2 open · web 3/40 · SerpApi 199``, from the files only; outside a
    project, an empty line."""
    import os
    import time

    from probandia import board, config, events
    from probandia.errors import ProbandiaError
    from probandia.i18n import _
    from probandia.lifecycle import pass_state
    from probandia.project import find_project
    from probandia.research import find_research
    from probandia.util.fs import atomic_write_json

    try:
        text = ctx.stdin.read() if ctx.stdin is not None and not ctx.stdin.isatty() else ""
    except (OSError, ValueError, AttributeError):
        text = ""
    cwd, session = _claude_code(text, ctx.cwd)
    environ = ctx.environ
    if session and not environ.get("PROBANDIA_SESSION"):
        environ = dict(environ, PROBANDIA_SESSION=session)   # the session the hooks name
    r = Result("OK", {"LINE": ""})
    try:
        project = find_project(ctx.args.project, environ, cwd)
    except ProbandiaError:
        r.raw = "\n"
        return r.table("line", [], hidden=True)
    stamp = _stamp(project)   # before reading: a file changed meanwhile makes the next call read again
    cfg = config.load(project, environ, strict=False)
    parts, row = ["Probandia"], {"project": project}
    try:
        research = find_research(project, fallback=True)
    except ProbandiaError:
        research = None
    if research is not None:
        from probandia.budget import native_budget
        from probandia.harness import detect

        last, open_ = pass_state(events.read(research.events_path))
        native = native_budget(project, research, cfg, environ, detect(ctx.args.harness, environ)[0])
        parts += [research.family, (_("pass {n} open") if open_ else _("pass {n} ended")).format(n=last)
                  if last else _("no pass yet"), _("web {used}/{max}").format(used=native["used"], max=native["per_pass"])]
        row.update(research=research.id, family=research.family, open_pass=last if open_ else None,
                   passes=last, native_used=native["used"], native_per_pass=native["per_pass"])
    from probandia.providers import accounts, catalogue

    cat = catalogue.load()
    found = accounts.accounts(cat, _ledger(project, cat, environ), cfg, environ, cfg.get("budget.reserve_percent"))
    account = board.lowest(found)[:1]
    parts += [board.account_text(a) for a in account]
    row["account"] = account[0]["account"] if account else None
    line = " · ".join(parts)
    try:
        atomic_write_json(os.path.join(project, STATUSLINE_CACHE), {"line": line, "stamp": stamp, "written": time.time()})
    except OSError:   # a read-only project: the line is read again next time
        pass
    r.set("LINE", line)
    r.raw = line + "\n"
    return r.table("line", [row], hidden=True)
