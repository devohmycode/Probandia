"""The ``config`` command: show, explain, set, unset, init, validate."""
import os

from probandia import config as cfgmod
from probandia.cli.output import Result
from probandia.config import registry, tomlfile
from probandia.errors import EXIT_USAGE, NotInProject, UsageError
from probandia.i18n import N_, _
from probandia.project import ENV_VAR, create_project, is_project, search_upwards

GRADE_CHOICES = ("essential", "advanced", "expert")
USER_HEADER = "# Probandia user settings.\n"


def configure(parser, common):
    sub = parser.add_subparsers(dest="action", metavar="<action>", title=_("actions"))
    sub.required = True
    p = sub.add_parser("show", parents=[common], help=_("settings in effect"))
    p.add_argument("--origin", action="store_true", help=_("show where each value comes from"))
    p.add_argument("--grade", dest="show_grade", choices=GRADE_CHOICES,
                   help=_("show the settings of another grade"))
    p.add_argument("--all", action="store_true", help=_("show every setting"))
    p.add_argument("--user", action="store_true", help=_("only what the user file sets"))
    p = sub.add_parser("explain", parents=[common], help=_("describe one setting"))
    p.add_argument("key")
    for name, text in (("set", N_("write a setting to a file")),
                       ("unset", N_("remove a setting from a file"))):
        p = sub.add_parser(name, parents=[common], help=_(text))
        p.add_argument("key")
        if name == "set":
            p.add_argument("value")
        where = p.add_mutually_exclusive_group()
        where.add_argument("--user", action="store_true", help=_("the user file"))
        where.add_argument("--local", action="store_true",
                           help=_("probandia.local.toml, not versioned"))
    p = sub.add_parser("init", parents=[common], help=_("create probandia.toml"))
    p.add_argument("--grade", dest="init_grade", choices=GRADE_CHOICES, default="essential",
                   help=_("settings written uncommented"))
    sub.add_parser("validate", parents=[common], help=_("check every layer"))
    sub.add_parser("path", parents=[common], help=_("the files of the seven layers, and which exist"))
    sub.add_parser("wizard", parents=[common], help=_("the essential settings, asked at the keyboard"))
    p = sub.add_parser("edit", parents=[common], help=_("open a settings file in an editor, then check it"))
    where = p.add_mutually_exclusive_group()
    where.add_argument("--user", action="store_true", help=_("the user file"))
    where.add_argument("--local", action="store_true", help=_("probandia.local.toml, not versioned"))
    p = sub.add_parser("grade", parents=[common], help=_("change the grade, and see the settings it shows"))
    p.add_argument("new_grade", choices=GRADE_CHOICES)
    p.add_argument("--user", action="store_true", help=_("the user file"))
    sub.add_parser("diff", parents=[common], help=_("what differs from the defaults, layer by layer"))
    sub.add_parser("roles", parents=[common],
                   help=_("the model and the effort of each agent role, and where each comes from"))
    p = sub.add_parser("theme", parents=[common], help=_("the themes of probandia tui: list, save, delete"))
    themes_sub = p.add_subparsers(dest="theme_action", metavar="<theme action>", title=_("actions"))
    themes_sub.required = True
    themes_sub.add_parser("list", parents=[common], help=_("Probandia's themes and yours, and the one in use"))
    q = themes_sub.add_parser("save", parents=[common],
                              help=_("write one of your themes: themes/<name>.toml in your configuration folder"))
    q.add_argument("name", help=_("small letters, digits and hyphens"))
    q.add_argument("--base", choices=("dark", "light"), help=_("the theme of Probandia it starts from"))
    q.add_argument("--from", dest="start", metavar="<theme>",
                   help=_("copy this theme first; by default the theme itself when it exists, else its base"))
    q.add_argument("--set", dest="changes", action="append", default=[], metavar="<key>=<value>",
                   help=_("a colour (primary=#D4A64A) or a layout entry (buttons=tall); repeat it"))
    q = themes_sub.add_parser("delete", parents=[common], help=_("remove one of your themes"))
    q.add_argument("name")


def run(ctx):
    action = ctx.args.action
    if action == "init":
        return init(ctx)
    if action not in ("path", "theme") and not getattr(ctx.args, "user", False):
        ctx.project  # without --user, the project's layers are wanted (exit code 6)
    return {"show": show, "explain": explain, "set": set_, "unset": unset,
            "validate": validate, "path": path, "wizard": wizard, "edit": edit, "grade": grade,
            "diff": diff, "roles": roles, "theme": theme}[action](ctx)


