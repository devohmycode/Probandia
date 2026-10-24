"""The jurisdictions a place came under, beyond the INSEE COG (GPS2-T3).

- GOV: the parents of a place on its page, with their dates and types; the parish
  of a place is often reached through its church; then deanery and diocese.
- Wikidata: the cantons a French commune belonged to, with their end dates, and a
  diocese when the item gives one.
- France (GPS-D9): the commune of 1790 follows the parish of the same name, and the
  department's diocese since the Concordat comes from ``catalogues/dioceses-fr.yaml``;
  both are rules, marked ``derived``.

Every function takes an ``http`` with ``get(url, params) -> text`` (``lang.places.Http``;
tests give recorded responses) and returns jurisdictions in the form of ``places.yaml``.
"""
import html
import json
import re

from probandia.lang.places import key

GOV_PAGE = "https://gov.genealogy.net/item/show/{id}"
WIKIDATA = "https://www.wikidata.org/w/api.php"
DAY = re.compile(r"^-?[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$")

GOV_LEVELS = {
    "Pfarrei": "parish", "Kirchspiel": "parish", "Pfarrkuratie": "parish", "Pfarr-Rektorat": "parish",
    "Dompfarrei": "parish", "paroisse": "parish",
    "Pfarrverband": "parish-group", "Pfarreiengemeinschaft": "parish-group",
    "Dekanat": "deanery", "Kirchenkreis": "deanery", "Superintendentur": "deanery",
    "Bistum": "diocese", "Diözese": "diocese", "Erzbistum": "diocese", "diocèse": "diocese",
    "Kirchenprovinz": "church-province",
    "commune": "commune",
    "Gemeinde": "municipality", "Ortsgemeinde": "municipality", "Landgemeinde": "municipality",
    "Stadtgemeinde": "municipality", "Marktgemeinde": "municipality", "Bürgermeisterei": "municipality",
    "Mairie": "municipality", "Amt": "municipality", "Verbandsgemeinde": "municipality",
    "Verwaltungsgemeinschaft": "municipality", "Samtgemeinde": "municipality",
    "Kanton": "canton", "canton": "canton",
    "Kreis": "district", "Landkreis": "district", "Landratsamt": "district", "Oberamt": "district",
    "Bezirksamt": "district", "arrondissement": "arrondissement",
    "Departement": "department", "Regierungsbezirk": "province", "Provinz": "province",
    "Amtsgericht": "court", "Landgericht": "court",
}
CHURCH_LEVELS = ("parish", "parish-group", "deanery", "diocese", "church-province")
CHURCHES = ("Kirche", "église")
TOP = ("diocese", "church-province", "department", "province", "state", "country")
MAX_DEPTH = {"church": 5, "civil": 2}
GOV_BUDGET = 15  # pages read for one place, at most
CANTON_CLASSES = {"Q184188", "Q18524218"}  # canton of France; canton of France (until 2015)


class NotConsulted(Exception):
    """The source did not answer: a challenge page, an error, the page budget spent."""


# GOV


