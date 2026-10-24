"""The benchmark runner (SPECS § 14.6).

    python bench/run.py [--bench-dir <dir>] [--out <file>] [--json <file>]
    python bench/run.py --case bench/public/cases/<case> [--played <project>]
    python bench/run.py --question <file.yaml> --json <results.json> [--harness <name>]
        [--harness-version <v>] [--model <model>] [--effort <level>]
    python bench/run.py --compare a.json b.json c.json [--out <file>]

The questions stay outside the repository, in ``PROBANDIA_BENCH_DIR`` (or
``--bench-dir``): one YAML file per already-solved question::

    id: marchand-parents
    project: ../projects/marchand        # relative to the question file
    research: 2026-09-01-ancestors-of-louis-marchand   # optional when the project holds one research
    expected:                            # the known answer
      - {person: "Henri MARCHAND", type: birth, year: 1870, place: Bourg-Vert}
      - {person: "Louise PERRIN", type: birth, abstain: true}   # the right answer is "not found"
    run: {tokens: 182000}                # only when the stop hooks recorded none (.probandia/tokens.jsonl)

A public case (TRUST5, ``bench/cases.py``) is scored the same way: ``--case``
scores its ``solution/``, or with ``--played`` the project where a harness ran
the research from its ``project/``; a bench folder may also hold case folders.

An expected answer may also say how its fact must be classified (version-1.0.0 T254): ``date``
(with ``tolerance_days``), ``axes``, ``confidence_max``, ``uncertain_reading`` and ``distinct``
(the ``label`` of another answer, whose person must be another one). Each is a check on the
facts the research proposed and applied, never a judge: passed, failed, or not judged when the
answer was not found. An ``observed`` case informs and blocks nothing.

The runner reads the research's indexes, events, search log and ledger, never a
report, and writes a Markdown report with, per question and in total: findings,
false promotions (per 100 proven facts), facts without a citation, justified
abstentions, the passages the findings quote and that are found again, tokens,
amount paid, native searches and duration. See METRICS.md. With ``--json``, it
also writes ``results.json`` (``schemas/bench-result-1.json``): the same scores with
what each question was played with, and nothing of the persons, keys or paths.
"""
import argparse
import datetime
import glob
import json
import os
import re
import statistics
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import probandia  # noqa: E402
from probandia import events, tokens  # noqa: E402
from probandia.indexes import FamilyIndexes  # noqa: E402
from probandia.lang.places import key  # noqa: E402
from probandia.research import all_researches  # noqa: E402
from probandia.util import yamlio  # noqa: E402

PROVEN = ("record", "index")
YEAR_TOLERANCE = 1
ONCE = ("birth", "baptism", "death", "burial")   # the events a person has once


def _year(fact):
    value = ((fact or {}).get("date") or {}).get("value") or ""
    return int(value[:4]) if value[:4].isdigit() else None


def _name_key(person):
    names = person.get("names") or {}
    return key(f"{names.get('given', '')} {names.get('surname', '')}")


def _same_person(expected, person):
    want = str(expected.get("person") or "")
    return want == person["id"] or key(want) == _name_key(person) or \
        (key(want) and set(key(want).split()) <= set(_name_key(person).split()))


# The expected place is a commune. A place as written is often longer: a hamlet or a parish after it
# ("Besançon, village de Chamars"), the commune last ("village de Chamars, Besançon", "… (Besançon)"),
# a reading in brackets ("Auxons [Les Auxons?]"), the words of the record before it ("né aux Auxons").
PLACE_SEGMENTS = re.compile(r"[,;()\[\]]")
PLACE_TAIL = re.compile(r"\s*\b(?:village|hameau|paroisse|lieu[- ]dit)\b.*$", re.I)
PLACE_LEAD = {"ne", "nee", "baptise", "baptisee", "decede", "decedee", "inhume", "inhumee", "a", "au", "aux", "en",
              "dans", "le", "la", "les", "l"}


def _bare(name):
    """``key`` without the words of the record and the article before the name: "né aux Auxons" is "auxons"."""
    words = key(name).split()
    while words and words[0] in PLACE_LEAD:
        words.pop(0)
    return " ".join(words)


