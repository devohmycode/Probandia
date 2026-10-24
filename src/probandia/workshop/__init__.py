"""The workshop a project lives in (docs/workshop-sync.md).

``workshop.yaml`` (schema workshop-link-1), written by ``import``, links the project
to its workshop: which person, fact and research of Probandia stand for what there,
and the markers the workshop needs that Probandia's records cannot hold. One
adapter exists, ``prototype``: the format of ``commun/personnes.yaml`` (WS-D9).

| Function | What it gives |
|---|---|
| ``load(project)`` | the link, or None when the project has no workshop |
| ``save(project, link)`` | writes it, after checking it against its schema |
| ``root(project, link)`` | the workshop folder |
| ``reports(folder)`` | the reports of ``rapports/``: name and whether it is the report of origin |
| ``last_markers(folder, report, origine)`` | the last volet and chapter of a report's facts |
| ``State(project, link, research)`` | the two bases compared: new, same, divergent, workshop only |
| ``Plan(state, accept)`` | what a push writes, the rules of the workshop checked, nothing written |
| ``push(project, plan, actor)`` | writes it: personnes.yaml, workshop.yaml, ``workshop.pushed`` |
"""
import os
import re

from probandia.importer import link_path
from probandia.util import yamlio

ROMAN = re.compile(r"^[IVXLCDM]+$")
VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
# the keys of a person that hold facts: maps, or lists of maps
FACT_KEYS = ("naissance", "bapteme", "baptême", "mariage", "deces", "décès", "inhumation", "residence",
             "résidence", "profession", "recensement", "militaire", "emigration", "émigration",
             "recherches", "evenements", "événements", "recensements")


def load(project):
    path = link_path(project)
    return yamlio.load(path) if os.path.isfile(path) else None


def save(project, link):
    from probandia.util.schema import validate_document

    validate_document("workshop-link", link, "workshop.yaml")
    yamlio.dump(link_path(project), link)


def root(project, link):
    return os.path.normpath(os.path.join(project, link.get("root") or "."))


def reports(folder):
    """[(name, origine)] of the folders of ``rapports/`` that declare a report."""
    base = os.path.join(folder, "rapports")
    out = []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        path = os.path.join(base, name, "rapport.yaml")
        if os.path.isfile(path):
            declared = yamlio.load(path) or {}
            out.append((name, isinstance(declared, dict) and declared.get("origine") is True))
    return out


def roman_value(text):
    """XIV -> 14; 0 for anything else."""
    if not isinstance(text, str) or not ROMAN.match(text):
        return 0
    total = 0
    for i, ch in enumerate(text):
        v = VALUES[ch]
        total += -v if i + 1 < len(text) and VALUES[text[i + 1]] > v else v
    return total


def _facts(people):
    for p in people.get("personnes") or []:
        if not isinstance(p, dict):
            continue
        for key in FACT_KEYS:
            value = p.get(key)
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict):
                    yield dict({"rapport": p.get("rapport")}, **item) if "rapport" not in item else item
    for u in people.get("unions") or []:
        if isinstance(u, dict):
            yield u


def last_markers(folder, report, origine):
    """(volet, chapitre) of the latest fact of a report — the report of origin owns
    the facts without a ``rapport`` — or (None, None). The default for the new facts
    of a research: a volet is never dated back (WS-D5)."""
    people = yamlio.load(os.path.join(folder, "commun", "personnes.yaml")) or {}
    best = None
    for f in _facts(people):
        owner = f.get("rapport")
        if owner == report or (origine and not owner):
            volet, chapitre = str(f.get("volet") or ""), str(f.get("chapitre") or "")
            rank = (roman_value(volet), roman_value(chapitre))
            if rank[0] and (best is None or rank > best[0]):
                best = (rank, volet, chapitre if rank[1] else None)
    return (best[1], best[2]) if best else (None, None)


# the state of the two bases, and the push (WS4)


def people_path(folder):
    return os.path.join(folder, "commun", "personnes.yaml")