def _clean(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _period(text):
    """``(1972 -)``, ``(- 1934-05-31)``, ``(1798 - 1834)`` or nothing: (from, to)."""
    inner = text.strip().strip("()").strip()
    if not inner:
        return None, None
    if inner.startswith("-"):
        start, end = None, inner[1:].strip()
    elif inner.endswith("-"):
        start, end = inner[:-1].strip(), None
    elif " - " in inner:
        start, end = (x.strip() for x in inner.split(" - ", 1))
    else:
        start = end = inner
    return (start if start and DAY.match(start) else None), (end if end and DAY.match(end) else None)


def _rows(text, table):
    m = re.search(r'<table[^>]*id="' + table + r'".*?<tbody>(.*?)</tbody>', text, re.S)
    if not m:
        return []
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        ref = re.search(r'href="/item/show/([A-Za-z0-9_]+)"', row)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if ref and cells:
            out.append((ref.group(1), cells))
    return out


def parse_gov(text):
    """The parents (ref, names, types, from, to, source) and the children (ref, name, types)
    of a GOV page."""
    if "anubis" in text.lower() and "parentobjects" not in text:
        raise NotConsulted("gov: challenge page")
    parents = []
    for ref, cells in _rows(text, "parentobjects"):
        if len(cells) < 3:
            continue
        start, end = _period(_clean(cells[1]))
        types = [_clean(t) for t in re.findall(r"<span[^>]*>([^<]*)</span>", cells[2])]
        source = re.search(r'title="([^"]+)"', cells[3]) if len(cells) > 3 else None
        parents.append({"ref": ref, "names": [n.strip() for n in _clean(cells[0]).split(",") if n.strip()],
                        "types": [t for t in types if t], "from": start, "to": end,
                        "source": html.unescape(source.group(1)) if source else None})
    children = []
    for ref, cells in _rows(text, "subordinateobjects"):
        types = [_clean(t) for t in re.findall(r"<span[^>]*>([^<]*)</span>", cells[1])] if len(cells) > 1 else []
        children.append({"ref": ref, "name": _clean(cells[0]), "types": [t for t in types if t]})
    return {"parents": parents, "children": children}


def _level(types):
    for t in types:
        if t in GOV_LEVELS:
            return GOV_LEVELS[t]
    return None


def _overlap(a_from, a_to, b_from, b_to):
    """The common part of two periods, or None. Years and days compare as text by their year first."""
    start = max([x for x in (a_from, b_from) if x], default=None, key=lambda d: (d[:4], d))
    end = min([x for x in (a_to, b_to) if x], default=None, key=lambda d: (d[:4], d))
    if start and end and end[:4] < start[:4]:
        return None
    return start, end


def gov_jurisdictions(ident, http, name=None, budget=GOV_BUDGET):
    """(jurisdictions, notes) of GOV object ``ident``: its civil parents two levels up, and
    its parish (directly, or through the church of the settlement of the same name), then
    the parish's deanery and diocese."""
    pages, notes = {}, []

    def page(ref):
        if ref not in pages:
            if len(pages) >= budget:
                raise NotConsulted("gov: page budget spent")
            pages[ref] = parse_gov(http.get(GOV_PAGE.format(id=ref), {}))
        return pages[ref]

    out = []

    def climb(ref, start, end, depth, kinds):
        for p in page(ref)["parents"]:
            level = _level(p["types"])
            if level is None:
                continue
            kind = "church" if level in CHURCH_LEVELS else "civil"
            if kind not in kinds:
                continue
            span = _overlap(start, end, p["from"], p["to"])
            if span is None:
                continue
            j = {"level": level, "name": p["names"][0], "from": span[0], "to": span[1],
                 "source": f"gov:{p['ref']}"}
            if p.get("source"):
                j["note"] = p["source"]
            if j not in out:
                out.append(j)
            if level not in TOP and depth + 1 < MAX_DEPTH[kind]:
                try:
                    climb(p["ref"], span[0], span[1], depth + 1, (kind,))
                except NotConsulted as err:
                    notes.append(str(err))
                    return

    try:
        climb(ident, None, None, 0, ("civil", "church"))
        if not any(j["level"] == "parish" for j in out):
            for church in _churches(ident, page, name):
                climb(church, None, None, 0, ("church",))
    except NotConsulted as err:
        notes.append(str(err))
    except Exception as err:  # noqa: BLE001 — a failing gazetteer never stops the guide
        notes.append(f"gov: failed ({type(err).__name__})")
    return out, notes


def _churches(ident, page, name=None):
    """The churches of the place, or of its settlement of the same name, one level down."""
    root = page(ident)
    found = [c["ref"] for c in root["children"] if set(c["types"]) & set(CHURCHES)]
    if found:
        return found
    wanted = key(name) if name else None
    for c in root["children"]:
        if wanted and key(c["name"]) != wanted:
            continue
        found += [x["ref"] for x in page(c["ref"])["children"] if set(x["types"]) & set(CHURCHES)]
        if found:
            break
    return found


# Wikidata


def _time(value):
    """A Wikidata time as a year or a day, after its precision."""
    if not isinstance(value, dict) or not value.get("time"):
        return None
    t = value["time"].lstrip("+")
    return t[:10] if value.get("precision", 11) >= 11 else t[:4]


def _claims(entity, prop):
    return entity.get("claims", {}).get(prop, [])


def _target(claim):
    v = (claim.get("mainsnak") or {}).get("datavalue", {}).get("value")
    return v.get("id") if isinstance(v, dict) else None


def _qualifier(claim, prop):
    for q in claim.get("qualifiers", {}).get(prop, []):
        return _time((q.get("datavalue") or {}).get("value"))
    return None


def _entities(http, ids, props):
    data = json.loads(http.get(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(ids), "props": props,
                                          "languages": "fr|en", "format": "json"}))
    return data.get("entities", {})


