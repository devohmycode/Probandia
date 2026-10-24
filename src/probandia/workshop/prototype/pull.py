"""From the workshop to Probandia (WS3-T5, WS-D8): what personnes.yaml gained or had
corrected by hand since the last sync becomes a proposal, which ``apply`` checks
like any other; the indexes are never written here.

- a fact of the workshop that Probandia lacks: a new fact (and its person, when the
  workshop has a person Probandia lacks);
- a date the workshop corrected (its text is no longer the one of the last sync):
  the fact of Probandia is refuted, never deleted, and a new fact takes its place.

Its source is the fact's own sentence, else « personnes.yaml de l'atelier ».
"""
from probandia.importer import DIVERGENCE, FACTS, STATUSES, UNCERTAIN
from probandia.util.ids import is_slug, slugify, ulid
from probandia.workshop.prototype.compare import DIVERGENT, WORKSHOP_ONLY

WORKSHOP_SOURCE = "personnes.yaml de l'atelier"


def _date(raw):
    from probandia.lang.dates import Unrecognized, read

    text = str(raw.get("date") or "").strip()
    if text:
        try:
            d = read(text)
            out = {"value": d["iso"], "qualifier": d["qualifier"], "calendar": d["calendar"], "original": text}
            if d.get("end"):
                out["end"] = d["end"]
            return out
        except Unrecognized:
            pass
    year = raw.get("annee")
    if isinstance(year, int):
        return {"value": f"{year:04d}", "qualifier": "about" if text else "exact", "original": text or None}
    return None


