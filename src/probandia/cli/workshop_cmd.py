"""The workshop of a project (docs/workshop-sync.md).

- ``workshop status [<research>]``: the two bases side by side, counted: new, same,
  divergent, workshop only, and whether the workshop changed since the last sync.
- ``workshop diff [<research>] [--format text|yaml]``: the facts by class, both values
  of each divergence with their sources; ``yaml``: the lines a push would insert.
- ``workshop push [<research>] [--accept <fact>…] [--dry-run]``: writes the new facts that pass the
  workshop's rules, and the divergent ones accepted one by one, as added lines; only a
  role that may apply does it, after a [y/N] at a terminal; ``workshop.pushed`` is logged.
- ``workshop pull [<research>]``: what the workshop gained or had corrected by hand since the
  last sync becomes a proposal of the research, for ``apply``; nothing else is written
  but workshop.yaml (WS-D8).
- ``workshop link <research>``: ties a research to a report of the workshop, with the
  volet and the chapter its new facts will carry there (WS-D5: asked once per
  research, the report's last ones offered).

No MCP tool: the plugin of Claude Code no longer declares the MCP server (E1), so
the command goes through the shell like the others.
"""
from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _

ACTIONS = ("status", "diff", "push", "pull", "link")
VERIFIER = "python outils/verifier.py"   # the check of a prototype workshop, recalled when none is set
BUILDER = "python outils/build.py"      # its build, recalled at pass end after a push, never run
CHECK_TIMEOUT = 120
GUIDE = "read skills/research/workshop.md"   # WS5-T5: the agent's instructions for a workshop, read on demand


def guide(ctx, r):
    """In a project linked to its workshop, ``NEXT`` of new, resume and apply names the agent's
    instructions for it, unless the answer has a NEXT of its own."""
    import os

    from probandia.importer import link_path

    if "NEXT" not in r.values and os.path.isfile(link_path(ctx.project)):
        r.set("NEXT", GUIDE)
    return r


def workshop_args(p, common):
    p.add_argument("action", choices=ACTIONS)
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--report", help=_("the folder of rapports/ the research's findings go to"))
    p.add_argument("--volet", help=_("the volet of its new facts, in Roman numerals"))
    p.add_argument("--chapitre", help=_("the chapter of its new facts, in Roman numerals"))
    p.add_argument("--format", dest="diff_format", choices=("text", "yaml"), default="text",
                   help=_("diff: the facts by class (text), or the lines a push would insert (yaml)"))
    p.add_argument("--accept", action="append", default=[], metavar="FACT",
                   help=_("push: write this divergent fact over the workshop's (repeatable)"))
    p.add_argument("--dry-run", action="store_true", help=_("push: show what would be written, write nothing"))


def _not_linked():
    return UsageError(_("this project has no workshop: workshop.yaml is written when a workshop is imported "
                        "(new in a workshop, or import <folder>)"), values={"REASON": "not-linked"})


def _roman(value, option):
    from probandia import workshop

    text = str(value or "").strip().upper()
    if not workshop.ROMAN.match(text):
        raise UsageError(_("{option} takes Roman numerals, as the workshop writes them: {value}").format(
            option=option, value=value), values={"REASON": "not-roman"})
    return text


def workshop(ctx):
    from probandia import workshop as ws

    link = ws.load(ctx.project)
    action = ctx.args.action
    if action == "status":
        return status(ctx, link)
    if link is None:
        raise _not_linked()
    if action == "diff":
        return diff(ctx, link)
    if action == "push":
        return push(ctx, link)
    if action == "pull":
        return pull(ctx, link)
    return link_research(ctx, link)


def _research_id(ctx):
    from probandia.research import find_research

    return find_research(ctx.project, ctx.args.research, ctx.environ).id if ctx.args.research else None


