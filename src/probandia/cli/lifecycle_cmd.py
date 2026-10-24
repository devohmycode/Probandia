"""The life of a research: new, resume, pass, digest, fork, verify, status, import."""
import os

from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import EXIT_FAIL, NotInProject, UsageError
from probandia.i18n import _

EFFORTS = ("low", "medium", "high", "xhigh", "max")
DIGEST_SHOWN = 34


def _run_options(p):
    p.add_argument("--mode", choices=("session", "subagent", "team"), help=_("who runs the research"))
    p.add_argument("--model", help=_("model of the subagent"))
    p.add_argument("--effort", choices=EFFORTS, help=_("effort of the subagent or the team"))
    p.add_argument("--agents", type=int, help=_("agents in a team"))
    p.add_argument("--passes", type=int, help=_("passes a team may run"))
    p.add_argument("--instructions", action="append", default=[], help=_("instructions for this pass"))
    p.add_argument("--prompt-lang", metavar="<tag>", help=_("language the agent reads in the prompt"))
    parallel_option(p)


def parallel_option(p):
    p.add_argument("--parallel", type=int, metavar="<n>", help=_("web searches run in parallel (1 to 8)"))


def _expiry(ctx):
    return ctx.config.get("locks.expiry_minutes")


def _launch(ctx, meta_run, values, question=None, family=None):
    """(run, assumed, ask result or None): the run block, with the launch questions
    asked together, or their defaults taken in a headless run. The defaults of the
    mode and the effort come from how hard the question looks (optimize 2.12)."""
    from probandia import complexity, lifecycle, questions
    from probandia.harness import CAPABILITIES

    harness = actor(ctx)["harness"]
    run, missing = lifecycle.run_options(ctx.args, ctx.config, meta_run, harness)
    if not missing:
        return run, False, None
    if questions.headless(ctx.environ):
        run = questions.assume(run, missing)
        run, still = lifecycle.run_options(ctx.args, ctx.config, run, harness)
        return questions.assume(run, still), True, None
    guess = complexity.estimate(ctx.project, family, question or "")
    r = questions.ask(missing, harness, values, defaults={"run_mode": guess["mode"], "run_effort": guess["effort"],
                                                          "team_effort": guess["effort"]})
    r.set("DIFFICULTY", guess["level"])
    # only a harness with model aliases (Claude Code) can switch: the person does it, with /model
    model = guess["model"] if guess["model"] in CAPABILITIES.get(harness, {}).get("models", ()) else None
    if model:
        r.set("SUGGESTED_MODEL", model)
    r.data("difficulty", f"{guess['level']} score={guess['score']} {' '.join(guess['reasons']) or '-'}: "
                         f"suggested {guess['mode']}, effort {guess['effort']}" + (f", model {model}" if model else ""))
    return run, False, r


# new


def new_args(p, common):
    p.add_argument("question", nargs="?", help=_("the research question"))
    p.add_argument("--family", help=_("family slug"))
    p.add_argument("--report-mode", choices=("journal", "living"))
    p.add_argument("--numbering", choices=("arabic", "roman", "roman-outline"))
    p.add_argument("--format", dest="formats", help=_("comma-separated formats: md, html, json"))
    opening = p.add_mutually_exclusive_group()
    opening.add_argument("--no-pass", action="store_true",
                         help=_("create the research without opening pass 1 (the default at a terminal)"))
    opening.add_argument("--open-pass", action="store_true", help=_("open pass 1 now, even at a terminal"))
    p.add_argument("--workshop", choices=("import", "ignore"),
                   help=_("when the folder is a prototype workshop never imported: import it first, or ignore it"))
    _run_options(p)


def _workshop(ctx, project):
    """(values, lines, ask result or None) for a project folder that is a prototype
    workshop never imported: the research would otherwise start blind to it. A
    headless run imports nothing and says so."""
    from probandia import questions
    from probandia.importer import Import, workshop_pending

    if not workshop_pending(project):
        return {}, [], None
    choice = ctx.args.workshop
    if choice is None and not questions.headless(ctx.environ):
        return {}, [], questions.ask(["workshop"], actor(ctx)["harness"], {"WORKSHOP": "pending"})
    if choice != "import":
        return {"WORKSHOP": "ignored"}, [_("this folder is a prototype workshop that was never imported; "
                                           "to start from what it establishes: probandia import .")], None
    imp = Import(project, project, None, actor(ctx)).run()
    path = imp.write()
    return ({"WORKSHOP": "imported", "IMPORTED_FAMILY": imp.family, "IMPORTED_PERSONS": len(imp.persons),
             "IMPORTED_RESEARCHES": len(imp.researches), "NOT_CONVERTED": len(imp.notes),
             "IMPORT_REPORT": os.path.relpath(path, project).replace(os.sep, "/")},
            [_("the workshop is imported: {persons} persons and {researches} closed researches in the family "
               "{family}; read the import report before the first pass").format(
                persons=len(imp.persons), researches=len(imp.researches), family=imp.family)], None)


