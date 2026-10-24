"""The planner: ``plan <research> [--question-type <t>] [--focus "<text>"]``.

It aims at the focus of the pass: the ``--focus`` text, otherwise the open
hypothesis last opened by this research or by none (never another research's:
hypotheses are kept for the whole family), with what would settle it, otherwise
the research's question — a research on the ancestors of Louis MARCHAND whose open
lead is the father of Louise PERRIN plans PERRIN at Les Ormes, not MARCHAND
again. The person is looked for in the family's persons, then among its
surnames; the places among its places index, then among the departments,
countries and communes of the INSEE COG the text names (those found nowhere are
listed apart); with no year in the text, the window comes from the person's
birth. It then crosses four axes:
- names: the surname forms (at most 8) and the given-name forms;
- places: the place, its old names (at most 4);
- windows: ± 2 years around an exact year, ± 5 around an "about" year, from a
  fact the question gives to place its person (a birth before a known death:
  the death's year minus 100 to minus 15), the family's period when nothing is
  known; ``--window`` corrects it;
- record types: those of the question type.

It plans the calls of the default routing (``routing.<type>``), then removes,
each with its reason, the calls to an archive whose years miss the window, whose
record types miss the call's or whose places miss the question's
(``out-of-coverage``), the calls for a fact already established
(``known-fact``), the calls a valid negative already answered
(``valid-negative``), and the calls that exceed the free quotas
(``over-quota``). The plan is written to ``work/plan-<pass>.yaml``, unless
``write`` is false: a field agent reads the plan, it does not make it.

The matrix comes first (GPS3-T7): each source type an open question still has
to do gives a ``matrix`` call, before the routing's, aimed at the repository the
place's guide (or the archives' catalogue) names for it; the plan lists in
``matrix`` every hole of the open questions, the gaps to justify included.
"""
import os
import re

from probandia import known as known_mod
from probandia.indexes import FamilyIndexes
from probandia.lang.places import key as fold
from probandia.lang.variants import given_forms, surname_forms
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now

TYPES = ("birth", "marriage", "death", "parents", "children", "residence", "migration",
         "identity", "negative", "general")
TYPE_WORDS = [
    ("negative", r"\b(absence|absent|introuvable|not found|no trace|aucune trace|n'existe pas)\b"),
    ("parents", r"\b(parents?|father|mother|p[eè]re|m[eè]re|eltern|vater|mutter|filiation)\b"),
    ("children", r"\b(children|child|enfants?|kinder|descendants?|fils|filles?)\b"),
    ("marriage", r"\b(marri\w*|mariage|mari[eé]e?s?|wedding|heirat\w*|[eé]pous\w*)\b"),
    ("death", r"\b(death|died|dies?|buried|d[eé]c[eè]s|d[eé]c[eé]d[eé]e?|mort\w*|tod|gestorben|starb|"
              r"verstorben|burial|inhum\w*)\b"),
    ("migration", r"\b(emigr\w*|[eé]migr\w*|immigr\w*|migration|auswander\w*)\b"),
    ("residence", r"\b(lived|habit\w*|r[eé]sid\w*|domicil\w*|wohn\w*|residence)\b"),
    ("identity", r"\b(homonym\w*|same person|m[eê]me personne|identit\w*)\b"),
    ("birth", r"\b(birth|born|naissance|n[eé]e?|geboren|geburt|getauft|bapt\w*)\b"),
]
# The facts a question gives to place its person, and the event it seeks (token-economy C1, C2).
EVENTS = {t: re.compile(p, re.I) for t, p in TYPE_WORDS if t in ("birth", "marriage", "death")}
SOUGHT = {"birth": "birth", "parents": "birth", "marriage": "marriage", "death": "death"}
# years from a given fact to the event sought: the bounds of a life, not a demography
FROM_FACT = {("birth", "death"): (-100, -15), ("birth", "marriage"): (-60, -15),
             ("death", "birth"): (0, 100), ("death", "marriage"): (0, 80),
             ("marriage", "birth"): (15, 60), ("marriage", "death"): (-80, 0)}
YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
AGE = re.compile(r"\b(?:aged|[aâ]g[eé]e?s? de|im alter von)\s+(\d{1,3})\b|\b(\d{1,3})\s+(?:ans|years|jahren?)\b", re.I)
NAMED_PLACE = re.compile(r"\b(?:à|au|aux|en|in|at|near|bei|zu|aus)\s+([A-ZÀ-ÖØ-Þ][\w'’-]*(?:\s+[A-ZÀ-ÖØ-Þ][\w'’-]*)*)"
                         r"(?:\s*\(([^)]+)\))?")
RECORD_TYPES = {
    "birth": ["birth", "baptism"], "marriage": ["marriage"], "death": ["death", "burial"],
    "parents": ["birth", "baptism", "marriage"], "children": ["birth", "baptism"],
    "residence": ["census", "residence"], "migration": ["emigration", "naturalisation", "census"],
    "identity": ["birth", "marriage", "death"], "negative": ["birth", "marriage", "death"],
    "general": [],
}
MAX_NAMES = 8
MAX_PLACES = 4
NAME_QUERIES = 3       # surname forms crossed with the first place, per engine
ARCHIVE_IDS = ("gallica", "matchid", "openarchives", "wikitree", "europeana", "loc", "wayback",
               "bnl", "geonames", "gov", "insee_cog", "iiif")
TOKENS = ("library", "family-index", "coverage", "native")


GIVEN_MARIE = re.compile(r"\b(?:Marie|MARIE)\b")   # T224: the given name, not "marié" ("Victor Marie HUGO")


def _detect(text):
    q = GIVEN_MARIE.sub(" ", text).lower()
    for name, pattern in TYPE_WORDS:
        if re.search(pattern, q):
            return name
    return "general"


def detect_type(question):
    """The type of what the question seeks: the event words of the facts it gives to place
    its person do not count ("Où est né X, mort en 1876 ?" seeks a birth)."""
    text = question
    for f in given_facts(question):
        s, e = f["span"]
        text = text[:s] + " " * (e - s) + text[e:]
    found = _detect(text)
    return found if found != "general" else _detect(question)


def given_facts(text):
    """The dated facts a question gives — "mort le 3 mars 1890 à Coutances (Manche)" —
    as [{type, year, date, qualifier, place, age, span}]: for each year, the event word nearest
    before it in its clause, else after it (German puts the verb last)."""
    from probandia.lang import dates

    out, used = [], set()
    for clause in re.finditer(r"[^,;?!]+", text):
        c, base = clause.group(0), clause.start()
        words = sorted((m.start(), m.end(), t) for t, rx in EVENTS.items() for m in rx.finditer(c))
        for y in YEAR.finditer(c):
            before = [w for w in words if w[1] <= y.start()]
            after = [w for w in words if w[0] >= y.end()]
            w = before[-1] if before else (after[0] if after else None)
            if w is None or w in used:
                continue
            used.add(w)
            lead, date = c[w[1] if before else 0:y.end()].split(), {}
            for i in range(max(0, len(lead) - 5), len(lead)):   # the longest date written up to the year
                try:
                    date = dates.read(" ".join(lead[i:]))
                    break
                except ValueError:
                    continue
            later = [x[0] for x in words if x[0] > w[0]]   # up to the next event word
            region = c[w[0]:later[0] if later else len(c)] if before else c[:w[1]]
            place, age = NAMED_PLACE.search(region), AGE.search(region)
            out.append({"type": w[2], "year": int(y.group(1)), "date": date.get("iso"),
                        "qualifier": date.get("qualifier", "exact"), "place": place.group(1) if place else None,
                        "age": int(age.group(1) or age.group(2)) if age else None,
                        "span": (base + w[0], base + w[1])})
    return out


