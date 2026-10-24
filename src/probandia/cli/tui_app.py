"""The Probandia application in a terminal (cli.md § 8.3 to 8.5, CLI15).

Imported only by ``probandia tui``, once Textual is known to be installed: the
engine never imports it. Every screen reads what a command publishes (its ``data``,
the command run in this process, through its handler) or what an engine function
returns. It reads in a thread, never in the interface's: a key changes the screen at
once, and a read under way shows its indicator (T88). What a screen read stays shown,
and is not read again, while the files it watches and what it depends on are those of
its last read. Every action runs an engine command, with its locks, its roles and its
guard, after a confirmation. The console's forms (``tui_forms``) open over the
application, from the command palette.
"""
import fnmatch
import functools
import glob
import io
import json
import os
import re
import threading

from textual.app import App, ScreenStackError
from textual.binding import Binding
from textual.command import Hit, Provider
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane
from textual.worker import WorkerState, get_current_worker

from probandia.cli.tui_cmd import PALETTE_KEY, SCREENS   # the help of tui reads them without Textual (T108)
from probandia.errors import ProbandiaError
from probandia.i18n import N_, _

# The parts of a screen, in tabs under its own (``[`` and ``]``): the first one bears its name.
PARTS = {"quotas": [("quotas", N_("Accounts")), ("providers", N_("Providers and keys"))],
         "config": [("config", N_("Settings")), ("themes", N_("Themes")), ("library", N_("Library")),
                    ("diagnostic", N_("Diagnostic"))],
         "help": [("help", N_("Settings")), ("help-layers", N_("Sources")), ("help-providers", N_("Providers")),
                  ("help-keyfiles", N_("Keys")), ("help-variables", N_("Variables")), ("help-options", N_("Options"))]}
# The tabs of the file of the research chosen, under the list: its report and its team follow it.
FILE_TABS = [("file", N_("File")), ("report", N_("Report")), ("team", N_("Team"))]


# The files each screen reads, as (folder, pattern): under the project, in the user's
# configuration folder (``config.toml``, ``.env``, the library) or in the user's data folder
# (the quota counter shared by the projects, cli.md § 4.4). A folder is watched by its
# files: one added or removed changes the list (T90).
RESEARCH = "families/*/research/*/"
RESEARCHES = (("project", RESEARCH + "research.yaml"), ("project", RESEARCH + "events.jsonl"))
INDEXES = (("project", "families/*/family.yaml"), ("project", "families/*/index/*.yaml"))
PROPOSALS = (("project", RESEARCH + "work/proposals/*"),)
LOCKS = (("project", ".probandia/locks/*"),)
LEDGERS = (("project", ".probandia/ledger.jsonl"), ("project", ".probandia/quota.json"),
           ("data", "quotas/ledger.jsonl"), ("data", "quotas/state.json"))
SETTINGS = (("project", "probandia.toml"), ("project", ".env"), ("config", "config.toml"), ("config", ".env"))


def watched(roots, patterns):
    """{path: (mtime, size)} of the files ``patterns`` name in ``roots`` ({folder: path}),
    ``*`` for any name. Each folder is listed once, by ``os.scandir``, whose entries carry
    their dates on Windows: the look of each second costs little (T90)."""
    tree = {}
    for root, pattern in patterns:
        if roots.get(root):
            node = tree.setdefault(roots[root], {})
            for part in pattern.split("/"):
                node = node.setdefault(part, {})
            node[None] = {}   # a pattern ends here
    out = {}
    for folder, node in tree.items():
        _look(folder, node, out)
    return out


def _look(folder, node, out):
    try:
        with os.scandir(folder) as listing:
            entries = list(listing)
    except OSError:
        return
    for entry in entries:
        below = {}
        for part, sub in node.items():
            if part is not None and fnmatch.fnmatch(entry.name, part):
                _merge(below, sub)
        if None in below:
            try:
                st = entry.stat()
            except OSError:
                continue
            out[entry.path] = (st.st_mtime_ns, st.st_size)
        if len(below) > (None in below) and entry.is_dir():
            _look(entry.path, below, out)


def _merge(into, node):
    """The patterns of ``node`` added to ``into``, a copy."""
    for part, sub in node.items():
        _merge(into.setdefault(part, {}), sub)


HEADERS = {"origin": N_("origin"), "base": N_("starts from"), "in_use": N_("in use"), "stale": N_("to check again"),
           "order": N_("order"), "default": N_("default"), "values": N_("values"), "option": N_("option"),
           "how": N_("how to write it"), "condition": N_("condition")}


def label(name):
    from probandia.cli.views import _label

    return _(HEADERS[name]) if name in HEADERS else _label(name)


def fill(table, rows, columns=None, key=None):
    """Rows (dicts) into a DataTable, under translated headers. Filled again, the table
    keeps its place (T89): the cursor stays on the row of the same key (``key``, a field
    of the rows or a function of a row), else on the same line, and the scroll where it
    was; filling it tells the screen nothing (no RowHighlighted). Each column is keyed by
    its field, each cell is the value in clear (``cell``), as text, never markup (T95)."""
    columns = columns or list(dict.fromkeys(k for r in rows for k in r))
    keyed = (lambda r: str(r.get(key))) if isinstance(key, str) else key
    line, column = table.cursor_coordinate
    was = None
    if keyed and table.is_valid_coordinate(table.cursor_coordinate):
        was = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
    scroll = (table.scroll_x, table.scroll_y)
    with table.prevent(DataTable.RowHighlighted, DataTable.CellHighlighted):
        if [c.key.value for c in table.columns.values()] == columns:
            table.clear()
        else:
            table.clear(columns=True)
            for c in columns:
                table.add_column(label(c), key=c)
        keys = [keyed(r) if keyed else None for r in rows]
        for k, r in zip(keys, rows):
            table.add_row(*cells(r, columns), key=k)
        if rows and (line or column or was is not None):
            if was is not None and was in keys:
                line = keys.index(was)
            table.move_cursor(row=min(line, len(rows) - 1), column=min(column, len(columns) - 1), scroll=False)
    if any(scroll):
        table.call_after_refresh(table.scroll_to, *scroll, animate=False)
    return table


def narrow(rows, word, columns=None):
    """The rows a filter keeps: those whose shown cells (``columns``, else all) hold ``word``."""
    if not word:
        return rows
    return [r for r in rows if any(word in cell(r.get(c), c).lower() for c in columns or r)]


# Values in clear (T95): the words of the engine's vocabularies, the dates written out.

ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
RELATIVE = ("last_activity", "last_run", "synced_at", "expires", "since", "opened", "renews", "written")   # from now
DATES = ("date", "born", "died")   # a genealogical date: 1898, about:1896, 1870-03-12
AMOUNTS = ("amount", "left", "of", "used", "input", "output", "weighted", "size", "bytes")   # with separators
UNITS = {"search": N_("searches"), "credit": N_("credits"), "request": N_("requests"), "dollar": N_("dollars"),
         "token": N_("tokens"), "page": N_("pages")}
EVENTS = {"pass.started": N_("pass opened"), "pass.ended": N_("pass closed"), "volet.opened": N_("part opened"),
          "instruction.added": N_("instruction"), "plan.made": N_("plan"), "search.logged": N_("search"),
          "evidence.recorded": N_("evidence"), "fact.asserted": N_("fact asserted"), "fact.revised": N_("fact revised"),
          "fact.retracted": N_("fact retracted"), "hypothesis.opened": N_("hypothesis opened"),
          "hypothesis.updated": N_("hypothesis updated"), "hypothesis.closed": N_("hypothesis closed"),
          "negative.recorded": N_("negative"), "erratum.recorded": N_("erratum"), "section.added": N_("section added"),
          "section.replaced": N_("section replaced"), "section.moved": N_("section moved"),
          "section.merged": N_("sections merged"), "branch.added": N_("branch added"), "mode.changed": N_("mode"),
          "language.changed": N_("language"), "verify.run": N_("verify"), "library.used": N_("script used"),
          "question.added": N_("question asked"), "question.updated": N_("question updated"),
          "research.closed": N_("research closed"), "analysis.recorded": N_("analysis"), "proof.recorded": N_("proof"),
          "matrix.justified": N_("matrix"), "fact.checked": N_("fact checked")}


@functools.cache
def vocabulary():
    """{field: {value: message id}}: the values the screens show in words, from the
    vocabularies the readable output and the reports already translate."""
    from probandia.cli import usage_cmd, views
    from probandia.report import labels

    states = {**views.PROVIDER_STATES, **usage_cmd.OUT_LABELS, "exhausted": N_("used up"),
              "expired": N_("expired"), "no-quota": N_("no quota left"), "held": N_("held"), "valid": N_("valid"),
              "due": N_("to check again")}
    rules = {"PASS": N_("passed"), "WARN": N_("warning"), "FAIL": N_("failed")}
    layers = {**views.LAYER_LABELS, "research": N_("research")}   # a research's own model or effort
    return {"status": {**views.RESEARCH_STATUSES, **views.FACT_STATUSES, **rules, "refuted": N_("refuted")},
            "state": states, "reason": states, "verdict": VERDICTS, "layer": views.LAYER_LABELS,
            "level": views.LEVELS, "grade": GRADES, "unit": UNITS, "source": views.KEY_SOURCES,
            "kind": {**views.KINDS, "destroyed": N_("destroyed"), "missing": N_("missing"),
                     "lacunary": N_("lacunary")},
            "relation": labels.TIMELINE_ROLES, "fact": labels.FACT_TYPES,
            "type": {**EVENTS, "task": N_("task"), "result": N_("result"), "finding": N_("finding"),
                     "question": N_("question"), "stop": N_("stop")},
            "match": {"exact": N_("exact"), "variant": N_("variant"), "phonetic": N_("sounds alike"),
                      "given name": N_("given name")},
            "value": {"true": N_("yes"), "false": N_("no")}, "default": {"true": N_("yes"), "false": N_("no")},
            "change": {"added": N_("added"), "modified": N_("modified")}, "outcome": views.KEY_OUTCOMES,
            "model_from": layers, "effort_from": layers,
            "index": {"persons": N_("persons"), "facts": N_("facts"), "places": N_("places"), "sources": N_("sources"),
                      "searches": N_("searches"), "hypotheses": N_("hypotheses"), "non-links": N_("non-links"),
                      "gaps": N_("gaps"), "analyses": N_("analyses"), "proofs": N_("proofs")}}


def moment(value, field=None):
    """A date and time of the files: from now for what is to come or was last (``in 3 d``),
    else written out, in UTC as written (``1 September 2026 10:09``)."""
    from probandia.cli import views
    from probandia.i18n import formats

    if field in RELATIVE:
        return views._when(value)
    return f"{formats.long_date(value[:10])} {value[11:16]}"


def genealogical(value):
    """``about:1896`` -> ``about 1896``, ``1870-03-12`` -> ``12 March 1870``, ``?`` as it is."""
    from probandia.i18n import formats
    from probandia.report import labels

    qualifier, _sep, date = str(value).rpartition(":")
    text = formats.long_date(date)
    return _(labels.QUALIFIERS[qualifier]).format(date=text, end="?") if qualifier in labels.QUALIFIERS else text


def cell(value, field=None):
    """A value as a screen shows it: the words of its vocabulary in the language in effect,
    a date written out, a list as a list, yes or no; never Python's nor the contract's forms."""
    from probandia.cli.human import show_value
    from probandia.i18n import formats

    if isinstance(value, (list, tuple)):
        return ", ".join(cell(x, field) for x in value) or "—"
    if isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool) and field in AMOUNTS):
        return formats.number(value)
    if isinstance(value, str) and value:
        known = vocabulary().get(field, {})
        if value in known:
            return _(known[value])
        if field in DATES:
            return genealogical(value)
        if ISO_TIME.fullmatch(value):
            return moment(value, field)
        if ISO_DATE.fullmatch(value):
            return moment(value, field) if field in RELATIVE else genealogical(value)
    return show_value(value)


def cells(row, columns):
    """The cells of a row, as text: what the files hold is never read as markup."""
    from rich.text import Text

    return [Text(cell(row.get(c), c)) for c in columns]


def browse(path):
    """A file of the project in the browser (``o``)."""
    import webbrowser

    webbrowser.open("file:///" + path.replace(os.sep, "/").lstrip("/"))


def displayed(widget):
    """True when ``widget`` is on display: neither it nor a tab around it is hidden."""
    return all(n.display for n in widget.ancestors_with_self)


def shown_in(widget, tab):
    """True when ``widget`` shows once ``tab`` does: nothing between them hides it."""
    while widget is not tab:
        if not widget.display:
            return False
        widget = widget.parent
    return True


def chose(table, line):
    """Puts the cursor of ``table`` on ``line`` without telling the screen."""
    if 0 <= line < table.row_count and table.cursor_row != line:
        with table.prevent(DataTable.RowHighlighted, DataTable.CellHighlighted):
            table.move_cursor(row=line)


def current(event):
    """False for a RowHighlighted overtaken by a later move of the cursor."""
    return event.cursor_row == event.data_table.cursor_row


class CommandFailed(Exception):
    """A command a screen reads that failed: the text says why (``failure``)."""


def failure(argv, answer):
    """What a screen says of a command that failed: the command and its reason, its
    first line, and the log an internal error left (T87)."""
    v = answer.get("values") or {}
    parts = [_("{command} failed: {reason}").format(command=" ".join(str(a) for a in argv),
                                                    reason=v.get("REASON") or answer.get("status") or "?")]
    parts += [str(x) for x in (answer.get("lines") or [])[:1] if str(x).strip()]
    if v.get("LOG"):
        parts.append(_("details in {log}").format(log=v["LOG"]))
    return " · ".join(parts)


def notes(answer):
    """The lines of an answer that say something, not its ``key=value`` data (T94)."""
    from probandia.cli.human import DATA_LINE

    return [str(x) for x in answer.get("lines") or [] if not DATA_LINE.match(str(x))]


def said(err):
    """What a screen says of a read that raised: a command that failed, an engine
    function that raised, a research removed meanwhile (T87)."""
    if isinstance(err, CommandFailed):
        return str(err)
    if isinstance(err, ProbandiaError):
        return _("{reason}: {message}").format(reason=err.reason, message=err.message)
    return _("internal error: {error}").format(error=f"{type(err).__name__}: {err}")


# The keys of a list that a pane holds while its first read is under way: pressed meanwhile, they
# would move nothing (the list is covered, empty) and be lost.
HELD_KEYS = {"j": "cursor_down", "down": "cursor_down", "k": "cursor_up", "up": "cursor_up",
             "g": "scroll_top", "home": "scroll_top", "G": "scroll_bottom", "end": "scroll_bottom",
             "pagedown": "page_down", "pageup": "page_up", "enter": "select_cursor"}


class Read:
    """One read of a screen: what it returned, the files and the context it was read
    with, and the read asked last (its number: an older one is dropped)."""

    def __init__(self):
        self.data = self.stamp = self.asked = None
        self.serial, self.busy = 0, False


