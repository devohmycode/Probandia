"""The console's forms (cli.md § 8.2, T85): one form per user command, drawn from
the engine's own parser, so an option added to a command appears in its form with
no other change. Written for Probandia on Textual, with no third-party adapter.

Imported when the console opens, never with the application; a command's form is
described (``build_form``) the first time it is shown, never before. A form's command
runs in the application, without closing it (T107).
"""
import argparse
import functools
import re
import shlex

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Checkbox, Footer, Header, Input, Select, Static, Tree

from probandia.cli.tui_cmd import RUN_KEY
from probandia.i18n import _

SECRET = re.compile(r"secret|password|passphrase|token", re.I)
REDACTED = "<redacted>"
# the class of the "append" action, found without naming argparse's private classes
APPEND = type(argparse.ArgumentParser(add_help=False).add_argument("--x", action="append"))


def user_commands():
    """The commands a person runs, in the order of the help: no engine command, nor ``tui`` itself."""
    from probandia.cli.commands import COMMANDS

    return [c for c in COMMANDS if not c.engine and c.name != "tui"]


def _actions(parser):
    # argparse lists a parser's actions nowhere public; cli.completion reads the same list
    return list(parser._actions)


def _subcommands(parser):
    """{name: parser} of the actions of a command (``config show``, ``config set``…), or {}."""
    for a in _actions(parser):
        if a.nargs == argparse.PARSER:
            return dict(a.choices)
    return {}


def _shown(action):
    """An argument of the command itself: not the help, nor a global option, nor a hidden one."""
    from probandia.cli import GLOBAL_DEFAULTS

    return (action.dest not in ("help", "version") and action.dest not in GLOBAL_DEFAULTS
            and action.help != argparse.SUPPRESS and action.nargs != argparse.PARSER)


def split(text):
    """The words of a field that takes several values, quoted as in a shell."""
    try:
        return shlex.split(text)
    except ValueError:   # an unclosed quote: the words as typed
        return text.split()


class Field:
    """One argument of a command, as its form shows it. ``kind`` is ``flag`` (a
    checkbox), ``choice`` (a list), ``optional`` (an option whose value may be left
    out, such as ``--watch``), ``list`` (several words), ``number`` or ``text``."""

    def __init__(self, action):
        self.dest = action.dest
        self.option = action.option_strings[-1] if action.option_strings else None   # the long form
        self.positional = not action.option_strings
        self.choices = [str(c) for c in action.choices] if action.choices else None
        self.help = action.help or ""
        self.metavar = action.metavar if isinstance(action.metavar, str) else None
        default = action.default
        self.default = (None if default is None or default is argparse.SUPPRESS or isinstance(default, (bool, list))
                        else str(default))
        self.const = None if action.const is None else str(action.const)   # --watch alone: --watch 2.0
        self.repeat = isinstance(action, APPEND)
        several = action.nargs in ("*", "+", argparse.REMAINDER) or (isinstance(action.nargs, int) and action.nargs > 1)
        if action.nargs == 0:
            self.kind = "flag"
        elif several or self.repeat:
            self.kind = "list"
        elif self.choices:
            self.kind = "choice"
        elif action.nargs == "?" and not self.positional:
            self.kind = "optional"
        elif action.type in (int, float):
            self.kind = "number"
        else:
            self.kind = "text"
        self.integer = action.type is int
        self.required = (bool(action.required) if not self.positional
                         else action.nargs in (None, "+") or isinstance(action.nargs, int))
        self.secret = bool(SECRET.search(f"{self.dest} {self.metavar or ''}"))

    @property
    def name(self):
        return self.option or self.metavar or self.dest

    def words(self, value, redact=False):
        """The arguments ``value`` gives; [] for a field left empty. A secret is
        written ``<redacted>`` when ``redact``."""
        if self.kind == "flag":
            return [self.option] if value else []
        if self.kind == "optional":
            used, text = value
            text = (text or "").strip()
            return ([self.option, REDACTED if redact and self.secret else text] if text else [self.option]) if used else []
        text = "" if value is None else str(value).strip()
        if not text or (not self.positional and text == self.default):
            return []
        parts = split(text) if self.kind == "list" else [text]
        if redact and self.secret:
            parts = [REDACTED for _p in parts]
        if self.positional:
            return parts
        if self.repeat:
            return [w for p in parts for w in (self.option, p)]
        return [self.option, *parts]


