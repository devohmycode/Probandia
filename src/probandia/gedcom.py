"""GEDCOM: export (7.0 as GEDZIP, and 5.5.1) and a reader for import.

**Export** (SPECS § 11.4, § 11.5). Persons become ``INDI``, couples ``FAM``,
sources ``SOUR`` records cited with ``PAGE`` and ``QUAY``; a fact's status is
``QUAY`` 3, 2 or 1 plus ``_STATUS``, its evidence axes ``_EVID``. A child's ``FAMC``
carries ``PEDI BIRTH`` when a birth or baptism act founds the link, and, in 7.0,
``STAT`` from that fact's status (T250). Hypotheses and
negatives become extension records ``_HYPO`` and ``_NEGA`` (7.0) or ``NOTE``
records (5.5.1). Refuted facts are left out unless asked for. A presumed-living
person is masked (``NAME Living //``, no events) or excluded; nothing else names
them either (T241): a source that only their facts cite is left out, a source
whose citation names them keeps only its repository and collection, and a
hypothesis or a negative search that names them is left out.

**Reading.** One parser for 5.5.1 and 7: levels, cross-references, ``CONC`` and
``CONT``, and the character sets UTF-8 (with or without BOM), UTF-16, ANSEL and
ANSI (Windows-1252).
"""
import io
import os
import re
import unicodedata
import urllib.parse
import zipfile

from probandia import SITE, __version__, cite
from probandia.images import views
from probandia.lang import calendars as cal
from probandia.report.living import living_set, name_forms, names_any

SCHEMA = {"_STATUS": f"{SITE}/gedcom/v1/status",
          "_EVID": f"{SITE}/gedcom/v1/evidence",
          "_HYPO": f"{SITE}/gedcom/v1/hypothesis",
          "_NEGA": f"{SITE}/gedcom/v1/negative",
          "_CONF": f"{SITE}/gedcom/v1/confidence"}
EVENTS = {"birth": "BIRT", "baptism": "CHR", "death": "DEAT", "burial": "BURI", "marriage": "MARR",
          "residence": "RESI",
          "occupation": "OCCU", "census": "CENS", "emigration": "EMIG", "naturalisation": "NATU",
          "military": "EVEN", "other": "EVEN"}
QUAY = {"record": "3", "index": "2", "hypothesis": "1", "refuted": "0"}
# T250: GEDCOM 7's FAMC-STAT, from the status of the birth fact a filiation rests on; an index leaves it unsaid
FAMC_STAT = {"record": "PROVEN", "hypothesis": "CHALLENGED", "refuted": "DISPROVEN"}
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
FRENCH_MONTHS = ("VEND", "BRUM", "FRIM", "NIVO", "PLUV", "VENT", "GERM", "FLOR", "PRAI", "MESS", "THER",
                 "FRUC", "COMP")
QUALIFIERS = {"about": "ABT", "before": "BEF", "after": "AFT", "calculated": "CAL"}


# dates


def _parts(value):
    parts = [int(x) for x in value.lstrip("-").split("-")]
    return parts + [None] * (3 - len(parts))


def _gregorian(value):
    y, m, d = _parts(value)
    out = str(y)
    if m:
        out = f"{MONTHS[m - 1]} {out}"
    if d:
        out = f"{d} {out}"
    return out


