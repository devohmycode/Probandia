"""Gallica (BnF): SRU search, ContentSearch, raw text, ALTO, IIIF regions.

Rates (shared with every Gallica call): 5 per minute for raw text and
full-size IIIF; the client applies 5 per minute to the whole host.
"""
import re

from probandia.archives import ConnectorError, Operation, OperationResult
from probandia.archives._util import find_all, first_text, local, save, strip_tags, xml
from probandia.i18n import _

ARCHIVE = "gallica"
HOSTS = ["gallica.bnf.fr"]
BASE = "https://gallica.bnf.fr"
OPERATIONS = {
    "search": Operation(doc="SRU search in Gallica: press issues, books, manuscripts, by words "
                            "and years", params={"query": str, "from": int, "to": int, "type": str,
                                                 "max": int}, required=("query",)),
    "content": Operation(doc="pages of one Gallica document that hold a word (ContentSearch)",
                         params={"ark": str, "query": str}, required=("ark", "query")),
    "text": Operation(doc="raw OCR text of one page of a Gallica document",
                      params={"ark": str, "page": int}, required=("ark", "page")),
    "alto": Operation(doc="ALTO OCR of one page, with the position of each word",
                      params={"ark": str, "page": int}, required=("ark", "page")),
    "image": Operation(doc="IIIF image region of one page of a Gallica document",
                       params={"ark": str, "page": int, "region": str, "width": int},
                       required=("ark", "page")),
}
WITNESS = {"operation": "search", "args": {"query": "Hugo", "type": "fascicule"},
           "expect": {"min_results": 1}}


def ark_id(value):
    m = re.search(r"(?:ark:/12148/)?(bpt6k[a-z0-9]+|btv1b[a-z0-9]+|cb[a-z0-9]+)", value or "")
    if not m:
        raise ConnectorError(_("not a Gallica ARK: {value}").format(value=value))
    return m.group(1)


def run(operation, args, ctx):
    if operation == "search":
        clauses = [f'gallica all "{args["query"]}"']
        if args.get("type"):
            clauses.append(f'dc.type all "{args["type"]}"')
        if args.get("from"):
            clauses.append(f'gallicapublication_date>="{args["from"]}"')
        if args.get("to"):
            clauses.append(f'gallicapublication_date<="{args["to"]}"')
        query = " and ".join(f"({c})" if i == 0 else c for i, c in enumerate(clauses))
        resp = ctx.get(f"{BASE}/SRU", {"operation": "searchRetrieve", "version": "1.2", "query": query,
                                      "maximumRecords": args.get("max", 15)})
        root = xml(resp, ARCHIVE)
        total = first_text(root, "numberOfRecords")
        rows = []
        for rec in find_all(root, "record"):
            ids = [e.text for e in rec.iter() if local(e.tag) == "identifier" and e.text]
            url = next((i for i in ids if "ark:/12148/" in i), None)
            if not url:
                continue
            rows.append({"title": first_text(rec, "title") or "", "date": first_text(rec, "date"),
                         "url": url, "ark": "ark:/12148/" + ark_id(url),
                         "type": first_text(rec, "type")})
        return OperationResult(rows=rows, count=int(total) if total else None, url=resp.url)

    ark = ark_id(args["ark"])
    if operation == "content":
        resp = ctx.get(f"{BASE}/services/ContentSearch", {"ark": ark, "query": args["query"]})
        root = xml(resp, ARCHIVE)
        rows = []
        for item in find_all(root, "item"):
            page = (first_text(item, "p_id") or "").replace("PAG_", "")
            rows.append({"page": int(page) if page.isdigit() else page,
                         "snippet": strip_tags(first_text(item, "content") or ""),
                         "url": f"{BASE}/ark:/12148/{ark}/f{page}.item"})
        count = root.get("countResults")
        return OperationResult(rows=rows, count=int(count) if count else len(rows), url=resp.url)

    page = args["page"]
    if operation == "text":
        from probandia.reading import detector
        from probandia.reading.extract import densest_block

        resp = ctx.get(f"{BASE}/ark:/12148/{ark}/f{page}.texteBrut", api=True)
        status, _rule = detector.classify(resp.status, resp.body, resp.url, None, resp.headers)
        if status == detector.OK:
            return OperationResult(text=densest_block(resp.text), url=resp.url)
        # The raw text page may sit behind a challenge (ALTCHA): the ALTO holds the same OCR.
        alto = run("alto", {"ark": args["ark"], "page": page}, ctx)
        alto.rows = [{"note": f"raw text not consulted ({status}); read from the ALTO"}]
        return alto
    if operation == "alto":
        resp = ctx.get(f"{BASE}/RequestDigitalElement", {"O": ark, "E": "ALTO", "Deb": page})
        root = xml(resp, ARCHIVE)
        lines = []
        for line in find_all(root, "TextLine"):
            words = [s.get("CONTENT", "") for s in line if local(s.tag) == "String"]
            if words:
                lines.append(" ".join(words))
        return OperationResult(text="\n".join(lines), count=len(lines), url=resp.url)
    if operation == "image":
        region = args.get("region", "full")
        width = args.get("width")
        size = f"{width}," if width else "full"
        url = f"{BASE}/iiif/ark:/12148/{ark}/f{page}/{region}/{size}/0/native.jpg"
        resp = ctx.get(url)
        if resp.status != 200:
            raise ConnectorError(_("gallica: HTTP {status}").format(status=resp.status),
                                 values={"URL": url})
        path = save(ctx, "images", f"gallica-{ark}-f{page}-{region.replace(',', '_')}.jpg", resp.body)
        return OperationResult(path=path, url=url)
    raise ConnectorError(_("unknown operation"))