class Pane(VerticalScroll):
    """A screen of the application. ``read`` (and ``read_<part>``) runs in a thread and
    only calls the engine; ``show`` (and ``show_<part>``) fills the widgets with what it
    returned, in the interface's thread."""

    needs_project = True
    parts = ("main",)
    indicator = "DataTable, Tree, MarkdownViewer"   # its main widget: a first read's indicator
    narrows = True   # its filter (``#filter``, ``/``) narrows what was read, without reading again
    file = None   # where Enter on its main list moves the focus: the file of the line (T93)
    watches = ()   # the files its reads depend on (``watched``)
    files_only = ()   # the parts that read files and run no command: they wait for no command

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = {name: Read() for name in self.parts}

    @property
    def data(self):
        """What the main read returned last, or None."""
        return self.reads["main"].data

    def compose(self):
        yield Static("", classes="title", markup=False)

    def filter_box(self, placeholder):
        """The filter of a screen that shows a list, which ``/`` reaches (T92)."""
        from textual.widgets import Input

        return Input(placeholder=placeholder, id="filter")

    def word(self):
        """What the filter holds, in lower case."""
        found = self.query_children("#filter")
        return found.first().value.strip().lower() if found else ""

    def on_input_changed(self, event):
        if event.input.id == "filter" and self.narrows and self.data is not None:
            event.stop()
            self.guard(self.show, self.data)   # the filter reads nothing again (T88)

    def main(self):
        """Its main widget, where the indicator of a first read shows, and the focus goes."""
        return self.query(self.indicator).first()

    def focus_target(self):
        """What takes the focus on it: its main widget (in it, the report's text), or itself while
        its first read is under way (T93)."""
        main = self.main()
        if not main.focusable and not main.loading:
            main = next((w for w in main.query("*") if w.focusable), main)
        return main if main.focusable else self

    def take_focus(self):
        self.screen.set_focus(self.focus_target())

    def on_data_table_row_selected(self, event):
        if self.file and event.data_table is self.main():
            self.open_file()

    def open_file(self):
        """Enter on the main list: the focus in the file of the line chosen."""
        found = self.query(self.file) if self.file else None
        if found:
            found.first().focus()
            found.first().scroll_visible(top=True, animate=False)

    def title(self, text):
        self.query_one(".title", Static).update(text)

    def context(self):
        """What the main read depends on besides the files: the research selected…"""
        return None

    def read(self, context):
        return None

    def show(self, data):
        pass

    def copy(self):
        """``c``: what the screen copies to the clipboard, when it copies something."""

    def refresh_data(self, force=False):
        """Reads the screen again, unless its files and its context are those of its last
        read; ``force`` reads it anyway."""
        if self.needs_project and not self.app.project:
            self.title(_("Not in a project: run probandia tui in the folder of a project, or with -p <path>"))
            return
        self.fetch("main", self.context(), force=force)

    def fetch(self, part="main", context=None, force=False, **extra):
        """Starts ``read_<part>(context, **extra)`` in a thread, unless what it would read
        is what the screen shows, or is being read. True when a read started."""
        stamp = (context, watched(self.app.roots, self.watches))
        state = self.reads[part]
        if not force and (stamp == state.stamp or (state.busy and stamp == state.asked)):
            return False
        state.serial += 1
        state.asked, state.busy = stamp, True
        if part == "main" and state.data is None:
            self.waiting(True)
        read = self.read if part == "main" else getattr(self, f"read_{part}")
        self.run_worker(functools.partial(self.app.reading, read, context, part in self.files_only, **extra),
                        name=f"{part}-{state.serial}", group=part, thread=True, exclusive=True, exit_on_error=False)
        return True

    held = None   # the keys of its list pressed during its first read, played once it is shown

    def waiting(self, on):
        """The indicator of a first read under way, over the screen's main widget: its
        filter stays at hand meanwhile, and the pane holds the focus and the keys of its list
        (``held``). Off, it returns the keys held."""
        try:
            main = self.main()
        except NoMatches:
            return []
        if not on:
            held, self.held = self.held or [], None
            main.loading = False
            return held
        if self.held is None:
            self.held = []
        main.loading = True
        if displayed(self) and self.screen.focused in (None, main):   # a covered list loses the focus
            self.screen.set_focus(self)
        return []

    def allow_focus(self):
        return self.held is not None or super().allow_focus()

    def on_key(self, event):
        if self.held is not None and event.key in HELD_KEYS and self.screen.focused is self:   # not the filter's
            self.held.append(event.key)
            event.stop()
            event.prevent_default()

    def on_worker_state_changed(self, event):
        worker = event.worker
        state = self.reads.get(worker.group)
        if (state is None or worker.name != f"{worker.group}-{state.serial}"
                or worker.state not in (WorkerState.SUCCESS, WorkerState.ERROR)):
            return   # a read replaced meanwhile, or not finished
        state.busy = False
        if worker.group == "main":
            held = self.waiting(False)
            if self.screen.focused is self:   # waited on the pane while it read (T93)
                self.take_focus()
            else:
                held = []
        if worker.state == WorkerState.ERROR:
            state.stamp = None   # read again next time
            self.guard(self.failed, worker.group, state.asked[0], worker.error)
            return
        state.data, state.stamp = worker.result, state.asked
        self.guard(self.show if worker.group == "main" else getattr(self, f"show_{worker.group}"), worker.result)
        if worker.group == "main":
            self.play(held)

    def play(self, held):
        """The keys held during the first read, on the list it filled."""
        table = self.screen.focused
        for key in held:
            if isinstance(table, DataTable):
                getattr(table, f"action_{HELD_KEYS[key]}")()

    def failed(self, part, context, err):
        """A read that raised: the title says why."""
        self.title(said(err))

    def guard(self, show, *args):
        """Runs ``show``. What it raises is said in the title, and the application goes
        on (T87); a screen being taken down is read again when it is back."""
        try:
            show(*args)
        except NoMatches:
            for state in self.reads.values():
                state.stamp = None
        except Exception as err:   # a defect of the screen: said, not raised
            self.title(said(err))


def keys(app):
    """[(key as shown, what it does)] of the application's bindings: the help says what the
    keys do, never a list of its own (T92)."""
    return [(app.get_key_display(b), b.tooltip or b.description) for b in type(app).BINDINGS]


def titled(table, text):
    """A DataTable that says what it is in its top line."""
    table.border_title = text
    table.add_class("-titled")
    return table


SECTIONS = {"accounts": N_("Accounts"), "alerts": N_("Alerts"), "next": N_("Next actions"),
            "passes": N_("Passes"), "verify": N_("Verification"), "tokens": N_("Tokens"), "log": N_("Log"),
            "facts": N_("Facts"), "relatives": N_("Relatives"), "hypotheses": N_("Hypotheses"),
            "negatives": N_("Negative searches"), "gaps": N_("Gaps")}


class HelpScreen(ModalScreen):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Vertical { width: 80; max-width: 100%; height: auto; max-height: 100%;
                            border: round $accent; background: $surface; padding: 0 1; }
    """
    BINDINGS = [Binding("escape,q,question_mark", "dismiss", N_("Close"))]

    def compose(self):
        with Vertical() as box:
            box.border_title = _("Keyboard")
            yield DataTable(id="help-keys", show_header=False, cursor_type="none")
            yield Static(_("The mouse works everywhere."))

    def on_mount(self):
        from rich.text import Text

        table = self.query_one("#help-keys", DataTable)
        listed = keys(self.app)
        half = (len(listed) + 1) // 2   # two columns of keys: the help fits in 80 × 24
        table.add_columns("", "", "", "")
        for i in range(half):
            right = listed[i + half] if i + half < len(listed) else ("", "")
            table.add_row(*(Text(x, style="bold" if j % 2 == 0 else "")   # text, never markup
                            for j, x in enumerate((*listed[i], *right))))

    def action_dismiss(self):
        self.dismiss()


def places():
    """[(pane or tab, title)]: the screens, the parts of a screen and the tabs of a research's file."""
    out = list(SCREENS)
    for parts in [*PARTS.values(), FILE_TABS]:
        out += [x for x in parts if x[0] not in dict(SCREENS)]
    return out


class Places(Provider):
    """The palette: the screens of the application, and their parts, listed first."""

    async def discover(self):
        from textual.command import DiscoveryHit

        for name, title in places():
            yield DiscoveryHit(_("Go to {screen}").format(screen=_(title)), lambda name=name: self.app.show(name))

    async def search(self, query):
        matcher = self.matcher(query)
        for name, title in places():
            text = _("Go to {screen}").format(screen=_(title))
            score = matcher.match(text)
            if score > 0:
                yield Hit(score, matcher.highlight(text), lambda name=name: self.app.show(name))


class Forms(Provider):
    """The console: one form per user command (``tui_forms``). A form runs its command
    in the application, its confirmations and its hidden input in its windows
    (``ProbandiaApp.execute``). The palette lists the commands by their help only: no form
    is described before it is shown."""

    async def discover(self):
        from textual.command import DiscoveryHit

        yield DiscoveryHit(_("Console: every command in forms"), self.app.open_forms)

    async def search(self, query):
        from probandia.cli.tui_forms import user_commands

        matcher = self.matcher(query)
        for spec in [None, *user_commands()]:
            name = spec.name if spec else None
            text = _("Form: {command}").format(command=name) if name else _("Console: every command in forms")
            score = matcher.match(text)
            if score > 0:
                yield Hit(score, matcher.highlight(text), lambda name=name: self.app.open_forms(name),
                          help=_(spec.help) if spec else None)


class Keys(Footer):
    """Textual's footer, drawn again only when the keys it shows change: a list that takes the
    focus from another shows the same keys, and drawing them again slows every switch (T93)."""

    drawn = None

    def bindings_changed(self, screen):
        shown = [(b.key, b.description, enabled) for _node, b, enabled, _tip in screen.active_bindings.values()
                 if b.show or b.action == "command_palette"]
        if shown != self.drawn:
            self.drawn = shown if screen.app.app_focus else None   # not drawn without the focus
            super().bindings_changed(screen)


class Main(Screen):
    """The tabs of the screens, a header and the keys."""

    def compose(self):
        yield Header(icon="*" if self.app.plain else None)
        with TabbedContent(id="screens"):
            for n, (name, title) in enumerate(SCREENS, 1):
                with TabPane(f"{n} {_(title)}", id=name):   # each tab shows its key (T92)
                    if name not in PARTS:
                        yield PANES[name](id=f"pane-{name}")
                        continue
                    with TabbedContent(id=f"parts-{name}"):
                        for part, text in PARTS[name]:
                            with TabPane(_(text), id=f"part-{part}"):
                                yield PANES[part](id=f"pane-{part}")
        yield Keys()

    def on_tabbed_content_tab_activated(self, event):
        from textual.widgets import Tabs

        self.app.refresh_screen(force=False)
        if isinstance(self.focused, Tabs):   # a tab chosen with the mouse: the focus on what it shows (T93)
            self.app.focus_in(event.pane)


# 1 Home and 2 Quotas (CLI15-T2)


HOME_EVENTS = 8   # the last events of the research chosen, on the home screen


def resume_command(harness, research):
    """The command that resumes ``research`` in an agent: the plugin's slash command as the harness
    names it, ``/probandia-resume`` where OpenCode copies the commands (``install/opencode.py``)."""
    return f"/probandia-resume {research}" if harness == "opencode" else f"/probandia:resume {research}"


class HomePane(Pane):
    """The board (cli.md § 7.2 and § 8.3), in two columns: the researches and the last events of
    the one chosen; the lowest accounts in gauges, the alerts and the next actions. Enter opens a
    research, ``c`` copies the command that resumes it in an agent: the application starts none."""

    needs_project = False
    parts = ("main", "events")
    files_only = ("events",)   # events.jsonl read from its end
    watches = RESEARCHES + INDEXES + PROPOSALS + LOCKS + LEDGERS + SETTINGS

    def compose(self):
        from textual.containers import Horizontal

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("filter: a research, an account, an alert"))
        with Horizontal(id="home-body"):
            with Vertical(id="home-left"):
                yield DataTable(id="home-researches", cursor_type="row", zebra_stripes=True)
                yield Static("", id="home-events-head", markup=False)
                yield DataTable(id="home-events", cursor_type="row")
            with Vertical(id="home-right"):
                for name in ("accounts", "alerts", "next"):
                    yield titled(DataTable(id=f"home-{name}", cursor_type="row", zebra_stripes=True),
                                 _(SECTIONS[name]))

    def refresh_data(self, force=False):
        if self.app.project and self.app.research:
            self.fetch("events", self.app.research, force=force)
        super().refresh_data(force=force)

    def read(self, context):
        from probandia import cli
        from probandia.cli import board_cmd

        ctx = self.app.ctx
        return board_cmd.welcome(cli.Context(ctx.args, ctx.environ, ctx.cwd)).extra

    def read_events(self, research):
        from probandia.research import find_research

        lines, _first, _end = last_lines(find_research(self.app.project, research).events_path, HOME_EVENTS)
        return {"research": research, "rows": event_rows(lines)}

    def show_events(self, d):
        from probandia.cli import views

        if d["research"] != self.app.research:
            return   # another research was chosen meanwhile
        self.query_one("#home-events-head", Static).update(_("Events · {research}").format(research=d["research"]))
        fill(self.query_one("#home-events"), [dict(x, time=views._when(x["time"])) for x in d["rows"]],
             ["time", "type", "what"], key="at")

    def failed(self, part, context, err):
        if part == "events":   # said in the place of the events
            self.query_one("#home-events-head", Static).update(said(err))
            fill(self.query_one("#home-events"), [], [])
            return
        super().failed(part, context, err)

    def on_data_table_row_highlighted(self, event):
        if event.data_table.id == "home-researches" and event.row_key is not None and current(event):
            if self.app.research != event.row_key.value:   # its events follow the line chosen
                self.app.research = event.row_key.value
                self.fetch("events", self.app.research)

    def on_data_table_row_selected(self, event):
        """Enter on a research: the screen Researches, on it."""
        if event.data_table.id == "home-researches" and event.row_key is not None:
            self.app.research = event.row_key.value
            self.app.show("researches")
            researches = self.app.pane("researches")
            if researches.data is not None:   # read already: shown again, on the research chosen
                researches.guard(researches.show, researches.data)

    def copy(self):
        """``c``: the command that resumes the research chosen, copied and shown; an agent's session
        is spent, so the application only copies it (T97)."""
        from probandia.harness import detect

        table = self.query_one("#home-researches", DataTable)
        if not table.row_count:
            return
        research = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        command = resume_command(detect(self.app.ctx.args.harness, self.app.ctx.environ)[0], research)
        self.app.copy_to_clipboard(command)
        self.app.notify(_("Copied: {text}").format(text=command), markup=False)

    def show(self, b):
        from probandia.cli import human, views

        n, word = views._plural, self.word()
        if self.app.research is None and b["researches"]:   # the first of `research list`: its log read without it
            self.app.research = b["researches"][0]["research"]
        self.title(" · ".join([n(len(b["families"]), _("{n} family"), _("{n} families")),
                               n(len(b["researches"]), _("{n} research"), _("{n} researches")),
                               n(len(b["alerts"]), _("{n} alert"), _("{n} alerts"))]))
        rows = narrow([
            {"research": x["research"], "status": x["status"],
             "pass": _("pass {n} open").format(n=x["open_pass"]) if x["open_pass"] else x["passes"],
             "pending": x["pending"], "rule": ", ".join(x["failed_rules"] or []) or None,
             "last_activity": views._when(x["last_activity"])} for x in b["researches"]], word)
        table = fill(self.query_one("#home-researches"), rows, key="research")
        ids = [x["research"] for x in rows]
        if self.app.research in ids:
            chose(table, ids.index(self.app.research))
        if self.app.project and self.app.research:
            self.fetch("events", self.app.research)
        style = human.Style(plain=self.app.plain)
        fill(self.query_one("#home-accounts"), narrow([
            {"account": a["name"], "gauge": human.bar(a["fraction"], style, 10),
             "left": f"{round(a['fraction'] * 100)} %"} for a in b["accounts"]], word),
            ["account", "gauge", "left"])
        fill(self.query_one("#home-alerts"), narrow([
            {"alert": _(views.ALERTS[a["kind"]]).format(what=a["what"], left=a.get("left"),
                                                       since=views._when(a.get("since")), days=a.get("days"))}
            for a in b["alerts"]], word), ["alert"])
        fill(self.query_one("#home-next"), narrow([{"command": x["command"], "why": _(x["why"])}
                                                   for x in b["next"]], word), ["command", "why"])


HISTORY_DAYS = 30   # the curve of an account on Quotas


def history(environ, project, days=HISTORY_DAYS):
    """{account: [the units counted each of the last ``days`` days, today last]}, from the user's
    counter, which the projects with the same key share (cli.md § 4.4): what ``usage`` counts,
    estimates and readings of balances left out. A ledger without a project catches nothing up:
    nothing is written."""
    from probandia.cli import usage_cmd
    from probandia.ledger import Ledger, _date
    from probandia.providers import catalogue
    from probandia.util import envfile

    ledger = Ledger(None, catalogue.load(), environ=envfile.merged(environ, project))
    today = usage_cmd._now().date()
    out = {}
    for e in ledger.entries():
        back = (today - _date(e["ts"]).date()).days
        if e.get("source") not in ("estimate", "sync") and 0 <= back < days:
            out.setdefault(ledger.pool(e["provider"]), [0] * days)[days - 1 - back] += e["units"]
    return out


class QuotasPane(Pane):
    """Every free tier, account by account (``usage``), with its gauge; the curve of the account
    chosen over 30 days; the calendar of the resets. ``/`` filters what was read, ``s``
    synchronises, ``c`` copies the view as CSV: the application writes no file (T98)."""

    needs_project = False
    watches = LEDGERS + SETTINGS
    accounts = {}   # {account: (name, unit)} of the lines shown

    def compose(self):
        from textual.widgets import Sparkline

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("filter: an account, a state, a section"))
        yield DataTable(id="quotas-accounts", cursor_type="row", zebra_stripes=True)
        yield Static("", id="quotas-history-head", markup=False)
        yield Sparkline([], id="quotas-history")
        yield DataTable(id="quotas-calendar", cursor_type="row")
        yield DataTable(id="quotas-out", cursor_type="row")

    def read(self, context, sync=False):
        d = self.app.engine("usage", *(["--sync"] if sync else []))
        return dict(d, history=history(self.app.ctx.environ, self.app.project))

    def on_data_table_row_highlighted(self, event):
        if event.data_table.id == "quotas-accounts" and current(event):
            self.show_history()

    def show_history(self):
        """The curve of the account under the cursor, a point a day; with ``--plain``, its total only."""
        from textual.widgets import Sparkline

        from probandia.i18n import formats

        table = self.query_one("#quotas-accounts", DataTable)
        account = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value if table.row_count else None
        points = (self.data or {}).get("history", {}).get(account) or [0] * HISTORY_DAYS
        curve = self.query_one("#quotas-history", Sparkline)
        curve.data, curve.display = points, account is not None and not self.app.plain   # its bars are blocks
        name, unit = self.accounts.get(account, (None, None))
        self.query_one("#quotas-history-head", Static).update(_("{account} · the last {days} days: {n} {unit}").format(
            account=name, days=HISTORY_DAYS, n=formats.number(sum(points)), unit=cell(unit, "unit")) if name else "")

    def copy(self):
        """``c``: the accounts as shown, filter included, as CSV in the clipboard; never in a file."""
        import csv

        table = self.query_one("#quotas-accounts", DataTable)
        buf = io.StringIO()
        sheet = csv.writer(buf, lineterminator="\n")
        sheet.writerow([str(c.label) for c in table.columns.values()])
        sheet.writerows([str(x) for x in table.get_row_at(i)] for i in range(table.row_count))
        self.app.copy_to_clipboard(buf.getvalue())
        self.app.notify(_("{n} accounts copied as CSV").format(n=table.row_count))

    def show(self, d):
        from probandia.cli import human

        from probandia.cli import usage_cmd
        from probandia.i18n import formats

        word = self.word()
        style = human.Style(plain=self.app.plain)   # #### . . . with --plain (T96)
        rows, kept = [], []
        for a in d.get("data", {}).get("accounts", []):
            section = a.get("section") or ""
            seen = (a.get("account"), a.get("name"), section, cell(a.get("state"), "state"),
                    _(usage_cmd.SECTION_TITLES[section]) if section in usage_cmd.SECTION_TITLES else "")
            if word and not any(word in str(x or "").lower() for x in seen):
                continue
            kept.append(a)
            share = (a["left"] / a["amount"]) if a.get("amount") and a.get("left") is not None else None
            money = a.get("unit") == "dollar"
            at, kind = a.get("renews_at"), a.get("renews")
            rows.append({"id": a.get("account"), "account": a["name"], "state": a["state"],
                         "left": formats.money(a["left"]) if money and a.get("left") is not None else a.get("left"),
                         "of": formats.money(a["amount"]) if money and a.get("amount") is not None else a.get("amount"),
                         "unit": a.get("unit"), "gauge": human.bar(share, style, 12) if share is not None else None,
                         "renews": (_("expires {when}").format(when=cell(at, "renews")) if kind == "expires" and at
                                    else _("one-off tier") if kind == "once" else at)})
        v = d.get("values", {})
        self.title(_("{ready} accounts ready of {n} · a reserve of {reserve} % is kept").format(
            ready=v.get("READY", 0), n=v.get("ACCOUNTS", 0), reserve=v.get("RESERVE_PERCENT", 0)))
        fill(self.query_one("#quotas-accounts"), rows, ["account", "state", "left", "of", "unit", "gauge", "renews"],
             key="id")
        self.accounts = {a["account"]: (a["name"], a.get("unit")) for a in kept}
        self.show_history()
        changes = {"reset": _("quota reset"), "expires": _("free tier ends")}   # the calendar, date by date
        fill(self.query_one("#quotas-calendar"), [
            {"date": a["renews_at"], "account": a["name"], "change": changes[a["renews"]]}
            for a in sorted(kept, key=lambda a: (a.get("renews_at") or "", a["name"]))
            if a.get("renews_at") and a.get("renews") in changes], ["date", "account", "change"])
        fill(self.query_one("#quotas-out"), d.get("data", {}).get("out_of_service", []),
             ["name", "reason", "remedy"])