def new(ctx):
    from probandia import lifecycle, questions
    from probandia.cli.report_cmd import report_language
    from probandia.project import create_project
    from probandia.research import create_research
    from probandia.util.ids import is_slug

    try:
        project = ctx.project
    except NotInProject:
        create_project(ctx.cwd)
        ctx._project = project = os.path.abspath(ctx.cwd)
    question = (ctx.args.question or "").strip()
    if not question:
        raise UsageError(_("give the research question"))
    workshop, workshop_lines, asking = _workshop(ctx, project)
    if asking:
        return asking
    run, assumed, asking = _launch(ctx, None, {}, question, ctx.args.family)
    if asking:
        return asking
    family = ctx.args.family
    if family and not is_slug(family):
        raise UsageError(_("invalid family name {name}").format(name=family))
    if not family:
        family, candidates = lifecycle.infer_family(project, question)
        if family is None:
            if questions.headless(ctx.environ) and candidates:
                family, assumed = candidates[0], True
            else:
                return questions.ask(["family"], actor(ctx)["harness"], {},
                                     given={"family": candidates or ["family"]})
    lang, source = report_language(ctx, {})
    created = lifecycle.create_family(project, family, question, lang)
    me = actor(ctx)
    research = create_research(project, family, question, lang, me, ctx.config,
                               instructions=ctx.args.instructions)
    formats = [f.strip() for f in (ctx.args.formats or "").split(",") if f.strip()]
    changes = {"run": run}
    if ctx.args.report_mode:
        changes["mode"] = ctx.args.report_mode
    if ctx.args.numbering:
        changes["numbering"] = ctx.args.numbering
    if formats:
        changes["formats"] = formats
    meta = lifecycle.update_meta(research, **changes)
    # Nobody runs a pass at a terminal: a person creates the research there, then
    # resumes it in their agent (cli.md 5.11.1).
    if ctx.args.no_pass or (ctx.human and not ctx.args.open_pass):
        r = Result("OK", {"RESEARCH": research.id, "FAMILY": family, "FAMILY_CREATED": bool(created), "PASS": 0,
                          "LANG": lang, "LANG_SOURCE": source, "MODE": meta["mode"], "RUN_MODE": run["mode"],
                          "FORMATS": ",".join(meta["formats"]), "NEXT": f"/probandia:resume {research.id}",
                          **workshop})
        r.lines += workshop_lines
        r.line(_("no pass is open yet; in your agent, run: /probandia:resume {id}").format(id=research.id))
        r.view = "new"
        return r.table("research", [_record(r)], hidden=True)
    n = lifecycle.start_pass(project, research, me, _expiry(ctx), run, ctx.args.instructions, assumed=assumed)
    r = Result("OK", {"RESEARCH": research.id, "FAMILY": family, "FAMILY_CREATED": bool(created), "PASS": n,
                      "LANG": lang, "LANG_SOURCE": source, "MODE": meta["mode"], "RUN_MODE": run["mode"],
                      "FORMATS": ",".join(meta["formats"]), **workshop})
    if assumed:
        r.set("ASSUMED", True)
    r.lines += workshop_lines
    from probandia.cli.workshop_cmd import guide

    guide(ctx, r)
    if run["mode"] == "subagent":   # the orchestrator subagent runs them in its own context
        r.line(_("pass {n} is open; next: known, then plan").format(n=n))
        return r.table("research", [_record(r)], hidden=True)
    try:
        _known_and_plan(ctx, research, n, r)
    except Exception as err:   # noqa: BLE001 — the research and its pass exist: never answer as if new failed
        r.status = "WARN"
        r.line(_("pass {n} is open; next: known, then plan").format(n=n))
        r.data("known_plan", f"failed {type(err).__name__}: {err}"[:200])
    return r.table("research", [_record(r)], hidden=True)


# the plan's keys that new repeats: those the research skill reads, and what the plan holds; T67: the native
# searches the skill counts, and no PLACES=, the count of the places= line that comes with them
NEW_PLAN_KEYS = ("TYPE", "WINDOW", "WINDOW_BASIS", "ANCHOR", "PLACE_CODES", "PLACES_UNKNOWN", "CALLS", "MATRIX_TODO",
                 "FOCUS", "QUOTA_LOW", "LOGIN_NEEDED", "BROWSER_GUIDED", "NATIVE_PARALLEL", "NATIVE_LEFT")
# T67: the plan's lines new repeats, so that the agent never opens work/new-<n>.txt for them (6 times in 9 runs)
NEW_PLAN_LINES = ("matrix=", "names=", "places=", "record_types=")


def _known_and_plan(ctx, research, n, r):
    """token-economy B1: the first two steps of the pass, run by new: plan, then known on the plan's
    names, places and window. Their keys here, their lines after new's, all of both in DETAILS."""
    import re

    from probandia.cli.data_cmd import known_result
    from probandia.cli.search_cmd import plan_result
    from probandia.util.fs import atomic_write_text

    doc, planned = plan_result(ctx, research)
    axes = doc["axes"]
    w = axes["window"]
    found = known_result(ctx, research.family, axes["names"], axes["places"],
                         (w["from"], w["to"]) if w.get("from") else None)
    for key in ("FACTS", "NEGATIVES", "NEGATIVES_DUE", "HYPOTHESES", "GAPS"):
        r.set("KNOWN_" + key, found.values[key])
    for key in NEW_PLAN_KEYS:
        if key in planned.values:
            r.set(key, planned.values[key])
    path = os.path.join(research.work, f"new-{n}.txt")
    atomic_write_text(path, found.render_text(max_lines=None) + planned.render_text(max_lines=None))
    r.details = os.path.relpath(path, ctx.project).replace(os.sep, "/")
    r.line(_("pass {n} is open; known and plan are done").format(n=n))   # the research skill says the rest
    r.lines += [x for x in planned.lines if x.startswith(NEW_PLAN_LINES) or not re.match(r"[a-z_]+=", x)]
    r.lines += sorted(found.lines, key=lambda x: x.startswith("fact="))   # facts last: the 40-line cap cuts them first


# resume


def resume_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--interrupted", choices=("continue", "close"),
                   help=_("what to do with an interrupted pass"))
    _run_options(p)


def _digest_result(ctx, research, values, write_as=None, differential=False):
    """The digest; with ``differential``, a session that already received one for
    this research gets only what changed (optimize 2.13). DETAILS keeps it whole."""
    from probandia import digest
    from probandia.cli.data_cmd import actor
    from probandia.util.fs import atomic_write_text

    lines = digest.lines_for(ctx.project, research, ctx.config, ctx.environ)
    r = Result("OK", values)
    r.set("DIGEST_LINES", len(lines))
    session = actor(ctx)["session"]
    previous = digest.seen(ctx.project, session, research.id) if differential else None
    digest.seen(ctx.project, session, research.id, lines)
    shown = digest.differential(previous, lines) if previous else lines[:DIGEST_SHOWN]
    r.set("DIGEST", "changes" if previous else "full")
    if write_as:
        path = os.path.join(research.work, write_as)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_text(path, "\n".join(lines) + "\n")
        r.details = os.path.relpath(path, ctx.project).replace(os.sep, "/")
    for line in shown:
        r.lines.append(line)
    return r.table("digest", [{"line": line} for line in lines], hidden=True)


