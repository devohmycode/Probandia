"""``question``: the questions of a research (GPS1-T3).

``question list``, ``add "<text>"``, ``edit <Q>``, ``answer <Q> --conclusion <facts>``,
``unresolved <Q> --reason "<why>"`` and ``reopen <Q>``. Every change is written by the
engine to research.yaml, under the research lock, with a ``question.*`` event.
"""
from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _

ACTIONS = ("list", "add", "edit", "answer", "unresolved", "reopen")


def question_args(p, common):
    p.add_argument("action", nargs="?", default="list", choices=ACTIONS)
    p.add_argument("target", nargs="?", help=_("the text of a new question, or a question id such as Q2"))
    p.add_argument("--research", help=_("research id or unique prefix"))
    p.add_argument("--text", help=_("the new text of the question"))
    p.add_argument("--type", dest="qtype", help=_("question type: birth, marriage, death, parents, children, "
                                                  "residence, migration, identity, negative, general"))
    p.add_argument("--person", action="append", default=[], help=_("a person of the family's index"))
    p.add_argument("--place", action="append", default=[], help=_("a place of the family's index"))
    p.add_argument("--window", help=_("years the question covers, such as 1849-1853"))
    p.add_argument("--conclusion", action="append", default=[],
                   help=_("a fact that answers the question (persons.yaml), such as emile-marchand-1851.birth"))
    p.add_argument("--reason", help=_("why the question stays unresolved"))
    p.add_argument("--standard", help=_("add, edit: what will count as an answer, such as a birth act naming "
                                        "both parents"))


def _expiry(ctx):
    return ctx.config.get("locks.expiry_minutes") or 30


def listing(research, changed=None):
    """The questions of a research, for every action: what changed, then all of them."""
    from probandia.proof import questions as Q

    meta = research.meta() or {}
    qs = Q.of(meta)
    still = [q for q in qs if q.get("status", "open") == "open"]
    r = Result("OK", {"RESEARCH": research.id, "QUESTIONS": len(qs), "OPEN": len(still)})
    if changed:
        r.set("QUESTION", changed["id"])
        r.set("QUESTION_STATUS", changed["status"])
    for q in qs:
        r.data(q["id"], f"{q.get('status', 'open')} {q['type']} {q['text']}")
    r.table("questions", [{"id": q["id"], "status": q.get("status", "open"), "type": q["type"],
                           "text": q["text"], "persons": ",".join(q.get("persons") or []),
                           "window": (f"{q['window']['from']}-{q['window']['to']}" if q.get("window") else ""),
                           "places": ",".join(q.get("places") or []),
                           "conclusion": ",".join(q.get("conclusion") or []), "reason": q.get("reason") or "",
                           "standard": q.get("standard") or ""}
                          for q in qs])
    if not meta.get("questions"):
        r.line(_("the research has only its free-text question, read as Q1; question add or edit writes "
                 "the questions"))
    r.view = "question"
    return r


def _read(ctx, research, text):
    """The persons, window and places a question's text names, as for a new research."""
    from probandia.research import _questions

    found = _questions(ctx.project, research.family, text or "") if (text or "").strip() else []
    return found[0] if len(found) == 1 else {}


def question(ctx):
    from probandia.indexes import FamilyIndexes
    from probandia.proof import questions as Q
    from probandia.research import find_research

    a = ctx.args
    research = find_research(ctx.project, a.research, ctx.environ)
    if a.action == "list":
        return listing(research)
    meta = research.meta() or {}
    qs = Q.of(meta)
    if a.action == "add":
        read = _read(ctx, research, a.target)   # what the text says, unless given
        qs, changed = Q.add(qs, a.target, a.qtype, a.person or read.get("persons"), a.place or read.get("places"),
                            a.window or ("{from}-{to}".format(**read["window"]) if read.get("window") else None),
                            standard=a.standard)
        event = "question.added"
    else:
        if not a.target:
            raise UsageError(_("name the question, such as Q2"))
        qid = Q.get(meta, a.target)["id"]
        if a.action == "edit":
            qs, changed = Q.edit(qs, qid, a.text, a.qtype, a.person, a.place, a.window, standard=a.standard)
        elif a.action == "answer":
            qs, changed = Q.settle(qs, qid, "answered", conclusion=a.conclusion)
            unknown = Q.missing_facts(changed, FamilyIndexes(ctx.project, research.family).items("persons"))
            if unknown:
                raise UsageError(_("not a fact of the family's index: {ids}").format(ids=", ".join(unknown)),
                                 values={"REASON": "unknown-fact"})
        elif a.action == "unresolved":
            qs, changed = Q.settle(qs, qid, "unresolved", reason=a.reason)
        else:
            qs, changed = Q.settle(qs, qid, "open")
        event = "question.updated"
    payload = {"question": changed["id"], "status": changed["status"]}
    if changed.get("conclusion"):
        payload["conclusion"] = changed["conclusion"]
    if changed.get("reason"):
        payload["reason"] = changed["reason"]
    if (a.standard or "").strip() and changed.get("standard"):   # T249: what will count as an answer
        payload["standard"] = changed["standard"]
    Q.write(ctx.project, research, actor(ctx), _expiry(ctx), qs, event, payload)
    return listing(research, changed)
