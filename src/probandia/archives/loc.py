"""Library of Congress: Chronicling America, American newspapers 1756-1963."""
from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "loc"
HOSTS = ["www.loc.gov"]
COLLECTION = "https://www.loc.gov/collections/chronicling-america/"
OPERATIONS = {
    "search": Operation(doc="American newspaper pages in full text (Chronicling America)",
                        params={"query": str, "from": int, "to": int, "max": int},
                        required=("query",)),
    "page": Operation(doc="one newspaper page of Chronicling America, with its OCR text",
                      params={"url": str}, required=("url",)),
}
WITNESS = {"operation": "search", "args": {"query": "Victor Hugo"}, "expect": {"min_results": 1}}


def run(operation, args, ctx):
    if operation == "search":
        params = {"q": args["query"], "fo": "json", "c": args.get("max", 20)}
        if args.get("from") or args.get("to"):
            params["dates"] = f"{args.get('from', 1756)}/{args.get('to', 1963)}"
        data, resp = ctx.json(COLLECTION, params, archive=ARCHIVE)
        results = data.get("results")
        if results is None:
            raise ConnectorError("loc: no results in the answer", values={"URL": resp.url})
        rows = [{"title": r.get("title", ""), "date": r.get("date"), "url": r.get("url") or r.get("id"),
                 "snippet": " ".join(r.get("description") or [])[:300]} for r in results]
        total = (data.get("pagination") or {}).get("of")
        return OperationResult(rows=rows, count=total, url=resp.url)
    url = args["url"]
    data, resp = ctx.json(url, {"fo": "json"}, archive=ARCHIVE)
    text = data.get("full_text") or ((data.get("page") or [{}])[0] or {}).get("full_text") or ""
    item = data.get("item") or {}
    return OperationResult(text=text, rows=[{"title": item.get("title", ""), "date": item.get("date"),
                                             "url": url}], url=resp.url)