def wikidata_item(http, insee):
    """The Wikidata item of the commune with INSEE code ``insee``, or None."""
    data = json.loads(http.get(WIKIDATA, {"action": "query", "list": "search", "srlimit": 3, "format": "json",
                                          "srsearch": f"haswbstatement:P374={insee}"}))
    hits = (data.get("query") or {}).get("search") or []
    return hits[0]["title"] if hits else None


def _label(entity):
    labels = entity.get("labels", {})
    return (labels.get("fr") or labels.get("en") or {}).get("value")


def wikidata_jurisdictions(http, qid=None, insee=None):
    """(jurisdictions, notes): the cantons and the diocese Wikidata gives a French commune."""
    notes = []
    try:
        qid = qid or (wikidata_item(http, insee) if insee else None)
        if not qid:
            return [], ["wikidata: no item for this place"]
        item = _entities(http, [qid], "claims").get(qid, {})
        links = [(c, "canton") for c in _claims(item, "P131")] + [(c, "diocese") for c in _claims(item, "P708")]
        targets = list(dict.fromkeys(t for t in (_target(c) for c, _k in links) if t))
        if not targets:
            return [], notes
        info = _entities(http, targets[:50], "labels|claims")
    except NotConsulted as err:
        return [], [f"wikidata: {err}"]
    except Exception as err:  # noqa: BLE001
        return [], [f"wikidata: failed ({type(err).__name__})"]
    out = []
    for claim, kind in links:
        target = info.get(_target(claim) or "", {})
        label = _label(target)
        if not label:
            continue
        if kind == "canton":
            classes = {_target(c) for c in _claims(target, "P31")}
            if not classes & CANTON_CLASSES:
                continue
            label = re.sub(r"^canton (de la |de l'|du |des |de |d')", "", label)
        else:
            label = re.sub(r"^(archi)?diocèse (de la |de l'|du |des |de |d')", "", label)
        start = _qualifier(claim, "P580") or next((_time((c.get("mainsnak") or {}).get("datavalue", {}).get("value"))
                                                   for c in _claims(target, "P571")), None)
        end = _qualifier(claim, "P582") or next((_time((c.get("mainsnak") or {}).get("datavalue", {}).get("value"))
                                                 for c in _claims(target, "P576")), None)
        j = {"level": kind, "name": label, "from": start, "to": end, "source": f"wikidata:{_target(claim)}"}
        if j not in out:
            out.append(j)
    return out, notes


# France: the rule of 1790 and the catalogue of dioceses (GPS-D9)


def load_dioceses(path=None):
    from probandia import paths
    from probandia.util import yamlio

    path = path or paths.data("catalogues", "dioceses-fr.yaml")
    try:
        return (yamlio.load(path) or {}).get("dioceses", [])
    except OSError:
        return []


def french_church(history, dioceses=None):
    """The parish (rule of 1790) and the dioceses since the Concordat of a French commune,
    from its INSEE history (``Cog.history``)."""
    dioceses = load_dioceses() if dioceses is None else dioceses
    communes = [j for j in history if j["level"] == "commune"]
    if not communes:
        return []
    out = [{"level": "parish", "name": communes[0]["name"], "from": None, "to": "1790",
            "source": "rule:parish-1790", "derived": True,
            "note": "the commune of 1790 follows the parish of the same name; a commune created later "
                    "follows the parish it was cut from"}]
    for dep in (j for j in history if j["level"] == "department"):
        code = (dep.get("note") or "").rsplit(" ", 1)[-1]
        for d in dioceses:
            if str(d.get("department")) != code:
                continue
            span = _overlap(dep["from"], dep["to"], d.get("from"), d.get("to"))
            if span is None:
                continue
            j = {"level": "diocese", "name": d["diocese"], "from": span[0], "to": span[1],
                 "source": "catalogue:dioceses-fr", "derived": True}
            if d.get("note"):
                j["note"] = d["note"]
            if out[-1]["level"] == "diocese" and out[-1]["name"] == j["name"]:
                out[-1]["to"] = j["to"]
            else:
                out.append(j)
    if not any(j["level"] == "diocese" for j in out):
        out[0]["note"] += "; the diocese of this department is not in catalogues/dioceses-fr.yaml"
    return out
