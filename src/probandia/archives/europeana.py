"""Europeana: texts and newspapers from European libraries. A key is required;
``EUROPEANA_API_KEY``, otherwise the public demonstration key."""
from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "europeana"
HOSTS = ["api.europeana.eu"]
OPERATIONS = {
    "search": Operation(doc="European newspapers and texts in full text (Europeana)",
                        params={"query": str, "from": int, "to": int, "max": int},
                        required=("query",)),
}
WITNESS = {"operation": "search", "args": {"query": "Luxembourg"}, "expect": {"min_results": 1}}


def run(operation, args, ctx):
    key = ctx.environ.get("EUROPEANA_API_KEY") or "api2demo"
    params = {"wskey": key, "query": args["query"], "rows": args.get("max", 20), "qf": ["TYPE:TEXT"]}
    if args.get("from") or args.get("to"):
        params["qf"].append(f"YEAR:[{args.get('from', '*')} TO {args.get('to', '*')}]")
    data, resp = ctx.json("https://api.europeana.eu/record/v2/search.json", params, archive=ARCHIVE)
    if not data.get("success") or "items" not in data:
        raise ConnectorError("europeana: " + str(data.get("error", "unexpected answer"))[:200],
                             values={"URL": resp.url.replace(key, "KEY")})
    rows = []
    for it in data["items"]:
        title = (it.get("title") or [""])[0]
        rows.append({"title": title, "date": (it.get("year") or [None])[0],
                     "provider": (it.get("dataProvider") or [None])[0],
                     "url": it.get("guid") or (it.get("edmIsShownAt") or [None])[0]})
    return OperationResult(rows=rows, count=data.get("totalResults"), url=resp.url.replace(key, "KEY"))