def _project(ctx):
    """The project root, or None outside a project: the user's settings, the
    environment and the arguments still apply there."""
    try:
        return ctx.project
    except NotInProject:
        return None


def _config(ctx):
    project = _project(ctx)
    if project is not None:
        return ctx.config
    return cfgmod.load(None, ctx.environ, ctx.args.harness_options, args=ctx.arg_settings)


def init(ctx):
    """Creates a project in --project, PROBANDIA_PROJECT, or the current folder."""
    target = ctx.args.project or ctx.environ.get(ENV_VAR)
    if not target:
        above = search_upwards(ctx.cwd)
        if above is not None:
            return Result("WARN", {"PROJECT": above},
                          [_("already inside a project; nothing written")]).table("written", [], ["file"], hidden=True)
        target = ctx.cwd
    root = os.path.abspath(target)
    existed = is_project(root)
    grade = registry.GRADE_NUMBERS[ctx.args.init_grade]
    written = create_project(root, grade)
    r = Result("WARN" if existed else "OK", {"PROJECT": root, "GRADE": ctx.args.init_grade})
    if existed:
        r.line(_("the project already exists; probandia.toml kept"))
    for path in written:
        r.line(_("wrote {path}").format(path=path))
    r.table("written", [{"file": path} for path in written], ["file"], hidden=True)
    return r


def _entry(cfg, key, with_origin):
    text = f"{key}={cfgmod.show(cfg.get(key))}"
    if with_origin:
        text += f"  # {cfg.origin(key)}"
    if cfg.above_grade(key):
        text += "  " + _("(above grade)")
    return text


def show(ctx):
    cfg = _config(ctx)
    if ctx.args.all:
        max_grade, shown = 3, "all"
    elif ctx.args.show_grade:
        max_grade, shown = registry.GRADE_NUMBERS[ctx.args.show_grade], ctx.args.show_grade
    else:
        max_grade, shown = cfg.grade, registry.GRADES[cfg.grade]
    keys = cfg.keys(max_grade)
    keys += [k for k in cfg.values if k not in keys and cfg.above_grade(k)]
    if ctx.args.user:
        keys = [k for k in cfg.values if cfg.origin(k).layer == "user"]
    r = Result("WARN" if cfg.warnings else "OK",
               {"GRADE": registry.GRADES[cfg.grade], "SHOWN": shown, "COUNT": len(keys)})
    for w in cfg.warnings:
        r.line(w)
    rows = []
    for key in keys:
        r.line(_entry(cfg, key, ctx.args.origin))
        setting = registry.lookup(key)
        origin = cfg.origin(key)
        rows.append({"key": key, "value": cfgmod.show(cfg.get(key)), "layer": origin.layer,
                     "source": str(origin.source), "grade": registry.GRADES[setting.grade] if setting else "",
                     "above_grade": cfg.above_grade(key), "help": _(setting.help) if setting else ""})
    r.table("settings", rows)
    r.view = "config-show"
    return r


def _setting(key):
    setting = registry.lookup(key)
    if setting is None:
        from probandia.suggest import lines

        raise UsageError(_("unknown setting {key}").format(key=key),
                         lines=lines(key, list(registry.BY_KEY)) + [_("list them with: config show --all")])
    return setting


def explain(ctx):
    key = ctx.args.key
    setting = _setting(key)
    cfg = _config(ctx)
    default = registry.default_of(key)
    values = {
        "KEY": key, "TYPE": setting.type, "DEFAULT": cfgmod.show(default),
        "VALUES": setting.describe_values(), "GRADE": registry.GRADES[setting.grade],
        "ENV": setting.env if not setting.is_pattern else registry.env_name(key),
        "FLAG": setting.flag or "", "HARNESS": setting.harness_key if setting.harness else "",
        "VALUE": cfgmod.show(cfg.get(key)), "ORIGIN": str(cfg.origin(key)),
    }
    r = Result("OK", values, [_(setting.help)])
    from probandia.roles import FIELDS, OLDER

    prefix, _dot, field = key.partition(".")
    role = next((role for role, older in OLDER.items() if older == prefix), None)
    if role and field in FIELDS:   # T117: run.* and search.* count only when the role's own key is left alone
        r.line(_("a fallback of {key}: it counts while {key} is left at its default").format(
            key=f"roles.{role}.{field}"))
    if cfg.above_grade(key):
        r.line(_("(above grade)"))
    r.view = "config-explain"
    return r


