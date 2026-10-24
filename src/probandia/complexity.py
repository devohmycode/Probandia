"""How hard a research question looks, and the run that suits it (optimize 2.12).

A simple question (one fact about a person the family already knows, nothing
in dispute) runs well in the session agent at a medium effort; a team costs
more tokens than it saves there. A question that must prove an absence, tell
homonyms apart or settle open hypotheses gains from more agents. The estimate
is a default the person sees and may change: it never decides alone.

| Points | For |
|---|---|
| 2 | a question of identity (homonyms) or a negative to prove |
| 1 | a question of parents or children (two generations to link) |
| 1 each, up to 3 | an open hypothesis of the family |
| 1 | a hypothesis with two candidates or more still open (a conflict) |
| 1 | a negative of the family due for a new check |
| 1 | a person the family index does not know yet |

0 or 1 point: simple (session, medium effort); 2 or 3: medium (session, high
effort); 4 or more: complex (team, high effort).

A simple or medium question also suggests Sonnet for the main loop (T80: 28 %
cheaper on a simple case, the proof intact); a complex one suggests no model.
The engine cannot change the session's model: the person switches, or not.
"""
import datetime

LEVELS = ((1, "simple", "session", "medium", "sonnet"), (3, "medium", "session", "high", "sonnet"),
          (99, "complex", "team", "high", None))


def estimate(project, family, question, today=None):
    """{score, level, mode, effort, model, reasons}: reasons are short English codes; model is
    a Claude Code alias, or None."""
    from probandia import planner
    from probandia.indexes import FamilyIndexes
    from probandia.lifecycle import infer_family

    score, reasons = 0, []
    qtype = planner.detect_type(question or "")
    if qtype in ("identity", "negative"):
        score += 2
        reasons.append(f"type:{qtype}")
    elif qtype in ("parents", "children"):
        score += 1
        reasons.append(f"type:{qtype}")
    if family is None and project:
        family = infer_family(project, question or "")[0]
    if project and family:
        try:
            idx = FamilyIndexes(project, family)
            hypotheses = [h for h in idx.items("hypotheses") if not h.get("closed")]
            persons = idx.items("persons")
            searches = idx.items("searches")
        except Exception:   # an index that does not read gives no point, never an error
            hypotheses, persons, searches = [], [], []
        if hypotheses:
            n = min(3, len(hypotheses))
            score += n
            reasons.append(f"open-hypotheses:{len(hypotheses)}")
        if any(sum(1 for c in h.get("hypotheses") or [] if c.get("status") == "open") >= 2 for h in hypotheses):
            score += 1
            reasons.append("conflict")
        today = today or datetime.date.today()
        due = [s for s in searches if s.get("result") == "negative" and s.get("recheck_after")
               and datetime.date.fromisoformat(str(s["recheck_after"])[:10]) <= today]
        if due:
            score += 1
            reasons.append(f"negatives-due:{len(due)}")
        if planner.find_indexed_person(question or "", persons) is None:
            score += 1
            reasons.append("unknown-person")
    for top, level, mode, effort, model in LEVELS:
        if score <= top:
            return {"score": score, "level": level, "mode": mode, "effort": effort, "model": model,
                    "reasons": reasons}