def resume(ctx):
    from probandia import events, lifecycle, questions
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    meta = research.meta() or {}
    me = actor(ctx)
    log = events.read(research.events_path)
    last, open_ = lifecycle.pass_state(log)
    if open_:
        choice = ctx.args.interrupted
        if choice is None and questions.headless(ctx.environ):
            choice = "continue"
        if choice is None:
            return questions.ask(["interrupted_pass"], me["harness"], {"RESEARCH": research.id, "PASS": last})
        lifecycle.take_research_lock(ctx.project, research, me, _expiry(ctx))
        if choice == "continue":
            lifecycle.add_instructions(research, last, ctx.args.instructions)
            return _guided(ctx, _digest_result(ctx, research, {"RESEARCH": research.id, "PASS": last,
                                                               "CONTINUED": True}, f"digest-{last}.txt",
                                               differential=True))
        lifecycle.end_pass(ctx.project, research, me, _expiry(ctx), summary="interrupted")
    run, assumed, asking = _launch(ctx, meta.get("run"), {"RESEARCH": research.id}, meta.get("question"),
                                   research.family)
    if asking:
        return asking
    done = lifecycle.pass_state(events.read(research.events_path))[0]
    if run.get("mode") == "team" and run.get("max_passes") and done >= run["max_passes"]:
        return Result.stop("team-passes", "fork", values={"RESEARCH": research.id, "PASSES": done,
                                                          "MAX_PASSES": run["max_passes"]})
    if run != meta.get("run"):
        lifecycle.update_meta(research, run=run)
    lifecycle.add_instructions(research, done + 1, ctx.args.instructions)
    if (research.meta() or {}).get("status") != "open":
        lifecycle.update_meta(research, status="open")
    # the instructions of the pass about to open: those given now, and for pass 1 those
    # given to new --no-pass
    given = [i["text"] for i in (research.meta() or {}).get("instructions") or [] if i.get("pass") == done + 1]
    n = lifecycle.start_pass(ctx.project, research, me, _expiry(ctx), run, given, assumed=assumed)
    values = {"RESEARCH": research.id, "PASS": n, "RUN_MODE": run["mode"]}
    if assumed:
        values["ASSUMED"] = True
    return _guided(ctx, _digest_result(ctx, research, values, f"digest-{n}.txt", differential=True))


def _guided(ctx, r):
    from probandia.cli.workshop_cmd import guide

    return guide(ctx, r)


# digest


def digest_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))


def digest_cmd(ctx):
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    return _digest_result(ctx, research, {"RESEARCH": research.id}, "digest.txt")


# volet (FL-D8)


def volet_args(p, common):
    p.add_argument("action", choices=("open", "list"))
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--title", help=_("open: the volet's title"))
    p.add_argument("--established", action="append", default=[],
                   help=_("open: what the volet before established, one line each"))
    p.add_argument("--correction", action="append", default=[], help=_("open: a correction, one line each"))
    p.add_argument("--opening", action="append", default=[], help=_("open: what this volet takes on"))


def volet_cmd(ctx):
    from probandia import events, lifecycle
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    if ctx.args.action == "list":
        found = lifecycle.volets(events.read(research.events_path))
        r = Result("OK", {"RESEARCH": research.id, "VOLETS": len(found)})
        for v in found:
            r.data("volet", f"{v['n']} from pass {v['from_pass']}: {v['title']}")
        return r
    if not (ctx.args.title or "").strip():
        raise UsageError(_("a volet needs its title (--title)"))
    payload, short = lifecycle.open_volet(ctx.project, research, actor(ctx), _expiry(ctx), ctx.args.title,
                                          ctx.args.established, ctx.args.correction, ctx.args.opening)
    r = Result("OK", {"RESEARCH": research.id, "VOLET": payload["n"], "FROM_PASS": payload["from_pass"]})
    if short:
        r.status = "WARN"
        r.line(_("volet {n} holds only {k} pass(es): a volet of fewer than four chapters is almost always "
                 "premature").format(n=short[0], k=short[1]))
    return r


# pass


def pass_args(p, common):
    p.add_argument("action", choices=("end", "status"))
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--summary", default="", help=_("what the pass found, and its open leads"))
    p.add_argument("--native-searches", type=int, help=_("native searches made in the pass"))
    p.add_argument("--unrecorded", metavar="REASON",
                   help=_("end: why the transcriptions of this pass that no fact cites are left so"))
    p.add_argument("--defer-workshop", metavar="REASON",
                   help=_("end: why the new facts of this research do not go to the workshop in this pass"))


def _build_reminder(ctx, research, n, r):
    """WS6-T2: a pass of a linked research that pushed to the workshop recalls its build, once, at its end;
    the engine never runs it (a step of the workshop's, long, that rewrites its reports)."""
    from probandia import events
    from probandia import workshop as ws
    from probandia.cli.workshop_cmd import BUILDER

    if ws.load(ctx.project) is None:
        return
    if any(e["type"] == "workshop.pushed" and e["pass"] == n for e in events.read(research.events_path)):
        r.set("WORKSHOP_BUILD", BUILDER)
        r.line(_("the workshop changed in this pass: build it with its own tool, once, in its folder: "
                 "{command}").format(command=BUILDER))


def _workshop_rule(ctx, research):
    """WS5-T3, the workshop's rule 4 (« in the same pass »): with workshop.sync ask or auto, a pass of a
    linked project closes only once its research's new facts are in the workshop, or with
    --defer-workshop "<reason>", which the event keeps and the next digest shows as a lead. Returns
    what was deferred, or None."""
    from probandia import workshop as ws

    link = ws.load(ctx.project)
    if link is None or (ctx.config.get("workshop.sync") or "ask") == "off":
        return None
    new = ws.State(ctx.project, link, research.id).counts["new"]
    reason = (ctx.args.defer_workshop or "").strip()
    if not new:
        return None
    if not reason:
        raise UsageError(_("{n} new fact(s) of this research are not in the workshop: workshop push, or say why "
                           "not with --defer-workshop \"<reason>\" (the workshop's rule 4: in the same pass)").format(
            n=new), values={"REASON": "workshop-not-reported", "RESEARCH": research.id, "WORKSHOP_NEW": new})
    ctx.args.summary = "; ".join(x for x in (ctx.args.summary, _(
        "new facts not reported to the workshop ({n}): {reason}").format(n=new, reason=reason)) if x)
    return {"facts": new, "reason": reason}


