"""The table of commands, each with its arguments and its handler.

A command that needs a project checks for one first, so outside a project it
exits with code 6.
"""

import importlib

from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import N_, _
from probandia.util.locks import Locks

def _resolve(target):
    """A function, or ``"<module>.<name>"`` of ``probandia.cli``, imported only when the command runs (T145):
    a launch loads its own command, not the 26 others."""
    if not isinstance(target, str):
        return target
    module, name = target.split(".")
    return getattr(importlib.import_module("probandia.cli." + module), name)


def _index_args(kind):
    return lambda p, common: _resolve("browse_cmd.index_args")(kind)(p, common)


class Command:
    def __init__(self, name, help, configure, handler, engine=False, needs_project=True,
                 own_harness=False, slash=None):
        self.name = name
        # a user command has its slash command (commands/<name>.md), unless it only serves a terminal
        self.slash = (not engine) if slash is None else slash
        self.own_harness = own_harness  # the command defines its own --harness
        self.help = help  # message id, translated when the parser is built
        self.engine = engine
        self.needs_project = needs_project
        self._configure = configure
        self.handler = handler

    def configure(self, parser, common):
        _resolve(self._configure)(parser, common)

    def run(self, ctx):
        if self.needs_project:
            ctx.project  # raises NotInProject (exit 6)
        return _resolve(self.handler)(ctx)


# lock


def _lock_args(p, common):
    p.add_argument("action", choices=("take", "renew", "release", "status", "list"))
    p.add_argument("scope", nargs="?", help=_("research:<id>, family:<id> or browser"))
    p.add_argument("--expired", action="store_true",
                   help=_("release: only an expired lock, left by a crash; never a live one"))


def _lock_list(ctx, locks):
    """lock list (cli.md 5.6.8): every lock, live or expired."""
    import os

    folder = os.path.join(ctx.project, ".probandia", "locks")
    rows = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            info, expired = locks.status(name[:-5])
            if info is not None:
                d = locks.describe(name[:-5], info)
                rows.append({"scope": name[:-5], "state": "expired" if expired else "held",
                             "holder": d["HOLDER"], "expires": d["EXPIRES"]})
    r = Result("OK", {"LOCKS": len(rows), "EXPIRED": sum(1 for x in rows if x["state"] == "expired")})
    for x in rows:
        r.data("lock", f"{x['scope']} {x['state']} {x['holder']} until {x['expires']}")
    r.table("locks", rows)
    return r


def _lock(ctx):
    locks = Locks(ctx.project, expiry_minutes=ctx.config.get("locks.expiry_minutes"))
    if ctx.args.action == "list":
        return _lock_list(ctx, locks)
    scope = ctx.args.scope
    if not scope:
        raise UsageError(_("lock {action} needs a scope: research:<id>, family:<id> or browser").format(
            action=ctx.args.action))
    from probandia.cli.data_cmd import actor

    me = actor(ctx)  # the detected harness, as every other writer records it
    owner = {"harness": me["harness"], "session": me["session"], "agent": me["agent"]}
    action = ctx.args.action
    if action == "release" and ctx.args.expired:
        info, expired = locks.status(scope)
        if info is None:
            return Result("OK", {"LOCK": scope, "STATE": "free"})
        if not expired:
            raise locks._held(scope, info)
        locks.release(scope, info.get("owner"))
        return Result("OK", {"LOCK": scope, "STATE": "released"})
    if action == "status":
        info, expired = locks.status(scope)
        if info is None:
            return Result("OK", {"LOCK": scope, "STATE": "free"})
        r = Result("OK", locks.describe(scope, info))
        r.set("STATE", "expired" if expired else "held")
        r.set("MINE", info.get("owner") == owner)
        return r
    if action == "take":
        info = locks.take(scope, owner)
    elif action == "renew":
        info = locks.renew(scope, owner)
    else:
        removed = locks.release(scope, owner)
        return Result("OK", {"LOCK": scope, "STATE": "released" if removed else "free"})
    r = Result("OK", locks.describe(scope, info))
    r.set("STATE", "held")
    return r


# hook and mcp: they speak to the harness, not to a person, so they print no
# output contract. A handler that returns None prints nothing and exits 0.


def _hook_args(p, common):
    p.add_argument("function", help=_("guard, digest, log or verify"))


def _hook(ctx):
    import sys

    from probandia import hooks

    text = hooks.run(ctx.args.function, environ=ctx.environ, harness=ctx.args.harness)
    if text:
        sys.stdout.write(text)
    return None