class ConfirmScreen(ModalScreen):
    """A question answered yes or no, before an action runs (cli.md § 6.4, § 8.5)."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical { width: 72; max-width: 100%; height: auto; border: round $warning;
                               background: $surface; padding: 1 2; }
    ConfirmScreen #question { margin: 0 0 1 0; }
    ConfirmScreen .actions { align-horizontal: right; margin: 0; }
    """
    BINDINGS = [Binding("y", "answer(True)", _("Yes")), Binding("n,escape", "answer(False)", _("No"))]

    def __init__(self, question):
        super().__init__()
        self.question = question

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button

        with Vertical() as box:
            box.border_title = _("Confirm")
            yield Static(self.question, id="question", markup=False)   # an engine's question is text
            with Horizontal(classes="actions"):
                yield Button(_("No"), id="no")
                yield Button(_("Yes"), id="yes", variant="warning")

    def on_button_pressed(self, event):
        self.dismiss(event.button.id == "yes")

    def action_answer(self, yes):
        self.dismiss(yes)


class AskScreen(ModalScreen):
    """The values an action needs, asked before its confirmation: dismissed with {field: value},
    or None when cancelled. ``fields``: [(id, what it is, value, Input type, ``password`` for a
    value typed unseen, or [(label, value)] to choose from)]."""

    DEFAULT_CSS = """
    AskScreen { align: center middle; }
    AskScreen > Vertical { width: 72; max-width: 100%; height: auto; border: round $accent; background: $surface;
                           padding: 1 2; }
    """
    BINDINGS = [Binding("escape", "cancel", N_("Cancel"))]

    def __init__(self, question, fields):
        super().__init__()
        self.question, self.fields = question, fields

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button, Input, Select

        with Vertical():
            yield Static(self.question, markup=False)
            for fid, what, value, kind in self.fields:
                yield Static(what, markup=False)
                yield (Select(kind, value=value, allow_blank=False, id=fid) if isinstance(kind, list)
                       else Input(value=value, id=fid, password=True) if kind == "password"
                       else Input(value=value, id=fid, type=kind))
            with Horizontal(classes="actions"):
                yield Button(_("Continue"), id="ask-next", variant="primary")
                yield Button(_("Cancel"), id="ask-cancel")

    def answered(self):
        return {fid: str(self.query_one(f"#{fid}").value).strip() for fid, *_rest in self.fields}

    def on_input_submitted(self, event):
        event.stop()
        self.dismiss(self.answered())

    def on_button_pressed(self, event):
        event.stop()
        self.dismiss(self.answered() if event.button.id == "ask-next" else None)

    def action_cancel(self):
        self.dismiss(None)


# 3 Researches, the Report in the file of a research (CLI15-T3)

ACTIONS = {"pause": N_("Pause"), "close": N_("Close"), "fork": N_("Fork"), "apply": N_("Accept"),
           "drop": N_("Set aside")}
VERDICTS = {"would-apply": N_("every rule of apply passes"), "would-reject": N_("a rule of apply fails")}
GRADES = {"essential": N_("essential"), "advanced": N_("advanced"), "expert": N_("expert")}
RENDER = N_("Render the report")
LOG_PAGE = 200   # the events of a research shown at first, and loaded more at a time (T91)
LOG_COLUMNS = ["time", "pass", "type", "what"]


def last_lines(path, count, end=None):
    """(the last ``count`` complete lines of ``path`` before byte ``end``, each with the byte
    it starts at; the byte the first starts at; the byte after the last). ``end`` None reads
    up to the end of the file, a line half written left for the next look. Read backwards,
    by blocks: a log of any length costs only the lines shown."""
    try:
        fh = open(path, "rb")
    except FileNotFoundError:
        return [], end or 0, end or 0
    with fh:
        partial = end is None
        if partial:
            end = fh.seek(0, os.SEEK_END)
        pos, chunk = end, b""
        while pos > 0 and chunk.count(b"\n") <= count:
            size = min(1 << 16, pos)
            pos -= size
            fh.seek(pos)
            chunk = fh.read(size) + chunk
    if partial:
        keep = chunk.rfind(b"\n") + 1
        end -= len(chunk) - keep
        chunk = chunk[:keep]
    lines, at = [], pos
    for raw in chunk.split(b"\n")[:-1]:
        lines.append((at, raw))
        at += len(raw) + 1
    lines = lines[1 if pos > 0 else 0:][-count:]   # the first began before the blocks read
    return [(at, raw.decode("utf-8")) for at, raw in lines], (lines[0][0] if lines else end), end


def lines_after(path, start):
    """(the complete lines of ``path`` from byte ``start``, each with the byte it starts at;
    the byte after them): an append-only file is never read twice, a line half written waits."""
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            chunk = fh.read()
    except FileNotFoundError:
        return [], start
    keep = chunk.rfind(b"\n") + 1
    out, at = [], start
    for raw in chunk[:keep].split(b"\n")[:-1]:
        out.append((at, raw.decode("utf-8")))
        at += len(raw) + 1
    return out, start + keep


def event_rows(lines):
    """The rows of the log table, keyed by the byte where each event starts."""
    from probandia.cli.browse_cmd import event_row

    return [dict(event_row(e), what=event_words(e), at=at) for at, e in ((at, json.loads(x)) for at, x in lines)]


def event_words(e):
    """What an event says, in a few words, as ``research log`` says it, but in clear: a
    status in words, values without their keys (T95)."""
    from probandia.cli.browse_cmd import event_what

    p = e.get("payload") or {}
    if isinstance(p.get("fact"), dict):
        return f"{p['fact'].get('id')} · {cell(p['fact'].get('status'), 'status')}"
    if e["type"] == "verify.run":
        return ", ".join(k for k, v in (p.get("results") or {}).items() if v == "FAIL") or cell("PASS", "status")
    if isinstance(p.get("section"), dict) or any(p.get(k) for k in ("summary", "search", "proposal", "plan",
                                                                     "root", "text")):
        return event_what(e)
    return " · ".join(str(v) for v in p.values() if isinstance(v, (str, int, float)))[:80]


class ResearchesPane(Pane):
    """The researches, filtered; the file of the one selected, in tabs: its passes and its
    last events, more on demand, then the new ones as they come (T91); its report; its team."""

    parts = ("main", "file", "log", "earlier")
    indicator = "#researches-list"
    file = "#research-tabs"
    files_only = ("log", "earlier")   # events.jsonl read from its end: no command to wait for
    watches = RESEARCHES + INDEXES + PROPOSALS + LOCKS + (("project", ".probandia/tokens.jsonl"),)
    offset = None   # the byte of events.jsonl read up to
    first = 0       # the byte of the first event shown
    log_of = None   # the research of the events shown
    passes = None   # the passes done of the research shown
    events = ()     # their rows

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("filter: a research, a family, a status"))
        yield DataTable(id="researches-list", cursor_type="row", zebra_stripes=True)
        yield Static("", id="research-head", markup=False)
        with TabbedContent(id="research-tabs"):
            with TabPane(_(FILE_TABS[0][1]), id="part-file"):
                with VerticalScroll(id="research-file"):
                    yield Static("", id="research-lock")
                    with Horizontal(classes="actions"):
                        for name in ("pause", "close", "fork"):
                            yield Button(_(ACTIONS[name]), id=f"research-{name}",
                                         variant="warning" if name == "close" else "default")
                    for name in ("passes", "verify", "tokens"):
                        yield titled(DataTable(id=f"research-{name}", cursor_type="row"), _(SECTIONS[name]))
                    earlier = Button(_("Load {n} earlier events").format(n=LOG_PAGE), id="research-earlier")
                    earlier.display = False
                    yield earlier
                    yield titled(DataTable(id="research-log", cursor_type="row"), _(SECTIONS["log"]))
            for name, title in FILE_TABS[1:]:
                with TabPane(_(title), id=f"part-{name}"):
                    yield PANES[name](id=f"pane-{name}")

    def refresh_data(self, force=False):
        if self.app.project and self.app.research:   # the log first: it costs least, and it moves
            self.fetch("log", self.app.research, force=force, start=self.start(self.app.research))
        super().refresh_data(force=force)

    def start(self, research):
        """Where to read the log of ``research`` from: after its events shown, or None."""
        return self.offset if research == self.log_of else None

    def on_data_table_row_highlighted(self, event):
        if event.data_table.id == "researches-list" and event.row_key is not None and current(event):
            if self.app.research != event.row_key.value:
                self.app.research = event.row_key.value
                self.fetch("file", self.app.research)
                self.fetch("log", self.app.research, start=None)
                self.follow()

    def follow(self):
        """The tab of the file shown, its report or its team, reads the research chosen."""
        for pane in self.app.shown():
            if pane is not self:
                pane.refresh_data()

    def read(self, context):
        return self.app.engine("research", "list").get("data", {}).get("researches", [])

    def show(self, every):
        from probandia.cli.views import _plural

        columns = ["research", "family", "status", "passes", "pending", "last_activity"]
        rows = narrow(every, self.word(), ["research", "family", "status"])
        self.title(_plural(len(rows), _("{n} research"), _("{n} researches")))
        table = fill(self.query_one("#researches-list"), rows, columns, key="research")
        before = self.app.research
        gone = self.app.research if self.app.research not in [None, *[x["research"] for x in every]] else None
        if gone:   # removed while it was shown (T87)
            self.app.research = None
        ids = [x["research"] for x in rows]
        if rows and self.app.research not in ids:
            self.app.research = rows[0]["research"]
        if self.app.research in ids:
            chose(table, ids.index(self.app.research))
        if gone:
            message = _("The research {research} no longer exists").format(research=gone)
            if self.app.research:
                self.app.notify(message, severity="warning")
            else:
                self.title(message)
        if self.app.research:
            self.fetch("log", self.app.research, start=self.start(self.app.research))
            self.fetch("file", self.app.research)
        else:
            for part in ("file", "log"):
                self.reads[part].stamp = None
            self.clear_file()
        if self.app.research != before:
            self.follow()

    def clear_file(self):
        """No research to show: its file is emptied."""
        for sid in ("#research-head", "#research-lock"):
            self.query_one(sid, Static).update("")
        for name in ("passes", "verify", "tokens", "log"):
            fill(self.query_one(f"#research-{name}"), [], [])
        self.events, self.first, self.log_of, self.offset = (), 0, None, None
        self.query_one("#research-earlier").display = False

    def read_file(self, research):
        """The file of ``research``, and who else holds it."""
        return {"research": research, "answer": self.app.engine("research", "show", research),
                "held": self.app.holder(research)}

    def read_log(self, research, start=None):
        """The events of ``research`` written after byte ``start``; when None, its last
        ``LOG_PAGE`` events, wherever its log starts."""
        from probandia.research import find_research

        path = find_research(self.app.project, research).events_path
        if start is None:
            lines, first, end = last_lines(path, LOG_PAGE)
        else:
            (lines, end), first = lines_after(path, start), None
        return {"research": research, "start": start, "first": first, "end": end, "rows": event_rows(lines)}

    def open_file(self):
        """Enter on a research: the focus in the tab of its file shown."""
        tabs = self.query_one("#research-tabs", TabbedContent)
        self.app.focus_in(tabs.active_pane)
        tabs.scroll_visible(top=True, animate=False)

    def show_log(self, d):
        if d["research"] != self.app.research:
            return   # another research was chosen meanwhile
        log = self.query_one("#research-log", DataTable)
        if d["start"] is None:   # a research newly shown: its last events
            self.events, self.first, self.log_of = list(d["rows"]), d["first"], d["research"]
            fill(log, self.events, LOG_COLUMNS, key="at")
            follow = True
        elif d["start"] == self.offset and self.log_of == d["research"]:   # what came since
            follow = log.cursor_row >= log.row_count - 1   # the last event under the cursor: the next ones too
            for x in d["rows"]:
                log.add_row(*cells(x, LOG_COLUMNS), key=str(x["at"]))
            self.events += d["rows"]
        else:   # read from another place meanwhile: read again
            self.reads["log"].stamp = None
            return
        self.offset = d["end"]
        if d["rows"] and follow:
            log.move_cursor(row=log.row_count - 1)
        self.query_one("#research-earlier").display = self.first > 0

    def earlier(self):
        """``Load earlier events``: the ``LOG_PAGE`` events before the first shown."""
        if self.log_of and self.first > 0:
            self.fetch("earlier", (self.log_of, self.first), force=True)

    def read_earlier(self, where):
        from probandia.research import find_research

        research, before = where
        lines, first, _end = last_lines(find_research(self.app.project, research).events_path, LOG_PAGE, before)
        return {"research": research, "before": before, "first": first, "rows": event_rows(lines)}

    def show_earlier(self, d):
        if d["research"] != self.log_of or d["before"] != self.first:
            return   # the log changed meanwhile
        self.events = d["rows"] + list(self.events)
        self.first = d["first"]
        fill(self.query_one("#research-log", DataTable), self.events, LOG_COLUMNS, key="at")   # the cursor stays
        self.query_one("#research-earlier").display = self.first > 0

    def failed(self, part, context, err):
        if part in ("log", "earlier"):   # said in the log's place, unless the research is gone
            if context == self.app.research or (part == "earlier" and context[0] == self.log_of):
                fill(self.query_one("#research-log", DataTable), [{"what": said(err)}], ["what"])
                self.log_of = self.offset = None   # its events read anew next time
                self.query_one("#research-earlier").display = False
            return
        super().failed(part, context, err)

    def show_file(self, f):
        if f["research"] != self.app.research:
            return   # another research was chosen meanwhile
        from probandia.cli import views

        d = f["answer"]
        v, data, n = d.get("values", {}), d.get("data", {}), views._plural
        status = v.get("RESEARCH_STATUS")
        self.query_one("#research-head", Static).update(v.get("QUESTION", "") + "\n" + " · ".join([
            _(views.RESEARCH_STATUSES.get(status, status or "?")),
            n(v.get("PASSES", 0), _("{n} pass done"), _("{n} passes done")),
            n(v.get("FACTS", 0), _("{n} fact"), _("{n} facts")),
            n(v.get("NEGATIVES", 0), _("{n} negative"), _("{n} negatives")),
            n(v.get("HYPOTHESES", 0), _("{n} open hypothesis"), _("{n} open hypotheses")),
            n(v.get("GAPS", 0), _("{n} gap"), _("{n} gaps")), *notes(d)]))   # sentences, not the contract (T94)
        fill(self.query_one("#research-passes"), data.get("passes", []),
             ["pass", "duration", "units", "native", "summary"])
        fill(self.query_one("#research-verify"), data.get("verify", []), ["rule", "status"])
        fill(self.query_one("#research-tokens"), data.get("tokens", []))
        self.passes = v.get("PASSES")   # the pass a fork starts from, by default
        self.app.grey(self, f["held"], ("research-pause", "research-close", "research-fork"), "research-lock")