def pass_cmd(ctx):
    from probandia import events, lifecycle
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    if ctx.args.action == "status":
        from probandia import tokens

        last, open_ = lifecycle.pass_state(events.read(research.events_path))
        r = Result("OK", {"RESEARCH": research.id, "PASS": last, "OPEN": open_})
        spent = tokens.pass_weighted(ctx.project, research.id, last)   # I2: what the pass has cost so far
        if spent is not None:
            r.set("TOKENS", spent)
        return r
    from probandia.proposals import pending, unsettled

    # J10: a proposal its dry run rejected, which no later one of its author replaced, counts too
    waiting = pending(research) + [f"{p} rejected" for p in unsettled(research)]
    if waiting:
        raise UsageError(_("{n} proposal(s) neither applied nor dropped: apply each one, or set it aside "
                           "with apply <proposal> --drop \"<reason>\"").format(n=len(waiting)),
                         values={"REASON": "pending-proposals", "RESEARCH": research.id, "PENDING": len(waiting)},
                         lines=[f"pending={p}" for p in waiting])
    # J12: an act read and transcribed in the pass, whose source no applied proposal brought in
    from probandia.proposals import applied_in_pass, unrecorded

    left = unrecorded(ctx.project, research)
    # T84: --unrecorded excuses a transcription too many, never a pass that applied no proposal at all
    if left and (ctx.args.unrecorded or "").strip() and not applied_in_pass(research):
        raise UsageError(_("this pass read acts and applied no proposal: propose what they prove, or a "
                           "negative or a hypothesis for an act that does not fit, before ending the pass"),
                         values={"REASON": "nothing-recorded", "RESEARCH": research.id, "UNRECORDED": len(left)},
                         lines=[f"transcription={s}" for s in left])
    if left and not (ctx.args.unrecorded or "").strip():
        raise UsageError(_("{n} transcription(s) of this pass cited by no fact of the family: propose what they "
                           "prove, or say why not with --unrecorded \"<reason>\"").format(n=len(left)),
                         values={"REASON": "unrecorded-transcriptions", "RESEARCH": research.id,
                                 "UNRECORDED": len(left)},
                         lines=[f"transcription={s}" for s in left])
    if left:   # the reason stays, as a lead of the next digest
        ctx.args.summary = "; ".join(x for x in (ctx.args.summary, _(
            "transcriptions not recorded ({sources}): {reason}").format(
            sources=", ".join(left), reason=ctx.args.unrecorded.strip())) if x)
    deferred = _workshop_rule(ctx, research)
    # B7: the report is rendered and checked here, and the pass closes only once the check passes
    from probandia import verify
    from probandia.cli.report_cmd import render_research

    rendered = render_research(ctx, research)
    if rendered.status not in ("OK", "WARN"):
        return Result("FAIL", {"REASON": "render", "RESEARCH": research.id, "RENDERED": rendered.status},
                      rendered.lines + [_("the pass stays open: run render, then pass end again")],
                      exit_code=EXIT_FAIL)
    results = verify.run(ctx.project, research, ctx.config, None, True)
    # T226: V-1 of this pass too, so that a pass with no plan is told at its close, not by a later verify; an
    # earlier pass's cannot be mended (the log is never rewritten), and is left to verify
    current = lifecycle.pass_state(events.read(research.events_path))[0]
    results = verify.run(ctx.project, research, ctx.config, ["V-1"], pass_no=current) + results
    log_verify(ctx, research, results, True)
    failed, earlier = [(rule, message) for rule, status, message in results if status == "FAIL"], []
    if failed:   # what an earlier pass left wrong is told, and holds only close: the pass's own errors block
        current = lifecycle.pass_state(events.read(research.events_path))[0]
        own = {rule: message for rule, status, message in verify.run(
            ctx.project, research, ctx.config, [rule for rule, _m in failed], pass_no=current) if status == "FAIL"}
        failed, earlier = [(rule, own[rule]) for rule, _m in failed if rule in own], \
            [(rule, m) for rule, m in failed if rule not in own]
    if failed:
        r = Result("FAIL", {"REASON": "verify", "RESEARCH": research.id, "RENDERED": rendered.status,
                            "VERIFY": "FAIL", "FAILED": len(failed)}, exit_code=EXIT_FAIL)
        for rule, message in failed:
            r.data(rule, f"FAIL {message}".rstrip())
        r.line(_("the pass stays open: fix these rules, then pass end again"))
        return r
    n, payload = lifecycle.end_pass(ctx.project, research, actor(ctx), _expiry(ctx), ctx.args.summary,
                                    ctx.args.native_searches,
                                    extra={"workshop_deferred": deferred} if deferred else None)
    r = Result("OK", {"RESEARCH": research.id, "PASS": n, "RENDERED": rendered.status, "VERIFY": "OK",
                      "NATIVE_SEARCHES": payload["native_searches"], "LOCK": "released",
                      "WORK_PURGED": tidy_work(ctx.project, research)})
    from probandia import transcription
    from probandia.indexes import FamilyIndexes

    folder = os.path.join(ctx.project, "families", research.family)
    doubtful = transcription.doubtful_names(FamilyIndexes(ctx.project, research.family).load("persons")["persons"],
                                            folder, research.id, n)
    if doubtful:   # T258: a doubt the reader marked must reach the user, not vanish from the reply
        r.set("DOUBTFUL_NAMES", len(doubtful))
        for line in doubtful[:5]:
            r.data("doubtful", line)
        r.line(_("in your reply, give each doubtful name with its reserve and its other reading"))
    if rendered.values.get("LABELS_MISSING"):   # T70: labels this pass's report asked for, still in English
        for key in ("LABELS_MISSING", "POT", "TARGET"):
            r.set(key, rendered.values[key])
    if earlier:
        r.status = "WARN"
        r.set("EARLIER_FAILED", len(earlier))
        for rule, message in earlier:
            r.data(rule, f"FAIL {message}".rstrip())
        r.line(_("these rules fail on what earlier passes brought: they did not hold this pass; plan their "
                 "repair in the next one, before close"))
    _build_reminder(ctx, research, n, r)
    tools = payload["tools"]
    for name in ("web", "mcp", "archive", "engine"):
        r.set("TOOLS_" + name.upper(), tools[name])
    if not tools["web"] and not tools["mcp"]:   # FL-D1: the first salvo always holds web searches
        r.status = "WARN"
        r.line(_("no web search and no MCP call in this pass: it is incomplete"))
    # optimize 5.1.4: what the library could keep, put to the user in one question
    from probandia import learning

    try:
        found = learning.candidates(ctx.project, research, n, ctx.environ)
    except Exception:   # noqa: BLE001 — the library never stops a pass from closing (J11: it did, once)
        found = []
    r.set("LEARN_CANDIDATES", len(found))
    for kind, detail in found[:8]:
        r.data("learn", f"{kind} {detail}")
    # optimize 5.2.8: the pass's decisions worth keeping in AGENTS.md, in the same question
    from probandia import memory

    try:
        kept = memory.candidates(ctx.project, research.id)
    except Exception:   # noqa: BLE001 — the memory never stops a pass from closing
        kept = []
    r.set("MEMORY_CANDIDATES", len(kept))
    for kind, detail in kept[:4]:
        r.data("memory", f"{kind} {detail}")
    if found or kept:   # token-economy H2: no question without a candidate to put in it
        r.line(_("ask the user once, in one question, which of these to keep: the library's candidates, and the "
                 "pass's decisions for AGENTS.md (conventions, template, providers, sign-ins, preferences, pitfalls; "
                 "never a fact, a living person or a key); then library save, draft or promote, and memory add, "
                 "each one they choose"))
    # a heavy base costs more than the research itself: say it once a pass, for the user
    from probandia import tokens
    from probandia.doctor import heavy_base_line

    base = tokens.base_context(ctx.project)
    if base and base[0] > tokens.BASE_HEAVY:
        r.set("CONTEXT_BASE", base[0])
        r.line(heavy_base_line(base[0]))
    return r


