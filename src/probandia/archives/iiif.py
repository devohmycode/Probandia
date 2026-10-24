"""Any IIIF image server: image information, regions, the views of a manifest, and a sheet of them."""
import re

from probandia.archives import ConnectorError, Operation, OperationResult
from probandia.archives._util import save

ARCHIVE = "iiif"
HOSTS = []  # any IIIF server; the host rate applies per host
SHEET_MAX_VIEWS = 20
OPERATIONS = {
    "info": Operation(doc="size and capabilities of one IIIF image", params={"url": str},
                      required=("url",)),
    "region": Operation(doc="a region of one IIIF image, saved for reading or transcription",
                        params={"url": str, "region": str, "width": int, "rotation": int}, required=("url",)),
    "manifest": Operation(doc="the views of a register (IIIF manifest, version 2 or 3) and their image addresses",
                          params={"url": str}, required=("url",)),
    "sheet": Operation(doc="a sheet of the top bands of views from..to of a manifest, numbered, to find the view",
                       params={"url": str, "from": int, "to": int, "band": float}, required=("url", "from", "to")),
}
WITNESS = {"operation": "info", "args": {"url": "https://iiif.io/api/image/3.0/example/reference/918ecd18c2592080851777620de9bcb5-gottingen"},
           "expect": {"min_results": 1}}


def base(url):
    """The image's base URI, without ``/info.json`` or region parameters."""
    url = url.strip()
    url = re.sub(r"/info\.json$", "", url)
    return re.sub(r"/(full|square|\d+,\d+,\d+,\d+|pct:[^/]+)/[^/]+/!?\d*/(native|default|color|gray|bitonal)\.\w+$",
                  "", url)


def _service_id(service):
    service = service[0] if isinstance(service, list) and service else service
    return (service or {}).get("@id") or (service or {}).get("id") if isinstance(service, dict) else None


def views(manifest):
    """[{view, label, image, width, height}] of a IIIF Presentation manifest, version 2 or 3."""
    out = []
    canvases = ((manifest.get("sequences") or [{}])[0].get("canvases") or []) if "sequences" in manifest \
        else manifest.get("items") or []
    for n, canvas in enumerate(canvases, 1):
        if "images" in canvas:   # version 2
            resource = (canvas["images"] or [{}])[0].get("resource") or {}
        else:                    # version 3: canvas > annotation page > annotation > body
            page = (canvas.get("items") or [{}])[0]
            resource = ((page.get("items") or [{}])[0]).get("body") or {}
        image = _service_id(resource.get("service")) or base(resource.get("@id") or resource.get("id") or "")
        label = canvas.get("label")
        if isinstance(label, dict):   # version 3: {"fr": ["…"]}
            label = next(iter(label.values()), [""])[0] if label else ""
        out.append({"view": n, "label": str(label or n), "image": image.rstrip("/"),
                    "width": canvas.get("width"), "height": canvas.get("height")})
    return out


def run(operation, args, ctx):
    if operation == "manifest":
        data, resp = ctx.json(args["url"], archive=ARCHIVE)
        found = views(data)
        if not found:
            raise ConnectorError("iiif: no view in this manifest", values={"URL": resp.url})
        return OperationResult(rows=found, url=resp.url)
    if operation == "sheet":
        return _sheet(args, ctx)
    b = base(args["url"])
    if operation == "info":
        data, resp = ctx.json(f"{b}/info.json", archive=ARCHIVE)
        if "width" not in data or "height" not in data:
            raise ConnectorError("iiif: no width or height in info.json", values={"URL": resp.url})
        return OperationResult(rows=[{"url": b, "width": data["width"], "height": data["height"],
                                      "profile": data.get("profile")}], url=resp.url)
    from probandia.transcription import region_size

    region = args.get("region", "full")
    rotation = int(args.get("rotation") or 0)
    if rotation not in (0, 90, 180, 270):
        raise ConnectorError("iiif: a rotation is 0, 90, 180 or 270", values={"ROTATION": rotation})
    size = region_size(region, args.get("width"))  # overview 1,500 px; regions within 2,576 px
    quality = "native" if "gallica" in b else "default"
    url = f"{b}/{region}/{size}/{rotation}/{quality}.jpg"
    resp = ctx.get(url)
    if resp.status != 200:
        raise ConnectorError(f"iiif: HTTP {resp.status}", values={"URL": url})
    name = re.sub(r"[^A-Za-z0-9]+", "-", b.split("//", 1)[-1])[-80:]
    turned = f"-r{rotation}" if rotation else ""
    return OperationResult(path=save(ctx, "images", f"{name}-{region.replace(',', '_')}{turned}.jpg", resp.body),
                           url=url)


def _sheet(args, ctx):
    """The server cuts each band (a small region); the engine puts them on one sheet (Pillow)."""
    from probandia import images

    lo, hi = int(args["from"]), int(args["to"])
    if hi < lo or hi - lo + 1 > SHEET_MAX_VIEWS:
        raise ConnectorError(f"iiif: a sheet holds 1 to {SHEET_MAX_VIEWS} views", values={"FROM": lo, "TO": hi})
    images._pil()   # no Pillow: stop before any download
    data, resp = ctx.json(args["url"], archive=ARCHIVE)
    chosen = [v for v in views(data) if lo <= v["view"] <= hi]
    if not chosen:
        raise ConnectorError("iiif: no view in this range", values={"URL": resp.url})
    band = max(0.05, min(1.0, float(args.get("band") or 0.25)))
    paths = []
    for v in chosen:
        url = f"{v['image']}/pct:0,0,100,{round(band * 100)}/660,/0/default.jpg"   # 660 px wide, as ad50 (T73b)
        got = ctx.get(url)
        if got.status != 200:
            raise ConnectorError(f"iiif: HTTP {got.status}", values={"URL": url})
        paths.append(save(ctx, "images", f"band-{v['view']}.jpg", got.body))
    out = save(ctx, "images", f"sheet-{lo}-{hi}.jpg", b"")
    images.sheet(paths, out, 1.0, [v["view"] for v in chosen])
    return OperationResult(path=out, rows=[{"view": v["view"], "label": v["label"]} for v in chosen], url=resp.url)
