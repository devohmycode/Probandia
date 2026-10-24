"""Proof arguments (GPS5): when one is required, and how a question's argument stands.

A question needs a written argument (GPS-D8) when its conclusion rests on
indirect evidence (a concluding fact whose ``evidence`` axis is ``indirect``),
on negative evidence (axis ``negative``: an absence says how far it goes only
in an argument, T237), when an analysis it relies on holds pieces of evidence that disagree, or when
it is a question of identity (two mentions are one person): homonyms mislead
there most often. A question answered by direct evidence, with no conflict,
needs none.
"""

REASONS = ("identity", "indirect", "negative", "conflict")


def relied_on(question, analyses):
    """The analyses a question relies on: those that name it, or that cite one of its concluding facts."""
    concluded = set(question.get("conclusion") or [])
    out = []
    for a in analyses:
        cited = {i.get("fact") for i in a.get("items") or []} | {(a.get("resolution") or {}).get("fact")}
        if a.get("question") == question["id"] or (concluded & cited):
            out.append(a)
    return out


def disagree(analysis):
    """True when the pieces of evidence of an analysis do not all assert the same thing."""
    return len({" ".join(i["asserts"].lower().split()) for i in analysis.get("items") or []}) > 1


def required(question, persons, analyses):
    """Why a question needs a proof argument: a list of ``identity``, ``indirect``, ``negative`` and
    ``conflict``; empty when it needs none."""
    facts = {f["id"]: f for p in persons for f in p.get("facts") or []}
    out = []
    if question.get("type") == "identity":
        out.append("identity")
    if any(((facts.get(fid) or {}).get("evidence") or {}).get("evidence") == "indirect"
           for fid in question.get("conclusion") or []):
        out.append("indirect")
    if any(((facts.get(fid) or {}).get("evidence") or {}).get("evidence") == "negative"
           for fid in question.get("conclusion") or []):
        out.append("negative")
    if any(disagree(a) for a in relied_on(question, analyses)):
        out.append("conflict")
    return out


def proof_id(question_id, research_id):
    return f"pf-{question_id.lower()}-{research_id}"[:128].rstrip("-")


def accepted(proofs, research_id, question_id):
    """The accepted proof argument of a question, or None."""
    for p in proofs:
        if p["research"] == research_id and p["question"] == question_id and p["review"]["state"] == "accepted":
            return p
    return None


def open_objections(proof):
    return [o for r in proof["review"]["rounds"] for o in r["objections"] if o["state"] == "open"]