def _mcp_args(p, common):
    pass


def _mcp(ctx):
    from probandia import mcp

    mcp.serve(environ=ctx.environ, cwd=ctx.cwd)
    return None


def _install_args(p, common):
    p.add_argument("--harness", dest="target", required=True, choices=("opencode", "codex", "codex-agents"),
                   help=_("where to install"))
    p.add_argument("--scope", choices=("user", "project"), default="user",
                   help=_("for OpenCode: the user's configuration, or the current project"))
    p.add_argument("--path", default=None, help=_("the project folder (default: the current folder)"))
    p.add_argument("--uninstall", action="store_true", help=_("remove what the install wrote"))


def _install(ctx):
    import os

    from probandia import install

    folder = os.path.abspath(ctx.args.path or ctx.cwd)
    if not ctx.args.uninstall:
        from probandia.install import convert

        convert.plugin_root()   # a refusal, before anything is written, from a wheel
    if ctx.args.target in ("codex", "codex-agents"):
        record_dir = os.path.join(folder, ".codex")
        if ctx.args.uninstall:
            removed, restored = install.uninstall(record_dir)
            return Result("OK", {"TARGET": ctx.args.target, "REMOVED": removed, "RESTORED": restored})
        inst = (install.install_codex(folder) if ctx.args.target == "codex"
                else install.install_codex_agents(folder))
    else:
        from probandia.install import opencode

        record_dir = opencode.record_dir(ctx.args.scope, folder, ctx.environ)
        if ctx.args.uninstall:
            removed, restored = install.uninstall(record_dir)
            return Result("OK", {"TARGET": "opencode", "REMOVED": removed, "RESTORED": restored})
        inst = opencode.install(ctx.args.scope, folder, ctx.environ)
    r = Result("OK", {"TARGET": ctx.args.target, "WRITTEN": len(inst.written),
                      "CHANGED": len(inst.backups)})
    for path in inst.written + [p for p, _b in inst.backups]:
        r.line(_("wrote {path}").format(path=path))
    if inst.notes:
        r.set("NOT_WRITTEN", len(inst.notes))
    for note in inst.notes:
        r.line(note)
    return r


def _manifests_args(p, common):
    p.add_argument("action", choices=("generate", "check"))


def _manifests(ctx):
    from probandia.install import manifests

    if ctx.args.action == "generate":
        changed = manifests.generate()
        r = Result("OK", {"CHANGED": len(changed)})
        for rel in changed:
            r.line(_("wrote {path}").format(path=rel))
        return r
    stale = manifests.check()
    if stale:
        r = Result("FAIL", {"REASON": "stale-manifests", "STALE": len(stale)})
        for rel in stale:
            r.line(_("out of date: {path}").format(path=rel))
        r.line(_("run: manifests generate"))
        return r
    return Result("OK", {"STALE": 0})


def _no_args(p, common):
    pass


def _id_args(p, common):
    p.add_argument("action", choices=("new",))
    p.add_argument("--prefix", help=_("a prefix in lowercase letters, such as src: src-<ULID>"))


def _id(ctx):
    """``id new [--prefix src]`` (token-economy B5): a new identifier, without guessing its form."""
    import re

    from probandia.util.ids import ulid

    prefix = ctx.args.prefix
    if prefix and not re.fullmatch(r"[a-z]+", prefix):
        raise UsageError(_("a prefix is made of lowercase letters, such as src"))
    return Result("OK", {"ID": f"{prefix}-{ulid()}" if prefix else ulid()})


def _help_args(p, common):
    from probandia.cli.helptext import TOPICS

    p.add_argument("subject", nargs="?", choices=[*TOPICS, "settings"], help=_("the subject"))


def _help(ctx):
    from probandia.cli.helptext import TOPICS

    subject = ctx.args.subject
    if subject is None:
        subjects = [*TOPICS, "settings"]
        r = Result("OK", {"SUBJECTS": len(subjects)})
        for name in subjects:
            r.line(_("probandia help {subject}").format(subject=name))
        return r.table("subjects", [{"subject": name} for name in subjects], hidden=True)
    if subject == "settings":   # every setting, the layers, the providers' conditions, the keys, the variables
        from probandia.cli import config_cmd

        return config_cmd.reference(ctx)
    lines = [_(line) for line in TOPICS[subject]]
    return Result("OK", {"SUBJECT": subject}, lines).table("lines", [{"line": x} for x in lines], hidden=True)


