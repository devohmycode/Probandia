"""Questions and confirmations at the keyboard (cli.md § 6.3, § 6.4).

In the readable output, a command that answers ``ASK`` is played the way the
``ask`` skill plays it for an agent: each question is put to the person with
its numbered choices and its default, and the command runs again with the
option that carries the answer. Nothing is ever answered in the person's
place: an empty answer takes the default the command offered, which the
person sees before pressing Enter.

In the terminal application, the console runs a command with a function of
its own (``through``): the questions come up in its modal screens, never in
the terminal it hides (T107).
"""
import contextlib
import threading

from probandia.i18n import _

_given = threading.local()


class Interrupted(Exception):
    """Ctrl+C, or the end of the input, while a question waited."""


@contextlib.contextmanager
def through(ask):
    """The questions of the commands this thread runs, put by ``ask(kind, prompt, choices=(),
    default="", other=False)`` instead of the keyboard. ``kind``: ``confirm`` (True or False),
    ``choose`` (one of ``choices``, or another answer when ``other``), ``secret`` (typed unseen);
    ``ask`` answers None when the person cancelled."""
    _given.ask = ask
    try:
        yield
    finally:
        _given.ask = None


def given():
    """The function that puts this thread's questions (``through``), or None: the keyboard."""
    return getattr(_given, "ask", None)


def terminal(stream):
    """True when ``stream`` is a terminal. Windows answers ``isatty()`` for the NUL
    device too (``open(os.devnull).isatty()`` is True): there the stream must also be
    a console, which ``GetConsoleMode`` tells. A stand-in with no descriptor is
    taken at its word."""
    import sys

    try:
        if not (stream and stream.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform != "win32":
        return True
    try:
        fd = stream.fileno()
    except (AttributeError, ValueError, OSError):
        return True
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(fd)
    except OSError:
        return False
    mode = ctypes.c_uint32()
    return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))


def interactive(stdin, environ):
    """True when a person can answer: the input is a terminal and the run is not
    headless; or the terminal application puts the questions (``through``)."""
    from probandia.questions import headless

    if given() is not None:
        return True
    if headless(environ):
        return False
    return terminal(stdin)


def _read(stdin, stdout, prompt):
    stdout.write(prompt)
    stdout.flush()
    try:
        line = stdin.readline()
    except KeyboardInterrupt:
        raise Interrupted()
    if not line:
        raise Interrupted()
    return line.strip()


def questions(result):
    """[(id, prompt, choices, default, allow_other, option)] of an ``ASK`` result
    the keyboard can answer; [] when it names no option to carry the answer."""
    v = result.values
    out = []
    ids = [q for q in str(v.get("QUESTIONS", "")).split("|") if q]
    if ids:
        for qid in ids:
            key = qid.upper()
            if not v.get(f"OPTION_{key}"):
                return []
            out.append((qid, v.get(f"PROMPT_{key}", qid), [c for c in str(v.get(f"CHOICES_{key}", "")).split("|") if c],
                        v.get(f"DEFAULT_{key}") or "", v.get(f"ALLOW_OTHER_{key}") in (True, "true"),
                        v[f"OPTION_{key}"]))
    elif v.get("OPTION"):
        out.append((v.get("QUESTION", ""), v.get("PROMPT", ""), [c for c in str(v.get("CHOICES", "")).split("|") if c],
                    v.get("DEFAULT") or "", v.get("ALLOW_OTHER") in (True, "true"), v["OPTION"]))
    return out


