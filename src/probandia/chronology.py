"""Chronology checks, used by ``apply``, ``verify`` (V-18) and the report's timelines.

Each finding names the facts it concerns:
- a date that does not exist (1851-02-30), or lies in the future;
- a death or burial before the birth or baptism;
- a marriage before the age of 12, or after the death;
- an age at death above 110;
- a parent under 12 at the child's birth, a mother over 55, or a child born
  after its mother's death, or more than a year after its father's;
- given the sources (T244), a fact dated after the act of its source that
  records it, or more than a year before it: only an act of the fact's own type
  counts (a birth and its act of birth or of baptism), since an act of death
  also gives a date of birth, and a mention in the margin dates another event.

Only ``record`` and ``index`` facts count: hypotheses and refuted facts are
leads, not dates to check.

``findings`` gives each one as a dict (GPS7-T1): ``code``, ``person``,
``facts``, ``years``, ``severity`` (``error`` when the dates cannot both be
true, ``warning`` when they are only unlikely) and ``message``. ``check``
keeps the ``P-9: <message>`` lines that ``apply`` gives as its reasons.
"""
import datetime
import os
import re

from probandia.i18n import _
from probandia.lang import calendars as cal

BIRTH = ("birth", "baptism")
END = ("death", "burial")
COUNTED = ("record", "index")
MIN_PARENT_AGE = 12
MAX_MOTHER_AGE = 55
MAX_AGE = 110
# what each finding is: impossible (error) or unlikely (warning)
SEVERITY = {"date-invalid": "error", "date-future": "error", "death-before-birth": "error",
            "age-over": "warning", "married-young": "warning", "married-after-death": "error",
            "parent-young": "error", "mother-old": "warning", "born-after-death": "error",
            "after-its-act": "error", "late-act": "warning"}
# T244: the acts that record a fact of each type, in the terms of the citation models (catalogues/citations)
ACTS_OF = {"birth": ("birth", "baptism"), "baptism": ("baptism",), "marriage": ("marriage",),
           "death": ("death", "burial"), "burial": ("burial",)}
ACT_ALIASES = {"inhumation": "burial", "interment": "burial", "christening": "baptism"}
ACT_FILLER = {"acte", "act", "de", "d", "of", "record", "certificate", "entry"}
DAY = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_acts = {}


def year(fact, last=False):
    date = fact.get("date") or {}
    value = (date.get("end") if last and date.get("end") else date.get("value")) or ""
    try:
        return int(value[:5] if value.startswith("-") else value[:4])
    except ValueError:
        return None


def date_exists(value):
    parts = value.lstrip("-").split("-")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if len(nums) == 3:
        return cal.valid_gregorian(*nums)
    if len(nums) == 2:
        return 1 <= nums[1] <= 12
    return True


def _pick(facts, types, last=False, counted=COUNTED):
    """(year, fact id) of the earliest (or latest) counted fact of these types."""
    found = [(year(f, last), f["id"]) for f in facts
             if f["type"] in types and f.get("status") in counted and year(f, last) is not None]
    if not found:
        return None
    return max(found) if last else min(found)


def _finding(code, person, facts, years, message):
    return {"code": code, "person": person, "facts": list(facts), "years": list(years),
            "severity": SEVERITY[code], "message": message}


