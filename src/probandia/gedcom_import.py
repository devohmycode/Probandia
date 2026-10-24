"""``import-gedcom``: a GEDCOM file into the staging area, then match proposals (SPECS § 11.6).

- **Staging.** Everything read goes to ``work/import/<name>.yaml``. Every fact
  becomes a ``hypothesis``: a tree found elsewhere is a lead, never a proof.
- **Matching.** A person of the file matches a person of the family when the
  surname and the first given name sound the same (Soundex2 or Kölner
  Phonetik), and the birth years are within 2 years or a place matches (its
  name as written, or an old name of the family's places).
- **Output.** Proposals, each with its reasons, written in the family's latest
  research: one per matched person (facts added to that person), and one for
  the persons that matched nobody. They are never applied automatically.
"""
import os
import re

from probandia import gedcom
from probandia.lang.phonetic import same_name
from probandia.lang.places import key
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now
from probandia.util.ids import slugify, ulid
from probandia.util.schema import validate_document

TAGS = {"BIRT": "birth", "CHR": "baptism", "BAPM": "baptism", "DEAT": "death", "BURI": "burial",
        "MARR": "marriage", "RESI": "residence", "OCCU": "occupation", "CENS": "census",
        "EMIG": "emigration", "NATU": "naturalisation", "EVEN": "other"}
YEARS = 2


def _name(node):
    raw = node.text("NAME") or ""
    m = re.match(r"^(.*?)/(.*?)/(.*)$", raw)
    given = (node.first("NAME").text("GIVN") if node.first("NAME") else None) or (m.group(1) if m else raw)
    surname = (node.first("NAME").text("SURN") if node.first("NAME") else None) or (m.group(2) if m else "")
    return given.strip(), surname.strip()


def read(path):
    """The persons of a GEDCOM file: ``{xref: {given, surname, sex, events, famc, fams}}``,
    the families and the sources."""
    roots, version = gedcom.read_file(path)
    sources = {n.xref: (n.text("TITL") or n.text("ABBR") or n.xref) for n in roots if n.tag == "SOUR" and n.xref}
    records = _records(roots)
    persons, families = {}, {}
    for n in roots:
        if n.tag == "INDI" and n.xref:
            given, surname = _name(n)
            persons[n.xref] = {"xref": n.xref, "given": given, "surname": surname,
                               "sex": n.text("SEX") if n.text("SEX") in ("M", "F") else "U",
                               "events": _events(n, sources), "note": n.text("NOTE"),
                               "famc": [c.value for c in n.all("FAMC")], "fams": [c.value for c in n.all("FAMS")]}
        elif n.tag == "FAM" and n.xref:
            families[n.xref] = {"husband": n.text("HUSB"), "wife": n.text("WIFE"),
                                "children": [c.value for c in n.all("CHIL")], "events": _events(n, sources)}
    return {"version": version, "persons": persons, "families": families, "sources": sources,
            "records": records}


def _records(roots):
    """The source records with what a citation needs (GPS6-T6): the title, the repository
    (its NAME), the call number, the note (Probandia writes the first note there)."""
    repos = {n.xref: n.text("NAME") for n in roots if n.tag == "REPO" and n.xref}
    out = {}
    for n in roots:
        if n.tag != "SOUR" or not n.xref:
            continue
        repo = n.first("REPO")
        out[n.xref] = {"title": n.text("TITL") or n.text("ABBR"),
                       "repository": repos.get(repo.value) if repo else None,
                       "reference": repo.text("CALN") if repo else None, "note": n.text("NOTE")}
    return out


def _events(node, sources):
    out = []
    for c in node.children:
        if c.tag not in TAGS:
            continue
        cites, pages = [], []
        for s in c.all("SOUR"):
            title = sources.get(s.value, s.value)
            cites.append(title + (f", {s.text('PAGE')}" if s.text("PAGE") else ""))
            pages.append({"source": s.value, "page": s.text("PAGE")})
        out.append({"type": TAGS[c.tag], "date_text": c.text("DATE"), "date": gedcom.parse_date(c.text("DATE")),
                    "place": c.text("PLAC"), "value": c.value or c.text("TYPE") or None, "sources": cites,
                    "citations": pages})
    return out


# matching


def _year(date):
    value = (date or {}).get("value") or ""
    return int(value[:4]) if value[:4].isdigit() else None