def _blocked(state):
    """[(Entry, [(rule, message)])] of the new facts the workshop's rules stop."""
    from probandia.workshop.prototype import rules
    from probandia.workshop.prototype.compare import NEW

    out = []
    adding = {e.person for e in state.of(NEW) if e.person not in state.ctx.wpersons}
    for e in state.of(NEW):
        found = rules.check(e.translation, state.ctx, adding)
        if found:
            out.append((e, found))
    return out


def _rows(state, blocked):
    stopped = {e.id: "; ".join(m for _r, m in found) for e, found in blocked}
    return [{"fact": e.id, "class": e.cls, "nature": e.nature, "person": e.person, "key": e.key, "index": e.index,
             "differs": e.differs, "probandia": e.probandia, "workshop": e.workshop, "blocked": stopped.get(e.id)}
            for e in state.entries]


def status(ctx, link):
    from probandia import workshop as ws

    if link is None:
        from probandia.importer import is_workshop

        return Result("OK", {"ADAPTER": "-", "ROOT": "-", "LINKED": False,
                             "NEXT": "new --workshop import" if is_workshop(ctx.project) else "-"})
    state = ws.State(ctx.project, link, _research_id(ctx))
    blocked = _blocked(state)
    c = state.counts
    pushable = c["new"] - len(blocked)
    nxt = "workshop push" if pushable else "workshop diff" if blocked or c["divergent"] else \
        "workshop pull" if state.changed else "-"
    r = Result("WARN" if blocked or c["divergent"] else "OK",
               {"ADAPTER": link["adapter"], "ROOT": link["root"], "LINKED": True, "NEW": c["new"], "SAME": c["same"],
                "DIVERGENT": c["divergent"], "WORKSHOP_ONLY": c["workshop-only"], "BLOCKED": len(blocked),
                "CHANGED_SINCE_SYNC": state.changed, "NEXT": nxt})
    for e in state.of("divergent")[:10]:
        r.data("divergent", f"{e.id} {e.nature}: {', '.join(e.differs)}")
    for e, found in blocked[:10]:
        r.line(found[0][1])
    r.table("facts", _rows(state, blocked), hidden=True)
    return r


def _show(fact):
    from probandia.workshop.prototype import render

    return render.flow(fact, "      ") if fact else []


def diff_text(state, blocked):
    """The readable diff: the facts by class, both values of each divergence."""
    from probandia.workshop.prototype.compare import CLASSES

    titles = {"new": _("new: {n}"), "same": _("same: {n}"), "divergent": _("divergent: {n}"),
              "workshop-only": _("in the workshop only: {n}")}
    marks = {"new": "+", "same": "=", "divergent": "~", "workshop-only": "<"}
    stopped = {e.id: found for e, found in blocked}
    out = []
    for cls in CLASSES:
        found = state.of(cls)
        out.append(titles[cls].format(n=len(found)))
        for e in found:
            where = f"{e.person}, {e.key}" + (f"[{e.index}]" if e.index is not None else "")
            head = f"  {marks[cls]} {e.id} ({where})"
            if e.nature:
                head += f" {e.nature}" + (f": {', '.join(e.differs)}" if e.differs else "")
            out.append(head)
            if cls == "new":
                out += _show(e.probandia)
                out += ["      ! " + m for _r, m in stopped.get(e.id, [])]
            elif cls == "divergent":
                out.append("    " + _("Probandia:"))
                out += _show(e.probandia)
                out.append("    " + _("workshop:"))
                out += _show(e.workshop)
            elif cls == "workshop-only":
                out += _show(e.workshop)
    return "\n".join(out) + "\n"


def diff(ctx, link):
    from probandia import workshop as ws

    state = ws.State(ctx.project, link, _research_id(ctx))
    blocked = _blocked(state)
    c = state.counts
    r = Result("OK", {"NEW": c["new"], "SAME": c["same"], "DIVERGENT": c["divergent"],
                      "WORKSHOP_ONLY": c["workshop-only"], "BLOCKED": len(blocked)})
    if ctx.args.diff_format == "yaml":
        plan = ws.Plan(state)
        text = "".join(f"# commun/personnes.yaml, {_('before line {n}').format(n=at)}\n" + "".join(x + "\n" for x in lines)
                       for at, lines in plan.lines())
        r.raw = text or "# " + _("nothing to insert") + "\n"
        r.table("insert", [{"line": at, "lines": lines} for at, lines in plan.lines()])
    else:
        r.raw = diff_text(state, blocked)
    r.table("facts", _rows(state, blocked))
    return r