def _target(ctx):
    paths = cfgmod.layer_paths(None if ctx.args.user else ctx.project, ctx.environ)
    if ctx.args.user:
        return "user", paths["user"]
    if getattr(ctx.args, "local", False):
        return "local", paths["local"]
    return "project", paths["project"]


def set_(ctx):
    key, raw = ctx.args.key, ctx.args.value
    setting = _setting(key)
    try:
        value = cfgmod.check_value(setting, cfgmod.parse_text(setting, raw))
    except ValueError:
        raise UsageError(_("invalid value {value} for {key}; allowed: {allowed}").format(
            value=repr(raw), key=key, allowed=setting.describe_values()))
    layer, path = _target(ctx)
    tomlfile.set_value(path, key, value, header=USER_HEADER if layer == "user" else None)
    after = cfgmod.load(_project(ctx), ctx.environ, ctx.args.harness_options, strict=False)
    r = Result("OK", {"KEY": key, "VALUE": cfgmod.show(value), "LAYER": layer, "FILE": path})
    origin = after.origin(key)
    if origin.layer != layer:
        r.status = "WARN"
        r.line(_("{layer} ({source}) overrides this value").format(
            layer=origin.layer, source=origin.source))
    if setting.grade > after.grade:
        r.line(_("this setting is above your grade ({grade}); it takes effect anyway")
               .format(grade=registry.GRADES[after.grade]))
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "roles":   # agent-models R4: a word on what the choice changes
        from probandia import roles as agent_roles

        for line in agent_roles.warnings(parts[1], parts[2], value):
            r.status = "WARN"
            r.line(line)
        hint = agent_roles.reinstall_hint(_project(ctx), parts[1])   # T125: agent files written before
        if hint:
            r.set("REINSTALL", f"probandia {hint[1]}")
            r.line(_("{path} keeps the earlier choice; rewrite it with: probandia {command}").format(
                path=hint[0], command=hint[1]))
    return r


def unset(ctx):
    key = ctx.args.key
    _setting(key)
    layer, path = _target(ctx)
    removed = tomlfile.unset_value(path, key)
    r = Result("OK" if removed else "WARN", {"KEY": key, "LAYER": layer, "FILE": path})
    if not removed:
        r.line(_("{key} is not set in this file").format(key=key))
    return r


def validate(ctx):
    cfg = cfgmod.load(_project(ctx), ctx.environ, ctx.args.harness_options,
                      args=ctx.arg_settings, strict=False)
    if cfg.problems:
        return Result("FAIL", {"REASON": "config", "ERRORS": len(cfg.problems)}, cfg.problems,
                      exit_code=EXIT_USAGE)
    if cfg.warnings:
        return Result("WARN", {"WARNINGS": len(cfg.warnings)}, cfg.warnings)
    return Result("OK", lines=[_("every layer is valid")])



def path(ctx):
    """The seven layers, lowest first: where each one comes from, and whether its
    file exists. Works outside a project."""
    project = _project(ctx)
    paths = cfgmod.layer_paths(project, ctx.environ)
    variables = sorted(k for k in ctx.environ if k.startswith("PROBANDIA_") and k not in registry.OTHER_VARIABLES)
    where = {
        "default": (_("built into the engine"), True),
        "harness": (_("--harness-options, or the options the harness remembered"), bool(ctx.args.harness_options)),
        "user": (paths["user"], os.path.isfile(paths["user"])),
        "project": (paths.get("project") or _("no project here"), "project" in paths and
                    os.path.isfile(paths["project"])),
        "local": (paths.get("local") or _("no project here"), "local" in paths and os.path.isfile(paths["local"])),
        "env": (", ".join(variables) or _("no PROBANDIA_ setting in the environment"), bool(variables)),
        "arg": (_("the options of the command"), bool(ctx.arg_settings)),
    }
    r = Result("OK", {"PROJECT": project or "none", "USER_FILE": paths["user"]})
    rows = []
    for layer in cfgmod.LAYERS:
        text, present = where[layer]
        r.data(layer, f"{'present' if present else 'absent'} {text}")
        rows.append({"layer": layer, "where": text, "present": present})
    r.table("layers", rows, ["layer", "where", "present"])
    r.view = "config-path"
    return r


# The questions of the essential settings (grade 1), in the order of probandia.toml.
WIZARD_CHOICES = {"language": ["auto", "en", "fr"], "report.formats": ["md,html", "md", "md,html,json"]}