class ReportPane(Pane):
    """The report of the research selected, rendered, with its table of contents; rendered
    again only when its text changed (T91)."""

    watches = RESEARCHES[:1] + (("project", RESEARCH + "report/*"),)
    rendered = None   # the text the viewer shows
    rendered_from = None   # (path, mtime, size) of the file it came from

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folders = {}   # {research: its folder}, found once

    def compose(self):
        from textual.widgets import Button, MarkdownViewer

        yield Static("", classes="title", markup=False)
        yield Button(_(RENDER), id="report-render")
        yield MarkdownViewer("", id="report-viewer", show_table_of_contents=True)

    def report_path(self, name="report.md", research=None):
        from probandia.research import find_research

        research = research or self.app.research
        if not research:
            return None
        folder = self.folders.get(research)
        if folder is None or not os.path.isdir(folder):
            folder = self.folders[research] = find_research(self.app.project, research).folder
        return os.path.join(folder, "report", name)

    def context(self):
        return self.app.research

    def read(self, research):
        if not research:
            d = self.app.engine("research", "list").get("data", {}).get("researches", [])
            research = d[0]["research"] if d else None
        path = self.report_path(research=research) if research else None
        try:
            st = os.stat(path) if path else None
        except OSError:
            st = None
        if st is None:
            return {"research": research, "text": None, "source": None}
        source = (path, st.st_mtime_ns, st.st_size)
        if source == self.rendered_from:   # the report shown: nothing to read
            return {"research": research, "same": True}
        with open(path, encoding="utf-8") as fh:
            return {"research": research, "text": fh.read(), "source": source}

    def show(self, d):
        from textual.widgets import MarkdownViewer

        if not self.app.research:
            self.app.research = d["research"]
        if not d.get("same"):
            if (d["text"] or "") != self.rendered:
                self.rendered = d["text"] or ""
                self.query_one("#report-viewer", MarkdownViewer).document.update(self.rendered)
            self.rendered_from = d["source"]
        if d.get("same") or d["text"] is not None:
            self.title(_("Report of {research} · o opens it in the browser").format(research=d["research"]))
        else:
            self.title(_("No report yet: the button {action} writes it").format(action=_(RENDER)))


# 4 Family and 5 Proposals (CLI15-T4)

GENERATIONS = 8   # the Sosa tree stops there


def sosa_tree(persons, root):
    """[(sosa, person)] of ``root`` and their known ancestors: 1 the root, 2n the
    father and 2n + 1 the mother of n."""
    by_id = {p["id"]: p for p in persons}
    out, todo = [], [(1, root)]
    while todo:
        n, pid = todo.pop(0)
        p = by_id.get(pid)
        if p is None:
            continue
        out.append((n, p))
        if n < 2 ** (GENERATIONS - 1):
            parents = p.get("parents") or {}
            todo += [(2 * n, parents.get("father")), (2 * n + 1, parents.get("mother"))]
    return out


def person_label(p, living):
    """A person's name and years, or the mask of a presumed-living person."""
    from probandia.cli.browse_cmd import BIRTH, END, _first_date, _name

    if p["id"] in living:
        return _("Living person")
    born, died = _first_date(p, BIRTH), _first_date(p, END)
    years = f" ({genealogical(born) if born else '?'}-{genealogical(died) if died else ''})"
    return _name(p) + (years if born or died else "")


class FamilyPane(Pane):
    """The persons of a family by Sosa numbers, from a root: the subject of the research chosen,
    or a person chosen in their file (T101); a selector of the family; the file of the person
    selected, whose facts are cited (T100); a search. ``o`` opens the family's HTML tree."""

    parts = ("main", "person", "find")
    indicator = "#family-tree"
    narrows = False   # its filter finds persons in the index, on Enter
    watches = INDEXES + SETTINGS
    living = ()
    nodes = {}   # {sosa: node} of the tree shown
    drawn = None   # (family, root) of the tree shown
    families = None   # the families of the selector
    picked = None   # the family chosen in the selector, over the research's
    root = None   # the person chosen as the root, over the research's subject
    facts = ()   # the facts of the person shown, which Cite cites; none for a presumed-living person

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button, Select, Tree

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("find a person: a surname, a given name"))
        yield Select([], id="family-choice", prompt=_("Family"), compact=True)
        found = DataTable(id="family-found", cursor_type="row")
        found.display = False
        yield found
        with Horizontal(id="family-body"):
            tree = Tree(_("Ancestors"), id="family-tree")
            tree.styles.width = f"{self.app.look['tree_width']}%"   # the theme's (config.themes)
            if self.app.plain:   # its guides and its arrows in ASCII (T96)
                tree.LINES = dict.fromkeys(("default", "bold", "double"), ("  ", "| ", "`-", "|-"))
                tree.ICON_NODE, tree.ICON_NODE_EXPANDED = "+ ", "- "
            yield tree
            with VerticalScroll(id="family-person"):
                yield Static("", id="person-head", markup=False)
                with Horizontal(classes="actions"):
                    yield Button(_("Cite"), id="person-cite")
                    yield Button(_("Root of the tree"), id="person-root")
                yield Static("", id="person-citation", markup=False)
                for name in ("facts", "relatives", "hypotheses", "negatives", "gaps"):
                    yield titled(DataTable(id=f"person-{name}", cursor_type="row"), _(SECTIONS[name]))

    def context(self):
        return self.app.research, self.picked

    def read(self, context):
        from probandia import events, lifecycle, treeview
        from probandia.indexes import FamilyIndexes
        from probandia.report.living import living_set
        from probandia.research import find_research

        research, picked = context
        families = sorted(lifecycle.families(self.app.project))
        res = find_research(self.app.project, research) if research else None
        fid = picked if picked in families else res.family if res else families[0] if families else None
        if not fid:
            return {"family": None, "families": families}
        persons = FamilyIndexes(self.app.project, fid).items("persons")
        # default_root reads only the branches added: the other lines are not decoded (20 000 events: 0.2 s)
        log = ([json.loads(x) for x in events.read_lines(res.events_path) if '"branch.added"' in x]
               if res and res.family == fid else ())
        return {"family": fid, "families": families, "persons": persons,   # the subject: the root of its tree
                "subject": treeview.default_root(persons, log) if persons else None,
                "living": living_set(persons, self.app.ctx.config.get("privacy.living_years") or 100)}

    def on_select_changed(self, event):
        if event.select.id == "family-choice" and isinstance(event.value, str) and event.value != (
                self.data or {}).get("family"):
            self.picked, self.root = event.value, None
            self.refresh_data()

    def show(self, d):
        from textual.widgets import Select, Tree

        choice = self.query_one("#family-choice", Select)
        with choice.prevent(Select.Changed):
            if d["families"] != self.families:
                self.families = d["families"]
                choice.set_options([(f, f) for f in self.families])
            if d["family"] and choice.value != d["family"]:
                choice.value = d["family"]
        persons = d.get("persons") or []
        root = self.root if self.root in {p["id"] for p in persons} else d.get("subject")
        tree = self.query_one("#family-tree", Tree)
        # read again, the tree keeps its folded branches and its cursor (T89); from another root, not
        before = self.nodes if self.drawn == (d["family"], root) else {}
        unfolded = {n for n, node in before.items() if node.is_expanded}
        at = next((n for n, node in before.items() if node is tree.cursor_node), None)
        with tree.prevent(Tree.NodeHighlighted):
            tree.clear()
        self.nodes = {}
        if not d["family"]:
            self.title(_("No family in this project yet"))
            return
        self.living = d["living"]
        self.title(_("Family {family} · {n} persons").format(family=d["family"], n=len(persons)))
        another = self.drawn is None or self.drawn[0] != d["family"]
        self.drawn = (d["family"], root)
        if not persons:
            return
        nodes = self.nodes
        for n, p in sosa_tree(persons, root):
            text = f"{n}  {person_label(p, self.living)}"
            parent = nodes.get(n // 2, tree.root) if n > 1 else tree.root
            nodes[n] = parent.add(text, data=p["id"], expand=n in unfolded if n in before else True)
        tree.root.expand()
        if at in nodes:   # its line is known once the tree is drawn
            tree.call_after_refresh(tree.move_cursor, nodes[at])
        if another or not str(self.query_one("#person-head", Static).content):
            self.fetch("person", (d["family"], root))

    def make_root(self):
        """Root of the tree: the person whose file is shown, numbered 1 (T101)."""
        f = self.reads["person"].data
        if f and self.data and f["family"] == self.data.get("family"):
            self.root = f["person"]
            self.guard(self.show, self.data)

    def open_tree(self):
        """``o``: the family's HTML tree in the browser. ``tree`` writes it first, after a confirmation,
        when it is missing or older than the index (T100)."""
        family = (self.data or {}).get("family")
        if not family:
            self.app.notify(_("No family in this project yet"), severity="warning")
            return
        folder = os.path.join(self.app.project, "families", family)
        path = os.path.join(folder, "trees", "tree.html")
        changed = max((os.path.getmtime(p) for p in glob.glob(os.path.join(glob.escape(folder), "index", "*.yaml"))),
                      default=0)
        if os.path.isfile(path) and os.path.getmtime(path) >= changed:
            browse(path)
            return
        self.app.act(_("Write the tree of the family {family}, then open it?").format(family=family),
                     "tree", "--family", family, "--format", "html",
                     then=lambda d: browse(path) if d.get("status") != "FAIL" else None)

    def on_tree_node_highlighted(self, event):
        if event.node.data and self.drawn:
            self.fetch("person", (self.drawn[0], event.node.data))

    def on_input_submitted(self, event):
        if self.drawn:
            self.fetch("find", (self.drawn[0], event.value))

    def read_find(self, asked):
        family, value = asked
        return self.app.engine("find", value, "--family", family).get("data", {}).get(
            "persons", []) if value.strip() else []

    def show_find(self, found):
        rows = []
        for x in found:
            masked = x["person"] in self.living
            rows.append({"person": x["person"], "name": _("Living person") if masked else x["name"],
                         "born": None if masked else x["born"], "died": None if masked else x["died"],
                         "match": x["match"]})
        table = fill(self.query_one("#family-found"), rows, ["person", "name", "born", "died", "match"], key="person")
        table.display = bool(rows)   # shown only when a search found someone: the tree keeps the room

    def on_data_table_row_selected(self, event):
        if event.data_table.id == "family-found" and self.drawn:
            self.fetch("person", (self.drawn[0], event.row_key.value))
            self.query_one("#person-facts").focus()   # Enter opens the file of the person (T93)

    def read_person(self, which):
        family, pid = which
        return {"family": family, "person": pid, "answer": self.app.engine("person", pid, "--family", family)}

    def show_person(self, f):
        pid, d = f["person"], f["answer"]
        data, v = d.get("data", {}), d.get("values", {})
        cite = self.query_one("#person-cite")
        self.query_one("#person-citation", Static).update("")
        if v.get("LIVING") or pid in self.living:   # masked as in the reports: nothing to cite
            self.facts, cite.display = (), False
            self.query_one("#person-head", Static).update(_("Living person: nothing is shown"))
            for name in ("facts", "relatives", "hypotheses", "negatives", "gaps"):
                fill(self.query_one(f"#person-{name}"), [], [])
            return
        self.facts, cite.display = data.get("facts", []), True
        self.query_one("#person-head", Static).update(f"{v.get('NAME', '')} · {pid}")
        relatives = [dict(x, name=_("Living person") if x["person"] in self.living else x["name"])
                     for x in data.get("relatives", [])]
        fill(self.query_one("#person-facts"), self.facts)
        fill(self.query_one("#person-relatives"), relatives, ["relation", "person", "name"])
        for name in ("hypotheses", "negatives", "gaps"):
            fill(self.query_one(f"#person-{name}"), data.get(name, []))

    def copy(self):
        """``c`` and Cite: the citation of the fact under the cursor, as ``person`` formed it, shown in
        full and copied, without asking the engine again (T100)."""
        table = self.query_one("#person-facts", DataTable)
        if not self.facts or not table.row_count:
            return
        citation = self.facts[table.cursor_row].get("citation")
        if not citation:
            self.app.notify(_("This fact has no source to cite"), severity="warning")
            return
        self.query_one("#person-citation", Static).update(citation)
        self.app.copy_to_clipboard(citation)
        self.app.notify(_("Citation copied"))


class ProposalsPane(Pane):
    """The proposals waiting, read one at a time with what applying it would change in the indexes,
    then accepted (``a``) or set aside with a reason (``x``); ``n`` and ``p`` go from one to the next,
    and once one is done the next one is shown (T102)."""

    parts = ("main", "file")
    watches = PROPOSALS + INDEXES + LOCKS
    selected = None   # (proposal, research)
    details = ("changes", "rules", "facts", "sources", "searches")

    indicator = "#proposals-list"
    file = "#proposal-changes"

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("filter: a proposal, a research, an author"))
        yield DataTable(id="proposals-list", cursor_type="row", zebra_stripes=True)
        yield Static("", id="proposal-head", markup=False)
        yield Static("", id="proposal-lock")
        with Horizontal(classes="actions"):
            yield Button(_(ACTIONS["apply"]), id="proposal-apply", variant="success")
            yield Button(_(ACTIONS["drop"]), id="proposal-drop", variant="warning")
        for name in self.details:
            yield DataTable(id=f"proposal-{name}", cursor_type="row")

    def step(self, step):
        """``n`` and ``p``: the next or the previous proposal, read."""
        table = self.query_one("#proposals-list", DataTable)
        if table.row_count:
            table.move_cursor(row=max(0, min(table.cursor_row + step, table.row_count - 1)))

    def read(self, context):
        return self.app.engine("proposals").get("data", {}).get("proposals", [])

    def show(self, every):
        from probandia.cli.views import _plural

        self.title(_plural(len(every), _("{n} proposal waiting"), _("{n} proposals waiting")))
        columns = ["proposal", "research", "pass", "author", "facts", "verdict"]
        rows = narrow(every, self.word(), columns)
        table = fill(self.query_one("#proposals-list"), rows, columns, key=lambda x: f"{x['proposal']}|{x['research']}")
        keys = [(x["proposal"], x["research"]) for x in rows]
        # the cursor's: fill kept it on its proposal, or on its line once that one is accepted or set aside
        # (the next one took it); n or p pressed just before this read keeps its move, its highlight not read yet
        self.selected = keys[min(table.cursor_row, len(keys) - 1)] if keys else None
        if self.selected:
            self.fetch("file", self.selected)
        else:
            self.reads["file"].stamp = None
            self.query_one("#proposal-head", Static).update(_("Nothing to review"))
            for name in self.details:
                fill(self.query_one(f"#proposal-{name}"), [], [])
            self.app.grey(self, None, ("proposal-apply", "proposal-drop"), "proposal-lock")

    def on_data_table_row_highlighted(self, event):
        if event.data_table.id == "proposals-list" and event.row_key is not None and current(event):
            chosen = tuple(event.row_key.value.split("|"))
            if chosen != self.selected:
                self.selected = chosen
                self.fetch("file", chosen)

    def read_file(self, selected):
        """The proposal ``selected``, and who else holds its research: a proposal of a
        research an agent holds is read, not applied nor set aside."""
        return {"selected": selected, "answer": self.app.engine("proposals", "show", selected[0]),
                "held": self.app.holder(selected[1])}

    def show_file(self, f):
        if f["selected"] != self.selected:
            return   # another proposal was chosen meanwhile
        d = f["answer"]
        v = d.get("values", {})
        verdict = v.get("VERDICT")
        self.query_one("#proposal-head", Static).update("\n".join([" · ".join(
            [_(VERDICTS.get(verdict, verdict or "?")), _("pass {n}").format(n=v.get("PASS", "?")),
             str(v.get("AUTHOR", "?"))])] + notes(d)))
        for name in self.details:
            fill(self.query_one(f"#proposal-{name}"), d.get("data", {}).get(name, []))
        self.app.grey(self, f["held"], ("proposal-apply", "proposal-drop"), "proposal-lock")


# Providers and keys (in 2 Quotas); 6 Config: Settings, Library, Diagnostic; the Team, in the file of a
# research (CLI15-T5)


class TablesPane(Pane):
    """A screen of tables, one per ``data`` table of a command."""

    tables = ()     # (id, data table name, columns or None)
    command = ()    # the engine command
    buttons = ()    # (id, label); None starts another row: four buttons hold in 80 columns
    notes = ()      # the ids of the texts under the buttons: what an action or an Enter said

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("filter: a name, a state, a value"))
        yield from self.controls()
        rows = [[]]
        for b in self.buttons:
            rows.append([]) if b is None else rows[-1].append(b)
        for row in rows if self.buttons else []:
            with Horizontal(classes="actions"):
                for bid, text in row:
                    yield Button(_(text), id=bid)
        for nid in self.notes:
            yield Static("", id=nid, classes="note", markup=False)
        for tid, _name, _columns in self.tables:
            yield DataTable(id=tid, cursor_type="row", zebra_stripes=True)

    def controls(self):
        """What narrows the list besides the filter: choices under it."""
        return ()

    def read(self, context):
        d = self.app.engine(*self.command)
        return {"status": d.get("status"), "values": d.get("values", {}), "lines": notes(d),
                "tables": {tid: d.get("data", {}).get(name, []) for tid, name, _columns in self.tables}}

    def show(self, d):
        for tid, _name, columns in self.tables:
            fill(self.query_one(f"#{tid}"), narrow(d["tables"].get(tid, []), self.word(), columns), columns)
        self.title(self.heading(d))

    def heading(self, d):
        """Its title: a sentence of the values its command answered, never their keys (T94)."""
        return ""

    def chosen(self, tid):
        """The first cell of the row under the cursor of table ``tid``, or None."""
        t = self.query_one(f"#{tid}", DataTable)
        return str(t.get_row_at(t.cursor_row)[0]) if t.row_count else None


