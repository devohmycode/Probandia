"""The tokens an agent used, read from its harness's transcript by the stop hooks.

The ``Stop`` and ``SubagentStop`` hooks read the transcript the harness names
(``transcript_path``; for a subagent of Claude Code, ``agent_transcript_path``,
or ``<session>/subagents/agent-<id>.jsonl``), and append to
``.probandia/tokens.jsonl`` the messages not counted yet, one line per pass:

    {"ts": "…", "research": "…", "pass": 2, "role": "researcher", "agent": "r1-archives",
     "harness": "claude-code", "session": "…", "model": "…",
     "input": 12, "output": 900, "cache_read": 40000, "cache_write": 3000, "cache_write_5m": 2000}

``cache_write`` is every token written to the cache; ``cache_write_5m`` the part of
it written to the five-minute cache (a subagent of Claude Code), the rest to the
one-hour cache (its main thread). A line written before ``cache_write_5m`` existed
lacks it: all of its ``cache_write`` counts as one-hour cache.

Each message goes to the pass whose window holds its time, from ``pass.started``
to ``pass.ended``; the messages that follow the end of a pass in the same reading
(the closing summary) go to it too. Others carry no pass.

Transcripts read:

| Harness | Transcript | What is read |
|---|---|---|
| Claude Code | JSONL, one line per part of a message | ``message.usage`` of each assistant message, the last line of each id; the five-minute part of the cache written from ``usage.cache_creation.ephemeral_5m_input_tokens`` |
| Codex | rollout JSONL | the differences between successive ``token_count`` totals |
| others | not known yet | nothing is recorded |

The role is ``session`` for the main thread. For a subagent it is its type, from
the hook's message or the ``.meta.json`` next to its transcript; a teammate of a
Claude Code team carries only its name there, so its type is taken from the
``Agent`` call that started it, in the session's transcript.
``.probandia/tokens-state.json`` keeps, per transcript, the time of the last
message counted.
"""
import datetime
import json
import os

from probandia.util.fs import atomic_write_json, iso, utc_now

FIELDS = ("input", "output", "cache_read", "cache_write", "cache_write_5m")


def _empty():
    return {k: 0 for k in FIELDS}


def _time(text):
    if not isinstance(text, str) or not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                yield e


def messages(path):
    """([(time or None, {input, output, cache_read, cache_write, cache_write_5m})], model) of one
    transcript, in order; None when the file is missing or of an unknown kind."""
    if not path or not os.path.isfile(path):
        return None
    claude, codex, model = {}, [], None
    for n, e in enumerate(_lines(path)):
        msg = e.get("message") if isinstance(e.get("message"), dict) else None
        if e.get("type") == "assistant" and msg and isinstance(msg.get("usage"), dict):
            key = msg.get("id") or f"line-{n}"
            first = claude.get(key, (_time(e.get("timestamp")), None))[0]
            claude[key] = (first, msg["usage"])   # the last line of an id counts
            model = msg.get("model") or model
            continue
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if payload.get("type") == "token_count":
            total = (payload.get("info") or {}).get("total_token_usage")
            if isinstance(total, dict):
                codex.append((_time(e.get("timestamp")), total))
        elif e.get("type") == "turn_context" and isinstance(payload.get("model"), str):
            model = payload["model"]
    if claude:
        return [(t, _claude_usage(u)) for t, u in claude.values()], model
    if codex:
        out, before = [], _empty()
        for t, total in codex:
            cached = int(total.get("cached_input_tokens") or 0)
            now = {"input": max(0, int(total.get("input_tokens") or 0) - cached),
                   "output": int(total.get("output_tokens") or 0), "cache_read": cached,
                   "cache_write": int(total.get("cache_write_input_tokens") or 0), "cache_write_5m": 0}
            delta = {k: now[k] - before[k] for k in FIELDS}
            if any(v < 0 for v in delta.values()):   # a count started again
                delta = now
            out.append((t, delta))
            before = now
        return out, model
    return None


def _claude_usage(u):
    written = int(u.get("cache_creation_input_tokens") or 0)
    split = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    return {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0), "cache_write": written,
            "cache_write_5m": min(written, int(split.get("ephemeral_5m_input_tokens") or 0))}


def parse(path):
    """The totals of one transcript, with its model, or None."""
    found = messages(path)
    if found is None:
        return None
    out = _empty()
    for _t, u in found[0]:
        for k in FIELDS:
            out[k] += u[k]
    out["model"] = found[1]
    return out


