"""What the hooks cost a pass, replayed offline from a kept session stream.

    python tools/hook_cost.py <session.jsonl> [--json]

Reads the tool calls of a session (the ``stream-json`` output of ``claude -p`` that
the session bench keeps, or a transcript of Claude Code), and replays each one, in
order, as the ``PreToolUse`` and ``PostToolUse`` payloads Claude Code would send to
the commands of ``hooks/hooks.json`` whose matcher takes the tool (``hook guard``
and ``hook log``). The hooks run in a copy of ``tests/sample-project``, with their own
configuration and data folders and no harness variable, as ``tools/startup_time.py``
does; the paths of the session's folder are moved into the copy. Nothing reaches the
network: no tool runs, only the hooks.

It prints, by event, the executions, their median and their total in milliseconds,
and the total of the pass. Exits 1 when a hook exits with another code than 0.
"""
import argparse
import json
import os
import platform
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from startup_time import ROOT, SAMPLE, clean_environment  # noqa: E402

HOOKS = os.path.join(ROOT, "hooks", "hooks.json")
EVENTS = ("PreToolUse", "PostToolUse")


def rows(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def tool_calls(path):
    """(call id, tool, input, agent type or None, response) of each tool call, in order, and the
    folders to move: the session's (the ``cwd`` of its first line that has one) and the plugin's
    (Probandia in the ``plugins`` of the stream's ``init`` line)."""
    calls, order, kinds, cwd, plugin = {}, [], {}, None, None
    for row in rows(path):
        cwd = cwd or row.get("cwd")
        plugin = plugin or next((p.get("path") for p in row.get("plugins") or []
                                 if isinstance(p, dict) and p.get("name") == "probandia"), None)
        msg = row.get("message") or {}
        content = msg.get("content")
        parent = row.get("parent_tool_use_id")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if row.get("type") == "assistant" and block.get("type") == "tool_use" and block.get("id") not in calls:
                data = block.get("input") or {}
                if block.get("name") in ("Agent", "Task"):
                    kinds[block.get("id")] = data.get("subagent_type") or "general-purpose"
                calls[block["id"]] = {"id": block["id"], "tool": block.get("name"), "input": data,
                                      "agent": kinds.get(parent), "parent": parent, "response": None}
                order.append(block["id"])
            elif row.get("type") == "user" and block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                answer = row.get("tool_use_result") or row.get("toolUseResult") or block.get("content")
                calls[block["tool_use_id"]]["response"] = answer
    for call in calls.values():   # a subagent's calls may come before its Agent call is known
        if call["agent"] is None and call["parent"] in kinds:
            call["agent"] = kinds[call["parent"]]
    return [calls[i] for i in order], {"session": cwd, "plugin": plugin}


def commands(hooks_file=HOOKS):
    """{event: [(matcher, command)]} for PreToolUse and PostToolUse, the plugin root filled in and
    ``python`` replaced by the interpreter running this script."""
    with open(hooks_file, encoding="utf-8") as fh:
        hooks = json.load(fh)["hooks"]
    found = {}
    for event in EVENTS:
        for entry in hooks.get(event, []):
            for hook in entry.get("hooks", []):
                if hook.get("type") != "command":
                    continue
                # `python … || python3 …` (T259): the first one
                words = [w.replace("${CLAUDE_PLUGIN_ROOT}", ROOT) for w in shlex.split(hook["command"].split(" || ")[0])]
                argv = [sys.executable if "python" in words[0] else words[0]] + words[1:]
                found.setdefault(event, []).append((entry.get("matcher") or "*", argv))
    return found


def matches(matcher, tool):
    """Claude Code's matcher: ``*`` or empty takes every tool, otherwise a regular expression."""
    return matcher in ("*", "") or re.fullmatch(matcher, tool or "") is not None


def _forms(folder):
    """A folder in its Windows, POSIX and Git Bash spellings, longest first."""
    forms = {folder, folder.replace("\\", "/")}
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", folder)
    if m:
        forms.add(f"/{m.group(1).lower()}/{m.group(2)}".replace("\\", "/"))
    return sorted(forms, key=len, reverse=True)


def _moved(value, moves):
    """The value with each old folder of ``moves`` ((old, new) pairs) replaced by the new one."""
    if isinstance(value, dict):
        return {k: _moved(v, moves) for k, v in value.items()}
    if isinstance(value, list):
        return [_moved(v, moves) for v in value]
    if isinstance(value, str):
        for old, new in moves:
            for form in _forms(old):
                value = value.replace(form, new)
    return value


def payloads(path, project, hooks_file=HOOKS):
    """(event, command, payload) of each hook run the session's tool calls trigger, in order."""
    calls, folders = tool_calls(path)
    moves = [(folders[k], new) for k, new in (("plugin", ROOT), ("session", project)) if folders[k]]
    found = commands(hooks_file)
    out = []
    for call in calls:
        tool_input = _moved(call["input"], moves)
        base = {"session_id": "hook-cost", "transcript_path": "", "cwd": project, "permission_mode": "default",
                "tool_name": call["tool"], "tool_input": tool_input, "tool_use_id": call["id"]}
        if call["agent"]:
            base.update(agent_id=call["parent"], agent_type=call["agent"])
        for event in EVENTS:
            for matcher, argv in found.get(event, []):
                if not matches(matcher, call["tool"]):
                    continue
                payload = dict(base, hook_event_name=event)
                if event == "PostToolUse":
                    payload["tool_response"] = _moved(call["response"], moves)
                out.append((event, argv, payload))
    return out


def replay(runs, project, env):
    """[(event, label, seconds, exit code, output)] of each hook run, in a fresh copy of the sample project."""
    results = []
    for event, argv, payload in runs:
        start = time.perf_counter()
        r = subprocess.run(argv, input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
                           encoding="utf-8", cwd=project, env=env)
        label = " ".join(argv[2:]) if len(argv) > 2 else " ".join(argv)
        results.append((event, label, time.perf_counter() - start, r.returncode, r.stdout.strip()))
    return results


def summary(results):
    """By event and command: executions, median and total in ms, refusals; and the total of the pass."""
    groups = {}
    for event, label, seconds, code, output in results:
        g = groups.setdefault((event, label), {"event": event, "command": label, "runs": 0, "times": [],
                                               "failed": 0, "refused": 0, "answered": 0})
        g["runs"] += 1
        g["times"].append(seconds)
        g["failed"] += code != 0
        g["refused"] += '"deny"' in output
        g["answered"] += bool(output)
    lines = []
    for g in groups.values():
        times = g.pop("times")
        g["median_ms"] = round(statistics.median(times) * 1000)
        g["total_ms"] = round(sum(times) * 1000)
        lines.append(g)
    return {"system": platform.system(), "python": platform.python_version(), "events": lines,
            "runs": len(results), "total_ms": round(sum(r[2] for r in results) * 1000)}


def render(report, out):
    w = out.write
    w(f"hook cost of the pass ({report['system']}, Python {report['python']})\n\n")
    w("| Event | Command | Runs | Median | Total | Refused | Exit ≠ 0 |\n|---|---|---:|---:|---:|---:|---:|\n")
    for g in report["events"]:
        w(f"| {g['event']} | `{g['command']}` | {g['runs']} | {g['median_ms']} ms | {g['total_ms']} ms | "
          f"{g['refused']} | {g['failed']} |\n")
    w(f"| **pass** | | {report['runs']} | | {report['total_ms']} ms | | |\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stream", help="the session's stream-json or transcript (.jsonl)")
    parser.add_argument("--hooks", default=HOOKS, help="the hooks file (default: hooks/hooks.json)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.stream):
        parser.error(f"no stream: {args.stream}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="probandia-hookcost-") as tmp:
        project = os.path.join(tmp, "sample")
        shutil.copytree(SAMPLE, project)
        results = replay(payloads(args.stream, project, args.hooks), project, clean_environment(tmp, project))
    report = summary(results)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        render(report, sys.stdout)
    return 1 if any(g["failed"] for g in report["events"]) else 0


if __name__ == "__main__":
    sys.exit(main())
