"""Archives départementales de la Manche (Arkothèque): the parish and civil registers of a commune,
one view of a register, saved as a file (token-economy A4) or as the act alone cut from it (T73c), and a sheet
of its views (T73).

The site answers the engine's own identity once the cookie of its first, plain redirect page is
replayed (decision A1, in the HTTP client). The search is the one the site's page sends:
``/_recherche-api/search/11`` with the engine-prefixed parameters, the commune in the filter
"Commune ou paroisse". robots.txt applies to every request (it disallows ``/_arkotheque/`` only).
"""
import html
import io
import json
import os
import re

from probandia.archives import ConnectorError, Operation, OperationResult
from probandia.archives._util import save
from probandia.util.fs import atomic_write_json

ARCHIVE = "ad50"
BASE = "https://www.archives-manche.fr"
HOSTS = ["www.archives-manche.fr"]
ENGINE = "arko_default_635b873d1f4a7"          # the search engine "Registres paroissiaux et d'état civil"
COMMUNE_FILTER = "arko_default_635fe0c23fd4c"  # its filter "Commune ou paroisse"
RESTITUTION = "arko_default_635b8783b6c86"     # the table of results
OPERATIONS = {
    "registers": Operation(doc="the parish and civil registers of a commune of the Manche: cote, act types, "
                               "years and detail of each", params={
                               "commune": str, "type": str, "from": int, "to": int}, required=("commune",)),
    "view": Operation(doc="one view of a register of the Manche, saved as an image file: \"size\": 900 to find "
                          "the act; \"region\": x,y,w,h as seen at that size, the act alone cut from the whole view; "
                          "without view, the number of its views",
                      params={"detail": int, "view": int, "viewer": str, "size": int, "region": str},
                      required=("detail",)),
    "sheet": Operation(doc="a sheet of the top bands of views from..to of a register of the Manche, numbered, "
                           "to find the view",
                       params={"detail": int, "from": int, "to": int, "band": float},
                       required=("detail", "from", "to")),
}
SHEET_MAX_VIEWS = 20   # as iiif.sheet
SHEET_PX = 660         # each view of a sheet, as "size": 660: an act's number, name in the margin and first line
                       # stay legible on its band, at two thirds of the pixels of 800 (T73b)
WITNESS = {"operation": "registers", "args": {"commune": "Octeville"}, "expect": {"min_results": 20}}
TYPES = {"birth": "naissances", "marriage": "mariages", "death": "décès", "baptism": "baptêmes",
         "burial": "sépultures", "decennial_tables": "table décennale", "tables": "table décennale"}


def registers(text):
    """The rows of the results table: one register each."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        detail = re.search(r'data-detail="(\d+)"', row)
        if not detail:
            continue
        found = {}
        for champ, value in re.findall(r'data-champ="([^"]+)"[^>]*>(.*?)</span>', row, re.S):
            found.setdefault(champ, []).append(html.unescape(re.sub(r"\s+", " ", value)).strip())
        cells = {k: ", ".join(v) for k, v in found.items()}
        years = [int(y) for y in re.findall(r"\b(1[0-9]{3})\b", cells.get("date", ""))]
        viewer = re.search(r'data-visionneuse-url="([^"]+)"', row)
        out.append({"detail": int(detail.group(1)), "cote": cells.get("cote_tableau", ""),
                    "commune": cells.get("geogname", ""), "types": cells.get("type_acte", ""),
                    "from": min(years) if years else None, "to": max(years) if years else None,
                    "viewer": html.unescape(viewer.group(1)) if viewer else None})
    return out


def run(operation, args, ctx):
    if operation == "registers":
        return _registers(args, ctx)
    return _sheet(args, ctx) if operation == "sheet" else _view(args, ctx)


def _get(ctx, path):
    resp = ctx.get(BASE + path, api=False)
    if resp.status != 200:
        raise ConnectorError(f"ad50: HTTP {resp.status}", values={"HTTP": resp.status, "URL": resp.url})
    return resp


def _registers(args, ctx):
    e = f"{ENGINE}--"
    group = f"{e}filtreGroupes[groupes][0][{COMMUNE_FILTER}]"
    params = [(f"{e}filtreGroupes[mode]", "simple"), (f"{e}filtreGroupes[op]", "AND"), (f"{group}[op]", "AND"),
              (f"{group}[q][]", args["commune"]), (f"{group}[extras][mode]", "popup"),
              (f"{e}from", 0), (f"{e}resultSize", 100), (f"{e}modeRestit", RESTITUTION)]
    import urllib.parse

    resp = _get(ctx, "/_recherche-api/search/11?" + urllib.parse.urlencode(params))
    try:
        data = json.loads(resp.text)
    except ValueError:
        raise ConnectorError("ad50: the search did not answer JSON", values={"URL": resp.url}) from None
    if data.get("total", 0) > 1000:   # the filter was not applied: never a whole collection
        raise ConnectorError("ad50: the commune filter was not applied", values={"COMMUNE": args["commune"]})
    rows = registers(data.get("html") or "")
    kind = TYPES.get((args.get("type") or "").lower(), (args.get("type") or "").lower())
    lo, hi = args.get("from"), args.get("to")
    rows = [r for r in rows if (not kind or kind in r["types"].lower())
            and (lo is None or r["to"] is None or r["to"] >= lo) and (hi is None or r["from"] is None or r["from"] <= hi)]
    _keep_viewers(ctx, {r["detail"]: r.pop("viewer") for r in rows if r.get("viewer")})
    return OperationResult(rows=rows, count=data.get("total"), url=resp.url)


def _viewers_file(ctx):
    """Where each register's viewer address is kept: a row leaves it out, 120 characters that an
    agent only copied back into ``view`` (token-economy J1)."""
    if ctx.project:
        return os.path.join(ctx.project, ".probandia", "cache", "ad50-viewers.json")
    return os.path.join(ctx.work, "ad50-viewers.json") if ctx.work else None


def _viewers(ctx):
    path = _viewers_file(ctx)
    try:
        with open(path, encoding="utf-8") as fh:
            kept = json.load(fh)
        return kept if isinstance(kept, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _keep_viewers(ctx, found):
    path = _viewers_file(ctx)
    if not (found and path):
        return
    kept = _viewers(ctx)
    kept.update({str(detail): viewer for detail, viewer in found.items()})
    try:
        atomic_write_json(path, kept)
    except OSError:
        pass   # without it, the view reads the register's page


def _sources(detail, args, ctx):
    """The address of a register's views, and their sources (``/_recherche-images/show/…``)."""
    viewer = args.get("viewer") or _viewers(ctx).get(str(detail))
    if not viewer:   # the register's page holds the address of its views
        page = _get(ctx, f"/recherche/registres-paroissiaux-et-detat-civil?detail={detail}").text
        m = re.search(r"(/_recherche-api/visionneuse-infos/[^\"'\s<>&]+)", page) or \
            re.search(r"visionneuse-infos/([^\"'\s<>&]+)", page)
        if not m:
            raise ConnectorError("ad50: no view on this register's page", values={"DETAIL": detail})
        viewer = m.group(1) if m.group(1).startswith("/") else "/_recherche-api/visionneuse-infos/" + m.group(1)
        _keep_viewers(ctx, {detail: viewer})
    infos = json.loads(_get(ctx, viewer).text)
    return viewer, (infos.get("medias") or [{}])[0].get("sources") or []