def push(ctx, link, research=None, confirm=True):
    """``workshop push``; ``research``, ``confirm``: for the push an apply makes (workshop.sync = auto)."""
    from probandia import proposals
    from probandia import workshop as ws
    from probandia.cli import asking
    from probandia.workshop.prototype.write import Changed, Malformed

    me = actor(ctx)
    if me["agent"] not in proposals.APPLY_ROLES:
        raise UsageError(_("only the orchestrator or the session agent may write to the workshop"),
                         values={"REASON": "not-allowed"})
    a = ctx.args
    state = ws.State(ctx.project, link, research or _research_id(ctx))
    plan = ws.Plan(state, getattr(a, "accept", None) or ())
    if plan.unknown_accept:
        raise UsageError(_("not a divergent fact of the workshop: {ids}").format(ids=", ".join(plan.unknown_accept)),
                         values={"REASON": "not-divergent"})
    values = {"PUSHED": len(plan.pushed), "PERSONS": len(plan.persons), "BLOCKED": len(plan.blocked),
              "DIVERGENT": state.counts["divergent"] - sum(1 for e in plan.pushed if e.cls == "divergent")}
    r = Result("WARN" if plan.blocked else "OK", values)
    for e, found in plan.blocked[:10]:
        r.line(found[0][1])
    r.table("pushed", [{"fact": e.id, "person": e.person, "key": e.key, "class": e.cls, "nature": e.nature}
                       for e in plan.pushed])
    r.table("blocked", [{"fact": e.id, "rules": [x for x, _m in found], "messages": [m for _x, m in found]}
                        for e, found in plan.blocked])
    if getattr(a, "dry_run", False) or not plan.pushed:
        r.set("DRY_RUN", bool(getattr(a, "dry_run", False)))
        for at, lines in plan.lines()[:10]:
            r.data("insert", f"line {at}: {lines[0].strip()}" + (f" (+{len(lines) - 1})" if len(lines) > 1 else ""))
        return r
    if confirm and not asking.confirm(ctx, _("Write {n} fact(s) to the workshop's personnes.yaml? The workshop "
                                             "keeps them; Probandia never takes a line back.").format(
            n=len(plan.pushed))):
        return asking.declined(values)
    try:
        ws.push(ctx.project, plan, me)
        check(ctx, state.ctx.folder, r)
    except Changed:
        return Result.stop("workshop-changed", values=dict(values, PUSHED=0)).line(
            _("personnes.yaml changed while the push was being prepared: nothing was written; run it again"))
    except Malformed as exc:
        return Result("FAIL", dict(values, PUSHED=0, REASON="malformed")).line(
            _("nothing was written: {why}").format(why=exc))
    return r


