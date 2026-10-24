"""The cases of the public benchmark (TRUST5, optimize.md 6.15).

    python bench/cases.py check bench/public/cases/<case>...
    python bench/cases.py check --all

A case is a folder named after its id:

- ``case.yaml`` (``schemas/bench-case-1.json``): the starting question, the
  family, the expected answers, the sources and their terms of reuse;
- ``project/``: the starting project, the family without the answer (no research);
- ``solution/``: the same project once the research was carried out.

``check`` admits a case only when (TRUST-D9, and TRUST-D3 made precise):

- every person of the solution has a death proven (``record`` or ``index``) more
  than a hundred years ago: nobody alive, nobody who could be;
- every source the solution cites is listed in ``case.yaml`` with its licence or
  terms of reuse, and none is read through an archive that needs a session, is
  read in the browser only, or forbids third parties;
- the solution answers the case: each expected answer is found, nothing is
  falsely promoted;
- each fact that gives an expected answer quotes its passage, and every excerpt of
  the solution is found from the case's own files (its transcriptions and
  ``evidence/pages``), never from ``work/`` or a cache;
- the solution meets every check its expected answers ask for (version-1.0.0 T254:
  ``date``, ``axes``, ``confidence_max``, ``uncertain_reading``, ``distinct``), and each
  ``distinct`` names the ``label`` of another answer.

It prints one line per reason and exits 1 when a case is refused.
"""
import argparse
import datetime
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)

import run as runner  # noqa: E402
from probandia import excerpt as X  # noqa: E402
from probandia.indexes import FamilyIndexes  # noqa: E402
from probandia.research import all_researches  # noqa: E402
from probandia.util import yamlio  # noqa: E402
from probandia.util.schema import validate_document  # noqa: E402

PUBLIC = os.path.join(HERE, "public", "cases")
PROVEN = ("record", "index")
YEARS_DEAD = 100


def load(folder):
    """The case of a folder, validated."""
    path = os.path.join(folder, "case.yaml")
    return validate_document("bench-case", yamlio.load(path), path)


def _research(project, rid):
    return next((r for r in all_researches(project) if r.id == rid), None)


def _year(fact):
    value = ((fact or {}).get("date") or {}).get("value") or ""
    return int(value[:4]) if value[:4].isdigit() else None


def check_persons(persons, today):
    """Every person dead, and proven dead, more than a hundred years ago."""
    out = []
    for p in persons:
        deaths = [_year(f) for f in p.get("facts") or [] if f.get("type") in ("death", "burial")
                  and f.get("status") in PROVEN and _year(f)]
        if not deaths:
            out.append(f"{p['id']}: no death proven: the case may only name persons dead for more than "
                       f"{YEARS_DEAD} years")
        elif max(deaths) > today.year - YEARS_DEAD - 1:
            out.append(f"{p['id']}: died in {max(deaths)}, less than {YEARS_DEAD} years ago")
    return out


def _archive_of(url, catalogue):
    host = urlparse(url or "").hostname or ""
    for archive_id, entry in catalogue.items():
        hosts = (entry.get("access") or {}).get("hosts") or []
        if host and any(host == h or host.endswith("." + h) for h in hosts):
            return archive_id, entry
    return None, None


def check_sources(case, facts, sources, catalogue):
    """Every cited source listed with its terms, none behind a session, the browser or a ban on third parties."""
    out = []
    listed = {s["id"] for s in case["sources"]}
    cited = sorted({f["source"] for f in facts if f.get("status") in PROVEN and f.get("source")})
    for sid in cited:
        if sid not in listed:
            out.append(f"{sid}: cited by the solution, but not in case.yaml with its licence")
        src = sources.get(sid)
        if src is None:
            out.append(f"{sid}: not a source of the solution")
            continue
        archive_id, entry = _archive_of(src.get("url"), catalogue)
        if entry is None:
            continue
        access = entry.get("access") or {}
        if (entry.get("login") or {}).get("required"):
            out.append(f"{sid}: {archive_id} needs a session: a replay could not read it")
        elif access.get("mode") == "browser":
            out.append(f"{sid}: {archive_id} is read in the browser only: a replay could not read it")
        elif access.get("third_party") == "forbidden":
            out.append(f"{sid}: {archive_id} forbids third parties from reading it")
    return out


