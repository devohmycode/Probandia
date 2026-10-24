"""``proof``: proof arguments and their review by the contradictor (GPS5-T3).

``proof list`` shows the arguments of a research and the questions that need
one; ``proof show <id>`` one argument with its objections; ``proof draft <Q>``
writes a skeleton to ``work/proofs/<id>.yaml``, its sources and correlation
filled in from the analyses, for the orchestrator to write; ``proof submit``
records it, submitted; ``proof review <id> --objections <file>`` records
what the contradictor returned; ``proof answer <id> <n>`` answers or
dismisses an objection; ``proof accept <id>`` accepts the argument once no
objection is open. Every change goes to the family through a proposal that
the engine applies at once: only the orchestrator or the session agent may.
"""
import os
import re

from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now

ACTIONS = ("list", "show", "draft", "submit", "review", "answer", "accept")
PARTS = ("question", "sources", "analysis", "correlation", "conflicts", "conclusion")
KEYS = {"objection": "text", "fact": "fact", "settle": "would_settle", "would settle": "would_settle",
        "what would settle it": "would_settle"}


def proof_args(p, common):
    p.add_argument("action", nargs="?", default="list", choices=ACTIONS)
    p.add_argument("target", nargs="?", help=_("a question (draft), a proof id, or the draft file (submit)"))
    p.add_argument("number", nargs="?", type=int, help=_("answer: the objection's number"))
    p.add_argument("--research", help=_("research id or unique prefix"))
    p.add_argument("--objections", help=_("review: the file of the contradictor's objections"))
    p.add_argument("--by", choices=("contradictor", "session"),
                   help=_("review: who reviewed, the contradictor subagent or the same session in a later turn"))
    p.add_argument("--text", help=_("answer: the answer to the objection"))
    p.add_argument("--dismiss", action="store_true", help=_("answer: set the objection aside"))
    p.add_argument("--reason", help=_("answer --dismiss: why the objection does not hold"))


