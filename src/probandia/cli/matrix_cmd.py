"""``matrix``: the exhaustiveness matrix of a research (GPS3-T5).

``matrix [<research>] [--question Q]`` shows, for each question, the source
types one expects to search and the state of each (consulted, gap, not
applicable, to do), with what is left to do; the engine writes it to
``research/<id>/matrix.yaml``. ``matrix justify <Q> <type> --reason "…"
[--research <id>]``
says why a source type does not apply to a question, under the research lock,
with a ``matrix.justified`` event; for ``catalogue_<country>``, a country the
catalogue has no rule for, the reason names the source types searched there.
"""
from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _

MARKS = {"consulted": "OK", "gap": "WARN", "not_applicable": "WARN", "unjustified_gap": "FAIL", "todo": "FAIL"}


def matrix_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix, or justify"))
    p.add_argument("target", nargs="?", help=_("justify: the question, such as Q1"))
    p.add_argument("source_type", nargs="?", help=_("justify: the source type, such as notarial"))
    p.add_argument("--question", help=_("only this question, such as Q1"))
    p.add_argument("--reason", help=_("justify: why the source type does not apply to the question; for "
                                      "catalogue_<country>, the source types searched there"))
    p.add_argument("--research", dest="research_opt", metavar="<research>", help=_("research id or unique prefix"))


def _expiry(ctx):
    return ctx.config.get("locks.expiry_minutes") or 30


def _name(row, catalogue):
    from probandia import i18n

    names = next((t["names"] for t in catalogue["types"] if t["id"] == row["type"]), {})
    return names.get(i18n.current().split("-")[0]) or names.get("en") or row["type"]


def _span(a, b):
    return str(a) if a == b else f"{a}-{b}"


def _left(qid, row):
    """What is left to do for a row, as a person reads it."""
    if row["state"] == "todo" and row["type"].startswith("catalogue_"):
        return _("name the source types searched: matrix justify {q} {type} --reason …").format(
            q=qid, type=row["type"])
    if row["state"] == "todo":
        where = ", ".join(r.get("archive") or r["name"] for r in row["repositories"])
        return (_("search {where}").format(where=where) if where else _("search: no repository known")) + \
            f" ({_span(*row['years'])})"
    if row["state"] == "unjustified_gap":
        return _("say how gap {ids} is known (justification or source)").format(ids=", ".join(row["gaps"]))
    if row["state"] == "not_applicable" and not row.get("reason"):
        return f"matrix justify {qid} {row['type']} --reason …"
    return ""


def _settled_by(row):
    if row["state"] == "consulted":
        return ", ".join(row["searches"])
    if row["state"] in ("gap", "unjustified_gap"):
        return ", ".join(row["gaps"])
    return row.get("reason") or ""


def listing(research, doc, only=None, catalogue=None):
    from probandia.proof import matrix, source_types

    catalogue = catalogue or source_types.load()
    shown = [q for q in doc["questions"] if not only or q["id"] == only]
    holes = {q["id"]: matrix.holes(q) for q in shown}
    count = sum(len(h) for h in holes.values())
    r = Result("WARN" if count else "OK", {"RESEARCH": research.id, "QUESTIONS": len(shown), "HOLES": count,
                                          "MATRIX": "matrix.yaml"})
    rows, questions = [], []
    for q in shown:
        window = _span(q["window"]["from"], q["window"]["to"]) if q.get("window") else ""
        questions.append({"question": q["id"], "type": q["type"], "status": q["status"], "window": window,
                          "unknown": ",".join(q["unknown"]), "notes": ",".join(q["notes"]),
                          "holes": len(holes[q["id"]])})
        r.data(q["id"], "holes: " + (", ".join(holes[q["id"]]) or "none"))
        for row in q["rows"]:
            rows.append({"question": q["id"], "type": row["type"], "name": _name(row, catalogue),
                         "state": row["state"], "places": ",".join(row["places"]),
                         "years": _span(*row["years"]),
                         "repositories": ", ".join(x.get("archive") or x["name"] for x in row["repositories"]),
                         "settled_by": _settled_by(row), "left": _left(q["id"], row)})
        for u in q["unknown"]:
            if u == "window":
                r.line(_("{q}: the question has no {what}; question edit {q} gives it").format(q=q["id"], what=_("window")))
            else:   # T261: a place already given may only lack its country, which its guide finds
                r.line(_("{q}: the question has no place of known country; question edit {q} --place gives one, "
                         "and places guide \"<place> (<department or country>)\" --refresh finds the country of a place given").format(q=q["id"]))
        for c in q["notes"]:
            r.line(_("{q}: no source type is catalogued for the country {country}; matrix justify {q} {type} "
                     "--reason names those searched").format(q=q["id"], country=c, type=matrix.catalogue_type(c)))
    r.table("questions", questions)
    r.table("matrix", rows)
    r.view = "matrix"
    return r


def matrix_cmd(ctx):
    from probandia.errors import LockHeld
    from probandia.indexes import locked
    from probandia.proof import matrix
    from probandia.proof import questions as Q
    from probandia.research import find_research

    a = ctx.args
    if a.research == "justify":
        return justify(ctx)
    research = find_research(ctx.project, a.research or a.research_opt, ctx.environ)
    only = Q.get(research.meta() or {}, a.question)["id"] if a.question else None
    try:
        with locked(ctx.project, f"research:{research.id}", actor(ctx), _expiry(ctx), wait_seconds=5):
            doc = matrix.build(research)
            matrix.write(research, doc)
        written = True
    except LockHeld:
        doc, written = matrix.build(research), False
    r = listing(research, doc, only)
    if not written:
        r.line(_("matrix.yaml was not written: the research is locked"))
    return r


def justify(ctx):
    """``matrix justify <Q> <type> --reason …``: a source type that does not apply to a question."""
    from probandia import events, lifecycle
    from probandia.indexes import locked
    from probandia.proof import matrix
    from probandia.proof import questions as Q
    from probandia.research import find_research
    from probandia.util.fs import iso, utc_now

    a = ctx.args
    if not a.target or not a.source_type:
        raise UsageError(_("name the question and the source type: matrix justify Q1 notarial --reason …"))
    reason = (a.reason or "").strip()
    if not reason:
        raise UsageError(_("say why the source type does not apply (--reason)"), values={"REASON": "no-reason"})
    research = find_research(ctx.project, a.research_opt, ctx.environ)
    qid = Q.get(research.meta() or {}, a.target)["id"]
    who = actor(ctx)
    with locked(ctx.project, f"research:{research.id}", who, _expiry(ctx), wait_seconds=5):
        doc = matrix.build(research)
        expected = {row["type"] for q in doc["questions"] if q["id"] == qid for row in q["rows"]}
        if a.source_type not in expected:
            raise UsageError(_("{type} is not a source type expected for {q}: {types}").format(
                type=a.source_type, q=qid, types=", ".join(sorted(expected)) or "-"),
                values={"REASON": "not-expected"})
        said = [x for x in doc["not_applicable"] if (x["question"], x["type"]) != (qid, a.source_type)]
        said.append({"question": qid, "type": a.source_type, "reason": reason, "ts": iso(utc_now()),
                     "agent": who["agent"]})
        doc = matrix.build(research, not_applicable=said)
        matrix.write(research, doc)
        last = lifecycle.pass_state(events.read(research.events_path))[0]
        events.append(research.events_path, [events.make(
            "matrix.justified", {"question": qid, "type": a.source_type, "reason": reason}, who, last)])
    r = listing(research, doc, qid)
    r.set("JUSTIFIED", f"{qid}.{a.source_type}")
    return r
