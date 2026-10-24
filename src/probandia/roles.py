"""The model and the effort of each agent role (agent-models R2).

``roles.<role>.model`` and ``roles.<role>.effort`` in the project's ``probandia.toml``, or the user's
settings, over the agent's own header (``.claude-plugin/agents/<role>.md``, generated with ``ROLE_DEFAULTS``). The
orchestrator takes a research's own ``--model`` and ``--effort`` first; the older keys ``run.*``
(the orchestrator) and ``search.*`` (the searcher) count when the role's own key is left alone.
In Claude Code the guard applies them to every launch of a Probandia agent (agent-models R3).
"""
from probandia.config.registry import ROLE_DEFAULTS
from probandia.i18n import N_

ROLES = tuple(ROLE_DEFAULTS)
FIELDS = ("model", "effort")
OLDER = {"orchestrator": "run", "searcher": "search"}
# The values the Agent tool of Claude Code takes for ``model`` (its schema, 12 Oct. 2026), weakest first.
CLAUDE_CODE_MODELS = ("haiku", "sonnet", "opus", "fable")
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")


def resolve(config, run=None):
    """{role: {"model", "effort", "model_from", "effort_from"}}: each value in effect and the layer that
    set it: ``default`` when the agent's header decides, ``research`` for a research's own option."""
    out = {}
    for role in ROLES:
        entry = {}
        for field in FIELDS:
            key = f"roles.{role}.{field}"
            value, layer = config.get(key), config.origin(key).layer
            older = OLDER.get(role)
            if layer == "default" and older:
                old_key = f"{older}.{field}"
                if config.origin(old_key).layer != "default" and config.get(old_key):
                    value, layer = config.get(old_key), config.origin(old_key).layer
            if role == "orchestrator" and (run or {}).get(field):
                value, layer = run[field], "research"
            entry[field], entry[f"{field}_from"] = value, layer
        out[role] = entry
    return out


# The form of a model each harness's agent files take (agent-models R5, R6; harnesses' docs read on 12 Oct.
# 2026): Codex, Cursor and Grok a name of their own, never a Claude alias; OpenCode provider/model; Factory
# Droid any (it maps Claude's aliases to its models, observed in droid 0.238.0) but inherit.
CLAUDE_ALIASES = CLAUDE_CODE_MODELS + ("inherit",)
MODEL_FORMS = {
    "codex": lambda model: "/" not in model and model not in CLAUDE_ALIASES,
    "opencode": lambda model: "/" in model,
    "cursor": lambda model: "/" not in model and model not in CLAUDE_ALIASES,
    "droid": lambda model: model != "inherit",
    "grok": lambda model: "/" not in model and model not in CLAUDE_ALIASES,
}


def harness_models(config, role):
    """{harness: model} of ``roles.<role>.models`` (``cursor:claude-opus-5`` items); a malformed item is left."""
    out = {}
    for item in config.get(f"roles.{role}.models") or []:
        harness, sep, model = str(item).partition(":")
        if sep and harness.strip() and model.strip():
            out[harness.strip()] = model.strip()
    return out


FORM_HINTS = {   # what MODEL_FORMS takes, said when a model is left out (T125)
    "codex": N_("a model name of its own, neither a Claude alias nor provider/model"),
    "opencode": N_("provider/model"),
    "cursor": N_("a model name of its own, neither a Claude alias nor provider/model"),
    "droid": N_("any model but inherit"),
    "grok": N_("a model name of its own, neither a Claude alias nor provider/model"),
}


def for_install(project, environ, harness, dropped=None):
    """{role: {"model", "effort"}} of what the user chose, as the agent files of ``harness`` take it: the
    harness's own model first (``roles.<role>.models``), else ``roles.<role>.model`` when it has that
    harness's form (else the agent runs on the harness's own, and ``(role, model)`` goes in ``dropped``),
    the effort as chosen. ``project`` None: the user's settings only."""
    from probandia.config import load

    config = load(project, environ, strict=False)
    out = {}
    for role, entry in resolve(config).items():
        wanted = chosen(entry)
        own = harness_models(config, role).get(harness)
        if own:
            wanted["model"] = own
        elif wanted.get("model") and not MODEL_FORMS[harness](wanted["model"]):
            if dropped is not None:
                dropped.append((role, wanted["model"]))
            del wanted["model"]
        if wanted:
            out[role] = wanted
    return out


def dropped_lines(harness, dropped):
    """One line per model ``for_install`` left out, naming the role and the form the harness takes."""
    from probandia.i18n import _

    return [_("{role}: the model {model} is not in the form {harness} takes ({form}), so it was not written and "
              "the agent runs on the harness's model; give it one with roles.{role}.models = [\"{harness}:<model>\"]")
            .format(role=role, model=model, harness=harness, form=_(FORM_HINTS[harness])) for role, model in dropped]


def reinstall_hint(project, role):
    """The command that rewrites the agent files already installed for ``role`` in ``project``, or None (T125)."""
    import os

    if not project:
        return None
    for path, command in ((os.path.join(".codex", "agents", f"probandia-{role}.toml"), "install --harness codex-agents"),
                          (os.path.join(".opencode", "agents", f"probandia-{role}.md"),
                           "install --harness opencode --scope project")):
        if os.path.isfile(os.path.join(project, path)):
            return path, command
    return None


def chosen(entry):
    """{field: value} of what the user chose for a role: the values not left to the agent's header."""
    return {f: entry[f] for f in FIELDS if entry[f"{f}_from"] != "default" and entry[f]}


def weaker(role, field, value):
    """True when ``value`` is below the role's default: a Claude model of a lower tier, or a lower effort."""
    default = ROLE_DEFAULTS[role][FIELDS.index(field)]
    order = CLAUDE_CODE_MODELS if field == "model" else EFFORT_ORDER
    if value not in order or default not in order:
        return False
    return order.index(value) < order.index(default)


def warnings(role, field, value):
    """What setting a role says, one line each (agent-models R0: free choice, a word when the reader goes down)."""
    from probandia.i18n import _

    out = []
    if field == "model" and value not in CLAUDE_CODE_MODELS + ("inherit",):
        out.append(_("{value} is no alias of the Agent tool of Claude Code ({aliases}): there, the agent keeps "
                     "the model of its header").format(value=value, aliases=", ".join(CLAUDE_CODE_MODELS)))
    if role == "reader" and weaker(role, field, value):
        out.append(_("the reader reads the acts, and its reading carries the proof: below {default}, a "
                     "misreading is likelier").format(default=ROLE_DEFAULTS[role][FIELDS.index(field)]))
    return out
