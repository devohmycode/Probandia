"""The native web search budget of a pass.

- ``search.max_parallel`` searches in one turn;
- at most ``search.native_max_per_pass`` per pass;
- under the harness's session cap, with a margin: Claude Code allows 200
  ``WebSearch`` calls per session, so a session stops at 180.

The native searches are counted from the search log: entries of kind
``native`` of the pass, and, for the session cap, those whose ``filters.session``
is the calling session.
"""
from probandia.indexes import FamilyIndexes
from probandia.lifecycle import current_pass
from probandia.util.locks import session_id

SESSION_CAPS = {"claude-code": 200}
SESSION_MARGIN = 0.10


def native_budget(project, research, config, environ, harness):
    searches = FamilyIndexes(project, research.family).items("searches")
    p = current_pass(research)
    used_pass = sum(1 for s in searches if s.get("kind") == "native" and s.get("research") == research.id
                    and s.get("pass") == p)
    session = session_id(environ)
    used_session = sum(1 for s in searches if s.get("kind") == "native"
                       and (s.get("filters") or {}).get("session") == session)
    per_pass = config.get("search.native_max_per_pass")
    left = per_pass - used_pass
    cap = SESSION_CAPS.get(harness)
    session_left = None
    if cap:
        session_left = int(cap * (1 - SESSION_MARGIN)) - used_session
        left = min(left, session_left)
    left = max(0, left)
    return {"pass": p, "used": used_pass, "per_pass": per_pass, "session_used": used_session,
            "session_left": session_left, "left": left,
            "parallel": min(config.get("search.max_parallel"), left)}


def split(left, agents):
    """The native searches each agent of a wave may run: an even share, the
    remainder to the first agents."""
    agents = max(1, int(agents))
    base, extra = divmod(max(0, int(left)), agents)
    return [base + (1 if i < extra else 0) for i in range(agents)]
