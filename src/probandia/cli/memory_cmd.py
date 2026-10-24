"""User command ``memory add | list | remove | sync`` (optimize.md § 5.2): the
managed section of ``AGENTS.md``. An agent proposes an entry, the user approves
it (``QUESTION=memory_add``), the engine writes it; the user's scope always asks
on its own."""
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _


def memory_args(p, common):
    from probandia.memory import KINDS

    p.add_argument("action", choices=("add", "list", "remove", "sync"))
    p.add_argument("target", nargs="?", help=_("add: the entry, one line; remove: its id (M3)"))
    p.add_argument("--kind", choices=KINDS, default="decision", help=_("add: what sort of entry"))
    p.add_argument("--supersedes", default="", help=_("add: comma-separated ids the entry replaces"))
    p.add_argument("--scope", choices=("project", "user"), default="project",
                   help=_("the project's AGENTS.md, or the user's file of the harness"))
    p.add_argument("--for", dest="for_harness", choices=("claude-code", "codex"),
                   help=_("user scope: the harness whose file to write (default: the one calling)"))
    p.add_argument("--approve", nargs="?", const="yes", choices=("yes", "no"),
                   help=_("add, remove, sync: the user approved it"))
    p.add_argument("--overflow", choices=("archive",),
                   help=_("add: the section is full; move the oldest entries to memory-archive.md"))


def _project(ctx):
    try:
        return ctx.project
    except Exception:   # noqa: BLE001
        return None


def _where(ctx):
    from probandia import memory

    harness = None
    if ctx.args.scope == "user":
        from probandia.harness import detect

        harness = ctx.args.for_harness or detect(ctx.args.harness, ctx.environ)[0]
    project = _project(ctx)
    if ctx.args.scope == "project" and project is None:
        ctx.project  # raises NotInProject (exit 6)
    path, claude = memory.target(ctx.args.scope, project, harness, ctx.environ)
    return project, path, claude


def _living_years(ctx):
    try:
        return ctx.config.get("privacy.living_years") or 100
    except Exception:   # noqa: BLE001 — outside a project
        return 100


def memory(ctx):
    action = ctx.args.action
    if action == "list":
        return listing(ctx)
    if action == "add":
        return add(ctx)
    if action == "remove":
        return remove(ctx)
    return sync(ctx)


def _sizes(r, section):
    from probandia import memory

    lines, nbytes = memory.size(section)
    r.set("LINES", f"{lines}/{memory.MAX_LINES}").set("BYTES", f"{nbytes}/{memory.MAX_BYTES}")


def listing(ctx):
    from probandia import memory

    _p, path, claude = _where(ctx)
    text, items = memory.load(path)
    r = Result("OK", {"ENTRIES": len(items), "FILE": path, "SCOPE": ctx.args.scope})
    _sizes(r, memory.section_of(text) or "")
    if claude is not None:
        r.set("IMPORT", memory.imports(claude))
    for x in items:
        r.data("entry", memory.line(x)[2:])
    r.table("entries", items, ["id", "date", "kind", "text"])
    return r


def _ask(ctx, question, prompt, values, show):
    """The question; the user reads the lines themselves before answering."""
    r = Result.ask(question, prompt, ["no", "yes"], "no", values=values)
    r.set("OPTION", "--approve")
    for text in show:
        r.data("show", text)
    r.line(_("show the user these lines as they will be written; never answer for them; "
             "then run the command again with --approve yes"))
    if getattr(ctx, "asks", False) and ctx.stdout is not None:
        ctx.stdout.write("\n" + "\n".join(show) + "\n\n")
    return r


