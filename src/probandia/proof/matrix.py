"""The exhaustiveness matrix of a research (GPS3, GPS-D2).

For each question, the source types one expects to search, given its type, its
window and its places (``catalogues/source-types.yaml``), each with the places
and years it concerns and the repositories that may hold it (the place's guide,
else ``catalogues/archives.yaml``).

A question without a window, or whose places have no known country, cannot say
what to expect: it carries one ``unknown`` hole (``window``, ``places``) until
``question edit`` gives it what is missing (GPS-D11).

A country the catalogue has no rule for cannot say what to expect either: its
places get one row ``catalogue_<country>`` (``catalogue_lu``), that no search
settles; the orchestrator settles it with ``matrix justify``, whose reason names
the source types searched there (T235: without it, a question outside France
looked exhaustive with nothing expected).

Then each expected type takes a state (GPS3-T4, GPS-D11):
- ``consulted``: a search of the family's searches.yaml covers it, for each of its
  places: the archive's coverage (types, years, places) and the search's window
  cross it; a search naming types in ``filters.types`` counts for those only;
- ``gap``: a gap of gaps.yaml crosses it and says how it is known (a justification
  or a source);
- ``not_applicable``: the orchestrator said why it does not apply (``matrix justify``);
- ``unjustified_gap``: a gap crosses it, without justification or source;
- ``todo``: nothing yet.
The last two are holes, and so is a ``not_applicable`` without its reason.

The engine writes ``research/<id>/matrix.yaml``: the questions and their rows, and
the ``not_applicable`` entries it was given.
"""
import os

from probandia.archives.coverage import DEPARTMENTS, covers
from probandia.proof import source_types
from probandia.util.fs import iso, utc_now

OPEN_END = 2999
STATES = ("consulted", "gap", "not_applicable", "unjustified_gap", "todo")
HOLES = ("unjustified_gap", "todo")
# The coverage types that answer a question of these types; a source type whose coverage
# has none of them (ten-year indexes, census lists) counts whole.
QUESTION_COVERAGE = {"birth": {"birth", "baptism"}, "marriage": {"marriage"}, "death": {"death", "burial"}}


def regions(place):
    """ISO codes of a place, most precise first (``["FR-56", "FR"]``); [] when unknown."""
    code = str(((place or {}).get("insee") or {}).get("code") or "")
    dep = code[:3] if code.startswith("97") else code[:2]
    if dep in DEPARTMENTS or code.startswith("97"):
        return [f"FR-{dep}", "FR"]
    for j in (place or {}).get("jurisdictions") or []:
        note = j.get("note") or ""
        if j.get("level") == "department" and note.startswith("department "):
            return [f"FR-{note.split()[-1]}", "FR"]
        if j.get("level") == "country" and len(j.get("name") or "") == 2:
            return [j["name"]]
    return []


def _matches(codes, places):
    return any(c == p or c.startswith(p + "-") for c in codes for p in places)


def years_kept(rule, codes, window):
    """The years of ``window`` the records of ``rule`` exist for a place of ``codes``,
    and the notes of the exceptions that apply there."""
    lo, hi = window
    years = set(range(max(lo, rule["from"]), min(hi, rule["to"] or OPEN_END) + 1))
    notes = []
    for x in rule.get("exceptions") or []:
        if not _matches(codes, x["places"]):
            continue
        span = set(range(max(lo, x["from"]), min(hi, x["to"]) + 1))
        if not span:
            continue
        if x["effect"] == "extended":
            years |= span
        elif x["effect"] in ("absent", "replaced"):
            if not years & span:
                continue
            years -= span
        notes.append({"effect": x["effect"], "years": [min(span), max(span)], "note": x["note"],
                      "by": x.get("by"), "references": x["references"]})
    return years, notes


def wanted(coverage, qtype):
    """The coverage types of a source type that answer a question of ``qtype``."""
    coverage = set(coverage)
    return (coverage & QUESTION_COVERAGE.get(qtype, coverage)) or coverage