def pull(ctx, link):
    from probandia import proposals
    from probandia import workshop as ws
    from probandia.cli.data_cmd import propose_parts
    from probandia.importer import _roman as roman
    from probandia.indexes import locked
    from probandia.research import find_research
    from probandia.util.fs import iso, utc_now
    from probandia.workshop.prototype.pull import Pull

    me = actor(ctx)
    if me["agent"] not in proposals.APPLY_ROLES:
        raise UsageError(_("only the orchestrator or the session agent may bring the workshop's changes in"),
                         values={"REASON": "not-allowed"})
    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    state = ws.State(ctx.project, link)
    p = Pull(state)
    pid = propose_parts(ctx, research, "workshop-pull", **p.parts()) if p.facts else None
    with locked(ctx.project, f"family:{state.ctx.family}", me):
        link["facts"].update(p.links)
        if p.superseded:
            link.setdefault("superseded", {}).update(p.superseded)
        for person, wid in p.new_persons.items():
            raw = state.ctx.wpersons.get(wid) or {}
            link["persons"][person] = {"workshop": wid, **{k: roman(raw.get(k)) for k in ("generation", "volet",
                                                                                           "chapitre")}}
            known = link["families"].setdefault(state.ctx.family, [])
            if wid not in known:
                known.append(wid)
        synced = link["synced"]
        synced.update(sha256=ws.file_sha(state.path), at=iso(utc_now()),
                      pulled=int(synced.get("pulled") or 0) + len(p.facts))
        ws.save(ctx.project, link)
    r = Result("OK", {"PULLED": len(p.facts), "CORRECTED": len(p.superseded), "PERSONS": len(p.new_persons),
                      "PROPOSAL": pid or "-", "NEXT": f"apply {pid}" if pid else "-"})
    r.table("pulled", [dict(entry, fact=fid) for fid, entry in p.links.items()])
    if pid:
        r.line(_("the proposal holds what the workshop says; apply checks it like any other"))
    return r