def _julian(value):
    y, m, d = _parts(value)
    if m is None or d is None:
        return "JULIAN " + _gregorian(value)
    j = cal.jdn_from_gregorian(y, m, d)
    # Julian calendar from the JDN
    c = j + 32082
    dd = (4 * c + 3) // 1461
    e = c - (1461 * dd) // 4
    mm = (5 * e + 2) // 153
    day = e - (153 * mm + 2) // 5 + 1
    month = mm + 3 - 12 * (mm // 10)
    year = dd - 4800 + mm // 10
    return f"JULIAN {day} {MONTHS[month - 1]} {year}"


def _republican(value):
    y, m, d = _parts(value)
    if m is None or d is None:
        return None
    j = cal.jdn_from_gregorian(y, m, d)
    for year in sorted(cal.REPUBLICAN_YEAR_START, reverse=True):
        start = cal.jdn_from_gregorian(*cal.REPUBLICAN_YEAR_START[year])
        if j >= start:
            offset = j - start
            month, day = offset // 30 + 1, offset % 30 + 1
            if month > 13:
                return None
            return f"FRENCH_R {day} {FRENCH_MONTHS[month - 1]} {year}"
    return None


def date_value(date, version=7):
    """A fact's date as a GEDCOM date: qualifier, calendar, value."""
    if not date or not date.get("value"):
        return None
    calendar = date.get("calendar") or "gregorian"

    def one(value):
        text = None
        if calendar == "julian":
            text = _julian(value)
        elif calendar == "republican":
            text = _republican(value)
        text = text or _gregorian(value)
        if version != 7:
            text = text.replace("JULIAN ", "@#DJULIAN@ ").replace("FRENCH_R ", "@#DFRENCH R@ ")
        return text
    q = date.get("qualifier") or "exact"
    if q == "between" and date.get("end"):
        return f"BET {one(date['value'])} AND {one(date['end'])}"
    prefix = QUALIFIERS.get(q)
    return f"{prefix} {one(date['value'])}" if prefix else one(date["value"])


def axes_quay(axes):
    """GEDCOM QUAY from the three axes of P-10: 3 for an original, primary and direct piece of evidence; 1 for
    indirect or negative evidence; 2 otherwise."""
    if axes.get("evidence") in ("indirect", "negative"):
        return "1"
    if axes.get("source") == "original" and axes.get("information") == "primary" and axes.get("evidence") == "direct":
        return "3"
    return "2"


# export


class Export:
    """The GEDCOM lines of a family."""

    def __init__(self, persons, sources, hypotheses=(), searches=(), places=(), lang="en",
                 living="mask", include_refuted=False, living_years=100, today=None, version=7,
                 media_prefix="", analyses=(), confidence=None, family_dir=None):
        self.version = version
        self.media_prefix = media_prefix  # 5.5.1: from the .ged file to the family folder
        self.family_dir = family_dir   # where the views are; given, a view that is no file there is left out
        self.lang = lang
        self.include_refuted = include_refuted
        self.mode = living
        self.living = living_set(persons, living_years, today)
        self.persons = [p for p in persons if not (living == "exclude" and p["id"] in self.living)]
        # T241: nothing names a person presumed living, whose own record is masked or left out
        self.forms = name_forms(persons, self.living)
        cited = {}
        for p in persons:
            for f in p.get("facts") or []:
                if f.get("source"):
                    cited.setdefault(f["source"], set()).add(p["id"])
        self.sources = {s["id"]: s for s in sources if not (cited.get(s["id"]) and cited[s["id"]] <= self.living)}
        self.hypotheses = [h for h in hypotheses if not names_any(
            " ".join([h.get("question") or ""] + [a.get("statement") or "" for a in h.get("hypotheses") or []]),
            self.forms)]
        self.negatives = [s for s in searches if s.get("result") == "negative" and s.get("family") != "opaque"
                          and not names_any(s.get("query"), self.forms)]
        self.places = {p["id"]: p for p in places}
        self.indi = {p["id"]: f"@I{i}@" for i, p in enumerate(sorted(self.persons, key=lambda p: p["id"]), 1)}
        self.sour = {sid: f"@S{i}@" for i, sid in enumerate(sorted(self.sources), 1)}
        # GPS6-T6: one repository record per repository of a typed source
        self.repo = {name: f"@R{i}@" for i, name in enumerate(sorted(
            {s["repository"] for s in self.sources.values() if s.get("type") and s.get("repository")}), 1)}
        self.media = {}
        self.media_names = {}   # view -> its file name in the GEDZIP's media/, one name per view
        self.missing = []   # the views left out: no file in the family's folder (a URL, a file that is gone)
        # GPS4-T7: the resolved analyses, by the fact they kept
        self.analyses = {a["resolution"]["fact"]: a for a in analyses
                         if a.get("status") == "resolved" and (a.get("resolution") or {}).get("fact")}
        # TRUST3-T4: {fact id: (level 0-3, name)}, the lowest confidence of the conclusions a fact carries
        self.confidence = dict(confidence or {})
        self.fams = self._families()
        self.lines = []

    def _families(self):
        """{(husband, wife): {"children": [...], "marriage": fact}} for couples with a member exported."""
        by_id = {p["id"]: p for p in self.persons}
        fams = {}

        def key(a, b):
            pa, pb = by_id.get(a), by_id.get(b)
            if pa and pa.get("sex") == "F" or (pb and pb.get("sex") == "M"):
                a, b = b, a
            return (a if a in by_id else None, b if b in by_id else None)
        for p in sorted(self.persons, key=lambda p: p["id"]):
            par = p.get("parents") or {}
            couple = (par.get("father") if par.get("father") in by_id else None,
                      par.get("mother") if par.get("mother") in by_id else None)
            if couple != (None, None):
                fams.setdefault(couple, {"children": [], "marriage": None})["children"].append(p["id"])
            for s in p.get("spouses") or []:
                if s.get("person") in by_id:
                    k = key(p["id"], s["person"])
                    fam = fams.setdefault(k, {"children": [], "marriage": None})
                    if s.get("marriage") and fam["marriage"] is None:
                        fam["marriage"] = s["marriage"]
        return {k: dict(v, xref=f"@F{i}@") for i, (k, v) in enumerate(sorted(fams.items(), key=lambda x: str(x[0])), 1)}

    def add(self, level, tag, value=None, xref=None):
        head = f"{level} " + (f"{xref} " if xref else "") + tag
        if value is None or value == "":
            self.lines.append(head)
            return
        value = str(value)
        if self.version == 7 and value.startswith("@") and not re.match(r"^@[^@]+@$", value):
            value = "@" + value
        parts = value.split("\n")
        self._value(head, parts[0], level)
        for extra in parts[1:]:
            self._value(f"{level + 1} CONT", extra, level + 1)

    def _value(self, head, text, level):
        if self.version != 7:
            room = 255 - len(head) - 1
            chunks = []
            while len(text) > room:
                cut = room
                while cut > 1 and (text[cut - 1] == " " or text[cut] == " "):
                    cut -= 1  # never split at a space: CONC joins without one
                chunks.append(text[:cut])
                text = text[cut:]
                room = 255 - len(f"{level + 1} CONC") - 1
            chunks.append(text)
            self.lines.append(f"{head} {chunks[0]}".rstrip())
            for c in chunks[1:]:
                self.lines.append(f"{level + 1} CONC {c}")
        else:
            self.lines.append(f"{head} {text}".rstrip())

    def header(self):
        self.add(0, "HEAD")
        if self.version == 7:
            self.add(1, "GEDC")
            self.add(2, "VERS", "7.0")
            self.add(1, "SCHMA")
            for tag, uri in SCHEMA.items():
                self.add(2, "TAG", f"{tag} {uri}")
            self.add(1, "SOUR", "PROBANDIA")
            self.add(2, "VERS", __version__)
            self.add(2, "NAME", "Probandia")
            self.add(1, "LANG", self.lang)
        else:
            self.add(1, "SOUR", "PROBANDIA")
            self.add(2, "VERS", __version__)
            self.add(2, "NAME", "Probandia")
            self.add(1, "SUBM", "@U1@")
            self.add(1, "GEDC")
            self.add(2, "VERS", "5.5.1")
            self.add(2, "FORM", "LINEAGE-LINKED")
            self.add(1, "CHAR", "UTF-8")

    def _status(self, level, fact):
        """7.0: ``_STATUS`` and ``_EVID``, documented in ``SCHMA``. 5.5.1: a ``NOTE``, with
        ``QUAY`` in the citation: Gramps reports each user tag as an error."""
        status, ev = fact.get("status"), fact.get("evidence") or {}
        axes = " ".join(ev[k] for k in ("source", "information", "evidence") if ev.get(k))
        conf = self.confidence.get(fact.get("id"))
        if self.version == 7:
            self.add(level, "_STATUS", status)
            if axes:
                self.add(level, "_EVID", axes)
            if conf is not None:
                self.add(level, "_CONF", conf[1])
        else:
            self.add(level, "NOTE", f"Status: {status}" + (f"; evidence: {axes}" if axes else "")
                     + (f"; confidence of the conclusion: {conf[1]}" if conf is not None else ""))

    def _place(self, fact):
        place = fact.get("place") or {}
        if place.get("as_written"):
            return place["as_written"]
        entry = self.places.get(place.get("id") or "")
        return (entry or {}).get("current_name") or place.get("id")

    def _citation(self, level, fact):
        src = self.sources.get(fact.get("source") or "")
        if not src:
            return
        self.add(level, "SOUR", self.sour[src["id"]])
        if src.get("type"):
            page = cite.page(src, self.lang)
        else:
            page = ", ".join(str(src[k]) for k in ("reference", "item") if src.get(k))
            if src.get("image_no"):
                page += (", " if page else "") + f"image {src['image_no']}"
        if page:
            self.add(level + 1, "PAGE", page)
        quoted = (fact.get("excerpt") or {}).get("text")
        if quoted:   # TRUST2-T4: the passage the fact cites, as the citation's text
            self.add(level + 1, "DATA")
            self.add(level + 2, "TEXT", quoted)
        if fact.get("status") in QUAY:
            quay = QUAY[fact["status"]]
            conf = self.confidence.get(fact.get("id"))
            if conf is not None and conf[0] < int(quay):   # the conclusion is weaker than the record
                quay = str(conf[0])
            self.add(level + 1, "QUAY", quay)

    def _event(self, level, fact):
        tag = EVENTS.get(fact["type"], "EVEN")
        value = fact.get("value") if fact["type"] in ("occupation",) else None
        self.add(level, tag, value)
        if tag == "EVEN":
            self.add(level + 1, "TYPE", fact["type"] if fact["type"] != "other" else (fact.get("value") or "other"))
        dv = date_value(fact.get("date"), self.version)
        if dv:
            self.add(level + 1, "DATE", dv)
            original = (fact.get("date") or {}).get("original")
            if original:
                if self.version == 7:
                    self.add(level + 2, "PHRASE", original)
                else:
                    self.add(level + 1, "NOTE", f"As written: {original}")
        place = self._place(fact)
        if place:
            self.add(level + 1, "PLAC", place)
        self._citation(level + 1, fact)
        self._status(level + 1, fact)
        self._analysis(level + 1, fact)

    def _analysis(self, level, fact):
        """GPS4-T7: the fact an analysis kept carries its summary as a NOTE, and each other piece of evidence
        of the analysis as a citation, its QUAY from its axes."""
        a = self.analyses.get(fact["id"])
        if a is None:
            return
        res = a["resolution"]
        parts = []
        for i in a["items"]:
            axes = ", ".join((i.get("axes") or {}).get(k) for k in ("source", "information", "evidence")
                             if (i.get("axes") or {}).get(k))
            parts.append(i["asserts"] + (f" ({axes})" if axes else ""))
        self.add(level, "NOTE", f"Analysis {a['id']}: kept {res['value']}. {res['reasoning']} "
                                f"Evidence: {'; '.join(parts)}.")
        cited = {fact.get("source")}
        for i in a["items"]:
            src = self.sources.get(i.get("source") or "")
            if not src or src["id"] in cited:
                continue
            cited.add(src["id"])
            self.add(level, "SOUR", self.sour[src["id"]])
            self.add(level + 1, "PAGE", i["asserts"])
            self.add(level + 1, "QUAY", axes_quay(i.get("axes") or {}))

    def _keep(self, fact):
        return fact.get("status") != "refuted" or self.include_refuted

    def individuals(self):
        by_fam_child = {c: f["xref"] for f in self.fams.values() for c in f["children"]}
        for p in sorted(self.persons, key=lambda p: p["id"]):
            self.add(0, "INDI", xref=self.indi[p["id"]])
            masked = p["id"] in self.living
            names = p.get("names") or {}
            if masked:
                self.add(1, "NAME", "Living //")
            else:
                given, surname = names.get("given") or "", names.get("surname") or ""
                self.add(1, "NAME", f"{given} /{surname}/".strip())
                if given:
                    self.add(2, "GIVN", given)
                if surname:
                    self.add(2, "SURN", surname)
                if p.get("sex") in ("M", "F", "U"):
                    self.add(1, "SEX", p["sex"] if p["sex"] != "U" else "U")
                for f in p.get("facts", []):
                    if f["type"] != "marriage" and self._keep(f):
                        self._event(1, f)
            if p["id"] in by_fam_child:
                self.add(1, "FAMC", by_fam_child[p["id"]])
                if not masked:
                    self._pedigree(2, p)
            for (h, w), fam in self.fams.items():
                if p["id"] in (h, w):
                    self.add(1, "FAMS", fam["xref"])
            self._media_links(p)

    def _pedigree(self, level, person):
        """T250: what a child's link to its parents rests on, its strongest birth or baptism fact. ``PEDI BIRTH``
        (5.5.1: ``birth``) when that fact is a record or an index; in 7.0, ``STAT`` from its status: ``PROVEN`` on
        a record, ``CHALLENGED`` on a hypothesis, ``DISPROVEN`` on a refuted fact. A link no birth fact founds,
        deduced from elsewhere, gets neither."""
        from probandia.trees import basis

        status = (basis(person) or {}).get("status")
        if status in ("record", "index"):
            self.add(level, "PEDI", "BIRTH" if self.version == 7 else "birth")
        if self.version == 7 and status in FAMC_STAT:
            self.add(level, "STAT", FAMC_STAT[status])

    def _on_disk(self, image):
        """A view is exported when it is a file of the family's folder; a URL, or a file that is gone, would be
        a reference to nothing. Without the folder (no check possible), every view goes."""
        return self.family_dir is None or os.path.isfile(os.path.join(self.family_dir, image))

    def _archive_name(self, image):
        """The file name of a view in the GEDZIP's ``media/``: its own, made unique when two views share it
        (``ad50/0012.png`` and ``ad51/0012.png``), so that no view replaces another."""
        if image not in self.media_names:
            base = os.path.basename(image)
            stem, ext = os.path.splitext(base)
            name, n = base, 2
            while name in self.media_names.values():
                name, n = f"{stem}-{n}{ext}", n + 1
            self.media_names[image] = name
        return self.media_names[image]

    def _media_links(self, p):
        for f in p.get("facts", []):
            src = self.sources.get(f.get("source") or "")
            if p["id"] in self.living or not src or src.get("rights") != "free" or not views(src):
                continue
            if src["id"] not in self.media:   # T247: one object, a file per view of the act
                found = [v for v in views(src) if self._on_disk(v)]
                self.missing += [v for v in views(src) if v not in found and v not in self.missing]
                if found:
                    self.media[src["id"]] = (f"@O{len(self.media) + 1}@", found)

    def families(self):
        facts = {f["id"]: f for p in self.persons for f in p.get("facts", [])}
        for (h, w), fam in self.fams.items():
            self.add(0, "FAM", xref=fam["xref"])
            if h:
                self.add(1, "HUSB", self.indi[h])
            if w:
                self.add(1, "WIFE", self.indi[w])
            for c in fam["children"]:
                self.add(1, "CHIL", self.indi[c])
            marriage = facts.get(fam["marriage"] or "")
            if marriage and self._keep(marriage) and not ({h, w} & self.living):
                self._event(1, dict(marriage, type="marriage"))

    def records(self):
        for sid in sorted(self.sources):
            s = self.sources[sid]
            self.add(0, "SOUR", xref=self.sour[sid])
            plain = ", ".join(x for x in (s.get("repository"), s.get("collection")) if x)
            if s.get("type"):
                # GPS6-T6: the entry of the list of sources, its repository, its first note
                title, note = cite.format(s, "full", self.lang), cite.format(s, "first", self.lang)
            else:
                title, note = plain or s.get("citation") or sid, s.get("url")   # GEDCOM 7 has no WWW there
            if names_any(f"{title} {note or ''}", self.forms):   # T241: it names a person presumed living
                title, note = plain or sid, None
            self.add(1, "TITL", title)
            if s.get("type") and s.get("repository"):
                self.add(1, "REPO", self.repo[s["repository"]])
                if s.get("reference"):
                    self.add(2, "CALN", s["reference"])
            if note:
                self.add(1, "NOTE", note)
            if sid in self.media:
                self.add(1, "OBJE", self.media[sid][0])
        for name, xref in sorted(self.repo.items(), key=lambda x: int(x[1][2:-1])):
            self.add(0, "REPO", xref=xref)
            self.add(1, "NAME", name)
        for sid, (xref, images) in sorted(self.media.items(), key=lambda x: x[1][0]):
            self.add(0, "OBJE", xref=xref)
            for image in images:
                name = self._archive_name(image) if self.version == 7 else os.path.basename(image)
                # 7.0: a FILE is a URI reference to the archive's entry, so a space or an accent is encoded
                self.add(1, "FILE", "media/" + urllib.parse.quote(name) if self.version == 7
                         else self.media_prefix + image)
                ext = os.path.splitext(name)[1].lower().lstrip(".")
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "tif": "image/tiff",
                        "tiff": "image/tiff", "pdf": "application/pdf"}.get(ext, "image/jpeg")
                self.add(2, "FORM", mime if self.version == 7 else (ext or "jpg"))
        for i, h in enumerate(self.hypotheses, 1):
            alts = "; ".join(f"{a['id']}: {a['statement']} ({a.get('status', 'open')})" for a in h.get("hypotheses") or [])
            if self.version == 7:
                self.add(0, "_HYPO", h["question"], xref=f"@H{i}@")
                for a in h.get("hypotheses") or []:
                    self.add(1, "NOTE", f"{a['id']}: {a['statement']} ({a.get('status', 'open')})")
            else:
                self.add(0, "NOTE", f"Hypothesis: {h['question']} — {alts}", xref=f"@H{i}@")
        for i, s in enumerate(self.negatives, 1):
            w = s.get("window") or {}
            text = f"{s['query']} ({s.get('engine') or s.get('kind')}, {w.get('from', '?')}-{w.get('to', '?')})"
            if self.version == 7:
                self.add(0, "_NEGA", text, xref=f"@N{i}@")
            else:
                self.add(0, "NOTE", f"Negative search: {text}", xref=f"@N{i}@")
        if self.version != 7:
            self.add(0, "SUBM", xref="@U1@")
            self.add(1, "NAME", "Probandia")

    def text(self):
        self.lines = []
        self.header()
        self.individuals()
        self.families()
        self.records()
        self.add(0, "TRLR")
        return "\n".join(self.lines) + "\n"


