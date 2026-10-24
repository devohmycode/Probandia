"""The timeline of a person, for the report (GPS7-T3).

For one person: their dated facts in order, with the age at each, the place,
the status, and the chronology findings that concern them; the facts of their
parents, spouses and children are landmarks. Hypotheses are shown too, and
checked: a lead that clashes with the dates is marked, which helps set it
aside (``apply`` and V-14 check proven facts only). A person presumed living
has no timeline, and a relative presumed living gives no landmark.

``chosen`` picks the persons by ``report.timeline``: ``main`` (the persons the
questions name, those their conclusions are about; for a research without
questions, those its free-text question names; else those the research's
facts are about), ``all`` (every person a fact of the research is about),
``off``. The report shows a timeline only from ``MIN_EVENTS`` dated facts of
the person: one fact alone is no chronology.
"""
from probandia import chronology
from probandia.report import labels as L

SHOWN = ("record", "index", "hypothesis")
MIN_EVENTS = 2
LANDMARKS = {"father": ("death",), "mother": ("death",), "spouse": ("marriage", "death"),
             "child": ("birth", "baptism")}


def _year(fact):
    return chronology.year(fact)


def _name(person):
    names = person.get("names") or {}
    given = names.get("usual") or names.get("given") or ""
    return " ".join(x for x in (given, names.get("surname") or "") if x)


def model(pid, persons, living=(), today=None):
    """The timeline of one person as a dict, or None when they are presumed living or have no dated fact."""
    by_id = {p["id"]: p for p in persons}
    person = by_id.get(pid)
    if person is None or pid in living:
        return None
    own = {f["id"] for f in person.get("facts") or []}
    found = [f for f in chronology.all_findings(persons, {pid}, today, counted=SHOWN)
             if any(x in own for x in f["facts"])]
    status = {f["id"]: f.get("status") for p in persons for f in p.get("facts") or []}
    flagged = {}
    for f in found:
        # a clash with a hypothesis is the hypothesis's: the proven fact it hits is not marked
        culprits = [x for x in f["facts"] if status.get(x) == "hypothesis"] or f["facts"]
        for x in culprits:
            if x in own:
                flagged.setdefault(x, []).append(f)
    born = chronology._pick(person.get("facts") or [], chronology.BIRTH, counted=SHOWN)
    events = []
    for f in person.get("facts") or []:
        y = _year(f)
        if y is None or f.get("status") not in SHOWN:
            continue
        clash = flagged.get(f["id"], [])
        events.append({"fact": f["id"], "type": f["type"], "year": y, "status": f["status"],
                       "qualifier": (f.get("date") or {}).get("qualifier") or "exact",
                       "place": (f.get("place") or {}).get("as_written") or "",
                       "age": (y - born[0]) if born and f["type"] not in chronology.BIRTH else None,
                       "severity": ("error" if any(c["severity"] == "error" for c in clash) else "warning")
                       if clash else None,
                       "findings": [c["message"] for c in clash]})
    if not events:
        return None
    events.sort(key=lambda e: (e["year"], e["type"] not in chronology.BIRTH, e["fact"]))
    relatives = []
    parents = person.get("parents") or {}
    kin = [("father", parents.get("father")), ("mother", parents.get("mother"))]
    kin += [("spouse", s.get("person")) for s in person.get("spouses") or []]
    kin += [("child", p["id"]) for p in persons
            if pid in ((p.get("parents") or {}).get("father"), (p.get("parents") or {}).get("mother"))]
    for role, rid in kin:
        rel = by_id.get(rid or "")
        if rel is None or rid in living:
            continue
        for f in rel.get("facts") or []:
            y = _year(f)
            if y is not None and f["type"] in LANDMARKS[role] and f.get("status") in SHOWN:
                relatives.append({"role": role, "person": rid, "name": _name(rel), "type": f["type"],
                                  "year": y, "fact": f["id"], "status": f["status"]})
    relatives.sort(key=lambda r: (r["year"], r["fact"]))
    years = [e["year"] for e in events] + [r["year"] for r in relatives]
    return {"person": pid, "name": _name(person), "span": [min(years), max(years)], "events": events,
            "relatives": relatives, "findings": found}


def chosen(meta, persons, setting="main"):
    """The persons who get a timeline, in the order of the family's index."""
    if setting == "off":
        return []
    rid = meta.get("id")
    owner = {f["id"]: p["id"] for p in persons for f in p.get("facts") or []}
    of_research = [p["id"] for p in persons if any(f.get("research") == rid for f in p.get("facts") or [])]
    if setting == "all":
        return of_research
    named = set()
    for q in meta.get("questions") or []:
        named.update(q.get("persons") or [])
        named.update(owner[c] for c in q.get("conclusion") or [] if c in owner)
    if not meta.get("questions") and meta.get("question"):
        # a research older than GPS1: the persons its free-text question names
        from probandia.proof.questions import from_text

        for q in from_text(meta["question"], {}, persons):
            named.update(q.get("persons") or [])
    if named:
        return [p["id"] for p in persons if p["id"] in named]
    return of_research


def markdown(tl, t):
    """The timeline as a table: what the report shows without SVG, and under the chart in HTML."""
    from probandia.report.content import table

    rows = []
    for e in tl["events"]:
        what = t(L.FACT_TYPES.get(e["type"], L.FACT_TYPES["other"]))
        if e["status"] == "hypothesis":
            what += " (" + t(L.STATUSES["hypothesis"]).lower() + ")"
        mark = ("✗ " if e["severity"] == "error" else "⚠ ") if e["severity"] else ""
        rows.append((e["year"], "" if e["age"] is None else e["age"], what, e["place"],
                     mark + "; ".join(e["findings"])))
    for r in tl["relatives"]:
        rows.append((r["year"], "", f"{t(L.TIMELINE_ROLES[r['role']])} — {r['name']}: "
                     f"{t(L.FACT_TYPES.get(r['type'], L.FACT_TYPES['other']))}", "", ""))
    rows.sort(key=lambda x: x[0])
    return table([t(L.TIMELINE_HEAD["year"]), t(L.TIMELINE_HEAD["age"]), t(L.TIMELINE_HEAD["event"]),
                  t(L.TIMELINE_HEAD["place"]), t(L.TIMELINE_HEAD["clash"])], rows)