def run_check(command, folder, timeout=CHECK_TIMEOUT):
    """(passed, its last ten lines): the workshop's own check, run in its folder (WS-D7: only the
    command the user set). ``python`` is the engine's interpreter: the one that runs is known."""
    import shlex
    import subprocess
    import sys

    args = shlex.split(command, posix=sys.platform != "win32")
    if args and args[0].lower() in ("python", "python3", "py"):
        args[0] = sys.executable
    try:
        done = subprocess.run(args, cwd=folder, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, [_("stopped after {n} s").format(n=timeout)]
    except OSError as exc:
        return False, [str(exc)]
    text = (done.stdout + done.stderr).decode("utf-8", "replace")
    return done.returncode == 0, [x for x in text.splitlines() if x.strip()][-10:]


def check(ctx, folder, r):
    """WS6-T1: after a real push, workshop.check runs, if it is set; its failure leaves the file as
    written, and says what to run again. Without it, the answer recalls the workshop's check."""
    command = (ctx.config.get("workshop.check") or "").strip()
    if not command:
        r.set("CHECK", "not-set")
        r.line(_("check the workshop with its own tool, in its folder: {command}").format(command=VERIFIER))
        return
    passed, tail = run_check(command, folder)
    r.set("CHECK", "passed" if passed else "failed")
    for line in tail:
        r.data("check", line)
    if not passed:
        r.status = "WARN"
        r.set("NEXT", command)
        r.line(_("the workshop's check failed: personnes.yaml stays as written; correct it, then run {command} "
                 "in the workshop again").format(command=command))


def _asked_path(research):
    import os

    return os.path.join(research.work, "workshop-push-asked.json")


def asked_in_pass(research):
    """The pass in which the question workshop_push was last asked, or None."""
    import json

    try:
        with open(_asked_path(research), encoding="utf-8") as fh:
            return json.load(fh).get("pass")
    except (OSError, ValueError, AttributeError):
        return None


def after_apply(ctx, research_id, r):
    """WS5-T2: the answer of an apply accepted in a project linked to its workshop carries
    WORKSHOP_NEW and WORKSHOP_DIVERGENT; with ``workshop.sync = ask`` the first apply of a
    pass that leaves new facts asks workshop_push (the answer it returns instead of ``r``),
    with ``auto`` the new facts are pushed, never the divergent ones. Nothing in a project
    without workshop, nor with ``off``."""
    import json
    import os

    from probandia import questions
    from probandia import workshop as ws
    from probandia.lifecycle import current_pass
    from probandia.research import find_research

    link = ws.load(ctx.project)
    mode = ctx.config.get("workshop.sync") or "ask"
    if link is None:
        return r
    guide(ctx, r)
    if mode == "off":
        return r
    research = find_research(ctx.project, research_id, ctx.environ)
    state = ws.State(ctx.project, link, research.id)
    new = state.counts["new"]
    r.set("WORKSHOP_NEW", new)
    r.set("WORKSHOP_DIVERGENT", state.counts["divergent"])
    if not new:
        return r
    if mode == "auto":
        pushed = push(ctx, link, research.id, confirm=False)
        done = pushed.values.get("PUSHED") or 0
        r.set("WORKSHOP_PUSHED", done)
        r.set("WORKSHOP_NEW", new - done)
        r.lines += pushed.lines
        return r
    n = current_pass(research)
    if asked_in_pass(research) == n:
        r.line(_("{n} new fact(s) of this research are not in the workshop yet: workshop push").format(n=new))
        return r
    os.makedirs(research.work, exist_ok=True)
    with open(_asked_path(research), "w", encoding="utf-8") as fh:
        json.dump({"pass": n}, fh)
    q = guide(ctx, questions.ask(["workshop_push"], actor(ctx)["harness"], dict(r.values)))
    q.lines = [_("ask the user, once in this pass; push: run workshop push {research}; later: nothing now, but pass "
                 "end refuses to close while the new facts are not in the workshop").format(research=research.id)]
    return q


def link_research(ctx, link):
    from probandia import questions
    from probandia import workshop as ws
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    folder = ws.root(ctx.project, link)
    harness = actor(ctx)["harness"]
    known = link["researches"].get(research.id)
    a = ctx.args
    if known and not (a.report or a.volet or a.chapitre):
        return Result("OK", {"RESEARCH": research.id, "RAPPORT": known["rapport"], "ORIGINE": known["origine"],
                             "VOLET": known.get("volet"), "CHAPITRE": known.get("chapitre"), "CHANGED": False})
    names = dict(ws.reports(folder))
    report = a.report or (known or {}).get("rapport")
    if not report:
        if questions.headless(ctx.environ):
            raise UsageError(_("give the report with --report: a headless run never chooses it"),
                             values={"REASON": "report-needed"})
        return questions.ask(["workshop_report"], harness, {"RESEARCH": research.id},
                             given={"workshop_report": list(names) + ["new"]})
    if report == "new":
        raise UsageError(_("create the report's folder in rapports/ with the workshop's own tool "
                           "(outils/nouveau_rapport.py), then link the research to it"),
                         values={"REASON": "no-report"})
    if report not in names:
        raise UsageError(_("no report {name} in {folder}: {known}").format(
            name=report, folder="rapports/", known=", ".join(names) or "-"), values={"REASON": "unknown-report"})
    volet, chapitre = a.volet or (known or {}).get("volet"), a.chapitre or (known or {}).get("chapitre")
    if not volet or not chapitre:
        last_volet, last_chapitre = ws.last_markers(folder, report, names[report])
        missing = [q for q, v in (("workshop_volet", volet), ("workshop_chapitre", chapitre)) if not v]
        if questions.headless(ctx.environ):
            if not (last_volet and last_chapitre):
                raise UsageError(_("give --volet and --chapitre: the report has no fact to take them from"),
                                 values={"REASON": "markers-needed"})
            volet, chapitre = volet or last_volet, chapitre or last_chapitre
        else:
            return questions.ask(missing, harness, {"RESEARCH": research.id, "REPORT": report},
                                 given={"workshop_volet": [last_volet] if last_volet else [],
                                        "workshop_chapitre": [last_chapitre] if last_chapitre else []})
    entry = {"rapport": report, "origine": names[report],
             "volet": _roman(volet, "--volet"), "chapitre": _roman(chapitre, "--chapitre")}
    link["researches"][research.id] = entry
    ws.save(ctx.project, link)
    return Result("OK", {"RESEARCH": research.id, "RAPPORT": report, "ORIGINE": entry["origine"],
                         "VOLET": entry["volet"], "CHAPITRE": entry["chapitre"], "CHANGED": True})