def _repositories(place, codes, source_type, qtype, span, project, catalogue):
    wanted_types = wanted(source_type["coverage"], qtype)
    out = []
    for repo in (place or {}).get("repositories") or []:
        for h in repo.get("holdings") or []:
            a, b = h.get("years") or (span[0], span[1])
            if h["type"] in wanted_types and a <= span[1] and b >= span[0]:
                out.append({"name": repo["name"], "archive": repo.get("archive")})
                break
    if out or (place or {}).get("repositories"):
        return out
    from probandia.archives.repositories import repositories

    deps = [(c[3:], DEPARTMENTS.get(c[3:], c[3:])) for c in codes if c.startswith("FR-")]
    found = repositories(codes, tuple(span), sorted(wanted_types), deps, project, catalogue)
    return [{"name": r["name"], "archive": r.get("archive")} for r in found
            if r.get("holdings") or r.get("source") == "rule:departmental-archives"]


def expected(question, places, catalogue=None, project=None, archives=None):
    """{question, window, rows, unknown, notes} for one question. ``places`` maps the
    family's place ids to their entries in places.yaml; ``rows`` holds one entry per
    expected source type, in the order of the catalogue."""
    catalogue = catalogue or source_types.load()
    out = {"question": question["id"], "window": question.get("window"), "rows": [], "unknown": [], "notes": []}
    window = question.get("window")
    if not window:
        out["unknown"].append("window")
    located = [(pid, places.get(pid), regions(places.get(pid))) for pid in question.get("places") or []]
    located = [x for x in located if x[2]]
    if not located:
        out["unknown"].append("places")
    if out["unknown"]:
        return out
    span = (window["from"], window["to"])
    for t in catalogue["types"]:
        if question["type"] not in t["answers"]:
            continue
        row = None
        for pid, place, codes in located:
            rule = source_types.rule(t, codes[-1][:2])
            if rule is None:
                continue
            years, notes = years_kept(rule, codes, span)
            if not years:
                continue
            kept = [min(years), max(years)]
            if row is None:
                row = {"type": t["id"], "names": t["names"], "coverage": t["coverage"], "places": [],
                       "years": kept, "repositories": [], "held_by": [], "notes": [],
                       "references": rule["references"]}
            row["places"].append(pid)
            row["years"] = [min(row["years"][0], kept[0]), max(row["years"][1], kept[1])]
            for r in _repositories(place, codes, t, question["type"], kept, project, archives):
                if r not in row["repositories"]:
                    row["repositories"].append(r)
            row["held_by"] += [h for h in rule["held_by"] if h not in row["held_by"]]
            row["notes"] += [n for n in notes if n not in row["notes"]]
        if row:
            out["rows"].append(row)
    countries = sorted({codes[-1][:2] for _p, _e, codes in located}
                       - {r["country"] for t in catalogue["types"] for r in t["rules"]})
    out["notes"] += [{"country": c} for c in countries]
    for c in countries:   # T235: a row no search settles, until matrix justify names the types searched
        out["rows"].append({"type": catalogue_type(c), "names": {}, "coverage": [],
                            "places": [pid for pid, _e, codes in located if codes[-1][:2] == c],
                            "years": [span[0], span[1]], "repositories": [], "held_by": [], "notes": [],
                            "references": []})
    return out


def catalogue_type(country):
    """The matrix row of a country the catalogue has no rule for (T235)."""
    return f"catalogue_{country.lower()}"


# filling (GPS3-T4)


def _overlap(a, b):
    """Two [from, to] spans (None: open) cross."""
    lo = max(x for x in (a[0], b[0], -1) if x is not None)
    hi = min(x for x in (a[1], b[1], OPEN_END + 1) if x is not None)
    return lo <= hi


def consults(search, row, codes, qtype, archives):
    """True when ``search`` covers the expected ``row`` for a place of ``codes``."""
    if search.get("result") == "failed" or search.get("failure"):
        return False
    filters = search.get("filters") or {}
    entry = archives.get(filters.get("archive") or "") or archives.get(search.get("engine") or "")
    if not entry:
        return False
    cov = entry.get("coverage") or {}
    named = set(filters.get("types") or [])
    want = wanted(row["coverage"], qtype)
    if not set(cov.get("types") or []) & want:
        return False
    if named and row["type"] not in named and not named & want:
        return False
    if cov.get("years") and not _overlap(cov["years"], row["years"]):
        return False
    window = search.get("window") or {}
    if window and not _overlap((window.get("from"), window.get("to")), row["years"]):
        return False
    return covers(cov.get("places") or [], codes) and not covers(cov.get("absent") or [], codes)


