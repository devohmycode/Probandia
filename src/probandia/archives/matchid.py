"""matchID: French deaths since 1970 (INSEE files), with names, places and dates."""
from probandia.archives import Operation, OperationResult

ARCHIVE = "matchid"
HOSTS = ["deces.matchid.io"]
OPERATIONS = {
    "search": Operation(doc="French death records since 1970: name, places and dates of birth and death",
                        params={"name": str, "first": str, "birth_date": str, "birth_place": str,
                                "death_date": str, "death_place": str, "max": int},
                        required=("name",)),
}
WITNESS = {"operation": "search", "args": {"name": "Hugo"}, "expect": {"min_results": 1}}


def _date(value):
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if value and len(value) == 8 else value


def run(operation, args, ctx):
    params = {"q": " ".join(v for v in (args.get("first"), args["name"]) if v),
              "size": args.get("max", 20)}
    for key, name in (("birth_date", "birthDate"), ("birth_place", "birthCity"),
                      ("death_date", "deathDate"), ("death_place", "deathCity")):
        if args.get(key):
            params[name] = args[key]
    data, resp = ctx.json("https://deces.matchid.io/deces/api/v1/search", params, archive=ARCHIVE)
    persons = (data.get("response") or {}).get("persons")
    if persons is None:
        from probandia.archives import ConnectorError
        raise ConnectorError("matchid: no persons in the answer", values={"URL": resp.url})
    rows = []
    for p in persons:
        name = p.get("name") or {}
        birth, death = p.get("birth") or {}, p.get("death") or {}
        rows.append({"title": f"{' '.join(name.get('first') or [])} {name.get('last', '')}".strip(),
                     "id": p.get("id"), "sex": p.get("sex"),
                     "birth": _date(birth.get("date")), "birth_place": (birth.get("location") or {}).get("city"),
                     "death": _date(death.get("date")), "death_place": (death.get("location") or {}).get("city"),
                     "url": f"https://deces.matchid.io/id/{p.get('id')}"})
    return OperationResult(rows=rows, count=(data.get("response") or {}).get("total"), url=resp.url)