def _view(args, ctx):
    """One view, saved; without ``view``, the number of the register's views and no image (token-economy
    J8: readers fetched view 1, 3,600 tokens once read, only to learn it). With ``region``, only the act
    (T73c: readers fetched whole views and cut half pages, 1,500 to 2,250 tokens each, to look for it)."""
    from probandia import images

    detail, size, region = int(args["detail"]), args.get("size"), args.get("region")
    if region and args.get("view") is not None:
        images._pil()   # no Pillow: stop before any download
    viewer, sources = _sources(detail, args, ctx)
    if args.get("view") is None:
        return OperationResult(rows=[{"detail": detail, "views": len(sources)}], url=BASE + viewer)
    n = int(args["view"])
    if not 1 <= n <= len(sources):
        raise ConnectorError(f"ad50: the register has {len(sources)} views", values={"VIEWS": len(sources)})
    show = sources[n - 1]["src"]   # /_recherche-images/show/<detail>/image/<valeurId>/<index>
    url = f"{show}?size=!{int(size)},{int(size)}" if size and not region else \
        show.replace("/_recherche-images/show/", "/_recherche-images/download/", 1)
    image = _get(ctx, url)
    row = {"detail": detail, "view": n, "views": len(sources), "url": BASE + url}
    if region:   # T73c: the act alone at full size; the whole view stays in memory, never read nor on disk
        path = save(ctx, "images", f"ad50-{detail}-{n:04d}-{re.sub(r'[^0-9.]+', '_', region)}.jpg", None)
        row["region"] = images.crop(io.BytesIO(image.body), path, region, seen=size)["REGION"]
    else:
        path = save(ctx, "images", f"ad50-{detail}-{n:04d}.jpg", image.body)
        images.mark_small(ctx.project, path, bool(size) and int(size) < images.READ_MIN_PX)   # J10: never transcribed
    return OperationResult(rows=[row], path=path, url=BASE + url)


def _sheet(args, ctx):
    """The views from..to fetched small, their top bands on one numbered sheet (Pillow), as iiif.sheet: one
    image to find the act, where a reader paid a Bash and a Read for each view (T73)."""
    from probandia import images

    detail, lo, hi = int(args["detail"]), int(args["from"]), int(args["to"])
    if not 1 <= lo <= hi < lo + SHEET_MAX_VIEWS:
        raise ConnectorError(f"ad50: a sheet holds 1 to {SHEET_MAX_VIEWS} views, from view 1",
                             values={"FROM": lo, "TO": hi})
    images._pil()   # no Pillow: stop before any download
    viewer, sources = _sources(detail, args, ctx)
    if hi > len(sources):
        raise ConnectorError(f"ad50: the register has {len(sources)} views", values={"VIEWS": len(sources)})
    # T73b: the small views stay in memory, never on disk: no reader reads them, no view saved whole is saved over
    small = [io.BytesIO(_get(ctx, f"{sources[n - 1]['src']}?size=!{SHEET_PX},{SHEET_PX}").body)
             for n in range(lo, hi + 1)]
    out = save(ctx, "images", f"ad50-{detail}-sheet-{lo}-{hi}.jpg", b"")
    images.sheet(small, out, max(0.05, min(1.0, float(args.get("band") or 0.25))), list(range(lo, hi + 1)))
    images.mark_small(ctx.project, out)   # J10: a sheet finds the act, never transcribed
    return OperationResult(rows=[{"detail": detail, "from": lo, "to": hi, "views": len(sources)}], path=out,
                           url=BASE + viewer)
