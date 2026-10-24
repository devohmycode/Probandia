"""The board: where the person stands, in one look (cli.md § 6.6, § 7.2).

``board()`` gathers what the welcome screen shows, from the files only (never a
report, as ``status``, PRD R-7): the researches and their open passes, the
proposals waiting, the last verdict of ``verify``, the lowest free quotas, the
alerts and the next actions. ``watch``, ``statusline`` and the TUI will read it
too; it writes nothing.
"""
import os

from probandia import events, lifecycle
from probandia.i18n import N_

LOW = 0.2   # an account below this share left is an alert


def _last_verdict(log):
    """The rules that failed at the last ``verify.run`` of the log; None when
    the research was never verified."""
    runs = [e for e in log if e["type"] == "verify.run"]
    if not runs:
        return None
    results = runs[-1]["payload"].get("results") or {}
    return sorted((rule for rule, status in results.items() if status == "FAIL"),
                  key=lambda r: int(r.split("-")[1]))


def researches(project):
    """One record per research, newest activity first."""
    from probandia.proposals import pending
    from probandia.research import all_researches

    out = []
    for res in all_researches(project):
        meta = res.meta() or {}
        log = events.read(res.events_path)
        last, open_ = lifecycle.pass_state(log)
        started = [e["ts"] for e in log if e["type"] == "pass.started" and e["pass"] == last]
        run = meta.get("run") or {}
        out.append({"research": res.id, "family": res.family, "status": meta.get("status", "open"),
                    "passes": last - (1 if open_ else 0), "open_pass": last if open_ else None,
                    "open_since": started[-1] if open_ and started else None,
                    "run_mode": run.get("mode"), "agents": run.get("max_agents"),
                    "failed_rules": _last_verdict(log), "pending": len(pending(res)),
                    "last_activity": log[-1]["ts"] if log else str(meta.get("created", ""))})
    return sorted(out, key=lambda r: r["last_activity"], reverse=True)


def expired_locks(project, expiry_minutes):
    from probandia.util.locks import Locks

    locks = Locks(project, expiry_minutes=expiry_minutes)
    folder = os.path.join(project, ".probandia", "locks")
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            info, expired = locks.status(name[:-5])
            if info is not None and expired:
                out.append({"scope": name[:-5], "expired_at": info.get("expires")})
    return out


def lowest(found):
    """The ready accounts of ``providers.accounts``, the least left first."""
    return sorted((a for a in found if a["state"] == "ready" and a["fraction"] is not None),
                  key=lambda a: (a["fraction"], a["account"]))


def account_text(a):
    """``SerpApi 199``: an account and what it has left, for a status bar (T146)."""
    from probandia.i18n import _, formats

    if a["left"] is None:
        return f"{a['name']} " + _("unlimited")
    left = max(0, a["left"])
    if a["unit"] == "dollar":
        return f"{a['name']} {formats.money(left)}"
    return f"{a['name']} " + (formats.number(left / 1e6, 1) + " M" if left >= 1e6 else formats.number(round(left)))


def board(project, config, environ, ledger, catalogue_entries):
    """{project, families, researches, pending, accounts, alerts, next}."""
    from probandia.doctor import catalogue_ages
    from probandia.providers import accounts
    from probandia.providers import catalogue as providers

    found = accounts.accounts(catalogue_entries, ledger, config, environ, config.get("budget.reserve_percent"))
    ready = lowest(found)
    alerts = []
    for a in ready:
        if a["fraction"] < LOW:
            alerts.append({"kind": "quota-low", "what": a["name"], "left": round(a["fraction"] * 100)})
    for a in found:
        if a["state"] in ("exhausted", "expired"):
            alerts.append({"kind": "quota-" + a["state"], "what": a["name"]})
    days = providers.max_age_days(config)
    old = providers.stale(catalogue_ages() or [], days)
    if old:
        alerts.append({"kind": "catalogue-old", "what": ", ".join(old), "days": days})
    out = {"project": project, "families": [], "researches": [], "accounts": ready[:3], "alerts": alerts,
           "next": [], "counted_projects": len({e.get("project") for e in _user_lines(ledger) if e.get("project")})}
    if project is None:
        return out
    out["families"] = sorted(lifecycle.families(project))
    out["researches"] = researches(project)
    for lock in expired_locks(project, config.get("locks.expiry_minutes")):
        alerts.append({"kind": "lock-expired", "what": lock["scope"], "since": lock["expired_at"]})
    for r in out["researches"]:
        if r["status"] == "closed":
            continue
        if r["pending"]:
            out["next"].append({"command": "probandia apply <proposal>", "why": N_("review the proposals waiting"),
                                "research": r["research"]})
        if r["failed_rules"]:
            out["next"].append({"command": f"probandia verify {r['research']}", "why": N_("see what failed"),
                                "research": r["research"]})
        if r["open_pass"] or r["status"] == "open":
            out["next"].append({"command": f"/probandia:resume {r['research']}",
                                "why": N_("in your agent, to go on with the open pass") if r["open_pass"]
                                else N_("in your agent, for the next pass"), "research": r["research"]})
    out["next"] = out["next"][:4]
    return out


# the steps of a pass, each the event that shows it done (P1-T1 of claude-code-mod.md)
PASS_STEPS = (("plan", "plan.made"), ("search", "search.logged"),
              ("facts", "fact.asserted"), ("report", "section.added"), ("verify", "verify.run"),
              ("end", "pass.ended"))
LAST_SEARCHES = 3


def focus(project, research, config, environ, harness):
    """One research seen from its last pass: the steps done, the native searches left, its last
    searches, the proposals waiting and the last verdict (``board --json``, T116)."""
    from probandia.budget import native_budget
    from probandia.indexes import FamilyIndexes
    from probandia.proposals import pending

    log = events.read(research.events_path)
    last, open_ = lifecycle.pass_state(log)
    done = {e["type"] for e in log if e.get("pass") == last}
    native = native_budget(project, research, config, environ, harness)
    searches = sorted((s for s in FamilyIndexes(project, research.family).items("searches")
                       if s.get("research") == research.id), key=lambda s: str(s.get("ts") or ""))
    return {"research": research.id, "family": research.family, "pass": last, "open": open_,
            "steps": [{"step": name, "done": kind in done} for name, kind in PASS_STEPS],
            "native": {k: native[k] for k in ("used", "per_pass", "left", "session_left")},
            "searches": [{"engine": s.get("engine"), "query": s.get("query"), "result": s.get("result"),
                          "ts": s.get("ts")} for s in searches[-LAST_SEARCHES:][::-1]],
            "pending": len(pending(research)), "failed_rules": _last_verdict(log)}


def _user_lines(ledger):
    from probandia.ledger import _read_lines

    return _read_lines(ledger.user_log) if getattr(ledger, "user", None) and ledger.user_log else []
