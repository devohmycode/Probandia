"""Internet Archive Wayback Machine: captures (CDX), raw captures, and Save Page Now.

Save Page Now is used only for a page cited as a source. ``IA_ACCESS_KEY`` and
``IA_SECRET_KEY`` are optional; anonymous limits are lower.
"""
import json
import urllib.parse

from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "wayback"
HOSTS = ["web.archive.org"]
OPERATIONS = {
    "cdx": Operation(doc="captures of a web page in the Wayback Machine (web archives)",
                     params={"url": str, "from": int, "to": int, "max": int}, required=("url",)),
    "raw": Operation(doc="one raw capture of a web page, as archived", params={"url": str,
                     "timestamp": str}, required=("url", "timestamp")),
    "save": Operation(doc="archive a cited page now (Save Page Now)", params={"url": str},
                      required=("url",)),
}
WITNESS = {"operation": "cdx", "args": {"url": "gallica.bnf.fr/", "max": 3}, "expect": {"min_results": 1}}


def run(operation, args, ctx):
    if operation == "cdx":
        params = {"url": args["url"], "output": "json", "filter": "statuscode:200",
                  "limit": args.get("max", 10)}
        if args.get("from"):
            params["from"] = str(args["from"])
        if args.get("to"):
            params["to"] = str(args["to"])
        data, resp = ctx.json("https://web.archive.org/cdx/search/cdx", params, archive=ARCHIVE)
        if not isinstance(data, list):
            raise ConnectorError("wayback: unexpected CDX answer", values={"URL": resp.url})
        if not data:
            return OperationResult(rows=[], url=resp.url)
        header = data[0]
        rows = []
        for line in data[1:]:
            rec = dict(zip(header, line))
            rows.append({"timestamp": rec.get("timestamp"), "status": rec.get("statuscode"),
                         "original": rec.get("original"),
                         "url": f"https://web.archive.org/web/{rec.get('timestamp')}/{rec.get('original')}"})
        return OperationResult(rows=rows, url=resp.url)
    if operation == "raw":
        url = f"https://web.archive.org/web/{args['timestamp']}id_/{args['url']}"
        resp = ctx.get(url)
        if resp.status != 200:
            raise ConnectorError(f"wayback: HTTP {resp.status}", values={"URL": url})
        from probandia.reading.extract import extract
        text, _how = extract(resp.text)
        return OperationResult(text=text, url=url)
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    if ctx.environ.get("IA_ACCESS_KEY") and ctx.environ.get("IA_SECRET_KEY"):
        headers["Authorization"] = f"LOW {ctx.environ['IA_ACCESS_KEY']}:{ctx.environ['IA_SECRET_KEY']}"
    body = urllib.parse.urlencode({"url": args["url"]}).encode()
    resp = ctx.client.request("POST", "https://web.archive.org/save", headers=headers, body=body,
                              api=True)
    if resp.status not in (200, 201):
        raise ConnectorError(f"wayback: Save Page Now answered HTTP {resp.status}",
                             values={"URL": args["url"]})
    try:
        info = json.loads(resp.text)
    except ValueError:
        info = {}
    return OperationResult(rows=[{"url": args["url"], "job_id": info.get("job_id")}], url=args["url"])