IMAGES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff")


def tidy_work(project, research):
    """token-economy H4: at the end of a pass, the images of ``work/`` that no source and no transcription
    cites (views, bands, sheets, crops) are removed; the count is returned. An image counts as cited when
    its file name appears in a source's ``image`` or ``images`` (T247) or in a Markdown or YAML file of the
    family's evidence or of ``work/`` (transcriptions, proposals): a name too common keeps an image, never
    removes one."""
    import re

    from probandia.images import views
    from probandia.indexes import FamilyIndexes

    found = [os.path.join(d, f) for d, _s, files in os.walk(research.work) for f in files if f.lower().endswith(IMAGES)]
    if not found:
        return 0
    texts = [str(v) for s in FamilyIndexes(project, research.family).items("sources") for v in views(s)]
    for root in (os.path.join(project, "families", research.family, "evidence"), research.work):
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x != "details"]   # pages read and digests cite nothing
            for f in files:
                if f.lower().endswith((".md", ".yaml", ".yml")):
                    with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                        texts.append(fh.read())
    cited = "\n".join(texts)
    purged = 0
    for path in found:
        if re.search(rf"(?<![\w.-]){re.escape(os.path.basename(path))}(?![\w.-])", cited, re.I):
            continue
        try:
            os.remove(path)
            purged += 1
        except OSError:   # a file still open elsewhere stays for the next pass end
            pass
    return purged


# fork


def fork_args(p, common):
    p.add_argument("research", help=_("research id or unique prefix"))
    p.add_argument("--at", type=int, help=_("the pass to fork from (default: the last one)"))
    p.add_argument("--name", help=_("slug of the fork"))
    p.add_argument("--new-family", help=_("copy the family into a new one"))
    p.add_argument("--instructions", action="append", default=[], help=_("instructions for the fork"))
    p.add_argument("--no-pass", action="store_true", help=_("do not open the fork's next pass"))


def fork_cmd(ctx):
    from probandia import lifecycle
    from probandia.cli.report_cmd import render_research
    from probandia.fork import fork
    from probandia.research import find_research

    parent = find_research(ctx.project, ctx.args.research, ctx.environ)
    me = actor(ctx)
    child, at = fork(ctx.project, parent, ctx.args.at, ctx.args.name, ctx.args.new_family,
                     ctx.args.instructions, me)
    rendered = render_research(ctx, child)
    r = Result("OK", {"RESEARCH": child.id, "FAMILY": child.family, "FORKED_FROM": parent.id, "AT": at,
                      "RENDERED": rendered.status})
    if not ctx.args.no_pass:
        n = lifecycle.start_pass(ctx.project, child, me, _expiry(ctx), (child.meta() or {}).get("run"),
                                 ctx.args.instructions)
        r.set("PASS", n)
        r.line(_("pass {n} is open; next: digest, then plan").format(n=n))
    return r.table("research", [_record(r)], hidden=True)


# verify


def verify_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--light", action="store_true", help=_("the light rules only"))
    p.add_argument("--all", action="store_true", help=_("list every rule, not only those that fail"))
    p.add_argument("--rule", action="append", default=[], help=_("one rule, such as V-3"))
    p.add_argument("--standard", action="store_true",
                   help=_("the five elements of the Genealogical Proof Standard, question by question"))