class Pull:
    """The proposal parts of a pull: ``facts``, ``persons``, ``sources``, ``refutations``;
    ``links``: fact id -> its entry for workshop.yaml once applied; ``superseded``: the
    facts of Probandia a correction replaces; ``new_persons``: pid -> workshop id."""

    def __init__(self, state):
        self.state = state
        ctx = state.ctx
        self.facts, self.persons, self.sources, self.refutations = [], [], [], []
        self.links, self.superseded, self.new_persons = {}, {}, {}
        self._citations = {(s.get("citation"), s.get("image")): sid for sid, s in ctx.sources.items()}
        self._ids = {f["id"] for p in ctx.persons for f in p.get("facts") or []}
        for e in state.entries:
            if e.cls == WORKSHOP_ONLY:
                self._new(e)
            elif e.cls == DIVERGENT and e.translation and e.translation.linked and self._corrected(e):
                self._correct(e)

    # where things go

    def _pid(self, wid):
        ctx = self.state.ctx
        pid = ctx.pid_of_wid(wid) or (wid if wid in ctx.by_pid else None)
        if pid:
            return pid
        if wid in self.new_persons.values():
            return next(p for p, w in self.new_persons.items() if w == wid)
        raw = ctx.wpersons.get(wid)
        if raw is None:
            return None
        pid = wid if is_slug(wid) else slugify(f"{raw.get('prenoms', '')} {raw.get('nom', '')}")
        parents = {"father": None, "mother": None}
        for key, parent in (("pere", "father"), ("mere", "mother")):
            if raw.get(key):
                parents[parent] = ctx.pid_of_wid(str(raw[key])) or (raw[key] if raw[key] in ctx.by_pid else None)
        self.persons.append({"id": pid, "names": {"given": str(raw.get("prenoms") or ""),
                                                  "surname": str(raw.get("nom") or "").upper()},
                             "sex": raw.get("sexe") if raw.get("sexe") in ("M", "F") else "U", "living": "auto",
                             "parents": parents, "spouses": [], "facts": []})
        self.new_persons[pid] = wid
        return pid

    def _fact_id(self, pid, ftype):
        base = f"{pid}.{ftype}"
        n, fid = 1, base
        while fid in self._ids:
            n += 1
            fid = f"{base}.{n}"
        self._ids.add(fid)
        return fid

    def _image(self, name):
        """The workshop's scan copied to the family's evidence/, as import does: (its path there) or None."""
        import os
        import shutil

        folder = self.state.ctx.folder
        src = next((p for p in (os.path.join(folder, str(name)), os.path.join(folder, "sources", str(name)))
                    if os.path.isfile(p)), None)
        if src is None:
            return None
        evidence = os.path.join(self.state.project, "families", self.state.ctx.family, "evidence")
        os.makedirs(evidence, exist_ok=True)
        target = os.path.join(evidence, os.path.basename(src))
        if not os.path.exists(target):
            shutil.copy2(src, target)
        return f"evidence/{os.path.basename(src)}"

    def _source(self, raw):
        sentence = str(raw.get("source") or "").strip() or WORKSHOP_SOURCE
        image = self._image(raw["image"]) if raw.get("image") else None
        key = (sentence, image)
        if key not in self._citations:
            sid = f"src-{ulid()}"
            self.sources.append(dict({"id": sid, "citation": sentence}, **({"image": image} if image else {})))
            self._citations[key] = sid
        return self._citations[key]

    def _fact(self, fid, ftype, raw):
        fact = {"id": fid, "type": ftype, "status": STATUSES.get(str(raw.get("statut") or "").lower(), "hypothesis"),
                "date": _date(raw), "place": {"id": None, "as_written": str(raw["lieu"])} if raw.get("lieu") else None,
                "source": self._source(raw), "note": ""}
        note = str(raw.get("note") or "")
        if UNCERTAIN.match(note) and not DIVERGENCE.match(note):
            fact["uncertain_reading"] = UNCERTAIN.sub("", note).strip()
        elif note:
            fact["note"] = note
        return fact

    def _link(self, fid, e, raw):
        from probandia.importer import _roman

        year = raw.get("annee")
        self.links[fid] = {"person": e.person, "key": e.key, "index": e.index,
                           "annee": year if isinstance(year, int) else None,
                           "date_text": str(raw["date"]) if raw.get("date") not in (None, "") else None,
                           "volet": _roman(raw.get("volet")), "chapitre": _roman(raw.get("chapitre")),
                           "rapport": str(raw["rapport"]) if raw.get("rapport") else
                           (self.state.ctx.wpersons.get(e.person) or {}).get("rapport")}

    # the two changes

    def _new(self, e):
        raw = e.workshop
        ftype = "marriage" if e.key == "unions" else FACTS.get(e.key)
        pid = self._pid(str(raw.get("epoux")) if e.key == "unions" else e.person)
        if ftype is None or pid is None:
            return
        fid = self._fact_id(pid, ftype)
        self.facts.append(self._fact(fid, ftype, raw))
        self._link(fid, e, raw)
        if e.key == "unions" and raw.get("epouse"):
            other = self._pid(str(raw["epouse"]))
            if other:
                self._spouses(pid, other, fid)

    def _spouses(self, a, b, fid):
        ctx = self.state.ctx
        for me, them in ((a, b), (b, a)):
            person = next((p for p in self.persons if p["id"] == me), None)
            if person is None:
                known = ctx.by_pid.get(me)
                if known is None:
                    continue
                person = {k: v for k, v in known.items() if k != "facts"}
                person["spouses"] = list(known.get("spouses") or [])
                person["facts"] = []
                self.persons.append(person)
            person["spouses"].append({"person": them, "marriage": fid})

    def _corrected(self, e):
        """True when it is the workshop that changed this date since the last sync."""
        was = (self.state.link.get("facts") or {}).get(e.id) or {}
        return "date" in e.differs and (e.workshop.get("date") or None) != was.get("date_text")

    def _correct(self, e):
        old = e.fact
        pid = old["id"].split(".", 1)[0]
        fid = self._fact_id(pid, old["type"])
        fact = self._fact(fid, old["type"], e.workshop)
        self.facts.append(fact)
        if old.get("status") != "refuted":
            self.refutations.append({"fact": old["id"], "cause": "other",
                                     "reason": f"corrected in the workshop's personnes.yaml: {e.workshop.get('date')}"})
        self._link(fid, e, e.workshop)
        self.superseded[old["id"]] = fid

    def parts(self):
        out = {}
        for key, value in (("persons", self.persons), ("facts", self.facts), ("sources", self.sources),
                           ("refutations", self.refutations)):
            if value:
                out[key] = value
        return out
