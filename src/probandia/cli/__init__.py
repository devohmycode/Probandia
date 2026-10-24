"""Command-line interface of the engine.

``python run_probandia.py <command> [options]``, ``probandia <command>`` or
``python -m probandia <command>``. Every command answers with the output
contract of ``probandia.cli.output`` and exits with one of the codes of
``probandia.errors``.
"""
import argparse
import os
import re
import sys

from probandia import __version__, i18n
from probandia.cli.output import Result
from probandia.errors import EXIT_INTERNAL, AmbiguousResearch, NotInProject, ProbandiaError, UsageError
from probandia.i18n import N_, _
from probandia.project import find_project

# T114: argparse's own words in the help, in the language of the messages; its error messages stay
# in English, which Parser.error reads
ARGPARSE_WORDS = frozenset((N_("usage: "), N_("options"), N_("positional arguments"), N_("%(heading)s:"),
                            N_("show this help message and exit"), N_("show program's version number and exit")))
argparse._ = lambda message: _(message) if message in ARGPARSE_WORDS else message

HARNESSES = ("claude-code", "codex", "cursor", "droid", "grok", "antigravity", "opencode", "cli")
OUTPUT_FORMATS = ("human", "contract", "json")
KEEPS_RESEARCH = ("new", "fork", "resume", "research")   # the commands that create or pick the research
# the commands that read the providers' balances when due (cli.search_cmd.auto_sync), kept here so that
# no other command imports it
# the commands the harness runs by itself, many times a minute, never an agent (token-economy H2)
NOT_COUNTED = ("statusline",)
SYNC_COMMANDS = ("new", "resume", "plan", "search", "read", "archive")

# Shortcuts at the root (decision D-5): each is rewritten into its command before
# parsing, so ``probandia -s --family x`` is ``probandia status --family x``.
# A shortcut may stand for a command and its action: ``-r x`` is ``report open x``.
SHORTCUTS = {"-s": "status", "--status": "status", "-u": "usage", "--usage": "usage",
             "-r": "report open", "--report": "report open"}
VALUE_OPTIONS = ("--project", "-p", "--lang", "-l", "--harness", "--agent", "--harness-options",
                 "--output-format", "--width")
FLAG_OPTIONS = ("--json", "--quiet", "-q", "--plain", "--no-color", "--yes", "-y")
SHORT_OPTIONS = ("-h", "-V", "-p", "-l", "-q", "-y")


def _commands():
    """The table of commands, imported at its first use: ``statusline`` answers from its kept line
    before (T146)."""
    import importlib

    return importlib.import_module("probandia.cli.commands")   # not ``from``: it would call __getattr__


def __getattr__(name):   # ``cli.commands`` for the callers that read it as an attribute
    if name == "commands":
        return _commands()
    raise AttributeError(name)


class Parser(argparse.ArgumentParser):
    """An argument parser that reports errors through the output contract."""

    def error(self, message):
        hint = []
        m = re.search(r"invalid choice: '([^']*)' \(choose from (.*)\)", message)
        if m:
            from probandia.suggest import lines

            hint = lines(m.group(1), re.findall(r"'?([\w-]+)'?", m.group(2)))
        raise UsageError(_("{prog}: {message}").format(prog=self.prog, message=message),
                         lines=hint + [_("see: {prog} --help").format(prog=self.prog)])


def _global_options(harness=True):
    """Global options, accepted before or after the command name. ``install``
    takes them without ``--harness``, which it uses for its own target."""
    p = Parser(add_help=False)
    g = p.add_argument_group(_("global options"))
    s = argparse.SUPPRESS
    g.add_argument("-p", "--project", metavar="<path>", default=s, help=_("project root"))
    g.add_argument("-l", "--lang", metavar="<tag>", default=s, help=_("output language (BCP-47)"))
    g.add_argument("--json", action="store_true", default=s, help=_("machine output: one JSON object"))
    g.add_argument("--output-format", choices=OUTPUT_FORMATS, default=s,
                   help=_("human (readable), contract (for agents) or json"))
    g.add_argument("--plain", action="store_true", default=s,
                   help=_("readable output without colours or box characters"))
    g.add_argument("--no-color", action="store_true", default=s, help=_("readable output without colours"))
    g.add_argument("--width", type=int, metavar="<n>", default=s, help=_("width of the readable output"))
    if harness:
        g.add_argument("--harness", choices=HARNESSES, default=s, help=_("the calling harness"))
    g.add_argument("--agent", metavar="<role>", default=s,
                   help=_("the calling role (default: session)"))
    g.add_argument("--harness-options", metavar='"<k=v;...>"', default=s,
                   help=_("settings passed by the harness"))
    g.add_argument("-q", "--quiet", action="store_true", default=s,
                   help=_("print only STATUS and DETAILS"))
    g.add_argument("-y", "--yes", action="store_true", default=s,
                   help=_("answer yes to the confirmations"))
    return p


