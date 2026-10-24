"""User command ``template list | show | check | import | export | use | designer``
(optimize.md § 4): the report templates of the project, the user's and the
built-in ones."""
import os
import shutil

from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _

LEVELS = ("research", "family", "project", "user")


def template_args(p, common):
    p.add_argument("action", choices=("list", "show", "check", "import", "export", "use", "designer"))
    p.add_argument("target", nargs="?", help=_("the template's id, or a .html file (check, import)"))
    p.add_argument("file", nargs="?", help=_("export: the file to write"))
    p.add_argument("--scope", choices=("project", "user"), default="project",
                   help=_("import: the project's templates/ or the user's folder"))
    p.add_argument("--replace", action="store_true", help=_("import: replace a template of the same id"))
    p.add_argument("--level", choices=LEVELS, default="project",
                   help=_("use: the research, its family, the project or the user"))
    p.add_argument("--research", help=_("use --level research or family: research id or unique prefix"))
    p.add_argument("--no-open", action="store_true", help=_("designer: copy the page without opening it"))


def _project(ctx):
    try:
        return ctx.project
    except Exception:   # noqa: BLE001 — outside a project: the user's and the built-in templates
        return None


def _config(ctx):
    try:
        return ctx.config
    except Exception:   # noqa: BLE001
        return None


def _get(ctx, tid):
    from probandia.report import template as T

    if not tid:
        raise UsageError(_("give the template's id"))
    tpl = T.find(tid, _project(ctx), _config(ctx), ctx.environ)
    if tpl is None:
        from probandia.suggest import lines

        known = [x.id for x in T.available(_project(ctx), _config(ctx), ctx.environ)]
        raise UsageError(_("no template {id}").format(id=tid), values={"REASON": "unknown-template"},
                         lines=lines(tid, known))
    return tpl


def _from_file_or_id(ctx, target):
    from probandia.report import template as T

    if target and target.endswith(".html") and os.path.isfile(target):
        return T.load(target, "file")
    return _get(ctx, target)


def template(ctx):
    action = ctx.args.action
    return {"list": listing, "show": show, "check": check, "import": import_, "export": export, "use": use,
            "designer": designer}[action](ctx)


def listing(ctx):
    from probandia.report import template as T

    project, config = _project(ctx), _config(ctx)
    found = T.available(project, config, ctx.environ)
    active, origin = T.choose(None, None, None, config)
    r = Result("OK", {"TEMPLATES": len(found), "ACTIVE": active, "ORIGIN": origin})
    rows = []
    for tpl in found:
        ok = not T.check(tpl)
        mark = "*" if tpl.id == active else " "
        r.data("template", f"{mark} {tpl.id} [{tpl.scope}] v{tpl.version} {tpl.name}" + ("" if ok else " (refused)"))
        rows.append({"id": tpl.id, "scope": tpl.scope, "version": tpl.version, "name": tpl.name,
                     "check": "ok" if ok else "refused", "active": tpl.id == active})
    r.table("templates", rows)
    return r


def show(ctx):
    from probandia.report import template as T

    tpl = _get(ctx, ctx.args.target)
    reasons = T.check(tpl)
    r = Result("OK" if not reasons else "WARN", {
        "TEMPLATE": tpl.id, "NAME": tpl.name, "VERSION": tpl.version, "CONTRACT": tpl.meta.get("contract", ""),
        "SCOPE": tpl.scope, "FILE": tpl.path, "HASH": tpl.sha256[:12], "NOTES": tpl.notes,
        "SLOTS": ",".join(tpl.slots()), "CHECK": "ok" if not reasons else "refused"})
    if tpl.meta.get("description"):
        r.line(tpl.meta["description"])
    for reason in reasons[:8]:
        r.data("problem", reason)
    return r


def check(ctx):
    from probandia.report import template as T

    tpl = _from_file_or_id(ctx, ctx.args.target)
    reasons = T.check(tpl)
    if reasons:
        r = Result("FAIL", {"TEMPLATE": tpl.id, "REASON": "template-refused", "PROBLEMS": len(reasons)})
        for reason in reasons[:20]:
            r.data("problem", reason)
        return r
    return Result("OK", {"TEMPLATE": tpl.id, "VERSION": tpl.version, "CONTRACT": tpl.meta.get("contract")})