class ProvidersPane(TablesPane):
    """The catalogue of free tiers and the keys: names and fingerprints, never a value. A key is checked by
    a free reading of its account, over the network, once confirmed; Sign up opens a provider's page (T103).
    Set the key writes one, typed in a masked field that only ``keys set`` reads; Remove the key takes it out of
    its .env (``keys unset``); Monthly cap and Cache life set the provider's own settings (``config set``)."""

    needs_project = False
    watches = SETTINGS + LEDGERS
    command = ("providers", "list")
    tables = (("providers-list", "providers", ["provider", "name", "kind", "family", "unit", "amount", "state",
                                               "stale"]),
              ("providers-keys", "keys", ["variable", "present", "source", "fingerprint", "unlocks", "outcome"]))
    buttons = (("provider-enable", N_("Enable")), ("provider-disable", N_("Disable")),
               ("provider-check", N_("Check the key")), ("provider-signup", N_("Sign up")), None,
               ("key-set", N_("Set the key")), ("key-unset", N_("Remove the key")),
               ("provider-cap", N_("Monthly cap")), ("provider-ttl", N_("Cache life")))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checks = {}   # {variable: what keys check answered}, while the application runs

    def read(self, context):
        d = super().read(context)
        stale = {x["provider"] for x in self.app.engine("providers", "stale").get("data", {}).get("stale", [])}
        d["tables"]["providers-list"] = [dict(x, stale=x["provider"] in stale) for x in d["tables"]["providers-list"]]
        keys = self.app.engine("keys")
        d["tables"]["providers-keys"] = keys.get("data", {}).get("keys", [])
        d["keys"] = keys.get("values", {})
        d["where"] = self.app.engine("keys", "where").get("data", {}).get("files", [])
        return d

    def set_key(self):
        """Set the key: the .env it goes to (the user's, or in a project the project's), then ``keys set`` once
        confirmed, the key typed in the masked field the command opens: it never leaves the command."""
        variable = self.chosen("providers-keys")
        files = {x["file"]: x["path"] for x in (self.data or {}).get("where", [])}
        if not variable or not files:
            return

        def write(where):
            self.app.act(_("Write the key {variable} in {path}? You type it next, unseen.").format(
                variable=variable, path=files[where]), "keys", "set", variable,
                *(["--in-project"] if where == "project" else []), asks=True)

        if "project" not in files:
            write("user")
            return
        self.app.push_screen(AskScreen(_("Set the key {variable}").format(variable=variable), [
            ("key-where", _("Written in"), "user", [(cell(f, "source"), f) for f in ("user", "project")])]),
            lambda answer: answer and write(answer["key-where"]))

    def unset_key(self):
        """Remove the key: from the .env it comes from, once confirmed (``keys unset``)."""
        variable = self.chosen("providers-keys")
        row = next((x for x in (self.data or {}).get("tables", {}).get("providers-keys", [])
                    if x["variable"] == variable), None)
        if row is None:
            return
        if row.get("source") not in ("user", "project"):
            self.app.notify((_("{variable} comes from the environment, not from a .env file") if row["present"]
                             else _("{variable} is not set")).format(variable=variable), severity="warning")
            return
        self.app.act(_("Remove the key {variable} from {path}?").format(variable=variable, path=row["file"]),
                     "keys", "unset", variable, *(["--in-project"] if row["source"] == "project" else []))

    def show(self, d):
        keys = [dict(x, outcome=self.checks.get(x["variable"])) for x in d["tables"]["providers-keys"]]
        super().show(dict(d, tables=dict(d["tables"], **{"providers-keys": keys})))

    def checked(self, d):
        """What ``keys check`` answered, in the line of the key: valid, refused, not subscribed..."""
        self.checks.update({x["variable"]: x["outcome"] for x in (d.get("data") or {}).get("checks", [])})

    def heading(self, d):
        v, k = d["values"], d.get("keys", {})
        return " · ".join([_("{n} providers in the catalogue · {ready} ready").format(
            n=v.get("PROVIDERS", 0), ready=v.get("READY", 0)), _("{n} of {total} keys set").format(
            n=k.get("PRESENT", 0), total=k.get("KEYS", 0)), _("keys read from {files}").format(
            files=", ".join(x["path"] for x in d.get("where", []) if x["present"]) or _("no .env file yet"))])


def refusal(setting, key, text):
    """Why the registry refuses ``text`` for ``key``, as ``config set`` says it; None when it takes it."""
    from probandia import config as cfgmod

    try:
        cfgmod.check_value(setting, cfgmod.parse_text(setting, text))
        return None
    except ValueError:
        return _("invalid value {value} for {key}; allowed: {allowed}").format(
            value=repr(text), key=key, allowed=setting.describe_values())


FLAGS = {"project": (), "local": ("--local",), "user": ("--user",)}   # the file config set writes, by its layer


class ChangeScreen(ModalScreen):
    """Change: one setting's value, by the control of its type in the registry: a box for true or false, a
    list for one of its values, a whole number within its bounds, boxes for the items of a list (moved up
    or down when their order counts), else a text; and the file it goes to. A value the registry refuses
    is said here, with its reason, and the window stays. Dismissed with {value, layer}, or None."""

    DEFAULT_CSS = """
    ChangeScreen { align: center middle; }
    ChangeScreen > Vertical { width: 72; max-width: 100%; height: auto; max-height: 100%; border: round $accent;
                              background: $surface; padding: 0 1; }
    ChangeScreen SelectionList { height: auto; max-height: 10; }
    ChangeScreen #change-error { color: $error; }
    """
    BINDINGS = [Binding("escape", "cancel", N_("Cancel"))]

    def __init__(self, key, value, files, layer):
        from probandia.config import registry

        super().__init__()
        self.key, self.setting, self.value = key, registry.lookup(key), value
        self.files, self.first = files, layer   # {layer: path} it may write, the one chosen first
        items = self.setting.items if self.setting.type == "list" else None
        self.order = (list(value or []) + [i for i in items if i not in (value or [])]) if items else None

    def compose(self):
        from textual.containers import Horizontal
        from textual.widgets import Button, Checkbox, Input, Select, SelectionList

        s, v = self.setting, self.value
        with Vertical() as box:
            box.border_title = _("Change {key}").format(key=self.key)
            yield Static(_(s.help), markup=False)
            if s.type == "int" and s.values:
                yield Static(_("a whole number from {min} to {max}").format(min=s.values[0], max=s.values[1]),
                             markup=False)
            elif s.type == "str" or (s.type == "list" and not s.items):
                yield Static(_("allowed: {values}").format(values=s.describe_values()), markup=False)
            if s.type == "bool":
                yield Checkbox(self.key, value=bool(v), id="change-value")
            elif s.type == "enum":
                yield Select([(x or _("(empty)"), x) for x in s.values], value=v if v in s.values else s.values[0],
                             allow_blank=False, id="change-value")
            elif self.order is not None:
                yield SelectionList(*[(i, i, i in (v or [])) for i in self.order], id="change-value")
                if s.ordered:
                    yield Static(_("In order: the first is tried first"), markup=False)
                    with Horizontal(classes="actions"):
                        yield Button(_("Up"), id="change-up")
                        yield Button(_("Down"), id="change-down")
            else:
                from probandia import config as cfgmod

                yield Input(value="" if v is None else cfgmod.show(v), id="change-value",
                            type="integer" if s.type == "int" else "text")
            places = [(f"{cell(layer, 'layer')} · {os.path.basename(path)}", layer) for layer, path in self.files.items()]
            yield Static(_("Written in"), markup=False)
            yield Select(places, value=self.first, allow_blank=False, id="change-layer", disabled=len(places) < 2)
            yield Static("", id="change-error", markup=False)
            with Horizontal(classes="actions"):
                yield Button(_("Continue"), id="change-next", variant="primary")
                yield Button(_("Cancel"), id="change-cancel")

    def text(self):
        """The value as config set takes it."""
        from textual.widgets import SelectionList

        w = self.query_one("#change-value")
        if self.setting.type == "bool":
            return "true" if w.value else "false"
        if isinstance(w, SelectionList):
            return ",".join(i for i in self.order if i in w.selected)
        return str(w.value).strip()

    def move(self, step):
        """The item under the cursor one place up (-1) or down (1), its box kept."""
        from textual.widgets import SelectionList

        w = self.query_one("#change-value", SelectionList)
        at = w.highlighted
        if at is None or not 0 <= at + step < len(self.order):
            return
        chosen = set(w.selected)
        self.order[at], self.order[at + step] = self.order[at + step], self.order[at]
        w.clear_options()
        w.add_options([(i, i, i in chosen) for i in self.order])
        w.highlighted = at + step

    def done(self):
        text = self.text()
        why = refusal(self.setting, self.key, text)
        if why:   # refused before anything is written
            self.query_one("#change-error", Static).update(why)
            return
        self.dismiss({"value": text, "layer": self.query_one("#change-layer").value})

    def on_input_submitted(self, event):
        event.stop()
        self.done()

    def on_button_pressed(self, event):
        event.stop()
        if event.button.id in ("change-up", "change-down"):
            self.move(-1 if event.button.id == "change-up" else 1)
        elif event.button.id == "change-next":
            self.done()
        else:
            self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


def grade_filter(fid):
    """The choice of a grade that narrows a list of settings; Select.NULL: every grade."""
    from textual.widgets import Select

    return Select([(_(text), g) for g, text in GRADES.items()], prompt=_("every grade"), id=fid, compact=True)


class ConfigPane(TablesPane):
    """The settings in effect, where each comes from, and the model and the effort of each agent role.
    Enter explains a setting (``config explain``); Change sets it by the control of its type (``config set``,
    the registry its judge, in the file chosen); Reset takes it out of the file that sets it (``config unset``);
    Add sets the rate of a host; Grade changes the grade (``config grade``), each once confirmed (T104).
    Validate and Differences show what ``config validate`` and ``config diff`` print; Wizard asks the
    essential settings one by one (``config wizard``). The list narrows by grade, domain and what was changed."""

    needs_project = False
    parts = ("main", "explain")
    watches = SETTINGS + RESEARCHES[:1]   # the roles: a research's own model and effort too
    command = ("config", "show", "--all")
    tables = (("config-settings", "settings", ["key", "value", "layer", "grade", "help"]),
              ("config-roles", "roles", ["role", "model", "model_from", "effort", "effort_from"]))
    buttons = (("config-set", N_("Change")), ("config-reset", N_("Reset")), ("config-add", N_("Add")),
               ("config-grade", N_("Grade")), None, ("config-validate", N_("Validate")),
               ("config-diff", N_("Differences")), ("config-wizard", N_("Wizard")))
    notes = ("config-explain",)
    explained = None   # the command whose readable output is shown: config explain <key>, validate or diff
    wanted = None   # the setting Help chose, put under the cursor once shown

    def controls(self):
        from textual.containers import Horizontal
        from textual.widgets import Checkbox, Select

        from probandia.config import registry

        with Horizontal(classes="filters"):
            yield grade_filter("config-by-grade")
            yield Select([(d, d) for d in dict.fromkeys(s.key.split(".")[0] for s in registry.SETTINGS)],
                         prompt=_("every domain"), id="config-by-domain", compact=True)
            yield Checkbox(_("changed only"), id="config-changed", compact=True)

    def on_select_changed(self, event):
        if event.select.id in ("config-by-grade", "config-by-domain") and self.data is not None:
            event.stop()
            self.guard(self.show, self.data)

    def on_checkbox_changed(self, event):
        if event.checkbox.id == "config-changed" and self.data is not None:
            event.stop()
            self.guard(self.show, self.data)

    def kept(self, x):
        """A setting the grade, the domain and changed only keep."""
        from textual.widgets import Checkbox, Select

        grade = self.query_one("#config-by-grade", Select).value
        domain = self.query_one("#config-by-domain", Select).value
        return ((grade == Select.NULL or x["grade"] == grade) and (domain == Select.NULL or x["key"].split(".")[0] == domain)
                and (not self.query_one("#config-changed", Checkbox).value or x["layer"] != "default"))

    def read(self, context):
        d = super().read(context)
        d["tables"]["config-roles"] = self.app.engine("config", "roles").get("data", {}).get("roles", [])
        return d

    def heading(self, d):
        grade = d.get("values", {}).get("GRADE", "?")
        return _("Settings of the {grade} grade · Enter explains one").format(grade=_(GRADES.get(grade, grade)))

    def show(self, d):
        if self.wanted:
            self.clear_filters()
        rows = [x for x in d["tables"]["config-settings"] if self.kept(x)]
        super().show(dict(d, tables=dict(d["tables"], **{"config-settings": rows})))
        if self.wanted:
            self.choose(self.wanted)
        if self.explained:   # read again when the settings changed
            self.fetch("explain", self.explained)

    def clear_filters(self):
        from textual.widgets import Checkbox, Input, Select

        with self.prevent(Input.Changed, Select.Changed, Checkbox.Changed):
            self.query_one("#filter", Input).value = ""
            for fid in ("#config-by-grade", "#config-by-domain"):
                self.query_one(fid, Select).clear()
            self.query_one("#config-changed", Checkbox).value = False

    def choose(self, key):
        """The line of ``key`` under the cursor, or for a key with a placeholder its first line."""
        from probandia.config import registry

        self.wanted = None
        table = self.query_one("#config-settings", DataTable)
        keys = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
        setting = registry.BY_KEY.get(key) or registry.lookup(key)
        line = keys.index(key) if key in keys else next(
            (n for n, k in enumerate(keys) if registry.lookup(k) is setting), None)
        if line is None:
            self.app.notify(_("{key} has no line yet: Add sets one").format(key=key), severity="warning", markup=False)
            return
        table.move_cursor(row=line)
        table.focus()

    def on_data_table_row_selected(self, event):
        if event.data_table.id == "config-settings":
            self.explained = ("config", "explain", self.chosen("config-settings"))
            self.fetch("explain", self.explained)

    def report(self, action):
        """Validate, Differences: what the command prints at a terminal, under the buttons; it writes nothing."""
        self.explained = ("config", action)
        self.fetch("explain", self.explained, force=True)

    def read_explain(self, argv):
        return dict(self.app.answer(*argv), argv=argv)   # a FAIL of validate is what it says

    def show_explain(self, d):
        """What ``config explain``, ``config validate`` or ``config diff`` prints at a terminal."""
        from probandia.cli import human
        from probandia.cli.output import Result

        r = Result(d["status"], d.get("values"), d.get("lines"))
        for name, rows in (d.get("data") or {}).items():
            r.table(name, rows)
        r.view = {"explain": "config-explain", "diff": "config-diff"}.get(d["argv"][1])
        self.query_one("#config-explain", Static).update(human.render(r, human.Style(plain=self.app.plain)).rstrip())

    def where(self):
        """A change goes to the project's settings, or outside a project to the user's."""
        return [] if self.app.project else ["--user"]

    def files(self):
        """{layer: path} of the files a setting may be written to: the project's, its local one and the
        user's; outside a project, the user's only."""
        from probandia import config as cfgmod

        paths = cfgmod.layer_paths(self.app.project, self.app.ctx.environ)
        return {layer: paths[layer] for layer in FLAGS if layer in paths}

    def row(self, key):
        return next((x for x in (self.data or {}).get("tables", {}).get("config-settings", []) if x["key"] == key), None)

    def written(self, key, argv):
        """What a write answered: its reason under the buttons when it failed, else the setting explained."""
        def done(d):
            if d.get("status") == "FAIL":
                self.query_one("#config-explain", Static).update(failure(argv, d))
            else:
                self.explained = ("config", "explain", key)
        return done

    def change(self, key=None):
        """Change: the new value of the setting chosen (or ``key``), by the control of its type, and the file it
        goes to, then ``config set`` once confirmed. A value the registry refuses is refused in the window, with
        the engine's reason, and nothing is written."""
        key = key or self.chosen("config-settings")
        if not key:
            return
        files, row = self.files(), self.row(key)
        layer = row["layer"] if row and row["layer"] in files else next(iter(files))

        def asked(answer):
            if answer is not None:
                argv = ("config", "set", key, answer["value"], *FLAGS[answer["layer"]])
                self.app.act(_("Set {key} to {value} in {file}?").format(
                    key=key, value=answer["value"] or '""', file=files[answer["layer"]]), *argv,
                    then=self.written(key, argv))

        self.app.push_screen(ChangeScreen(key, self.app.setting(key), files, layer), asked)

    def reset(self):
        """Reset: the setting chosen taken out of the file that sets it, once confirmed (``config unset``); the
        layer below it then gives its value."""
        key = self.chosen("config-settings")
        row = self.row(key)
        if row is None:
            return
        files = self.files()
        if row["layer"] not in files:
            self.app.notify((_("{key} already has its default value") if row["layer"] == "default" else
                             _("{key} comes from {layer}, not from a settings file")).format(
                key=key, layer=cell(row["layer"], "layer")), severity="warning", markup=False)
            return
        argv = ("config", "unset", key, *FLAGS[row["layer"]])
        self.app.act(_("Remove {key} from {file}? The layer below then gives its value.").format(
            key=key, file=files[row["layer"]]), *argv, then=self.written(key, argv))

    def add_rate(self):
        """Add: the rate of a host, a key the list cannot show before it is set (``hosts.<host>.rate``): the host,
        the rate and the file asked, checked by the registry, then ``config set`` once confirmed."""
        from probandia.config import registry

        setting, files = registry.BY_KEY["hosts.<host>.rate"], self.files()

        def asked(answer):
            if answer is None:
                return
            key = f"hosts.{answer['add-host'].lower()}.rate"
            why = (_("{host} is not a host name, such as archives.example.org").format(host=answer["add-host"])
                   if registry.lookup(key) is not setting else refusal(setting, key, answer["add-rate"]))
            if why:
                self.query_one("#config-explain", Static).update(why)
                return
            layer = answer.get("add-layer") or next(iter(files))
            argv = ("config", "set", key, answer["add-rate"], *FLAGS[layer])
            self.app.act(_("Set {key} to {value} in {file}?").format(key=key, value=answer["add-rate"],
                                                                    file=files[layer]), *argv,
                         then=self.written(key, argv))

        fields = [("add-host", _("The host, such as archives.example.org"), "", "text"),
                  ("add-rate", _("Its rate: {values}").format(values=setting.describe_values()), "5/min", "text")]
        if len(files) > 1:
            fields.append(("add-layer", _("Written in"), next(iter(files)),
                           [(f"{cell(layer, 'layer')} · {os.path.basename(path)}", layer) for layer, path in files.items()]))
        self.app.push_screen(AskScreen(_(setting.help), fields), asked)

    def regrade(self):
        """Grade: the grade chosen, then ``config grade`` once confirmed."""
        grade = (self.data or {}).get("values", {}).get("GRADE")
        if grade not in GRADES:   # not read
            return

        def asked(answer):
            if answer is not None and answer["config-grade"] != grade:
                self.app.act(_("Change the grade to {grade}?").format(grade=_(GRADES[answer["config-grade"]])),
                             "config", "grade", answer["config-grade"], *self.where())

        self.app.push_screen(AskScreen(_("The grade decides the settings shown"), [
            ("config-grade", _("Grade"), grade, [(_(text), g) for g, text in GRADES.items()])]), asked)


