"""Where a Claude Code session spent its tokens, to improve Probandia.

    python tools/analyse_session.py <transcript.jsonl>
    python tools/analyse_session.py --session <id> --project "<project folder>"
    python tools/analyse_session.py <transcript> --since "/probandia:resume" --top 15 --json
    python tools/analyse_session.py <transcript> --by-agent [--json]

Reads the session's transcript (``~/.claude/projects/<folder>/<session>.jsonl``)
and the transcripts of its subagents (``<session>/subagents/*.jsonl``); writes
nothing. With ``--by-agent`` it writes one line per agent (the main one, then each
type of subagent with its number): calls, first and largest context, images and
their tokens, the characters returned to the parent, and the visible output (the
characters of the ``text`` and ``tool_use`` blocks) against the billed output and
its thinking part. Otherwise it reports:

- per phase (a phase starts at each prompt of the user): calls to the model, input
  tokens (cache reads and writes included), output, the context at the first and
  largest call. Every call reads the whole context again, so the cost of a session
  is about calls × context: the two levers are fewer calls and a smaller context;
- the tools used, the engine commands run (``pb.py <command>`` or
  ``run_probandia.py <command>``), the commands retried, the screenshots;
- the largest tool results, and the largest rises of the context, with their cause;
- the files read outside the project (a skill, a schema of the plugin): a sign
  that the agent's instructions lacked something.

Probandia's own ``.probandia/tokens.jsonl`` keeps only the totals per pass; this
script is for a person looking for what to change. Standard library only.
"""
import argparse
import base64
import collections
import glob
import json
import os
import re
import struct
import sys

ENGINE = re.compile(r"(?:pb\.py|run_probandia\.py|\bprobandia)[\"']?\s+((?:-{1,2}[a-z-]+(?:\s+[^-\s]\S*)?\s+)*)"
                    r"([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?")
GROUPS = {"archive", "library", "memory", "pass", "places", "quota", "keys", "question", "matrix", "team",
          "transcribe", "workshop", "config", "providers"}
READ_TOOLS = {"Read", "Grep", "Glob"}


def transcript_of(session, project):
    """The transcript of a session of Claude Code, from its id and the project folder."""
    folder = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project))
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(home, "projects", folder, f"{session}.jsonl")


def lines(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _text(content):
    if isinstance(content, str):
        return content
    return " ".join(x.get("text", "") for x in content or [] if isinstance(x, dict) and x.get("type") == "text")


def _prompt(row):
    """The text of a prompt of the user, or None for a tool result or a meta line."""
    if row.get("type") != "user" or row.get("isMeta"):
        return None
    content = row.get("message", {}).get("content")
    if isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
        return None
    text = _text(content).strip()
    m = re.search(r"<command-name>([^<]+)</command-name>", text)
    if m:
        text = m.group(1) + " " + re.sub(r"<[^>]+>", " ", text.split("</command-name>", 1)[-1])
    return " ".join(text.split()) or None


def engine_command(cmd):
    m = ENGINE.search(cmd or "")
    if not m:
        return None
    name = m.group(2)
    if name in GROUPS and m.group(3):
        name += " " + m.group(3)
    return name


def _label(name, data):
    for key in ("command", "query", "url", "file_path", "pattern", "description", "action"):
        if data.get(key):
            return f"{name}: {' '.join(str(data[key]).split())}"
    return name


def _inside(path, project):
    """True when a path (Windows, or Git Bash's /c/…) lies in the project folder."""
    m = re.match(r"^/([a-zA-Z])/(.*)", path)
    if m:
        path = f"{m.group(1)}:/{m.group(2)}"
    return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(project)))


