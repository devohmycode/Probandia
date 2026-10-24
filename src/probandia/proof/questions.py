"""The questions of a research (GPS1).

A research may carry ``questions`` in ``research.yaml``: each one with an id
(``Q1``, ``Q2``…), its text, its type (the planner's), the persons, window and
places it is about, what will count as an answer (``standard``, T249), and a status:
- ``open``: still searched;
- ``answered``: its ``conclusion`` lists the facts (or analyses) that answer it;
- ``unresolved``: given up, with its ``reason``.

A research written before GPS1 has only its free-text ``question``: it stands
as ``Q1``. The engine writes the questions, under the research lock, with a
``question.added`` or ``question.updated`` event; ``close`` refuses a research
whose questions are not all answered or unresolved.
"""
import re

from probandia.errors import UsageError
from probandia.i18n import _
from probandia.lang.places import key as fold
from probandia.planner import TYPES, detect_type, find_indexed_person, find_window
from probandia.util.fs import iso, utc_now

STATUSES = ("open", "answered", "unresolved")
ID = re.compile(r"^Q[1-9][0-9]*$")
SPLIT = re.compile(r"(?<=\?)\s+|\s*;\s*|\s*\n+\s*")


def of(meta):
    """The questions of a research, as dicts; the free-text question as Q1 when
    the research has none."""
    found = (meta or {}).get("questions")
    if found:
        return [dict(q) for q in found]
    text = ((meta or {}).get("question") or "").strip()
    if not text:
        return []
    return [{"id": "Q1", "text": text, "type": detect_type(text), "status": "open"}]


def get(meta, qid):
    qid = (qid or "").upper()
    for q in of(meta):
        if q["id"] == qid:
            return q
    raise UsageError(_("no question {id} in this research").format(id=qid),
                     values={"REASON": "no-question", "QUESTION": qid})


def unsettled(meta):
    """The questions still open."""
    return [q for q in of(meta) if q.get("status", "open") == "open"]


def next_id(questions):
    numbers = [int(q["id"][1:]) for q in questions if ID.match(q.get("id", ""))]
    return f"Q{max(numbers, default=0) + 1}"


def split(text):
    """The questions a free text asks: one per question mark, semicolon or line. A sentence that ends
    with a full stop after a question tells about it, and stays with it (T224: "… ? The act is in the
    project.")."""
    out = []
    for part in (p.strip() for p in SPLIT.split(text or "")):
        if part and out and out[-1].endswith("?") and part.endswith((".", "!")) and "?" not in part:
            out[-1] = f"{out[-1]} {part}"
        elif part:
            out.append(part)
    return out or ([text.strip()] if text and text.strip() else [])


def place_ids(text, places):
    """The places of the family's index the text names."""
    words = f" {fold(text)} "
    out = []
    for p in places:
        names = [p.get("current_name") or ""] + list(p.get("names_as_written") or [])
        if any(n and f" {fold(n)} " in words for n in names) and p["id"] not in out:
            out.append(p["id"])
    return out


def from_text(text, family=None, persons=(), places=()):
    """The questions of a new research, from its free text: typed, with the
    persons, window and places that can be read from it. A question that names
    nobody is about the person of the question before it ("… Where did he die?")."""
    family = family or {}
    out, previous = [], []
    for n, part in enumerate(split(text), start=1):
        q = {"id": f"Q{n}", "text": part, "type": detect_type(part), "status": "open"}
        person = find_indexed_person(part, persons)
        who = [person["id"]] if person else previous
        if who:
            q["persons"] = list(who)
        start, end, how = find_window(part, family)
        if how != "family" and start and end:
            q["window"] = {"from": start, "to": end}
        where = place_ids(part, places)
        if where:
            q["places"] = where
        previous = who
        out.append(q)
    return out


