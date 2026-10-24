"""Import of a prototype workshop. The workshop is read, never written.

| Prototype | Probandia |
|---|---|
| ``commun/personnes.yaml`` | ``persons.yaml``; statuses acte, index, hypothese, refute |
| the ``source`` sentence of a fact | a ``sources.yaml`` entry with that citation |
| ``image`` | a file copied into ``evidence/`` |
| a note ``DIVERGENCE NON TRANCHÉE :`` | a ``hypotheses.yaml`` entry |
| a note ``LECTURE INCERTAINE :`` | ``uncertain_reading`` |
| ``commun/depouilles.yaml`` | ``searches.yaml`` |
| ``commun/variantes.yaml`` | ``variants.yaml`` |
| ``rapports/<name>/rapport.html`` | a closed journal research, one section per ``<article>`` |
| ``outils/collecte/*.py`` | ``library/connectors/``, status ``draft``, no witness |

What could not be converted is listed in ``work/import-report.md``.
"""
import hashlib
import html
import os
import re
import shutil
from html.parser import HTMLParser

from probandia import events
from probandia.errors import UsageError
from probandia.i18n import _
from probandia.util import yamlio
from probandia.util.fs import atomic_write_text, iso, utc_now
from probandia.util.ids import is_slug, slugify, ulid

STATUSES = {"acte": "record", "index": "index", "hypothese": "hypothesis", "hypothèse": "hypothesis",
            "refute": "refuted", "réfuté": "refuted", "refuté": "refuted"}
FACTS = {"naissance": "birth", "bapteme": "baptism", "baptême": "baptism", "mariage": "marriage",
         "deces": "death", "décès": "death", "inhumation": "burial", "residence": "residence",
         "résidence": "residence", "profession": "occupation", "recensement": "census",
         "militaire": "military", "emigration": "emigration", "émigration": "emigration"}
RESULTS = {"positif": "positive", "negatif": "negative", "négatif": "negative", "partiel": "partial"}
DIVERGENCE = re.compile(r"^\s*DIVERGENCE NON TRANCH[ÉE]E\s*:\s*", re.I)
UNCERTAIN = re.compile(r"^\s*LECTURE INCERTAINE\s*:\s*", re.I)


