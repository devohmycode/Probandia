"""The two bases side by side (WS3-T2): each fact is ``new`` (not in the workshop),
``same`` (same date, place and status), ``divergent`` (a value differs, both kept)
or ``workshop-only`` (not in Probandia).

A divergence is of nature ``precision`` when the two values agree but one says
more (a day in the year the workshop gives, a place it lacks, a stronger status),
``contradiction`` otherwise. A refuted fact the workshop still holds without
``volet_refute`` is ``new`` of nature ``refutation``: the push adds the marker,
the workshop's fact stays (WS-D6).
"""
from probandia.importer import FACTS
from probandia.workshop.prototype.mapping import translate_all

NEW, SAME, DIVERGENT, WORKSHOP_ONLY = "new", "same", "divergent", "workshop-only"
CLASSES = (NEW, SAME, DIVERGENT, WORKSHOP_ONLY)
STRENGTH = {"hypothese": 0, "index": 1, "acte": 2}


class Entry:
    def __init__(self, cls, person, key, index, probandia=None, workshop=None, nature=None, differs=(),
                 translation=None, fact=None):
        self.cls, self.person, self.key, self.index = cls, person, key, index
        self.probandia, self.workshop, self.nature, self.differs = probandia, workshop, nature, list(differs)
        self.translation, self.fact = translation, fact
        self.id = fact["id"] if fact else f"{person}.{key}" + (f".{index}" if index is not None else "")

    def __repr__(self):
        return f"Entry({self.cls!r}, {self.id!r}, {self.nature!r}, {self.differs!r})"


def workshop_facts(people):
    """[(wid, key, index, fact)] of the facts of the workshop that Probandia imports."""
    out = []
    for p in people.get("personnes") or []:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        for key in FACTS:
            value = p.get(key)
            if isinstance(value, dict):
                out.append((str(p["id"]), key, None, value))
            elif isinstance(value, list):
                out += [(str(p["id"]), key, i, v) for i, v in enumerate(value) if isinstance(v, dict)]
    for i, u in enumerate(people.get("unions") or []):
        if isinstance(u, dict):
            out.append((str(u.get("epoux") or u.get("epouse")), "unions", i, u))   # T175: or the wife's alone
    return out


def _pad(iso, tail):
    """1885 -> 1885-01-01 or 1885-12-31; 1885-05 -> 1885-05-01 or 1885-05-31 (a day too many is harmless)."""
    return iso + tail[len(iso) - 4:] if len(iso) < 10 else iso


def _interval(fact):
    """The days a workshop's date may stand for, as ISO strings, or None without a date."""
    from probandia.lang.dates import Unrecognized, read

    text, year = fact.get("date"), fact.get("annee")
    try:
        d = read(str(text)) if text else None
    except Unrecognized:
        d = None
    if d is None:
        if not isinstance(year, int):
            return None
        d = {"iso": f"{year:04d}", "qualifier": "exact", "end": None}
    lo, hi = _pad(d["iso"], "-01-01"), _pad(d.get("end") or d["iso"], "-12-31")
    if d["qualifier"] == "before":
        lo = "0000-01-01"
    elif d["qualifier"] == "after":
        hi = "9999-12-31"
    return lo, hi, (d["iso"], d["qualifier"], d.get("end"))


def differences(p, w):
    """[(field, nature)] where a fact of Probandia and one of the workshop differ."""
    out = []
    a, b = _interval(p), _interval(w)
    if (a and a[2]) != (b and b[2]):
        compatible = a is None or b is None or (a[0] <= b[1] and b[0] <= a[1])
        out.append(("date", "precision" if compatible else "contradiction"))
    lp, lw = str(p.get("lieu") or "").casefold(), str(w.get("lieu") or "").casefold()
    if lp != lw:
        out.append(("lieu", "precision" if not lp or not lw else "contradiction"))
    sp, sw = p.get("statut"), w.get("statut")
    if sp != sw and not (sp == "refute" and w.get("volet_refute")):
        out.append(("statut", "precision" if sp in STRENGTH and sw in STRENGTH else "contradiction"))
    return out


def compare(ctx):
    """[Entry] for every fact of the family and every fact of the workshop."""
    people = ctx.people
    wfacts = workshop_facts(people)
    by_place = {(wid, key, index): f for wid, key, index, f in wfacts}
    claimed, out = set(), []
    superseded = ctx.link.get("superseded") or {}   # refuted by a pull: another fact holds their place
    for _person, fact, t in translate_all(ctx):
        if fact["id"] in superseded:
            continue
        where = (t.person, t.key, t.index)
        w = by_place.get(where) if t.linked else None
        if not t.linked:
            if t.key == "unions":
                where = next(((wid, key, i) for wid, key, i, f in wfacts if key == "unions" and (wid, key, i) not in
                              claimed and f.get("epoux") == t.fact.get("epoux")
                              and f.get("epouse") == t.fact.get("epouse")), where)
            else:
                where = (t.person, t.key, None)
            w = by_place.get(where)
        if w is None:
            if t.linked:   # it was there: someone took it out of the workshop
                out.append(Entry(DIVERGENT, t.person, t.key, t.index, t.fact, None, "contradiction", ["absent"],
                                 t, fact))
            else:
                out.append(Entry(NEW, t.person, t.key, None, t.fact, None, None, (), t, fact))
            continue
        claimed.add(where)
        diffs = differences(t.fact, w)
        if t.fact.get("statut") == "refute" and w.get("statut") != "refute" and not w.get("volet_refute"):
            out.append(Entry(NEW, where[0], where[1], where[2], t.fact, w, "refutation", [], t, fact))
        elif not diffs:
            out.append(Entry(SAME, where[0], where[1], where[2], t.fact, w, None, (), t, fact))
        else:
            nature = "contradiction" if any(n == "contradiction" for _, n in diffs) else "precision"
            out.append(Entry(DIVERGENT, where[0], where[1], where[2], t.fact, w, nature, [f for f, _ in diffs],
                             t, fact))
    for wid, key, index, f in wfacts:
        if (wid, key, index) not in claimed:
            out.append(Entry(WORKSHOP_ONLY, wid, key, index, None, f))
    return out


def counts(entries):
    return {c: sum(1 for e in entries if e.cls == c) for c in CLASSES}
