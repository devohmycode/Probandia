"""Where a place's records are kept (GPS2-T4): the archives of ``catalogues/archives.yaml``
whose coverage crosses the place, the window and the types asked, and the departmental
archives of each department the place belonged to, with or without a connector."""
from probandia.archives.coverage import DEPARTMENTS, covers

# Sources that hold no record of a person: gazetteers, trees, web pages, image servers.
NOT_RECORDS = {"place", "tree", "web", "image"}


def _span(years, window):
    a, b = years
    if window:
        lo, hi = window
        a, b = max(a, lo) if lo is not None else a, min(b, hi) if hi is not None else b
    return [a, b] if a <= b else None


def _holdings(entry, window, types):
    cov = entry.get("coverage") or {}
    span = _span(cov["years"], window) if cov.get("years") else None
    if cov.get("years") and span is None:
        return None
    kinds = [t for t in cov.get("types", []) if t not in NOT_RECORDS and (not types or t in types)]
    if not kinds:
        return None
    return [dict({"type": t}, **({"years": span} if span else {})) for t in kinds]


CIVIL_REGISTERS_FROM = 1793   # the civil registers of France begin in the last months of 1792


def first_step(window=None):
    """Where to look first in a French department's archives (token-economy A3): the decennial
    tables, ten years of a commune on one page, then the register of the year; before 1793 the
    parish registers."""
    lo, hi = window or (None, None)
    steps = []
    if hi is None or hi >= CIVIL_REGISTERS_FROM:
        steps.append("decennial tables of the commune first (ten years of births, marriages and deaths "
                      "on one page), then the register of the year")
    if lo is None or lo < CIVIL_REGISTERS_FROM:
        steps.append("before 1793, the parish registers (baptisms, marriages, burials), year by year")
    return "; ".join(steps)


def repositories(codes, window=None, types=None, departments=(), project=None, catalogue=None):
    """[repository] for a place given as ISO codes (``FR-56``, ``FR``, ``DE``), a window
    (from, to) and source types (none: all). ``departments`` are the place's French
    departments, as ``[(code, name)]``: each has its departmental archives, from the
    catalogue when it is there (``ad56``), else by name, its holdings to be checked."""
    from probandia.archives.finder import load_catalogue

    cat = catalogue if catalogue is not None else load_catalogue(project)
    out, seen = [], set()
    for code, name in departments:
        entry = cat.get(f"ad{code.lower()}")
        repo = {"name": entry["name"] if entry else f"Archives départementales ({name or DEPARTMENTS.get(code, code)})",
                "archive": entry["id"] if entry else None, "source": "catalogue:archives" if entry else
                "rule:departmental-archives"}
        if entry:
            repo["holdings"] = _holdings(entry, window, types) or []
            hosts = (entry.get("access") or {}).get("hosts") or []
            if hosts:
                repo["url"] = f"https://{hosts[0]}/"
            repo["note"] = first_step(window)
            seen.add(entry["id"])
        else:
            repo["holdings"] = []
            repo["note"] = "no entry in catalogues/archives.yaml: check its finding aids for the parish and civil registers"
        if repo["name"] not in {r["name"] for r in out}:
            out.append(repo)
    for archive, entry in sorted(cat.items()):
        if archive in seen:
            continue
        cov = entry.get("coverage") or {}
        if not codes or not covers(cov.get("places", []), codes):
            continue
        if covers(cov.get("absent", []), [c for c in codes if c.startswith("FR-")]):
            continue
        holdings = _holdings(entry, window, types)
        if holdings is None:
            continue
        repo = {"name": entry.get("name", archive), "archive": archive, "holdings": holdings,
                "source": "catalogue:archives"}
        if not (entry.get("access") or {}).get("connector"):
            repo["note"] = "read in a browser"
        out.append(repo)
    return out