def _birth(events):
    for t in ("birth", "baptism"):
        for e in events:
            if e["type"] == t and _year(e["date"]):
                return e
    return None


def match(person, family_persons, places=()):
    """(person id, reasons) of the best match in the family, or (None, [])."""
    old_names = {}
    for p in places:
        for n in [p.get("current_name")] + list(p.get("names_as_written") or []):
            if n:
                old_names.setdefault(p["id"], set()).add(key(n))
    best = (None, [], 0)
    first_given = (person["given"].split() or [""])[0]
    for cand in family_persons:
        names = cand.get("names") or {}
        cand_given = ((names.get("given") or "").split() or [""])[0]
        if not person["surname"] or not same_name(person["surname"], names.get("surname") or ""):
            continue
        if not first_given or not same_name(first_given, cand_given):
            continue
        reasons = [f"surname {person['surname']} sounds as {names.get('surname')}",
                   f"given name {first_given} sounds as {cand_given}"]
        score = 2
        b = _birth(person["events"])
        cb = next((f for f in cand.get("facts", []) if f["type"] in ("birth", "baptism") and _year(f.get("date"))),
                  None)
        if b and cb:
            gap = abs(_year(b["date"]) - _year(cb["date"]))
            if gap > YEARS:
                continue
            reasons.append(f"birth {_year(b['date'])} and {_year(cb['date'])}, {gap} year(s) apart (within ±{YEARS})")
            score += 2
        places_of = {key(e["place"]) for e in person["events"] if e.get("place")}
        cand_places = set()
        for f in cand.get("facts", []):
            pl = f.get("place") or {}
            if pl.get("as_written"):
                cand_places.add(key(pl["as_written"]))
            cand_places |= old_names.get(pl.get("id"), set())
        shared = sorted(places_of & cand_places)
        if shared:
            reasons.append(f"place {shared[0]} in both")
            score += 1
        if score < 3:
            continue  # a name alone is not enough
        if score > best[2]:
            best = (cand["id"], reasons, score)
    return best[0], best[1]


# proposals


def _fact_id(pid, ftype, taken):
    base = f"{pid}.{ftype}"
    if base not in taken:
        taken.add(base)
        return base
    n = 2
    while f"{base}.{n}" in taken:
        n += 1
    taken.add(f"{base}.{n}")
    return f"{base}.{n}"


def _fact(fid, event, origin, source_ids):
    date = event["date"]
    if date:
        date = {k: v for k, v in date.items() if v is not None or k == "end"}
    note = origin + (f"; date as written: {event['date_text']}" if event.get("date_text") and not date else "")
    fact = {"id": fid, "type": event["type"], "status": "hypothesis", "date": date,
            "place": {"id": None, "as_written": event["place"]} if event.get("place") else None,
            "source": source_ids[0] if source_ids else None, "note": note}
    if event["type"] in ("occupation", "other") and event.get("value"):
        fact["value"] = str(event["value"])
    return fact


