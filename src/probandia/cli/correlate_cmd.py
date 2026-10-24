"""``correlate``: conflicting evidence and its analyses (GPS4-T3).

``correlate [list]`` shows the conflicts no analysis deals with yet, and the
analyses; ``correlate open`` writes a proposal opening an analysis for each
of those conflicts, its evidence filled in; ``correlate resolve <id> --value
… --reasoning …`` writes a proposal that resolves one; ``correlate diverge <id>
--reason …`` one that leaves it unresolved on purpose, the sources side by side
(FL-D9). ``apply`` then accepts or rejects the proposal, as for anything else of
the family.
"""
from probandia.cli.data_cmd import propose_parts
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _
from probandia.proof.conflicts import missing_axes

ACTIONS = ("list", "open", "resolve", "diverge")


def correlate_args(p, common):
    p.add_argument("action", nargs="?", default="list", choices=ACTIONS)
    p.add_argument("analysis", nargs="?", help=_("resolve: the analysis id, such as an-emile-marchand-1851-birth"))
    p.add_argument("--research", help=_("research id or unique prefix"))
    p.add_argument("--person", help=_("only this person of the family's index"))
    p.add_argument("--question", help=_("the research question the analyses serve, such as Q1"))
    p.add_argument("--value", help=_("resolve: the value kept, such as 1802-02-26"))
    p.add_argument("--fact", help=_("resolve: the fact kept, such as emile-marchand-1851.birth"))
    p.add_argument("--reasoning", help=_("resolve: why this value, against the other evidence"))
    p.add_argument("--reason", help=_("diverge: why the divergence is left unresolved"))


def _state(ctx, research):
    from probandia.indexes import FamilyIndexes
    from probandia.proof import conflicts

    idx = FamilyIndexes(ctx.project, research.family)
    persons, places, analyses = idx.items("persons"), idx.items("places"), idx.items("analyses")
    only = {ctx.args.person} if ctx.args.person else None
    groups = conflicts.unanalysed(persons, places, analyses, only)
    return persons, analyses, groups


def _propose(ctx, research, analyses):
    return propose_parts(ctx, research, "correlate", analyses=analyses)


def correlate(ctx):
    from probandia.proof import conflicts
    from probandia.proof import questions as Q
    from probandia.research import find_research

    a = ctx.args
    research = find_research(ctx.project, a.research, ctx.environ)
    if a.question:
        a.question = Q.get(research.meta() or {}, a.question)["id"]
    persons, analyses, groups = _state(ctx, research)
    if a.action == "open":
        if not groups:
            return Result("OK", {"RESEARCH": research.id, "OPENED": 0}, [_("no conflict left without an analysis")])
        opened = [conflicts.open_analysis(cs, persons, a.question, research.id) for cs in groups.values()]
        pid = _propose(ctx, research, opened)
        r = Result("OK", {"RESEARCH": research.id, "OPENED": len(opened), "PROPOSAL": pid})
        for x in opened:
            r.data("analysis", f"{x['id']} {len(x['items'])} pieces of evidence")
        r.line(_("next: apply {id}; then give each piece of evidence its three axes and resolve the analysis "
                 "(correlate resolve)").format(id=pid))
        return r
    if a.action in ("resolve", "diverge"):
        if not a.analysis:
            raise UsageError(_("name the analysis to resolve"))
        found = [x for x in analyses if x["id"] == a.analysis]
        if not found:
            raise UsageError(_("no analysis {id} in the family's index").format(id=a.analysis),
                             values={"REASON": "no-analysis"})
        if a.action == "diverge":
            if not (a.reason or "").strip():
                raise UsageError(_("a divergence left unresolved says why (--reason)"))
            resolved = {k: v for k, v in found[0].items() if k != "resolution"}
            resolved.update(status="divergent", reason=a.reason.strip())
        else:
            if not (a.value or "").strip() or not (a.reasoning or "").strip():
                raise UsageError(_("a resolution gives the value kept (--value) and why (--reasoning)"))
            resolved = dict({k: v for k, v in found[0].items() if k != "reason"}, status="resolved",
                            resolution={k: v for k, v in (("value", a.value.strip()), ("fact", a.fact),
                                                          ("reasoning", a.reasoning.strip())) if v})
        pid = _propose(ctx, research, [resolved])
        r = Result("OK", {"RESEARCH": research.id, "ANALYSIS": resolved["id"], "PROPOSAL": pid})
        r.line(_("next: apply {id}").format(id=pid))
        return r
    return listing(research, groups, analyses, a.person, ctx.config.get("proof.standard") or "off")


def listing(research, groups, analyses, person=None, standard="off"):
    shown = [x for x in analyses if not person or x["person"] == person]
    still = [x for x in shown if x["status"] == "open"]
    divergent = [x for x in shown if x["status"] == "divergent"]
    # GPS4-T4: once the standard is checked, every piece of evidence of an analysis needs its three axes
    bare = [x["id"] for x in shown if missing_axes(x)] if standard != "off" else []
    r = Result("WARN" if groups or bare else "OK", {"RESEARCH": research.id, "CONFLICTS": len(groups),
                                                    "OPEN": len(still), "RESOLVED": len(shown) - len(still) - len(divergent)})
    if divergent:
        r.set("DIVERGENT", len(divergent))
    if bare:
        r.set("WITHOUT_AXES", len(bare))
        r.line(_("give each piece of evidence its three axes (source, information, evidence): {ids}").format(
            ids=", ".join(bare)))
    rows = []
    for (pid, kind), cs in sorted(groups.items()):
        for c in cs:
            r.data("conflict", f"{pid} {kind} {c['on']}: {' / '.join(c['values'])}")
            rows.append({"person": pid, "fact": kind, "on": c["on"], "values": " / ".join(c["values"]),
                         "facts": ", ".join(c["facts"])})
    r.table("conflicts", rows)
    arows = []
    for x in shown:
        res = x.get("resolution") or {}
        r.data("analysis", f"{x['id']} {x['status']} {len(x['items'])} pieces" + (f" -> {res['value']}" if res else ""))
        arows.append({"analysis": x["id"], "status": x["status"], "person": x["person"], "fact": x["fact_kind"],
                      "evidence": len(x["items"]), "missing_axes": missing_axes(x), "kept": res.get("value", ""),
                      "question": x.get("question", "")})
    r.table("analyses", arows)
    if groups:
        r.line(_("{n} conflict(s) without an analysis: correlate open writes a proposal for them").format(n=len(groups)))
    r.view = "correlate"
    return r