def _place_keys(place, places=None):
    """The comparable forms of a fact's place: as written, each of its segments (between commas, semicolons
    and brackets) cut before a "village de", its id, and the names the family's places.yaml gives that id."""
    written = (place.get("as_written") or "").replace("?", "")
    names = [written, place.get("id") or "", *(places or {}).get(place.get("id"), [])]
    names += [PLACE_TAIL.sub("", s) for s in PLACE_SEGMENTS.split(written)]
    return {_bare(n) for n in names if _bare(n)}


def _hyphened(name):
    """Like ``_bare``, hyphens kept: "Besançon-les-Bains" is "besancon-les-bains", one word."""
    text = unicodedata.normalize("NFKD", str(name))
    words = re.findall(r"[a-z0-9-]+", "".join(c for c in text if not unicodedata.combining(c)).lower())
    while words and words[0].replace("-", " ") in PLACE_LEAD:
        words.pop(0)
    return " ".join(words)


def _place_ok(expected, fact, places=None):
    """The expected place, or one of a list of its names (a commune under two names: Les Auxons, Auxon-Dessus).
    Beyond ``_place_keys``, the commune followed by a space at the head of a segment: "Besançon Doubs"
    is Besançon, "Besançon-les-Bains" is not."""
    want = expected.get("place")
    if not want:
        return True
    place = fact.get("place") or {}
    keys = _place_keys(place, places)
    heads = [_hyphened(s) for s in PLACE_SEGMENTS.split((place.get("as_written") or "").replace("?", ""))]
    for name in want if isinstance(want, list) else [want]:
        if _bare(name) in keys or any(h.startswith(_hyphened(name) + " ") for h in heads if _hyphened(name)):
            return True
    return False


def run_settings(research, log):
    """{mode, model, effort} the research ran with: the ``run`` of each ``pass.started`` (what each pass
    was launched with), else the ``run`` of research.yaml; several values are joined, none is None."""
    runs = [(e.get("payload") or {}).get("run") or {} for e in log if e["type"] == "pass.started"]
    runs = runs or [(research.meta() or {}).get("run") or {}]
    return {k: ", ".join(dict.fromkeys(str(r[k]) for r in runs if r.get(k))) or None
            for k in ("mode", "model", "effort")}


def duplicates(proven):
    """version-1.0.0 T40: the ids of the proven facts that prove again an event of a person the research
    already proved: the same type when a person has it once (birth, baptism, death, burial), else the
    same type, the same word in the id (``parentage`` of ``<person>.parentage.2``) and the same date.
    The first proof of each event is not counted."""
    seen, out = set(), []
    for p, f in proven:
        if f["type"] in ONCE:
            k = (p["id"], f["type"])
        else:
            rest = f["id"][len(p["id"]) + 1:] if f["id"].startswith(p["id"] + ".") else f["type"]
            k = (p["id"], f["type"], rest.split(".")[0], ((f.get("date") or {}).get("value")))
        if k in seen:
            out.append(f["id"])
        seen.add(k)
    return out


