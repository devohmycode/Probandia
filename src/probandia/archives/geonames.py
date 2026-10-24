"""GeoNames: places and their coordinates. Needs ``GEONAMES_USERNAME`` (free account)."""
from probandia.archives import ConnectorError, Operation, OperationResult

ARCHIVE = "geonames"
HOSTS = ["api.geonames.org"]
OPERATIONS = {
    "search": Operation(doc="places by name, with coordinates and country (GeoNames)",
                        params={"name": str, "country": str, "max": int}, required=("name",)),
    "get": Operation(doc="one GeoNames place by its id", params={"id": str}, required=("id",)),
}
WITNESS = {"operation": "search", "args": {"name": "Octeville", "country": "FR"},
           "expect": {"min_results": 1}}


def _row(g):
    return {"title": g.get("name") or g.get("toponymName"), "id": str(g.get("geonameId")),
            "country": g.get("countryCode"), "admin": g.get("adminName1"),
            "lat": g.get("lat"), "lon": g.get("lng"),
            "url": f"https://www.geonames.org/{g.get('geonameId')}"}


def run(operation, args, ctx):
    user = ctx.environ.get("GEONAMES_USERNAME")
    if not user:
        raise ConnectorError("geonames: GEONAMES_USERNAME is not set")
    if operation == "search":
        params = {"q": args["name"], "maxRows": args.get("max", 10), "username": user}
        if args.get("country"):
            params["country"] = args["country"]
        data, resp = ctx.json("http://api.geonames.org/searchJSON", params, archive=ARCHIVE)
    else:
        data, resp = ctx.json("http://api.geonames.org/getJSON", {"geonameId": args["id"],
                                                                 "username": user}, archive=ARCHIVE)
    if "status" in data:
        raise ConnectorError("geonames: " + str(data["status"].get("message", ""))[:200],
                             values={"URL": resp.url.replace(user, "USER")})
    items = data.get("geonames") if operation == "search" else [data]
    if items is None:
        raise ConnectorError("geonames: unexpected answer", values={"URL": resp.url})
    return OperationResult(rows=[_row(g) for g in items], count=data.get("totalResultsCount"),
                           url=resp.url.replace(user, "USER"))
