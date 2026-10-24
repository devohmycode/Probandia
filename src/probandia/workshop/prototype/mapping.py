"""A fact of Probandia as a fact of the workshop (WS3-T1, WS3-T3): the way back of
``importer.py``.

| Probandia | Workshop |
|---|---|
| ``status`` record, index, hypothesis, refuted | ``statut`` acte, index, hypothese, refute |
| ``type`` (birth, death…) | the key of the person (naissance, deces…); ``marriage`` is a union |
| ``date.original``, else the date in French | ``date``, with ``annee`` |
| ``place.as_written``, else the place's name | ``lieu``, as ``commun/lieux.yaml`` writes it |
| the source's citation | ``source`` |
| the source's image | ``image``: the file of ``sources/`` (never copied) |
| ``uncertain_reading`` | ``note: "LECTURE INCERTAINE : …"`` |
| an open hypothesis, a divergent analysis | ``note: "DIVERGENCE NON TRANCHÉE : …"`` (WS-D1) |
| ``workshop.yaml`` | ``volet``, ``chapitre``, ``rapport``; ``refuted_in`` gives ``volet_refute`` |
"""
import os

from probandia.importer import DIVERGENCE, STATUSES, UNCERTAIN, WID
from probandia.util import yamlio

STATUS_BACK = {"record": "acte", "index": "index", "hypothesis": "hypothese", "refuted": "refute"}
KEY_OF = {"birth": "naissance", "baptism": "bapteme", "death": "deces", "burial": "inhumation",
          "residence": "residence", "occupation": "profession", "census": "recensement", "military": "militaire",
          "emigration": "emigration"}
DIVERGENCE_NOTE = "DIVERGENCE NON TRANCHÉE : "
UNCERTAIN_NOTE = "LECTURE INCERTAINE : "


