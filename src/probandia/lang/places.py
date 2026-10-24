"""Historical place names: ``places "<name>" [--as-of <year>]``.

Sources, in this order; the lookup stops at the first source that has a place
of exactly that name:

1. the family's ``places.yaml``;
2. the INSEE COG files, read locally (French communes and their history since 1943);
3. GOV, the historical gazetteer (old names, Lorraine, Luxembourg);
4. GeoNames (needs ``GEONAMES_USERNAME``);
5. Nominatim (one request per second, with the engine's User-Agent);
6. Wikidata;
7. the World Historical Gazetteer.

At most 5 candidates come back, each with its name as of the year asked, its
current name, its codes and its coordinates. When the two best candidates are
equally likely, the caller asks the user.
"""
import csv
import html
import json
import os
import re
import unicodedata
import urllib.parse

from probandia.i18n import _

MAX_CANDIDATES = 5
COG_YEAR = 2024
COG_URLS = {
    f"v_commune_{COG_YEAR}.csv": f"https://www.insee.fr/fr/statistiques/fichier/7766585/v_commune_{COG_YEAR}.csv",
    f"v_mvt_commune_{COG_YEAR}.csv": f"https://www.insee.fr/fr/statistiques/fichier/7766585/v_mvt_commune_{COG_YEAR}.csv",
}
# Read when present: older installations have only the two files above.
COG_EXTRA_URLS = {
    f"v_canton_{COG_YEAR}.csv": f"https://www.insee.fr/fr/statistiques/fichier/7766585/v_canton_{COG_YEAR}.csv",
    f"v_arrondissement_{COG_YEAR}.csv": f"https://www.insee.fr/fr/statistiques/fichier/7766585/v_arrondissement_{COG_YEAR}.csv",
}
ABSORBING = {"31", "32", "33", "34"}  # fusions
RECODED = {"41", "50"}  # a new code: another department, or another chief town
CREATED, RESTORED = "20", "21"
# The cantons of the COG are those drawn in 2014, in force since the elections of 22 March 2015.
CANTONS_SINCE = "2015-03-22"