def _gap_crosses(gap, row):
    if gap.get("types"):
        if row["type"] not in gap["types"]:
            return False
    elif gap["archive"] not in {r.get("archive") for r in row["repositories"]} | {r["name"] for r in row["repositories"]}:
        return False
    if gap.get("place") and gap["place"] not in row["places"]:
        return False
    return _overlap((gap["window"]["from"], gap["window"]["to"]), row["years"])


def fill(found, qtype, places, searches, gaps, not_applicable=(), archives=None):
    """The rows of ``expected`` with their state and what settles it."""
    if archives is None:
        from probandia.archives.finder import load_catalogue

        archives = load_catalogue()
    said = {x["type"]: x for x in not_applicable if x.get("question") == found["question"]}
    rows = []
    for row in found["rows"]:
        out = {k: row[k] for k in ("type", "places", "years", "repositories")}
        hits, all_places = [], True
        for pid in row["places"]:
            codes = regions(places.get(pid))
            mine = [s["id"] for s in searches if consults(s, row, codes, qtype, archives)]
            all_places = all_places and bool(mine)
            hits += [s for s in mine if s not in hits]
        crossing = [g for g in gaps if _gap_crosses(g, row)]
        justified = [g for g in crossing if g.get("justification") or g.get("source")]
        if hits and all_places:
            out["state"] = "consulted"
        elif justified:
            out["state"] = "gap"
        elif row["type"] in said:
            out["state"] = "not_applicable"
            if said[row["type"]].get("reason"):
                out["reason"] = said[row["type"]]["reason"]
        elif crossing:
            out["state"] = "unjustified_gap"
        else:
            out["state"] = "todo"
        out["searches"] = hits
        out["gaps"] = [g.get("id") or g["archive"] for g in crossing]
        rows.append(out)
    return rows


def holes(question_matrix):
    """The holes of one question: its unknowns, then its rows still open."""
    out = [f"unknown:{u}" for u in question_matrix.get("unknown") or []]
    for row in question_matrix.get("rows") or []:
        if row["state"] in HOLES or (row["state"] == "not_applicable" and not row.get("reason")):
            out.append(row["type"])
    return out


def path(research):
    return os.path.join(research.folder, "matrix.yaml")


def read(research):
    """The stored matrix, or None."""
    from probandia.util import yamlio
    from probandia.util.schema import validate_document

    p = path(research)
    if not os.path.exists(p):
        return None
    return validate_document("matrix", yamlio.load(p), os.path.relpath(p, research.project))


def build(research, meta=None, not_applicable=None, catalogue=None, archives=None, now=None):
    """The matrix of a research, from its questions and its family's indexes."""
    from probandia.indexes import FamilyIndexes
    from probandia.proof import questions

    meta = meta if meta is not None else research.meta()
    if not_applicable is None:
        not_applicable = (read(research) or {}).get("not_applicable") or []
    idx = FamilyIndexes(research.project, research.family)
    places = {p["id"]: p for p in idx.items("places")}
    searches, gaps = idx.items("searches"), idx.items("gaps")
    catalogue = catalogue or source_types.load()
    if archives is None:
        from probandia.archives.finder import load_catalogue

        archives = load_catalogue(research.project)
    out = {"schema": 1, "research": research.id, "updated": iso(now or utc_now()), "questions": [],
           "not_applicable": list(not_applicable)}
    for q in questions.of(meta):
        found = expected(q, places, catalogue, research.project, archives)
        out["questions"].append({"id": q["id"], "type": q["type"], "status": q.get("status", "open"),
                                 "window": found["window"], "unknown": found["unknown"],
                                 "notes": [n["country"] for n in found["notes"]],
                                 "rows": fill(found, q["type"], places, searches, gaps, not_applicable, archives)})
    return out


def write(research, doc):
    """Writes matrix.yaml; the caller holds the research lock when it changes ``not_applicable``."""
    from probandia.util import yamlio
    from probandia.util.schema import validate_document

    validate_document("matrix", doc, "matrix.yaml")
    yamlio.dump(path(research), doc)
    return path(research)
