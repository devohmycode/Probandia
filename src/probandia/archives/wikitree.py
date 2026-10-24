"""WikiTree: a shared online tree, read only. A lead, never a source."""
from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "wikitree"
HOSTS = ["api.wikitree.com"]
API = "https://api.wikitree.com/api.php"
FIELDS = "Id,Name,FirstName,MiddleName,LastNameAtBirth,LastNameCurrent,BirthDate,DeathDate," \
         "BirthLocation,DeathLocation,Father,Mother"
OPERATIONS = {
    "profile": Operation(doc="one WikiTree profile (online tree, a lead)", params={"key": str},
                         required=("key",)),
    "ancestors": Operation(doc="ancestors of a WikiTree profile", params={"key": str, "depth": int},
                           required=("key",)),
    "descendants": Operation(doc="descendants of a WikiTree profile",
                             params={"key": str, "depth": int}, required=("key",)),
}
WITNESS = {"operation": "profile", "args": {"key": "Lincoln-7"}, "expect": {"contains": "Lincoln"}}


def _row(p):
    name = " ".join(x for x in (p.get("FirstName"), p.get("MiddleName"), p.get("LastNameAtBirth")) if x)
    return {"title": name, "id": p.get("Name"), "birth": p.get("BirthDate"),
            "death": p.get("DeathDate"), "birth_place": p.get("BirthLocation"),
            "url": f"https://www.wikitree.com/wiki/{p.get('Name')}"}


def run(operation, args, ctx):
    if operation == "profile":
        params = {"action": "getProfile", "key": args["key"], "fields": FIELDS}
    else:  # getAncestors and getDescendants are deprecated in favour of getPeople
        params = {"action": "getPeople", "keys": args["key"], operation: args.get("depth", 2),
                  "fields": FIELDS}
    data, resp = ctx.json(API, params, archive=ARCHIVE)
    if not isinstance(data, list) or not data:
        raise ConnectorError("wikitree: unexpected answer", values={"URL": resp.url})
    item = data[0]
    if operation == "profile":
        if item.get("status") not in (0, None, "0", ""):
            raise ConnectorError(f"wikitree: {item.get('status')}", values={"URL": resp.url})
        return OperationResult(rows=[_row(item.get("profile") or {})], url=resp.url)
    people = item.get("people")
    if not isinstance(people, dict):
        raise ConnectorError(f"wikitree: {item.get('status') or 'no people in the answer'}",
                             values={"URL": resp.url})
    start = ((item.get("resultByKey") or {}).get(args["key"]) or {}).get("Id")
    rows = [_row(p) for pid, p in people.items() if p.get("Id") != start]
    return OperationResult(rows=rows, url=resp.url)