class LibraryPane(TablesPane):
    """The scripts the agents learned, their trust and their witnesses. Test plays the witness of the script
    chosen, over the network (``library test``); Approve trusts it (``library trust``); each once confirmed,
    then what it answered is said (T105)."""

    watches = (("project", "library/*"), ("config", "library/*"))
    command = ("library", "list")
    tables = (("library-scripts", "scripts", None),)
    buttons = (("library-test", N_("Test")), ("library-trust", N_("Approve")))
    notes = ("library-outcome",)

    def script(self, action):
        """Test or Approve the script chosen, once confirmed."""
        from probandia.cli.views import _plural

        script = self.chosen("library-scripts")
        if not script:
            return
        argv = ("library", action, script)

        def said(d):   # its state and the runs of its witness passed, or why it failed
            v = d.get("values") or {}
            self.query_one("#library-outcome", Static).update(failure(argv, d) if d.get("status") == "FAIL" else " · ".join(
                [script, cell(v.get("STATE"), "level")]
                + ([_plural(v["RUNS_OK"], _("{n} run passed"), _("{n} runs passed"))] if "RUNS_OK" in v else [])))

        question = (_("Test the script {script}? Its witness runs once, over the network, on the hosts it declares.")
                    if action == "test" else _("Approve the script {script}? It is then marked trusted."))
        self.app.act(question.format(script=script), *argv, then=said)

    def heading(self, d):
        from probandia.cli.views import _plural

        n = len(d["tables"].get("library-scripts", []))
        return (_plural(n, _("{n} learned script"), _("{n} learned scripts")) if n else
                _("nothing in the library yet: agents save the scripts they write, with a witness"))


LOG_LINES = 20   # the last lines of a log Diagnostic shows


