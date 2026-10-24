"""A collector written for the library's contract: it needs no network."""

WITNESS = {"args": {"name": "Hugo"}, "expect": {"min_results": 1}}


def run(args, http):
    name = args.get("name", "")
    return [{"name": name, "source": "echo"}] if name else []