def _choices(setting):
    if setting.key in WIZARD_CHOICES:
        return WIZARD_CHOICES[setting.key], True
    if setting.type == "enum":
        return [v for v in setting.values if v], False
    if setting.type == "int" and setting.values:
        lo, hi = setting.values
        return [str(n) for n in range(lo, hi + 1)], False
    if setting.type == "bool":
        return ["true", "false"], False
    return [], True


def wizard(ctx, project=None):
    """Asks the essential settings at the keyboard, the value in effect as the
    default, and writes the answers to the project's probandia.toml (CLI7-T9)."""
    from probandia.cli import asking, human

    if not getattr(ctx, "asks", False):
        raise UsageError(_("config wizard asks its questions at a terminal; use config set otherwise"))
    project = project or ctx.project
    cfg = cfgmod.load(project, ctx.environ, strict=False)
    path = cfgmod.layer_paths(project, ctx.environ)["project"]
    style = human.style_for(ctx.stdout, ctx.environ, ctx.args)
    answers = {}
    for setting in [s for s in registry.SETTINGS if s.grade == 1 and not s.is_pattern]:
        choices, other = _choices(setting)
        default = cfgmod.show(cfg.get(setting.key))
        if default not in choices and not other:
            default = choices[0] if choices else ""
        while True:
            raw = asking.ask_one(ctx.stdin, ctx.stdout, style, f"{setting.key} · {_(setting.help)}",
                                 choices, default, other)
            try:
                value = cfgmod.check_value(setting, cfgmod.parse_text(setting, raw))
                break
            except ValueError:
                ctx.stdout.write("  " + _("invalid value {value} for {key}; allowed: {allowed}").format(
                    value=repr(raw), key=setting.key, allowed=setting.describe_values()) + "\n")
        answers[setting.key] = value
    for key, value in answers.items():   # written once every answer is in: Ctrl+C writes nothing
        tomlfile.set_value(path, key, value)
    r = Result("OK", {"FILE": path, "SETTINGS": len(answers)})
    for key, value in answers.items():
        r.data(key, cfgmod.show(value))
    return r


def _editor(environ):
    """``VISUAL``, ``EDITOR``, else Notepad on Windows and ``vi`` elsewhere."""
    import shlex

    chosen = environ.get("VISUAL") or environ.get("EDITOR")
    if chosen:
        return shlex.split(chosen, posix=os.name != "nt")
    return ["notepad"] if os.name == "nt" else ["vi"]


def _run_editor(command, path):
    import subprocess

    return subprocess.call(command + [path])


def edit(ctx):
    """Opens the settings file in an editor, then validates every layer."""
    layer, path = _target(ctx)
    if not os.path.exists(path):
        tomlfile.set_value(path, "schema", 1, header=USER_HEADER if layer == "user" else None)
    code = _run_editor(_editor(ctx.environ), path)
    after = cfgmod.load(_project(ctx), ctx.environ, ctx.args.harness_options, args=ctx.arg_settings, strict=False)
    if after.problems:
        return Result("FAIL", {"REASON": "config", "FILE": path, "ERRORS": len(after.problems)}, after.problems,
                      exit_code=EXIT_USAGE)
    r = Result("WARN" if after.warnings or code else "OK", {"FILE": path, "LAYER": layer, "EDITOR_EXIT": code},
               after.warnings)
    if not after.warnings:
        r.line(_("every layer is valid"))
    return r


def grade(ctx):
    """Sets the grade, and lists the settings the new grade shows that the old one hid."""
    cfg = ctx.config if not ctx.args.user else cfgmod.load(_project(ctx), ctx.environ, strict=False)
    old = cfg.grade
    new = registry.GRADE_NUMBERS[ctx.args.new_grade]
    layer, path = _target(ctx)
    tomlfile.set_value(path, "grade", ctx.args.new_grade, header=USER_HEADER if layer == "user" else None)
    shown = [k for k in cfg.keys(new) if k not in cfg.keys(old)]
    r = Result("OK", {"GRADE": ctx.args.new_grade, "WAS": registry.GRADES[old], "LAYER": layer, "FILE": path,
                      "NEW_SETTINGS": len(shown)})
    for key in shown:
        r.data(key, cfgmod.show(cfg.get(key)))
    if new < old:
        r.line(_("the settings above this grade keep their values, and still take effect"))
    return r


