"""The catalogue of source types (GPS3-T1): ``catalogues/source-types.yaml``.

For each kind of record (parish registers, civil registers, census lists…), by
country: the years it was kept, the places and years where it was not (or was
longer), the question types it answers and the archive coverage types that
carry it. Every rule cites its references; the schema refuses one without.
"""
from probandia.errors import SchemaError
from probandia.i18n import _
from probandia.util.schema import ValidationIssue, validate_document


def check(doc, source="source-types.yaml"):
    """Validates the catalogue, then what the schema cannot say: unique ids, a
    ``by`` exactly on replaced exceptions and naming a known type, years in order."""
    validate_document("source-types", doc, source)
    issues, ids = [], [t["id"] for t in doc["types"]]
    for i, t in enumerate(doc["types"]):
        if ids.index(t["id"]) != i:
            issues.append(ValidationIssue(f"$.types[{i}].id", _("duplicate id {id}").format(id=t["id"])))
        for j, rule in enumerate(t["rules"]):
            path = f"$.types[{i}].rules[{j}]"
            if rule["to"] is not None and rule["to"] < rule["from"]:
                issues.append(ValidationIssue(f"{path}.to", _("before from")))
            for k, x in enumerate(rule.get("exceptions") or []):
                at = f"{path}.exceptions[{k}]"
                if x["to"] < x["from"]:
                    issues.append(ValidationIssue(f"{at}.to", _("before from")))
                if (x["effect"] == "replaced") != ("by" in x):
                    issues.append(ValidationIssue(f"{at}.by", _("required with effect replaced, and only then")))
                elif "by" in x and (x["by"] not in ids or x["by"] == t["id"]):
                    issues.append(ValidationIssue(f"{at}.by", _("unknown source type {id}").format(id=x["by"])))
                if not all(p.split("-")[0] == rule["country"] for p in x["places"]):
                    issues.append(ValidationIssue(f"{at}.places", _("outside {country}").format(
                        country=rule["country"])))
    if issues:
        raise SchemaError(_("{source}: {n} error(s); first: {first}").format(
            source=source, n=len(issues), first=issues[0]), issues, lines=[str(x) for x in issues[:10]])
    return doc


def load(path=None):
    """The catalogue, checked; ``path`` defaults to the built-in one."""
    from probandia import paths
    from probandia.util import yamlio

    path = path or paths.data("catalogues", "source-types.yaml")
    return check(yamlio.load(path), path)


def by_id(doc):
    return {t["id"]: t for t in doc["types"]}


def rule(source_type, country):
    """The rule of a source type for a country (ISO code), or None."""
    return next((r for r in source_type["rules"] if r["country"] == country), None)