def standard_result(ctx, research):
    """``verify --standard`` (GPS8-T1): each question, its five elements and what each lacks. With
    proof.standard strict, a question that does not conform is a failure (GPS-D13); else a warning."""
    from probandia.proof import confidence as C
    from probandia.proof import standard as S

    found = S.of_research(ctx.project, research, strict=ctx.config.get("proof.standard") == "strict")
    n = S.counts(found)
    strict = (ctx.config.get("proof.standard") or "off") == "strict"
    status = "OK" if n["conform"] == len(found) else "FAIL" if strict and n["not_conform"] else "WARN"
    r = Result(status, {"RESEARCH": research.id, "QUESTIONS": len(found), "CONFORM": n["conform"],
                        "PARTIAL": n["partial"], "NOT_CONFORM": n["not_conform"]},
               exit_code=EXIT_FAIL if status == "FAIL" else None)
    rows, lacks = [], []
    for q in found:
        els = q["elements"]
        r.data(q["question"], " ".join([q["level"]] + [f"{k}={els[k]['state']}" for k in S.ELEMENTS]))
        conf = q.get("confidence")
        rows.append(dict({"question": q["question"], "status": q["status"], "level": q["level"]},
                         **{k: els[k]["state"] for k in S.ELEMENTS},
                         confidence=conf["name"] if conf else None,
                         reasons=[C.describe(x, _) for x in conf["reasons"]] if conf else []))
        if conf:   # TRUST3-T2: the confidence of the conclusion, and what holds it down
            r.data(f"{q['question']}.confidence", " ".join([conf["name"]] + [S.short(x) for x in conf["reasons"]]))
        for k in S.ELEMENTS:
            for lack in els[k]["lacks"]:
                r.data(f"{q['question']}.{k}", S.short(lack))
                lacks.append({"question": q["question"], "element": k, "state": els[k]["state"],
                              "lacks": S.describe(lack, _), "why": lack["why"], "ids": lack["ids"]})
    if not found:
        r.line(_("the research has no question"))
    r.table("questions", rows)
    r.table("lacks", lacks)
    r.view = "standard"
    return r


def verify_cmd(ctx):
    from probandia import verify
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    if ctx.args.standard:
        return standard_result(ctx, research)
    rules = [r.upper() for r in ctx.args.rule]
    unknown = [r for r in rules if r not in verify.RULES]
    if unknown:
        raise UsageError(_("unknown rule {rule}; rules: V-1 to {last}").format(rule=unknown[0], last=verify.RULES[-1]))
    results = verify.run(ctx.project, research, ctx.config, rules or None, ctx.args.light)
    failed = [rule for rule, status, _m in results if status == "FAIL"]
    r = Result("FAIL" if failed else "OK", {"RESEARCH": research.id, "RULES": len(results),
                                            "FAILED": len(failed)},
               exit_code=EXIT_FAIL if failed else None)
    for rule, status, message in results:   # F2: the rules that fail; every one with --all or --rule
        if status != "PASS" or ctx.args.all or rules:
            r.data(rule, f"{status} {message}".rstrip())
    r.table("rules", [{"rule": rule, "status": status, "detail": message} for rule, status, message in results])
    r.view = "verify"
    if not log_verify(ctx, research, results, ctx.args.light):
        r.line(_("the result was not written to the log: the research is locked"))
    return r


def log_verify(ctx, research, results, light):
    """Step 11 of a pass: an open pass logs the result. False when the research is locked."""
    from probandia import events, lifecycle
    from probandia.errors import LockHeld
    from probandia.indexes import locked

    last, open_ = lifecycle.pass_state(events.read(research.events_path))
    if not open_:
        return True
    try:
        with locked(ctx.project, f"research:{research.id}", actor(ctx), _expiry(ctx), wait_seconds=5):
            # A pass end run at the same time may have closed the pass while we waited.
            if lifecycle.pass_state(events.read(research.events_path)) == (last, True):
                events.append(research.events_path, [events.make(
                    "verify.run", {"results": {rule: status for rule, status, _m in results},
                                   "light": bool(light)}, actor(ctx), last)])
    except LockHeld:
        return False
    return True


# close (GPS1-T4)


def close_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))


def close_cmd(ctx):
    """Closes a research once its pass is ended and every question is answered or
    unresolved. verify runs first: with proof.standard strict a failed rule refuses
    the closing; with warn, the person confirms it; with off, it is reported."""
    from probandia import events, lifecycle, verify
    from probandia.cli import asking
    from probandia.indexes import locked
    from probandia.proof import questions as Q
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    meta = research.meta() or {}
    if meta.get("status") == "closed":
        return Result("OK", {"RESEARCH": research.id, "CLOSED": True},
                      [_("the research is already closed; resume opens it again")]).table("rules", [], RULE_COLUMNS,
                                                                                           hidden=True)
    last, open_ = lifecycle.pass_state(events.read(research.events_path))
    if open_:
        raise UsageError(_("pass {n} is still open: close it first (pass end)").format(n=last),
                         values={"REASON": "pass-open", "RESEARCH": research.id, "PASS": last})
    still = Q.unsettled(meta)
    if still:
        raise UsageError(_("{n} question(s) still open: answer each one (question answer), or set it aside "
                           "with question unresolved <Q> --reason \"<why>\"").format(n=len(still)),
                         values={"REASON": "open-questions", "RESEARCH": research.id, "OPEN": len(still)},
                         lines=[f"open={q['id']} {q['text']}" for q in still])
    standard = ctx.config.get("proof.standard") or "off"
    results = verify.run(ctx.project, research, ctx.config)
    failed = [rule for rule, status, _m in results if status == "FAIL"]
    if failed and standard == "strict":
        r = Result("FAIL", {"RESEARCH": research.id, "REASON": "verify-failed", "STANDARD": standard,
                            "FAILED": len(failed)}, exit_code=EXIT_FAIL)
        r.table("rules", _rule_rows(results), RULE_COLUMNS, hidden=True)
        for rule, status, message in results:
            if status != "PASS":
                r.data(rule, f"{status} {message}".rstrip())
        r.line(_("proof.standard is strict: the research closes once verify passes"))
        return r
    if standard == "strict":   # GPS-D13: every question conforms to the GPS, or is at least partly conform
        from probandia.proof import standard as S

        bad = [q for q in S.of_research(ctx.project, research, meta, strict=True) if q["level"] == "not_conform"]
        if bad:
            r = Result("FAIL", {"RESEARCH": research.id, "REASON": "not-conform", "STANDARD": standard,
                                "NOT_CONFORM": len(bad)}, exit_code=EXIT_FAIL)
            for q in bad:
                r.data(q["question"], " ".join(f"{k}={e['state']}" for k, e in q["elements"].items()
                                               if e["state"] == "missing"))
            r.line(_("proof.standard is strict: every question conforms to the Genealogical Proof Standard "
                     "before the research closes; verify --standard shows what is missing"))
            return r
    if failed and standard == "warn" and not asking.confirm(
            ctx, _("verify finds {n} failed rule(s): {rules}. Close the research anyway?").format(
                n=len(failed), rules=", ".join(failed))):
        return Result("OK", {"RESEARCH": research.id, "CLOSED": False},
                      [_("the research stays open")]).table("rules", _rule_rows(results), RULE_COLUMNS, hidden=True)
    me = actor(ctx)
    with locked(ctx.project, f"research:{research.id}", me, ctx.config.get("locks.expiry_minutes") or 30,
                wait_seconds=5):
        lifecycle.update_meta(research, status="closed")
        events.append(research.events_path, [events.make(
            "research.closed", {"standard": standard, "failed": failed,
                                "questions": {q["id"]: q.get("status", "open") for q in Q.of(meta)}}, me, last)])
    warned = [x for x in results if x[1] != "PASS"]
    r = Result("WARN" if warned else "OK", {"RESEARCH": research.id, "CLOSED": True, "STANDARD": standard,
                                             "FAILED": len(failed)})
    for rule, status, message in warned:
        r.data(rule, f"{status} {message}".rstrip())
    if failed:
        r.line(_("closed with {n} failed rule(s) of verify; resume opens the research again").format(n=len(failed)))
    return r.table("rules", _rule_rows(results), RULE_COLUMNS, hidden=True)


