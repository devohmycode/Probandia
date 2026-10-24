"""User command ``library``: find, save, test, trust, list, show and run learned scripts,
in the project's library and the user's (decision 5.1.1); promote and demote
between them."""
import json
import os

from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import EXIT_FAIL, UsageError
from probandia.i18n import _


def library_args(p, common):
    p.add_argument("action", choices=("find", "save", "test", "trust", "list", "show", "run", "promote", "demote",
                                      "draft", "install", "uninstall", "export", "import"))
    p.add_argument("target", nargs="?", help=_("the need (find), the file (save) or the script id"))
    p.add_argument("--id", dest="sid", help=_("save: the script's id (a slug)"))
    p.add_argument("--kind", choices=("connector", "helper", "skill", "agent"), default=None,
                   help=_("save: connector or helper; draft: skill or agent"))
    p.add_argument("--trigger", default="", help=_("draft: when a harness should use the skill or agent"))
    p.add_argument("--harnesses", default="", help=_("draft: comma-separated harnesses it is meant for"))
    p.add_argument("--scope", choices=("project", "user"), default="project",
                   help=_("install, uninstall, draft: the project's library or the user's"))
    p.add_argument("--ids", default="", help=_("export: comma-separated element ids"))
    p.add_argument("--for", dest="for_harness", choices=("claude-code", "codex", "cursor", "droid"),
                   help=_("install, uninstall: the harness to install for (default: the one calling)"))
    p.add_argument("--purpose", default="", help=_("save: what the script does"))
    p.add_argument("--hosts", default="", help=_("save: comma-separated hosts it may reach"))
    p.add_argument("--env", default="", help=_("save: comma-separated variables it may read"))
    p.add_argument("--witness-args", help=_("save: JSON arguments of the witness run"))
    p.add_argument("--expect", type=int, default=1, help=_("save: the witness's minimum number of results"))
    p.add_argument("--inputs", help=_("save: JSON object of the inputs and their types"))
    p.add_argument("--outputs", default="", help=_("save: what the script returns"))
    p.add_argument("--args", dest="run_args", default="{}", help=_("run: JSON arguments"))
    p.add_argument("--research", help=_("run: the research whose pass uses the script"))
    p.add_argument("--approve", nargs="?", const="yes", choices=("yes", "no"),
                   help=_("run, install: the user approved it"))
    p.add_argument("--to", dest="to_scope", choices=("user",), default="user",
                   help=_("promote: the scope to copy the element to"))


def _json(text, what):
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        raise UsageError(_("{what} is not valid JSON").format(what=what))
    if not isinstance(value, dict):
        raise UsageError(_("{what} must be a JSON object").format(what=what))
    return value


def _line(s):
    if s["kind"] == "recipe":
        return f"{s['id']} [recipe] {s.get('question_type')} {s.get('archive')}: {s.get('query_template')} " \
               f"({s.get('hits', 0)} hits)"
    hosts = ",".join((s.get("target") or {}).get("hosts") or []) or "-"
    runs = s.get("runs") or {}
    use = f"used={int(s.get('used') or 0)} ok={int(runs.get('ok') or 0)} last={_last(s) or '-'}"
    return f"{s['id']} [{s['status']}] v{s.get('version', 1)} {s['kind']} {hosts} {use}: {s.get('purpose', '')}"


def _last(s):
    """The last time an element was used or passed."""
    dates = [d for d in (s.get("last_used"), (s.get("runs") or {}).get("last_ok")) if d]
    return max(dates) if dates else None


def _row(s, scope="project"):
    runs = s.get("runs") or {}
    return {"script": s["id"], "scope": scope, "level": "recipe" if s["kind"] == "recipe" else s["status"], "kind": s["kind"],
            "version": s.get("version", 1), "witness": bool(s.get("witness")) or s["kind"] == "recipe",
            "runs": f"{runs.get('ok', 0)}/{runs.get('ok', 0) + runs.get('failed', 0)}",
            "used": int(s.get("used") or 0), "last_run": _last(s),
            "purpose": s.get("purpose") or s.get("query_template") or ""}