def roman(n):
    if not isinstance(n, int) or n < 1:
        return None
    out = ""
    for value, digits in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
                          (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + digits, n - value
    return out


class Context:
    """What a translation needs: the link, the workshop's file read, and the family's indexes."""

    def __init__(self, project, link, family=None, people=None):
        from probandia import workshop
        from probandia.indexes import FamilyIndexes

        self.project, self.link = project, link
        self.folder = workshop.root(project, link)
        self.family = family or next(iter(link.get("families") or {}), None)
        if people is None:
            path = os.path.join(self.folder, "commun", "personnes.yaml")
            people = yamlio.load(path) if os.path.isfile(path) else {}
        self.people = people or {}
        idx = FamilyIndexes(project, self.family)
        self.persons = idx.items("persons")
        self.by_pid = {p["id"]: p for p in self.persons}
        self.sources = {s["id"]: s for s in idx.items("sources")}
        self.hypotheses = idx.items("hypotheses")
        self.analyses = idx.items("analyses")
        self.places = {p["id"]: p for p in idx.items("places")}
        self.wpersons = {str(p.get("id")): p for p in self.people.get("personnes") or [] if isinstance(p, dict)}
        self.lieux = self._lieux()
        self.reports = {name: origine for name, origine in workshop.reports(self.folder)}

    def _lieux(self):
        path = os.path.join(self.folder, "commun", "lieux.yaml")
        doc = yamlio.load(path) if os.path.isfile(path) else None
        items = doc.get("lieux", doc) if isinstance(doc, dict) else doc
        names = list(items) if isinstance(items, dict) else \
            [x.get("nom") or x.get("lieu") if isinstance(x, dict) else x for x in items or []]
        return {str(n).casefold(): str(n) for n in names if n}

    def wid(self, pid):
        """The workshop id of a person of Probandia: the link's, else its own."""
        known = (self.link.get("persons") or {}).get(pid)
        return known["workshop"] if known else pid

    def pid_of_wid(self, wid):
        return next((pid for pid, p in (self.link.get("persons") or {}).items() if p["workshop"] == wid), None)

    def research_link(self, fact):
        return (self.link.get("researches") or {}).get(fact.get("research") or "") or {}

    def image(self, name):
        """The image as the workshop names it, or (None, the name) when it has no such file."""
        base = os.path.basename(str(name))
        if os.path.isfile(os.path.join(self.folder, "sources", base)):
            return base, None
        # shortcut: one level of folders besides sources/ is looked into; deeper trees when a workshop needs it
        for entry in sorted(os.listdir(self.folder)):
            if os.path.isfile(os.path.join(self.folder, entry, base)) and entry not in ("families", ".probandia"):
                return f"{entry}/{base}", None
        return None, base


def _date(fact, linked):
    from probandia.lang.dates import french

    d = fact.get("date")
    if not d:
        return None, None
    value = str(d.get("value") or "")
    year = int(value[:4]) if value[:4].isdigit() else None
    annee = linked.get("annee") if linked and linked.get("annee") is not None else year
    if d.get("original"):
        return str(d["original"]), annee
    if linked and linked.get("date_text") is None and annee is not None and value == f"{annee:04d}":
        return None, annee   # the workshop gave only its year
    return french(value, d.get("qualifier") or "exact", d.get("end")), annee


def _divergence(ctx, fact):
    """The note of a divergence left open on this fact, or None (WS3-T3)."""
    for h in ctx.hypotheses:
        if h.get("outcome") or h.get("closed"):
            continue
        if any(e.get("ref") == fact["id"] for e in h.get("evidence") or []):
            open_ = [a["statement"] for a in h.get("hypotheses") or [] if a.get("status") == "open"]
            if len(open_) < 2:
                continue
            question = str(h.get("question") or "")
            pos, inside = 0, True   # an imported divergence keeps the workshop's own sentence
            for s in open_:
                at = question.find(s, pos)
                inside, pos = inside and at >= 0, max(pos, at + len(s))
            return DIVERGENCE_NOTE + (question if inside else " ; ".join(open_))
    for a in ctx.analyses:
        if a.get("status") == "divergent" and any(i.get("fact") == fact["id"] for i in a.get("items") or []):
            return DIVERGENCE_NOTE + str(a.get("reason") or "").strip()
    return None


class Translation:
    """A fact of Probandia written for the workshop: ``person`` (its workshop id),
    ``key`` (naissance…, ``unions``), ``index`` (in a list, or None), ``fact`` (the
    workshop's dict), ``missing`` (an image not in the workshop's ``sources/``)."""

    def __init__(self, fid, person, key, index, fact, missing=None, linked=False):
        self.id, self.person, self.key, self.index, self.fact = fid, person, key, index, fact
        self.missing, self.linked = missing, linked
        self.research = {}   # the research's entry in workshop.yaml

    def __repr__(self):
        return f"Translation({self.id!r}, {self.person!r}, {self.key!r}, {self.index!r}, {self.fact!r})"


def translate(ctx, person, fact):
    """The Translation of a fact of a person of Probandia, or None for a type the
    workshop has no key for (naturalisation, other)."""
    linked = (ctx.link.get("facts") or {}).get(fact["id"])
    # T175: a marriage the workshop keeps on its person ("mariage:", beside "conjoint:") stays there, not a union
    key = (linked or {}).get("key") or ("unions" if fact["type"] == "marriage" else KEY_OF.get(fact["type"]))
    is_union = key == "unions"
    if key is None:
        return None
    wid = ctx.wid(person["id"])
    research = ctx.research_link(fact)
    out = {}
    if is_union:
        spouse = next((s["person"] for s in person.get("spouses") or [] if s.get("marriage") == fact["id"]), None)
        other = ctx.wid(spouse) if spouse else None
        husband = person.get("sex") != "F"
        out["epoux"], out["epouse"] = (wid, other) if husband else (other, wid)
        if not other:
            del out["epouse" if husband else "epoux"]
    date, annee = _date(fact, linked)
    if date is not None:
        out["date"] = date
    if annee is not None:
        out["annee"] = annee
    place = fact.get("place") or {}
    lieu = place.get("as_written") or (ctx.places.get(place.get("id")) or {}).get("current_name") or place.get("id")
    if lieu:
        out["lieu"] = ctx.lieux.get(str(lieu).casefold(), str(lieu))
    out["statut"] = STATUS_BACK[fact["status"]]
    volet = (linked or {}).get("volet") or research.get("volet") or roman(fact.get("volet"))
    chapitre = (linked or {}).get("chapitre") or research.get("chapitre")
    if volet:
        out["volet"] = volet
    if chapitre:
        out["chapitre"] = chapitre
    refuted = fact.get("refuted_in")
    if refuted and fact["status"] == "refuted":
        out["volet_refute"] = research.get("volet") or roman(refuted.get("volet")) or volet
    rapport = (linked or {}).get("rapport") if linked else (None if research.get("origine") else research.get("rapport"))
    owner = (ctx.wpersons.get(wid) or {}).get("rapport")
    if rapport and rapport != owner:
        out["rapport"] = rapport
    source = ctx.sources.get(fact.get("source") or "")
    if source and source.get("citation"):
        out["source"] = source["citation"]
    missing = None
    if source and source.get("image"):
        name, missing = ctx.image(source["image"])
        if name:
            out["image"] = name
    note = _divergence(ctx, fact)
    if note is None and fact.get("uncertain_reading"):
        note = UNCERTAIN_NOTE + fact["uncertain_reading"]
    if note is None and fact.get("note"):
        note = fact["note"]
    if note:
        out["note"] = note
    index = (linked or {}).get("index") if linked else None
    t = Translation(fact["id"], wid, key, index, out, missing, bool(linked))
    t.research = research
    return t


def translate_all(ctx):
    """[(person, fact, Translation)] of every fact of the family that has one."""
    out = []
    for p in ctx.persons:
        for f in p.get("facts") or []:
            t = translate(ctx, p, f)
            if t is not None:
                out.append((p, f, t))
    return out


def is_divergence_note(text):
    return bool(DIVERGENCE.match(str(text or "")))


def is_uncertain_note(text):
    return bool(UNCERTAIN.match(str(text or "")))


def known_status(text):
    return str(text or "").strip().lower() in STATUSES


def valid_id(text):
    return bool(WID.match(str(text or "")))