def focus_of(question, hypotheses, explicit=None):
    """(text, source) the pass aims at: ``argument``, ``hypothesis <id>`` or ``question``."""
    if explicit:
        return explicit, "argument"
    open_ = [h for h in hypotheses if not h.get("closed")
             and any(a.get("status") == "open" for a in h.get("hypotheses") or [])]
    if open_:
        h = sorted(open_, key=lambda x: str(x.get("opened") or ""))[-1]
        text = " ".join(str(x) for x in (h.get("question"), h.get("discriminating")) if x)
        return text, f"hypothesis {h['id']}"
    return question, "question"


def find_indexed_person(text, persons):
    """The person of the family's index whose given name and surname the text
    names (the given name just before the surname first), or None."""
    words = [fold(w) for w in re.findall(r"[\w'’-]+", text)]
    found = []
    for p in persons:
        names = p.get("names") or {}
        given, surname = fold(names.get("given") or ""), fold(names.get("surname") or "")
        if not given or not surname or surname not in words or given.split()[0] not in words:
            continue
        adjacent = any(words[i] == given.split()[0] and words[i + 1] == surname for i in range(len(words) - 1))
        found.append((not adjacent, p))
    found.sort(key=lambda x: x[0])
    return found[0][1] if found else None


NOT_GIVEN = {"quand", "ou", "qui", "quel", "quelle", "comment", "when", "where", "who", "what", "wann", "wo", "wer",
             "le", "la", "les", "de", "du", "des", "the", "von", "der", "die"}


def find_person(question, family):
    """(given name, surname) of the person the question is about."""
    surnames = [family.get("name", "")] + list(family.get("surnames", []))
    folded = fold(question)
    words = re.findall(r"[\w'’-]+", question)
    for s in surnames:
        k = fold(s)
        if not k or f" {k} " not in f" {folded} ":
            continue
        for i, w in enumerate(words):
            if fold(w) == k:
                j = i   # T224: every given name before the surname ("Victor Marie HUGO"), not the last alone
                while j and i - j < 4 and words[j - 1][:1].isupper() and fold(words[j - 1]) not in NOT_GIVEN:
                    j -= 1
                return " ".join(words[j:i]), w
    return "", (family.get("surnames") or [family.get("name", "")])[0]


def find_window(question, family, qtype=None):
    """(from, to, how): around the year of the event sought (``exact`` ± 2, ``about`` ± 5); else
    from a fact the question gives (``anchor``: a birth before a known death runs from the death's
    year minus 100 to minus 15, narrowed by the age at that fact); else around the first year
    written; else the family's period."""
    sought = SOUGHT.get(qtype or detect_type(question))
    facts = given_facts(question) if sought else []
    for f in facts:
        if f["type"] == sought:
            pad = 5 if f["qualifier"] == "about" else 2
            return f["year"] - pad, f["year"] + pad, "about" if pad == 5 else "exact"
    for f in facts:
        pad = 5 if f["qualifier"] == "about" else 0
        if sought == "birth" and f["age"] is not None:
            from probandia.lang.dates import age_range

            born = age_range(f["age"], f["date"] if len(f["date"] or "") == 10 else f"{f['year']}-01-01")
            return int(born["iso"][:4]) - pad, int(born["end"][:4]) + pad, "anchor"
        if (sought, f["type"]) in FROM_FACT:
            lo, hi = FROM_FACT[(sought, f["type"])]
            return f["year"] + lo - pad, f["year"] + hi + pad, "anchor"
    q = question.lower()
    m = re.search(r"\b(about|around|circa|ca\.?|vers|environ|um|gegen)\s+(\d{4})\b", q)
    if m:
        y = int(m.group(2))
        return y - 5, y + 5, "about"
    m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", q)
    if m:
        y = int(m.group(1))
        return y - 2, y + 2, "exact"
    period = family.get("period") or [None, None]
    return period[0], period[1], "family"