def add(ctx):
    from probandia import memory

    text = (ctx.args.target or "").strip()
    if not text:
        raise UsageError(_("memory add needs the entry, in one line"))
    project, path, claude = _where(ctx)
    reasons = memory.check(text, project, ctx.environ, _living_years(ctx))
    if reasons:
        raise UsageError(_("the entry is refused"), lines=reasons, values={"REASON": "refused"})
    supersedes = [s.strip() for s in ctx.args.supersedes.split(",") if s.strip()]
    items, entry, gone, same = memory.plan_add(path, ctx.args.scope, text, ctx.args.kind, supersedes)
    values = {"ENTRY": entry["id"], "SCOPE": ctx.args.scope, "FILE": path}
    if same:
        r = Result("OK", dict(values, CHANGED=False))
        r.line(_("already in the memory: nothing written"))
        return r
    keep, overflowing = items, []
    if not memory.fits(memory.render(items, ctx.args.scope)):
        if ctx.args.overflow != "archive":
            olds = memory.overflow(items, ctx.args.scope)[1]
            r = Result.ask("memory_full", _("The memory is full ({lines} lines or {bytes} bytes). Merge entries "
                                            "into one, or move the oldest to {archive}?").format(
                lines=memory.MAX_LINES, bytes=memory.MAX_BYTES, archive=memory.ARCHIVE),
                ["merge", "archive", "no"], "merge", values=dict(values, ENTRY=None, OLDEST=len(olds)))
            for x in olds:
                r.data("oldest", memory.line(x)[2:])
            r.line(_("merge: memory add \"<one entry for several>\" --supersedes <ids>; "
                     "archive: the same command again with --overflow archive"))
            return r
        keep, overflowing = memory.overflow(items, ctx.args.scope)
    importing = claude is not None and not memory.imports(claude)
    if ctx.args.approve == "no":
        from probandia.cli import asking

        return asking.declined(values)
    if ctx.args.approve != "yes":
        show = [memory.line(entry)]
        show += [_("replaces: {line}").format(line=memory.line(x)) for x in gone]
        show += [_("to {archive}: {line}").format(archive=memory.ARCHIVE, line=memory.line(x)) for x in overflowing]
        if importing:
            show.append(_("CLAUDE.md gets one line: {line}").format(line=memory.IMPORT))
        where = path if ctx.args.scope == "user" else "AGENTS.md"
        r = _ask(ctx, "memory_add", _("Write this entry in {file}, which the harness loads at every session?")
                 .format(file=where), dict(values, IMPORT="add" if importing else "none"), show)
        if ctx.args.scope == "user":
            r.line(_("the user's scope reaches every project: ask for it on its own, even when the project's "
                     "entries were approved"))
        return r
    memory.archive(path, ctx.args.scope, gone, _("replaced by {id}").format(id=entry["id"]))
    memory.archive(path, ctx.args.scope, overflowing, _("archived"))
    changed = memory.write(path, keep, ctx.args.scope, project, ctx.environ)
    if importing:
        memory.add_import(claude)
    r = Result("OK", dict(values, CHANGED=changed, REPLACED=len(gone), ARCHIVED=len(overflowing),
                          IMPORT="added" if importing else "none"))
    _sizes(r, memory.section_of(memory.read(path)) or "")
    return r


def remove(ctx):
    from probandia import memory

    eid = (ctx.args.target or "").strip().upper()
    if not eid:
        raise UsageError(_("give the entry's id, such as M3"))
    project, path, _claude = _where(ctx)
    _text, items = memory.load(path)
    entry = next((x for x in items if x["id"] == eid), None)
    if entry is None:
        raise UsageError(_("no entry {ids} in the memory").format(ids=eid))
    values = {"ENTRY": eid, "SCOPE": ctx.args.scope, "FILE": path}
    if ctx.args.approve == "no":
        from probandia.cli import asking

        return asking.declined(values)
    if ctx.args.approve != "yes":
        return _ask(ctx, "memory_remove", _("Remove this entry from the memory? It goes to {archive}.").format(
            archive=memory.ARCHIVE), values, [memory.line(entry)])
    memory.archive(path, ctx.args.scope, [entry], _("removed"))
    memory.write(path, [x for x in items if x["id"] != eid], ctx.args.scope, project, ctx.environ)
    return Result("OK", dict(values, REMOVED=1, ENTRIES=len(items) - 1))


def sync(ctx):
    """Writes the section again from its entries: one section, the title of the
    user's language, the fingerprint taken again (a hand edit is adopted once
    its entries pass the checks), and the ``@AGENTS.md`` import, asked."""
    from probandia import memory

    project, path, claude = _where(ctx)
    text, items = memory.load(path)
    refused = []
    for x in items:
        reasons = memory.check(x["text"], project, ctx.environ, _living_years(ctx))
        if reasons:
            refused.append(f"{x['id']}: {'; '.join(reasons)}")
    if refused:
        raise UsageError(_("entries of the section break the rules: remove them, then sync again"),
                         lines=refused, values={"REASON": "refused"})
    importing = claude is not None and not memory.imports(claude) and memory.section_of(text) is not None
    if importing and ctx.args.approve != "yes":
        if ctx.args.approve == "no":
            importing = False
        else:
            return _ask(ctx, "memory_import", _("Add the line {line} to CLAUDE.md, so that Claude Code loads the "
                                                "memory of AGENTS.md?").format(line=memory.IMPORT),
                        {"FILE": claude}, [memory.IMPORT])
    changed = memory.write(path, items, ctx.args.scope, project, ctx.environ) if memory.section_of(text) else False
    if importing:
        memory.add_import(claude)
    r = Result("OK", {"ENTRIES": len(items), "CHANGED": changed, "FILE": path,
                      "IMPORT": "added" if importing else ("present" if claude and memory.imports(claude) else "none")})
    _sizes(r, memory.section_of(memory.read(path)) or "")
    return r
