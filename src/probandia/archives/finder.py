"""``archive find "<need>"``: the five operations that best match a need.

The score crosses the words of the need with each operation's description, and
the need's record types, places and years with the coverage of its archive.
"""
import copy
import os
import re

from probandia.archives import connectors
from probandia.archives.coverage import covers, places_in
from probandia import paths
from probandia.lang.places import key
from probandia.util import yamlio

STOP = {"the", "and", "for", "les", "des", "une", "dans", "pour", "with", "von", "der", "die", "das",
        "und", "aux", "sur", "par", "from", "find", "trouver", "chercher", "search"}
# C5: words of any need, never the name of one archive (the "état" of "état civil" is not AGATHA)
COMMON = {"etat", "civil", "civils", "civile", "archive", "archives", "acte", "actes", "registre",
          "registres", "record", "records", "register", "registers", "departementales", "nationales"}
SYNONYMS = {
    "recensement": "census", "census": "census", "volkszahlung": "census", "denombrement": "census",
    "naissance": "birth", "naissances": "birth", "birth": "birth", "births": "birth", "geburt": "birth",
    "bapteme": "baptism", "baptism": "baptism", "taufe": "baptism",
    "mariage": "marriage", "mariages": "marriage", "marriage": "marriage", "heirat": "marriage",
    "deces": "death", "death": "death", "deaths": "death", "sterbefall": "death", "tod": "death",
    "inhumation": "burial", "burial": "burial",
    "journal": "press", "journaux": "press", "presse": "press", "newspaper": "press",
    "newspapers": "press", "zeitung": "press", "gazette": "press",
    "lieu": "place", "lieux": "place", "place": "place", "commune": "place", "village": "place",
    "arbre": "tree", "tree": "tree", "stammbaum": "tree",
    "image": "image", "images": "image", "scan": "image", "acte": "record",
    "livre": "book", "book": "book", "web": "web", "page": "web", "site": "web",
    "militaire": "military", "military": "military", "soldat": "military",
    "deportation": "persecution", "persecution": "persecution",
}


CATALOGUES = ("archives.yaml", "archives-fr-ad.yaml")   # the departmental archives apart (token-economy A2)


def catalogue_paths(project=None, data_root=None):
    """The package's archive catalogues, then the project's own (which wins on an id)."""
    out = [os.path.join(data_root, "catalogues", name) if data_root else paths.data("catalogues", name)
           for name in CATALOGUES]
    return out + ([os.path.join(project, "library", "archives.yaml")] if project else [])


_PARSED = {}   # path -> ((mtime_ns, size), entries): the package's catalogues, parsed once per process


def _entries(path, keep=False):
    """The entries of one catalogue file. ``keep``: a file already parsed and unchanged
    since is not parsed again (about 150 ms each time); the caller gets its own copy."""
    if not keep:
        data = yamlio.load(path) or {}
        return data.get("archives", []) if isinstance(data, dict) else data
    st = os.stat(path)
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _PARSED.get(path)
    if cached is None or cached[0] != stamp:
        cached = _PARSED[path] = (stamp, _entries(path))
    return copy.deepcopy(cached[1])


def load_catalogue(project=None):
    entries = []
    for i, path in enumerate(catalogue_paths(project)):
        if path and os.path.isfile(path):
            # the package's files are parsed once; the project's own, edited by the user, every time
            entries += _entries(path, keep=i < len(CATALOGUES))
    return {e["id"]: e for e in entries}


def words(text):
    return {w for w in key(text).split() if len(w) >= 3 and w not in STOP}


def find(need, project=None, limit=5, place_only=False):
    """[(score, archive, operation, Operation, entry)], best first; and the
    archives without a connector that match (to read in a browser). ``place_only``:
    a browser archive the need does not name must cover a place the need gives."""
    terms = words(need)
    types = {SYNONYMS[w] for w in terms if w in SYNONYMS}
    codes = places_in(need)
    years = [int(y) for y in re.findall(r"\b(1[0-9]{3}|20[0-9]{2})\b", need)]
    cat = load_catalogue(project)
    names = {a: words(f"{a} {e.get('name', '')}") - COMMON for a, e in cat.items()}
    # Only distinctive name words identify an archive; "France" or "archives"
    # alone must still obey the coverage filters.
    named = {a for a, ws in names.items() if any(
        w in terms and sum(w in other for other in names.values()) == 1 for w in ws)}
    scored = []
    for archive, module in connectors(project).items():
        entry = cat.get(archive, {})
        cov = entry.get("coverage") or {}
        base = 0
        if types and set(cov.get("types", [])) & types:
            base += 3
        if codes and covers(cov.get("places", []), codes):
            # C5: the department's own archives before an archive of the whole country
            base += 4 if covers([p for p in cov.get("places", []) if "-" in p], codes) else 2
        elif codes and cov.get("places"):
            base -= 6   # none of the need's places: as good as absent
        if codes and covers(cov.get("absent", []), [c for c in codes if c.startswith("FR-")]):
            base -= 6
        span = cov.get("years")
        if years and span:
            base += 2 if all(span[0] <= y <= span[1] for y in years) else -3
        for name, op in module.OPERATIONS.items():
            doc_words = words(f"{op.doc} {entry.get('name', '')}")
            doc_types = {SYNONYMS.get(w, w) for w in doc_words}
            score = base + 2 * len(terms & doc_words) + 2 * len(types & doc_types)
            scored.append((score, archive, name, op, entry))
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    browser = []
    for archive, entry in cat.items():
        if (entry.get("access") or {}).get("connector"):
            continue
        cov = entry.get("coverage") or {}
        placed = covers(cov.get("places", []), codes) if codes else not place_only
        if archive in named or (not types or set(cov.get("types", [])) & types) and placed \
                and not (codes and covers(cov.get("absent", []), [c for c in codes if c.startswith("FR-")])):
            browser.append(entry)
    # The CLI shows only three browser suggestions: an explicitly named archive
    # must not disappear behind the catalogue's insertion order.
    browser.sort(key=lambda e: -len(terms & words(f"{e['id']} {e.get('name', '')}")))
    return scored[:limit], browser