def _context(usage):
    return sum(usage.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def analyse(path, since=None, top=10, project=None):
    """The report of one transcript, as a dict."""
    rows = list(lines(path))
    start = 0
    if since:
        for i, row in enumerate(rows):
            text = _prompt(row)
            if text and since in text:
                start = i
    phases, current = [], None
    seen, counted, uses, last_result = set(), {}, {}, None
    tools, engine, retried = collections.Counter(), collections.Counter(), collections.Counter()
    results, rises, outside = [], [], collections.Counter()
    images = previous = 0
    last_command = None
    for row in rows[start:]:
        text = _prompt(row)
        if text:
            current = {"prompt": text[:120], "start": row.get("timestamp"), "calls": 0, "input": 0,
                       "cache_read": 0, "cache_write": 0, "output": 0, "first_context": None, "max_context": 0}
            phases.append(current)
            continue
        if row.get("type") == "assistant":
            msg = row.get("message") or {}
            usage = msg.get("usage") or {}
            # A message spans one line per content block; its output grows to the last one.
            if current is not None and msg.get("id") in counted:
                grown = (usage.get("output_tokens", 0) or 0) - counted[msg["id"]]
                if grown > 0:
                    current["output"] += grown
                    counted[msg["id"]] += grown
            if msg.get("id") and msg["id"] not in seen:
                seen.add(msg["id"])
                counted[msg["id"]] = usage.get("output_tokens", 0) or 0
                if current is None:
                    current = {"prompt": "(before the first prompt)", "start": row.get("timestamp"), "calls": 0,
                               "input": 0, "cache_read": 0, "cache_write": 0, "output": 0,
                               "first_context": None, "max_context": 0}
                    phases.append(current)
                ctx = _context(usage)
                current["calls"] += 1
                current["input"] += ctx
                current["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
                current["cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0
                current["output"] += usage.get("output_tokens", 0) or 0
                current["first_context"] = current["first_context"] or ctx
                current["max_context"] = max(current["max_context"], ctx)
                current["end"] = row.get("timestamp")
                if previous:
                    rises.append((ctx - previous, row.get("timestamp"), last_result))
                previous = ctx
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name, data = block.get("name", "?"), block.get("input") or {}
                uses[block.get("id")] = (name, data)
                tools[name] += 1
                if name == "Bash":
                    command = engine_command(data.get("command"))
                    if command:
                        engine[command] += 1
                        if command == last_command:
                            retried[command] += 1
                        last_command = command
                where = data.get("file_path") or data.get("path") or ""
                if name in READ_TOOLS and project and where and not _inside(where, project):
                    outside[where] += 1
                if name == "Bash" and project:
                    m = re.match(r'\s*cd\s+"?([^"&;]+?)"?\s*(?:&&|;|$)', data.get("command", ""))
                    if m and not _inside(m.group(1), project):
                        outside["commands run in " + m.group(1)] += 1
                    for found in re.findall(r"(?:cat|head|sed -n \S+|less)\s+\"?([A-Za-z]:[/\\][^\"\s|;&]+)",
                                            data.get("command", "")):
                        if not _inside(found, project):
                            outside[found] += 1
        elif row.get("type") == "user" and isinstance(row.get("message", {}).get("content"), list):
            for block in row["message"]["content"]:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                name, data = uses.get(block.get("tool_use_id"), ("?", {}))
                content = block.get("content")
                shots = sum(1 for x in content if isinstance(x, dict) and x.get("type") == "image") \
                    if isinstance(content, list) else 0
                images += shots
                size = len(_text(content) if not isinstance(content, str) else content)
                last_result = _label(name, data)[:110]
                results.append({"chars": size, "images": shots, "tool": name, "call": last_result})
    by_tool = collections.Counter()
    for r in results:
        by_tool[r["tool"]] += r["chars"]
    total = {k: sum(p[k] for p in phases) for k in ("calls", "input", "cache_read", "cache_write", "output")}
    return {
        "transcript": path, "phases": phases, "total": total,
        "tools": dict(tools.most_common()), "engine": dict(engine.most_common()),
        "retried": dict(retried.most_common()), "images": images,
        "result_chars": dict(by_tool.most_common()),
        "largest_results": sorted(results, key=lambda r: r["chars"], reverse=True)[:top],
        "largest_rises": [{"tokens": t, "at": at, "after": what}
                          for t, at, what in sorted(rises, key=lambda x: x[0], reverse=True)[:top]],
        "outside_project": dict(outside.most_common(top)),
    }


def subagents(path):
    folder = os.path.splitext(path)[0]
    return sorted(glob.glob(os.path.join(folder, "subagents", "*.jsonl")))


def image_size(data):
    """Width and height of a base64 PNG, JPEG, GIF or WebP image, or None."""
    try:
        raw = base64.b64decode(data or "")
    except ValueError:
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if raw[:6] in (b"GIF87a", b"GIF89a") and len(raw) >= 10:
        return struct.unpack("<HH", raw[6:10])
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" and len(raw) >= 30:
        if raw[12:16] == b"VP8X":
            return (int.from_bytes(raw[24:27], "little") + 1, int.from_bytes(raw[27:30], "little") + 1)
        if raw[12:16] == b"VP8 ":
            w, h = struct.unpack("<HH", raw[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if raw[12:16] == b"VP8L":
            bits = int.from_bytes(raw[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if raw[:2] == b"\xff\xd8":
        i = 2
        while i + 9 <= len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                i += 1 if marker == 0xFF else 2
                continue
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    return None


def image_tokens(block):
    """The tokens of an image block: width × height / 750, Anthropic's rule for the image as sent."""
    size = image_size((block.get("source") or {}).get("data"))
    return round(size[0] * size[1] / 750) if size else 0


def agent_usage(path, start=0):
    """What one agent's transcript spent: calls, contexts, images, visible and billed output."""
    calls, output, thinking = {}, {}, {}
    visible = images = tokens = 0
    models = collections.Counter()
    for row in list(lines(path))[start:]:
        msg = row.get("message") or {}
        if row.get("type") == "assistant" and msg.get("id"):
            usage = msg.get("usage") or {}
            if msg["id"] not in calls:
                calls[msg["id"]] = _context(usage)
                models[msg.get("model") or "?"] += 1
            # one line per content block: the output of the message is that of its last line
            output[msg["id"]] = max(output.get(msg["id"], 0), usage.get("output_tokens", 0) or 0)
            details = usage.get("output_tokens_details") or {}
            thinking[msg["id"]] = max(thinking.get(msg["id"], 0), details.get("thinking_tokens", 0) or 0)
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    visible += len(block.get("text") or "")
                elif block.get("type") == "tool_use":
                    visible += len(block.get("name") or "") + len(json.dumps(block.get("input") or {}, ensure_ascii=False))
        elif row.get("type") == "user" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                content = block.get("content") if isinstance(block, dict) and block.get("type") == "tool_result" else None
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict) and part.get("type") == "image":
                        images += 1
                        tokens += image_tokens(part)
    contexts = list(calls.values())
    return {"calls": len(calls), "first_context": contexts[0] if contexts else 0,
            "max_context": max(contexts, default=0), "images": images, "image_tokens": tokens,
            "visible_chars": visible, "output": sum(output.values()), "thinking": sum(thinking.values()),
            "models": sorted(models)}


def _returns(paths):
    """The characters of each Agent/Task result, by the id of the call, read in every transcript given."""
    returned, kinds = {}, {}
    for path in paths:
        for row in lines(path):
            blocks = (row.get("message") or {}).get("content")
            for block in blocks if isinstance(blocks, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                    kinds[block.get("id")] = (block.get("input") or {}).get("subagent_type")
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in kinds:
                    content = block.get("content")
                    returned[block["tool_use_id"]] = len(content if isinstance(content, str) else _text(content))
    return returned, kinds


def _meta(sub):
    try:
        with open(os.path.splitext(sub)[0] + ".meta.json", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def by_agent(path, since=None):
    """One line per agent: the main one, then each type of subagent with its number."""
    start = 0
    if since:
        for i, row in enumerate(lines(path)):
            text = _prompt(row)
            if text and since in text:
                start = i
    kept = {block.get("id") for row in list(lines(path))[start:]
            for block in ((row.get("message") or {}).get("content") or [])
            if isinstance(block, dict) and block.get("type") == "tool_use"} if since else None
    subs = subagents(path)
    returned, kinds = _returns([path] + subs)
    usage = agent_usage(path, start)
    main = {"agent": "main", "count": 1, "returned_chars": None, **usage,
            "first_context": [usage["first_context"]], "max_context": [usage["max_context"]]}
    groups = {}
    for sub in subs:
        meta = _meta(sub)
        call = meta.get("toolUseId")
        if kept is not None and call not in kept:
            continue
        kind = meta.get("agentType") or kinds.get(call) or "subagent"
        one = agent_usage(sub)
        g = groups.setdefault(kind, {"agent": kind, "count": 0, "returned_chars": 0, "calls": 0, "first_context": [],
                                     "max_context": [], "images": 0, "image_tokens": 0, "visible_chars": 0,
                                     "output": 0, "thinking": 0, "models": []})
        g["count"] += 1
        for key in ("calls", "images", "image_tokens", "visible_chars", "output", "thinking"):
            g[key] += one[key]
        g["first_context"].append(one["first_context"])
        g["max_context"].append(one["max_context"])
        g["returned_chars"] += returned.get(call, 0)
        g["models"] = sorted(set(g["models"]) | set(one["models"]))
    return [main] + sorted(groups.values(), key=lambda g: -g["output"])


def _span(values):
    low, high = min(values, default=0), max(values, default=0)
    return _n(low) if low == high else f"{_n(low)}–{_n(high)}"


def render_by_agent(rows, out):
    w = out.write
    w("| Agent | Calls | Context first | Context max | Images (tokens) | Returned chars | "
      "Visible chars | Billed output (thinking) | Chars per billed token |\n|---|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        name = "main" if r["returned_chars"] is None else f"{r['agent']} ×{r['count']}"
        per = f"{r['visible_chars'] / r['output']:.1f}" if r["output"] else "–"
        back = "–" if r["returned_chars"] is None else _n(r["returned_chars"])
        w(f"| {name} | {r['calls']} | {_span(r['first_context'])} | {_span(r['max_context'])} | "
          f"{r['images']} ({_n(r['image_tokens'])}) | {back} | {_n(r['visible_chars'])} | "
          f"{_n(r['output'])} ({_n(r['thinking'])}) | {per} |\n")
    w("\nContexts are ranges over the agents of a type. A token is about 4 characters of English prose (fewer for"
      " French or JSON): far fewer characters per billed token means output the transcript does not show.\n")


def _n(value):
    return f"{value:,}".replace(",", " ")


def render(report, out):
    w = out.write
    w(f"# {report['transcript']}\n\n")
    w("## Phases (one per prompt of the user)\n\n")
    w("| Prompt | Calls | Input | Output | Context first → max |\n|---|---|---|---|---|\n")
    for p in report["phases"]:
        if not p["calls"]:   # /clear, /plugin, a local command: no call to the model
            continue
        w(f"| {p['prompt'][:60]} | {p['calls']} | {_n(p['input'])} | {_n(p['output'])} | "
          f"{_n(p['first_context'] or 0)} → {_n(p['max_context'])} |\n")
    t = report["total"]
    w(f"| **total** | {t['calls']} | {_n(t['input'])} (cache read {_n(t['cache_read'])}) | {_n(t['output'])} | |\n\n")
    for title, key in (("Tools", "tools"), ("Engine commands", "engine"), ("Engine commands run twice in a row", "retried"),
                       ("Characters of tool results, by tool", "result_chars"),
                       ("Files read outside the project", "outside_project")):
        if report[key]:
            w(f"## {title}\n\n")
            for name, count in report[key].items():
                w(f"- {_n(count)} {name}\n")
            w("\n")
    w(f"Screenshots and images returned: {report['images']}\n\n")
    w("## Largest tool results\n\n")
    for r in report["largest_results"]:
        w(f"- {_n(r['chars'])} chars, {r['images']} image(s): {r['call']}\n")
    w("\n## Largest rises of the context\n\n")
    for r in report["largest_rises"]:
        w(f"- +{_n(r['tokens'])} at {r['at']}, after {r['after']}\n")
    w("\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("transcript", nargs="?", help="the session's .jsonl")
    p.add_argument("--session", help="the session id, with --project")
    p.add_argument("--project", help="the project folder the session ran in")
    p.add_argument("--since", help="start at the last prompt of the user holding this text")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.add_argument("--by-agent", action="store_true", help="one line per agent: where each one spends")
    args = p.parse_args(argv)
    path = args.transcript or (transcript_of(args.session, args.project) if args.session and args.project else None)
    if not path or not os.path.isfile(path):
        p.error(f"no transcript: {path or 'give a transcript, or --session and --project'}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.by_agent:
        rows = by_agent(path, args.since)
        if args.json:
            json.dump(rows, sys.stdout, ensure_ascii=False, indent=1)
            sys.stdout.write("\n")
        else:
            render_by_agent(rows, sys.stdout)
        return 0
    reports = [analyse(path, args.since, args.top, args.project)]
    reports += [analyse(sub, None, args.top, args.project) for sub in subagents(path)]
    if args.json:
        json.dump(reports, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        for report in reports:
            render(report, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
