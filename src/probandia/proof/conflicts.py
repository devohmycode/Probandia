"""Conflicting evidence (GPS4-T2).

Two proven facts (``record`` or ``index``) of the same type for the same person
conflict when their dates cannot both be true, or when they name two places
neither of which contains the other. Each conflict is offered as an open
analysis, its evidence already filled in; ``correlate`` lists them and V-15
asks that each one be analysed.

**Dates.** A date is a range of days: a year, a month or a day as written;
``about`` adds two years on each side, ``calculated`` one; ``before`` and
``after`` are open on one side; ``between`` runs to its ``end``. A date written
in the Julian calendar may carry the old-style year, which began on 25 March:
its range reaches one year later. Two dates conflict when their ranges do not
meet.

**Places.** Two places of the family's index conflict unless they are the same,
or one contains the other through its ``parent`` (a parish and its commune do
not conflict). Places written without an index id conflict when their written
forms differ; one written form against an index place is not judged.
"""
import datetime

from probandia.lang.places import key as fold

PROVEN = ("record", "index")
PLACED = ("birth", "baptism", "marriage", "death", "burial")
SPREAD = {"about": 2, "calculated": 1}
AXES = ("source", "information", "evidence")


def _bounds(value):
    """(first day, last day) of a written date, as ordinals; None when it cannot be read."""
    try:
        neg = value.startswith("-")
        parts = [int(p) for p in value.lstrip("-").split("-")]
    except (AttributeError, ValueError):
        return None
    if neg or not parts or parts[0] < 1:
        return None
    y = parts[0]
    try:
        if len(parts) == 1:
            return datetime.date(y, 1, 1).toordinal(), datetime.date(y, 12, 31).toordinal()
        m = parts[1]
        if len(parts) == 2:
            last = (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1)).day
            return datetime.date(y, m, 1).toordinal(), datetime.date(y, m, last).toordinal()
        d = datetime.date(y, m, parts[2]).toordinal()
        return d, d
    except ValueError:
        return None


def date_range(date):
    """(low, high) days of a fact's date, None for an open side; None when there is no readable date."""
    date = date or {}
    found = _bounds(date.get("value") or "")
    if found is None:
        return None
    lo, hi = found
    qualifier = date.get("qualifier") or "exact"
    if qualifier in SPREAD:
        lo, hi = lo - 366 * SPREAD[qualifier], hi + 366 * SPREAD[qualifier]
    elif qualifier == "before":
        lo = None
    elif qualifier == "after":
        hi = None
    elif qualifier == "between":
        end = _bounds(date.get("end") or "")
        hi = end[1] if end else None
    if date.get("calendar") == "julian" and hi is not None:
        hi += 366   # the old-style year began on 25 March
    return lo, hi


def dates_agree(a, b):
    ra, rb = date_range(a), date_range(b)
    if ra is None or rb is None:
        return True
    (alo, ahi), (blo, bhi) = ra, rb
    if ahi is not None and blo is not None and ahi < blo:
        return False
    if bhi is not None and alo is not None and bhi < alo:
        return False
    return True


def _chain(pid, by_id):
    seen = []
    while pid and pid in by_id and pid not in seen:
        seen.append(pid)
        pid = by_id[pid].get("parent")
    return seen


def places_agree(a, b, places):
    a, b = a or {}, b or {}
    by_id = {p["id"]: p for p in places}
    if a.get("id") and b.get("id"):
        return a["id"] == b["id"] or a["id"] in _chain(b["id"], by_id) or b["id"] in _chain(a["id"], by_id)
    if not a.get("id") and not b.get("id") and a.get("as_written") and b.get("as_written"):
        return fold(a["as_written"]) == fold(b["as_written"])
    return True


def find(persons, places=(), only=None):
    """The conflicts among the proven facts of the persons (``only``: their ids), as dicts:
    ``person``, ``fact_kind``, ``on`` (``date`` or ``place``), ``facts`` and ``values``."""
    out = []
    for p in persons:
        if only is not None and p["id"] not in only:
            continue
        by_type = {}
        for f in p.get("facts") or []:
            if f.get("status") in PROVEN:
                by_type.setdefault(f["type"], []).append(f)
        for kind, facts in sorted(by_type.items()):
            for i, a in enumerate(facts):
                for b in facts[i + 1:]:
                    if not dates_agree(a.get("date"), b.get("date")):
                        out.append({"person": p["id"], "fact_kind": kind, "on": "date", "facts": [a["id"], b["id"]],
                                    "values": [_written(a, "date"), _written(b, "date")]})
                    if kind in PLACED and not places_agree(a.get("place"), b.get("place"), places):
                        out.append({"person": p["id"], "fact_kind": kind, "on": "place", "facts": [a["id"], b["id"]],
                                    "values": [_written(a, "place"), _written(b, "place")]})
    return out


def _written(fact, on):
    if on == "place":
        place = fact.get("place") or {}
        return place.get("as_written") or place.get("id") or ""
    date = fact.get("date") or {}
    value = date.get("value") or ""
    qualifier = date.get("qualifier") or "exact"
    if qualifier == "between" and date.get("end"):
        return f"{value}/{date['end']}"
    return value if qualifier == "exact" else f"{qualifier} {value}"


def missing_axes(a):
    """The number of pieces of evidence of an analysis whose three axes are not all given."""
    return sum(1 for i in a.get("items") or [] if any(not (i.get("axes") or {}).get(k) for k in AXES))


def analysis_id(person, kind):
    return f"an-{person}-{kind}"


def covered(conflict, analyses):
    """The analysis that already deals with a conflict: same person and kind of fact, or one that cites
    both its facts."""
    for a in analyses:
        cited = {i.get("fact") for i in a.get("items") or []}
        if (a["person"] == conflict["person"] and a["fact_kind"] == conflict["fact_kind"]) \
                or set(conflict["facts"]) <= cited:
            return a
    return None


def open_analysis(conflicts, persons, question=None, research=None):
    """One open analysis for the conflicts of one person and kind of fact, its evidence filled in from the
    facts: their source, what each asserts (its date, and its place when the conflict is on the place), and
    their axes when the fact records them."""
    first = conflicts[0]
    facts = {f["id"]: f for p in persons for f in p.get("facts") or []}
    ons = {c["on"] for c in conflicts}
    seen, items = [], []
    for c in conflicts:
        for fid in c["facts"]:
            if fid in seen:
                continue
            seen.append(fid)
            f = facts[fid]
            asserts = " — ".join(x for x in ([_written(f, "date")] if "date" in ons or not f.get("place") else [])
                                 + ([_written(f, "place")] if "place" in ons else []) if x) or "?"
            item = {"source": f.get("source"), "fact": fid, "asserts": asserts}
            if f.get("evidence"):
                item["axes"] = {k: v for k, v in f["evidence"].items() if v}
            items.append(item)
    a = {"id": analysis_id(first["person"], first["fact_kind"]), "person": first["person"],
         "fact_kind": first["fact_kind"], "items": items, "status": "open"}
    if question:
        a["question"] = question
    if research:
        a["research"] = research
    return a


def unanalysed(persons, places, analyses, only=None):
    """The conflicts no analysis deals with yet, grouped by person and kind of fact."""
    groups = {}
    for c in find(persons, places, only):
        if covered(c, analyses) is None:
            groups.setdefault((c["person"], c["fact_kind"]), []).append(c)
    return groups
