"""Sessions the user opens in the browser for the agent (optimize.md § 3).

``.probandia/logins.json`` keeps, per archive, the state of its session:
``pending`` (a ``login_required`` question waits for the user's answer),
``confirmed`` (the user said they signed in, at ``ts``), ``skipped`` (the source
is left for this research) or ``expired`` (a sign-in screen came back after a
confirmation). Only a state and a time: never a username, a password, a cookie
or a token. ``manual-tasks.jsonl`` lists the pages left unread for want of a
session, when nobody could be asked (``PROBANDIA_HEADLESS=1``).
"""
import datetime
import json
import os

from probandia.util.fs import iso, parse_iso, utc_now

STATES = ("pending", "confirmed", "skipped", "expired")


def _path(project):
    return os.path.join(project, ".probandia", "logins.json")


def load(project):
    try:
        with open(_path(project), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_state(project, archive, state, url=None, research=None, now=None):
    """Records the state of an archive's session; returns its record."""
    data = load(project)
    record = {"state": state, "ts": iso(now or utc_now())}
    if url:
        record["url"] = url
    if research:
        record["research"] = research
    previous = data.get(archive) or {}
    if state in ("pending", "expired") and previous.get("confirmed"):
        record["confirmed"] = previous["confirmed"]
        if previous.get("state") == "confirmed":   # a sign-in screen after a confirmation: the session ended
            record["expired"] = record["ts"]
    if state == "confirmed":
        record["confirmed"] = record["ts"]
    data[archive] = record
    os.makedirs(os.path.dirname(_path(project)), exist_ok=True)
    with open(_path(project), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
    # every change is kept, in order: when the user signed in, when a session ended
    with open(os.path.join(project, ".probandia", "logins-history.jsonl"), "a", encoding="utf-8",
              newline="\n") as fh:
        fh.write(json.dumps(dict(record, archive=archive), ensure_ascii=False) + "\n")
    return record


def state(project, archive):
    return load(project).get(archive)


def pending(project):
    """The archives whose ``login_required`` question waits for an answer."""
    return sorted(a for a, r in load(project).items() if r.get("state") == "pending")


def valid(record, session_hours=None, now=None):
    """True when a confirmed session is still within its indicative duration."""
    if not record or record.get("state") != "confirmed":
        return False
    if not session_hours:
        return True
    when = parse_iso(record["confirmed"])
    return (now or utc_now()) - when < datetime.timedelta(hours=session_hours)


def add_manual_task(project, research, archive, url, reason="login-required", now=None):
    """A page left unread for want of a session: the user will read it by hand."""
    path = os.path.join(project, ".probandia", "manual-tasks.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for task in manual_tasks(project, research):
        if task.get("url") == url:
            return task
    task = {"ts": iso(now or utc_now()), "research": research, "archive": archive, "url": url, "reason": reason}
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(task, ensure_ascii=False) + "\n")
    return task


def manual_tasks(project, research=None):
    path = os.path.join(project, ".probandia", "manual-tasks.jsonl")
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    task = json.loads(line)
                    if research is None or task.get("research") == research:
                        out.append(task)
    except (OSError, ValueError):
        pass
    return out
