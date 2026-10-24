"""Per-project copies of the agents, for the harnesses whose plugin agents cannot take a project's model and
effort (agent-models R6; their docs and CLIs read on 12 Oct. 2026):

| Harness | Copy | Model, effort |
|---|---|---|
| Cursor | ``.cursor/agents/probandia-<role>.md`` (same name: it comes before the plugin's, whose model is forced to ``inherit``) | ``model: <id>[effort=<level>]``; no copy without a model, the effort living inside it |
| Factory Droid | ``.factory/droids/probandia-<role>.md`` (same name; that it comes before the plugin's is to check in ``/droids``) | ``model``, ``reasoningEffort`` |
| Grok Build | ``.grok/agents/probandia-<role>.md`` (the plugin's is ``probandia:<role>``: the guard sends each launch to the copy) | ``model``, ``effort`` |

``sync`` writes them at each session start (the session hook), for the roles the user set only; it rewrites
one when the plugin changed and removes it when the setting goes. A file Probandia did not write is never
touched: what it wrote is listed in ``.probandia/cache/agent-copies.json``.
"""
import json
import os

from probandia.install import convert
from probandia.util.fs import atomic_write_text

FOLDERS = {"cursor": (".cursor", "agents"), "droid": (".factory", "droids"), "grok": (".grok", "agents")}
RECORD = os.path.join(".probandia", "cache", "agent-copies.json")


def _one_line(text):
    return " ".join(str(text or "").split())


def _cursor(role, fm, body, mine):
    """Cursor's workspace agents are read line by line, ``key: value``, without YAML unquoting (observed in
    cursor-agent 2026.09.28): single-line values, never quoted."""
    if not mine.get("model"):
        return None
    model = mine["model"] + (f"[effort={mine['effort']}]" if mine.get("effort") else "")
    lines = ["---", f"name: probandia-{role}", f"description: {_one_line(fm.get('description'))}", f"model: {model}"]
    tools = convert.tools_list(fm.get("tools"))
    if tools:
        lines.append(f"tools: {', '.join(tools)}")
    if role == "contradictor":
        lines.append("permissionMode: readonly")
    return "\n".join(lines + ["---", ""]) + "\n" + body


def _droid(role, fm, body, mine):
    from probandia.install.manifests import droid_agent

    return droid_agent(role, dict(fm, model=mine.get("model", fm.get("model", "inherit")),
                                  effort=mine.get("effort", fm.get("effort", "medium"))), body)


def _grok(role, fm, body, mine):
    fields = {"name": f"probandia-{role}", "description": fm.get("description", ""), "model": mine.get("model"),
              "effort": mine.get("effort", fm.get("effort")), "tools": fm.get("tools")}
    return convert.front_matter(fields) + "\n" + body


WRITERS = {"cursor": _cursor, "droid": _droid, "grok": _grok}


def path_of(project, harness, role):
    return os.path.join(project, *FOLDERS[harness], f"probandia-{role}.md")


def _record(project):
    try:
        with open(os.path.join(project, RECORD), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def written(project, harness):
    """The copies Probandia wrote for ``harness`` in ``project``, as paths relative to it."""
    return [p for p in _record(project).get(harness) or [] if isinstance(p, str)]


def sync(project, harness, environ=None):
    """Writes, rewrites or removes the copies of ``harness`` in ``project``; returns (action, path) pairs:
    ``wrote``, ``removed``, or ``kept`` for a file of that name Probandia did not write."""
    from probandia import roles

    if harness not in FOLDERS:
        return []
    chosen = roles.for_install(project, environ if environ is not None else os.environ, harness)
    mine = set(written(project, harness))
    root = convert.package_root().replace("\\", "/")
    kept, done = set(), []
    for role, (fm, body) in convert.agents().items():
        path = path_of(project, harness, role)
        rel = os.path.relpath(path, project).replace(os.sep, "/")
        text = None
        if role in chosen:
            text = WRITERS[harness](role, fm, convert.with_harness(convert.with_root(body, root), harness),
                                    chosen[role])
        exists = os.path.isfile(path)
        if text is None:
            if rel in mine and exists:
                os.remove(path)
                done.append(("removed", rel))
            continue
        if exists and rel not in mine:
            done.append(("kept", rel))
            continue
        current = None
        if exists:
            with open(path, encoding="utf-8") as fh:
                current = fh.read()
        if current != text:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            atomic_write_text(path, text)
            done.append(("wrote", rel))
        kept.add(rel)
    record = _record(project)
    if kept or harness in record:
        record[harness] = sorted(kept)
        os.makedirs(os.path.dirname(os.path.join(project, RECORD)), exist_ok=True)
        atomic_write_text(os.path.join(project, RECORD), json.dumps(record, indent=2) + "\n")
    return done
