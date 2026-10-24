"""The readable output: what a person sees at a terminal (cli.md § 6.2).

The same ``Result`` as the contract, laid out for the eye: the status with its
symbol, the values aligned, the lines as bullets, the tables as columns. No
information rests on colour alone; ``--plain`` keeps to ASCII. Standard library
only: the core has no dependency (PRD N-2).
"""
import os
import re
import shutil
import subprocess
import textwrap

from probandia.i18n import _

SYMBOLS = {"OK": "✓", "WARN": "⚠", "FAIL": "✗", "ASK": "?", "STOP": "■"}
PLAIN_SYMBOLS = {"OK": "[ok]", "WARN": "[!]", "FAIL": "[x]", "ASK": "[?]", "STOP": "[stop]"}
COLORS = {"OK": "32", "WARN": "33", "FAIL": "31", "ASK": "34", "STOP": "31"}
DATA_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)=(.*)$")
NUMBER = re.compile(r"^-?[\d\s., ]+(\s?[%$€])?$")


def status_label(status):
    return {"OK": "OK", "WARN": _("warning"), "FAIL": _("failed"), "ASK": _("question"),
            "STOP": _("stopped")}[status]


class Style:
    """How to draw: colours or not, ASCII only or not, and the width to fit."""

    def __init__(self, color=False, plain=False, width=80):
        self.color = color and not plain
        self.plain = plain
        self.width = max(40, width)

    def paint(self, text, code):
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def bold(self, text):
        return self.paint(text, "1")

    def dim(self, text):
        return self.paint(text, "2")

    def symbol(self, status):
        return (PLAIN_SYMBOLS if self.plain else SYMBOLS)[status]

    @property
    def rule(self):
        return "-" if self.plain else "─"

    @property
    def ellipsis(self):
        return "..." if self.plain else "…"


