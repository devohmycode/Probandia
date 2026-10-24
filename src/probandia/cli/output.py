"""Output contract of every command.

Text form, at most 40 lines::

    STATUS=OK                      first line: OK | WARN | FAIL | ASK | STOP
    RESEARCH=2026-09-30-parents-of-victor-hugo
    - up to a few human-readable lines, each starting with "- "
    DETAILS=families/hugo/research/…/work/details/01J9….md

- Keys are ``[A-Z_]+``. Values fit on one line, with newlines escaped as ``\\n``.
- ``ASK`` carries QUESTION, PROMPT, CHOICES, ALLOW_OTHER and DEFAULT, or, for
  questions asked together, QUESTIONS and those keys suffixed ``_<ID>``.
- ``STOP`` carries REASON and, when there is one, ALTERNATIVE.
- ``--json`` prints one object instead: {"status", "values", "lines", "details"},
  plus ``data`` ({name: [record, …]}) when the command filled tables.
- ``--quiet`` keeps STATUS and DETAILS, plus the keys that ASK and STOP need.
- RESEARCH comes only from the commands that create or pick the research
  (``KEEPS_RESEARCH`` in ``cli/__init__.py``); ``--json`` always has it.
"""
import json
import re

from probandia.errors import EXIT_ASK, EXIT_FAIL, EXIT_OK, EXIT_STOP
from probandia.i18n import _
from probandia.limits import OUTPUT_MAX_LINES

STATUSES = ("OK", "WARN", "FAIL", "ASK", "STOP")
KEY_RE = re.compile(r"^[A-Z_]+$")
EXIT_BY_STATUS = {"OK": EXIT_OK, "WARN": EXIT_OK, "FAIL": EXIT_FAIL, "ASK": EXIT_ASK, "STOP": EXIT_STOP}
ASK_KEYS = ("QUESTION", "PROMPT", "CHOICES", "ALLOW_OTHER", "DEFAULT", "OPTION", "TOOL", "QUESTIONS")
ASK_GROUP_PREFIXES = ("PROMPT_", "CHOICES_", "DEFAULT_", "ALLOW_OTHER_", "OPTION_")
STOP_KEYS = ("REASON", "ALTERNATIVE")


def escape(value):
    """One line per value: newlines become the two characters \\n."""
    if isinstance(value, bool):
        value = "true" if value else "false"
    return str(value).replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


class Result:
    """What a command returns. The CLI prints it and exits with its code."""

    def __init__(self, status="OK", values=None, lines=None, details=None, exit_code=None):
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        self.status = status
        self.values = {}
        for k, v in (values or {}).items():
            self.set(k, v)
        self.lines = [str(line) for line in (lines or [])]
        self.details = details
        self.exit_code = EXIT_BY_STATUS[status] if exit_code is None else exit_code
        self.tables = {}   # name -> {"columns": [...], "rows": [{...}, ...]}
        self.view = None   # the name of a readable layout of its own (cli.human.VIEWS)
        self.extra = None  # what that layout needs beyond values, lines and tables
        self.raw = None    # a text printed as it is (CSV, Markdown) instead of the contract

    def set(self, key, value):
        if not KEY_RE.match(key) or key in ("STATUS", "DETAILS"):
            raise ValueError(f"invalid output key {key!r}")
        self.values[key] = value
        return self

    def line(self, text):
        self.lines.append(str(text))
        return self

    def data(self, key, text):
        """A data line, ``key=text``: a value to read, not a message to translate."""
        self.lines.append(f"{key}={text}")
        return self

    def table(self, name, rows, columns=None, hidden=False):
        """Structured records (a list of dicts) for ``--json`` and the readable
        output. The text of the contract does not show them; a ``hidden`` table
        is for ``--json`` only, its records already on the readable screen (T111)."""
        rows = [dict(r) for r in rows]
        if columns is None:
            columns = list(dict.fromkeys(k for r in rows for k in r))
        self.tables[name] = {"columns": list(columns), "rows": rows, "hidden": hidden}
        return self

    @classmethod
    def ask(cls, question, prompt, choices, default, allow_other=False, values=None):
        r = cls("ASK", values)
        r.set("QUESTION", question).set("PROMPT", prompt)
        r.set("CHOICES", "|".join(choices)).set("ALLOW_OTHER", bool(allow_other))
        r.set("DEFAULT", default)
        return r

    @classmethod
    def stop(cls, reason, alternative=None, values=None):
        r = cls("STOP", values)
        r.set("REASON", reason)
        if alternative:
            r.set("ALTERNATIVE", alternative)
        return r

    # rendering

    def fits(self, max_lines=OUTPUT_MAX_LINES):
        """True when the text form needs no cut."""
        return (1 + len(self.values) + len(self.lines) + (1 if self.details else 0)) <= max_lines

    def render_text(self, quiet=False, max_lines=OUTPUT_MAX_LINES):
        """The text form, capped at ``max_lines`` lines (None: no cap)."""
        keep = ASK_KEYS if self.status == "ASK" else STOP_KEYS if self.status == "STOP" else ()
        values = [(k, v) for k, v in self.values.items()
                  if not quiet or k in keep or (self.status == "ASK" and k.startswith(ASK_GROUP_PREFIXES))]
        head = [f"STATUS={self.status}"] + [f"{k}={escape(v)}" for k, v in values]
        tail = [f"DETAILS={escape(self.details)}"] if self.details else []
        body = [] if quiet else [f"- {escape(line)}" for line in self.lines]
        if max_lines is None:
            return "\n".join(head + body + tail) + "\n"
        room = max_lines - len(head) - len(tail)
        if room < 0:  # too many keys: keep the first ones, and say so
            head = head[: max_lines - len(tail) - 1]
            head.append("- " + _("{n} more values omitted").format(n=len(values) - (len(head) - 1)))
            body = []
        elif len(body) > room:
            omitted = len(body) - room + 1
            body = body[: room - 1] + ["- " + _("… {n} more lines omitted").format(n=omitted)] if room else []
        return "\n".join(head + body + tail) + "\n"

    def to_json(self):
        out = {"status": self.status, "values": self.values, "lines": self.lines,
               "details": self.details}
        if self.tables:
            out["data"] = {name: t["rows"] for name, t in self.tables.items()}
        return out

    def render_json(self):
        # a date or a time in a record (an account's renewal) is written as ISO 8601
        return json.dumps(self.to_json(), ensure_ascii=False,
                          default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)) + "\n"