def find_places(question, family, places_index, as_of, person=None):
    named = [p for p in family.get("places", []) if fold(p) and fold(p) in fold(question)]
    for p in places_index:     # the places of the family's index the text names
        for f in [p.get("current_name") or ""] + list(p.get("names_as_written", [])):
            if f and fold(f) in fold(question) and f not in named:
                named.append(f)
    for fact in (person or {}).get("facts", []):   # then where the person is known to have been
        written = (fact.get("place") or {}).get("as_written")
        if written and written not in named:
            named.append(written)
    out = []
    for name in named:
        out.append(name)
        for p in places_index:
            forms = [p.get("current_name") or ""] + list(p.get("names_as_written", []))
            if fold(name) in {fold(f) for f in forms if f}:
                out += [f for f in forms if f]
    seen, unique = set(), []
    for p in out:
        if fold(p) not in seen:
            seen.add(fold(p))
            unique.append(p)
    return unique[:MAX_PLACES]


def question_places(text, cog_folder=None):
    """([(name, codes)], [names not found]): the places a question names after à, in, at, bei…, as
    a department or a country (``coverage.places_in``), else as a commune of the INSEE COG; the
    department in brackets chooses among communes of one name, and stands for the place the
    COG does not know ("Le Hamel (Manche)" → FR-50), as a country does ("Vianden
    (Luxembourg)" → LU)."""
    from probandia.archives.coverage import places_in
    from probandia.lang.places import Cog, department_of

    found, unknown, cog = [], [], False
    for m in NAMED_PLACE.finditer(text):
        name, bracket = m.group(1), m.group(2)
        codes = places_in(name)
        deps = {c[3:] for c in places_in(bracket or "") if c.startswith("FR-")}
        if not codes and cog_folder:
            cog = Cog.load(cog_folder) if cog is False else cog
            communes = {department_of(i) for i in (cog.names.get(fold(name), ()) if cog else ())}
            communes = communes & deps if deps else communes
            codes = [f"FR-{communes.pop()}", "FR"] if len(communes) == 1 else ["FR"] if communes else []
        if not codes and deps:
            codes = [f"FR-{d}" for d in sorted(deps)] + ["FR"]
        if not codes:   # "Vianden (Luxembourg)": the country in brackets
            codes = places_in(bracket or "")
        if codes:
            found.append((name, codes))
        else:
            unknown.append(f"{name} ({bracket})" if bracket else name)
    return found, unknown


def _place_name(place):
    return (place.get("names_as_written") or [place.get("current_name") or place["id"]])[0]


def matrix_targets(research, meta, places, catalogue=None, archives=None):
    """The holes of the open questions' matrix: [{question, type, state, places, years,
    repositories, record_types}], in the order of the questions, then of the catalogue."""
    from probandia.proof import matrix, source_types

    catalogue = catalogue or source_types.load()
    coverage = {t["id"]: t["coverage"] for t in catalogue["types"]}
    doc = matrix.build(research, meta=meta, catalogue=catalogue, archives=archives)
    out = []
    for q in doc["questions"]:
        if q["status"] != "open":
            continue
        for row in q["rows"]:
            if row["state"] not in matrix.HOLES:
                continue
            out.append({"question": q["id"], "type": row["type"], "state": row["state"],
                        "places": [_place_name(places[p]) if p in places else p for p in row["places"]],
                        "years": row["years"],
                        "repositories": [r.get("archive") or r["name"] for r in row["repositories"]],
                        "record_types": sorted(matrix.wanted(coverage[row["type"]], q["type"]))})
    return out


def matrix_calls(targets, surname):
    """One call for each source type to do: at its first repository, the surname at its first place."""
    return [{"engine": (t["repositories"] or ["manual"])[0], "kind": "matrix",
             "query": f"{surname} {t['places'][0] if t['places'] else ''}".strip(),
             "record_types": t["record_types"], "window": {"from": t["years"][0], "to": t["years"][1]},
             "units": 0, "matrix": f"{t['question']}.{t['type']}"}
            for t in targets if t["state"] == "todo"]


RECORDS = {t for types in RECORD_TYPES.values() for t in types}