def gedzip(export, family_dir):
    """A GEDZIP archive: ``gedcom.ged`` (UTF-8 with BOM) and ``media/`` (free images only).
    Image paths are relative to the family folder."""
    text = export.text()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("gedcom.ged", date_time=(1980, 1, 1, 0, 0, 0))
        z.writestr(info, ("﻿" + text).encode("utf-8"), zipfile.ZIP_DEFLATED)
        written = set()
        for _sid, (_xref, images) in sorted(export.media.items(), key=lambda x: x[1][0]):
            for image in images:   # T247: every view of the act, each under the name its FILE line gives
                path, name = os.path.join(family_dir, image), f"media/{export.media_names[image]}"
                if os.path.isfile(path) and name not in written:
                    written.add(name)
                    with open(path, "rb") as fh:
                        z.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), fh.read(),
                                   zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# reading

ANSEL_SPECIAL = {0xA1: "Ł", 0xA2: "Ø", 0xA3: "Đ", 0xA4: "Þ", 0xA5: "Æ", 0xA6: "Œ", 0xA7: "ʹ", 0xA8: "·",
                 0xA9: "♭", 0xAA: "®", 0xAB: "±", 0xAC: "Ơ", 0xAD: "Ư", 0xAE: "ʼ", 0xB0: "ʻ", 0xB1: "ł",
                 0xB2: "ø", 0xB3: "đ", 0xB4: "þ", 0xB5: "æ", 0xB6: "œ", 0xB7: "ʺ", 0xB8: "ı", 0xB9: "£",
                 0xBA: "ð", 0xBC: "ơ", 0xBD: "ư", 0xC0: "°", 0xC1: "ℓ", 0xC2: "℗", 0xC3: "©", 0xC4: "♯",
                 0xC5: "¿", 0xC6: "¡", 0xC7: "ß", 0xC8: "€"}