GLOBAL_DEFAULTS = {"project": None, "lang": None, "json": False, "harness": "cli",
                   "agent": "session", "harness_options": None, "quiet": False, "output_format": None,
                   "plain": False, "no_color": False, "width": None, "yes": False}


def build_parser(only=None):
    """The parser of every command; with ``only``, of that command alone, so that a launch imports
    no other command module (T145). ``only=""`` adds none: ``--version``."""
    common = _global_options()
    common_without_harness = _global_options(harness=False)
    parser = Parser(
        prog="probandia",
        parents=[common],
        description=_("Probandia: nothing is concluded until it is proven."),
        epilog=_("Commands marked [engine] are called by skills, agents and the MCP server."),
    )
    parser.add_argument("-V", "--version", action="version", version=f"probandia {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", title=_("commands"))
    sub.required = True
    for spec in _commands().COMMANDS:
        if only is not None and spec.name != only:
            continue
        label = ("[engine] " if spec.engine else "") + _(spec.help)
        parent = common_without_harness if spec.own_harness else common
        from probandia.cli.helptext import examples_epilog

        p = sub.add_parser(spec.name, parents=[parent], help=label, description=label,
                           epilog=examples_epilog(spec.name),
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        spec.configure(p, common)
        p.set_defaults(_spec=spec)
    return parser


class Context:
    """What a command handler receives."""

    def __init__(self, args, environ=None, cwd=None):
        self.args = args
        self.environ = os.environ if environ is None else environ
        self.cwd = cwd or os.getcwd()
        self._project = None
        self._config = None
        # A person at the keyboard (readable output, interactive input): questions
        # and confirmations are asked there (cli.asking); never for an agent.
        self.stdin = self.stdout = None
        self.asks = self.human = False

    @property
    def project(self):
        """The project root; raises NotInProject outside a project."""
        if self._project is None:
            self._project = find_project(self.args.project, self.environ, self.cwd)
        return self._project

    @property
    def arg_settings(self):
        """Settings given as command arguments: the seventh layer."""
        out = {}
        if self.args.lang:
            out["language"] = self.args.lang
        if getattr(self.args, "parallel", None) is not None:
            out["search.max_parallel"] = self.args.parallel
        return out

    @property
    def config(self):
        """The settings in effect. Raises ConfigError (exit 2) on an invalid value."""
        if self._config is None:
            from probandia import config

            self._config = config.load(self.project, self.environ, self._harness_options(),
                                       args=self.arg_settings)
        return self._config

    def _harness_options(self):
        """``--harness-options`` when the harness filled them (and then remembered),
        else those remembered for this session (``launcher``). Writes the short
        launcher of the project on the way, only when a harness calls: a person
        running an installed ``probandia`` must not point the plugin's launcher
        at another copy of the engine."""
        from probandia import launcher
        from probandia.harness import detect
        from probandia.util.locks import session_id

        given = self.args.harness_options
        try:
            if detect(self.args.harness, self.environ)[0] != "cli":
                launcher.write_launcher(self.project)
            if given and launcher.has_values(given):
                launcher.remember(self.project, given, session_id(self.environ))
                return given
            return launcher.recall(self.project, session_id(self.environ)) or given
        except OSError:
            return given


def _from_error(err):
    values = {"REASON": err.reason}
    values.update(err.values)
    r = Result("FAIL", values, [err.message] + err.lines, exit_code=err.exit_code)
    if isinstance(err, NotInProject):
        r.view = "no-project"
    return r


def _work_folder(args, environ, cwd, kind):
    """``<project>/.probandia/<kind>``, or the temporary folder outside a project."""
    try:
        root = find_project(getattr(args, "project", None), environ, cwd)
        folder = os.path.join(root, ".probandia", kind)
        os.makedirs(folder, exist_ok=True)
        return folder
    except (NotInProject, OSError):
        import tempfile

        return tempfile.gettempdir()


def _internal_error(args, environ, cwd):
    """Writes the traceback to a log and returns the result to print."""
    import traceback

    from probandia.util.ids import ulid

    path = os.path.join(_work_folder(args, environ, cwd, "logs"), f"internal-{ulid()}.log")
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(traceback.format_exc())
    except OSError:
        path = ""
    r = Result("FAIL", {"REASON": "internal-error"}, [_("internal error; details in the log")],
               exit_code=EXIT_INTERNAL)
    if path:
        r.set("LOG", path)
    return r


def _spill(result, args, environ, cwd):
    """A result too long for the output contract keeps its first lines; the full
    text goes to a details file, named by DETAILS."""
    if result.details or result.fits():
        return
    from probandia.util.fs import atomic_write_text
    from probandia.util.ids import ulid

    name = getattr(args, "command", None) or "output"
    path = os.path.join(_work_folder(args, environ, cwd, "details"), f"{name}-{ulid()}.txt")
    atomic_write_text(path, result.render_text(max_lines=None))
    result.details = path


def _with_env_files(args, environ, cwd):
    """The environment completed by the user's and the project's ``.env`` files."""
    from probandia.util import envfile

    try:
        project = find_project(getattr(args, "project", None), environ, cwd)
    except (NotInProject, OSError):
        project = None
    return envfile.merged(environ, project)


def _utf8(stream):
    try:
        stream.reconfigure(encoding="utf-8", newline="\n")
    except (AttributeError, ValueError):
        pass


def _early_language(argv, environ):
    """The language of messages, known before the arguments are parsed."""
    for i, arg in enumerate(argv):
        if arg in ("--lang", "-l") and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return environ.get("PROBANDIA_LANGUAGE") or environ.get("PROBANDIA_LANG") or "en"


def _first_command(argv):
    """The index of the first argument that is not a global option."""
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in VALUE_OPTIONS:
            i += 2
        elif arg in FLAG_OPTIONS or (arg.startswith("--") and "=" in arg):
            i += 1
        else:
            break
    return i


def _only_command(argv):
    """The one command ``argv`` runs, ``""`` for ``--version``, None when the whole parser is needed
    (a misspelt command, whose error suggests the others)."""
    i = _first_command(argv)
    word = argv[i] if i < len(argv) else None
    if word in ("-V", "--version"):
        return ""
    return word if word in _commands().COMMAND_NAMES else None


def _fast_call(argv):
    """The arguments of ``hook <function> [--harness <name>]``, the forms the manifests write, and of
    ``statusline`` alone, read without argparse, whose help formatter alone costs some 60 ms at each
    call (T145, T146); None otherwise."""
    if argv == ["statusline"]:
        return argparse.Namespace(**GLOBAL_DEFAULTS, command="statusline", _spec=_spec("statusline"))
    if argv[:1] != ["hook"] or len(argv) not in (2, 4) or argv[1].startswith("-") \
            or (len(argv) == 4 and (argv[2] != "--harness" or argv[3] not in HARNESSES)):
        return None
    return argparse.Namespace(**dict(GLOBAL_DEFAULTS, harness=argv[3] if len(argv) == 4 else "cli"),
                              command="hook", function=argv[1], _spec=_spec("hook"))


def _spec(name):
    return next(c for c in _commands().COMMANDS if c.name == name)


def _top_level_help(argv):
    """``(asked, all)``: the top-level help was asked, with or without ``--all``."""
    rest = [a for a in argv if a not in ("-h", "--help", "--all")]
    asked = len(rest) < len(argv) and any(a in ("-h", "--help") for a in argv)
    return asked and _first_command(rest) >= len(rest), "--all" in argv


def expand_shortcut(argv):
    """The arguments with a root shortcut replaced by its command: the first
    argument that is not a global option decides."""
    i = _first_command(argv)
    if i >= len(argv):
        return argv
    arg = argv[i]
    if arg in SHORTCUTS:
        return argv[:i] + SHORTCUTS[arg].split() + argv[i + 1:]
    if re.fullmatch(r"-[A-Za-z]", arg) and arg not in SHORT_OPTIONS:
        raise UsageError(_("unknown shortcut {arg}").format(arg=arg),
                         lines=[_("shortcuts: {list}").format(
                             list=", ".join(f"{k} ({v})" for k, v in SHORTCUTS.items() if len(k) == 2))])
    return argv


def _argv_value(argv, option):
    for i, arg in enumerate(argv):
        if arg == option and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(option + "="):
            return arg.split("=", 1)[1]
    return None


def output_mode(args, argv, stdout, environ):
    """``human``, ``contract`` or ``json`` (cli.md § 6.1, decision D-2).

    The contract, which agents read, unless a person is at a terminal: the
    stream ``main`` writes to is a terminal, no harness is detected, and
    neither ``--json`` nor ``--quiet`` is given. ``--output-format`` decides
    first; ``PROBANDIA_OUTPUT`` next, but its ``human`` never reaches a harness,
    which may have inherited it from the person's shell."""
    from probandia.harness import detect

    explicit = getattr(args, "output_format", None) if args else _argv_value(argv, "--output-format")
    if explicit in OUTPUT_FORMATS:
        return explicit
    if (args.json if args else "--json" in argv):
        return "json"
    if (args.quiet if args else ("--quiet" in argv or "-q" in argv)):
        return "contract"
    harness = detect(args.harness if args else _argv_value(argv, "--harness"), environ)[0]
    wanted = (environ.get("PROBANDIA_OUTPUT") or "").strip().lower()
    if wanted in ("contract", "json"):
        return wanted
    if harness != "cli":
        return "contract"
    if wanted == "human":
        return "human"
    try:
        return "human" if stdout.isatty() else "contract"
    except (AttributeError, ValueError):
        return "contract"


def _sleep(seconds):
    import time

    time.sleep(seconds)


def _clock():
    import datetime

    return datetime.datetime.now()


def _relative(result, args, environ, cwd):
    """Paths inside the project, written relative to its root in the contract
    (optimize 2.11): fewer tokens, and the same text on every computer."""
    try:
        root = find_project(getattr(args, "project", None), environ, cwd)
    except ProbandiaError:
        return
    root = os.path.abspath(root).replace("\\", "/").rstrip("/")
    roots = {root, root[0].lower() + root[1:], root[0].upper() + root[1:]} if root[1:2] == ":" else {root}

    def short(text):
        if not isinstance(text, str):
            return text
        t = text.replace("\\", "/")
        for r in roots:
            if t == r:
                return "."
            if r + "/" in t:
                return t.replace(r + "/", "")
        return text

    for key, value in list(result.values.items()):
        result.values[key] = short(value)
    result.lines = [short(line) for line in result.lines]
    result.details = short(result.details)


def _note_call(args, environ, cwd):
    """An agent's command (its harness is known), counted for the open pass (``lifecycle.note_call``);
    a person's, in a shell or in the terminal application, is not."""
    from probandia.harness import detect

    if detect(getattr(args, "harness", None), environ)[0] == "cli" or args.command in NOT_COUNTED:
        return
    try:
        root = find_project(getattr(args, "project", None), environ, cwd)
    except ProbandiaError:
        return
    from probandia.lifecycle import note_call

    note_call(root, args.command)


def _no_command(argv):
    """True when ``argv`` holds global options only: ``probandia`` alone."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in VALUE_OPTIONS:
            i += 2
        elif a in FLAG_OPTIONS or (a.startswith("--") and a.split("=", 1)[0] in VALUE_OPTIONS):
            i += 1
        else:
            return False
    return True


def _welcome(argv, stdout, environ, cwd):
    """The welcome screen of ``probandia`` alone (decision D-11), readable only."""
    from probandia.cli import board_cmd

    args, _rest = _global_options().parse_known_args(argv)
    for k, v in GLOBAL_DEFAULTS.items():
        if not hasattr(args, k):
            setattr(args, k, v)
    ctx = Context(args, _with_env_files(args, environ, cwd), cwd)
    ctx.human = True
    return board_cmd.welcome(ctx), args


def main(argv=None, stdout=None, environ=None, cwd=None, stdin=None):
    """Runs one command. ``stdin`` is where a person answers questions and
    confirmations, in the readable output only: sys.stdin when ``main`` writes
    to sys.stdout itself, nothing otherwise (a caller that passes its own
    ``stdout`` passes its own ``stdin`` too)."""
    from probandia.cli import asking

    argv = sys.argv[1:] if argv is None else list(argv)
    environ = os.environ if environ is None else environ
    if argv[:1] == ["__complete"]:   # Tab completion: candidates only, no contract (cli.completion)
        from probandia.cli import completion

        return completion.run(argv[1:], stdout or sys.stdout, environ, cwd or os.getcwd())
    base_environ = environ
    if stdin is None and stdout is None:
        stdin = sys.stdin
    if stdout is None:
        _utf8(sys.stdout)
        _utf8(sys.stderr)
        stdout = sys.stdout
    if argv == ["statusline"]:   # T146: the kept line, without the table of commands nor argparse
        from probandia.cli import board_cmd

        try:
            raw = getattr(stdin, "buffer", None)   # Claude Code writes UTF-8, whatever the code page
            text = "" if stdin is None or stdin.isatty() else \
                raw.read().decode("utf-8-sig", errors="replace") if raw else stdin.read()
        except (OSError, ValueError, AttributeError):
            text = ""
        line = board_cmd.cached_line(text, environ, cwd or os.getcwd())
        if line is not None:
            stdout.write(line + "\n")
            stdout.flush()
            return 0
        import io

        stdin = io.StringIO(text)
    i18n.activate(_early_language(argv, environ))
    mode = output_mode(None, argv, stdout, environ)
    quiet = "--quiet" in argv or "-q" in argv
    args = None
    synced = None   # the balances read before the command (T52)
    try:
        argv = expand_shortcut(argv)
        asked, everything = _top_level_help(argv)
        if asked and mode == "human" and not everything:
            from probandia.cli import helptext, human

            stdout.write(helptext.readable_help(human.style_for(stdout, environ), _commands().COMMANDS,
                                                __version__))
            stdout.flush()
            return 0
        if asked:
            argv = [a for a in argv if a != "--all"]
        if mode == "human" and _no_command(argv):
            result, args = _welcome(argv, stdout, base_environ, cwd)
            argv = None
        while argv is not None:
            args = _fast_call(argv) or build_parser(_only_command(argv)).parse_args(argv)
            for k, v in GLOBAL_DEFAULTS.items():
                if not hasattr(args, k):
                    setattr(args, k, v)
            mode, quiet = output_mode(args, argv, stdout, base_environ), args.quiet
            environ = _with_env_files(args, base_environ, cwd)
            ctx = Context(args, environ, cwd)
            ctx.stdin, ctx.stdout = stdin, stdout
            ctx.human = mode == "human"
            ctx.asks = ctx.human and asking.interactive(stdin, environ)
            if synced is None and args.command in SYNC_COMMANDS:
                from probandia.cli.search_cmd import auto_sync

                synced = auto_sync(ctx) or False
            try:
                result = args._spec.run(ctx)
            except AmbiguousResearch as err:
                if not ctx.asks or err.ref is None:   # no prefix to replace: the research must be named
                    raise
                # cli.md § 6.5: a prefix that names several researches is a choice at the keyboard
                from probandia.cli import human

                chosen = asking.ask_one(stdin, stdout, human.style_for(stdout, environ, args),
                                        _("{ref} names several researches: which one?").format(ref=err.ref),
                                        err.candidates, "", False)
                argv = [chosen if a == err.ref else a for a in argv]
                continue
            if result is None:  # hook, mcp: they wrote what the harness reads
                return 0
            if not (ctx.asks and result.status == "ASK"):
                break
            # cli.md § 6.3: the command plays the ask skill, then runs again with the answers
            from probandia.cli import human

            extra = asking.answer(result, stdin, stdout, human.style_for(stdout, environ, args))
            if extra is None:
                break
            argv = argv + extra
    except asking.Interrupted:
        result = Result("STOP", {"REASON": "interrupted"}, exit_code=130)
    except ProbandiaError as err:
        result = _from_error(err)
    except KeyboardInterrupt:
        result = Result("STOP", {"REASON": "interrupted"}, exit_code=130)
    except Exception:
        result = _internal_error(args, environ, cwd)
    if synced:
        from probandia.cli.search_cmd import merge_sync

        merge_sync(result, synced)
    if mode != "human" and getattr(args, "command", None):   # token-economy H2: the engine calls of a pass
        _note_call(args, environ, cwd)
    if (mode == "human" and getattr(args, "watch", None) and result.status not in ("FAIL", "ASK")
            and not getattr(args, "json", False)):
        from probandia.cli import human

        def again():
            again_ctx = Context(args, environ, cwd)
            again_ctx.human = True
            try:
                return args._spec.run(again_ctx)
            except ProbandiaError as err:
                return _from_error(err)

        return human.watch(again, stdout, human.style_for(stdout, environ, args), max(0.5, args.watch),
                           _sleep, _clock, first=result)
    if mode == "contract" and getattr(args, "command", None) not in KEEPS_RESEARCH:
        result.values.pop("RESEARCH", None)   # the caller already knows it (token-economy B6)
    if mode == "contract" and not quiet:
        try:
            _spill(result, args, environ, cwd)
        except OSError:   # a read-only sandbox (Codex's contradictor, T129): the first lines still go out
            result.lines.insert(0, _("the details could not be written: only the first lines follow"))
    if mode in ("contract", "json"):
        _relative(result, args, environ, cwd)
    if mode == "json":
        text = result.render_json()
    elif result.raw is not None:
        text = result.raw
        if mode == "human":   # a long Markdown (report show) goes through the pager
            from probandia.cli import human

            if human.page_if_long(text, stdout, environ):
                return result.exit_code
    elif mode == "human":
        from probandia.cli import human

        text = human.render(result, human.style_for(stdout, environ, args))
        if human.page_if_long(text, stdout, environ):
            return result.exit_code
    else:
        text = result.render_text(quiet=quiet)
    stdout.write(text)
    stdout.flush()
    return result.exit_code