def _window(value):
    if value in (None, ""):
        return None
    m = re.match(r"^\s*(\d{4})\s*(?:-|–|\.\.)\s*(\d{4})\s*$", str(value)) or re.match(r"^\s*(\d{4})\s*$", str(value))
    if not m:
        raise UsageError(_("a window is written FROM-TO, such as 1849-1853: {value}").format(value=value))
    start, end = int(m.group(1)), int(m.group(m.lastindex))
    if end < start:
        raise UsageError(_("the window ends before it starts: {value}").format(value=value))
    return {"from": start, "to": end}


def _ids(values):
    out = []
    for v in values or []:
        for item in str(v).split(","):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out


def _check_type(kind):
    if kind and kind not in TYPES:
        raise UsageError(_("unknown question type {type}; types: {types}").format(type=kind, types=", ".join(TYPES)))


def add(questions, text, kind=None, persons=(), places=(), window=None, now=None, standard=None):
    """The questions with a new one appended; returns (questions, the new one). ``standard``: what will
    count as an answer (T249)."""
    text = (text or "").strip()
    if not text:
        raise UsageError(_("give the text of the question"))
    _check_type(kind)
    q = {"id": next_id(questions), "text": text, "type": kind or detect_type(text), "status": "open"}
    if _ids(persons):
        q["persons"] = _ids(persons)
    if _window(window):
        q["window"] = _window(window)
    if _ids(places):
        q["places"] = _ids(places)
    if (standard or "").strip():
        q["standard"] = " ".join(standard.split())
    q["updated"] = iso(now or utc_now())
    return questions + [q], q


def edit(questions, qid, text=None, kind=None, persons=None, places=None, window=None, now=None, standard=None):
    """The questions with one changed: only what is given changes."""
    _check_type(kind)
    out, found = [], None
    for q in questions:
        if q["id"] == qid:
            q = dict(q)
            if text is not None and text.strip():
                q["text"] = text.strip()
            if kind:
                q["type"] = kind
            for key, value in (("persons", persons), ("places", places)):
                if value:
                    q[key] = _ids(value)
            if window:
                q["window"] = _window(window)
            if (standard or "").strip():   # T249: what will count as an answer
                q["standard"] = " ".join(standard.split())
            q["updated"] = iso(now or utc_now())
            found = q
        out.append(q)
    if found is None:
        raise UsageError(_("no question {id} in this research").format(id=qid),
                         values={"REASON": "no-question", "QUESTION": qid})
    return out, found


def settle(questions, qid, status, conclusion=(), reason=None, now=None):
    """The questions with one answered (its conclusion) or unresolved (its reason),
    or opened again."""
    if status == "answered" and not _ids(conclusion):
        raise UsageError(_("an answered question names its conclusion: the facts that answer it (--conclusion)"))
    if status == "unresolved" and not (reason or "").strip():
        raise UsageError(_("an unresolved question says why (--reason)"))
    out, found = [], None
    for q in questions:
        if q["id"] == qid:
            q = {k: v for k, v in q.items() if k not in ("conclusion", "reason")}
            q["status"] = status
            if status == "answered":
                q["conclusion"] = _ids(conclusion)
            if status == "unresolved":
                q["reason"] = reason.strip()
            q["updated"] = iso(now or utc_now())
            found = q
        out.append(q)
    if found is None:
        raise UsageError(_("no question {id} in this research").format(id=qid),
                         values={"REASON": "no-question", "QUESTION": qid})
    return out, found


def missing_facts(question, persons):
    """The conclusion's fact ids that the family's index does not know."""
    known = {f.get("id") for p in persons for f in p.get("facts") or []}
    return [c for c in question.get("conclusion") or [] if "." in c and c not in known]


def write(project, research, actor, expiry, questions, event_type, payload):
    """Writes the questions to research.yaml and logs the change, under the research lock."""
    from probandia import events, lifecycle
    from probandia.indexes import locked

    with locked(project, f"research:{research.id}", actor, expiry, wait_seconds=5):
        lifecycle.update_meta(research, questions=questions)
        last = lifecycle.pass_state(events.read(research.events_path))[0]
        events.append(research.events_path, [events.make(event_type, payload, actor, last)])
