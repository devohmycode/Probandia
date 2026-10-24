"""DDB v2 public search API. Metadata is CC0; object rights remain separate."""
from urllib.parse import quote

from probandia.archives import ConnectorError, Operation, OperationResult
from probandia.errors import UsageError
from probandia.i18n import _

ARCHIVE = "ddb"
HOSTS = ["api.deutsche-digitale-bibliothek.de"]
API = "https://api.deutsche-digitale-bibliothek.de/2/search/index/search/select"
OPERATIONS = {
    "search": Operation(doc="German archives, newspapers, books and cultural heritage metadata (DDB)",
                        params={"query": str, "max": int, "offset": int}, required=("query",)),
}
WITNESS = {"operation": "search", "args": {"query": "Goethe", "max": 1},
           "expect": {"min_results": 1, "contains": "Goethe"}}


def _first(value):
    return value[0] if isinstance(value, list) and value else value if isinstance(value, str) else None


def run(operation, args, ctx):
    size, offset = args.get("max", 20), args.get("offset", 0)
    if not isinstance(args["query"], str) or not args["query"].strip() or not 1 <= size <= 100 or offset < 0:
        raise UsageError(_("ddb: query must be non-empty, max between 1 and 100, offset non-negative"))
    data, resp = ctx.json(API, {"q": args["query"], "rows": size, "start": offset, "wt": "json"},
                          archive=ARCHIVE)
    response = data.get("response") if isinstance(data, dict) else None
    docs = response.get("docs") if isinstance(response, dict) else None
    count = response.get("numFound") if isinstance(response, dict) else None
    header = data.get("responseHeader", {}) if isinstance(data, dict) else {}
    if not isinstance(docs, list) or type(count) is not int or count < len(docs) or \
            not isinstance(header, dict) or header.get("status", 0) != 0 or \
            (count == 0 and response.get("numFoundExact") is False) or any(
            not isinstance(doc, dict) or not isinstance(doc.get("id"), str) or not doc["id"]
            for doc in docs):
        raise ConnectorError(_("ddb: unexpected search response"), values={"URL": resp.url})
    rows = [{"id": doc["id"], "title": _first(doc.get("title")) or _first(doc.get("label")) or "",
             "url": "https://www.deutsche-digitale-bibliothek.de/item/" + quote(doc["id"], safe=""),
             "provider": _first(doc.get("provider_fct")), "place": _first(doc.get("place_fct")),
             "snippet": _first(doc.get("description")) or _first(doc.get("preview")),
             "rights": doc.get("license") or []} for doc in docs[:size]]
    return OperationResult(rows=rows, count=count, url=resp.url)
