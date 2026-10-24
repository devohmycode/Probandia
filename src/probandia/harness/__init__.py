"""What each harness can do, and how to tell which one is calling.

``CAPABILITIES`` is the table ``doctor`` reports from. A missing capability
degrades in a documented way (``DEGRADATIONS``).
"""
import os

from probandia.i18n import N_

FIRST_CLASS, BETA, REDUCED, NONE = "first-class", "beta", "reduced", "none"

# Capabilities: web search, subagents in plugins, a multiple-choice question
# tool, messages between agents, hooks, the MCP server, and the effort levels
# agents accept. Checked again on 23 October 2026 (version-1.0.0 T219), from each CLI's help, its local
# documentation and the official docs: Claude Code 2.1.308, codex-cli 0.163.0, agy 1.4.6, grok 1.0.67,
# droid 0.245.1, opencode 1.18.29, cursor-agent 2026.09.28 and Cursor 3.27.6; install, doctor and status
# replayed on 17 October 2026 in Codex, Grok Build, Factory Droid, Antigravity and OpenCode, and on
# 21 October 2026 in Claude Code, Cursor, Claude Desktop, Codex, Grok Build and Factory Droid (T178). ``models``: the
# model aliases a subagent can take (Claude Code: ``roles.CLAUDE_CODE_MODELS``, the default first);
# elsewhere the harness's default model is used. ``mcp``: the plugin's manifest declares the server
# (token-economy E1: the Claude Code plugin has none, its skills call the engine through the shell).
CAPABILITIES = {
    "claude-code": dict(support=FIRST_CLASS, web_search="WebSearch", subagents=True,
                        question="AskUserQuestion", messaging="SendMessage", hooks=True, mcp=False,
                        efforts=("low", "medium", "high", "xhigh", "max"),
                        models=("sonnet", "opus", "haiku", "fable"), root_variable="${CLAUDE_PLUGIN_ROOT}"),
    # Plugins cannot hold subagents: `install --harness codex` also writes custom agents.
    # Plugin hooks run once the user approves them in /hooks. Codex also knows "ultra", above "max": Probandia's
    # efforts stop at "max".
    "codex": dict(support=FIRST_CLASS, web_search="web_search", subagents=False,
                  question="request_user_input", messaging="send_message", hooks=True, mcp=True,
                  efforts=("low", "medium", "high", "xhigh", "max"),
                  root_variable="${PLUGIN_ROOT}"),
    # Agents use the harness's own model: no effort can be set per agent (Cursor takes one only with a model
    # pinned in the agent, `model: <id>[effort=high]`).
    "cursor": dict(support=FIRST_CLASS, web_search="WebSearch", subagents=True,
                   question="AskQuestion", messaging=None, hooks=True, mcp=True,
                   efforts=(), root_variable="${CURSOR_PLUGIN_ROOT}"),
    # Droid expands DROID_PLUGIN_ROOT and CLAUDE_PLUGIN_ROOT in a plugin's MCP settings, but the shared mcp.json
    # names ${PLUGIN_ROOT} (Codex's): the MCP server does not start.
    "droid": dict(support=FIRST_CLASS, web_search="WebSearch", subagents=True,
                  question="AskUser", messaging=None, hooks=True, mcp=False,
                  efforts=("low", "medium", "high", "xhigh", "max"), root_variable="${DROID_PLUGIN_ROOT}"),
    # Plugin options (/config) are ignored: the settings come from files and arguments. It reads
    # .claude-plugin/; it could start a trusted plugin's .mcp.json, which the plugin does not ship.
    "grok": dict(support=FIRST_CLASS, web_search="web_search", subagents=True,
                 question="ask_user_question", messaging=None, hooks=True, mcp=False,
                 efforts=("low", "medium", "high", "xhigh"), root_variable="${GROK_PLUGIN_ROOT}"),
    # Hooks and MCP run in the plugin folder. agy reads agents/, whose headers hold `tools` as a list and no
    # model (version-1.0.0 T267): its agents take the session's model.
    "antigravity": dict(support=BETA, web_search="search_web", subagents=True,
                        question="ask_question", messaging="send_message", hooks=True, mcp=True,
                        efforts=(), root_variable=None),
    # Installed by `install --harness opencode`, with absolute paths.
    "opencode": dict(support=REDUCED, web_search="websearch", subagents=True,
                     question="question", messaging=None, hooks=True, mcp=True,
                     efforts=("low", "medium", "high", "xhigh", "max"), root_variable=None),
    "cli": dict(support=NONE, web_search=None, subagents=False, question=None, messaging=None,
                hooks=False, mcp=False, efforts=(), root_variable=None),
}

DEGRADATIONS = {
    "web_search": N_("no web search of its own: only the engine's providers are used"),
    "subagents": N_("no subagents in plugins: roles run as skills, or as agent files installed apart"),
    "question": N_("no multiple-choice tool: questions are asked as numbered choices in the text"),
    "messaging": N_("no messages between agents: the orchestrator relays them between waves"),
    "hooks": N_("no hooks: the checks run in the commands and the MCP server"),
    "mcp": N_("no MCP server: the engine is called through the shell"),
    "efforts": N_("no effort per agent: the model tier only"),
}

# Variables that reveal the calling harness, checked in this order. Claude Code comes last: a harness started
# from its shell inherits CLAUDECODE, and its own variables must win.
DETECTION = (
    ("droid", ("DROID_PLUGIN_ROOT", "FACTORY_DROID", "FACTORY_SESSION_ID")),
    ("codex", ("CODEX_SANDBOX", "CODEX_THREAD_ID", "CODEX_SESSION_ID")),
    ("cursor", ("CURSOR_AGENT", "CURSOR_TRACE_ID")),
    ("grok", ("GROK_SESSION_ID", "GROK_AGENT")),
    ("antigravity", ("ANTIGRAVITY_AGENT", "ANTIGRAVITY_SESSION_ID")),
    ("opencode", ("OPENCODE", "OPENCODE_SESSION_ID")),
    ("claude-code", ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")),
)


def detect(explicit=None, environ=None):
    """(harness, how it was found)."""
    environ = os.environ if environ is None else environ
    if explicit and explicit != "cli":
        return explicit, "--harness"
    named = environ.get("PROBANDIA_HARNESS")
    if named in CAPABILITIES:
        return named, "PROBANDIA_HARNESS"
    for harness, variables in DETECTION:
        for var in variables:
            if environ.get(var):
                return harness, var
    return "cli", "none"


def degradations(harness):
    """The message ids of the degradations in effect for a harness."""
    caps = CAPABILITIES[harness]
    if harness == "cli":
        return []
    return [DEGRADATIONS[k] for k in ("web_search", "subagents", "question", "messaging", "hooks",
                                      "mcp", "efforts") if not caps[k]]