def file_sha(path):
    import hashlib

    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class State:
    """The comparison of the project with its workshop: ``entries`` ([compare.Entry]),
    of one research when ``research`` is given; ``changed``: personnes.yaml changed
    since the last import, push or pull."""

    def __init__(self, project, link, research=None):
        from probandia.workshop.prototype import compare
        from probandia.workshop.prototype.mapping import Context

        self.project, self.link, self.research = project, link, research
        self.ctx = Context(project, link)
        self.path = people_path(self.ctx.folder)
        entries = compare.compare(self.ctx)
        if research:
            entries = [e for e in entries if e.fact and e.fact.get("research") == research]
        self.entries = entries
        self.counts = compare.counts(entries)
        self.changed = file_sha(self.path) != (link.get("synced") or {}).get("sha256")

    def of(self, cls):
        return [e for e in self.entries if e.cls == cls]


STRENGTH = ("hypothese", "index", "acte")


class Plan:
    """What a push writes: ``writer`` (its insertions made, nothing written yet),
    ``pushed`` ([Entry]), ``blocked`` ([(Entry, [(rule, message)])]), ``persons``
    ([pid] added to the workshop), ``links`` (fact id -> its entry for workshop.yaml)."""

    def __init__(self, state, accept=(), today=None):
        from probandia.workshop.prototype import rules
        from probandia.workshop.prototype.compare import DIVERGENT, NEW
        from probandia.workshop.prototype.write import Malformed, Writer

        self.state = state
        ctx = state.ctx
        self.writer = w = Writer(state.path)
        self.pushed, self.blocked, self.persons, self.links = [], [], [], {}
        accept = set(accept)
        chosen = [e for e in state.entries if e.cls == NEW or (e.cls == DIVERGENT and e.id in accept)]
        self.unknown_accept = sorted(accept - {e.id for e in state.entries if e.cls == DIVERGENT})
        # the persons of Probandia the workshop lacks, that a fact to push names
        adding = {}
        for e in chosen:
            for wid in (e.person, e.probandia.get("epoux"), e.probandia.get("epouse")):
                pid = ctx.pid_of_wid(wid) or wid
                if wid and wid not in ctx.wpersons and pid in ctx.by_pid:
                    adding[wid] = pid
        new_facts = {wid: [] for wid in adding}
        for e in chosen:
            blocks = rules.check(e.translation, ctx, set(adding))
            if blocks:
                self.blocked.append((e, blocks))
                continue
            try:
                if e.nature == "refutation":
                    w.add_refutation(e.person, e.key, e.index, e.probandia["volet_refute"])
                elif e.cls == DIVERGENT:
                    merged = dict(e.workshop, **{k: e.probandia[k] for k in ("date", "annee", "lieu", "statut",
                                                                             "source", "image") if k in e.probandia})
                    w.replace_fact(e.person, e.key, e.index, merged)
                    self._link(e, e.index)
                elif e.key == "unions":
                    self._link(e, w.add_union(e.probandia))
                elif e.person in new_facts:
                    new_facts[e.person].append(e)
                    continue
                else:
                    self._link(e, w.add_fact(e.person, e.key, e.probandia))
            except Malformed as exc:
                self.blocked.append((e, [("write", str(exc))]))
                continue
            self.pushed.append(e)
        for wid, pid in adding.items():
            self._person(wid, pid, new_facts[wid])
        if self.pushed:
            w.touch(today)

    def _link(self, e, index):
        t = e.translation
        f = e.probandia
        self.links[e.id] = {"person": e.person, "key": e.key, "index": index, "annee": f.get("annee"),
                            "date_text": f.get("date"), "volet": f.get("volet"), "chapitre": f.get("chapitre"),
                            "rapport": f.get("rapport") if not t.research.get("origine") else None}

    def _person(self, wid, pid, entries):
        ctx = self.state.ctx
        p = ctx.by_pid[pid]
        research = next((e.translation.research for e in entries), None) or next(
            (e.translation.research for e in self.pushed if e.translation.research), {})
        statuses = [e.probandia.get("statut") for e in entries + [e for e in self.pushed if wid in (
            e.probandia.get("epoux"), e.probandia.get("epouse"))]]
        best = max((s for s in statuses if s in STRENGTH), key=STRENGTH.index, default="hypothese")
        person = {"id": wid, "nom": p["names"].get("surname") or "", "prenoms": p["names"].get("given") or "",
                  "sexe": p.get("sex") if p.get("sex") in ("M", "F") else "U", "statut": best}
        for key in ("volet", "chapitre"):
            if research.get(key):
                person[key] = research[key]
        if research.get("rapport") and not research.get("origine"):
            person["rapport"] = research["rapport"]
        for key, parent in (("pere", "father"), ("mere", "mother")):
            other = (p.get("parents") or {}).get(parent)
            if other and ctx.wid(other) in ctx.wpersons:
                person[key] = ctx.wid(other)
        if not person["nom"] or not person["prenoms"]:
            for e in entries:
                self.blocked.append((e, [("links", f"{wid}: a person of the workshop has a nom and prenoms")]))
            return
        facts = []
        for e in entries:
            fact = {k: v for k, v in e.probandia.items() if not (k == "rapport" and v == person.get("rapport"))}
            facts.append((e.key, fact))
            self.pushed.append(e)
        self.writer.add_person(person, facts)
        self.persons.append((pid, wid, person))
        for e in entries:
            self._link(e, 0 if e.key in ("recherches", "evenements") else None)

    def lines(self):
        """[(line number from 1, [lines])] that the push inserts, in file order."""
        out = {}
        for at, new, _late in sorted(self.writer.inserts, key=lambda x: x[2]):
            out.setdefault(at, []).extend(new)
        for at, new in self.writer.replaced.items():
            if isinstance(new, list):
                out.setdefault(at, []).extend(new)
        return sorted((at + 1, lines) for at, lines in out.items())