def enable_vt():
    """True when the console shows ANSI colours. Windows consoles need the
    virtual terminal mode switched on; elsewhere a terminal has it."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)   # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


def style_for(stream, environ, args=None):
    """The style for ``stream``: ``NO_COLOR`` and ``--no-color`` turn colours off,
    ``FORCE_COLOR`` on; otherwise a terminal that can show them gets them."""
    plain = bool(getattr(args, "plain", False))
    width = getattr(args, "width", None) or shutil.get_terminal_size((80, 24)).columns
    if plain or getattr(args, "no_color", False) or environ.get("NO_COLOR"):
        color = False
    elif environ.get("FORCE_COLOR") not in (None, "", "0"):
        color = True
    else:
        try:
            color = stream.isatty() and enable_vt()
        except (AttributeError, ValueError):
            color = False
    return Style(color=color, plain=plain, width=width)


def humanize(key):
    """``KEYS_MISSING`` -> ``keys missing``."""
    return key.lower().replace("_", " ")


def show_value(value):
    if isinstance(value, bool):
        return _("yes") if value else _("no")
    if value is None or value == "":
        return "—"
    return str(value)


def cut(text, width, style):
    """``text`` cut to ``width`` characters, with an ellipsis."""
    if len(text) <= width:
        return text
    if width <= len(style.ellipsis):
        return text[:width]
    return text[: width - len(style.ellipsis)] + style.ellipsis


def bar(fraction, style, width=16):
    """A gauge: ``█████░░░`` (``#####...`` in plain style)."""
    fraction = min(1.0, max(0.0, fraction))
    filled = round(fraction * width)
    full, empty = ("#", ".") if style.plain else ("█", "░")
    return full * filled + empty * (width - filled)


def table(columns, rows, style, headers=None):
    """Rows as aligned columns, fitted to the width: the widest columns give way
    first, their cells cut with an ellipsis. Numbers are right-aligned."""
    headers = headers or {c: humanize(c) for c in columns}
    cells = [[show_value(r.get(c)) for c in columns] for r in rows]
    widths = [max([len(headers[c])] + [len(row[i]) for row in cells]) for i, c in enumerate(columns)]
    numeric = [bool(cells) and all(NUMBER.match(row[i]) or row[i] == "—" for row in cells)
               and any(row[i] != "—" for row in cells)
               for i in range(len(columns))]
    gap = 2
    room = style.width - 2 - gap * (len(columns) - 1)
    while sum(widths) > room and max(widths) > 8:
        widest = widths.index(max(widths))
        widths[widest] -= 1

    def line(values, paint=None):
        parts = []
        for i, v in enumerate(values):
            v = cut(v, widths[i], style)
            parts.append(v.rjust(widths[i]) if numeric[i] else v.ljust(widths[i]))
        text = "  " + (" " * gap).join(parts).rstrip()
        return paint(text) if paint else text

    out = [line([headers[c] for c in columns], style.bold),
           "  " + style.dim(style.rule * min(room + gap * (len(columns) - 1), sum(widths) + gap * (len(columns) - 1)))]
    out += [line(row) for row in cells]
    return out


def mark(status, style):
    """The status symbol, in its colour."""
    return style.paint(style.symbol(status), COLORS[status])


def section(title, style):
    """A blank line, then a bold title."""
    return ["", style.bold(title)]


def pairs(items, style, indent=2):
    """``(key, value)`` pairs, the keys dimmed and aligned."""
    items = list(items)
    if not items:
        return []
    w = max(len(k) for k, _v in items)
    return [" " * indent + style.dim(k.ljust(w)) + "  " + cut(show_value(v), style.width - w - indent - 2, style)
            for k, v in items]


def bullets(messages, style, symbol=None):
    """Messages as wrapped bullets; ``symbol`` (a status) replaces the bullet."""
    out = []
    for m in messages:
        head = f"  {mark(symbol, style)} " if symbol else ("  - " if style.plain else "  • ")
        rest = " " * (len(style.symbol(symbol)) + 3 if symbol else 4)
        lines = textwrap.wrap(m, style.width - len(rest), break_long_words=False, break_on_hyphens=False)
        out += [head + lines[0]] + [rest + x for x in lines[1:]] if lines else [head.rstrip()]
    return out


def next_step(command, style):
    """A command to run next: ``→ probandia …``."""
    return style.paint("-> " if style.plain else "→ ", "1") + command


# Layouts of their own, by the name a command gives ``Result.view``.
VIEWS = {}


def render(result, style):
    """The readable form of a ``Result``. Every command has one, even without a
    layout of its own."""
    from probandia.cli import views  # noqa: F401  (registers the layouts)

    if result.view in VIEWS:
        return VIEWS[result.view](result, style)
    out = [style.paint(f"{style.symbol(result.status)} {status_label(result.status)}",
                       COLORS[result.status])]
    if result.values:
        keys = [humanize(k) for k in result.values]
        w = max(len(k) for k in keys)
        for key, value in zip(keys, result.values.values()):
            out.append("  " + style.dim(key.ljust(w)) + "  " + cut(show_value(value), style.width - w - 4, style))
    bullet = "-" if style.plain else "•"
    data, messages = [], []
    for text in result.lines:
        m = DATA_LINE.match(text)
        (data if m else messages).append(m.groups() if m else text)
    if messages:
        out.append("")
        for m in messages:
            out += textwrap.wrap(m, style.width - 2, initial_indent=f"  {bullet} ", subsequent_indent="    ",
                                 break_long_words=False, break_on_hyphens=False) or [f"  {bullet}"]
    if data:
        out.append("")
        w = max(len(humanize(k)) for k, _v in data)
        out += ["  " + style.dim(humanize(k).ljust(w)) + "  " + v for k, v in data]
    for name, t in result.tables.items():
        if t.get("hidden"):
            continue
        out += ["", style.bold(humanize(name))]
        out += table(t["columns"], t["rows"], style)
    if result.details:
        out += ["", style.dim(_("details: {path}").format(path=result.details))]
    return "\n".join(out) + "\n"


# Watch (cli.md 5.1.9)


def watch_option(p):
    """``-w``, ``--watch [s]``: refresh the readable screen every *s* seconds (2 by default)."""
    p.add_argument("-w", "--watch", nargs="?", const=2.0, type=float, metavar="<s>",
                   help=_("refresh the screen every s seconds (2 by default), until Ctrl+C"))


def watch(run, stream, style, interval, sleep, clock, first=None):
    """Shows ``first``, then runs ``run()`` (a fresh Result each time) every
    ``interval`` seconds, clearing the screen, until Ctrl+C. Readable output only."""
    try:
        while True:
            text = render(first if first is not None else run(), style)
            first = None
            footer = _("refreshed every {s} s, at {time} · Ctrl+C to stop").format(
                s=f"{interval:g}", time=clock().strftime("%H:%M:%S"))
            stream.write("\x1b[H\x1b[2J" + text + "\n" + style.dim(footer) + "\n")
            stream.flush()
            sleep(interval)
    except KeyboardInterrupt:
        stream.write("\n")
        stream.flush()
    return 0


# Pager


def terminal_height():
    return shutil.get_terminal_size((80, 24)).lines


BUILTIN = "builtin"


def pager_command(environ):
    """``PROBANDIA_PAGER``, else ``less -R`` (it keeps the colours), else the
    pager built in below. ``PROBANDIA_PAGER=none`` (or empty) turns paging off.
    Windows' ``more`` is never chosen by itself: it reads its input in the
    console's code page, which mangles UTF-8, and drops the colours."""
    if "PROBANDIA_PAGER" in environ:
        value = environ["PROBANDIA_PAGER"].strip()
        return None if value.lower() in ("", "none", "off") else value
    if shutil.which("less"):
        return "less -R"
    return BUILTIN


def read_key():
    """One key from the keyboard, without Enter; ``q`` when none can be read."""
    try:
        if os.name == "nt":
            import msvcrt

            return msvcrt.getwch()
        import termios
        import tty

        fd = os.open("/dev/tty", os.O_RDONLY)
        try:
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                return os.read(fd, 1).decode("utf-8", "replace")
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        finally:
            os.close(fd)
    except (ImportError, OSError):
        return "q"


def builtin_pager(text, stream, key=read_key, height=None):
    """Shows ``text`` a screen at a time, on the same stream as the rest of the
    output: Space for the next screen, Enter for the next line, q to stop."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    height = max(2, height or terminal_height())
    shown, step = 0, height - 1
    while True:
        chunk = lines[shown:shown + step]
        stream.write("".join(line + "\n" for line in chunk))
        shown += len(chunk)
        if shown >= len(lines):
            stream.flush()
            return
        prompt = _("-- {percent} % · Space: next screen, Enter: next line, q: quit --").format(
            percent=round(100 * shown / len(lines)))
        stream.write(prompt)
        stream.flush()
        pressed = key()
        stream.write("\r" + " " * len(prompt) + "\r")
        if pressed in ("q", "Q", "\x1b", "\x03"):
            stream.flush()
            return
        step = 1 if pressed in ("\r", "\n") else height - 1


def page_if_long(text, stream, environ):
    """Shows ``text`` through a pager when it is taller than the terminal. True when
    it did; the caller then writes nothing. The contract keeps its 40-line cut."""
    try:
        if not stream.isatty() or text.count("\n") < terminal_height():
            return False
    except (AttributeError, ValueError):
        return False
    command = pager_command(environ)
    if not command:
        return False
    if command == BUILTIN:
        builtin_pager(text, stream)
        return True
    try:
        subprocess.run(command, input=text, text=True, encoding="utf-8", shell=True, check=False)
    except OSError:
        return False
    return True