RULE_COLUMNS = ("rule", "status", "message")


def _record(r):
    """The values of a command about one research, as its record in ``data`` (T111)."""
    return {k.lower(): v for k, v in r.values.items()}


def _rule_rows(results):
    return [dict(zip(RULE_COLUMNS, x)) for x in results]


# status


def status_args(p, common):
    from probandia.cli.human import watch_option

    p.add_argument("research", nargs="?", help=_("a research: also the tokens of its last pass, by role"))
    p.add_argument("--family", help=_("family slug"))
    watch_option(p)


def status_cmd(ctx):
    """Families, researches, passes, locks, quotas: research.yaml, the events and
    the ledger only, never a report."""
    from probandia import events, lifecycle
    from probandia.cli.search_cmd import _ledger
    from probandia.providers import catalogue
    from probandia.research import all_researches
    from probandia.util.locks import Locks

    fams = lifecycle.families(ctx.project)
    if ctx.args.family and ctx.args.family not in fams:
        from probandia.suggest import lines

        raise UsageError(_("no family {family} in this project").format(family=ctx.args.family),
                         lines=lines(ctx.args.family, fams))
    researches = [r for r in all_researches(ctx.project) if not ctx.args.family or r.family == ctx.args.family]
    r = Result("OK", {"FAMILIES": len(fams), "RESEARCHES": len(researches)})
    family_rows, research_rows, lock_rows = [], [], []
    for fid in sorted(fams):
        if not ctx.args.family or fid == ctx.args.family:
            n = sum(1 for x in researches if x.family == fid)
            r.data("family", f"{fid} {n} researches")
            family_rows.append({"family": fid, "researches": n})
    for res in researches:
        meta = res.meta() or {}
        log = events.read(res.events_path)
        last, open_ = lifecycle.pass_state(log)
        state = f"pass {last} open" if open_ else f"{meta.get('passes', last)} passes"
        r.data("research", f"{res.id} [{meta.get('status', 'open')}] {state} {meta.get('mode', 'journal')} "
                           f"{meta.get('language', '?')}")
        started = [e["ts"] for e in log if e["type"] == "pass.started" and e["pass"] == last]
        standard = None
        if meta.get("questions"):   # GPS8-T1: how many questions conform to the GPS
            from probandia.proof import standard as S

            standard = S.counts(S.of_research(ctx.project, res, meta,
                                              strict=ctx.config.get("proof.standard") == "strict"))
            r.data("standard", f"{res.id} " + " ".join(f"{k}={n}" for k, n in standard.items()))
        research_rows.append({"research": res.id, "family": res.family, "status": meta.get("status", "open"),
                              "passes": meta.get("passes", last), "open_pass": last if open_ else None,
                              "open_since": started[-1] if open_ and started else None,
                              "mode": meta.get("mode", "journal"), "language": meta.get("language"),
                              "last_activity": log[-1]["ts"] if log else meta.get("created"),
                              "standard": standard})
    locks = Locks(ctx.project, expiry_minutes=_expiry(ctx))
    folder = os.path.join(ctx.project, ".probandia", "locks")
    held = 0
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        scope = name[:-5]
        info, expired = locks.status(scope)
        if info is not None and not expired:
            held += 1
            d = locks.describe(scope, info)
            r.data("lock", f"{scope} {d['HOLDER']} until {d['EXPIRES']}")
            lock_rows.append({"scope": scope, "holder": d["HOLDER"], "expires": d["EXPIRES"]})
    r.set("LOCKS", held)
    r.table("families", family_rows, ["family", "researches"])
    r.table("researches", research_rows)
    r.table("locks", lock_rows, ["scope", "holder", "expires"])
    ledger = _ledger(ctx)
    lefts = []
    for provider in catalogue.usable(ctx.config, ctx.environ):
        left = ledger.left(provider, ctx.config.get("budget.reserve_percent"))
        if left is not None:
            lefts.append((left, provider))
    for left, provider in sorted(lefts, key=lambda x: (-x[0], x[1]))[:5]:
        r.data("quota", f"{provider} {left:,.0f} left")
    r.table("lowest_accounts", _lowest_accounts(ctx, ledger))
    # optimize 3.11: the sessions the user opened in the browser, and those that ended
    from probandia import logins

    sessions = logins.load(ctx.project)
    for archive, record in sorted(sessions.items()):
        r.data("login", f"{archive} {record.get('state')} {record.get('ts')}"
                        + (f" expired={record['expired']}" if record.get("expired") else ""))
    if sessions:
        r.table("logins", [{"archive": a, "state": x.get("state"), "since": x.get("ts"),
                            "confirmed": x.get("confirmed"), "expired": x.get("expired")}
                           for a, x in sorted(sessions.items())])
    if ctx.args.research:
        _tokens_lines(ctx, r)
    r.view = "status"
    return r