def push(project, plan, actor, now=None):
    """Writes a Plan: personnes.yaml, then workshop.yaml, then ``workshop.pushed`` in
    each research whose facts went. Raises write.Malformed or write.Changed with the
    file left as it was. Returns the new sha256 of personnes.yaml."""
    from probandia import events
    from probandia.indexes import locked
    from probandia.lifecycle import current_pass
    from probandia.research import Research
    from probandia.util.fs import iso, utc_now

    now = now or utc_now()
    state = plan.state
    link = state.link
    with locked(project, f"family:{state.ctx.family}", actor):   # as apply: one writer of the family at a time
        sha = plan.writer.write()
        for fid, entry in plan.links.items():   # the facts pushed are linked: the next status finds them same
            link.setdefault("facts", {})[fid] = entry
        family = state.ctx.family
        for pid, wid, person in plan.persons:
            link.setdefault("persons", {})[pid] = {"workshop": wid, "generation": None,
                                                   "volet": person.get("volet"), "chapitre": person.get("chapitre")}
            known = link.setdefault("families", {}).setdefault(family, [])
            if wid not in known:
                known.append(wid)
        synced = link.setdefault("synced", {})
        synced.update(sha256=sha, at=iso(now), pushed=int(synced.get("pushed") or 0) + len(plan.pushed))
        save(project, link)
    by_research = {}
    for e in plan.pushed:
        by_research.setdefault(e.fact.get("research"), []).append(e)
    for rid, entries in by_research.items():
        if not rid:
            continue
        r = Research(project, family, rid)
        if not os.path.isfile(r.events_path):
            continue
        payload = {"facts": [e.id for e in entries], "persons": [wid for _p, wid, _x in plan.persons],
                   "blocked": [e.id for e, _ in plan.blocked], "file": "commun/personnes.yaml", "sha256": sha}
        with locked(project, f"research:{rid}", actor):
            events.append(r.events_path, [events.make("workshop.pushed", payload, actor, current_pass(r), now=now)])
    return sha