def diff(ctx):
    """The settings whose value differs from the default, with the layer that sets them."""
    cfg = ctx.config
    rows = []
    for key in sorted(cfg.values):
        origin = cfg.origin(key)
        if origin.layer == "default":
            continue
        default = registry.default_of(key)
        value = cfg.get(key)
        if value == default:
            continue
        rows.append({"key": key, "value": cfgmod.show(value), "default": cfgmod.show(default),
                     "layer": origin.layer, "source": str(origin.source)})
    order = {layer: n for n, layer in enumerate(cfgmod.LAYERS)}
    rows.sort(key=lambda x: (order.get(x["layer"], 9), x["key"]))
    r = Result("OK", {"CHANGED": len(rows)})
    for x in rows:
        r.data(x["key"], f"{x['value']} (default {x['default']}) from {x['layer']}")
    r.table("diff", rows)
    r.view = "config-diff"
    return r


def roles(ctx):
    """agent-models R2: the seven agent roles, the model and the effort in effect for each, and the layer
    that sets it (``default``: the agent's own header; ``research``: the research's --model or --effort)."""
    from probandia import roles as agent_roles
    from probandia.errors import ProbandiaError

    cfg = _config(ctx)
    run = None
    project = _project(ctx)
    if project is not None:
        from probandia.research import find_research

        try:
            run = (find_research(project, fallback=True).meta() or {}).get("run")
        except ProbandiaError:
            run = None
    table = agent_roles.resolve(cfg, run)
    r = Result("OK", {"ROLES": len(table), "CHOSEN": sum(1 for e in table.values() if agent_roles.chosen(e))})
    rows = []
    for role, e in table.items():
        r.data(role, f"{e['model']} {e['effort']} ({e['model_from']}, {e['effort_from']})")
        rows.append({"role": role, "model": e["model"], "model_from": e["model_from"],
                     "effort": e["effort"], "effort_from": e["effort_from"]})
        for field, value in agent_roles.chosen(e).items():
            for line in agent_roles.warnings(role, field, value):
                r.status = "WARN"
                r.line(_("{role}: {warning}").format(role=role, warning=line))
    r.table("roles", rows, ["role", "model", "model_from", "effort", "effort_from"])
    r.line(_("change one with: config set roles.<role>.model <model> (or .effort <level>); in Claude Code the "
             "guard applies it to each launch of the agent"))
    return r


# help settings: what each layer of cfgmod.LAYERS is, how it is written; what makes a provider usable
# (catalogue.why_unusable, by its reason); where keys are read (envfile, keys_cmd.rows)
LAYER_HELP = {"arg": (N_("the option of a command, for one call"), "--lang, --effort…"),
              "env": (N_("the environment variable PROBANDIA_<KEY>"), "PROBANDIA_REPORT_MODE=living"),
              "local": (N_("the project's local settings, not versioned"), "config set <key> <value> --local"),
              "project": (N_("the project's settings"), "config set <key> <value>"),
              "user": (N_("your settings, for every project"), "config set <key> <value> --user"),
              "harness": (N_("the plugin's options, which only the harness writes"), '--harness-options "k=v;…"'),
              "default": (N_("the registry's default"), "")}
CONDITIONS = (("not-enabled", N_("it is in providers.enabled")),
              ("not-enabled", N_("it is not in providers.disabled")),
              ("card-required", N_("if its free tier requires a card, providers.allow_card_required is true")),
              ("content-reuse", N_("if it may reuse the content sent to it, providers.allow_content_reuse is true")),
              ("no-key", N_("its key is found")))
KEY_PLACES = (("environment", N_("the environment variable, which wins")),
              ("project", N_("the project's .env, next to probandia.toml")),
              ("user", N_("your .env, next to config.toml")))


