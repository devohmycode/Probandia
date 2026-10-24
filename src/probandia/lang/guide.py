"""A place's locality guide (GPS2-T5): its jurisdictions over time, its repositories,
assembled from the INSEE COG, GOV, Wikidata, the rule of 1790, the catalogue of
dioceses and the catalogue of archives.

The answers of the online gazetteers are kept under ``.probandia/cache/places/``
(GPS-D4): a guide built once is built again without a network call, in any family of
the project; ``--refresh`` asks again.
"""
import copy
import datetime
import hashlib
import os
import urllib.parse

from probandia.i18n import _
from probandia.lang import jurisdictions as J
from probandia.lang.places import key

LEVEL_ORDER = ["parish", "parish-group", "deanery", "diocese", "church-province", "commune", "municipality",
               "canton", "district", "arrondissement", "department", "region", "province", "state", "country",
               "bailliage", "seneschalsy", "generality", "court"]


def cache_folder(project):
    return os.path.join(project, ".probandia", "cache", "places")


class CachedHttp:
    """Answers from the cache first, then from ``inner`` (None: offline). Counts both."""

    def __init__(self, inner, folder=None, refresh=False):
        self.inner, self.folder, self.refresh = inner, folder, refresh
        self.hits = self.calls = 0

    def _path(self, url, params):
        raw = url + "?" + urllib.parse.urlencode(sorted((params or {}).items()))
        return os.path.join(self.folder, hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32] + ".txt")

    def get(self, url, params):
        path = self._path(url, params) if self.folder else None
        if path and not self.refresh and os.path.exists(path):
            self.hits += 1
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        if self.inner is None:
            raise J.NotConsulted(_("{host}: offline, and not in the cache").format(
                host=urllib.parse.urlparse(url).netloc))
        text = self.inner.get(url, params)
        self.calls += 1
        if path and "anubis" not in text.lower():   # a challenge page is never kept
            from probandia.util.fs import atomic_write_bytes

            atomic_write_bytes(path, text.encode("utf-8"))
        return text


def _compatible(a, b):
    return a is None or b is None or a == b


def merge(found):
    """One entry per jurisdiction: the same level and name with compatible dates are one,
    their missing dates filled in; then in the order of LEVEL_ORDER and of their dates."""
    out = []
    for j in found:
        same = next((e for e in out if e["level"] == j["level"] and key(e["name"]) == key(j["name"])
                     and _compatible(e.get("from"), j.get("from")) and _compatible(e.get("to"), j.get("to"))), None)
        if same is None:
            out.append(dict(j))
            continue
        for k in ("from", "to"):
            if same.get(k) is None and j.get(k) is not None:
                same[k] = j[k]
    rank = {lv: n for n, lv in enumerate(LEVEL_ORDER)}
    return sorted(out, key=lambda j: (rank.get(j["level"], len(rank)), j.get("from") or ""))


def departments_of(found):
    """[(code, name)] of the French departments in jurisdictions (``Cog.history``)."""
    out = []
    for j in found:
        if j["level"] == "department" and (j.get("note") or "").startswith("department "):
            pair = (j["note"].split()[-1], j["name"])
            if pair not in out:
                out.append(pair)
    return out


def build(place, cog=None, http=None, window=None, project=None, today=None, context=None):
    """(the place with its jurisdictions, repositories and guide; notes). ``http`` is
    None offline: only the local sources answer."""
    from probandia.archives.coverage import DEPARTMENTS, places_in
    from probandia.archives.repositories import repositories

    place, notes, sources, found = copy.deepcopy(place), [], [], []
    insee = (place.get("insee") or {}).get("code")
    if insee and cog is not None:
        history = cog.history(insee)
        if history:
            found += history
            sources.append("insee-cog")
            church = J.french_church(history)
            found += church
            sources += ["rule:parish-1790"] + (["catalogue:dioceses-fr"] if len(church) > 1 else [])
        else:
            notes.append(_("insee: no commune {code} in the COG files").format(code=insee))
    elif insee:
        notes.append(_("insee: the COG files are not installed (places --update-cog)"))
    if http is None:
        notes.append(_("online gazetteers: not queried (offline)"))
    else:
        if insee:
            got, said = J.wikidata_jurisdictions(http, qid=place.get("wikidata"), insee=insee)
            found += got
            notes += said
            if got:
                sources.append("wikidata")
        gov = place.get("gov")
        if not gov and not insee:
            gov, context = _gov_id(place, http, notes, context)
            if gov:
                place["gov"] = gov
        if gov:
            got, said = J.gov_jurisdictions(gov, http, name=place.get("current_name"))
            found += got
            notes += said
            if got:
                sources.append("gov")
    found = merge(found)
    deps = departments_of(found)
    codes = [f"FR-{c}" for c, _n in deps] + (["FR"] if deps else [])
    if not codes and context:
        codes = places_in(context)
        # A3: the department a gazetteer's label names has its departmental archives
        deps = [(c[3:], DEPARTMENTS[c[3:]]) for c in codes if c.startswith("FR-") and c[3:] in DEPARTMENTS]
        # T261: kept in the jurisdictions too, where the matrix reads the place's country
        found += [{"level": "department", "name": name, "from": None, "to": None, "source": "gazetteer-label",
                   "note": f"department {code}"} for code, name in deps]
        found += [{"level": "country", "name": c, "from": None, "to": None, "source": "gazetteer-label"}
                  for c in codes if len(c) == 2 and not deps]
    repos = repositories(codes, window, None, deps, project) if codes else []
    if repos:
        sources.append("catalogue:archives")
    elif not codes:
        notes.append(_("repositories: the country of the place is not known"))
    place["jurisdictions"] = found
    place["repositories"] = repos
    place["guide"] = {"built": (today or datetime.datetime.now(datetime.UTC).date()).isoformat(), "sources": sources}
    return place, notes


def _gov_id(place, http, notes, context):
    from probandia.lang.places import from_gov

    name = place.get("current_name") or (place.get("names_as_written") or [place["id"]])[0]
    try:
        found = [c for c in from_gov(name, http) if c["score"] == 2]
    except J.NotConsulted as err:
        notes.append(str(err))
        return None, context
    except Exception as err:  # noqa: BLE001
        notes.append(_("{source}: failed ({error})").format(source="gov", error=type(err).__name__))
        return None, context
    if not found:
        return None, context
    return found[0]["codes"]["gov"], context or found[0].get("context")


def copy_guide(place, other_places, family):
    """The place with the guide of the same place in ``other_places`` (another family),
    or None. The same place: the same id, INSEE code or GOV id."""
    insee = (place.get("insee") or {}).get("code")
    for p in other_places:
        same = p["id"] == place["id"] or (insee and (p.get("insee") or {}).get("code") == insee) or (
            place.get("gov") and p.get("gov") == place.get("gov"))
        if same and p.get("jurisdictions"):
            out = copy.deepcopy(place)
            for k in ("jurisdictions", "repositories"):
                out[k] = copy.deepcopy(p.get(k) or [])
            out["guide"] = dict(copy.deepcopy(p.get("guide") or {}), copied_from=family)
            for k in ("insee", "gov", "wikidata", "geonames", "lat", "lon", "current_name", "type"):
                if out.get(k) in (None, "") and p.get(k) not in (None, ""):
                    out[k] = copy.deepcopy(p[k])
            return out
    return None
