"""GOV, the historical gazetteer of the Verein für Computergenealogie: old names,
Lorraine, Luxembourg, parishes. It has no JSON API: its HTML pages are read."""
import html
import re

from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "gov"
HOSTS = ["gov.genealogy.net"]
OPERATIONS = {
    "search": Operation(doc="historical places by name, with their GOV id (old names, parishes)",
                        params={"name": str}, required=("name",)),
    "history": Operation(doc="the names and the history of one GOV place", params={"id": str},
                         required=("id",)),
}
WITNESS = {"operation": "search", "args": {"name": "Octeville"}, "expect": {"min_results": 1}}


def _checked(resp):
    """GOV's pages are HTML: the silent-failure detector decides whether they were read."""
    from probandia.reading import detector

    status, _rule = detector.classify(resp.status, resp.body, resp.url, resp.final_url, resp.headers)
    if status not in (detector.OK, detector.EMPTY):
        raise ConnectorError(f"gov: not consulted ({status})", values={"URL": resp.url,
                                                                       "FAILURE": status})
    return resp


def run(operation, args, ctx):
    if operation == "search":
        resp = _checked(ctx.get("https://gov.genealogy.net/search/name", {"name": args["name"]}))
        rows = []
        for m in re.finditer(r'<tr id="([A-Za-z0-9_]+)">(.*?)</tr>', resp.text, re.S):
            ident, body = m.group(1), m.group(2)
            title = re.search(r'<a href="/item/show/[^"]+">([^<]+)</a>', body)
            cells = re.findall(r"<td>([^<]*)</td>", body)
            if title:
                rows.append({"title": html.unescape(title.group(1)), "id": ident,
                             "context": html.unescape(cells[0]) if cells else "",
                             "url": f"https://gov.genealogy.net/item/show/{ident}"})
        return OperationResult(rows=rows, url=resp.url)
    url = f"https://gov.genealogy.net/item/show/{args['id']}"
    resp = _checked(ctx.get(url))
    from probandia.reading.extract import main_text
    return OperationResult(text=main_text(resp.text), url=url)