def versioned_excerpt(project, family, fact, sources):
    """Why an excerpt is not found from the case's own files, never work/ nor a cache: [] when it is."""
    found = fact.get("excerpt")
    source = sources.get(fact.get("source") or "")
    if source is None:
        return ["its source is not known"]
    if found["kind"] == "transcription":
        return X.locate(found, lines=X.transcription_lines(project, family, source))
    kept = X.page_paths(project, family, source["id"])[0]
    return X.locate(found, text=X.read_page(kept) if os.path.isfile(kept) else None)


def check(folder, today=None, catalogue=None):
    """The reasons a case is refused; [] when it is admitted."""
    from probandia.archives.finder import load_catalogue

    today = today or datetime.date.today()
    try:
        case = load(folder)
    except Exception as err:   # noqa: BLE001 — a case that does not load is refused, with why
        return [f"case.yaml: {err}"]
    out = []
    if os.path.basename(os.path.normpath(folder)) != case["id"]:
        out.append(f"the folder must be named {case['id']}")
    project, solution = os.path.join(folder, "project"), os.path.join(folder, "solution")
    for name, path in (("project", os.path.join(project, "probandia.toml")),
                       ("project", os.path.join(project, "families", case["family"], "family.yaml")),
                       ("solution", os.path.join(solution, "probandia.toml"))):
        if not os.path.isfile(path):
            out.append(f"{name}/: no {os.path.relpath(path, folder).replace(os.sep, '/')}")
    if os.path.isdir(os.path.join(project, "families", case["family"], "research")):
        out.append("project/: holds a research: the starting project must not hold the answer")
    research = _research(solution, case["research"]) if os.path.isdir(solution) else None
    if research is None:
        return out + [f"solution/: no research {case['research']}"]
    idx = FamilyIndexes(solution, case["family"])
    persons, sources = idx.items("persons"), {s["id"]: s for s in idx.items("sources")}
    facts = [f for p in persons for f in p.get("facts") or []]
    out += check_persons(persons, today)
    out += check_sources(case, facts, sources, catalogue if catalogue is not None else load_catalogue(solution))
    result = runner.score(case, runner.measure(solution, research))
    if result["findings"] < result["expected"]:
        out.append(f"solution/: {result['findings']} of {result['expected']} expected answers found")
    if result["false_ids"]:
        out.append(f"solution/: falsely promoted: {', '.join(result['false_ids'])}")
    # version-1.0.0 T254: the solution meets the checks its expected answers ask for
    labels = [e["label"] for e in case["expected"] if e.get("label")]
    out += [f"expected: the label {x} is given twice" for x in sorted({x for x in labels if labels.count(x) > 1})]
    out += [f"expected: distinct names {e['distinct']}, which no answer is labelled"
            for e in case["expected"] if e.get("distinct") and e["distinct"] not in labels]
    out += [f"solution/: {c['answer']} fails its check {c['check']}" for c in result["checks"]
            if c["state"] == "failed"]
    by_id = {f["id"]: f for f in facts}
    for exp in case["expected"]:
        fact = by_id.get(exp.get("fact") or "")
        if exp.get("fact") and fact is None:
            out.append(f"{exp['fact']}: not a fact of the solution")
        elif fact is not None and fact.get("status") == "record" and not fact.get("excerpt"):
            out.append(f"{fact['id']}: gives an expected answer but does not quote its passage")
    for f in facts:
        if f.get("excerpt"):
            out += [f"{f['id']}: excerpt: {why}" for why in versioned_excerpt(solution, case["family"], f, sources)]
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="The cases of the public benchmark")
    p.add_argument("action", choices=("check",))
    p.add_argument("cases", nargs="*", help="case folders")
    p.add_argument("--all", action="store_true", help="every case of bench/public/cases")
    a = p.parse_args(argv)
    folders = list(a.cases)
    if a.all and os.path.isdir(PUBLIC):
        folders += [os.path.join(PUBLIC, n) for n in sorted(os.listdir(PUBLIC))
                    if os.path.isfile(os.path.join(PUBLIC, n, "case.yaml"))]
    if not folders:
        print("no case to check")
        return 2
    refused = 0
    for folder in folders:
        reasons = check(folder)
        name = os.path.basename(os.path.normpath(folder))
        print(f"{name}: {'refused' if reasons else 'admitted'}")
        for why in reasons:
            print(f"  - {why}")
        refused += bool(reasons)
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