def library(ctx):
    from probandia import library as libmod
    from probandia.library import Library

    lib = Library(ctx.project)
    action = ctx.args.action
    if action == "list":
        rows, lines = [], []
        for one in libmod.libraries(ctx.project, ctx.environ):
            for s in one.scripts():
                rows.append(_row(s, one.scope))
                lines.append(f"{_line(s)} ({one.scope})" if one.scope == "user" else _line(s))
        r = Result("OK", {"SCRIPTS": len(rows), "USER": sum(1 for x in rows if x["scope"] == "user")})
        for line in lines:
            r.data("script", line)
        r.table("scripts", rows)
        r.view = "library"
        return r
    if action == "find":
        if not ctx.args.target:
            raise UsageError(_("library find needs the need, in words"))
        found = libmod.find_all(ctx.project, ctx.args.target, ctx.environ)
        r = Result("OK", {"FOUND": len(found)})
        for score, s, scope in found:
            r.data("script", f"{score} [{scope}] {_line(s)}")
        if not found:
            r.line(_("nothing in the library: write the script, then library save it with its witness"))
        return r
    if action == "save":
        if not ctx.args.target or not ctx.args.sid:
            raise UsageError(_("library save needs the file and --id"))
        witness = None
        if ctx.args.witness_args is not None:
            witness = {"args": _json(ctx.args.witness_args, "--witness-args"),
                       "expect": {"min_results": ctx.args.expect}}
        me = actor(ctx)
        entry = lib.save(ctx.args.target, ctx.args.sid, ctx.args.kind or "connector", ctx.args.purpose, witness,
                         [h.strip() for h in ctx.args.hosts.split(",") if h.strip()],
                         [v.strip() for v in ctx.args.env.split(",") if v.strip()],
                         _json(ctx.args.inputs, "--inputs"), ctx.args.outputs,
                         {"harness": me["harness"], "agent": me["agent"]})
        r = Result("OK", {"SCRIPT": entry["id"], "STATE": entry["status"], "VERSION": entry["version"],
                          "HASH": entry["sha256"][:12]})
        if not witness:
            r.line(_("no witness: the script stays a draft until it has one"))
        return r
    if action == "draft":
        return draft(ctx)
    if action == "import":
        return import_lot(ctx)
    if action == "export":
        return export(ctx)
    if not ctx.args.target:
        raise UsageError(_("give the script id"))
    sid = ctx.args.target
    if action in ("install", "uninstall"):
        return install(ctx, sid)
    if action == "promote":
        entry, ok, error = libmod.promote(ctx.project, sid, ctx.environ)
        r = Result("OK" if ok is not False else "WARN", {"SCRIPT": sid, "SCOPE": "user", "STATE": entry["status"],
                                                        "WITNESS": {None: "none", True: "passed", False: "failed"}[ok],
                                                        "FILE": libmod.user_folder(ctx.environ)})
        if error:
            r.line(error)
        return r
    if action == "demote":
        entry = libmod.demote(ctx.project, sid, ctx.environ)
        return Result("OK", {"SCRIPT": sid, "SCOPE": "project", "STATE": entry["status"]})
    lib, _s = libmod.locate(ctx.project, sid, ctx.environ)
    if action == "show":
        s = lib.get(sid)
        r = Result("OK", {"SCRIPT": sid, "STATE": s["status"], "KIND": s["kind"], "VERSION": s.get("version", 1),
                          "SCOPE": lib.scope})
        for k in ("purpose", "path", "query_template", "question_type", "archive"):
            if s.get(k):
                r.data(k, s[k])
        if s.get("target"):
            r.data("hosts", ",".join(s["target"].get("hosts") or []))
        r.data("env", ",".join(s.get("env") or []))
        if s.get("witness"):
            r.data("witness", json.dumps(s["witness"], ensure_ascii=False))
        r.data("runs", json.dumps(s.get("runs") or {}, ensure_ascii=False))
        return r
    if action == "trust":
        s = lib.trust(sid)
        return Result("OK", {"SCRIPT": sid, "STATE": s["status"]})
    if action == "test":
        auto = ctx.config.get("library.auto_trust_after") if ctx.config.grade >= 3 else 0
        ok, error = lib.test(sid, ctx.environ, auto_trust_after=auto)
        s = lib.get(sid)
        r = Result("OK" if ok else "FAIL", {"SCRIPT": sid, "STATE": s["status"],
                                           "RUNS_OK": s["runs"]["ok"]}, exit_code=None if ok else EXIT_FAIL)
        if error:
            r.set("REASON", "witness-failed")
            r.line(error)
        return r
    return run(ctx, lib, sid)