def _init_args(p, common):
    from probandia.cli import config_cmd

    p.add_argument("--grade", dest="init_grade", choices=config_cmd.GRADE_CHOICES, default="essential",
                   help=_("settings written uncommented"))


def _init(ctx):
    """config init, then, at a terminal, the questions of config wizard."""
    from probandia.cli import config_cmd

    r = config_cmd.init(ctx)
    if getattr(ctx, "asks", False) and r.status == "OK":
        answered = config_cmd.wizard(ctx, r.values["PROJECT"])
        r.set("SETTINGS", answered.values["SETTINGS"])
    return r


def _completion_args(p, common):
    from probandia.cli.completion import SCRIPTS

    p.add_argument("shell", choices=tuple(SCRIPTS))


def _completion(ctx):
    from probandia.cli.completion import SCRIPTS

    r = Result("OK", {"SHELL": ctx.args.shell})
    r.raw = SCRIPTS[ctx.args.shell]
    return r


def _doctor(ctx):
    from probandia import doctor

    from probandia.cli.providers_cmd import _config

    return doctor.run(ctx.args.harness, ctx.environ, config=_config(ctx))   # the user's layers outside a project


def _tui_args(p, common):
    """``tui --help`` describes the application: its screens, their keys, the palette and the console (T108)."""
    from probandia.cli.tui_cmd import about

    p.description += "\n\n" + about()


def _tui(ctx):
    from probandia.cli import tui_cmd

    return tui_cmd.run(ctx)