class Form:
    """A command, or an action of one (``config set``): its fields, its help, its actions."""

    def __init__(self, words, parser, summary=""):
        self.words = tuple(words)
        self.parser = parser
        self.help = parser.description or summary
        self.fields = [Field(a) for a in _actions(parser) if _shown(a)]
        self.actions = list(_subcommands(parser))

    def argv(self, values, redact=False):
        """The command line of the values (one per field): the positionals in their
        order, then the options."""
        given = list(zip(self.fields, values))
        return [*self.words, *[w for f, v in given if f.positional for w in f.words(v, redact)],
                *[w for f, v in given if not f.positional for w in f.words(v, redact)]]

    def missing(self, values):
        """The first required field left empty, or None."""
        return next((f for f, v in zip(self.fields, values) if f.required and not f.words(v)), None)


def build_form(parser, words, summary=""):
    """The form of ``words`` (``("usage",)``, ``("config", "set")``) in the engine's parser."""
    p = parser
    for word in words:
        p = _subcommands(p)[word]
    return Form(words, p, summary)


class FieldRow(Vertical):
    """A field of the form: its name, its control and its help."""

    DEFAULT_CSS = """
    FieldRow { height: auto; margin: 0 0 1 0; }
    FieldRow > Horizontal { height: auto; }
    FieldRow .field-name { text-style: bold; width: auto; }
    FieldRow .field-required { color: $warning; width: auto; margin: 0 0 0 2; }
    FieldRow .field-help { color: $text-muted; }
    FieldRow Input { width: 1fr; }
    """

    def __init__(self, field, n):
        super().__init__(id=f"field-{n}")
        self.field = field

    def compose(self):
        f = self.field
        placeholder = (_("{value} (default)").format(value=f.default) if f.default
                       else (f.metavar or f.dest).strip("<>"))
        if f.kind == "flag":
            yield Checkbox(f.name, False, classes="control")
        else:
            with Horizontal():
                yield Static(f.name, classes="field-name", markup=False)
                if f.required:
                    yield Static(_("required"), classes="field-required")
            if f.kind == "choice":
                yield Select([(c, c) for c in f.choices], prompt=_("Select"), allow_blank=True,
                             value=f.default if f.default in f.choices else Select.NULL, classes="control")
            elif f.kind == "optional":
                with Horizontal():
                    yield Checkbox(_("use it"), False, classes="control")
                    yield Input(placeholder=_("{value} (default)").format(value=f.const) if f.const else "",
                                password=f.secret, classes="control-value")
            else:
                kind = ("integer" if f.integer else "number") if f.kind == "number" else "text"
                yield Input(placeholder=placeholder, type=kind, password=f.secret, classes="control")
        if f.help:
            yield Static(f.help, classes="field-help", markup=False)

    def value(self):
        f = self.field
        control = self.query_one(".control")
        if f.kind == "optional":
            return control.value, self.query_one(".control-value", Input).value
        if f.kind == "choice":
            return None if control.is_blank() else control.value
        return control.value

    def focus_control(self):
        self.query_one(".control").focus()


class CommandHelp(ModalScreen):
    """The help of a command, as ``probandia <command> --help`` prints it."""

    DEFAULT_CSS = """
    CommandHelp { align: center middle; }
    CommandHelp VerticalScroll { width: 85%; height: 85%; border: round $accent; background: $surface; padding: 1 2;
                                 border-title-color: $accent; border-title-style: bold; }
    """
    BINDINGS = [Binding("escape,q,f1", "dismiss", _("Close"))]

    def __init__(self, text):
        super().__init__()
        self.text = text

    def compose(self):
        with VerticalScroll() as box:
            box.border_title = _("Command help")
            yield Static(self.text, markup=False)

    def action_dismiss(self):
        self.dismiss()


