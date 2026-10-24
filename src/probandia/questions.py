"""The launch questions of a research, and how ``STATUS=ASK`` carries them.

| Id | Question | Choices |
|---|---|---|
| ``run_mode`` | Who runs this research? | session, subagent, team |
| ``run_model`` | Which model for the subagent? | the harness's models (``doctor``), or other |
| ``run_effort`` | Which effort? | the levels the harness accepts |
| ``team_agents`` | Agents | 1, 3, 5, 10, or a number |
| ``team_effort`` | Which effort? | the levels the harness accepts |
| ``team_passes`` | Passes | 1, 2, 3, 4, or a number |
| ``workshop`` | Import the prototype workshop first? | import, ignore |
| ``workshop_report`` | Which report do the findings go to? | the workshop's reports, new |
| ``workshop_volet``, ``workshop_chapitre`` | The volet and the chapter of the new facts | the report's last ones, or other |
| ``workshop_push`` | Write the new facts to the workshop now? (once a pass, ``workshop.sync = ask``) | push, later |

Questions that go together are asked in one call: the three team questions,
and the subagent's model and effort. The answer carries ``QUESTION=`` (the
first), ``QUESTIONS=`` (all of them, ``|``-separated) and, for each,
``PROMPT_<ID>``, ``CHOICES_<ID>``, ``DEFAULT_<ID>``, ``ALLOW_OTHER_<ID>`` and
``OPTION_<ID>`` (the argument that carries the answer). A lone question has
the plain keys instead (``PROMPT``, ``CHOICES``, ``DEFAULT``, ``ALLOW_OTHER``,
``OPTION``), each value once. ``TOOL=`` names the harness's question tool, or
``none`` for numbered choices.

A headless run (``PROBANDIA_HEADLESS=1``, or a child run with
``PROBANDIA_WORKER=1``) asks nothing: the defaults are taken, and
``pass.started`` records ``assumed: true``.
"""
from probandia.cli.output import Result
from probandia.harness import CAPABILITIES
from probandia.i18n import N_, _

SPECS = {
    "run_mode": (N_("Who runs this research?"), ("session", "subagent", "team"), "session", False, "--mode"),
    "run_model": (N_("Which model for the subagent?"), None, None, True, "--model"),
    "run_effort": (N_("Which effort?"), None, "medium", False, "--effort"),
    "team_agents": (N_("Agents"), ("1", "3", "5", "10"), "3", True, "--agents"),
    "team_effort": (N_("Which effort?"), None, "medium", False, "--effort"),
    "team_passes": (N_("Passes"), ("1", "2", "3", "4"), "2", True, "--passes"),
    "family": (N_("Which family is this research about?"), None, None, True, "--family"),
    "interrupted_pass": (N_("The previous pass was interrupted. Continue it, or close it as interrupted?"),
                         ("continue", "close"), "continue", False, "--interrupted"),
    "workshop": (N_("This folder is a prototype workshop that was never imported. Import it first, so the "
                    "research starts from what it establishes, or start without it?"),
                 ("import", "ignore"), "import", False, "--workshop"),
    "workshop_report": (N_("Which report of the workshop do the findings of this research go to? (new: create its "
                           "folder with the workshop's own tool first)"), None, None, False, "--report"),
    "workshop_volet": (N_("In which volet do they enter the workshop? (never an earlier one)"), None, None, True,
                       "--volet"),
    "workshop_chapitre": (N_("Which chapter establishes them?"), None, None, True, "--chapitre"),
    "workshop_push": (N_("Facts of this pass are not in the workshop yet. Write them to its personnes.yaml now "
                         "(push), or later in the pass (later)?"), ("push", "later"), "push", False, "workshop push"),
}
DEFAULTS = {"run_mode": "session", "team_agents": 3, "team_effort": "medium", "team_passes": 2}


def headless(environ):
    return environ.get("PROBANDIA_HEADLESS") == "1" or environ.get("PROBANDIA_WORKER") == "1"


def choices(qid, harness, given=None):
    """The choices of a question for a harness; an empty tuple when it has none to offer."""
    if given:
        return tuple(given)
    prompt, fixed, _default, _other, _option = SPECS[qid]
    if fixed:
        return fixed
    caps = CAPABILITIES.get(harness) or CAPABILITIES["cli"]
    if qid == "run_model":
        return tuple(caps.get("models") or ())
    if qid in ("run_effort", "team_effort"):
        return tuple(caps.get("efforts") or ())
    return ()


def ask(qids, harness, values=None, given=None, prompts=None, defaults=None):
    """One ``ASK`` result for questions asked together. ``defaults`` replaces the
    default of a question (the run that suits the question, optimize 2.12)."""
    given = given or {}
    prompts = prompts or {}
    defaults = defaults or {}
    tool = (CAPABILITIES.get(harness) or CAPABILITIES["cli"]).get("question") or "none"
    fields = {}
    for qid in qids:
        opts = choices(qid, harness, given.get(qid))
        prompt, _fixed, default, other, option = SPECS[qid]
        default = defaults.get(qid) or default
        fields[qid] = (prompts.get(qid) or _(prompt), opts, default if default in opts else (opts[0] if opts else ""),
                       bool(other or not opts), option)
    if len(qids) == 1:  # one question: the plain keys only, never the same values again under _<ID> keys
        prompt, opts, default, other, option = fields[qids[0]]
        r = Result.ask(qids[0], prompt, list(opts) or ["other"], default or "other", allow_other=other, values=values)
        r.set("TOOL", tool).set("OPTION", option)
    else:
        r = Result("ASK", values).set("QUESTION", qids[0]).set("TOOL", tool).set("QUESTIONS", "|".join(qids))
        for qid, (prompt, opts, default, other, option) in fields.items():
            key = qid.upper()
            r.set(f"PROMPT_{key}", prompt)
            r.set(f"CHOICES_{key}", "|".join(opts))
            r.set(f"DEFAULT_{key}", default)
            r.set(f"ALLOW_OTHER_{key}", other)
            r.set(f"OPTION_{key}", option)
    r.line(_("ask the user these questions together and never answer them yourself; then run the command again "
             "with: {options}").format(
        options=" ".join(f"{SPECS[q][4]} <{q}>" for q in qids)))
    return r


def missing_run(run, config, harness):
    """The launch questions still open for a run block, in the order they are asked
    together: ``[run_mode]``, then the subagent's or the team's questions."""
    if not run.get("mode"):
        return ["run_mode"]
    if run["mode"] == "team":
        out = []
        if not run.get("max_agents") and config.get("team.max_agents") is None:
            out.append("team_agents")
        if not run.get("effort") and config.get("team.effort") is None and choices("team_effort", harness):
            out.append("team_effort")
        if not run.get("max_passes") and config.get("team.max_passes") is None:
            out.append("team_passes")
        return out
    if run["mode"] == "subagent":
        out = []
        if not run.get("model") and not config.get("run.model") and choices("run_model", harness):
            out.append("run_model")
        if not run.get("effort") and not config.get("run.effort") and choices("run_effort", harness):
            out.append("run_effort")
        return out
    return []


def assume(run, qids):
    """The defaults of a headless run."""
    run = dict(run)
    for qid in qids:
        if qid == "run_mode":
            run["mode"] = DEFAULTS["run_mode"]
        elif qid == "team_agents":
            run["max_agents"] = DEFAULTS["team_agents"]
        elif qid == "team_effort":
            run["effort"] = DEFAULTS["team_effort"]
        elif qid == "team_passes":
            run["max_passes"] = DEFAULTS["team_passes"]
    return run