def _witness_of(code):
    """The ``WITNESS = {...}`` literal of a script, or None."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "WITNESS" for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None


def is_workshop(folder):
    return os.path.isfile(os.path.join(folder, "commun", "personnes.yaml"))


def workshop_pending(project):
    """True when the project folder is itself a prototype workshop that was never
    imported: a research opened there would ignore what the workshop establishes.
    ``workshop.yaml`` says it was; ``work/import-report.md`` for an import made before it."""
    return bool(project) and is_workshop(project) and not os.path.isfile(link_path(project)) \
        and not os.path.isfile(report_path(project))


def report_path(project):
    return os.path.join(project, "work", "import-report.md")


def link_path(project):
    """``workshop.yaml``: the link between the project and its workshop (schema workshop-link-1)."""
    return os.path.join(project, "workshop.yaml")


WID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")   # an id of the workshop (its outils/validation.py)
ROMAN = re.compile(r"^[IVXLCDM]+$")


def _roman(value):
    """A volet, a chapter or a generation of the workshop: Roman numerals, else None."""
    text = str(value).strip() if value is not None else ""
    return text if ROMAN.match(text) else None


def _load(path, default):
    if not os.path.isfile(path):
        return default
    return yamlio.load(path) or default


# HTML of the workshop's reports -> Markdown


class _Markdown(HTMLParser):
    BLOCKS = {"p", "div", "section", "blockquote", "ul", "ol", "table", "tr", "figure", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.lists, self.href = [], [], None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "nav"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5"):
            self.out.append("\n\n" + "#" * min(int(tag[1]) + 1, 6) + " ")
        elif tag in self.BLOCKS:
            self.out.append("\n\n" + ("> " if tag == "blockquote" else ""))
            if tag in ("ul", "ol"):
                self.lists.append(tag)
        elif tag == "li":
            self.out.append("\n" + "  " * (len(self.lists) - 1) + ("1. " if self.lists[-1:] == ["ol"] else "- "))
        elif tag == "br":
            self.out.append("  \n")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag == "a":
            self.href = a.get("href")
            self.out.append("[")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]")
            self.href = None
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data).replace("<", "&lt;"))

    def text(self):
        md = "".join(self.out)
        md = re.sub(r"[ \t]+\n", "\n", md)
        md = re.sub(r"\n{3,}", "\n\n", md)
        return "\n".join(line.strip() if not line.startswith("  ") else line.rstrip()
                         for line in md.strip().splitlines()).strip()


def html_to_markdown(text):
    p = _Markdown()
    p.feed(text)
    p.close()
    return p.text()


ARTICLE = re.compile(r"<article\b[^>]*>(.*?)</article>", re.S | re.I)
HEADING = re.compile(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", re.S | re.I)
TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)


def _plain(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def chapters(report_html):
    """[(title, body Markdown)] of the ``<article>`` elements of a report."""
    out = []
    for body in ARTICLE.findall(report_html):
        m = HEADING.search(body)
        title = _plain(m.group(1)) if m else ""
        rest = body[m.end():] if m else body
        title = re.sub(r"^(?:[IVXLCDM]+|[0-9]+|[A-Z])[.)]\s+", "", title)  # the numbers are the engine's now
        out.append((title or f"{len(out) + 1}", html_to_markdown(rest)))
    return out


# the mapping


class Import:
    def __init__(self, project, workshop, family=None, actor=None, now=None):
        if not is_workshop(workshop):
            raise UsageError(_("{path} is not a prototype workshop: no commun/personnes.yaml").format(
                path=workshop))
        self.project = project
        self.workshop = os.path.abspath(workshop)
        self.now = now or utc_now()
        self.actor = actor or {"harness": "cli", "agent": "session"}
        self.people = _load(os.path.join(workshop, "commun", "personnes.yaml"), {})
        self.family = family or self._family()
        self.notes = []          # what could not be converted
        self.sources, self.by_citation = [], {}
        self.persons, self.hypotheses, self.searches = [], [], []
        self.variants = {"schema": 1, "surnames": {}, "given": {}}
        self.images, self.connectors, self.researches = [], [], []
        self.ids = {}
        self.link_persons, self.link_facts = {}, {}
        self.report_origin, self.research_of = {}, {}

    def _family(self):
        counts = {}
        for p in self.people.get("personnes") or []:
            if isinstance(p, dict) and p.get("nom") and p.get("statut") != "refute":
                counts[str(p["nom"]).upper()] = counts.get(str(p["nom"]).upper(), 0) + 1
        if not counts:
            raise UsageError(_("no family name found in the workshop: name one with --family"))
        return slugify(max(sorted(counts), key=lambda k: counts[k]))

    def note(self, text):
        self.notes.append(text)

    # persons and facts

    def _source(self, sentence, image=None):
        sentence = str(sentence or "").strip()
        if not sentence:
            return None
        if sentence in self.by_citation:
            return self.by_citation[sentence]
        sid = f"src-{ulid()}"
        entry = {"id": sid, "citation": sentence}
        if image:
            entry["image"] = image
        self.sources.append(entry)
        self.by_citation[sentence] = sid
        return sid

    def _image(self, path):
        if not path:
            return None
        # the workshop keeps its scans in sources/, and a fact often names the file alone
        src = next((p for p in (os.path.join(self.workshop, str(path)),
                                os.path.join(self.workshop, "sources", str(path))) if os.path.isfile(p)), None)
        if src is None:
            self.note(f"image not found: {path}")
            return None
        name = os.path.basename(src)
        self.images.append((src, name))
        return f"evidence/{name}"

    def _date(self, fact):
        from probandia.lang.dates import read

        text = str(fact.get("date") or "").strip()
        if text:
            try:
                d = read(text)
                out = {"value": d["iso"], "qualifier": d["qualifier"], "calendar": d["calendar"],
                       "original": text}
                if d.get("end"):
                    out["end"] = d["end"]
                return out
            except Exception:  # noqa: BLE001 — anything unreadable keeps its year
                self.note(f"date kept as its year: {text!r}")
        year = fact.get("annee")
        if isinstance(year, int) or (isinstance(year, str) and year.isdigit()):
            return {"value": f"{int(year):04d}", "qualifier": "about" if text else "exact",
                    "original": text or None}
        return None

    def _fact(self, pid, ftype, raw, n, research_of):
        status = STATUSES.get(str(raw.get("statut") or "").strip().lower())
        if status is None:
            self.note(f"{pid}.{ftype}: unknown status {raw.get('statut')!r}; imported as hypothesis")
            status = "hypothesis"
        image = self._image(raw.get("image"))
        fact = {"id": f"{pid}.{ftype}" + (f".{n}" if n > 1 else ""), "type": ftype, "status": status,
                "date": self._date(raw), "place": {"id": None, "as_written": str(raw["lieu"])} if raw.get("lieu") else None,
                "source": self._source(raw.get("source"), image), "note": ""}
        if status in ("record", "index") and not fact["source"]:
            self.note(f"{fact['id']}: {status} without a source sentence (rule P-1 will flag it)")
        note = str(raw.get("note") or "")
        if DIVERGENCE.match(note):
            text = DIVERGENCE.sub("", note).strip()
            parts = [x.strip(" .") for x in re.split(r";|,| ou | or ", text) if x.strip(" .")] or [text]
            alts = [{"id": chr(97 + i), "statement": x, "status": "open"} for i, x in enumerate(parts[:6])]
            self.hypotheses.append({"id": f"h-{slugify(fact['id'])}"[:64], "question": text or fact["id"],
                                    "hypotheses": alts,
                                    "evidence": [{"ref": fact["id"], "marks": {a["id"]: "neutral" for a in alts}}],
                                    "discriminating": None, "opened": self.now.strftime("%Y-%m-%d"),
                                    "closed": None, "outcome": None})
        elif UNCERTAIN.match(note):
            fact["uncertain_reading"] = UNCERTAIN.sub("", note).strip()
        elif note:
            fact["note"] = note
        report = raw.get("rapport")
        if report and report in research_of:
            fact["research"] = research_of[report]
        return fact

    # the link (workshop.yaml): what the workshop needs back, which Probandia's records cannot hold

    def _link_person(self, pid, raw):
        wid = str(raw.get("id") or "")
        if not WID.match(wid):
            self.note(f"{pid}: workshop id {wid!r} kept out of workshop.yaml (not a workshop id)")
            return
        self.link_persons[pid] = {"workshop": wid, "generation": _roman(raw.get("generation")),
                                  "volet": _roman(raw.get("volet")), "chapitre": _roman(raw.get("chapitre"))}

    def _link_fact(self, fid, wid, key, index, item):
        wid = str(wid or "")
        if not WID.match(wid):
            return
        year = item.get("annee")
        date = item.get("date")
        self.link_facts[fid] = {
            "person": wid, "key": key, "index": index,
            "annee": int(year) if isinstance(year, int) or (isinstance(year, str) and year.isdigit()) else None,
            "date_text": str(date) if date not in (None, "") else None,
            "volet": _roman(item.get("volet")), "chapitre": _roman(item.get("chapitre")),
            "rapport": str(item["rapport"]) if item.get("rapport") else None}

    def link_doc(self):
        with open(os.path.join(self.workshop, "commun", "personnes.yaml"), "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        root = os.path.relpath(self.workshop, os.path.abspath(self.project)).replace(os.sep, "/")
        return {"schema": 1, "adapter": "prototype", "root": root,
                "families": {self.family: [p["workshop"] for p in self.link_persons.values()]},
                "persons": self.link_persons, "facts": self.link_facts,
                "researches": {rid: {"rapport": name, "origine": self.report_origin.get(name, False)}
                               for name, rid in self.research_of.items()},
                "synced": {"sha256": digest, "at": iso(self.now), "pushed": 0, "pulled": 0}}

    def _person_id(self, raw):
        pid = str(raw.get("id") or "")
        if not is_slug(pid):
            pid = slugify(pid or f"{raw.get('prenoms', '')} {raw.get('nom', '')}")
        return pid

    def map_persons(self, research_of):
        raw_people = [p for p in self.people.get("personnes") or [] if isinstance(p, dict) and p.get("id")]
        for raw in raw_people:
            self.ids[str(raw["id"])] = self._person_id(raw)
        for raw in raw_people:
            pid = self.ids[str(raw["id"])]
            person = {"id": pid, "names": {"given": str(raw.get("prenoms") or ""),
                                           "surname": str(raw.get("nom") or "").upper()},
                      "sex": raw.get("sexe") if raw.get("sexe") in ("M", "F") else "U", "living": "auto",
                      "parents": {"father": self.ids.get(str(raw.get("pere"))),
                                  "mother": self.ids.get(str(raw.get("mere")))},
                      "spouses": [], "facts": []}
            counts = {}
            for key, ftype in FACTS.items():
                value = raw.get(key)
                items = list(enumerate(value)) if isinstance(value, list) else \
                    [(None, value)] if isinstance(value, dict) else []
                for index, item in items:
                    if not isinstance(item, dict):
                        continue
                    counts[ftype] = counts.get(ftype, 0) + 1
                    item = dict(item)
                    item.setdefault("rapport", raw.get("rapport"))
                    if str(raw.get("statut")) == "refute":
                        item["statut"] = "refute"
                    fact = self._fact(pid, ftype, item, counts[ftype], research_of)
                    person["facts"].append(fact)
                    self._link_fact(fact["id"], raw["id"], key, index, item)
            self._link_person(pid, raw)
            known = set(FACTS) | {"id", "nom", "prenoms", "sexe", "statut", "pere", "mere", "volet",
                                  "volet_refute", "rapport", "chapitre", "note", "generation"}
            extra = sorted(k for k in raw if k not in known)
            if extra:
                self.note(f"{pid}: fields not imported: {', '.join(extra)}")
            self.persons.append(person)
        by_id = {p["id"]: p for p in self.persons}
        for index, u in enumerate(self.people.get("unions") or []):
            if not isinstance(u, dict):
                continue
            a, b = self.ids.get(str(u.get("epoux"))), self.ids.get(str(u.get("epouse")))
            holder = u.get("epoux")
            if a not in by_id and b in by_id:   # T175: a husband named only in words (conjoint_libre): the wife's
                a, b, holder = b, None, u.get("epouse")
            if a not in by_id:
                self.note(f"union without a known husband: {u.get('epoux')}")
                continue
            fact = self._fact(a, "marriage", u, 1 + sum(1 for f in by_id[a]["facts"] if f["type"] == "marriage"),
                              research_of)
            by_id[a]["facts"].append(fact)
            self._link_fact(fact["id"], holder, "unions", index, u)
            if b in by_id:
                by_id[a]["spouses"].append({"person": b, "marriage": fact["id"]})
                by_id[b]["spouses"].append({"person": a, "marriage": fact["id"]})

    # search log, variants, connectors

    def map_searches(self):
        entries = _load(os.path.join(self.workshop, "commun", "depouilles.yaml"), [])
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict):
                continue
            result = RESULTS.get(str(e.get("resultat") or "").lower())
            if result is None:
                self.note(f"search without a known result: {e.get('gisement')} {e.get('cote')}")
                continue
            fenetre = str(e.get("fenetre") or "")
            years = [int(y) for y in re.findall(r"\b(\d{4})\b", fenetre)]
            places = [p.strip() for p in re.sub(r"\d{4}\s*-\s*\d{4}|\d{4}", "", fenetre).split(",") if p.strip()]
            ts = f"{e['date']}T00:00:00Z" if re.match(r"^\d{4}-\d{2}-\d{2}$", str(e.get("date") or "")) \
                else iso(self.now)
            self.searches.append({
                "id": f"s-{ulid()}", "ts": ts, "research": None, "pass": None, "kind": "archive",
                "engine": str(e.get("gisement") or "?"), "family": None, "query": str(e.get("question") or ""),
                "variants": [], "filters": {"reference": e.get("cote"), "views": e.get("vues")},
                "window": {"from": min(years) if years else None, "to": max(years) if years else None,
                           "places": places},
                "results": None, "result": result, "failure": None, "support": "image", "witness": None,
                "source_state": e.get("note") or None, "recheck_if": None, "recheck_after": None,
                "units": None, "proves": None})

    def map_variants(self):
        entries = _load(os.path.join(self.workshop, "commun", "variantes.yaml"), [])
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict) or not e.get("forme"):
                continue
            kind = "given" if e.get("type") in ("prenom", "prénom") else "surnames"
            forms = self.variants[kind].setdefault(str(e["forme"]), [])
            for v in e.get("variantes") or []:
                if isinstance(v, dict):
                    forms.append({"form": str(v.get("forme") or v.get("form") or ""), "source": v.get("source")})
                else:
                    forms.append({"form": str(v), "source": e.get("source")})

    def map_connectors(self):
        folder = os.path.join(self.workshop, "outils", "collecte")
        if not os.path.isdir(folder):
            return
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py") and not name.startswith("_"):
                self.connectors.append((os.path.join(folder, name), slugify(name[:-3])))

    def map_reports(self):
        """Each ``rapports/<name>/`` becomes a closed research in journal mode."""
        folder = os.path.join(self.workshop, "rapports")
        out = {}
        if not os.path.isdir(folder):
            return out
        for name in sorted(os.listdir(folder)):
            declared = _load(os.path.join(folder, name, "rapport.yaml"), {})
            if isinstance(declared, dict):
                self.report_origin[name] = declared.get("origine") is True
            path = os.path.join(folder, name, "rapport.html")
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            m = TITLE.search(text)
            title = _plain(m.group(1)) if m else name
            rid = f"{self.now.strftime('%Y-%m-%d')}-{slugify(name)}"[:64].rstrip("-")
            parts = chapters(text)
            if not parts:
                self.note(f"rapports/{name}: no <article> found")
            self.researches.append((rid, title, parts))
            out[name] = rid
        return out

    def run(self):
        research_of = self.research_of = self.map_reports()
        self.map_persons(research_of)
        self.map_searches()
        self.map_variants()
        self.map_connectors()
        return self

    # writing

    def write(self):
        from probandia.indexes import FamilyIndexes, locked
        from probandia.lifecycle import create_family
        from probandia.util.schema import validate_document

        if os.path.isfile(link_path(self.project)):
            raise UsageError(_("this project is already linked to its workshop (workshop.yaml): see the "
                               "workshop's later changes with workshop status and workshop diff, bring them in with "
                               "workshop pull, never a second import"),
                             values={"REASON": "already-imported"})
        link = self.link_doc()
        validate_document("workshop-link", link, "workshop.yaml")
        create_family(self.project, self.family, language="fr")
        fam = os.path.join(self.project, "families", self.family)
        idx = FamilyIndexes(self.project, self.family)
        with locked(self.project, f"family:{self.family}", self.actor):
            docs = {}
            persons = idx.load("persons")
            known = {p["id"] for p in persons["persons"]}
            clash = [p["id"] for p in self.persons if p["id"] in known]
            if clash:
                raise UsageError(_("persons already in the family: {ids}").format(ids=", ".join(clash[:5])))
            persons["persons"] += self.persons
            docs["persons"] = persons
            for name, key, items in (("sources", "sources", self.sources),
                                     ("hypotheses", "hypotheses", self.hypotheses),
                                     ("searches", "searches", self.searches)):
                doc = idx.load(name)
                doc[key] += items
                docs[name] = doc
            variants = idx.load("variants")
            for kind in ("surnames", "given"):
                for form, items in self.variants[kind].items():
                    variants.setdefault(kind, {}).setdefault(form, []).extend(items)
            docs["variants"] = variants
            for src, name in self.images:
                os.makedirs(os.path.join(fam, "evidence"), exist_ok=True)
                shutil.copy2(src, os.path.join(fam, "evidence", name))
            idx.write(docs, self.actor, "import")
        for rid, title, parts in self.researches:
            self._write_research(rid, title, parts)
        self._write_connectors()
        yamlio.dump(link_path(self.project), link)
        return self._write_report()

    def _write_research(self, rid, title, parts):
        from probandia.research import Research
        from probandia.util.schema import validate_document

        r = Research(self.project, self.family, rid)
        if os.path.exists(r.folder):
            self.note(f"research {rid} already exists: not imported again")
            return
        os.makedirs(r.folder)
        ts = iso(self.now)
        meta = {"schema": 1, "id": rid, "family": self.family, "question": title or rid, "language": "fr",
                "mode": "journal", "numbering": "roman", "formats": ["md", "html"], "created": ts,
                "created_by": {"harness": self.actor.get("harness", "cli"), "agent": "import"},
                "forked_from": None, "run": {"mode": "session"}, "instructions": [], "status": "closed",
                "passes": 1}
        validate_document("research", meta, "research.yaml")
        yamlio.dump(os.path.join(r.folder, "research.yaml"), meta)
        actor = dict(self.actor, agent="import")
        evs = [events.make("pass.started", {"n": 1, "run": {"mode": "session"}, "instructions": [],
                                            "imported": True}, actor, 1, now=self.now),
               events.make("plan.made", {"imported": True}, actor, 1, now=self.now)]
        for title_, body in parts:
            sid = ulid()
            evs.append(events.make("section.added", {"section": {"id": sid, "parent": None, "kind": "chapter",
                                                                 "title": title_, "body_md": body, "facts": []}},
                                   actor, 1, now=self.now))
        evs.append(events.make("pass.ended", {"n": 1, "summary": "imported", "units": {}, "native_searches": 0,
                                              "duration_s": 0}, actor, 1, now=self.now))
        events.append(r.events_path, evs)

    def _write_connectors(self):
        """The prototype's collectors go to the library as drafts, with the hosts the
        workshop's profile declares; a collector that has the library's entry point and
        a ``WITNESS`` gets its witness run, and becomes ``tested`` when it passes."""
        if not self.connectors:
            return
        from probandia.library import Escapes, Library

        lib = Library(self.project, now=self.now)
        have = {s["id"] for s in lib.scripts()}
        declared = {}
        profile = _load(os.path.join(self.workshop, "genealogie.profil.yaml"), {})
        for g in profile.get("gisements") or [] if isinstance(profile, dict) else []:
            if isinstance(g, dict) and g.get("client"):
                declared[os.path.basename(str(g["client"]))] = g
        self.connector_states = []
        for src, sid in self.connectors:
            if sid in have:
                self.note(f"connector {sid} already in the library")
                continue
            g = declared.get(os.path.basename(src), {})
            with open(src, encoding="utf-8", errors="replace") as fh:
                code = fh.read()
            witness = _witness_of(code)
            purpose = g.get("note") or f"imported from the prototype: {os.path.basename(src)}"
            try:
                lib.save(src, sid, "connector", purpose, witness, [str(h) for h in g.get("hotes") or []], [],
                         author={"harness": "import"})
            except Escapes as err:   # T175: one collector the library refuses, not the whole import
                self.connector_states.append((sid, "refused", str(err)))
                self.note(f"connector {sid}: not kept — {err}")
                continue
            if not re.search(r"^def run\(\s*args\s*,\s*http", code, re.M):
                why = "no run(args, http) entry point: a command-line client of the workshop, to wrap"
            elif witness is None:
                why = "no WITNESS in the script: write one, then library test"
            elif not g.get("hotes") and re.search(r"https?://", code):
                why = "no hosts declared in genealogie.profil.yaml"
            else:
                ok, error = lib.test(sid)
                why = None if ok else f"its witness failed: {error}"
            state = "tested" if why is None else "draft"
            self.connector_states.append((sid, state, why))
            self.note(f"connector {sid}: tested" if why is None else f"connector {sid}: stays draft — {why}")

    def report_text(self):
        lines = ["# Import report", "", f"- Workshop: `{self.workshop}`", f"- Family: `{self.family}`",
                 f"- Date: {iso(self.now)}", "", "## Mapping", "",
                 "| Prototype | Probandia | Count |", "|---|---|---|",
                 f"| commun/personnes.yaml | persons.yaml | {len(self.persons)} persons, "
                 f"{sum(len(p['facts']) for p in self.persons)} facts |",
                 f"| source sentences | sources.yaml | {len(self.sources)} |",
                 f"| images | evidence/ | {len(self.images)} |",
                 f"| DIVERGENCE NON TRANCHÉE | hypotheses.yaml | {len(self.hypotheses)} |",
                 f"| LECTURE INCERTAINE | uncertain_reading | "
                 f"{sum(1 for p in self.persons for f in p['facts'] if f.get('uncertain_reading'))} |",
                 f"| commun/depouilles.yaml | searches.yaml | {len(self.searches)} |",
                 f"| commun/variantes.yaml | variants.yaml | "
                 f"{sum(len(v) for v in self.variants['surnames'].values()) + sum(len(v) for v in self.variants['given'].values())} |",
                 f"| rapports/ | closed researches | {len(self.researches)} |",
                 f"| outils/collecte/ | library/connectors (draft) | {len(self.connectors)} |",
                 f"| volet, chapitre, annee, generation | workshop.yaml | {len(self.link_facts)} facts, "
                 f"{len(self.link_persons)} persons |",
                 "", "## Not converted", ""]
        lines += [f"- {n}" for n in self.notes] or ["- nothing"]
        return "\n".join(lines) + "\n"

    def _write_report(self):
        path = report_path(self.project)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_text(path, self.report_text())
        return path