def _lowest_accounts(ctx, ledger, n=5):
    """The ready accounts with the smallest share left: the readable output and
    --json show them; the contract keeps its five largest (SPECS § 5.9)."""
    from probandia.cli.usage_cmd import _pays
    from probandia.providers import accounts, catalogue

    found = accounts.accounts(catalogue.load(), ledger, ctx.config, ctx.environ,
                              ctx.config.get("budget.reserve_percent"))
    ready = [a for a in found if a["state"] == "ready" and a["fraction"] is not None]
    return [{"account": a["name"], "left": f"{round(a['fraction'] * 100)} %", "pays for": _pays(a)}
            for a in sorted(ready, key=lambda a: (a["fraction"], a["account"]))[:n]]


def _tokens_lines(ctx, r):
    """The tokens of the research's last measured pass, by role (``tokens``)."""
    from probandia import tokens
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    pass_no, roles = tokens.by_role(ctx.project, research.id)
    r.set("TOKENS_PASS", pass_no if pass_no is not None else "none")
    rows = []
    for role, t in sorted(roles.items()):
        r.data("tokens", f"{role} input={t['input']} output={t['output']} cache_read={t['cache_read']} "
                         f"cache_write={t['cache_write']} weighted={tokens.weighted(t)}")
        rows.append({"role": role, "input": t["input"], "output": t["output"], "cache_read": t["cache_read"],
                     "cache_write": t["cache_write"], "weighted": tokens.weighted(t)})
    r.table("tokens", rows)


# import


def import_args(p, common):
    p.add_argument("workshop", help=_("folder of the workshop, the one that holds commun/personnes.yaml"))
    p.add_argument("--family", help=_("family slug"))
    p.add_argument("--dry-run", action="store_true", help=_("show the mapping, write nothing"))


def import_cmd(ctx):
    from probandia.importer import Import

    imp = Import(ctx.project, ctx.args.workshop, ctx.args.family, actor(ctx)).run()
    values = {"FAMILY": imp.family, "PERSONS": len(imp.persons),
              "FACTS": sum(len(p["facts"]) for p in imp.persons), "SOURCES": len(imp.sources),
              "SEARCHES": len(imp.searches), "HYPOTHESES": len(imp.hypotheses),
              "RESEARCHES": len(imp.researches), "CONNECTORS": len(imp.connectors),
              "NOT_CONVERTED": len(imp.notes)}
    if ctx.args.dry_run:
        r = Result("OK", dict(values, DRY_RUN=True))
        for note in imp.notes[:20]:
            r.line(note)
        return r.table("not_converted", [{"note": note} for note in imp.notes], ["note"], hidden=True)
    path = imp.write()
    values["NOT_CONVERTED"] = len(imp.notes)
    return Result("WARN" if imp.notes else "OK", values,
                  details=os.path.relpath(path, ctx.project).replace(os.sep, "/")).table(
        "not_converted", [{"note": note} for note in imp.notes], ["note"], hidden=True)


# team


def team_args(p, common):
    p.add_argument("action", choices=("wave", "budget", "send", "inbox"))
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--agents", type=int, default=1, help=_("agents in the wave"))
    p.add_argument("--to", help=_("the receiving agent"))
    p.add_argument("--from", dest="sender", help=_("the sending agent"))
    p.add_argument("--type", dest="msg_type", default="task", help=_("task, result, finding, question or stop"))
    p.add_argument("--body", default="", help=_("the message"))
    p.add_argument("--refs", default="", help=_("comma-separated references"))
    p.add_argument("--keep", action="store_true", help=_("show the messages again next time"))


def team_cmd(ctx):
    import json

    from probandia import team
    from probandia.budget import native_budget
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    action = ctx.args.action
    if action in ("wave", "budget"):
        b = native_budget(ctx.project, research, ctx.config, ctx.environ, actor(ctx)["harness"])
        max_agents, max_passes = team.caps(research, ctx.config)
        values = {"RESEARCH": research.id, "PASS": b["pass"], "MAX_AGENTS": max_agents,
                  "NATIVE_LEFT": b["left"], "PARALLEL": b["parallel"]}
        if action == "budget":
            from probandia.budget import split

            r = Result("OK", values)
            r.data("native", ",".join(str(n) for n in split(b["left"], ctx.args.agents)))
            return r
        try:
            wave = team.start_wave(research, ctx.config, ctx.args.agents, b["left"])
        except team.TeamCap as err:
            return Result.stop("team-agents", str(err.cap), values=values)
        r = Result("OK", dict(values, WAVE=wave["wave"], AGENTS=wave["agents"]))
        r.data("native", ",".join(str(n) for n in wave["native"]))
        return r
    if action == "send":
        if not ctx.args.to:
            raise UsageError(_("team send needs --to"))
        msg = team.send(research, ctx.args.sender or ctx.args.agent or "orchestrator", ctx.args.to,
                        ctx.args.msg_type, ctx.args.body, [x for x in ctx.args.refs.split(",") if x])
        return Result("OK", {"RESEARCH": research.id, "TO": msg["to"], "TYPE": msg["type"]})
    agent = ctx.args.to or ctx.args.agent or "orchestrator"
    msgs = team.inbox(research, agent, ctx.args.keep)
    r = Result("OK", {"RESEARCH": research.id, "AGENT": agent, "MESSAGES": len(msgs)})
    for m in msgs:
        r.data("message", json.dumps({k: m[k] for k in ("type", "from", "body", "refs")}, ensure_ascii=False))
    return r
