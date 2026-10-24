"""``fact``: what a person did with a fact of the family (T248).

``fact check <fact> --by "<who>" --looked "<what was looked at>" [--research <id>]``
records that a person looked at the record a fact rests on: a ``fact.checked``
event (who, when, what was looked at), written under the research lock. It is
refused when no one is at the keyboard (an agent, a pipe, ``PROBANDIA_HEADLESS``):
an agent may never write that a person checked.
"""
from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _


def fact_args(p, common):
    p.add_argument("action", choices=("check",))
    p.add_argument("fact", nargs="?", help=_("the fact, such as emile-marchand-1851.birth"))
    p.add_argument("--by", help=_("check: who looked at the record, as the report names them"))
    p.add_argument("--looked", help=_("check: what was looked at, such as the image of the act, view 45"))
    p.add_argument("--research", help=_("research id or unique prefix"))


def _expiry(ctx):
    return ctx.config.get("locks.expiry_minutes") or 30


def fact(ctx):
    from probandia import events, factcheck, lifecycle
    from probandia.indexes import FamilyIndexes, locked
    from probandia.research import find_research

    a = ctx.args
    if not getattr(ctx, "asks", False):   # T248: only a person writes that a person checked
        raise UsageError(_("fact check records what a person looked at: run it yourself, at your terminal"),
                         values={"REASON": "needs-person"})
    if not a.fact:
        raise UsageError(_("name the fact, such as emile-marchand-1851.birth"))
    by, looked = (a.by or "").strip(), (a.looked or "").strip()
    if not by:
        raise UsageError(_("say who looked at the record (--by)"), values={"REASON": "no-by"})
    if not looked:
        raise UsageError(_("say what was looked at (--looked)"), values={"REASON": "no-looked"})
    research = find_research(ctx.project, a.research, ctx.environ)
    known = {f.get("id") for p in FamilyIndexes(ctx.project, research.family).items("persons")
             for f in p.get("facts") or []}
    if a.fact not in known:
        raise UsageError(_("{fact} is not a fact of the family's index").format(fact=a.fact),
                         values={"REASON": "unknown-fact"})
    who = actor(ctx)
    with locked(ctx.project, f"research:{research.id}", who, _expiry(ctx), wait_seconds=5):
        last = lifecycle.pass_state(events.read(research.events_path))[0]
        written = events.append(research.events_path, [events.make(
            factcheck.EVENT, {"fact": a.fact, "by": by, "looked": looked}, who, last, [a.fact])])
    checks = factcheck.of_family(ctx.project, research.family)
    r = Result("OK", {"RESEARCH": research.id, "FACT": a.fact, "EVENT": written[0]["id"],
                      "CHECKS": len(checks.get(a.fact) or [])})
    r.line(_("{who} looked at {looked} for {fact}").format(who=by, looked=looked, fact=a.fact))
    left = factcheck.unchecked(research.meta() or {}, checks)
    if left:
        r.line(_("concluding facts no one checked yet: {ids}").format(ids=", ".join(left)))
    return r
