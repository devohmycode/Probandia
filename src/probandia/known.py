"""``known``: what the family already knows, before any search.

It reads only the family indexes and returns:
- the facts that match: names through their phonetic keys and attested
  variants, places with their old names, dates within the window;
- the negatives, still valid or due for a recheck;
- the open hypotheses;
- the gaps that overlap the window.
"""
import datetime
import re

from probandia.errors import UsageError
from probandia.i18n import _
from probandia.indexes import FamilyIndexes
from probandia.lang.phonetic import fold, same_name
from probandia.util.fs import parse_iso


def parse_window(text):
    """``1840-1860``, ``1851`` or ``1851+-5`` (also ``1851±5``) -> (from, to)."""
    if not text:
        return None
    t = text.strip().replace("±", "+-")
    m = re.fullmatch(r"(-?\d{1,4})\s*\+-\s*(\d{1,3})", t)
    if m:
        y, d = int(m.group(1)), int(m.group(2))
        return y - d, y + d
    m = re.fullmatch(r"(-?\d{1,4})\s*-\s*(-?\d{1,4})", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return min(a, b), max(a, b)
    m = re.fullmatch(r"-?\d{1,4}", t)
    if m:
        return int(t), int(t)
    raise UsageError(_("invalid window {window}: expected 1840-1860, 1851 or 1851+-5").format(
        window=text))


def split_list(text):
    if not text:
        return []
    return [x.strip() for x in re.split(r"[,;]", text) if x.strip()]


def _year_span(fact):
    date = fact.get("date") or {}
    value, end = date.get("value") or "", date.get("end") or ""
    try:
        start = int(value[:4])
    except ValueError:
        return None
    try:
        stop = int(end[:4]) if end else start
    except ValueError:
        stop = start
    return start, stop


def _overlaps(span, window):
    return span is not None and span[0] <= window[1] and span[1] >= window[0]


class Matcher:
    def __init__(self, names, places, window, variants, place_index):
        self.names = names
        self.places = [fold(p) for p in places]
        self.window = window
        self.variants = variants
        # every written form of a place -> its id
        self.place_ids = set()
        for p in place_index:
            forms = [p["id"], p.get("current_name") or ""] + list(p.get("names_as_written", []))
            if any(fold(f) in self.places for f in forms if f):
                self.place_ids.add(p["id"])

    def surname_forms(self, surname):
        forms = {surname}
        for name, attested in self.variants.items():
            all_forms = {name} | {a["form"] for a in attested}
            if any(same_name(surname, f) for f in all_forms):
                forms |= all_forms
        return forms

    def name_ok(self, surname):
        if not self.names:
            return True
        forms = self.surname_forms(surname)
        return any(same_name(q, f) for q in self.names for f in forms)

    def place_ok(self, fact):
        if not self.places:
            return True
        place = fact.get("place") or {}
        if place.get("id") in self.place_ids:
            return True
        return fold(place.get("as_written") or "") in self.places

    def window_ok(self, fact):
        return not self.window or _overlaps(_year_span(fact), self.window)


def known(project, family, names=(), places=(), window=None, config=None, today=None):
    """{facts, negatives, hypotheses, gaps}: lists of dicts, best first."""
    today = today or datetime.date.today()
    idx = FamilyIndexes(project, family)
    variants = idx.load("variants").get("surnames", {})
    m = Matcher(list(names), list(places), window, variants, idx.items("places"))

    facts = []
    for person in idx.items("persons"):
        surname = (person.get("names") or {}).get("surname", "")
        if not m.name_ok(surname):
            continue
        for f in person.get("facts", []):
            if f["status"] == "refuted":
                continue
            if m.place_ok(f) and m.window_ok(f):
                facts.append(f)

    recheck_days = config.get("negatives.recheck_days") if config else 365
    negatives = []
    for s in idx.items("searches"):
        if s["result"] != "negative" or s.get("family") == "opaque":
            continue  # an opaque engine (a native search) never makes a negative
        if names:
            tokens = re.findall(r"[^\W\d_]+", s.get("query", "")) + list(s.get("variants", []))
            if not any(m.name_ok(t) for t in tokens):
                continue
        w = s.get("window") or {}
        if window and w.get("from") is not None and not _overlaps((w["from"], w["to"]), window):
            continue
        if s.get("recheck_after"):
            due = datetime.date.fromisoformat(s["recheck_after"]) <= today
        else:
            due = (today - parse_iso(s["ts"]).date()).days >= recheck_days
        negatives.append(dict(s, state="due" if due else "valid"))

    hypotheses = [h for h in idx.items("hypotheses") if not h.get("closed")]
    gaps = [g for g in idx.items("gaps")
            if not window or _overlaps((g["window"]["from"], g["window"]["to"]), window)]
    return {"facts": facts, "negatives": negatives, "hypotheses": hypotheses, "gaps": gaps}


def date_text(fact):
    """``1898``, ``about:1896``, or ``?``."""
    date = (fact.get("date") or {}).get("value") or "?"
    qual = (fact.get("date") or {}).get("qualifier")
    return f"{qual}:{date}" if qual and qual != "exact" else date


def place_text(fact):
    return (fact.get("place") or {}).get("id") or (fact.get("place") or {}).get("as_written") or "?"


def lines(found):
    """Data lines, one per item: ``fact=<id> <type> <date> <place> [<status>] <source>``."""
    out = []
    for f in found["facts"]:
        date, place = date_text(f), place_text(f)
        out.append(f"fact={f['id']} {f['type']} {date} {place} [{f['status']}] {f.get('source') or '-'}")
    for s in found["negatives"]:
        w = s.get("window") or {}
        out.append(f"negative={s['id']} {s['state']} \"{s['query']}\" {s.get('engine') or s['kind']} "
                   f"{w.get('from', '?')}-{w.get('to', '?')}")
    for h in found["hypotheses"]:
        out.append(f"hypothesis={h['id']} {h['question']}")
    for g in found["gaps"]:
        out.append(f"gap={g['archive']} {g.get('reference') or '-'} "
                   f"{g['window']['from']}-{g['window']['to']} {g['kind']}")
    return out