def logs(project):
    """[{file, size, written}] of the files of ``.probandia/logs``, the newest first: listed, never opened."""
    import datetime

    try:
        with os.scandir(os.path.join(project, ".probandia", "logs")) as listing:
            found = [(e.name, e.stat()) for e in listing if e.is_file()]
    except OSError:
        return []
    return [{"file": name, "size": st.st_size, "written": datetime.datetime.fromtimestamp(
        st.st_mtime, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for name, st in sorted(found, key=lambda x: -x[1].st_mtime)]


class DiagnosticPane(TablesPane):
    """doctor, the optional tools, and the locks: an expired one can be released. The cache of answers
    (``cache stats``), purged provider by provider once confirmed (``cache clear``); the logs of
    ``.probandia/logs``, whose last lines Enter shows, read only (T106)."""

    needs_project = False
    parts = ("main", "log")
    files_only = ("log",)
    watches = LOCKS + SETTINGS + (("project", ".probandia/cache/*"), ("project", ".probandia/cache-stats.json"),
                                  ("project", ".probandia/logs/*"))   # the cache by its folders: they hold many
    command = ("doctor",)
    tables = (("doctor-tools", "tools", ["tool", "installed", "purpose", "install"]),
              ("diagnostic-locks", "locks", ["scope", "state", "holder", "expires"]),
              ("diagnostic-cache", "cache", ["provider", "entries", "bytes", "expired_entries", "served", "saved"]),
              ("diagnostic-logs", "logs", ["file", "size", "written"]))
    buttons = (("lock-release", N_("Release the expired lock")), ("cache-purge", N_("Purge the cache")))
    shown_log = None   # the log whose last lines are shown

    def compose(self):
        yield from super().compose()
        yield Static("", id="diagnostic-log", markup=False)

    def read(self, context):
        d = super().read(context)
        if self.app.project:
            d["tables"]["diagnostic-locks"] = self.app.engine("lock", "list").get("data", {}).get("locks", [])
            d["tables"]["diagnostic-cache"] = [dict(x, expired_entries=x["expired"]) for x in self.app.engine(
                "cache", "stats").get("data", {}).get("cache", [])]   # a number, not the state "expired"
            d["tables"]["diagnostic-logs"] = logs(self.app.project)
        return d

    def show(self, d):
        super().show(d)
        if self.shown_log:   # read again when it grew
            self.fetch("log", self.shown_log)

    def on_data_table_row_selected(self, event):
        if event.data_table.id == "diagnostic-logs" and self.app.project:
            self.shown_log = os.path.join(self.app.project, ".probandia", "logs", self.chosen("diagnostic-logs"))
            self.fetch("log", self.shown_log)

    def read_log(self, path):
        lines, _first, _end = last_lines(path, LOG_LINES)   # opened to read, from its end
        return {"file": os.path.basename(path), "lines": [x for _at, x in lines]}

    def show_log(self, d):
        shown = self.query_one("#diagnostic-log", Static)
        shown.update("\n".join([_("The last lines of {file}").format(file=d["file"]), *d["lines"]]))
        shown.scroll_visible(animate=False)

    def purge(self):
        """Purge: the entries of the cache paid to the provider chosen, once confirmed, the question saying
        how many go and their size; then ``cache clear --provider <id> --yes``."""
        from probandia.i18n import formats

        provider = self.chosen("diagnostic-cache")
        row = next((x for x in (self.data or {}).get("tables", {}).get("diagnostic-cache", [])
                    if x["provider"] == provider), None)
        if not row or not row["entries"]:
            self.app.notify(_("Nothing to purge"), severity="warning")
            return
        self.app.act(_("Remove the {n} cache entries of {provider} ({size} bytes)? Those answers will be paid for "
                       "again if asked again.").format(n=row["entries"], provider=provider,
                                                       size=formats.number(row["bytes"])),
                     "cache", "clear", "--provider", provider, "--yes")

    def heading(self, d):
        v = d["values"]
        head = {"OK": _("Probandia is ready"), "WARN": _("Probandia works; a few things to look at"),
                "FAIL": _("Probandia cannot run here")}.get(d.get("status"), _("Probandia"))
        harness = v.get("HARNESS")
        return " · ".join([head, "Python " + str(v.get("PYTHON", "?")),
                           _("no harness detected") if harness in (None, "cli") else str(harness)])


class TeamPane(Pane):
    """The waves, the budget of native searches and the messages of a team: read only."""

    watches = RESEARCHES + (("project", RESEARCH + "work/team/*"),)

    def compose(self):
        yield Static("", classes="title", markup=False)
        for tid in ("team-waves", "team-messages"):
            yield DataTable(id=tid, cursor_type="row")

    def context(self):
        return self.app.research

    def read(self, research):
        from probandia import team
        from probandia.research import find_research

        if not research:
            d = self.app.engine("research", "list").get("data", {}).get("researches", [])
            research = d[0]["research"] if d else None
        if not research:
            return {"research": None}
        res = find_research(self.app.project, research)
        messages = []
        for path in sorted(glob.glob(os.path.join(team.folder(res), "*.inbox.jsonl"))):
            messages += team._read_jsonl(path)   # read, never consumed: inbox would mark them read
        return {"research": res.id, "budget": self.app.engine("team", "budget", res.id).get("values", {}),
                "waves": team.waves(res), "messages": messages}

    def show(self, d):
        if not self.app.research:
            self.app.research = d["research"]
        if not d["research"]:
            self.title(_("No research yet"))
            return
        v = d["budget"]
        self.title(_("{research} · pass {n} · at most {agents} agents · {native} native searches left").format(
            research=d["research"], n=v.get("PASS", "—"), agents=v.get("MAX_AGENTS", "—"),
            native=v.get("NATIVE_LEFT", "—")))
        fill(self.query_one("#team-waves"), d["waves"], ["pass", "wave", "agents", "ts"])
        fill(self.query_one("#team-messages"), d["messages"], ["ts", "from", "to", "type", "body"])


# Config, Themes: the themes of probandia tui, Probandia's and the person's own (config.themes)

COLOR_NAMES = {"primary": N_("Main"), "secondary": N_("Second"), "accent": N_("Accent"), "warning": N_("Warning"),
               "error": N_("Error"), "success": N_("Success"), "foreground": N_("Text"),
               "background": N_("Background"), "surface": N_("Surface"), "panel": N_("Panel")}
LAYOUT_NAMES = {"buttons": N_("Buttons"), "section_titles": N_("Section titles"), "focus_mark": N_("Focus mark"),
                "zebra": N_("Shaded lines"), "frames": N_("Frames"), "tree_width": N_("Family tree"),
                "commands_width": N_("Console list")}
CHOICES = {"compact": N_("compact"), "tall": N_("tall"), "round": N_("round"), "solid": N_("solid"),
           "heavy": N_("heavy"), "double": N_("double"), "ascii": N_("ASCII")}
BASES = {"dark": N_("dark"), "light": N_("light")}
SAMPLE_WIDTH = 32


def theme_id(name):
    """The name Textual knows a theme by: probandia and probandia-light for Probandia's own."""
    return {"dark": "probandia", "light": "probandia-light"}.get(name, f"probandia-{name}")


def textual_theme(spec):
    """The Textual theme of a theme of ``config.themes``."""
    from textual.theme import Theme

    return Theme(name=theme_id(spec["name"]), dark=spec["base"] == "dark", **spec["colors"])


def sample(spec, plain=False):
    """A theme in a few lines, in its own colours whatever the theme in use: a title, text, a
    section and its list, buttons and statuses, as its layout draws them."""
    from rich.style import Style
    from rich.text import Text

    c, look = spec["colors"], spec["layout"]

    def style(fg, bg="background", bold=False):
        return Style(color=c[fg], bgcolor=c[bg], bold=bold)

    lines = []

    def line(*pieces, bg="background", fill=" ", fill_fg="foreground"):
        t = Text()
        for text, s in pieces:
            t.append(text, s)
        t.truncate(SAMPLE_WIDTH)
        t.append(fill * (SAMPLE_WIDTH - t.cell_len), style(fill_fg, bg))
        lines.append(t)

    line((" " + _("Probandia · a screen"), style("primary", "panel", True)), bg="panel")
    line((_("The text of the screens"), style("foreground")))
    line(("", style("foreground")))
    if look["section_titles"]:
        line((_("Accounts") + " ", style("secondary", bold=True)), fill="-" if plain else "─", fill_fg="panel")
    mark = ("|" if plain else "▌") if look["focus_mark"] else " "
    rows = [("serper", "2 500"), ("brave", "1 800"), ("tavily", "950")]
    line((mark, style("accent")), (" " + _("provider").ljust(14) + _("left"), style("secondary", bold=True)))
    for n, (name, left) in enumerate(rows):
        bg = "primary" if n == 0 else "surface" if look["zebra"] and n % 2 else "background"
        fg = "background" if n == 0 else "foreground"
        line((mark, style("accent")), (" " + name.ljust(14) + left, style(fg, bg)), bg=bg)
    line(("", style("foreground")))
    buttons = [(_("Accept"), "success"), (_("Set aside"), "warning"), (_("Cancel"), "panel")]
    labels = [(f" {text} ", c[color]) for text, color in buttons]
    rows = (["", "label", ""] if look["buttons"] == "tall" else ["label"])
    for which in rows:
        pieces = []
        for text, color in labels:
            fg = c["foreground"] if color == c["panel"] else c["background"]
            pieces += [(text if which else " " * len(text), Style(color=fg, bgcolor=color, bold=True)),
                       (" ", style("foreground"))]
        line(*pieces)
    line(("", style("foreground")))
    signs = ("+", "!", "x") if plain else ("✓", "⚠", "✗")
    line(*[(f"{sign} {_(text)}  ", style(color)) for sign, text, color in
           zip(signs, (N_("passed"), N_("warning"), N_("failed")), ("success", "warning", "error"))])
    return Text("\n").join(lines)


class ThemesPane(Pane):
    """The themes of the application: Probandia's, dark and light, and the person's own, one file each
    in their configuration folder. The theme chosen in the list fills the form, its sample drawn as it
    is changed; Save writes it (``config theme save``), Delete removes it (``config theme delete``), Use
    takes it for the application and keeps it (``config set --user tui.theme``), each once confirmed."""

    needs_project = False
    indicator = "#themes-list"
    watches = SETTINGS + (("config", "themes/*.toml"),)
    loaded = None   # the name of the theme the form was filled with
    wanted = None   # the theme to choose in the list at its next read: the one saved, the new one's model
    edited = None   # the theme as the form holds it, its wrong entries left as they were
    wrong = ()   # the entries of the form whose value is wrong

    def compose(self):
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Button, Checkbox, Input, Select

        from probandia.config import themes as tmod

        yield Static("", classes="title", markup=False)
        yield self.filter_box(_("filter: a name"))
        yield DataTable(id="themes-list", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="actions"):
            yield Button(_("Use"), id="theme-use", variant="primary")
            yield Button(_("New"), id="theme-new")
            yield Button(_("Save"), id="theme-save", variant="success")
            yield Button(_("Delete"), id="theme-delete", variant="warning")
        yield Static("", id="theme-note", classes="note", markup=False)
        with Horizontal(id="theme-body"):
            with Vertical(id="theme-form"):
                with Horizontal(classes="theme-row"):
                    yield Static(_("Name"), classes="theme-label")
                    yield Input(id="theme-name", max_length=40)
                with Horizontal(classes="theme-row"):
                    yield Static(_("Starts from"), classes="theme-label")
                    yield Select([(_(text), base) for base, text in BASES.items()], value="dark",
                                 allow_blank=False, id="theme-base")
                yield Static(_("Colours"), classes="section")
                for key, help in tmod.COLORS.items():
                    with Horizontal(classes="theme-row"):
                        yield Static(_(COLOR_NAMES[key]), classes="theme-label")
                        yield Input(id=f"theme-color-{key}", max_length=7)
                        yield Static("", id=f"theme-swatch-{key}", classes="swatch")
                        yield Static(_(help), classes="theme-help", markup=False)
                yield Static(_("Layout"), classes="section")
                for key, (_default, help, values) in tmod.LAYOUT.items():
                    with Horizontal(classes="theme-row"):
                        yield Static(_(LAYOUT_NAMES[key]), classes="theme-label")
                        wid = f"theme-layout-{key}"
                        if values is bool:
                            yield Checkbox("", id=wid)
                        elif isinstance(values[0], int):
                            yield Input(id=wid, type="integer", max_length=3, classes="-layout")
                        else:
                            yield Select([(_(CHOICES[v]), v) for v in values], value=values[0],
                                         allow_blank=False, id=wid)
                        yield Static(_(help), classes="theme-help", markup=False)
            box = Static("", id="theme-sample")
            box.border_title = _("Sample")
            yield box

    def read(self, context):
        from probandia.config import themes as tmod

        listed = self.app.engine("config", "theme", "list")
        found, problems = tmod.load(self.app.ctx.environ)
        return {"values": listed.get("values", {}), "themes": found, "problems": problems}

    def show(self, d):
        from probandia.cli.views import _plural

        found, problems = d["themes"], d["problems"]
        in_use = d["values"].get("IN_USE") or "dark"
        self.app.adopt_themes(found)
        rows = [{"name": name, "origin": _("Probandia") if t["builtin"] else _("yours"),
                 "base": _(BASES[t["base"]]), "in_use": ("*" if self.app.plain else "✓") if name == in_use else ""}
                for name, t in found.items()]
        columns = ["name", "origin", "base", "in_use"]
        table = fill(self.query_one("#themes-list", DataTable), narrow(rows, self.word(), columns), columns, key="name")
        head = [_plural(len(found), _("{n} theme"), _("{n} themes")),
                _("in use: {theme}").format(theme=in_use if in_use in found else "dark")]
        if problems:
            head.append(_plural(len(problems), _("{n} file with a mistake"), _("{n} files with a mistake")))
        self.title(" · ".join(head))
        want = self.wanted or (None if self.loaded in found else in_use if in_use in found else "dark")
        listed = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
        if want in found:
            if want in listed:
                chose(table, listed.index(want))
            self.wanted = None
            self.load(found[want])
        if self.loaded in problems:
            self.say(" · ".join(problems[self.loaded]))

    def on_data_table_row_highlighted(self, event):
        if event.data_table.id == "themes-list" and current(event) and self.data:
            name = self.chosen()
            if name in self.data["themes"] and name != self.loaded:
                self.load(self.data["themes"][name])
                self.say(" · ".join(self.data["problems"].get(name, [])))

    def chosen(self):
        t = self.query_one("#themes-list", DataTable)
        return str(t.get_row_at(t.cursor_row)[0]) if t.row_count else None

    def say(self, text):
        self.query_one("#theme-note", Static).update(text)

    def load(self, spec, name=None):
        """The form filled with ``spec``, under ``name`` (its own by default)."""
        from textual.widgets import Input

        self.loaded = spec["name"]
        self.edited = {**spec, "colors": dict(spec["colors"]), "layout": dict(spec["layout"])}
        self.wrong = set()
        self.query_one("#theme-name", Input).value = name or spec["name"]
        self.query_one("#theme-base").value = spec["base"]
        for key, value in spec["colors"].items():
            self.query_one(f"#theme-color-{key}", Input).value = value
            self.paint(key, value)
        for key, value in spec["layout"].items():
            widget = self.query_one(f"#theme-layout-{key}")
            widget.value = str(value) if isinstance(widget, Input) else value
        self.draw()

    def paint(self, key, value):
        self.query_one(f"#theme-swatch-{key}", Static).styles.background = value

    def draw(self):
        """The sample, in the colours and the layout of the form."""
        box = self.query_one("#theme-sample", Static)
        c = self.edited["colors"]
        box.styles.background = c["background"]
        box.styles.border = ("ascii" if self.app.plain else self.edited["layout"]["frames"], c["accent"])
        box.styles.border_title_color = c["accent"]
        box.update(sample(self.edited, self.app.plain))

    def entered(self, widget, value):
        """An entry of the form changed: checked, then the sample drawn again when it is right."""
        from probandia.config import themes as tmod

        wid = widget.id or ""
        if self.edited is None or not wid.startswith(("theme-color-", "theme-layout-", "theme-base")):
            return
        if wid == "theme-base":
            self.edited["base"] = value
            return
        key = wid.split("-", 2)[2]
        try:
            value = tmod.check(key, value)
        except ValueError:
            self.wrong.add(key)
            widget.add_class("-invalid")
            return
        self.wrong.discard(key)
        widget.remove_class("-invalid")
        self.edited["colors" if key in tmod.COLORS else "layout"][key] = value
        if key in tmod.COLORS:
            self.paint(key, value)
        self.draw()

    def on_input_changed(self, event):
        if event.input.id == "filter":
            return super().on_input_changed(event)
        event.stop()
        self.entered(event.input, event.value)

    def on_select_changed(self, event):
        event.stop()
        self.entered(event.select, event.value)

    def on_checkbox_changed(self, event):
        event.stop()
        self.entered(event.checkbox, event.value)

    def pressed(self, bid):
        """The buttons of the screen: Use, New, Save, Delete."""
        from textual.widgets import Input

        from probandia.config import themes as tmod

        name = self.chosen()
        if bid == "theme-use" and name:
            self.app.act(_("Use the theme {theme}? It is kept in your settings.").format(theme=name),
                         "config", "set", "tui.theme", name, "--user",
                         then=lambda d: d.get("status") != "FAIL" and self.app.use_theme(name))
        elif bid == "theme-new" and self.edited:
            taken = set(self.data["themes"]) if self.data else set()
            new = next(f"theme-{n}" for n in range(1, len(taken) + 2) if f"theme-{n}" not in taken)
            self.load(self.edited, name=new)
            self.say(_("A new theme, from {theme}: change it, then Save").format(theme=self.loaded))
            self.query_one("#theme-name", Input).focus()
        elif bid == "theme-save" and self.edited:
            self.save(self.query_one("#theme-name", Input).value.strip())
        elif bid == "theme-delete" and name:
            if name in tmod.BUILTIN:
                self.say(_("{theme} is a theme of Probandia: it cannot be deleted").format(theme=name))
                return
            self.app.act(_("Delete the theme {theme}? Its file is removed.").format(theme=name),
                         "config", "theme", "delete", name, "--yes")

    def save(self, name):
        """Save: the form written as the theme ``name`` by ``config theme save``, once confirmed."""
        from probandia.config import themes as tmod

        try:
            tmod.check_name(name)
        except ValueError as err:
            self.say(str(err))
            return
        if self.wrong:
            self.say(_("To correct first: {entries}").format(entries=", ".join(
                _(COLOR_NAMES.get(k) or LAYOUT_NAMES[k]) for k in sorted(self.wrong))))
            return
        changes = [f"{k}={v}" for k, v in self.edited["colors"].items()]
        changes += [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in self.edited["layout"].items()]
        argv = ["config", "theme", "save", name, "--base", self.edited["base"]]
        for change in changes:
            argv += ["--set", change]

        def done(d):
            if d.get("status") == "FAIL":
                self.say(failure(argv[:4], d))
            else:
                self.wanted, self.loaded = name, None

        self.app.act(_("Save the theme {theme}? It is written in {path}.").format(
            theme=name, path=tmod.path_of(name, self.app.ctx.environ)), *argv, then=done)

# 7 Help: what docs/parameters.md shows, read from the engine (help settings), never copied


class HelpPane(TablesPane):
    """A part of Help: tables of ``help settings``, and of the commands named in ``more``."""

    needs_project = False
    watches = SETTINGS
    command = ("help", "settings")
    more = ()   # (table id, engine command, its data table)
    head = ""

    def read(self, context):
        d = super().read(context)
        for tid, argv, name in self.more:
            d["tables"][tid] = self.app.engine(*argv).get("data", {}).get(name, [])
        return d

    def heading(self, d):
        return _(self.head)


class HelpSettingsPane(HelpPane):
    """Every setting of the registry, by domain: its grade, default, values, variable, option and help, in the
    language in effect; narrowed by grade and by the filter. Enter takes the setting chosen to the Settings."""

    tables = (("help-settings", "settings", ["key", "grade", "default", "values", "variable", "option", "help"]),)
    head = N_("Every setting, by domain · Enter takes one to the Settings")

    def controls(self):
        from textual.containers import Horizontal

        with Horizontal(classes="filters"):
            yield grade_filter("help-by-grade")

    def on_select_changed(self, event):
        if event.select.id == "help-by-grade" and self.data is not None:
            event.stop()
            self.guard(self.show, self.data)

    def show(self, d):
        from textual.widgets import Select

        grade = self.query_one("#help-by-grade", Select).value
        rows = d["tables"]["help-settings"]
        order = {domain: n for n, domain in enumerate(dict.fromkeys(x["domain"] for x in rows))}
        rows = sorted((x for x in rows if grade == Select.NULL or x["grade"] == grade), key=lambda x: order[x["domain"]])
        super().show(dict(d, tables={"help-settings": rows}))

    def on_data_table_row_selected(self, event):
        if event.data_table.id == "help-settings":
            self.app.goto_setting(self.chosen("help-settings"))


class HelpLayersPane(HelpPane):
    tables = (("help-layers", "layers", ["order", "layer", "what", "file", "how"]),)
    head = N_("Where a value comes from: the first line wins over the next ones")


class HelpProvidersPane(HelpPane):
    tables = (("help-conditions", "conditions", ["condition", "reason"]),
              ("help-provider-states", None, ["provider", "name", "state"]))
    more = (("help-provider-states", ("providers", "list"), "providers"),)
    head = N_("A provider is used when the five conditions hold; each provider's state")


class HelpKeysPane(HelpPane):
    tables = (("help-key-places", "keys", ["order", "source", "what", "file"]),
              ("help-key-variables", None, ["variable", "present", "source", "unlocks"]))
    more = (("help-key-variables", ("keys",), "keys"),)

    def heading(self, d):
        return " · ".join([_("Keys live in .env files, never in a setting: the first found wins"), *d["lines"]])


class HelpVariablesPane(HelpPane):
    tables = (("help-variables", "variables", ["variable", "what"]),)
    head = N_("The PROBANDIA_ variables that are not settings")


class HelpOptionsPane(HelpPane):
    tables = (("help-options", "options", ["option", "what"]),)
    head = N_("The options every command takes")


PANES = {"home": HomePane, "quotas": QuotasPane, "researches": ResearchesPane, "report": ReportPane,
         "family": FamilyPane, "proposals": ProposalsPane, "providers": ProvidersPane, "config": ConfigPane,
         "themes": ThemesPane, "diagnostic": DiagnosticPane, "library": LibraryPane,
         "team": TeamPane, "help": HelpSettingsPane, "help-layers": HelpLayersPane,
         "help-providers": HelpProvidersPane, "help-keyfiles": HelpKeysPane, "help-variables": HelpVariablesPane,
         "help-options": HelpOptionsPane}   # name -> Pane subclass


def make_app(ctx):
    """The application of ``probandia tui``, for the command's context: its keys say what
    they do in the language of the command, whatever language the module was imported in."""
    return type(ProbandiaApp.__name__, (ProbandiaApp,), {"BINDINGS": bindings()})(ctx)


def bindings():
    """The keys of the application, their words in the language in effect: the footer and
    the help show them (T92)."""
    out = [Binding(PALETTE_KEY, "command_palette", _("Palette"), show=False, priority=True,
                   tooltip=_("screens and command forms"))]
    out += [Binding(str(n), f"show('{name}')", _(title), show=False, tooltip=_("the screen {screen}").format(
        screen=_(title))) for n, (name, title) in enumerate(SCREENS, 1)]
    return out + [
        Binding("left_square_bracket", "part(-1)", _("Previous tab"), show=False, key_display="[",
                tooltip=_("the previous tab")),
        Binding("right_square_bracket", "part(1)", _("Next tab"), show=False, key_display="]",
                tooltip=_("the next tab")),
        Binding("slash", "search", _("Filter"), show=False, key_display="/", tooltip=_("the filter of the list")),
        Binding("escape", "leave", _("Leave the field"), show=False, tooltip=_("out of the field")),
        Binding("j", "move(0)", _("Down"), show=False, tooltip=_("the next line")),
        Binding("k", "move(1)", _("Up"), show=False, tooltip=_("the previous line")),
        Binding("g", "move(2)", _("Top"), show=False, tooltip=_("the first line")),
        Binding("G", "move(3)", _("Bottom"), show=False, tooltip=_("the last line")),
        Binding("enter", "open_file", _("Open the file"), show=False, tooltip=_("the file of the line chosen")),
        Binding("backspace", "back", _("Back"), show=False, tooltip=_("back to the list")),
        Binding("s", "sync", _("Synchronise"), tooltip=_("balances read again, free")),
        Binding("o", "open", _("Open"), show=False, tooltip=_("the report, or the family's tree, in the browser")),
        Binding("c", "copy", _("Copy"), show=False,
                tooltip=_("the command that resumes a research, the accounts as CSV, a citation")),
        Binding("a", "review('apply')", _("Accept"), show=False, tooltip=_("the proposal shown, once confirmed")),
        Binding("x", "review('drop')", _("Set aside"), show=False, tooltip=_("the proposal shown, with a reason")),
        Binding("n", "step(1)", _("Next proposal"), show=False, tooltip=_("the next proposal")),
        Binding("p", "step(-1)", _("Previous proposal"), show=False, tooltip=_("the previous proposal")),
        Binding("r", "refresh", _("Refresh"), tooltip=_("the screen read again")),
        Binding("t", "toggle_theme", _("Theme"), show=False, tooltip=_("the next theme, kept")),
        Binding("question_mark", "help", _("Help"), key_display="?", tooltip=_("this help")),
        Binding("q", "quit", _("Quit"), tooltip=_("quit"))]


class ProbandiaApp(App):
    """The screens in tabs, the palette, and the console's forms over them."""

    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tui.tcss")
    COMMANDS = {Places, Forms}   # Probandia's own: Textual's commands, in English, are left out (T95)
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (120, "-wide")]   # the home in two columns when wide (T97)
    BINDINGS = []   # those of ``bindings()``, in a subclass made by ``make_app``

    def __init__(self, ctx):
        from probandia.errors import NotInProject

        super().__init__()
        self.ctx = ctx
        try:
            self.project = ctx.project
        except NotInProject:
            self.project = None
        self.roots = self.folders(ctx.environ)   # where the screens' files are (``watched``)
        self.research = None   # the research selected, shared by the screens
        self.lock = threading.Lock()   # one engine command at a time, as the engine expects
        self.file_lock = threading.Lock()   # the reads of files only (``Pane.files_only``)
        self._parser = None
        # --plain: ASCII and no colour; --no-color or NO_COLOR: no colour, the meaning kept (T96)
        self.plain = bool(getattr(ctx.args, "plain", False))
        self.no_color = (self.no_color or self.plain or bool(getattr(ctx.args, "no_color", False))
                         or bool(ctx.environ.get("NO_COLOR")))
        self.set_class(self.plain, "-plain")
        from probandia.config import themes as tmod

        self.theme_specs = {}   # {name: theme of config.themes}, Probandia's and the person's own
        self.theme_name = self.look = None   # the theme in use, by its name, and its layout
        self.adopt_themes(tmod.load(ctx.environ)[0])
        self.use_theme(self.setting("tui.theme"))   # kept (T94)

    def adopt_themes(self, found):
        """The themes ``found`` known to Textual; the one in use drawn again when its file changed."""
        before = self.theme_specs.get(self.theme_name)
        self.theme_specs = found
        for spec in found.values():
            self.register_theme(textual_theme(spec))
        if self.theme_name and found.get(self.theme_name) != before:
            self.use_theme(self.theme_name)

    def use_theme(self, name):
        """The theme ``name`` in use, its colours and its layout (classes of the application, the
        widths of the family's tree and of the console's list); Probandia's dark one when there is
        no such theme."""
        from probandia.config import themes as tmod

        name = name if name in self.theme_specs else "dark"
        spec = self.theme_specs.get(name) or tmod.builtin("dark")
        self.theme_name, self.look = name, spec["layout"]
        self.register_theme(textual_theme(spec))
        look = self.look
        self.set_class(look["buttons"] == "compact", "-compact-buttons")
        self.set_class(look["section_titles"], "-section-titles")
        self.set_class(look["focus_mark"], "-focus-mark")
        self.set_class(not look["zebra"], "-no-zebra")
        for frame in tmod.FRAMES[1:]:
            self.set_class(look["frames"] == frame, f"-frames-{frame}")
        for screen in self.screen_stack:
            for tree in screen.query("#family-tree"):
                tree.styles.width = f"{look['tree_width']}%"
            for side in screen.query("#forms-side"):
                side.styles.width = look["commands_width"]
        if self.theme == theme_id(name):
            if self.is_running:   # the same theme, its colours changed
                self.refresh_css(animate=False)
        else:
            self.theme = theme_id(name)
        return True

    def get_key_display(self, binding):
        """A key as the footer and the help show it; in ASCII with ``--plain`` (T96)."""
        shown = super().get_key_display(binding)
        return binding.key if self.plain and not shown.isascii() else shown

    def get_line_filters(self):
        """Textual's, and without colour what ``--no-color``, ``--plain`` or ``NO_COLOR`` asks,
        as Textual does for ``NO_COLOR`` alone: shades of grey, the contrasts kept."""
        from textual.filter import Monochrome, NoColor

        filters = list(super().get_line_filters())
        if self.no_color and not any(isinstance(f, (Monochrome, NoColor)) for f in filters):
            self.greys = getattr(self, "greys", None) or Monochrome()
            filters.append(self.greys)
        return filters

    def setting(self, key):
        """The value of a setting in effect, here or outside a project; None when the
        settings cannot be read."""
        from probandia import config as cfgmod

        try:
            return cfgmod.load(self.project, self.ctx.environ, strict=False).get(key)
        except (ProbandiaError, OSError):
            return None

    def get_default_screen(self):
        return Main()

    def on_mount(self):
        self.title = "Probandia" + (f" · {self.project}" if self.project else "")
        self.set_interval(1.0, self.tick)

    def folders(self, environ):
        """{folder: path} of the files the screens watch: the project, the user's
        configuration folder and the user's data folder."""
        from probandia.config import user_config_path
        from probandia.paths import user_data_dir

        return {"project": self.project, "config": os.path.dirname(user_config_path(environ)),
                "data": user_data_dir(environ)}

    def open_forms(self, command=None):
        """The console: the forms of the user commands, on ``command`` when one is given."""
        from probandia.cli.tui_forms import FormsScreen

        self.push_screen(FormsScreen(command))

    # reading and acting through the engine, in threads (T88)

    def reading(self, read, context, files_only=False, **extra):
        """A read of a screen, in its thread: one engine command at a time, and nothing
        when a newer read replaced it while it waited. A read of files only waits for the
        other reads of files, not for a command."""
        with self.file_lock if files_only else self.lock:
            if get_current_worker().is_cancelled:
                return None
            return read(context, **extra)

    def parser(self):
        """The engine's parser, built once: building it costs more than most reads."""
        if self._parser is None:
            from probandia import cli

            self._parser = cli.build_parser()
        return self._parser

    def defaults(self):
        """The global options ``probandia tui`` was given that its commands keep: the project, the language."""
        return [w for dest, option in (("project", "--project"), ("lang", "--lang"))
                if getattr(self.ctx.args, dest, None) for w in (option, getattr(self.ctx.args, dest))]

    def answer(self, *argv, asks=False):
        """A command as the person would run it with ``--json``, run in this process by
        its handler, as ``cli.main`` runs it, without parsing anew nor going through the
        text: its answer as the dict of ``--json``, always one. A command that answers
        nothing, or a reader that raises, answers FAIL with the reason. ``asks``: its questions
        in the application's windows (``ask``), a secret in a masked field that only the command
        reads; one cancelled, it answers that it was declined. Called from a thread, under ``lock``."""
        import contextlib

        from probandia import cli
        from probandia.cli import asking
        from probandia.cli.output import Result

        args, environ, cwd = None, self.ctx.environ, self.ctx.cwd
        out = io.StringIO()
        try:
            try:
                args = self.parser().parse_args([*self.defaults(), *argv, "--json"])
                for k, v in cli.GLOBAL_DEFAULTS.items():
                    if not hasattr(args, k):
                        setattr(args, k, v)
                environ = cli._with_env_files(args, self.ctx.environ, cwd)
                ctx = cli.Context(args, environ, cwd)
                ctx.stdin, ctx.stdout = io.StringIO(), out
                ctx.asks = asks
                with asking.through(self.ask) if asks else contextlib.nullcontext():
                    result = args._spec.run(ctx)
            except asking.Interrupted:
                result = asking.declined()
            except ProbandiaError as err:
                result = cli._from_error(err)
            except Exception:   # a command's defect, as cli.main says it: a log, and its path
                result = cli._internal_error(args, environ, cwd)
            if not isinstance(result, Result):
                first = next((x.strip() for x in out.getvalue().splitlines() if x.strip()), "")
                return {"status": "FAIL", "values": {"REASON": "tui-no-json"},
                        "lines": [_("the command printed no JSON answer") + (f": {first[:80]}" if first else "")]}
            cli._relative(result, args, environ, cwd)
            return result.to_json()
        except Exception as err:   # the reader's own defect
            return {"status": "FAIL", "values": {"REASON": "tui-engine-raised"},
                    "lines": [f"{type(err).__name__}: {err}"]}

    def engine(self, *argv):
        """The answer of a command a screen reads; CommandFailed when it failed, so that
        the screen says why."""
        d = self.answer(*argv)
        if d.get("status") == "FAIL":
            raise CommandFailed(failure(argv, d))
        return d

    def execute(self, argv, shown):
        """A command of the console, in its thread, as a terminal runs it (T107): (its exit code, its
        line, ``shown`` with a secret written <redacted>, then its readable output). Its confirmations
        and the values it asks for come up in the application's windows (``ask``), never in the
        terminal it hides; one engine command at a time."""
        from probandia.cli import asking, tui_cmd

        out = io.StringIO()
        with self.lock, asking.through(self.ask):
            code = tui_cmd.execute([*self.defaults(), *argv], stdout=out, stdin=io.StringIO(),
                                   environ=self.ctx.environ, cwd=self.ctx.cwd,
                                   preview_args=[*self.defaults(), *shown])
        return code, out.getvalue()

    def ask(self, kind, prompt, choices=(), default="", other=False):
        """A question of the console's command (``asking.through``), from its thread: put in a window,
        its answer awaited. True or False for ``confirm``, else the value typed or chosen; None when
        cancelled, or when the application closes meanwhile."""
        import queue

        if kind == "confirm":
            screen = ConfirmScreen(prompt)
        else:
            control = ("password" if kind == "secret" else [(c, c) for c in choices] if choices and not other
                       else "text")
            what = (_("The value, typed unseen") if kind == "secret" else _("Your choice") if not choices
                    else _("Your choice: {choices}").format(choices=", ".join(choices)))
            value = (default if default in choices else choices[0]) if isinstance(control, list) else default or ""
            screen = AskScreen(prompt.strip(), [("answer", what, value, control)])
        answers = queue.Queue()
        if not self.is_running:
            return None
        self.call_from_thread(self.push_screen, screen, answers.put)
        while self.is_running:
            try:
                got = answers.get(timeout=0.1)
            except queue.Empty:
                continue
            return got if kind == "confirm" else got and got["answer"]
        return None

    def busy(self):
        """A read or an action under way, or read and not shown yet."""
        return (any(w.state in (WorkerState.PENDING, WorkerState.RUNNING) for w in self.workers)
                or any(state.busy for pane in self.screen.query(Pane) for state in pane.reads.values()))

    # screens

    def pane(self, name):
        return self.screen.query_one(f"#pane-{name}", Pane)

    def shown(self):
        """The panes on display: the screen's, then that of the tab of its file; none when a
        help, a question or the console's forms are over them."""
        if not isinstance(self.screen, Main):
            return []
        top = self.screen.query_one("#screens", TabbedContent).active_pane
        return [p for p in top.query(Pane) if displayed(p)] if top else []   # none while the tabs are built

    def target(self, tab):
        """What takes the focus when ``tab`` shows: the main widget of the pane it shows, else
        its first list; None when nothing there takes it (T93)."""
        panes = [p for p in tab.query(Pane) if shown_in(p, tab)]
        if panes:
            return panes[0].focus_target()
        return next((w for w in tab.query("DataTable, Tree") if shown_in(w, tab) and w.focusable), None)

    def focus_in(self, tab):
        """The focus on what ``tab`` shows, when it is on display."""
        if tab is not None and displayed(tab):
            self.screen.set_focus(self.target(tab))

    def go(self, tab):
        """``tab`` shown, with the tabs around it, the focus on what it shows. The focus moves
        first: as the screen left is hidden, Textual would move it to another of its widgets,
        and show that screen again (T93). One move: the footer is drawn once (``Keys``)."""
        self.screen.set_focus(self.target(tab))
        for t in tab.ancestors_with_self:   # each tab on the way, the screen's last
            if isinstance(t, TabPane):
                t.parent.parent.active = t.id

    def action_leave(self):
        """Escape: out of a field, the focus on the main widget of its screen (T93)."""
        from textual.widgets import Input

        pane = next((a for a in self.focused.ancestors if isinstance(a, Pane)), None) if isinstance(
            self.focused, Input) else None
        if pane:
            pane.take_focus()

    def action_move(self, step):
        """j, k, g, G: the line of the list or of the tree that has the focus, moved; what has
        no line scrolls (T93)."""
        from textual.widgets import Tree

        widget = self.focused
        if widget is None:
            return
        if isinstance(widget, (DataTable, Tree)):
            names = ("cursor_down", "cursor_up") + (("scroll_top", "scroll_bottom") if isinstance(widget, DataTable)
                                                    else ("scroll_home", "scroll_end"))
        else:   # the report's text: its viewer scrolls
            widget = next((w for w in widget.ancestors_with_self if getattr(w, "allow_vertical_scroll", False)),
                          widget)
            names = ("scroll_down", "scroll_up", "scroll_home", "scroll_end")
        getattr(widget, f"action_{names[step]}")()

    def action_open_file(self):
        """Enter, when what has the focus does not take it: the file of the line chosen."""
        for pane in self.shown()[:1]:
            pane.open_file()

    def action_back(self):
        """Backspace: from the file, back to the list of the screen (T93)."""
        for pane in self.shown()[:1]:
            pane.take_focus()
            pane.main().scroll_visible(animate=False)

    def action_show(self, name):
        """The screen ``name``, or the part or the file's tab ``name`` with its screen."""
        if not isinstance(self.screen, Main):
            self.pop_screen()
        found = self.screen.query(f"#part-{name}")
        self.go(found.first() if found else self.screen.query_one(f"#{name}", TabPane))

    def show(self, name):
        self.action_show(name)

    def action_part(self, step):
        """``[`` and ``]``: the previous or the next tab of the screen, its parts or the file's."""
        from textual.widgets import ContentSwitcher

        top = self.screen.query_one("#screens", TabbedContent).active_pane
        found = top.query(TabbedContent) if top else None
        if found:
            tabs = list(found.first().query_children(ContentSwitcher).first().children)
            now = next(i for i, t in enumerate(tabs) if t.display)
            self.go(tabs[(now + step) % len(tabs)])

    def refresh_screen(self, force=True):
        """The screen shown, read again: always (``force``), or when its files changed."""
        try:
            screen = self.screen
        except ScreenStackError:   # the application is closing
            return
        if isinstance(screen, Main):
            for pane in self.shown():
                pane.refresh_data(force=force)

    def action_search(self):
        """``/``: the filter of the screen shown (T92)."""
        for pane in self.shown():
            found = pane.query_children("#filter")
            if found:
                found.first().focus()
                return

    def action_sync(self):
        """``s``: the balances read from the accounts, at no cost (``usage --sync``)."""
        self.show("quotas")
        self.pane("quotas").fetch(force=True, sync=True)

    def action_refresh(self):
        self.refresh_screen()

    def tick(self):
        """Once a second: the screen shown reads its data again when one of its files
        changed; the others, when they are shown (T90)."""
        try:
            self.refresh_screen(force=False)
        except NoMatches:
            pass   # the screen is being built or taken down: the next tick reads it again

    # actions: an engine command, after a confirmation

    def act(self, question, *argv, then=None, asks=False):
        """Asks ``question``; on yes, runs ``argv`` through the engine in a thread, says
        how it went, and reads the screen again. No question: an action that writes nothing
        and spends nothing, run at once. ``asks``: the command's own questions in windows (``answer``)."""
        def answered(yes):
            if yes:
                self.run_worker(functools.partial(self.reading, lambda _context: (argv, then, self.answer(
                    *argv, asks=asks)), None), name="act", group="act", thread=True, exit_on_error=False)
        if question is None:
            answered(True)
        else:
            self.push_screen(ConfirmScreen(question), answered)

    def on_worker_state_changed(self, event):
        worker = event.worker
        if worker.group == "theme" and worker.state in (WorkerState.SUCCESS, WorkerState.ERROR):
            d = worker.result or {"status": "FAIL", "values": {"REASON": said(worker.error) if worker.error else "?"}}
            if d.get("status") == "FAIL":   # the theme stays for this time: said, not raised
                self.notify(failure(("config", "set", "tui.theme"), d), severity="warning", markup=False)
            return
        if worker.group != "act" or worker.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        if worker.state == WorkerState.ERROR or worker.result is None:
            self.notify(said(worker.error) if worker.error else "?", severity="error", markup=False)
            return
        argv, then, d = worker.result
        from probandia.cli.human import status_label

        text = (failure(argv, d) if d.get("status") == "FAIL"   # what it says, not its contract (T95)
                else " · ".join(notes(d)[:3]) or status_label(d.get("status", "OK")))
        self.notify(text, severity="information" if d.get("status") in ("OK", "WARN") else "error", markup=False)
        if then:
            then(d)
        self.refresh_screen()

    def on_button_pressed(self, event):
        bid = event.button.id or ""
        if bid == "report-render" and self.research:
            self.act(_("Render the report of {research} again?").format(research=self.research),
                     "render", self.research)
        elif bid in ("provider-enable", "provider-disable"):
            provider = self.pane("providers").chosen("providers-list")
            if provider:
                action = bid.split("-")[1]
                question = (_("Enable the provider {provider}?") if action == "enable"
                            else _("Disable the provider {provider}?"))
                self.act(question.format(provider=provider), "providers", action, provider)
        elif bid == "provider-check":
            pane = self.pane("providers")
            variable = pane.chosen("providers-keys")
            if variable:
                self.act(_("Check the key {variable}? A free reading of its account, over the network: nothing is "
                           "spent.").format(variable=variable), "keys", "check", variable, then=pane.checked)
        elif bid == "provider-signup":
            provider = self.pane("providers").chosen("providers-list")
            if provider:   # asked for, as o opens a page: the engine opens the provider's page
                self.act(None, "keys", "signup", provider)
        elif bid == "cache-purge":
            self.pane("diagnostic").purge()
        elif bid in ("library-test", "library-trust"):
            self.pane("library").script(bid.split("-")[1])
        elif bid.startswith("theme-"):
            self.pane("themes").pressed(bid)
        elif bid == "config-set":
            self.pane("config").change()
        elif bid == "config-grade":
            self.pane("config").regrade()
        elif bid == "config-reset":
            self.pane("config").reset()
        elif bid == "config-add":
            self.pane("config").add_rate()
        elif bid in ("config-validate", "config-diff"):
            self.pane("config").report(bid.split("-")[1])
        elif bid == "config-wizard":   # its questions one by one in windows; nothing written until the last
            self.act(_("Answer the essential settings one by one? They are written in the project's settings "
                       "once the last is answered."), "config", "wizard", asks=True)
        elif bid == "key-set":
            self.pane("providers").set_key()
        elif bid == "key-unset":
            self.pane("providers").unset_key()
        elif bid in ("provider-cap", "provider-ttl"):
            provider = self.pane("providers").chosen("providers-list")
            if provider:
                self.pane("config").change(f"providers.{provider}.{'monthly_cap' if bid == 'provider-cap' else 'cache_ttl'}")
        elif bid == "lock-release":
            scope = self.pane("diagnostic").chosen("diagnostic-locks")
            if scope:
                self.act(_("Release the lock {scope}? Only an expired lock is released.").format(scope=scope),
                         "lock", "release", scope, "--expired")
        elif bid in ("proposal-apply", "proposal-drop"):
            self.review(bid.split("-")[1])
        elif bid == "research-earlier":
            self.pane("researches").earlier()
        elif bid == "research-fork" and self.research:
            self.fork()
        elif bid == "person-cite":
            self.pane("family").copy()
        elif bid == "person-root":
            self.pane("family").make_root()
        elif bid in ("research-pause", "research-close") and self.research:
            action = bid.split("-")[1]
            question = (_("Pause the research {research}?") if action == "pause"
                        else _("Close the research {research}?"))
            self.act(question.format(research=self.research),
                     "research", action, self.research, "--yes")

    def fork(self):
        """Fork the research chosen: the pass it starts from and its name are asked, then a
        confirmation. The fork opens no pass, which no agent would hold; once made, it is the
        research chosen (T99)."""
        research, at = self.research, self.pane("researches").passes

        def made(d):
            if d.get("status") != "FAIL":
                self.research = (d.get("values") or {}).get("RESEARCH") or self.research

        def asked(answer):
            if answer is None:
                return
            argv = ["fork", research, *(["--at", answer["fork-at"]] if answer["fork-at"] else []),
                    *(["--name", answer["fork-name"]] if answer["fork-name"] else []), "--no-pass"]
            self.act(_("Fork {research} at pass {n}? The fork opens no pass: resume it in your agent.").format(
                research=research, n=answer["fork-at"] or at), *argv, then=made)

        self.push_screen(AskScreen(_("Fork the research {research}").format(research=research), [
            ("fork-at", _("From the pass"), str(at or ""), "integer"),
            ("fork-name", _("Its name; empty, it is made from this research's"), "", "text")]), asked)

    def goto_setting(self, key):
        """A setting of Help (``key``, or a key with a placeholder) chosen in the Settings, its filters
        cleared."""
        pane = self.pane("config")
        pane.wanted = key
        self.show("config")
        if pane.data is not None:
            pane.guard(pane.show, pane.data)

    def review(self, action):
        """Accept or set aside the proposal shown, its reason asked first, then on to the next one; not
        while an agent holds its research (its buttons greyed)."""
        pane = self.pane("proposals")
        if not pane.selected or pane.query_one(f"#proposal-{action}").disabled:
            return
        pid = pane.selected[0]
        if action == "apply":
            self.act(_("Apply the proposal {proposal} to the family? Once applied, it is corrected "
                       "only by an erratum.").format(proposal=pid), "proposals", "apply", pid, "--yes")
            return

        def asked(answer):
            if answer is None:
                return
            if not answer["drop-reason"]:
                self.notify(_("say why the proposal is dropped"), severity="warning")
                return
            self.act(_("Set the proposal {proposal} aside?").format(proposal=pid),
                     "proposals", "drop", pid, "--reason", answer["drop-reason"], "--yes")

        self.push_screen(AskScreen(_("Set the proposal {proposal} aside").format(proposal=pid),
                                   [("drop-reason", _("why it is set aside"), "", "text")]), asked)

    def action_review(self, action):
        """``a`` and ``x``: the proposal shown accepted or set aside, on the screen Proposals (T102)."""
        if any(isinstance(p, ProposalsPane) for p in self.shown()[:1]):
            self.review(action)

    def action_step(self, step):
        """``n`` and ``p``: the next or the previous proposal (T102)."""
        for pane in self.shown()[:1]:
            if isinstance(pane, ProposalsPane):
                pane.step(step)

    # guards (cli.md § 8.5, PRD R-8)

    def holder(self, research):
        """Who else holds the lock of ``research`` now, or None: a research has one
        writer at a time, and the application only reads it meanwhile. Read in a thread."""
        from probandia.harness import detect
        from probandia.util.locks import Locks, same_session, session_id

        if not research or not self.project:
            return None
        info, expired = Locks(self.project).status(f"research:{research}")
        if info is None or expired:
            return None
        me = {"harness": detect(self.ctx.args.harness, self.ctx.environ)[0],
              "session": session_id(self.ctx.environ)}
        if same_session(info.get("owner"), me):
            return None
        owner = info.get("owner") or {}
        return {"who": "/".join(str(owner.get(k, "?")) for k in ("harness", "agent")),
                "until": info.get("expires", "?")}

    def grey(self, pane, held, buttons, note):
        """The actions of a research an agent holds (``held``) are greyed, with the reason."""
        for bid in buttons:
            pane.query_one(f"#{bid}").disabled = bool(held)
        pane.query_one(f"#{note}", Static).update(
            _("Read only: {who} is writing this research, until {until}").format(**held) if held else "")

    def action_open(self):
        """``o``: on the Family, its HTML tree; elsewhere, the HTML report of the research
        selected, in the browser."""
        shown = self.shown()
        if shown and isinstance(shown[0], FamilyPane):
            shown[0].open_tree()
            return
        try:
            path = self.pane("report").report_path("report.html")
        except ProbandiaError as err:   # the research is gone
            self.notify(err.message, severity="warning", markup=False)
            return
        if path and os.path.isfile(path):
            browse(path)
        else:
            self.notify(_("No HTML report yet"), severity="warning")

    def action_copy(self):
        """``c``: what the screen shown copies: the command that resumes a research, the accounts
        as CSV, the citation of a fact."""
        for pane in self.shown()[:1]:
            pane.copy()

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_command_palette(self):
        """``Ctrl+P``: the palette, its field saying what it finds in the language in effect."""
        from textual.command import CommandPalette

        if self.use_command_palette and not CommandPalette.is_open(self):
            self.push_screen(CommandPalette(id="--command-palette",
                                            placeholder=_("A screen, or a command to fill in…")))

    def action_toggle_theme(self):
        """``t``: the next theme, Probandia's dark and light ones then the person's own, kept in the
        user's settings by the engine (``config set --user tui.theme``), the only write that asks
        nothing (T94)."""
        names = list(self.theme_specs)
        choice = names[(names.index(self.theme_name) + 1) % len(names)] if self.theme_name in names else "light"
        self.use_theme(choice)
        argv = ("config", "set", "tui.theme", choice, "--user")
        self.run_worker(functools.partial(self.reading, lambda _context: self.answer(*argv), None),
                        name="theme", group="theme", thread=True, exit_on_error=False)