def measure(project, research):
    """The metrics of one research against nothing: what it produced."""
    idx = FamilyIndexes(project, research.family)
    persons = idx.items("persons")
    sources = {s["id"] for s in idx.items("sources")}
    log = events.read(research.events_path)
    facts = [(p, f) for p in persons for f in p.get("facts", []) if f.get("research") == research.id]
    proven = [(p, f) for p, f in facts if f.get("status") in PROVEN]
    revised = {(e.get("payload") or {}).get("fact") for e in log if e["type"] in ("fact.revised", "fact.retracted")}
    searches = [s for s in idx.items("searches") if s.get("research") == research.id]
    ledger = os.path.join(project, ".probandia", "ledger.jsonl")
    paid = 0.0
    if os.path.isfile(ledger):
        with open(ledger, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("research") == research.id:
                    paid += float(e.get("paid") or 0)
    ended = [e for e in log if e["type"] == "pass.ended"]
    # TRUST5-T4: the state of each proven fact's excerpt, found again or not
    from probandia import excerpt

    cited = {s["id"]: s for s in idx.items("sources")}
    quoted = {f["id"]: excerpt.verdict(project, research.family, f, cited, research)[0]
              for _p, f in proven if f.get("excerpt")}
    places = {p["id"]: [*(p.get("names_as_written") or []), p.get("current_name") or ""]
              for p in idx.items("places") if p.get("id")}
    return {"quoted": quoted, "persons": persons, "facts": facts, "proven": proven, "revised": revised,
            "places": places,
            "uncited": [f["id"] for _p, f in proven if f.get("source") not in sources],
            # P-2, V-2: an online tree never proves a fact; finding the right date there is not reading the act
            "on_tree": [f["id"] for _p, f in proven if (cited.get(f.get("source")) or {}).get("type") == "online-tree"],
            "duplicates": duplicates(proven),
            "native": sum(1 for s in searches if s.get("kind") == "native"), "paid": paid,
            "duration": sum(int((e.get("payload") or {}).get("duration_s") or 0) for e in ended),
            "passes": len(ended), "tokens": tokens.kinds(project, research.id),
            "by_model": tokens.by_model(project, research.id), "run": run_settings(research, log),
            "main": next(iter(tokens.by_model(project, research.id, role="session")), None),
            "project": project, "research": research}


def _matches(exp, m):
    return [(p, f) for p, f in m["proven"] if f["type"] == exp.get("type") and _same_person(exp, p)]


def _good(exp, m):
    """The (person, fact) pairs that give an expected answer: same person and type, the year within 1, the place."""
    return [(p, f) for p, f in _matches(exp, m)
            if (_year(f) is None or exp.get("year") is None or abs(_year(f) - exp["year"]) <= YEAR_TOLERANCE)
            and _place_ok(exp, f, m.get("places"))]


def score(question, m):
    expected = question.get("expected") or []
    found, abstain_ok, abstain_n, false, quoted = 0, 0, 0, [], 0
    wanted = [e for e in expected if not e.get("abstain")]
    # T254: the fact of a homonym that gives another expected answer contradicts nothing
    answers = {f["id"] for e in wanted for _p, f in _good(e, m)}
    for exp in expected:
        matches = _matches(exp, m)
        if exp.get("abstain"):
            abstain_n += 1
            if not matches:
                abstain_ok += 1
            else:
                false += [f["id"] for _p, f in matches]  # a proof where none can exist
            continue
        good = [f for _p, f in _good(exp, m)]
        if good:
            found += 1
            quoted += any(m.get("quoted", {}).get(f["id"]) == "ok" for f in good)
        false += [f["id"] for _p, f in matches if f not in good and f["id"] not in answers]
    false += [f["id"] for _p, f in m["proven"] if f["id"] in m["revised"] and f["id"] not in false]
    false += [i for i in m.get("on_tree", ()) if i not in false]
    n_proven = len(m["proven"]) or 1
    trap = checks(question, m)
    return {"id": question.get("id"), "findings": found, "expected": len(wanted), "quoted": quoted,
            "checks": trap, "observed": bool(question.get("observed")),
            "false_promotions": round(100.0 * len(false) / n_proven, 1), "false_ids": false,
            "uncited": len(m["uncited"]), "abstentions": abstain_ok, "abstain_expected": abstain_n,
            # weighted by price (input-equivalent); run.tokens only when the hooks recorded nothing
            "tokens": m["tokens"]["weighted"] if m["tokens"] else (question.get("run") or {}).get("tokens"),
            "token_kinds": m["tokens"], "by_model": m["by_model"], "run": m["run"], "main": m["main"],
            "paid": m["paid"], "native": m["native"],
            "duration": m["duration"], "passes": m["passes"], "facts": len(m["facts"]),
            "proven": len(m["proven"]), "duplicate_ids": m["duplicates"]}


CHECKS = ("date", "axes", "confidence_max", "uncertain_reading", "distinct")


def _date_ok(exp, fact):
    """The fact's date is the expected one: the same text, or both full dates within ``tolerance_days``."""
    want = str(exp["date"])
    have = str(((fact.get("date") or {}).get("value")) or "")
    if have == want:
        return True
    try:
        a, b = datetime.date.fromisoformat(want), datetime.date.fromisoformat(have)
    except ValueError:
        return False
    return abs((a - b).days) <= int(exp.get("tolerance_days") or 0)


def conclusions(project, research):
    """{fact id: [the confidence of each answered question that concludes on it]} (TRUST3), as the
    report shows it."""
    from probandia.proof import standard

    meta = research.meta() or {}
    docs = FamilyIndexes(project, research.family).load_all()
    facts = {f["id"]: f for p in docs["persons"].get("persons", []) for f in p.get("facts") or []}
    analyses = (docs.get("analyses") or {}).get("analyses") or []
    raw = {q["id"]: q for q in meta.get("questions") or []}
    out = {}
    for q in standard.of_research(project, research, meta, docs=docs):
        if q.get("confidence") and q["question"] in raw:
            for fid in standard.question_facts(raw[q["question"]], facts, analyses, research.id):
                out.setdefault(fid, []).append(q["confidence"]["name"])
    return out


def checks(question, m):
    """version-1.0.0 T254: each check an expected answer asks for, on the facts that give it:
    [{answer, check, state}], state ``passed``, ``failed``, or ``unjudged`` when the answer was not found."""
    from probandia.proof.confidence import LEVELS

    expected = [e for e in question.get("expected") or [] if not e.get("abstain")]
    labels = {e["label"]: e for e in expected if e.get("label")}
    out, confidence = [], None
    for n, exp in enumerate(expected, 1):
        good = _good(exp, m)
        for check in (c for c in CHECKS if c in exp):
            if check == "distinct":
                other = _good(labels[exp["distinct"]], m) if exp["distinct"] in labels else []
                state = None if not (good and other) else \
                    not ({p["id"] for p, _f in good} & {p["id"] for p, _f in other})
            elif not good:
                state = None
            elif check == "date":
                state = any(_date_ok(exp, f) for _p, f in good)
            elif check == "axes":
                state = any(all((f.get("evidence") or {}).get(k) == v for k, v in exp["axes"].items())
                            for _p, f in good)
            elif check == "uncertain_reading":
                state = any(bool(f.get("uncertain_reading")) == exp["uncertain_reading"] for _p, f in good)
            else:   # confidence_max: no question answered on it may claim more
                if confidence is None:
                    confidence = conclusions(m["project"], m["research"]) if m.get("research") else {}
                ceiling = LEVELS.index(exp["confidence_max"])
                state = all(LEVELS.index(c) <= ceiling for _p, f in good for c in confidence.get(f["id"], []))
            out.append({"answer": exp.get("label") or f"#{n}", "check": check,
                        "state": "unjudged" if state is None else "passed" if state else "failed"})
    return out


def load_case(folder, played=None):
    """A public case (``case.yaml``, TRUST5) as a question: its solution, or the project ``played``."""
    from probandia.util.schema import validate_document

    path = os.path.join(folder, "case.yaml")
    q = validate_document("bench-case", yamlio.load(path), path)
    q["_dir"] = folder
    q["project"] = os.path.abspath(played) if played else "solution"
    return q


def load_question(path):
    """A question file; its id defaults to the file's name."""
    q = yamlio.load(path) or {}
    q.setdefault("id", os.path.splitext(os.path.basename(path))[0])
    q["_dir"] = os.path.dirname(os.path.abspath(path))
    return q


def load_questions(bench_dir):
    out = [load_question(path) for path in sorted(glob.glob(os.path.join(bench_dir, "*.yaml")))]
    for path in sorted(glob.glob(os.path.join(bench_dir, "*", "case.yaml"))):   # public cases (TRUST5)
        out.append(load_case(os.path.dirname(path)))
    return out


class Usage(Exception):
    """A question the runner cannot score as written: exit code 2."""


def run_question(q):
    project = os.path.normpath(os.path.join(q["_dir"], q["project"]))
    rid = q.get("research")
    found = all_researches(project)
    if not rid:   # version-1.0.0 T39: the only research of the project
        if len(found) != 1:
            raise Usage(f"{q.get('id')}: {len(found)} researches in {project}; name one with research:")
        return score(q, measure(project, found[0]))
    research = next((r for r in found if r.id == rid), None)
    if research is None:
        raise SystemExit(f"{q.get('id')}: no research {rid} in {project}")
    return score(q, measure(project, research))


def _kinds_doc(t):
    return {k: int(t.get(k) or 0) for k in tokens.FIELDS} | {"weighted": int(t["weighted"])}


def result_document(results, version, today, given=None):
    """version-1.0.0 T39: ``results.json`` (``schemas/bench-result-1.json``). The harness, model and
    effort are ``given`` (the options), else read from the research: the harness and model of its main
    thread's tokens (role ``session``, else the heaviest pair), the model and effort of its run. No fact
    id, research id or path: they carry the names of persons and of the user's folders."""
    given = given or {}
    cases = []
    for r in results:
        run = r.get("run") or {}
        main = r.get("main") or next(iter(r.get("by_model") or {}), None) or (None, None)
        kinds = r.get("token_kinds")
        trap = r.get("checks") or []
        extra = {"checks": len(trap), "checks_judged": sum(c["state"] != "unjudged" for c in trap),
                 "checks_passed": sum(c["state"] == "passed" for c in trap)} if trap else {}
        cases.append({
            "id": str(r["id"]),
            **({"observed": True} if r.get("observed") else {}),
            "harness": {"name": given.get("harness") or main[0], "version": given.get("harness_version")},
            "model": given.get("model") or run.get("model") or main[1],
            "effort": given.get("effort") or run.get("effort"),
            "mode": run.get("mode"),
            "duration_s": int(r["duration"]), "passes": int(r["passes"]),
            "metrics": {"findings": r["findings"], "expected": r["expected"],
                        "false_promotions": float(r["false_promotions"]), "false_count": len(r["false_ids"]),
                        "uncited": r["uncited"], "abstentions": r["abstentions"],
                        "abstain_expected": r["abstain_expected"], "quoted": int(r["quoted"]),
                        "facts": r["facts"], "proven": r["proven"], "duplicates": len(r["duplicate_ids"]),
                        "native": r["native"],
                        "paid": float(r["paid"]), **extra},
            "tokens": None if r["tokens"] is None else {
                "weighted": int(r["tokens"]), "kinds": _kinds_doc(kinds) if kinds else None},
            "by_model": [{"harness": h, "model": m, "tokens": _kinds_doc(t)}
                         for (h, m), t in (r.get("by_model") or {}).items()]})
    return {"schema": 1, "probandia": version, "date": today, "cases": cases}


def _fmt_duration(s):
    return str(datetime.timedelta(seconds=int(s)))


def _kinds(results):
    rows = [r["token_kinds"] for r in results if r.get("token_kinds")]
    if not rows:
        return "—"
    return ", ".join(f"{k} {sum(x[k] for x in rows):,}" for k in tokens.FIELDS)


def _by_model(results):
    """version-1.0.0 T38: the tokens of each question per (harness, model) pair, with the research's
    mode and effort (the run of its passes)."""
    rows = [(r, h, m, t) for r in results for (h, m), t in (r.get("by_model") or {}).items()]
    if not rows:
        return []
    out = ["## Tokens by harness and model", "",
           "| Question | Harness | Model | Mode | Effort | Input | Output | Cache read | Cache written | "
           "of which 5 min | Weighted |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r, h, m, t in rows:
        run = r.get("run") or {}
        out.append(f"| {r['id']} | {h or '?'} | {m or '?'} | {run.get('mode') or '—'} | {run.get('effort') or '—'} | "
                   f"{t['input']} | {t['output']} | {t['cache_read']} | {t['cache_write']} | {t['cache_write_5m']} | "
                   f"{t['weighted']} |")
    return out + [""]


def _checks(results):
    """version-1.0.0 T254: the checks of the cases that ask for some, and the ones that failed; an
    observed case says so."""
    rows = [r for r in results if r.get("checks")]
    if not rows:
        return []
    out = ["## Checks of the expected answers", "",
           "| Question | Passed | Judged | Asked | Failed |", "|---|---|---|---|---|"]
    for r in rows:
        trap = r["checks"]
        failed = ", ".join(f"{c['answer']} {c['check']}" for c in trap if c["state"] == "failed") or "—"
        out.append(f"| {r['id']}{' (observed)' if r.get('observed') else ''} | "
                   f"{sum(c['state'] == 'passed' for c in trap)} | {sum(c['state'] != 'unjudged' for c in trap)} | "
                   f"{len(trap)} | {failed} |")
    return out + [""]


def report(results, version, today):
    tot = {k: sum((r.get(k) or 0) for r in results) for k in
           ("findings", "expected", "uncited", "abstentions", "abstain_expected", "paid", "native", "duration",
            "facts", "quoted")}
    tokens = [r["tokens"] for r in results if r["tokens"] is not None]
    lines = [f"# Benchmark — Probandia {version}", "", f"- Date: {today}", f"- Questions: {len(results)}", "",
             "| Question | Findings | False promotions /100 | Uncited | Abstentions | Tokens (weighted) | Paid | Native | Duration |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {r['findings']}/{r['expected']} | {r['false_promotions']} | {r['uncited']} | "
                     f"{r['abstentions']}/{r['abstain_expected']} | {r['tokens'] if r['tokens'] is not None else '—'} | "
                     f"{r['paid']:.2f} | {r['native']} | {_fmt_duration(r['duration'])} |")
    falses = sum(len(r["false_ids"]) for r in results)
    proven = sum(r["proven"] for r in results)
    lines += ["", "## Totals", "",
              f"- findings: {tot['findings']}/{tot['expected']}",
              f"- false promotions: {falses} ({round(100.0 * falses / proven, 1) if proven else 0.0} per 100 proven facts)",
              f"- facts without a citation: {tot['uncited']}",
              f"- duplicates (an event of a person proven again): {sum(len(r['duplicate_ids']) for r in results)}",
              f"- justified abstentions: {tot['abstentions']}/{tot['abstain_expected']}",
              f"- findings quoting their passage, found again: {tot['quoted']}/{tot['findings']}",
              f"- tokens: {str(sum(tokens)) + ', weighted by price (input-equivalent)' if tokens else '— (not reported by the harness)'}",
              f"- tokens by kind: {_kinds(results)}",
              f"- amount paid: {tot['paid']:.2f}",
              f"- native searches: {tot['native']}",
              f"- duration: {_fmt_duration(tot['duration'])}", ""]
    trap = [c for r in results for c in r.get("checks") or []]
    if trap:   # T254
        lines.insert(-1, f"- checks of the expected answers: {sum(c['state'] == 'passed' for c in trap)} passed, "
                         f"{sum(c['state'] != 'unjudged' for c in trap)} judged, {len(trap)} asked")
    lines += _by_model(results)
    lines += _checks(results)
    for r in results:
        if r["false_ids"]:
            lines.append(f"- {r['id']}: false promotions {', '.join(r['false_ids'])}")
        if r["duplicate_ids"]:
            lines.append(f"- {r['id']}: duplicates {', '.join(r['duplicate_ids'])}")
    return "\n".join(lines).rstrip() + "\n"


# version-1.0.0 T41: what --compare puts side by side, per case and per (harness, model, effort)
COMPARED = (("tokens (weighted)", lambda c: (c.get("tokens") or {}).get("weighted")),
            ("findings", lambda c: c["metrics"]["findings"]),
            ("false promotions /100", lambda c: c["metrics"]["false_promotions"]),
            ("facts without a citation", lambda c: c["metrics"]["uncited"]),
            ("duplicates", lambda c: c["metrics"].get("duplicates")),
            ("passages found again", lambda c: c["metrics"]["quoted"]),
            ("amount paid", lambda c: c["metrics"]["paid"]),
            ("duration (s)", lambda c: c["duration_s"]),
            ("checks passed", lambda c: c["metrics"].get("checks_passed")))
OPTIONAL = {"checks passed"}   # T254: a row only for the cases that ask for checks
MIN_RUNS = 3


def verdict(reference, values):
    """The rule of the session bench (version-1.0.0 T33): with at least 3 runs on each side, ``lower``
    or ``higher`` only when the min-max ranges do not overlap (3 runs against 3: an exact permutation
    test, p = 1/20), else ``inconclusive``; under 3 runs, ``too few runs``."""
    ref, got = [v for v in reference if v is not None], [v for v in values if v is not None]
    if len(ref) < MIN_RUNS or len(got) < MIN_RUNS:
        return "too few runs"
    if max(got) < min(ref):
        return "lower"
    if min(got) > max(ref):
        return "higher"
    return "inconclusive"


def _num(v):
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _spread(values):
    """``median [min–max]`` of the runs that have a value."""
    got = [v for v in values if v is not None]
    if not got:
        return "—"
    return f"{_num(statistics.median(got))} [{_num(min(got))}–{_num(max(got))}]"


def compare(docs):
    """A Markdown table per case: one column per (harness, model, effort), in the order met, each run
    of the same column a repetition; every column after the first gets the verdict against the first."""
    cases = {}
    for doc in docs:
        for c in doc["cases"]:
            column = ((c.get("harness") or {}).get("name"), c.get("model"), c.get("effort"))
            cases.setdefault(c["id"], {}).setdefault(column, []).append(c)
    lines = ["# Benchmark comparison", "", f"- Results: {len(docs)}",
             "- Each cell: the median of the runs [min–max]; each column after the first: its verdict against "
             f"the first (at least {MIN_RUNS} runs a side, ranges apart; see bench/METRICS.md)", ""]
    for case, columns in cases.items():
        names = list(columns)
        heads = [f"{h or '?'} / {m or '?'} / {e or '—'} ({len(columns[(h, m, e)])} "
                 f"run{'s' if len(columns[(h, m, e)]) > 1 else ''})" for h, m, e in names]
        observed = any(c.get("observed") for runs in columns.values() for c in runs)
        lines += [f"## {case}{' (observed)' if observed else ''}", "", "| Metric | " + " | ".join(heads) + " |",
                  "|---" * (len(names) + 1) + "|"]
        for label, get in COMPARED:
            if label in OPTIONAL and all(get(c) is None for runs in columns.values() for c in runs):
                continue
            ref = [get(c) for c in columns[names[0]]]
            cells = [_spread(ref)]
            for name in names[1:]:
                values = [get(c) for c in columns[name]]
                cells.append(f"{_spread(values)} {verdict(ref, values)}")
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def compare_main(paths, out=None):
    from probandia.errors import SchemaError
    from probandia.util.schema import validate_document

    docs = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                docs.append(validate_document("bench-result", json.load(fh), path))
        except (OSError, ValueError, SchemaError) as e:
            print(f"{path}: {e}")
            return 2
    text = compare(docs)
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    print(text)
    if out:
        print(f"written: {out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Probandia benchmark runner")
    p.add_argument("--bench-dir", default=os.environ.get("PROBANDIA_BENCH_DIR"))
    p.add_argument("--out", help="the report file (default: <bench dir>/report-<version>-<date>.md)")
    p.add_argument("--case", action="append", default=[], help="a public case folder (TRUST5); may repeat")
    p.add_argument("--played", help="with one --case: the project where the research was run from its project/")
    p.add_argument("--question", action="append", default=[],
                   help="a question file, outside any bench folder; may repeat")
    p.add_argument("--json", help="also write the scores as results.json (schemas/bench-result-1.json)")
    p.add_argument("--harness", help="the harness the research was played with, when its tokens do not say")
    p.add_argument("--harness-version", help="the version of that harness")
    p.add_argument("--model", help="the model the research was played with")
    p.add_argument("--effort", help="the effort the research was played with")
    p.add_argument("--compare", nargs="+", metavar="RESULTS", help="results.json files to put side by side")
    a = p.parse_args(argv)
    if a.compare:
        return compare_main(a.compare, a.out)
    if a.question:
        questions = [load_question(q) for q in a.question]
        where = os.path.dirname(os.path.abspath(a.question[0]))
    elif a.case:
        if a.played and len(a.case) != 1:
            print("--played goes with one --case")
            return 2
        questions = [load_case(c, a.played) for c in a.case]
        where = a.case[0] if len(a.case) == 1 else os.getcwd()
    elif not a.bench_dir or not os.path.isdir(a.bench_dir):
        print("set PROBANDIA_BENCH_DIR, or pass --bench-dir: the questions stay outside the repository")
        return 2
    else:
        questions, where = load_questions(a.bench_dir), a.bench_dir
    try:
        results = [run_question(q) for q in questions]
    except Usage as e:
        print(e)
        return 2
    today = datetime.date.today().isoformat()
    text = report(results, probandia.__version__, today)
    out = a.out or os.path.join(where, f"report-{probandia.__version__}-{today}.md")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(text)
    print(f"written: {out}")
    if a.json:
        doc = result_document(results, probandia.__version__, today,
                              {"harness": a.harness, "harness_version": a.harness_version, "model": a.model,
                               "effort": a.effort})
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"written: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