def reference(ctx):
    """``help settings``: every setting of the registry, the seven layers, the conditions of a provider,
    where keys are read, the variables that are not settings and the common options: what
    docs/parameters.md shows, read from the code. Works outside a project."""
    from probandia import cli
    from probandia.util import envfile

    project = _project(ctx)
    paths = cfgmod.layer_paths(project, ctx.environ)
    settings = []
    for s in registry.SETTINGS:
        default = _("per key") if callable(s.default) else cfgmod.show(s.default)
        settings.append({"key": s.key, "domain": s.key.split(".")[0], "grade": registry.GRADES[s.grade],
                         "type": s.type, "default": default, "values": s.describe_values(),
                         "variable": ", ".join((s.env, *s.env_aliases)), "option": s.flag or "", "help": _(s.help)})
    assert set(LAYER_HELP) == set(cfgmod.LAYERS)
    layers = [{"order": n, "layer": layer, "what": _(LAYER_HELP[layer][0]), "file": paths.get(layer, ""),
               "how": LAYER_HELP[layer][1]} for n, layer in enumerate(reversed(cfgmod.LAYERS), 1)]
    files = dict(zip(("user", "project"), envfile.files(ctx.environ, project)))
    keys = [{"order": n, "source": source, "what": _(text), "file": files.get(source, "")}
            for n, (source, text) in enumerate(KEY_PLACES, 1)]
    options = [{"option": ", ".join(a.option_strings) + (f" {a.metavar}" if a.metavar else ""), "what": a.help}
               for a in cli._global_options()._actions if a.option_strings]
    r = Result("OK", {"SETTINGS": len(settings), "LAYERS": len(layers), "CONDITIONS": len(CONDITIONS),
                      "VARIABLES": len(registry.OTHER_VARIABLES), "OPTIONS": len(options)})
    r.line(_("PROBANDIA_ENV_FILES names other .env files; a key is never shown"))
    r.table("settings", settings)
    r.table("layers", layers)
    r.table("conditions", [{"condition": _(text), "reason": reason} for reason, text in CONDITIONS])
    r.table("keys", keys)
    r.table("variables", [{"variable": v, "what": _(registry.VARIABLE_HELP[v])} for v in registry.OTHER_VARIABLES])
    r.table("options", options)
    return r


def theme(ctx):
    """The themes of probandia tui (``config.themes``): listed, saved or deleted. They live outside
    any project, in the user's configuration folder."""
    return {"list": theme_list, "save": theme_save, "delete": theme_delete}[ctx.args.theme_action](ctx)


def _in_use(ctx):
    return cfgmod.load(_project(ctx), ctx.environ, strict=False).get("tui.theme") or "dark"


def theme_list(ctx):
    from probandia.config import themes

    found, problems = themes.load(ctx.environ)
    in_use = _in_use(ctx)
    r = Result("WARN" if problems or in_use not in found else "OK",
               {"THEMES": len(found), "IN_USE": in_use, "FOLDER": themes.folder(ctx.environ)})
    rows = []
    for name, t in found.items():
        rows.append({"theme": name, "kind": "builtin" if t["builtin"] else "user", "base": t["base"],
                     "in_use": name == in_use, "file": t["file"] or "", "problems": len(problems.get(name, []))})
        r.line((_("{theme} ({base}), in use") if name == in_use else _("{theme} ({base})")).format(
            theme=name, base=t["base"]))
    for name, found_problems in problems.items():
        for problem in found_problems:
            r.line(_("{theme}: {problem}").format(theme=name, problem=problem))
    if in_use not in found:
        r.line(_("tui.theme names {theme}, which is not a theme: the application shows dark").format(theme=in_use))
    r.table("themes", rows, ["theme", "kind", "base", "in_use", "file", "problems"])
    return r


def theme_save(ctx):
    from probandia.config import themes

    changes = []
    for item in ctx.args.changes:
        key, eq, value = item.partition("=")
        if not eq:
            raise UsageError(_("--set takes <key>=<value>, not {item}").format(item=item))
        changes.append((key.strip(), value.strip()))
    try:
        saved, path, replaced = themes.save(ctx.args.name, ctx.args.base, ctx.args.start, changes, ctx.environ)
    except ValueError as err:
        raise UsageError(str(err))
    r = Result("OK", {"THEME": saved["name"], "BASE": saved["base"], "FILE": path, "REPLACED": replaced})
    r.line((_("replaced {path}") if replaced else _("wrote {path}")).format(path=path))
    if _in_use(ctx) != saved["name"]:
        r.line(_("use it with: config set --user tui.theme {theme}").format(theme=saved["name"]))
    return r


def theme_delete(ctx):
    from probandia.cli import asking
    from probandia.config import themes

    name = ctx.args.name
    try:
        themes.check_name(name)
    except ValueError as err:
        raise UsageError(str(err))
    path = themes.path_of(name, ctx.environ)
    if not os.path.isfile(path):
        return Result("WARN", {"THEME": name, "FILE": path}, [_("no theme of yours named {theme}").format(theme=name)])
    if not asking.confirm(ctx, _("Delete the theme {theme}? Its file is removed.").format(theme=name)):
        return asking.declined({"THEME": name})
    themes.delete(name, ctx.environ)
    r = Result("OK", {"THEME": name, "FILE": path}, [_("removed {path}").format(path=path)])
    if _in_use(ctx) == name:
        r.status = "WARN"
        r.line(_("tui.theme still names it: the application shows dark until you choose another"))
    return r