def _scope_dir(ctx, scope):
    from probandia.report import template as T

    if scope == "project":
        return os.path.join(ctx.project, "templates")
    return T.user_dir(_config(ctx), ctx.environ)


def import_(ctx):
    """``template import <file> [--scope project|user] [--replace]``: checked, then copied
    as ``<id>.html``."""
    from probandia.report import template as T
    from probandia.util.fs import atomic_write_text

    if not ctx.args.target or not os.path.isfile(ctx.args.target):
        raise UsageError(_("template import needs the template's .html file"))
    tpl = T.load(ctx.args.target, "file")
    folder = _scope_dir(ctx, ctx.args.scope)
    dest = os.path.join(folder, f"{tpl.id}.html")
    reasons = T.check(T.parse(tpl.text, dest))
    if reasons:
        raise UsageError(_("the template is refused"), lines=reasons[:20],
                         values={"REASON": "template-refused", "TEMPLATE": tpl.id})
    if os.path.isfile(dest) and T.load(dest).sha256 != tpl.sha256 and not ctx.args.replace:
        raise UsageError(_("{file} exists: --replace to replace it").format(file=dest),
                         values={"REASON": "exists", "TEMPLATE": tpl.id})
    os.makedirs(folder, exist_ok=True)
    atomic_write_text(dest, tpl.text)
    r = Result("OK", {"TEMPLATE": tpl.id, "VERSION": tpl.version, "SCOPE": ctx.args.scope, "FILE": dest})
    if T.find(tpl.id, None, None, ctx.environ) is not None and ctx.args.scope == "project":
        r.line(_("it hides the template of the same id of your folder or of the engine"))
    r.line(_("to use it: template use {id}").format(id=tpl.id))
    return r


def export(ctx):
    tpl = _get(ctx, ctx.args.target)
    if not ctx.args.file:
        raise UsageError(_("template export needs the file to write"))
    folder = os.path.dirname(os.path.abspath(ctx.args.file))
    os.makedirs(folder, exist_ok=True)
    shutil.copyfile(tpl.path, ctx.args.file)
    return Result("OK", {"TEMPLATE": tpl.id, "FILE": ctx.args.file, "HASH": tpl.sha256[:12]})


def use(ctx):
    """``template use <id> [--level research|family|project|user] [--research <id>]``."""
    from probandia import config as cfgmod
    from probandia.config import tomlfile
    from probandia.report import template as T
    from probandia.util import yamlio

    tpl = _get(ctx, ctx.args.target)
    reasons = T.check(tpl)
    if reasons:
        raise UsageError(_("the template {id} is refused: run template check {id}").format(id=tpl.id),
                         lines=reasons[:5], values={"REASON": "template-refused"})
    level = ctx.args.level
    if level in ("research", "family"):
        from probandia.research import find_research

        research = find_research(ctx.project, ctx.args.research, ctx.environ)
        path = os.path.join(research.folder, "research.yaml") if level == "research" else \
            os.path.join(research.family_folder, "family.yaml")
        doc = yamlio.load(path) or {}
        doc["template"] = tpl.id
        yamlio.dump(path, doc)
        where = research.id if level == "research" else research.family
    else:
        from probandia.cli.config_cmd import USER_HEADER

        paths = cfgmod.layer_paths(_project(ctx) if level == "project" else None, ctx.environ)
        if level == "project":
            ctx.project  # raises NotInProject (exit 6)
        path = paths[level]
        tomlfile.set_value(path, "report.template", tpl.id, header=USER_HEADER if level == "user" else None)
        where = path
    r = Result("OK", {"TEMPLATE": tpl.id, "LEVEL": level, "FILE": path, "WHERE": where})
    if tpl.scope == "project" and level == "user":
        r.status = "WARN"
        r.line(_("the template is the project's: other projects will not find it; template import it --scope user"))
    r.line(_("render the reports again: render --all"))
    return r


def designer(ctx):
    """``template designer``: copies the template designer, with a sample report, into
    the project (``templates/designer.html``) and opens it (optimize 4.7)."""
    from probandia.report import designer as D

    folder = os.path.join(ctx.project, "templates") if _project(ctx) else os.getcwd()
    path = D.write(folder, ctx.environ)
    r = Result("OK", {"FILE": path})
    if not ctx.args.no_open:
        opened = D.open_page(path)
        r.set("OPENED", opened)
    r.line(_("the page works offline: change the settings, then download the template and run "
             "template import <file>"))
    return r
