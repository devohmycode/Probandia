"""Open Archives (openarchieven.nl): indexed civil and church records of the
Netherlands and Belgium, and some of France and Germany."""
from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "openarchives"
HOSTS = ["api.openarch.nl"]
API = "https://api.openarch.nl/1.1/records"
OPERATIONS = {
    "search": Operation(doc="indexed births, marriages, deaths and other records by name, place and "
                            "period (Netherlands, Belgium)",
                        params={"name": str, "place": str, "type": str, "from": int, "to": int,
                                "max": int}, required=("name",)),
    "record": Operation(doc="one record of Open Archives, with every person and its source",
                        params={"archive": str, "identifier": str}, required=("archive", "identifier")),
}
WITNESS = {"operation": "search", "args": {"name": "Hugo"}, "expect": {"min_results": 1}}


def _date(d):
    if not isinstance(d, dict) or not d.get("year"):
        return None
    parts = [f"{d['year']:04d}"]
    if d.get("month"):
        parts.append(f"{d['month']:02d}")
        if d.get("day"):
            parts.append(f"{d['day']:02d}")
    return "-".join(parts)


def run(operation, args, ctx):
    if operation == "search":
        params = {"name": args["name"], "number_show": args.get("max", 25), "lang": "en"}
        if args.get("place"):
            params["eventplace"] = args["place"]
        if args.get("type"):
            params["eventtype"] = args["type"]
        data, resp = ctx.json(f"{API}/search.json", params, archive=ARCHIVE)
        docs = (data.get("response") or {}).get("docs")
        if docs is None:
            raise ConnectorError("openarchives: no docs in the answer", values={"URL": resp.url})
        rows = []
        for d in docs:
            date = _date(d.get("eventdate"))
            year = int(date[:4]) if date else None
            if year and ((args.get("from") and year < args["from"]) or (args.get("to") and year > args["to"])):
                continue
            rows.append({"title": d.get("personname", ""), "type": d.get("eventtype"),
                         "date": date, "place": ", ".join(d.get("eventplace") or []),
                         "archive": d.get("archive_code"), "identifier": d.get("identifier"),
                         "role": d.get("relationtype"),
                         "url": f"https://www.openarchieven.nl/{d.get('archive_code')}:{d.get('identifier')}"})
        return OperationResult(rows=rows, count=(data.get("response") or {}).get("number_found"),
                               url=resp.url)
    data, resp = ctx.json(f"{API}/show.json", {"archive": args["archive"],
                                               "identifier": args["identifier"], "lang": "en"},
                          archive=ARCHIVE)
    return OperationResult(rows=[data] if data else [], url=resp.url)