def key(name):
    """A comparable form: no accents, no case, no punctuation."""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _day_before(day):
    import datetime

    return (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat()


def _day_after(day):
    import datetime

    return (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()


# The earlier names of a department code since 1943, each with its last day.
DEPARTMENT_NAMES = {
    "20": [("1975-12-31", "Corse")],
    "04": [("1970-04-12", "Basses-Alpes")],
    "22": [("1990-02-26", "Côtes-du-Nord")],
    "44": [("1957-03-08", "Loire-Inférieure")],
    "64": [("1969-10-09", "Basses-Pyrénées")],
    "75": [("1967-12-31", "Seine")],
    "76": [("1955-01-17", "Seine-Inférieure")],
    "78": [("1967-12-31", "Seine-et-Oise")],
}


def _department_names(dep, current, start, end):
    """[(name, from, to)]: the names department ``dep`` bore between ``start`` and ``end``."""
    out, begin = [], start
    for last, old in DEPARTMENT_NAMES.get(dep, []):
        if begin is not None and begin > last:
            continue
        if end is not None and end <= last:
            return out + [(old, begin, end)]
        out.append((old, begin, last))
        begin = _day_after(last)
    return out + [(current, begin, end)]


def data_dir(environ=None):
    from probandia.paths import user_data_dir

    return user_data_dir(environ)


def candidate(name, source, current=None, codes=None, lat=None, lon=None, exact=False, ident=None):
    return {"name": name, "current": current or name, "source": source, "codes": codes or {},
            "lat": lat, "lon": lon, "score": 2 if exact else 1, "id": ident or f"{source}:{name}"}


# 1. the family


def from_family(name, places, as_of=None):
    out = []
    q = key(name)
    for p in places:
        forms = [p["id"], p.get("current_name") or ""] + list(p.get("names_as_written", []))
        if q in {key(f) for f in forms if f}:
            codes = {k: p.get(k) for k in ("gov", "geonames", "wikidata", "whg") if p.get(k)}
            if p.get("insee"):
                codes["insee"] = p["insee"].get("code")
            out.append(candidate(p.get("current_name") or p["id"], "family", p.get("current_name"),
                                 codes, p.get("lat"), p.get("lon"), True, f"family:{p['id']}"))
    return out


# 2. the INSEE COG


def cog_installed(folder):
    return all(os.path.exists(os.path.join(folder, f)) for f in COG_URLS)


def department_of(insee):
    """``50`` for commune ``50569``, ``971`` for ``97105``."""
    return insee[:3] if insee.startswith("97") else insee[:2]


class Cog:
    """The communes and their changes since 1943, from the INSEE COG files."""

    def __init__(self, folder, year=COG_YEAR):
        self.current = {}   # code -> current name (communes only)
        self.names = {}     # name key -> {codes}
        self.changes = {}   # code -> [(year, row)] where the code changes or disappears
        self.arrivals = {}  # code -> [(year, row)] where a commune takes this code
        self.communes = {}  # code -> its row of v_commune (communes only)
        self.cantons, self.arrondissements = {}, {}
        with open(os.path.join(folder, f"v_commune_{year}.csv"), encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                self.names.setdefault(key(row["LIBELLE"]), set()).add(row["COM"])
                if row["TYPECOM"] == "COM":
                    self.current[row["COM"]] = row["LIBELLE"]
                    self.communes[row["COM"]] = row
        with open(os.path.join(folder, f"v_mvt_commune_{year}.csv"), encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                y = int(row["DATE_EFF"][:4])
                if row["TYPECOM_AV"] == "COM":
                    self.names.setdefault(key(row["LIBELLE_AV"]), set()).add(row["COM_AV"])
                    self.changes.setdefault(row["COM_AV"], []).append((y, row))
                if row["TYPECOM_AP"] == "COM":
                    self.names.setdefault(key(row["LIBELLE_AP"]), set()).add(row["COM_AP"])
                    self.arrivals.setdefault(row["COM_AP"], []).append((y, row))
        for table in (self.changes, self.arrivals):
            for rows in table.values():
                rows.sort(key=lambda yr: (yr[0], yr[1]["DATE_EFF"]))
        for name, target, ident in ((f"v_canton_{year}.csv", self.cantons, "CAN"),
                                    (f"v_arrondissement_{year}.csv", self.arrondissements, "ARR")):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        target[row[ident]] = row["LIBELLE"]

    @classmethod
    def load(cls, folder):
        return cls(folder) if cog_installed(folder) else None

    def absorbed(self, code, until=None):
        """The commune that holds ``code`` at the end of year ``until`` (None: today)."""
        seen = set()
        while code not in seen:
            seen.add(code)
            nxt = None
            for y, row in self.changes.get(code, []):
                if until is not None and y > until:
                    break
                if (row["MOD"] in ABSORBING and row["TYPECOM_AP"] == "COM"
                        and row["COM_AP"] != code):
                    nxt = row["COM_AP"]
                    break
            if nxt is None:
                return code
            code = nxt
        return code

    def name_at(self, code, year):
        """The name a commune had during ``year``."""
        for y, row in self.changes.get(code, []):
            if y > year:
                return row["LIBELLE_AV"]
        return self.current.get(code) or self.changes.get(code, [(0, {"LIBELLE_AP": None})])[-1][1]["LIBELLE_AP"]

    def history(self, code):
        """The jurisdictions the territory of commune ``code`` came under since 1943: each
        commune that held it, by name, then the departments, and today's canton and
        arrondissement. Dates are days (``YYYY-MM-DD``); ``None`` is open or unknown."""
        def ruling(name, start, end, at):
            return {"level": "commune", "name": name, "from": start, "to": end, "source": "insee-cog",
                    "codes": [at]}

        periods = []
        start, cur, name = None, code, None
        origins = [r for _y, r in self.arrivals.get(code, [])
                   if r["MOD"] in (CREATED, RESTORED) and r["COM_AV"] != code]
        if origins:
            r = origins[0]
            periods.append(ruling(r["LIBELLE_AV"], None, _day_before(r["DATE_EFF"]), r["COM_AV"]))
            start, name = r["DATE_EFF"], r["LIBELLE_AP"]
        if name is None:
            first = [r for _y, r in self.changes.get(code, [])]
            name = first[0]["LIBELLE_AV"] if first else self.current.get(code)
        if name is None:
            return []
        seen = {code}
        while True:
            nxt = None
            for _y, r in self.changes.get(cur, []):
                if (start and r["DATE_EFF"] < start) or r["TYPECOM_AP"] != "COM":
                    continue
                if r["COM_AP"] == cur:
                    if r["LIBELLE_AP"] != name:
                        periods.append(ruling(name, start, _day_before(r["DATE_EFF"]), cur))
                        start, name = r["DATE_EFF"], r["LIBELLE_AP"]
                elif r["MOD"] in ABSORBING | RECODED or (r["MOD"] == RESTORED and r["COM_AP"] == code):
                    nxt = r
                    break
            if nxt is None or nxt["COM_AP"] in seen - {code}:
                break
            periods.append(ruling(name, start, _day_before(nxt["DATE_EFF"]), cur))
            start, cur, name = nxt["DATE_EFF"], nxt["COM_AP"], nxt["LIBELLE_AP"]
            seen.add(cur)
        periods.append(ruling(name, start, None, cur))
        departments = self._departments(periods)
        communes = []
        for p in periods:   # a new code under the same name (another department) is the same commune
            if communes and communes[-1]["name"] == p["name"]:
                communes[-1]["to"] = p["to"]
                communes[-1]["codes"] += [c for c in p["codes"] if c not in communes[-1]["codes"]]
            else:
                communes.append(p)
        for p in communes:
            p["note"] = "INSEE " + ", then ".join(p.pop("codes"))
        return communes + departments + self._today(cur)

    def _departments(self, periods):
        from probandia.archives.coverage import DEPARTMENTS

        out = []
        for p in periods:
            at = p["codes"][0]
            dep = at[:3] if at.startswith("97") else at[:2]
            for name, start, end in _department_names(dep, DEPARTMENTS.get(dep, dep), p["from"], p["to"]):
                if out and out[-1]["name"] == name:
                    out[-1]["to"] = end
                else:
                    out.append({"level": "department", "name": name, "from": start, "to": end,
                                "source": "insee-cog", "note": f"department {dep}"})
        return out

    def _today(self, code):
        row = self.communes.get(code)
        if row is None:
            return []
        out = []
        if row.get("CAN") and row["CAN"] in self.cantons:
            out.append({"level": "canton", "name": self.cantons[row["CAN"]], "from": CANTONS_SINCE, "to": None,
                        "source": "insee-cog", "derived": True,
                        "note": f"canton {row['CAN']}, of the map in force since March 2015"})
        if row.get("ARR") and row["ARR"] in self.arrondissements:
            out.append({"level": "arrondissement", "name": self.arrondissements[row["ARR"]], "from": None,
                        "to": None, "source": "insee-cog", "note": f"arrondissement {row['ARR']}"})
        return out

    def lookup(self, name, as_of=None):
        out = []
        for code in sorted(self.names.get(key(name), ())):
            now = self.absorbed(code)
            current = self.current.get(now)
            if current is None:
                continue
            if as_of is not None:
                holder = self.absorbed(code, as_of)
                then = self.name_at(holder, as_of)
            else:
                holder, then = now, current
            out.append(candidate(then, "insee", current, {"insee": now, "insee_then": holder},
                                 exact=True, ident=f"insee:{code}"))
        return out


# 3 to 7. online gazetteers


# Documented APIs and downloads, exempt from robots.txt; GOV's pages are read as pages.
API_HOSTS = {"api.geonames.org", "secure.geonames.org", "nominatim.openstreetmap.org", "www.wikidata.org",
             "whgazetteer.org", "www.insee.fr"}


class Http:
    """``get(url, params) -> text`` over ``util.http.Client``: robots.txt, the rate of each host shared
    between processes (Nominatim: 1 request a second), ``Retry-After``. Tests replace ``get``."""

    def __init__(self, contact="", state_dir=None, config=None, transport=None):
        from probandia.util.http import Client

        self.client = Client(state_dir or data_dir(), contact or None, config, transport)

    def fetch(self, url, params=None):
        """The response of a 2xx answer; NetworkError otherwise."""
        from probandia.errors import NetworkError

        resp = self.client.get(url + ("?" + urllib.parse.urlencode(params) if params else ""),
                               api=urllib.parse.urlsplit(url).netloc in API_HOSTS)
        if not 200 <= resp.status < 300:
            raise NetworkError(_("{url} answered {status}").format(url=url, status=resp.status),
                               values={"URL": url})
        return resp

    def get(self, url, params):
        return self.fetch(url, params).text


def from_gov(name, http):
    text = http.get("https://gov.genealogy.net/search/name", {"name": name})
    out = []
    for m in re.finditer(r'<tr id="([A-Za-z0-9_]+)">(.*?)</tr>', text, re.S):
        ident, body = m.group(1), m.group(2)
        title = re.search(r'<a href="/item/show/[^"]+">([^<]+)</a>', body)
        cells = re.findall(r"<td>([^<]*)</td>", body)
        if not title:
            continue
        label = html.unescape(title.group(1))
        out.append(candidate(label, "gov", label, {"gov": ident}, exact=key(label) == key(name),
                             ident=f"gov:{ident}"))
        if cells:
            out[-1]["context"] = html.unescape(cells[0])
    return out


def from_geonames(name, http, username):
    data = json.loads(http.get("http://api.geonames.org/searchJSON",
                               {"q": name, "maxRows": MAX_CANDIDATES, "username": username}))
    return [candidate(g["name"], "geonames", g["name"], {"geonames": str(g["geonameId"])},
                      float(g["lat"]), float(g["lng"]), key(g["name"]) == key(name),
                      f"geonames:{g['geonameId']}") for g in data.get("geonames", [])]


def from_nominatim(name, http):
    data = json.loads(http.get("https://nominatim.openstreetmap.org/search",
                               {"q": name, "format": "jsonv2", "limit": MAX_CANDIDATES}))
    out = []
    for p in data:
        label = p.get("name") or p["display_name"].split(",")[0]
        c = candidate(label, "nominatim", label, {"osm": f"{p.get('osm_type')}/{p.get('osm_id')}"},
                      float(p["lat"]), float(p["lon"]), key(label) == key(name),
                      f"osm:{p.get('osm_type')}/{p.get('osm_id')}")
        c["context"] = p.get("display_name")
        out.append(c)
    return out


def from_wikidata(name, http):
    data = json.loads(http.get("https://www.wikidata.org/w/api.php", {
        "action": "wbsearchentities", "search": name, "language": "fr", "format": "json",
        "type": "item", "limit": MAX_CANDIDATES}))
    out = []
    for item in data.get("search", []):
        label = item.get("label") or item["id"]
        c = candidate(label, "wikidata", label, {"wikidata": item["id"]},
                      exact=key(label) == key(name), ident=f"wikidata:{item['id']}")
        c["context"] = item.get("description")
        out.append(c)
    return out


def from_whg(name, http):
    data = json.loads(http.get("https://whgazetteer.org/api/index/", {"name": name}))
    out = []
    for f in data.get("features", []):
        props = f.get("properties", {})
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        label = props.get("title", "")
        out.append(candidate(label, "whg", label, {"whg": str(props.get("place_id"))},
                             coords[1], coords[0], key(label) == key(name),
                             f"whg:{props.get('place_id')}"))
    return out


def lookup(name, as_of=None, family_places=(), cog=None, http=None, environ=None, offline=False):
    """(candidates, notes). ``notes`` say which sources were skipped, and why."""
    environ = os.environ if environ is None else environ
    notes, found = [], []

    def add(items):
        for c in items:
            if c["id"] not in {x["id"] for x in found}:
                found.append(c)
        return any(c["score"] == 2 for c in items)

    if add(from_family(name, family_places, as_of)):
        return rank(found), notes
    if cog is None:
        notes.append(_("insee: the COG files are not installed (places --update-cog)"))
    elif add(cog.lookup(name, as_of)):
        return rank(found), notes
    if offline or http is None:
        notes.append(_("online gazetteers: not queried (offline)"))
        return rank(found), notes
    sources = [("gov", lambda: from_gov(name, http))]
    if environ.get("GEONAMES_USERNAME"):
        sources.append(("geonames", lambda: from_geonames(name, http, environ["GEONAMES_USERNAME"])))
    else:
        notes.append(_("geonames: GEONAMES_USERNAME is not set"))
    sources += [("nominatim", lambda: from_nominatim(name, http)),
                ("wikidata", lambda: from_wikidata(name, http)),
                ("whg", lambda: from_whg(name, http))]
    for source, fetch in sources:
        try:
            if add(fetch()):
                break
        except Exception as err:  # one failing gazetteer does not stop the others
            notes.append(_("{source}: failed ({error})").format(source=source, error=type(err).__name__))
    return rank(found), notes


def rank(found):
    return sorted(found, key=lambda c: -c["score"])[:MAX_CANDIDATES]


def ambiguous(candidates):
    """True when the two best candidates are equally likely and not the same place."""
    if len(candidates) < 2:
        return False
    a, b = candidates[0], candidates[1]
    same = a["codes"].get("insee") and a["codes"].get("insee") == b["codes"].get("insee") \
        and a["name"] == b["name"]
    return a["score"] == b["score"] == 2 and not same


def update_cog(folder, http=None):
    """Downloads the COG files into ``folder``. Returns the paths written."""
    from probandia.util.fs import atomic_write_bytes

    os.makedirs(folder, exist_ok=True)
    written = []
    for name, url in {**COG_URLS, **COG_EXTRA_URLS}.items():
        atomic_write_bytes(os.path.join(folder, name), (http or Http()).fetch(url).body)
        written.append(os.path.join(folder, name))
    return written