class Import:
    def __init__(self, project, family, path, actor=None, now=None):
        self.project, self.family, self.path = project, family, path
        self.name = slugify(os.path.splitext(os.path.basename(path))[0])
        self.now = now or utc_now()
        self.actor = actor or {"harness": "cli", "agent": "session"}
        self.data = read(path)

    def staging(self):
        return {"schema": 1, "file": os.path.basename(self.path), "version": self.data["version"],
                "imported": iso(self.now), "persons": list(self.data["persons"].values()),
                "families": list(self.data["families"].values())}

    def proposals(self, family_persons, places=(), research=None, pass_no=1):
        """[(proposal, reasons by person)]: one per matched person, one for the others."""
        taken = {f["id"] for p in family_persons for f in p.get("facts", [])}
        taken_people = {p["id"] for p in family_persons}
        fams = self.data["families"]
        ids, reasons = {}, {}
        for xref, person in self.data["persons"].items():
            pid, why = match(person, family_persons, places)
            if pid:
                ids[xref], reasons[xref] = pid, why
        new = {}
        for xref, person in self.data["persons"].items():
            if xref in ids:
                continue
            b = _birth(person["events"])
            base = slugify(f"{person['given']} {person['surname']} {_year(b['date']) if b else ''}".strip() or xref)
            pid, n = base, 2
            while pid in taken_people:
                pid, n = f"{base}-{n}", n + 1
            taken_people.add(pid)
            ids[xref] = pid
            new[xref] = pid
        sources = {}

        def src(event):
            out = []
            for c, cited in zip(event["sources"], event.get("citations") or [{}] * len(event["sources"])):
                if c not in sources:
                    record = self.data.get("records", {}).get(cited.get("source")) or {}
                    sources[c] = {"id": f"src-{ulid()}", "repository": os.path.basename(self.path),
                                  "citation": f"GEDCOM {os.path.basename(self.path)}: {c}"}
                    if record.get("repository") and record.get("note"):
                        # GPS6-T6: a citation written by Probandia (or with a note) keeps its parts
                        sources[c].update({k: v for k, v in (
                            ("repository", record.get("repository")), ("title", record.get("title")),
                            ("reference", record.get("reference")), ("item", cited.get("page")),
                            ("citation", record["note"])) if v})
                out.append(sources[c]["id"])
            return out

        def facts_of(xref, pid, origin):
            out = []
            person = self.data["persons"][xref]
            for e in person["events"]:
                out.append(_fact(_fact_id(pid, e["type"], taken), e, origin, src(e)))
            for fx in person["fams"]:
                fam = fams.get(fx) or {}
                if xref != fam.get("husband"):
                    continue
                for e in fam.get("events", []):
                    out.append(_fact(_fact_id(pid, e["type"], taken), e, origin, src(e)))
            return out

        out = []
        base_doc = {"schema": 1, "research": research, "pass": pass_no, "author": dict(self.actor)}
        for xref, pid in sorted(ids.items()):
            if xref in new:
                continue
            origin = f"GEDCOM {os.path.basename(self.path)} {xref}: matched because " + "; ".join(reasons[xref])
            doc = dict(base_doc, id=ulid(), facts=facts_of(xref, pid, origin))
            doc["sources"] = [sources[c] for c in sources if sources[c]["id"] in {f["source"] for f in doc["facts"]}]
            out.append((doc, {pid: reasons[xref]}))
        if new:
            persons, facts = [], []
            for xref, pid in sorted(new.items()):
                person = self.data["persons"][xref]
                parents = {"father": None, "mother": None}
                for fx in person["famc"]:
                    fam = fams.get(fx) or {}
                    parents = {"father": ids.get(fam.get("husband")), "mother": ids.get(fam.get("wife"))}
                spouses = []
                for fx in person["fams"]:
                    fam = fams.get(fx) or {}
                    other = fam.get("wife") if fam.get("husband") == xref else fam.get("husband")
                    if other in ids:
                        spouses.append({"person": ids[other]})
                persons.append({"id": pid, "names": {"given": person["given"], "surname": person["surname"].upper()},
                                "sex": person["sex"], "living": "auto", "parents": parents, "spouses": spouses,
                                "facts": []})
                facts += facts_of(xref, pid, f"GEDCOM {os.path.basename(self.path)} {xref}: no match in the family")
            doc = dict(base_doc, id=ulid(), persons=persons, facts=facts)
            doc["sources"] = [sources[c] for c in sources if sources[c]["id"] in {f["source"] for f in facts}]
            out.append((doc, {p["id"]: ["no match in the family"] for p in persons}))
        return out

    def write(self, family_persons, places, research=None):
        """Writes the staging file and, with a research, the proposals. Returns
        (staging path, [(proposal path, reasons)])."""
        folder = os.path.join(self.project, "work", "import")
        os.makedirs(folder, exist_ok=True)
        stage = os.path.join(folder, f"{self.name}.yaml")
        yamlio.dump(stage, self.staging())
        written = []
        if research is not None:
            from probandia.lifecycle import current_pass

            pdir = os.path.join(research.work, "proposals")
            os.makedirs(pdir, exist_ok=True)
            found = self.proposals(family_persons, places, research.id, max(1, current_pass(research)))
            for doc, why in found:   # T120: all checked before any is written, each refusal naming its persons
                validate_document("proposal", doc, f"proposal {doc['id']} ({', '.join(why)})")
            for doc, why in found:
                path = os.path.join(pdir, f"{doc['id']}.yaml")
                yamlio.dump(path, doc)
                written.append((path, why))
        return stage, written