def findings(person, by_id, today=None, counted=COUNTED, sources=None):
    """The chronology findings of one person, as dicts. ``counted``: the statuses whose facts are
    checked; the report's timelines add ``hypothesis``, to mark a lead that clashes (GPS7). ``sources``:
    the family's, by id, to check each fact against the date of its act (T244)."""
    today = today or datetime.date.today()
    out = []
    pid = person["id"]
    facts = person.get("facts", [])
    for f in facts:
        date = f.get("date") or {}
        for key in ("value", "end"):
            value = date.get(key)
            if value and not date_exists(value):
                out.append(_finding("date-invalid", pid, [f["id"]], [],
                                    _("{fact}: the date {date} does not exist").format(fact=f["id"], date=value)))
        y = year(f)
        if y is not None and y > today.year and f.get("status") in counted:
            out.append(_finding("date-future", pid, [f["id"]], [y],
                                _("{fact}: the year {year} is in the future").format(fact=f["id"], year=y)))
    born = _pick(facts, BIRTH, counted=counted)
    died = _pick(facts, END, last=True, counted=counted)
    married = _pick(facts, ("marriage",), counted=counted)
    if born and died and died[0] < born[0]:
        out.append(_finding("death-before-birth", pid, [died[1], born[1]], [died[0], born[0]],
                            _("{died_fact} ({died}) comes before {born_fact} ({born}): death before birth")
                            .format(died_fact=died[1], died=died[0], born_fact=born[1], born=born[0])))
    if born and died and died[0] - born[0] > MAX_AGE:
        out.append(_finding("age-over", pid, [died[1], born[1]], [died[0], born[0]],
                            _("{died_fact}: an age at death of {age}, above {max}").format(
                                died_fact=died[1], age=died[0] - born[0], max=MAX_AGE)))
    if born and married and married[0] < born[0] + MIN_PARENT_AGE:
        out.append(_finding("married-young", pid, [married[1], born[1]], [married[0], born[0]],
                            _("{married_fact} ({married}): married before the age of {min} ({born_fact}, {born})")
                            .format(married_fact=married[1], married=married[0], min=MIN_PARENT_AGE,
                                    born_fact=born[1], born=born[0])))
    if died and married and married[0] > died[0]:
        out.append(_finding("married-after-death", pid, [married[1], died[1]], [married[0], died[0]],
                            _("{married_fact} ({married}) comes after {died_fact} ({died})").format(
                                married_fact=married[1], married=married[0], died_fact=died[1], died=died[0])))
    parents = person.get("parents") or {}
    for role in ("father", "mother"):
        parent = by_id.get(parents.get(role) or "")
        if not parent or not born:
            continue
        pf = parent.get("facts", [])
        p_born = _pick(pf, BIRTH, counted=counted)
        p_died = _pick(pf, END, last=True, counted=counted)
        if p_born and born[0] < p_born[0] + MIN_PARENT_AGE:
            out.append(_finding("parent-young", pid, [born[1], p_born[1]], [born[0], p_born[0]],
                                _("{child_fact} ({born}): the {role} was born in {p_born} ({p_fact}), "
                                  "so under {min} at the birth").format(
                                    child_fact=born[1], born=born[0], role=role, p_born=p_born[0],
                                    p_fact=p_born[1], min=MIN_PARENT_AGE)))
        if role == "mother" and p_born and born[0] > p_born[0] + MAX_MOTHER_AGE:
            out.append(_finding("mother-old", pid, [born[1], p_born[1]], [born[0], p_born[0]],
                                _("{child_fact} ({born}): the mother was born in {p_born} ({p_fact}), "
                                  "so over {max} at the birth").format(
                                    child_fact=born[1], born=born[0], p_born=p_born[0], p_fact=p_born[1],
                                    max=MAX_MOTHER_AGE)))
        if p_died:
            limit = p_died[0] + (1 if role == "father" else 0)
            if born[0] > limit:
                out.append(_finding("born-after-death", pid, [born[1], p_died[1]], [born[0], p_died[0]],
                                    _("{child_fact} ({born}) comes after the {role}'s death "
                                      "({p_fact}, {p_died})").format(
                                        child_fact=born[1], born=born[0], role=role, p_fact=p_died[1],
                                        p_died=p_died[0])))
    if sources:
        out += act_findings(person, sources, counted)
    return out


def _fold_act(text):
    from probandia.lang.places import key

    return " ".join(w for w in key(text).split() if w not in ACT_FILLER)


