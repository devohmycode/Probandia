"""The event log of a research: ``events.jsonl``, append only, with a hash chain.

One JSON object per line. ``prev`` is the SHA-256 of the previous line, as UTF-8
bytes without its line end, written ``sha256:<hex>``; it is null on the first
line. The chain lets ``verify`` prove that the log was only ever appended to.
Only ``append`` writes the file, under the research lock.
"""
import hashlib
import json
import os

from probandia.errors import ProbandiaError, SchemaError
from probandia.i18n import _
from probandia.util.fs import iso, utc_now
from probandia.util.ids import ulid
from probandia.util.schema import Validator, check_event_type, load_schema


def line_hash(line):
    """The chain value of one line (without its line end)."""
    return "sha256:" + hashlib.sha256(line.encode("utf-8")).hexdigest()


def encode(event):
    """One line: compact JSON, keys in a fixed order, no line end."""
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def read_lines(path):
    """The lines of the log, without their line ends."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        data = fh.read()
    if not data:
        return []
    lines = data.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def last_hash(path):
    lines = read_lines(path)
    return line_hash(lines[-1]) if lines else None


class ChainError(ProbandiaError):
    reason = "chain-broken"


def check_chain(path):
    """None when the chain holds; otherwise (line number from 1, what is wrong).
    Raises SchemaVersionError on an event type written by a newer version."""
    prev = None
    for n, line in enumerate(read_lines(path), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return n, _("not valid JSON")
        if not isinstance(event, dict):
            return n, _("not an event")
        if event.get("prev") != prev:
            return n, _("prev does not match the line before")
        check_event_type(event, _("events.jsonl, line {n}").format(n=n))
        prev = line_hash(line)
    return None


_validator = None


def validate(event):
    global _validator
    if _validator is None:
        _validator = Validator(load_schema("event", 1))
    issues = _validator.errors(event)
    if issues:
        raise SchemaError(_("invalid event: {first}").format(first=issues[0]), issues,
                          lines=[str(i) for i in issues[1:5]])


def make(type_, payload, actor, pass_no, refs=(), supersedes=None, now=None):
    """A new event, without its ``prev`` yet."""
    return {"id": ulid(), "ts": iso(now or utc_now()), "pass": pass_no, "actor": actor,
            "type": type_, "payload": payload, "refs": list(refs), "supersedes": supersedes}


def append(path, events):
    """Appends events, chaining each to the line before. The caller holds the
    research lock. Refuses to append to a broken chain. Returns the events written."""
    broken = check_chain(path)
    if broken:
        raise ChainError(_("events.jsonl is broken at line {n}: {what}").format(
            n=broken[0], what=broken[1]), values={"LINE": broken[0]})
    prev = last_hash(path)
    lines = []
    for event in events:
        event = dict(event)
        event["prev"] = prev
        validate(event)
        line = encode(event)
        lines.append(line)
        prev = line_hash(line)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return [json.loads(line) for line in lines]


def read(path):
    return [json.loads(line) for line in read_lines(path)]