COMMANDS = [
    # user commands
    Command("new", N_("create a research and run its first pass"), needs_project=False,
            configure="lifecycle_cmd.new_args", handler="lifecycle_cmd.new"),
    Command("resume", N_("run the next pass of a research"),
            configure="lifecycle_cmd.resume_args", handler="lifecycle_cmd.resume"),
    Command("fork", N_("copy a research at a pass and continue it separately"),
            configure="lifecycle_cmd.fork_args", handler="lifecycle_cmd.fork_cmd"),
    Command("verify", N_("check a research against the proof rules"),
            configure="lifecycle_cmd.verify_args", handler="lifecycle_cmd.verify_cmd"),
    Command("question", N_("the questions of a research: list, add, edit, answer, unresolved, reopen"),
            configure="question_cmd.question_args", handler="question_cmd.question"),
    Command("matrix", N_("the source types each question expects, consulted or still to do; justify"),
            configure="matrix_cmd.matrix_args", handler="matrix_cmd.matrix_cmd"),
    # T248: a person records what they looked at; an agent never runs it, so it has no slash command
    Command("fact", N_("check: record that you looked at the record a fact rests on, at your terminal"),
            configure="fact_cmd.fact_args", handler="fact_cmd.fact", slash=False),
    Command("close", N_("close a research once its questions are settled and verify has run"),
            configure="lifecycle_cmd.close_args", handler="lifecycle_cmd.close_cmd"),
    Command("status", N_("families, researches, passes, locks, quotas"),
            configure="lifecycle_cmd.status_args", handler="lifecycle_cmd.status_cmd"),
    Command("report", N_("the report of a research: open it in the browser, show it, render it"),
            configure="report_cmd.report_args", handler="report_cmd.report", slash=False),
    Command("tree", N_("write the family tree (html or md)"),
            configure="export_cmd.tree_args", handler="export_cmd.tree"),
    Command("export", N_("export GEDCOM 7, GEDCOM 5.5.1 or Gramps Web"),
            configure="export_cmd.export_args", handler="export_cmd.export"),
    Command("config", N_("the settings: show, explain, set, unset, init, validate, path, wizard, edit, grade, diff, roles, theme"),
            needs_project=False, configure="config_cmd.configure", handler="config_cmd.run"),
    Command("quota", N_("show, sync, add or estimate free-tier usage"),
            configure="search_cmd.quota_args", handler="search_cmd.quota"),
    Command("doctor", N_("check the harness, keys, Python and optional tools"), needs_project=False,
            configure=_no_args, handler=_doctor),
    Command("library", N_("the learned scripts: find, save, test, trust, list, show, run, promote, demote, draft, install, "
                                      "uninstall, export, import"),
            configure="library_cmd.library_args", handler="library_cmd.library"),
    Command("memory", N_("the decisions kept in AGENTS.md: add, list, remove, sync"), needs_project=False,
            configure="memory_cmd.memory_args", handler="memory_cmd.memory"),
    Command("template", N_("the report templates: list, show, check, import, export, use, designer"),
            needs_project=False, configure="template_cmd.template_args", handler="template_cmd.template"),
    Command("import", N_("import a workshop in its own format: commun/personnes.yaml, its reports and collectors"),
            configure="lifecycle_cmd.import_args", handler="lifecycle_cmd.import_cmd"),
    Command("import-gedcom", N_("import a GEDCOM file into the staging area"),
            configure="export_cmd.import_gedcom_args", handler="export_cmd.import_gedcom"),
    Command("usage", N_("the free tiers account by account: what is left, what it pays for, when it starts again"),
            needs_project=False, configure="usage_cmd.usage_args", handler="usage_cmd.usage", slash=False),
    Command("cache", N_("what the cache of responses holds and saves the quotas: stats, clear"),
            configure="cache_cmd.configure", handler="cache_cmd.run", slash=False),
    Command("help", N_("short pages: quotas, negatives, grades, exit codes, project files"),
            needs_project=False, configure=_help_args, handler=_help, slash=False),
    Command("completion", N_("the Tab completion script of a shell"), needs_project=False,
            configure=_completion_args, handler=_completion, slash=False),
    Command("init", N_("create a project here; at a terminal, ask its essential settings"), needs_project=False,
            configure=_init_args, handler=_init, slash=False),
    Command("keys", N_("the API keys: list where they come from, check, set, unset, signup"), needs_project=False,
            configure="keys_cmd.configure", handler="keys_cmd.run", slash=False),
    Command("providers", N_("the free-tier catalogue: list, show, stale, enable, disable"), needs_project=False,
            configure="providers_cmd.configure", handler="providers_cmd.run", slash=False),
    Command("research", N_("the researches: list, show, log, pause, close, reopen"),
            configure="browse_cmd.research_args", handler="browse_cmd.research", slash=False),
    Command("family", N_("the families: list, show"),
            configure="browse_cmd.family_args", handler="browse_cmd.family", slash=False),
    Command("find", N_("find a person in every family, with the spelling variants"),
            configure="browse_cmd.find_args", handler="browse_cmd.find", slash=False),
    Command("person", N_("a person's file: facts and sources, relatives, hypotheses, negatives, gaps"),
            configure="browse_cmd.person_args", handler="browse_cmd.person", slash=False),
    Command("searches", N_("what was already searched, where, and what it found"),
            configure=_index_args("searches"), handler="browse_cmd.index_list", slash=False),
    Command("sources", N_("the sources of the families, with their citations"),
            configure=_index_args("sources"), handler="browse_cmd.index_list", slash=False),
    Command("negatives", N_("the negative searches, and whether to check them again"),
            configure=_index_args("negatives"), handler="browse_cmd.index_list", slash=False),
    Command("hypotheses", N_("the hypotheses of the families, open and closed"),
            configure=_index_args("hypotheses"), handler="browse_cmd.index_list", slash=False),
    Command("gaps", N_("the gaps in the archives: registers lost or not filmed"),
            configure=_index_args("gaps"), handler="browse_cmd.index_list", slash=False),
    Command("proposals", N_("the proposals waiting: list, show, apply, drop"),
            configure="browse_cmd.proposals_args", handler="browse_cmd.proposals", slash=False),
    Command("board", N_("where you stand, in one look: the research in focus and its pass, quotas, alerts"),
            needs_project=False, configure="board_cmd.board_args", handler="board_cmd.board_cmd", slash=False),
    Command("statusline", N_("one line for the status bar of Claude Code: research, pass, web searches, quota"),
            needs_project=False, configure="board_cmd.statusline_args", handler="board_cmd.statusline", slash=False),
    Command("tui", N_("the application in a terminal: its screens, the palette and the console"),
            needs_project=False, configure=_tui_args, handler=_tui,
            slash=False),
    # engine commands
    Command("watch", N_("replay the archives' witnesses and list the stale catalogue entries"),
            needs_project=False, configure="watch_cmd.watch_args", handler="watch_cmd.watch"),
    Command("plan", N_("axes and estimate of the next pass"), engine=True,
            configure="search_cmd.plan_args", handler="search_cmd.plan"),
    Command("known", N_("facts, negatives, hypotheses and gaps already known"), engine=True,
            configure="data_cmd.known_args", handler="data_cmd.known"),
    Command("correlate", N_("conflicting evidence and its analyses: list, open, resolve, diverge"), engine=True,
            configure="correlate_cmd.correlate_args", handler="correlate_cmd.correlate"),
    Command("proof", N_("proof arguments and their review: list, show, draft, submit, review, answer, accept"),
            engine=True, configure="proof_cmd.proof_args", handler="proof_cmd.proof"),
    Command("search", N_("provider search, written to the search log"), engine=True,
            configure="search_exec.search_args", handler="search_exec.search"),
    Command("login", N_("where a session the user opens in the browser stands: check, confirm, skip"),
            engine=True, configure="login_cmd.login_args", handler="login_cmd.login"),
    Command("browser", N_("login: open the local browser for you to sign in to an archive"), slash=False,
            configure="login_cmd.browser_args", handler="login_cmd.browser"),
    Command("read", N_("read a page through the reading ladder"), engine=True,
            configure="reading_cmd.read_args", handler="reading_cmd.read"),
    Command("archive", N_("the archives' connectors: find or run an operation, list, coverage, stale"), engine=True,
            configure="archive_cmd.archive_args", handler="archive_cmd.archive"),
    Command("transcribe", N_("a record's transcription: template, check, quote, ocr, new, compare"), engine=True,
            configure="export_cmd.transcribe_args", handler="export_cmd.transcribe"),
    Command("image", N_("a sheet of views, a crop or a rotate by a quarter turn, with what reading it costs"), engine=True,
            needs_project=False, configure="image_cmd.image_args", handler="image_cmd.image"),
    Command("dates", N_("parse and convert genealogical dates"), engine=True, needs_project=False,
            configure="lang_cmd.dates_args", handler="lang_cmd.dates"),
    Command("variants", N_("spelling variants of a surname"), engine=True, needs_project=False,
            configure="lang_cmd.variants_args", handler="lang_cmd.variants"),
    Command("places", N_("historical place names"), engine=True, needs_project=False,
            configure="lang_cmd.places_args", handler="lang_cmd.places"),
    Command("cite", N_("citation sentence of a source"), engine=True, needs_project=False,
            configure="data_cmd.cite_args", handler="data_cmd.cite"),
    Command("id", N_("a new identifier, such as src-<ULID> for a source to come"), engine=True,
            needs_project=False, configure=_id_args, handler=_id),
    Command("workshop", N_("the workshop the project lives in: status, diff, push, pull, link a research to one of its reports"), engine=True,
            configure="workshop_cmd.workshop_args", handler="workshop_cmd.workshop"),
    Command("propose", N_("validate and store a proposal"), engine=True,
            configure="data_cmd.propose_args", handler="data_cmd.propose"),
    Command("apply", N_("accept or reject a proposal as a whole"), engine=True,
            configure="data_cmd.apply_args", handler="data_cmd.apply"),
    Command("event", N_("append an event to a research, or check the log"), engine=True,
            configure="data_cmd.event_args", handler="data_cmd.event"),
    Command("render", N_("render the report of a research"), engine=True,
            configure="report_cmd.render_args", handler="report_cmd.render"),
    Command("digest", N_("the state digest of a research"), engine=True,
            configure="lifecycle_cmd.digest_args", handler="lifecycle_cmd.digest_cmd"),
    Command("pass", N_("the open pass of a research: end it, or its status"), engine=True,
            configure="lifecycle_cmd.pass_args", handler="lifecycle_cmd.pass_cmd"),
    Command("volet", N_("open a volet, a group of passes, or list them"), engine=True,
            configure="lifecycle_cmd.volet_args", handler="lifecycle_cmd.volet_cmd"),
    Command("team", N_("a team: its wave, its search budget, send and inbox for its messages"), engine=True,
            configure="lifecycle_cmd.team_args", handler="lifecycle_cmd.team_cmd"),
    Command("lock", N_("the locks: take, renew, release, status, list"), engine=True,
            configure=_lock_args, handler=_lock),
    Command("manifests", N_("generate or check the harness manifests"), engine=True,
            needs_project=False, configure=_manifests_args, handler=_manifests),
    Command("install", N_("install into a harness"), engine=True,
            needs_project=False, configure=_install_args, handler=_install, own_harness=True),
    Command("mcp", N_("run the MCP server over stdio"), engine=True, needs_project=False,
            configure=_mcp_args, handler=_mcp),
    Command("hook", N_("entry point of the harness hooks"), engine=True, needs_project=False,
            configure=_hook_args, handler=_hook),
]

COMMAND_NAMES = [c.name for c in COMMANDS]
