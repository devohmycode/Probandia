"""Presumed-living persons, and their masking in shared outputs.

A person is presumed living unless ``living: false`` is set, a death or burial
fact exists, or the person was born more than ``privacy.living_years`` ago.
``living: true`` always counts as living.

The birth is the birth or the baptism; without either, the latest birth the
other facts allow (T240): each dated fact of the person, less the youngest age
at which one has it (``MIN_AGE``: a marriage at 14, a military register at 17),
and the birth of each child, less 12 years. A person whom no date places at all
is presumed living: shared outputs mask them until ``living: false`` says
otherwise, as the BCG's rule for the living asks.
"""
import datetime

from probandia.chronology import year

BIRTH = ("birth", "baptism")
END = ("death", "burial")
# T240: the youngest age at which a person has a fact of this type; any other type, from birth on
MIN_AGE = {"marriage": 14, "military": 17, "occupation": 12}
PARENT_MIN_AGE = 12


def latest_birth(person, by_id):
    """The year of birth, or the latest one the person's dated facts and their children's births allow; None
    when no date places the person."""
    facts = [f for f in person.get("facts", []) if f.get("status") != "refuted"]
    years = [y for y in (year(f) for f in facts if f["type"] in BIRTH) if y is not None]
    if years:
        return min(years)
    bounds = [year(f) - MIN_AGE.get(f["type"], 0) for f in facts if year(f) is not None]
    for other in by_id.values():
        parents = other.get("parents") or {}
        if person["id"] in (parents.get("father"), parents.get("mother")):
            bounds += [y - PARENT_MIN_AGE for f in other.get("facts", [])
                       if f["type"] in BIRTH and f.get("status") != "refuted" and (y := year(f)) is not None]
    return min(bounds) if bounds else None


def presumed_living(person, by_id, living_years=100, today=None):
    if person.get("living") is True:
        return True
    if person.get("living") is False:
        return False
    if any(f["type"] in END and f.get("status") != "refuted" for f in person.get("facts", [])):
        return False
    born = latest_birth(person, by_id)
    if born is None:
        return True   # T240: no date places the person: a name alone may be anyone's
    today = today or datetime.date.today()
    return born > today.year - living_years


def living_set(persons, living_years=100, today=None):
    by_id = {p["id"]: p for p in persons}
    return {p["id"] for p in persons if presumed_living(p, by_id, living_years, today)}


def full_names(person):
    names = person.get("names") or {}
    given = (names.get("given") or "").strip()
    out = []
    for surname in {names.get("surname"), names.get("at_birth"), names.get("usual")}:
        if surname and given:
            out.append(f"{given} {surname}")
    return out


def name_forms(persons, living):
    """The comparable forms (``lang.places.key``) of the full names of the persons whose ids ``living`` holds,
    given name first and surname first (T241)."""
    from probandia.lang.places import key

    out = set()
    for p in persons:
        if p["id"] not in living:
            continue
        for name in full_names(p):
            given, _sep, surname = name.partition(" ")
            out |= {key(name), key(f"{surname} {given}")}
    return out - {""}


def names_any(text, forms):
    """True when ``text`` holds one of the name ``forms`` (``name_forms``), ignoring accents and case."""
    from probandia.lang.places import key

    padded = f" {key(text or '')} "
    return any(f" {form} " in padded for form in forms)


def names_in_query(query, persons, living_years=100, today=None):
    """The full names of presumed-living persons that a query holds, in either
    order (given name first or surname first), ignoring accents and case."""
    from probandia.lang.places import key

    text = f" {key(query)} "
    by_id = {x["id"]: x for x in persons}
    found = []
    for p in persons:
        if not presumed_living(p, by_id, living_years, today):
            continue
        for name in full_names(p):
            given, _sep, surname = name.partition(" ")
            for form in (name, f"{surname} {given}"):
                if f" {key(form)} " in text and name not in found:
                    found.append(name)
    return found