def parse_objections(text):
    """The objections of a contradictor's return: blocks separated by a blank line, with ``objection:``,
    ``fact:`` and ``settle:`` lines; a block without them is one objection's text. ``none`` gives none."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        block = block.strip()
        if not block or block.lower().rstrip(".") in ("none", "no objection", "aucune"):
            continue
        item, last = {}, "text"
        for line in block.splitlines():
            line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
            m = re.match(r"^([A-Za-z ]+?)\s*:\s*(.*)$", line)
            key = KEYS.get(m.group(1).strip().lower()) if m else None
            if key:
                item[key], last = m.group(2).strip(), key
            elif line:
                item[last] = (item.get(last, "") + " " + line).strip()
        if item.get("text"):
            out.append(item)
    return out


def _research(ctx):
    from probandia.research import find_research

    return find_research(ctx.project, ctx.args.research, ctx.environ)


def _proofs(ctx, research):
    from probandia.indexes import FamilyIndexes

    return FamilyIndexes(ctx.project, research.family).items("proofs")


def _find(ctx, research, pid):
    if not pid:
        raise UsageError(_("name the proof argument, such as pf-q1-<research>"))
    for p in _proofs(ctx, research):
        if p["id"] == pid:
            return p
    raise UsageError(_("no proof argument {id} in the family's index").format(id=pid), values={"REASON": "no-proof"})


def _record(ctx, research, proof):
    """Applies a proposal carrying the proof argument: the family changes only through apply."""
    from probandia import lifecycle, proposals
    from probandia.util.ids import ulid

    me = actor(ctx)
    if me["agent"] not in proposals.APPLY_ROLES:
        raise UsageError(_("only the orchestrator or the session agent records a proof argument"),
                         values={"REASON": "not-allowed"})
    doc = {"schema": 1, "id": ulid(), "research": research.id, "pass": max(1, lifecycle.current_pass(research)),
           "author": {"harness": me["harness"], "agent": me["agent"]}, "proofs": [proof]}
    os.makedirs(research.work, exist_ok=True)
    draft = os.path.join(research.work, f"proof-{doc['id']}.yaml")
    yamlio.dump(draft, doc)
    try:
        proposals.propose(ctx.project, research, draft)
    finally:
        os.unlink(draft)
    proposals.apply(ctx.project, doc["id"], me, ctx.config)
    return doc["id"]


def _draft(ctx, research, qid):
    from probandia.indexes import FamilyIndexes
    from probandia.proof import arguments as A
    from probandia.proof import questions as Q

    q = Q.get(research.meta() or {}, qid)
    idx = FamilyIndexes(ctx.project, research.family)
    sources = {s["id"]: s for s in idx.items("sources")}
    facts = {f["id"]: f for p in idx.items("persons") for f in p.get("facts") or []}
    analyses = A.relied_on(q, idx.items("analyses"))
    cited = [facts[f].get("source") for f in q.get("conclusion") or [] if f in facts]
    cited += [i.get("source") for a in analyses for i in a["items"]]
    lines = []
    for sid in dict.fromkeys(x for x in cited if x):
        lines.append("- " + ((sources.get(sid) or {}).get("citation") or sid))
    corr = []
    for a in analyses:
        kept = (a.get("resolution") or {}).get("value")
        corr.append(f"- {a['id']}: " + " / ".join(i["asserts"] for i in a["items"]) + (f" -> {kept}" if kept else ""))
    return {"id": A.proof_id(q["id"], research.id), "research": research.id, "question": q["id"],
            "conclusion": [f for f in q.get("conclusion") or [] if f in facts], "analyses": [a["id"] for a in analyses],
            "parts": {"question": q["text"], "sources": "\n".join(lines), "analysis": "",
                      "correlation": "\n".join(corr), "conflicts": "", "conclusion": ""},
            "review": {"state": "draft", "rounds": []}}


def proof(ctx):
    from probandia.proof import arguments as A

    a = ctx.args
    research = _research(ctx)
    if a.action == "list":
        return listing(ctx, research)
    if a.action == "show":
        return showing(research, _find(ctx, research, a.target))
    if a.action == "draft":
        if not a.target:
            raise UsageError(_("name the question to argue, such as Q1"))
        doc = _draft(ctx, research, a.target)
        folder = os.path.join(research.work, "proofs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{doc['id']}.yaml")
        yamlio.dump(path, doc)
        r = Result("OK", {"RESEARCH": research.id, "PROOF": doc["id"], "FILE": os.path.relpath(path, ctx.project)})
        r.line(_("write the analysis, the conflicts and the conclusion in the file, then: proof submit {id}").format(
            id=doc["id"]))
        return r
    if a.action == "submit":
        path = a.target if a.target and os.path.isfile(a.target) else \
            os.path.join(research.work, "proofs", f"{a.target}.yaml")
        if not a.target or not os.path.isfile(path):
            raise UsageError(_("no draft {target}: run proof draft <question> first").format(target=a.target))
        doc = yamlio.load(path)
        empty = [k for k in PARTS if not str((doc.get("parts") or {}).get(k) or "").strip()]
        if empty:
            raise UsageError(_("the argument still lacks: {parts}").format(parts=", ".join(empty)),
                             values={"REASON": "incomplete-proof"})
        known = [p for p in _proofs(ctx, research) if p["id"] == doc["id"]]
        rounds = known[0]["review"]["rounds"] if known else []
        doc["review"] = {"state": "submitted", "rounds": rounds}
        return _done(ctx, research, doc, _record(ctx, research, doc))
    p = _find(ctx, research, a.target)
    if a.action == "review":
        if not a.objections or not os.path.isfile(a.objections):
            raise UsageError(_("give the contradictor's return as a file (--objections)"))
        if not a.by:
            raise UsageError(_("say who reviewed (--by contradictor, or --by session for the same session)"))
        with open(a.objections, encoding="utf-8") as fh:
            returned = fh.read()
        found = parse_objections(returned)
        n = sum(len(r["objections"]) for r in p["review"]["rounds"])
        # the return is kept verbatim beside the objections read from it: anyone can compare them
        round_ = {"date": iso(utc_now()), "reviewer": a.by, "returned": returned.strip(),
                  "objections": [dict(o, n=n + i, state="open") for i, o in enumerate(found, 1)]}
        p = dict(p, review={"state": "objected" if found else "submitted", "rounds": p["review"]["rounds"] + [round_]})
    elif a.action == "answer":
        if not a.number:
            raise UsageError(_("give the objection's number"))
        if a.dismiss and not (a.reason or "").strip():
            raise UsageError(_("a dismissed objection says why (--reason)"))
        if not a.dismiss and not (a.text or "").strip():
            raise UsageError(_("give the answer (--text), or dismiss the objection (--dismiss --reason)"))
        hit = False
        rounds = []
        for r in p["review"]["rounds"]:
            objections = []
            for o in r["objections"]:
                if o["n"] == a.number:
                    hit = True
                    o = dict(o, state="dismissed", reason=a.reason.strip()) if a.dismiss else \
                        dict(o, state="answered", answer=a.text.strip())
                objections.append(o)
            rounds.append(dict(r, objections=objections))
        if not hit:
            raise UsageError(_("no objection {n} in {id}").format(n=a.number, id=p["id"]))
        p = dict(p, review=dict(p["review"], rounds=rounds))
    else:   # accept
        still = A.open_objections(p)
        if still:
            raise UsageError(_("{n} objection(s) still open: answer or dismiss each one first").format(n=len(still)),
                             values={"REASON": "open-objections", "OPEN": len(still)},
                             lines=[f"open={o['n']} {o['text']}" for o in still])
        if not p["review"]["rounds"]:
            raise UsageError(_("the contradictor has not reviewed the argument yet (proof review)"),
                             values={"REASON": "not-reviewed"})
        p = dict(p, review=dict(p["review"], state="accepted"))
    return _done(ctx, research, p, _record(ctx, research, p))


def _done(ctx, research, p, proposal):
    r = showing(research, p)
    r.set("PROPOSAL", proposal)
    return r


def listing(ctx, research):
    from probandia.indexes import FamilyIndexes
    from probandia.proof import arguments as A
    from probandia.proof import questions as Q

    idx = FamilyIndexes(ctx.project, research.family)
    persons, analyses = idx.items("persons"), idx.items("analyses")
    mine = [p for p in idx.items("proofs") if p["research"] == research.id]
    rows, needed = [], 0
    for q in Q.of(research.meta() or {}):
        why = A.required(q, persons, analyses)
        found = [p for p in mine if p["question"] == q["id"]]
        state = found[0]["review"]["state"] if found else ""
        if why and state != "accepted":
            needed += 1
        rows.append({"question": q["id"], "needs": ", ".join(why), "proof": found[0]["id"] if found else "",
                     "state": state, "open": len(A.open_objections(found[0])) if found else 0})
    r = Result("WARN" if needed else "OK", {"RESEARCH": research.id, "PROOFS": len(mine), "NEEDED": needed})
    for x in rows:
        r.data("question", f"{x['question']} needs={x['needs'] or '-'} proof={x['proof'] or '-'} {x['state']}".rstrip())
    r.table("questions", rows)
    if needed:
        r.line(_("{n} question(s) need an accepted proof argument: proof draft <question>").format(n=needed))
    r.view = "proof-list"
    return r


def showing(research, p):
    from probandia.proof import arguments as A

    still = A.open_objections(p)
    r = Result("WARN" if still else "OK", {"RESEARCH": research.id, "PROOF": p["id"], "QUESTION": p["question"],
                                           "STATE": p["review"]["state"], "OPEN": len(still)})
    reviewers = sorted({rnd["reviewer"] for rnd in p["review"]["rounds"]})
    if reviewers:
        r.set("REVIEWED_BY", ",".join(reviewers))
    rows = []
    for rnd in p["review"]["rounds"]:
        for o in rnd["objections"]:
            rows.append({"n": o["n"], "state": o["state"], "text": o["text"], "fact": o.get("fact", ""),
                         "settle": o.get("would_settle", ""), "answer": o.get("answer") or o.get("reason") or ""})
            r.data("objection", f"{o['n']} {o['state']} {o['text']}")
    r.table("objections", rows)
    r.extra = {"parts": p["parts"]}
    r.view = "proof"
    return r