ANSEL_COMBINING = {0xE0: "̉", 0xE1: "̀", 0xE2: "́", 0xE3: "̂", 0xE4: "̃",
                   0xE5: "̄", 0xE6: "̆", 0xE7: "̇", 0xE8: "̈", 0xE9: "̌",
                   0xEA: "̊", 0xEB: "︠", 0xEC: "︡", 0xED: "̕", 0xEE: "̋",
                   0xEF: "̐", 0xF0: "̧", 0xF1: "̨", 0xF2: "̣", 0xF3: "̤",
                   0xF4: "̥", 0xF5: "̳", 0xF6: "̲", 0xF7: "̦", 0xF8: "̜",
                   0xF9: "̮", 0xFA: "︢", 0xFB: "︣", 0xFE: "̓"}


def decode_ansel(data):
    """ANSEL (Z39.47): diacritics come before their letter; Unicode puts them after."""
    out, pending = [], []
    for b in data:
        if b in ANSEL_COMBINING:
            pending.append(ANSEL_COMBINING[b])
            continue
        ch = chr(b) if b < 0x80 else ANSEL_SPECIAL.get(b, "�")
        out.append(ch + "".join(reversed(pending)))
        pending = []
    return unicodedata.normalize("NFC", "".join(out))


def decode(data):
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    head = data[:4000]
    m = re.search(rb"\n\s*1\s+CHAR\s+(\S+)", head)
    charset = (m.group(1).decode("ascii", "replace").upper() if m else "UTF-8")
    if charset == "ANSEL":
        return decode_ansel(data)
    if charset in ("ANSI", "WINDOWS-1252", "CP1252", "IBMPC"):
        return data.decode("cp1252", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


LINE = re.compile(r"^\s*(\d+)\s+(?:(@[^@\s]+@)\s+)?([A-Za-z0-9_]+)(?:\s(.*))?$")


class Node:
    __slots__ = ("level", "xref", "tag", "value", "children")

    def __init__(self, level, xref, tag, value):
        self.level, self.xref, self.tag, self.value, self.children = level, xref, tag, value, []

    def first(self, tag):
        return next((c for c in self.children if c.tag == tag), None)

    def all(self, tag):
        return [c for c in self.children if c.tag == tag]

    def text(self, tag):
        node = self.first(tag)
        return node.value if node is not None else None


def parse(text):
    """The top-level records of a GEDCOM text, with ``CONC`` and ``CONT`` joined."""
    roots, stack = [], []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE.match(raw.lstrip("﻿"))
        if not m:
            continue
        level, xref, tag, value = int(m.group(1)), m.group(2), m.group(3).upper(), m.group(4) or ""
        if value.startswith("@@"):
            value = value[1:]
        while stack and stack[-1].level >= level:
            stack.pop()
        if tag in ("CONC", "CONT") and stack:
            parent = stack[-1]
            parent.value = (parent.value or "") + ("\n" if tag == "CONT" else "") + value
            continue
        node = Node(level, xref, tag, value)
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def read_file(path):
    """(text, version) of a ``.ged`` or a ``.gdz`` (its ``gedcom.ged``)."""
    if path.lower().endswith((".gdz", ".zip")):
        with zipfile.ZipFile(path) as z:
            data = z.read("gedcom.ged")
    else:
        with open(path, "rb") as fh:
            data = fh.read()
    text = decode(data)
    roots = parse(text)
    head = next((r for r in roots if r.tag == "HEAD"), None)
    gedc = head.first("GEDC") if head else None
    version = (gedc.text("VERS") if gedc else None) or "5.5.1"
    return roots, version


GED_MONTHS = {m: i for i, m in enumerate(MONTHS, 1)}
FR_MONTHS = {m: i for i, m in enumerate(FRENCH_MONTHS, 1)}
DATE_RX = re.compile(r"^(?:(\d{1,2})\s+)?(?:([A-Z]{3,4})\s+)?(\d{1,4})(?:/\d+)?(?:\s+B\.?C\.?)?$")


def _one(text):
    """(iso, calendar) of one GEDCOM date, or None."""
    text = text.strip().upper()
    calendar = "gregorian"
    for esc, name in (("@#DJULIAN@", "julian"), ("JULIAN", "julian"), ("@#DFRENCH R@", "republican"),
                      ("FRENCH_R", "republican"), ("@#DGREGORIAN@", "gregorian"), ("GREGORIAN", "gregorian")):
        if text.startswith(esc):
            calendar, text = name, text[len(esc):].strip()
    m = DATE_RX.match(text)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2), int(m.group(3))
    if calendar == "republican":
        mon = FR_MONTHS.get(month or "")
        if mon and day:
            g = cal.republican_to_gregorian(year, mon, int(day))
            return (cal.iso(*g), calendar) if g else None
        span = cal.republican_year_span(year)
        return (cal.iso(span[0][0]), calendar) if span else None
    mon = GED_MONTHS.get(month or "") if month else None
    if month and not mon:
        return None
    if calendar == "julian" and mon and day:
        return cal.iso(*cal.julian_to_gregorian(year, mon, int(day))), calendar
    return cal.iso(year, mon, int(day) if day and mon else None), calendar


def parse_date(text):
    """A GEDCOM date as a fact date, or None (then kept as written)."""
    if not text:
        return None
    raw = text.strip()
    t = raw.upper()
    m = re.match(r"^\((.*)\)$", raw)
    if m:
        return None
    t = re.sub(r"^INT\s+(.*?)\s*\(.*\)$", r"\1", t)
    qualifier = "exact"
    for prefix, q in (("ABT ", "about"), ("EST ", "about"), ("CAL ", "calculated"), ("BEF ", "before"),
                      ("AFT ", "after"), ("TO ", "before"), ("FROM ", "after")):
        if t.startswith(prefix):
            qualifier, t = q, t[len(prefix):]
            break
    if t.startswith("BET ") and " AND " in t:
        a, b = t[4:].split(" AND ", 1)
        first, second = _one(a), _one(b)
        if not first or not second:
            return None
        return {"value": first[0], "qualifier": "between", "end": second[0], "calendar": first[1],
                "original": raw}
    if t.startswith("FROM ") and " TO " in t:
        t = t[5:].split(" TO ", 1)[0]
    one = _one(t)
    if not one:
        return None
    return {"value": one[0], "qualifier": qualifier, "end": None, "calendar": one[1], "original": raw}