def _agent_call(main, name):
    """The ``subagent_type`` of the ``Agent`` call that named a teammate ``name``."""
    if not main or not os.path.isfile(main):
        return None
    for e in _lines(main):
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        for block in msg.get("content") or []:
            if (isinstance(block, dict) and block.get("type") == "tool_use"
                    and isinstance(block.get("input"), dict) and block["input"].get("name") == name):
                return block["input"].get("subagent_type")
    return None


def _session_transcript(payload, transcript):
    main = payload.get("transcript_path")
    if main and os.path.normcase(os.path.abspath(main)) != os.path.normcase(os.path.abspath(transcript)):
        return main
    folder = os.path.dirname(os.path.dirname(transcript))   # <session>/subagents/agent-….jsonl
    return folder + ".jsonl" if os.path.basename(os.path.dirname(transcript)) == "subagents" else None


def _strip(kind):
    kind = str(kind or "subagent")
    for prefix in ("probandia:", "probandia-"):
        kind = kind.removeprefix(prefix)
    return kind


def role_of(payload, transcript):
    """(role, agent name or None)."""
    if str(payload.get("hook_event_name") or "") != "SubagentStop":
        return "session", None
    meta = {}
    if transcript:
        try:
            with open(os.path.splitext(transcript)[0] + ".meta.json", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            meta = {}
    name = meta.get("name") or payload.get("agent_name")
    kind = payload.get("agent_type") or payload.get("subagent_type") or meta.get("agentType")
    if name and (not kind or kind == name):   # a teammate: only its name is given
        kind = _agent_call(_session_transcript(payload, transcript), name) or kind
    return _strip(kind), name


def transcript_of(payload):
    """The transcript a stop hook is about: the subagent's own for ``SubagentStop``
    (named, or found next to the session's), the session's otherwise."""
    main = payload.get("transcript_path")
    if str(payload.get("hook_event_name") or "") != "SubagentStop":
        return main
    own = payload.get("agent_transcript_path")
    if own:
        return own
    agent = payload.get("agent_id")
    if main and agent:
        folder = os.path.join(os.path.splitext(main)[0], "subagents")
        for candidate in (f"agent-{agent}.jsonl", f"agent-a{agent}.jsonl"):
            if os.path.isfile(os.path.join(folder, candidate)):
                return os.path.join(folder, candidate)
    return None   # never the session's transcript under a subagent's name


def _pass_of(t, windows):
    for p, start, end in windows:
        if t is not None and start is not None and t >= start and (end is None or t <= end):
            return p
    return None


def record(project, payload, harness, session=None, research=None, windows=(), clock=utc_now):
    """Appends the messages of the transcript not counted yet, one line per pass.
    ``windows``: [(pass, started, ended or None)] of the research. Returns the lines."""
    path = transcript_of(payload)
    found = messages(path)
    if found is None:
        return []
    msgs, model = found
    state_path = os.path.join(project, ".probandia", "tokens-state.json")
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    key = os.path.normcase(os.path.abspath(path))
    seen = state.get(key) or {}
    last = _time(seen.get("last"))
    count = int(seen.get("count") or 0)
    if last is not None:
        new = [(t, u) for t, u in msgs if t is None or t > last] if all(t for t, _u in msgs) else msgs[count:]
    else:
        new = msgs[count:]
    times = [t for t, _u in msgs if t is not None]
    first = seen.get("first_context")
    if first is None and msgs:   # what every call reads again before any work: the base
        first = msgs[0][1]["input"] + msgs[0][1]["cache_read"] + msgs[0][1]["cache_write"]
    state[key] = {"last": iso(max(times)) if times else None, "count": len(msgs), "first_context": first,
                  "main": "subagents" not in os.path.normcase(path).split(os.sep)}
    atomic_write_json(state_path, state)
    windows = [(p, _time(s) if isinstance(s, str) else s, _time(e) if isinstance(e, str) else e)
               for p, s, e in windows]
    now = clock()
    groups, current = {}, None
    for t, u in new:
        p = _pass_of(t or now, windows)
        if p is None and current is not None:
            p = current       # after the end of a pass, in the same reading: its closing summary
        current = p if p is not None else current
        g = groups.setdefault(p, _empty())
        for k in FIELDS:
            g[k] += u[k]
    role, agent = role_of(payload, path)
    out = []
    for p, totals in groups.items():
        if not any(totals.values()):
            continue
        line = {"ts": iso(now), "research": research, "pass": p, "role": role, "agent": agent,
                "harness": harness, "session": session, "model": model}
        line.update(totals)
        out.append(line)
    if out:
        os.makedirs(os.path.join(project, ".probandia"), exist_ok=True)
        with open(os.path.join(project, ".probandia", "tokens.jsonl"), "a", encoding="utf-8",
                  newline="\n") as fh:
            for line in out:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return out


# The context of the first call of a session: the system prompt, the tools, the
# skills, the MCP servers and the instructions of every plugin the harness loaded.
# Probandia's own part was about 1,200 tokens in Claude Code 2.1.287 (19 skills and
# commands, 7 agents, 1 MCP server; docs/claude-code-mod.md § 3). Above BASE_HEAVY,
# the other plugins cost more than the research: each call reads them again.
PLUGIN_BASE = 1200
BASE_HEAVY = 40000


def base_context(project):
    """(tokens, last time) of the first call of the latest main session recorded, or None."""
    try:
        with open(os.path.join(project, ".probandia", "tokens-state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return None
    found = [(v.get("last") or "", v["first_context"]) for v in state.values()
             if isinstance(v, dict) and v.get("main", True) and v.get("first_context")]
    if not found:
        return None
    last, tokens = max(found)
    return tokens, last


def windows_of(events_list):
    """[(pass, started, ended or None)] from a research's events."""
    out = {}
    for e in events_list:
        if e.get("type") == "pass.started":
            out[e.get("pass")] = [e.get("pass"), e.get("ts"), None]
        elif e.get("type") == "pass.ended" and e.get("pass") in out:
            out[e["pass"]][2] = e.get("ts")
    return [tuple(v) for v in out.values()]


def entries(project):
    try:
        with open(os.path.join(project, ".probandia", "tokens.jsonl"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return []


def by_role(project, research, pass_no=None):
    """(pass, {role: totals}) for one pass of a research, the last one that has
    any when ``pass_no`` is None."""
    rows = [e for e in entries(project) if e.get("research") == research and e.get("pass") is not None]
    if pass_no is None:
        pass_no = max((e["pass"] for e in rows), default=None)
    out = {}
    for e in rows:
        if e["pass"] != pass_no:
            continue
        t = out.setdefault(e.get("role") or "?", _empty())
        for k in FIELDS:
            t[k] += int(e.get(k) or 0)
    return pass_no, out


# Prices relative to an input token (Anthropic's ratios for its Claude models): a
# cache read costs a tenth, a write to the one-hour cache (Claude Code's main
# thread) twice, a write to the five-minute cache (its subagents) 1.25 times, an
# output token five times. Kinds differ too much in price to be added up as they
# are: 1.7 million cache reads weigh less than 6,500 output tokens do.
# ``cache_write`` holds both caches: its weight applies to what is not ``cache_write_5m``.
WEIGHTS = {"input": 1.0, "cache_read": 0.1, "cache_write": 2.0, "cache_write_5m": 1.25, "output": 5.0}


def weighted(totals):
    """Input-equivalent tokens: each kind at its relative price."""
    written = int(totals.get("cache_write") or 0)
    short = min(written, int(totals.get("cache_write_5m") or 0))
    return round(WEIGHTS["input"] * int(totals.get("input") or 0) + WEIGHTS["output"] * int(totals.get("output") or 0)
                 + WEIGHTS["cache_read"] * int(totals.get("cache_read") or 0)
                 + WEIGHTS["cache_write"] * (written - short) + WEIGHTS["cache_write_5m"] * short)


def pass_weighted(project, research, pass_no):
    """token-economy I2: the input-equivalent tokens recorded so far for one pass, every role together
    (what ``pass status`` and the digest show); None when none was recorded."""
    _p, roles = by_role(project, research, pass_no)
    if not roles:
        return None
    return weighted({k: sum(t[k] for t in roles.values()) for k in FIELDS})


def kinds(project, research):
    """{input, output, cache_read, cache_write, cache_write_5m, weighted} of a research, or None
    when none was recorded."""
    rows = [e for e in entries(project) if e.get("research") == research]
    if not rows:
        return None
    out = _empty()
    for e in rows:
        for k in FIELDS:
            out[k] += int(e.get(k) or 0)
    out["weighted"] = weighted(out)
    return out


def by_model(project, research, role=None):
    """{(harness, model): {input, output, cache_read, cache_write, cache_write_5m, weighted}} of a
    research (of one role of it when ``role`` is given), the heaviest pair first: a research whose
    agents run on several models (the main thread on one, the readers on another) mixes tokens of
    different prices (version-1.0.0 T38)."""
    out = {}
    for e in entries(project):
        if e.get("research") != research or role is not None and e.get("role") != role:
            continue
        t = out.setdefault((e.get("harness"), e.get("model")), _empty())
        for k in FIELDS:
            t[k] += int(e.get(k) or 0)
    for t in out.values():
        t["weighted"] = weighted(t)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["weighted"]))