def ask_one(stdin, stdout, style, prompt, choices, default, allow_other):
    """Puts one question; the answer (a choice, or a free text when allowed). In the terminal
    application, its screen puts it (``through``), and the answer is checked the same way."""
    from probandia.cli import human as h

    shown = [c for c in choices if c != "other"]
    # Choices that are numbers (agents, passes) are typed as they are; the others by their rank.
    by_value = bool(shown) and all(c.isdigit() for c in shown)
    hint = default if by_value else (str(shown.index(default) + 1) if default in shown else default)
    ask = given()
    if ask is None:
        stdout.write(style.bold(prompt) + "\n")
        if by_value:
            stdout.write("  " + ", ".join(shown) + (" " + style.dim(_("or another number")) if allow_other else "")
                         + "\n")
        else:
            for n, choice in enumerate(shown, start=1):
                mark = "  " + style.dim(_("(default)")) if choice == default else ""
                stdout.write(f"  {n}. {choice}{mark}\n")
            if allow_other:
                stdout.write("  " + style.dim(_("or type another answer")) + "\n")
    while True:
        if ask is None:
            answer = _read(stdin, stdout, (_("Your choice [{default}]: ").format(default=hint) if hint
                                           else _("Your choice: ")))
        else:
            answer = ask("choose", prompt, shown, default, allow_other)
            if answer is None:
                raise Interrupted()
            answer = answer.strip()
        if not answer:
            if default:
                return default
        elif by_value:
            if answer in shown or (allow_other and answer.isdigit() and int(answer) > 0):
                return answer
        elif answer.isdigit() and 1 <= int(answer) <= len(shown):
            return shown[int(answer) - 1]
        elif answer in shown or (allow_other and not answer.isdigit()):
            return answer
        wanted = (_("answer with a number, such as {choices}").format(choices=", ".join(shown)) if by_value and allow_other
                  else _("answer with one of: {choices}").format(choices=", ".join(shown)) if by_value
                  else _("answer with a number from 1 to {n}").format(n=len(shown)) if shown
                  else _("type an answer"))
        stdout.write("  " + h.mark("WARN", style) + " " + wanted + "\n")


def answer(result, stdin, stdout, style):
    """The arguments that carry the person's answers to an ``ASK``; None when the
    keyboard cannot answer it. Raises Interrupted on Ctrl+C."""
    asked = questions(result)
    if not asked:
        return None
    extra = []
    for _qid, prompt, choices, default, allow_other, option in asked:
        extra += [option, ask_one(stdin, stdout, style, prompt, choices, default, allow_other)]
    return extra


def declined(values=None):
    """What a command answers when the person said no: nothing written, nothing spent."""
    from probandia.cli.output import Result

    r = Result.stop("declined", values=values)
    r.line(_("nothing was done"))
    return r


def spend_question(ctx, engines, operation="search"):
    """``Search with Tavily (1 search, 900 left)?``: the engines about to be used,
    what one call costs each, and what is left of their free quota."""
    from probandia.cli.search_cmd import _ledger
    from probandia.i18n import formats
    from probandia.providers import catalogue

    cat = catalogue.load()
    ledger = _ledger(ctx)
    reserve = ctx.config.get("budget.reserve_percent")
    parts = []
    for p in engines:
        entry = cat.get(p, {})
        cost = (entry.get("costs") or {}).get(operation, 1)
        left = ledger.left(p, reserve)
        unit = entry.get("unit") or "unit"
        parts.append(_("{name}: {cost} {unit}, {left} left").format(
            name=entry.get("name", p), cost=formats.number(cost), unit=unit,
            left=_("unlimited") if left is None else formats.number(round(left))))
    return "; ".join(parts)


def will_ask(ctx):
    """True when ``confirm`` puts its question to a person: no ``--yes``, and someone at the keyboard."""
    return not getattr(ctx.args, "yes", False) and getattr(ctx, "asks", False)


def confirm(ctx, question):
    """True when the action may go on: ``--yes`` was given, nobody is at the
    keyboard (the contract does what it says), or the person answered yes.
    The answer is ``[y/N]``: anything but yes declines (cli.md § 6.4)."""
    if not will_ask(ctx):
        return True
    if given() is not None:   # the terminal application's yes or no
        return bool(given()("confirm", question))
    stdout, stdin = ctx.stdout, ctx.stdin
    try:
        reply = _read(stdin, stdout, question + " " + _("[y/N]") + " ")
    except Interrupted:
        return False
    return reply.strip().lower() in (_("y"), _("yes"), "y", "yes")