def run(ctx, lib, sid):
    """``library run``: a script inside a pass. A draft needs the user's approval
    (``library_run_draft``), recorded; a tested script whose witness is stale is
    tested again first."""
    from probandia import events
    from probandia.indexes import locked
    from probandia.lifecycle import pass_state
    from probandia.research import find_research

    s = lib.get(sid)
    if s["kind"] == "recipe":
        raise UsageError(_("a recipe is a query: the planner proposes it"))
    me = actor(ctx)
    approval = None
    if s["status"] == "draft" and not lib.approved(s):
        if ctx.args.approve != "yes":
            prompt = _("The learned script {id} is a draft (version {v}, never tested). Run it once?").format(
                id=sid, v=s.get("version", 1))
            r = Result.ask("library_run_draft", prompt, ["no", "yes"], "no", values={"SCRIPT": sid})
            r.line(_("answer yes with --approve, after the user said so"))
            return r
        approval = lib.approve(s, f"{me['harness']}/{me.get('session', '')}/{me['agent']}")
    if s["status"] in ("tested", "trusted") and not lib.witness_fresh(s, ctx.config.get("witness.max_age_hours")):
        ok, error = lib.test(sid, ctx.environ)
        if not ok:
            return Result("FAIL", {"SCRIPT": sid, "REASON": "witness-failed", "STATE": "draft"}, [error],
                          exit_code=EXIT_FAIL)
        s = lib.get(sid)
    ok, rows, error = lib.run(s, _json(ctx.args.run_args, "--args"), ctx.environ)
    lib.record_use(sid, ok)
    research = None
    try:
        research = find_research(ctx.project, ctx.args.research, ctx.environ)
    except Exception:  # noqa: BLE001 — outside a research, nothing is logged
        research = None
    if research is not None:
        last, open_ = pass_state(events.read(research.events_path))
        if open_:
            payload = {"script": sid, "version": s.get("version", 1), "sha256": s.get("sha256"),
                       "status": s["status"], "ok": ok}
            if approval:
                payload["approval"] = approval
            with locked(ctx.project, f"research:{research.id}", me, ctx.config.get("locks.expiry_minutes")):
                events.append(research.events_path, [events.make("library.used", payload, me, last)])
    if not ok:
        return Result("FAIL", {"SCRIPT": sid, "REASON": "script-failed"}, [error], exit_code=EXIT_FAIL)
    rows = rows if isinstance(rows, list) else [rows]
    path = os.path.join(ctx.project, ".probandia", "details", f"library-{sid}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1, default=str)
    r = Result("OK", {"SCRIPT": sid, "STATE": s["status"], "VERSION": s.get("version", 1), "ROWS": len(rows)},
               details=os.path.relpath(path, ctx.project).replace(os.sep, "/"))
    if approval:
        r.set("APPROVED", True)
    for row in rows[:10]:
        r.data("row", json.dumps(row, ensure_ascii=False, default=str)[:200])
    return r


# learned skills and agents (optimize 5.1.5 to 5.1.8, 5.1.10)


def _harness(ctx):
    from probandia.harness import detect

    harness = ctx.args.for_harness or detect(ctx.args.harness, ctx.environ)[0]
    if harness == "cli":
        raise UsageError(_("name the harness to install for: --for claude-code, codex, cursor or droid"))
    return harness


def _library(ctx, scope):
    from probandia.library import Library

    project = None
    try:
        project = ctx.project
    except Exception:   # noqa: BLE001 — the user's library works outside a project
        if scope == "project":
            raise
    return Library(project, scope=scope, environ=ctx.environ)


def draft(ctx):
    """``library draft <file> --kind skill|agent --id probandia-<name>``: checked, stored as a draft."""
    from probandia import learning

    if ctx.args.kind not in ("skill", "agent") or not ctx.args.target or not ctx.args.sid:
        raise UsageError(_("library draft needs the file, --kind skill or agent, and --id probandia-<name>"))
    me = actor(ctx)
    entry = learning.draft(_library(ctx, ctx.args.scope), ctx.args.kind, ctx.args.target, ctx.args.sid,
                           ctx.args.purpose, ctx.args.trigger,
                           [h.strip() for h in ctx.args.harnesses.split(",") if h.strip()],
                           {"harness": me["harness"], "agent": me["agent"]})
    r = Result("OK", {"ELEMENT": entry["id"], "KIND": entry["kind"], "STATE": entry["status"],
                      "VERSION": entry["version"], "SCOPE": entry["scope"], "HASH": entry["sha256"][:12]})
    r.line(_("checked: format, size and rules; ask the user before library install"))
    return r


def install(ctx, sid):
    """``library install|uninstall <id> --scope project|user --harness <h>``. An install
    asks the user first (QUESTION=library_install), always for the user's scope."""
    from probandia import learning
    from probandia.library import locate

    lib, entry = locate(ctx.project if ctx.args.scope == "project" else _project(ctx), sid, ctx.environ)
    harness = _harness(ctx)
    if ctx.args.action == "uninstall":
        removed = learning.uninstall(lib, sid, harness, ctx.args.scope)
        r = Result("OK" if removed else "WARN", {"ELEMENT": sid, "REMOVED": len(removed)})
        for path in removed:
            r.data("removed", path)
        return r
    view = learning.preview(lib, sid, ctx.args.scope, harness)
    auto = ctx.args.scope == "project" and _setting(ctx, "library.save") == "auto"
    if ctx.args.approve == "no":
        from probandia.cli import asking

        return asking.declined({"ELEMENT": sid})
    if ctx.args.approve != "yes" and not auto:
        prompt = _("Install the {kind} {id} ({change}) for {harness}, at {scope} scope? {purpose}").format(
            kind=view["KIND"], id=sid, change=view["CHANGE"], harness=harness, scope=view["SCOPE"],
            purpose=view["PURPOSE"])
        r = Result.ask("library_install", prompt, ["no", "yes"], "no", values=dict(view, ELEMENT=sid))
        r.set("OPTION", "--approve")
        # the user approves the text itself, not a summary: the keyword check is only a first filter
        path = lib.file(entry)
        r.set("FILE", path)
        r.details = path
        r.line(_("show the user the whole text of FILE before they answer; never answer for them; "
                 "then run the command again with --approve yes"))
        if getattr(ctx, "asks", False) and ctx.stdout is not None:
            with open(path, encoding="utf-8") as fh:
                ctx.stdout.write("\n" + fh.read().rstrip() + "\n\n")
        return r
    paths = learning.install(lib, sid, ctx.args.scope, harness, _project(ctx), ctx.environ)
    r = Result("OK", dict(view, ELEMENT=sid, WRITTEN=len(paths)))
    for path in paths:
        r.data("wrote", path)
    return r


def _project(ctx):
    try:
        return ctx.project
    except Exception:   # noqa: BLE001
        return None


def _setting(ctx, key):
    try:
        return ctx.config.get(key)
    except Exception:   # noqa: BLE001 — outside a project
        return None


def export(ctx):
    from probandia import learning

    ids = [i.strip() for i in ctx.args.ids.split(",") if i.strip()]
    if not ctx.args.target or not ids:
        raise UsageError(_("library export needs the lot's file (.zip) and --ids"))
    entries = learning.export(_project(ctx), ids, ctx.args.target, ctx.environ)
    return Result("OK", {"FILE": ctx.args.target, "ELEMENTS": len(entries)})


def import_lot(ctx):
    """``library import <lot.zip>``: every element back to draft; the witnesses run again."""
    from probandia import learning
    from probandia import library as libmod

    if not ctx.args.target:
        raise UsageError(_("library import needs the lot's file"))
    lib = _library(ctx, ctx.args.scope)
    entries = learning.import_lot(lib, ctx.args.target)
    r = Result("OK", {"FILE": ctx.args.target, "ELEMENTS": len(entries), "SCOPE": lib.scope})
    for e in entries:
        state = e["status"]
        if e["kind"] in ("connector", "helper") and e.get("witness"):
            try:
                ok, error = lib.test(e["id"], ctx.environ)
            except libmod.Escapes as err:
                ok, error = False, err.message
            state = lib.get(e["id"])["status"]
            if not ok:
                r.status = "WARN"
                r.data("witness_failed", f"{e['id']}: {error}")
        r.data("element", f"{e['id']} {e['kind']} {state}")
    return r