def _outside(cov, window, record_type, codes):
    """Why an archive's coverage misses a call, or None: its years (C2), the record type
    of an archive of records (matchID has deaths only; Gallica's press may tell of a
    birth), the places of the question (C5)."""
    from probandia.archives.coverage import covers

    span, types, places = cov.get("years"), cov.get("types") or [], cov.get("places") or []
    if span and window[0] is not None and window[1] is not None and (window[1] < span[0] or window[0] > span[1]):
        return f"{span[0]}-{span[1]}"
    if record_type and RECORDS & set(types) and record_type not in types:
        return "types " + ",".join(types)
    if codes and places and (not covers(places, codes) or covers(cov.get("absent") or [], codes)):
        return "places " + ",".join(places)
    return None


def _plan_pass(research, meta):
    """The open pass; else the next one."""
    from probandia import events
    from probandia.lifecycle import pass_state

    last, open_ = pass_state(events.read(research.events_path))
    return last if open_ else max(last, int(meta.get("passes") or 0)) + 1


def _planned_reads(ledger, config, environ, kept, usable, reserve):
    """The pages a wave will read: ``reading.per_search`` for each provider search,
    fitted into the free quotas of the readers that draw on an account, in the
    ladder's order (``reading.readers``, then the unblocking readers: T256; Jina
    without a key draws on none)."""
    from probandia.ledger import fit
    from probandia.providers.meter import Meter
    from probandia.reading.ladder import reader_order

    try:
        per = config.get("reading.per_search")
    except KeyError:
        per = 3
    pages = per * sum(1 for c in kept if c["kind"] == "provider")
    if not pages:
        return {}
    meter = Meter(ledger, config, environ)
    readers = [p for p in reader_order(config) + [p for p, e in ledger.catalogue.items() if e.get("unblocker")]
               if p in usable and meter.metered(p)]
    out = {"pages": pages, "estimate": {}}
    if readers:
        alloc = fit(ledger, {readers[0]: pages}, readers, reserve, readers, operation="read")
        out["estimate"] = {p: n * ledger.cost(p, "read") for p, n in alloc.kept.items()}
        if alloc.dropped:
            out["over_quota"] = sum(alloc.dropped.values())
    return out


def _own_hypotheses(project, research, idx):
    """The family's hypotheses this research may aim at: those it opened
    (``hypothesis.opened`` in its events) and those no research opened (imported,
    or older than the log); never another research's."""
    from probandia import events
    from probandia.research import all_researches

    mine, others = set(), set()
    for r in all_researches(project):
        if r.family != research.family:
            continue
        opened = {ref for e in events.read(r.events_path) if e.get("type") == "hypothesis.opened"
                  for ref in e.get("refs") or []}
        (mine if r.id == research.id else others).update(opened)
    # T175: one no research opened (imported from a workshop) only when it is about a person the question names
    asked = {p for q in (research.meta() or {}).get("questions") or [] for p in q.get("persons") or []}
    for p in idx.items("persons") if asked else []:   # and their parents, children and spouses
        kin = set((p.get("parents") or {}).values()) | {s.get("person") for s in p.get("spouses") or []}
        if p["id"] in asked or kin & asked:
            asked = asked | kin | {p["id"]}
    asked.discard(None)

    def about_asked(h):
        refs = [e.get("ref") or "" for e in h.get("evidence") or []]
        return not asked or not refs or any(r.split(".")[0] in asked for r in refs)             or any(p in h.get("id", "") for p in asked)

    return [h for h in idx.items("hypotheses")
            if h.get("id") in mine or (h.get("id") not in others and about_asked(h))]


def _person_window(person):
    """(from, to, how) around the person's birth, or None."""
    for fact in (person or {}).get("facts", []):
        if fact.get("type") in ("birth", "baptism"):
            m = re.search(r"\d{4}", str((fact.get("date") or {}).get("value") or ""))
            if m:
                y = int(m.group(0))
                exact = (fact.get("date") or {}).get("qualifier") == "exact"
                return (y - 2, y + 2, "exact") if exact else (y - 5, y + 5, "about")
    return None


