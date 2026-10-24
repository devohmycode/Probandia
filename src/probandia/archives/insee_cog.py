"""INSEE COG: the history of French communes since 1943, from the local files
(``places --update-cog`` downloads them). No network."""
import os

from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "insee_cog"
HOSTS = []
OPERATIONS = {
    "commune": Operation(doc="a French commune: its name in a given year, its current name and INSEE code",
                         params={"name": str, "year": int}, required=("name",)),
    "history": Operation(doc="a French commune's history since 1943: mergers, splits, new names and "
                             "departments, with their dates; its canton and arrondissement today",
                         params={"code": str}, required=("code",)),
}
WITNESS = {"operation": "commune", "args": {"name": "Octeville", "year": 1900},
           "expect": {"contains": "Cherbourg-en-Cotentin"}}


def run(operation, args, ctx):
    from probandia.lang.places import Cog, data_dir

    folder = os.path.join(ctx.data_dir or data_dir(ctx.environ), "insee")
    cog = Cog.load(folder)
    if cog is None:
        raise ConnectorError("insee_cog: the COG files are not installed (places --update-cog)")
    if operation == "history":
        rows = [{"title": f"{j['level']} {j['name']}", "level": j["level"], "name": j["name"],
                 "from": j["from"], "to": j["to"], "note": j.get("note")} for j in cog.history(args["code"])]
        return OperationResult(rows=rows)
    rows = [{"title": c["name"], "current": c["current"], "insee": c["codes"].get("insee"),
             "insee_then": c["codes"].get("insee_then")} for c in cog.lookup(args["name"], args.get("year"))]
    return OperationResult(rows=rows)
