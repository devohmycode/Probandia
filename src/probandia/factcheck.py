"""A fact a person checked (T248).

``fact check <fact> --by "<who>" --looked "<what was looked at>"`` writes a
``fact.checked`` event to a research's log, under its lock, and only when a
person is at the keyboard: an agent may never write that someone looked at a
record. The agents' own reviews stay those of ``proofs.yaml`` (``reviewer``).

A check is about the fact, whichever research's log holds it: the digest and
the report read those of every research of the family. A concluding fact (the
conclusion of an answered question) that no one checked is counted by the
digest.
"""
from probandia import events

EVENT = "fact.checked"


def of_log(log, research_id=None):
    """{fact id: [{by, looked, ts, research}]} of one research's events, oldest first."""
    out = {}
    for e in log:
        if e.get("type") != EVENT:
            continue
        p = e.get("payload") or {}
        if p.get("fact"):
            out.setdefault(p["fact"], []).append({"by": p.get("by") or "", "looked": p.get("looked") or "",
                                                  "ts": e.get("ts") or "", "research": research_id})
    return out


def of_family(project, family):
    """The checks of every research of a family, by fact, oldest first."""
    from probandia.research import all_researches

    out = {}
    for r in all_researches(project):
        if r.family != family:
            continue
        for fid, found in of_log(events.read(r.events_path), r.id).items():
            out.setdefault(fid, []).extend(found)
    for found in out.values():
        found.sort(key=lambda c: c["ts"])
    return out


def concluding(meta):
    """The fact ids the answered questions of a research conclude on, in their order."""
    out = []
    for q in (meta or {}).get("questions") or []:
        if q.get("status") == "answered":
            out += [c for c in q.get("conclusion") or [] if "." in c and c not in out]
    return out


def unchecked(meta, checks):
    """The concluding facts of a research that no one checked."""
    return [fid for fid in concluding(meta) if not checks.get(fid)]