def plan(project, research, config, environ, question_type=None, ledger=None, usable_ids=None,
         now=None, write=True, focus=None, years=None):
    meta = research.meta() or {}
    family = yamlio.load(os.path.join(research.family_folder, "family.yaml")) or {}
    idx = FamilyIndexes(project, research.family)
    asked = meta.get("question", "")
    question, focus_source = focus_of(asked, _own_hypotheses(project, research, idx), focus)
    qtype = question_type or detect_type(question)
    person = find_indexed_person(question, idx.items("persons"))
    asked_person = find_indexed_person(asked, idx.items("persons"))
    # the focus is about the person asked about: the question's window and places hold
    same = person is None or (asked_person or {}).get("id") == person.get("id")
    if person:
        # as the text writes them: the variants of a surname start from its spelling
        written = {fold(w): w for w in re.findall(r"[\w'’-]+", question)}
        given = written.get(fold(person["names"]["given"].split()[0]), person["names"]["given"].split()[0])
        surname = written.get(fold(person["names"]["surname"]), person["names"]["surname"])
    else:
        given, surname = find_person(question, family)
        given = given.split()[0] if given else ""   # the first given name, as for a person of the index
    attested = idx.load("variants").get("surnames", {})
    names = [surname] + [f for f, _k, _d in surname_forms(surname, attested)]
    names = list(dict.fromkeys(names))[:MAX_NAMES]
    givens = [given] + [f for f, _l in given_forms(given)] if given else []
    if same:
        wtext = asked if find_window(question, family, qtype)[2] == "family" else question
        ptext = asked + " " + question
        window = find_window(wtext, family, qtype)
        places = find_places(ptext, family, idx.items("places"), window[0])
    else:
        wtext = ptext = question
        window = find_window(question, family, qtype)
        if window[2] == "family" and _person_window(person):
            window = _person_window(person)
        places = find_places(question, family, idx.items("places"), window[0], person)
    # C3: the places the question names, the family's or not; a name found nowhere is said
    from probandia.lang.places import data_dir

    named, unknown = question_places(ptext, os.path.join(data_dir(environ), "insee"))
    have = {fold(p) for p in places}
    places = (places + [n for n in dict.fromkeys(n for n, _c in named) if fold(n) not in have])[:MAX_PLACES]
    have |= {fold(n) for n, _c in named}
    unknown = [u for u in dict.fromkeys(unknown) if fold(u.split(" (")[0]) not in have]
    codes = list(dict.fromkeys(c for _n, cs in named for c in cs))
    codes = [c for c in codes if not any(d.startswith(c + "-") for d in codes)]   # FR-50, not also FR
    if years:   # plan --window: the user's correction, without rewriting the question
        window = (years[0], years[1], "argument")
    record_types = RECORD_TYPES.get(qtype, [])
    route = config.get(f"routing.{qtype}") if qtype in TYPES else []

    found = known_mod.known(project, research.family, names, places,
                            (window[0], window[1]) if window[0] else None, config)
    person_facts = [f for f in found["facts"] if f["status"] in ("record", "index")
                    and (not given or fold(given) in fold(f["id"].replace("-", " ")))]
    known_types = {f["type"] for f in person_facts if f["status"] == "record"}
    negatives = [n for n in found["negatives"] if n["state"] == "valid"]

    places_by_id = {p["id"]: p for p in idx.items("places")}
    targets = matrix_targets(research, meta, places_by_id)
    calls, removed = matrix_calls(targets, surname), []
    place = places[0] if places else ""
    # PRD S-8: the queries that produced facts for this type of question come first
    from probandia.library import Library, fill

    axes = {"names": names, "given": givens[:4], "places": places,
            "window": {"from": window[0], "to": window[1]}}
    for recipe in Library(project).recipes(qtype)[:5]:
        engine = recipe.get("archive")
        if not engine:
            continue
        calls.append({"engine": engine, "kind": "archive" if engine in ARCHIVE_IDS else "provider",
                      "query": fill(recipe["query_template"], axes), "record_type": None, "units": 0,
                      "recipe": recipe["id"]})
    for engine in route:
        if engine in TOKENS:
            calls.append({"engine": engine, "kind": engine, "query": f"{surname} {place}".strip(),
                          "record_types": record_types, "units": 0})
            continue
        archive = engine in ARCHIVE_IDS
        forms = names[:1] if archive else names[:NAME_QUERIES]
        for form in forms:
            query = f"{form} {place}".strip() if archive else f"\"{form}\" {place}".strip()
            for rtype in (record_types or [None]) if archive else [None]:
                calls.append({"engine": engine, "kind": "archive" if archive else "provider",
                              "query": query, "record_type": rtype, "units": 0})
    from probandia.archives.finder import load_catalogue

    archives = load_catalogue(project)
    kept, seen = [], set()
    for c in calls:
        key = (c["engine"], fold(c["query"]), c.get("record_type"), c.get("matrix"))
        if key in seen:
            continue  # a recipe already asks it
        seen.add(key)
        rt = c.get("record_type")
        if rt and rt in known_types:
            removed.append(dict(c, reason="known-fact",
                                detail=next(f["id"] for f in person_facts if f["type"] == rt)))
            continue
        neg = next((n for n in negatives if n.get("engine") == c["engine"]
                    and fold(n["query"]) == fold(c["query"])), None)
        if neg:
            removed.append(dict(c, reason="valid-negative", detail=neg["id"]))
            continue
        # C2, C5: after this research's own reasons, which name the fact or the negative
        outside = _outside(((archives.get(c["engine"]) or {}).get("coverage") or {}) if c["kind"] == "archive"
                           else {}, window, rt, codes)
        if outside:
            removed.append(dict(c, reason="out-of-coverage", detail=outside))
            continue
        kept.append(c)

    estimate, reads = {}, {}
    if ledger is not None:
        from probandia.ledger import fit
        wanted = {}
        for c in kept:
            if c["kind"] == "provider":
                wanted[c["engine"]] = wanted.get(c["engine"], 0) + 1
        usable = usable_ids if usable_ids is not None else list(wanted)
        reserve = config.get("budget.reserve_percent")
        not_usable = [p for p in wanted if p not in usable]
        alloc = fit(ledger, {p: n for p, n in wanted.items() if p in usable}, route, reserve, usable)
        keep_counts = dict(alloc.kept)
        final = []
        for c in kept:
            if c["kind"] != "provider":
                final.append(c)
                continue
            if c["engine"] in not_usable:
                removed.append(dict(c, reason="unusable", detail="no key, card or content reuse"))
                continue
            target = c["engine"]
            if keep_counts.get(target, 0) <= 0:
                moved = next((to for frm, to, n in alloc.moved if frm == target and keep_counts.get(to, 0) > 0), None)
                if moved is None:
                    removed.append(dict(c, reason="over-quota", detail=target))
                    continue
                c = dict(c, engine=moved, moved_from=target)
                target = moved
            keep_counts[target] -= 1
            c["units"] = ledger.cost(target)
            final.append(c)
        kept = final
        for c in kept:
            if c["kind"] == "provider":
                estimate[c["engine"]] = estimate.get(c["engine"], 0) + c["units"]
        reads = _planned_reads(ledger, config, environ, kept, usable, reserve)

    doc = {"schema": 1, "research": research.id, "pass": _plan_pass(research, meta),
           "created": iso(now or utc_now()), "question": question, "question_type": qtype,
           "focus": {"source": focus_source, "person": (person or {}).get("id")},
           "axes": {"names": names, "given": givens[:4], "places": places, "place_codes": codes,
                    "places_unknown": unknown,
                    "window": {"from": window[0], "to": window[1], "basis": window[2]},
                    "record_types": record_types,
                    "anchors": [{k: v for k, v in f.items() if k != "span"} for f in given_facts(wtext)]},
           "matrix": targets, "calls": kept, "estimate": estimate, "reads": reads, "removed": removed}
    path = os.path.join(research.work, f"plan-{doc['pass']}.yaml")
    if not write:
        return (yamlio.load(path) or doc, path) if os.path.isfile(path) else (doc, None)
    yamlio.dump(path, doc)
    return doc, path

