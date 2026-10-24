"""Writes a big invented family for the performance targets of PRD N-8 (version-1.0.0 T148).

    python tools/make_big_family.py <folder> [--persons 500]

Copies ``tests/sample-project`` (30 persons of the invented family ``marchand``) into ``<folder>``, then
adds copies of its persons, each copy with its own identifiers (``<id>-c<n>``, parents and spouses
within the copy), until the family has at least ``--persons`` persons. Sources, places and the
research are those of the sample: the copies' facts cite them and belong to its research, so that
``verify`` checks every one. Everything is fixed: running the script again writes the same bytes.
"""
import argparse
import copy
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import probandia  # noqa: E402,F401
from probandia.util import yamlio  # noqa: E402

SAMPLE = os.path.join(ROOT, "tests", "sample-project")
FAMILY = "marchand"
RESEARCH = "2026-09-01-ancestors-of-louis-marchand"


def renamed(person, ids, n):
    """A copy of ``person`` whose own identifiers, and those of its relatives in ``ids``, end in ``-c<n>``."""
    def new(pid):
        return f"{pid}-c{n}" if pid in ids else pid

    p = copy.deepcopy(person)
    old = p["id"]
    p["id"] = new(old)
    parents = p.get("parents") or {}
    for role in ("father", "mother"):
        if parents.get(role):
            parents[role] = new(parents[role])
    for spouse in p.get("spouses") or []:
        spouse["person"] = new(spouse["person"])
        if spouse.get("marriage"):   # <person>.<fact>: the fact of one of the couple
            head, _dot, tail = spouse["marriage"].partition(".")
            spouse["marriage"] = f"{new(head)}.{tail}"
    for fact in p.get("facts") or []:
        fact["id"] = fact["id"].replace(old, p["id"], 1)
    return p


def make(folder, persons=500):
    """Writes the project; returns (persons, facts)."""
    if os.path.exists(folder):
        shutil.rmtree(folder)
    shutil.copytree(SAMPLE, folder)
    path = os.path.join(folder, "families", FAMILY, "index", "persons.yaml")
    doc = yamlio.load(path)
    base = doc["persons"]
    ids = {p["id"] for p in base}
    out = list(base)
    n = 0
    while len(out) < persons:
        n += 1
        out += [renamed(p, ids, n) for p in base]
    doc["persons"] = out
    yamlio.dump(path, doc)
    return len(out), sum(len(p.get("facts") or []) for p in out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder")
    p.add_argument("--persons", type=int, default=500)
    a = p.parse_args(argv)
    count, facts = make(a.folder, a.persons)
    print(f"{a.folder}: {count} persons, {facts} facts, research {RESEARCH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
