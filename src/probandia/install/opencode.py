"""``install --harness opencode [--scope user|project] [--uninstall]``.

OpenCode has no plugin package, so the installer:

1. copies ``skills/*`` to ``~/.agents/skills/probandia-*/`` (``.agents/skills/`` in a project);
2. converts ``agents/*.md`` into ``~/.config/opencode/agents/`` (``.opencode/agents/``):
   ``mode: subagent``, no ``reasoningEffort`` and no ``tools`` string (OpenCode refuses the
   whole configuration); a ``model`` only when the user chose one for the role as
   ``provider/model`` (``roles.<role>.model``), with the effort as its ``variant``;
3. copies ``commands/*.md`` into ``~/.config/opencode/commands/`` (``.opencode/commands/``);
4. merges the MCP server into ``opencode.json``, keeping every other key, after a ``.bak`` copy;
5. writes the JS plugin of the hooks into ``~/.config/opencode/plugins/`` (``.opencode/plugins/``).

Files installed outside a plugin cannot rely on a plugin root variable: they name
the engine by its absolute path.
"""
import json
import os
import sys

from probandia.install import Installer, convert

PLUGIN_JS = """\
// Probandia hooks for OpenCode. Written by: python run_probandia.py install --harness opencode
// Before a tool runs, the guard may refuse it (the error blocks the call);
// after it ran, the log records it. Both never block on an internal error.
//
// The tool hooks do not say which agent calls (OpenCode 1.18: tool, sessionID,
// callID): the agent of each session is learnt from chat.message and from the
// session and message events (probandia-researcher for a field agent).
import {{ spawnSync }} from "node:child_process";

const PYTHON = {python};
const ENGINE = {engine};
const agents = new Map();
// built-in tools the log never records: no Python started after them
const UNLOGGED = new Set(["bash", "read", "write", "edit", "patch", "glob", "grep", "list", "webfetch",
                          "todowrite", "todoread"]);

function hook(fn, payload, timeout) {{
  try {{
    const out = spawnSync(PYTHON, [ENGINE, "hook", fn],
                          {{ input: JSON.stringify(payload), encoding: "utf8", timeout, windowsHide: true }});
    return (out.stdout || "").trim();
  }} catch (e) {{
    return "";
  }}
}}

function payload(input, args) {{
  return {{ harness: "opencode", tool_name: input.tool, tool_input: args || {{}},
            agent_type: agents.get(input.sessionID) || "", session_id: input.sessionID || "" }};
}}

export const Probandia = async () => ({{
  "chat.message": async (input) => {{
    if (input && input.sessionID && input.agent) agents.set(input.sessionID, input.agent);
  }},
  event: async ({{ event }}) => {{
    const info = (event && event.properties && event.properties.info) || {{}};
    const sid = info.sessionID || (event.type && event.type.startsWith("session.") ? info.id : undefined);
    if (sid && info.agent) agents.set(sid, info.agent);
  }},
  "tool.execute.before": async (input, output) => {{
    const text = hook("guard", payload(input, output && output.args), 10000);
    if (text) {{
      let decision = null;
      try {{ decision = JSON.parse(text); }} catch (e) {{}}
      if (decision && decision.permission === "deny") throw new Error(decision.reason || "probandia: refused");
    }}
  }},
  "tool.execute.after": async (input, output) => {{
    if (UNLOGGED.has(input.tool)) return;
    hook("log", payload(input, (output && output.args) || input.args), 15000);
  }},
}});
"""


def config_home(environ):
    base = environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "opencode")


def home(environ):
    return environ.get("HOME") or environ.get("USERPROFILE") or os.path.expanduser("~")