def act_kind(act):
    """The event an act records, from the ``act`` of its source as written (``birth``, ``naissance``, ``Acte de
    baptême``), in the terms of the citation models; an act that records no birth, marriage or death (banns, a
    marriage contract, a will) keeps its own term, and nothing written gives None."""
    if not _acts:
        from probandia import paths
        from probandia.util import yamlio

        names = dict(ACT_ALIASES)
        folder = paths.data("catalogues", "citations")
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.endswith(".yaml"):
                names.update({word: term for term, word in ((yamlio.load(os.path.join(folder, name)) or {})
                                                             .get("terms") or {}).items()})
        for word, term in list(names.items()) + [(term, term) for term in names.values()]:
            _acts[_fold_act(word)] = term
    folded = _fold_act(act or "")
    return _acts.get(folded, folded or None)


def _day(value):
    """(year, month, day) as far as a date gives them; None for what is not a date of the Gregorian form."""
    m = DAY.match(str(value or ""))
    return tuple(int(x) for x in m.groups() if x) if m else None


def _over_a_year(early, late):
    """True when ``late`` is surely more than a year after ``early``, at the precision both give."""
    n = min(len(early), len(late))
    if n == 3:
        return (early[0] + 1, early[1], early[2]) < late
    if n == 2:
        return (late[0] - early[0]) * 12 + late[1] - early[1] > 12
    return late[0] - early[0] > 1


def act_findings(person, sources, counted=COUNTED):
    """T244: a fact dated after the act of its source that records it, an act of its own type, cannot be true:
    an ``error``. Dated more than a year before it, the act is a late registration, a transcription or a
    judgement, which the fact's note explains: a ``warning``. Only an exact date is compared, at the precision
    both dates give."""
    out = []
    for f in person.get("facts") or []:
        src = sources.get(f.get("source") or "") or {}
        date = f.get("date") or {}
        if f.get("status") not in counted or date.get("qualifier") not in (None, "exact") or date.get("end") \
                or act_kind(src.get("act")) not in ACTS_OF.get(f.get("type"), ()):
            continue
        day, act = _day(date.get("value")), _day(src.get("act_date"))
        if not day or not act:
            continue
        n = min(len(day), len(act))
        if day[:n] > act[:n]:
            out.append(_finding("after-its-act", person["id"], [f["id"]], [day[0], act[0]],
                                _("{fact} ({date}) comes after the act that records it: {source}, of {act_date}")
                                .format(fact=f["id"], date=date["value"], source=src["id"],
                                        act_date=src["act_date"])))
        elif _over_a_year(day, act):
            out.append(_finding("late-act", person["id"], [f["id"]], [day[0], act[0]],
                                _("{fact} ({date}): its act, {source}, is of {act_date}, more than a year later; "
                                  "a late registration, a transcription or a judgement? say so in the fact's note")
                                .format(fact=f["id"], date=date["value"], source=src["id"],
                                        act_date=src["act_date"])))
    return out


def check_person(person, by_id, today=None):
    """The messages of one person's findings."""
    return [f["message"] for f in findings(person, by_id, today)]


def selection(persons, touched=None):
    """The persons touched (all when None), their parents and children."""
    by_id = {p["id"]: p for p in persons}
    if touched is None:
        return set(by_id)
    selected = set(touched)
    for p in persons:
        parents = p.get("parents") or {}
        if p["id"] in touched or parents.get("father") in touched or parents.get("mother") in touched:
            selected.add(p["id"])
    return selected


def all_findings(persons, touched=None, today=None, counted=COUNTED, sources=None):
    """The findings of the persons touched (all when None), their parents and children; ``sources``, by id, adds
    the dates of their acts (T244)."""
    by_id = {p["id"]: p for p in persons}
    out = []
    for pid in sorted(selection(persons, touched)):
        if pid in by_id:
            out += findings(by_id[pid], by_id, today, counted, sources)
    return out


def check(persons, touched=None, today=None, sources=None):
    """``P-9: <message>`` for each finding: the reasons ``apply`` gives. A late act that the fact's note explains
    is none (T244)."""
    noted = {f["id"] for p in persons for f in p.get("facts") or [] if f.get("note")}
    return ["P-9: " + f["message"] for f in all_findings(persons, touched, today, sources=sources)
            if not (f["code"] == "late-act" and noted & set(f["facts"]))]