class FormsScreen(Screen):
    """The console: the user commands in a tree, the form of the one chosen, and the
    command line it makes. ``Ctrl+R`` runs it in the application (T107): its line and its
    readable output under the form, its confirmations and its hidden input in the
    application's windows; another command follows, the application still open."""

    DEFAULT_CSS = """
    FormsScreen #forms-side { width: 32; border-right: vkey $panel; }
    FormsScreen #forms-commands { height: 1fr; }
    FormsScreen #forms-main { width: 1fr; }
    FormsScreen #form-description { height: auto; padding: 0 1 1 1; }
    FormsScreen #form-body { height: 1fr; padding: 0 1; }
    FormsScreen #form-preview { height: auto; padding: 0 1; background: $boost; color: $secondary; text-style: bold; }
    FormsScreen #form-output { height: 1fr; padding: 0 1; border-top: solid $primary; display: none; }
    """
    BINDINGS = [
        Binding(RUN_KEY, "run", _("Run command")),
        Binding("ctrl+y", "copy", _("Copy command")),
        Binding("escape", "focus_commands", _("Commands")),
        Binding("f1,ctrl+o,question_mark", "command_help", _("Command help")),
        Binding("ctrl+s,slash", "focus_search", _("Search")),
        Binding("q", "back", _("Back")),
    ]

    def __init__(self, command=None):
        super().__init__()
        self.initial = command
        self.parser = None    # the engine's parser, built when the first form is
        self.forms = {}       # words -> Form, each described once
        self.current = None   # the Form shown
        self.running = False  # a command under way: one at a time

    def compose(self):
        yield Header()
        with Horizontal():
            with Vertical(id="forms-side"):
                yield Input(placeholder=_("Search..."), id="forms-search")
                yield Tree(_("Commands"), id="forms-commands")
            with Vertical(id="forms-main"):
                yield Static("", id="form-description", markup=False)
                yield VerticalScroll(id="form-body")
                yield Static("", id="form-preview", markup=False)
                with VerticalScroll(id="form-output"):
                    yield Static("", id="form-result", markup=False)
        yield Footer()

    async def on_mount(self):
        tree = self.query_one("#forms-commands", Tree)
        tree.show_root = False
        look = getattr(self.app, "look", None)
        if look:   # the width of the theme in use (config.themes)
            self.query_one("#forms-side").styles.width = look["commands_width"]
        self.fill_tree()
        tree.focus()
        commands = list(tree.root.children)
        node = next((n for n in commands if n.data == (self.initial,)), commands[0] if commands else None)
        if node is not None:   # its form, then the cursor on it: one line per command, none expanded yet
            await self.show(node)
            tree.cursor_line = commands.index(node)

    def fill_tree(self, word=""):
        tree = self.query_one("#forms-commands", Tree)
        tree.clear()
        word = word.strip().lower()
        for spec in user_commands():
            if not word or word in spec.name or word in _(spec.help).lower():
                tree.root.add(spec.name, data=(spec.name,), allow_expand=False)
        tree.root.expand()

    def form(self, words):
        if words not in self.forms:
            if self.parser is None:
                from probandia import cli

                self.parser = cli.build_parser()
            spec = next((c for c in user_commands() if c.name == words[0]), None)
            self.forms[words] = build_form(self.parser, words, _(spec.help) if spec else "")
        return self.forms[words]

    async def on_tree_node_highlighted(self, event):
        if event.node.data and (self.current is None or event.node.data != self.current.words):
            await self.show(event.node)

    async def show(self, node):
        form = self.form(node.data)
        self.current = form
        if form.actions and not node.children:   # config: its actions under it
            node.allow_expand = True
            for action in form.actions:
                node.add_leaf(action, data=(*form.words, action))
            node.expand()
        text = "probandia " + " ".join(form.words) + ("\n" + form.help if form.help else "")
        if form.actions:
            text += "\n" + _("Choose an action: {actions}").format(actions=", ".join(form.actions))
        self.query_one("#form-description", Static).update(text)
        body = self.query_one("#form-body", VerticalScroll)
        await body.remove_children()
        await body.mount_all([FieldRow(f, n) for n, f in enumerate(form.fields)])
        self.update_preview()

    def values(self):
        return [row.value() for row in self.query(FieldRow)]

    def command(self, redact=False):
        """The arguments of the form as filled, after ``probandia``; None before a form is shown."""
        if self.current is None:
            return None
        return self.current.argv(self.values(), redact=redact)

    def update_preview(self):
        from probandia.cli.tui_cmd import command_line

        argv = self.command(redact=True)
        self.query_one("#form-preview", Static).update("$ " + command_line(["probandia", *argv]) if argv else "")

    def on_input_changed(self, event):
        if event.input.id == "forms-search":
            self.fill_tree(event.value)
        else:
            self.update_preview()

    def on_select_changed(self, _event):
        self.update_preview()

    def on_checkbox_changed(self, _event):
        self.update_preview()

    def action_run(self):
        """``Ctrl+R``: the command run in the application, in a thread (``ProbandiaApp.execute``);
        its output fills the panel under the form once it ends."""
        if self.current is None or self.current.actions:
            self.notify(_("Choose a command first"), severity="warning")
            return
        values = self.values()
        missing = self.current.missing(values)
        if missing is not None:
            self.notify(_("{field} is required").format(field=missing.name), severity="warning")
            next(r for r in self.query(FieldRow) if r.field is missing).focus_control()
            return
        argv = self.current.argv(values)
        if "--watch" in argv or argv[:2] == ["config", "edit"]:   # they hold the terminal: until Ctrl+C, an editor
            self.notify(_("This command needs the terminal: Ctrl+Y copies it"), severity="warning")
            return
        if self.running:
            self.notify(_("A command is running"), severity="warning")
            return
        self.running = True
        shown = self.current.argv(values, redact=True)
        self.query_one("#form-output").display = True
        self.query_one("#form-result", Static).update(_("Running {command}…").format(command=" ".join(shown)))
        width = ["--width", str(max(40, self.query_one("#forms-main").size.width - 4))]   # fitted to the panel
        self.run_worker(functools.partial(self.app.execute, [*argv, *width], shown),
                        name="console", group="console", thread=True, exit_on_error=False)

    def on_worker_state_changed(self, event):
        from rich.text import Text
        from textual.worker import WorkerState

        worker = event.worker
        if worker.group != "console" or worker.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        self.running = False
        if worker.state == WorkerState.ERROR:
            text = _("internal error: {error}").format(error=f"{type(worker.error).__name__}: {worker.error}")
        else:
            code, text = worker.result
            text = text.rstrip("\n") + "\n\n" + _("Exit code: {code}").format(code=code)
        self.query_one("#form-result", Static).update(Text.from_ansi(text))   # text, never markup
        self.query_one("#form-output").scroll_home(animate=False)

    def action_copy(self):
        """``Ctrl+Y``: the command line, a secret left out, to the clipboard; nothing is run."""
        from probandia.cli.tui_cmd import command_line

        argv = self.command(redact=True)
        if argv:
            self.app.copy_to_clipboard(command_line(["probandia", *argv]))
            self.notify(_("Command copied"))

    def action_focus_commands(self):
        self.query_one("#forms-commands", Tree).focus()

    def action_focus_search(self):
        self.query_one("#forms-search", Input).focus()

    def action_command_help(self):
        if self.current is not None:
            self.app.push_screen(CommandHelp(self.current.parser.format_help()))

    def action_back(self):
        if len(self.app.screen_stack) > 1:   # opened over the application: back to it
            self.app.pop_screen()
        else:
            self.app.exit()