def places(scope, project, environ):
    """{kind: folder} for a scope."""
    if scope == "project":
        return {"skills": os.path.join(project, ".agents", "skills"),
                "agents": os.path.join(project, ".opencode", "agents"),
                "commands": os.path.join(project, ".opencode", "commands"),
                "plugins": os.path.join(project, ".opencode", "plugins"),
                "config": os.path.join(project, "opencode.json"),
                "record": os.path.join(project, ".opencode")}
    cfg = config_home(environ)
    return {"skills": os.path.join(home(environ), ".agents", "skills"),
            "agents": os.path.join(cfg, "agents"),
            "commands": os.path.join(cfg, "commands"),
            "plugins": os.path.join(cfg, "plugins"),
            "config": os.path.join(cfg, "opencode.json"),
            "record": cfg}


def record_dir(scope, project, environ):
    return places(scope, project, environ)["record"]


def opencode_agent(role, fm, body, engine_root, chosen=None):
    # No reasoningEffort: a model without reasoning refuses the parameter ("does not support
    # parameter reasoningEffort"). The agent runs on the user's model unless a provider/model was
    # chosen for its role (agent-models R6); its effort is then the model's variant, which OpenCode
    # applies with the agent's own model only and ignores when the model has no such variant.
    fields = {"description": fm.get("description", ""), "mode": "subagent"}
    if (chosen or {}).get("model"):
        fields["model"] = chosen["model"]
        if chosen.get("effort"):
            fields["variant"] = chosen["effort"]
    if "maxTurns" in fm:
        fields["steps"] = fm["maxTurns"]
    if role == "contradictor":
        fields["permission"] = {"edit": "deny"}
    text = convert.with_harness(convert.with_root(body, engine_root), "opencode")
    return convert.front_matter(fields) + "\n" + text


def _rewrite(text, engine_root):
    return convert.with_harness(convert.with_root(text, engine_root), "opencode")


def install(scope, project, environ):
    where = places(scope, project, environ)
    inst = Installer(where["record"])
    root = convert.package_root()
    engine_root = root.replace("\\", "/")

    for name in sorted(os.listdir(os.path.join(root, "skills"))):
        src_dir = os.path.join(root, "skills", name)
        for folder, _dirs, files in os.walk(src_dir):
            for f in sorted(files):
                rel = os.path.relpath(os.path.join(folder, f), src_dir)
                target = os.path.join(where["skills"], f"probandia-{name}", rel)
                inst.write(target, _rewrite(convert.read(os.path.join(folder, f)), engine_root))

    from probandia import roles

    dropped = []
    chosen = roles.for_install(project if scope == "project" else None, environ, "opencode", dropped)
    inst.notes += roles.dropped_lines("opencode", dropped)
    for role, (fm, body) in convert.agents(root).items():
        inst.write(os.path.join(where["agents"], f"probandia-{role}.md"),
                   opencode_agent(role, fm, body, engine_root, chosen.get(role)))

    for name, (fm, body) in convert.commands(root).items():
        fields = {"description": fm.get("description", "")}
        inst.write(os.path.join(where["commands"], f"probandia-{name}.md"),
                   convert.front_matter(fields) + "\n" + _rewrite(body, engine_root))

    config = where["config"]
    data = {}
    if os.path.exists(config):
        with open(config, encoding="utf-8") as fh:
            data = json.load(fh)
    ours = [["mcp", "probandia"]] + ([] if "$schema" in data else [["$schema"]])
    data.setdefault("$schema", "https://opencode.ai/config.json")
    data.setdefault("mcp", {})["probandia"] = {
        "type": "local", "command": [_python(), f"{engine_root}/run_probandia.py", "mcp"],
        "enabled": True, "environment": {"PROBANDIA_HARNESS": "opencode"}}
    inst.merge(config, json.dumps(data, ensure_ascii=False, indent=2) + "\n", ours)

    js = PLUGIN_JS.format(python=json.dumps(_python()), engine=json.dumps(f"{engine_root}/run_probandia.py"))
    inst.write(os.path.join(where["plugins"], "probandia.js"), js)
    inst.save()
    return inst


def _python():
    return sys.executable.replace("\\", "/")
