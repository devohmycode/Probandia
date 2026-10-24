"""Entry point of the harness hooks: ``run_probandia.py hook <function>``.

| Function | When | What it does |
|---|---|---|
| ``guard`` | before a tool runs | the rules of ``guard.py``; a refusal in the harness's format |
| ``session`` | when a session starts, or starts again after a compaction | the plugin's options and the agents' copies; after a compaction, with a pass this session holds, the state digest as context |
| ``digest`` | when the user submits a prompt | on ``/probandia:resume``, the state digest as context |
| ``log`` | after a tool ran | native and MCP web searches into the search log; MCP calls of a provider into the ledger; a team's messages into the relay; in Claude Code, a long page an MCP reader returned into ``work/reads/``; a page ``WebFetch`` returned that did not load, told as not consulted |
| ``verify`` | when the agent stops | the light verification and the quotas left, as a short message |

A hook reads the harness's payload on standard input and:

- stays silent outside a Probandia project;
- never blocks on an internal error: it exits 0 with no output (Antigravity,
  where silence refuses, gets an explicit ``allowTool``);
- keeps within its timeout (10 s for the guard, 15 s for the others);
- with ``PROBANDIA_WORKER=1`` (child runs), silences ``digest``, ``verify`` and the
  digest of ``session``; the guard and the log keep running. ``hooks.digest`` turns off
  both digests.
"""
import json
import os
import re
import sys

from probandia.util.locks import SESSION_VARIABLES, session_id

FUNCTIONS = ("guard", "digest", "log", "verify", "session")
WEB_SEARCH_TOOLS = {"WebSearch", "web_search", "websearch", "search_web", "web_search_preview"}
MESSAGE_TOOLS = {"SendMessage", "send_message"}
FETCH_TOOLS = {"webfetch", "web_fetch"}
RESUME = re.compile(r"(^|\s)/?probandia[:\s]resume\b|/resume\b.*probandia", re.I)
PREFIX = re.compile(r"\s*(?:/\S+\s+)?(seul|solo|agents)\s*:", re.I)   # also after a slash command


def _harness(payload, environ, explicit=None):
    from probandia.harness import detect

    name = explicit if explicit and explicit != "cli" else (payload.get("harness") or environ.get("PROBANDIA_HARNESS"))
    if name:
        return name
    return detect(None, environ)[0]


def _session(payload, environ):
    if any(environ.get(v) for v in SESSION_VARIABLES):
        return session_id(environ)
    return payload.get("session_id") or payload.get("conversation_id") or session_id(environ)


def _read_stdin(stream=None):
    """The payload: harnesses send UTF-8 JSON, whatever the console's code page
    (on Windows, a text read in cp1252 turned "Rémy" into "RÃ©my")."""
    stream = sys.stdin if stream is None else stream
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream.read()
    return buffer.read().decode("utf-8-sig", errors="replace")


def run(function, stdin=None, environ=None, harness=None):
    """Runs one hook function. Returns the text to print (empty: nothing)."""
    environ = os.environ if environ is None else environ
    payload = {}
    try:
        raw = stdin.read() if stdin is not None else _read_stdin()
        payload = json.loads(raw) if raw.strip() else {}
        if function not in FUNCTIONS or not isinstance(payload, dict):
            return ""
        name = _harness(payload, environ, harness)
        if not enabled(function, payload, environ):
            if function == "guard":
                from probandia import guard as g

                return _json(g.allowed(name))
            if function == "verify":   # the tokens are measured even without the verify hook
                log_tokens(payload, environ, name)
            return ""
        if function == "guard":
            return _json(guard(payload, environ, name))
        if function in ("session", "digest"):   # SessionStart and every prompt: /config may change
            remember_options(payload, environ)
            if function == "session":
                sync_agent_copies(payload, environ, name)
                if environ.get("PROBANDIA_WORKER") == "1" or not enabled("digest", payload, environ):
                    return ""
                return _json(compacted(payload, environ, name))
        if function == "log":
            log_native_search(payload, environ, name)
            log_mcp_search(payload, environ, name)
            log_provider_call(payload, environ)
            log_team_message(payload, environ)
            log_learned_use(payload, environ)
            return _json(trim_mcp_read(payload, environ, name) or unconsulted_page(payload, environ))
        if function == "verify":   # Stop and SubagentStop: the tokens first, workers included
            log_tokens(payload, environ, name)
        if environ.get("PROBANDIA_WORKER") == "1":
            return ""
        if function == "digest":
            return _json(digest(payload, environ, name))
        return _json(verify(payload, environ, name))
    except Exception:  # noqa: BLE001 — a hook never blocks on its own failure
        if function == "guard" and _harness(payload if isinstance(payload, dict) else {}, environ,
                                            harness) == "antigravity":
            return _json({"allowTool": True})
        return ""


# The setting that turns each hook function off (grade Expert). ``log`` writes the
# search journal, hence ``hooks.journal``; ``session`` only remembers the options.
HOOK_SETTINGS = {"guard": "hooks.guard", "digest": "hooks.digest", "log": "hooks.journal",
                 "verify": "hooks.verify"}


def enabled(function, payload, environ):
    """False when the project's settings turn this hook function off."""
    key = HOOK_SETTINGS.get(function)
    if key is None:
        return True
    from probandia.config import load
    from probandia.errors import ProbandiaError
    from probandia.project import find_project

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        return True   # outside a project every function stays silent anyway
    return bool(load(project, environ, strict=False).get(key))


def _json(obj):
    return json.dumps(obj, ensure_ascii=False) + "\n" if obj else ""


# guard


def guard(payload, environ, harness):
    from probandia import guard as g

    found = g.check(payload, environ, harness)
    if found is not None and not isinstance(found[1], g.Notice):
        return g.refusal(harness, found[0], found[1])
    # agent-models R3: a Probandia agent launched with the model and the effort chosen for its role
    try:
        tool_input = g.agent_settings(payload, environ, harness)
    except Exception:   # noqa: BLE001 — a setting never stops an agent from starting
        tool_input = None
    if found is None:
        return g.updated(harness, tool_input) if tool_input else g.allowed(harness)
    out = g.notice(harness, *found)
    return g.updated(harness, tool_input, out) if tool_input else out


# session


def remember_options(payload, environ):
    """The plugin options the harness exported to the hook, kept for the engine's
    calls, and the project's short launcher (``launcher``)."""
    from probandia import launcher
    from probandia.errors import ProbandiaError
    from probandia.project import find_project

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        return None
    try:
        launcher.write_launcher(project)
        text = launcher.from_environment(environ)
        return launcher.remember(project, text, _session(payload, environ)) if text else False
    except OSError:
        return None


def sync_agent_copies(payload, environ, harness):
    """agent-models R6: at each session start in Cursor, Factory Droid or Grok, the project's copies of the
    agents follow the roles' settings and the plugin's own agents. Never fails the session."""
    from probandia.errors import ProbandiaError
    from probandia.install import copies
    from probandia.project import find_project

    if harness not in copies.FOLDERS:
        return None
    roots = payload.get("workspace_roots") or []   # Cursor names the workspace, not a cwd
    where = payload.get("cwd") or (roots[0] if roots and isinstance(roots[0], str) else None) or os.getcwd()
    try:
        return copies.sync(find_project(None, environ, where), harness, environ)
    except (ProbandiaError, OSError, ValueError):
        return None


def compacted(payload, environ, harness):
    """T71: after a compaction, the state digest of the pass this session holds, as context, so that the
    agent does not read the pass again (``known``, ``digest``, ``work/``); 60 lines at most (``digest.max_lines``).

    Claude Code runs SessionStart with ``"source": "compact"`` "after compaction" (matcher ``compact``:
    "Auto or manual compaction"), and ``hookSpecificOutput.additionalContext`` is the "String added to
    Claude's context" (SessionStart input and decision control, https://code.claude.com/docs/en/hooks,
    read 14 Oct. 2026). Codex (https://learn.chatgpt.com/docs/hooks) and Factory Droid
    (https://docs.factory.com/reference/hooks-reference) document the same source and field; Grok
    (https://docs.x.ai/build/features/hooks) documents neither, so it gets nothing."""
    if payload.get("source") != "compact" or harness not in ("claude-code", "codex", "droid", "grok"):
        return None
    held = _held_pass(payload, environ, harness)
    if held is None:
        return None
    from probandia import digest as d
    from probandia.config import load

    project, research, _n = held
    lines = d.lines_for(project, research, load(project, environ, strict=False), environ)
    d.seen(project, _session(payload, environ), research.id, lines)   # E6: a later resume gives the changes
    return {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": "Probandia state digest:\n" + "\n".join(lines)}}


# digest


def _run_mode_prefix(prompt):
    """FL-D6: a message that starts with ``seul :`` (or ``solo:``) or ``agents :`` sets who runs the
    research, whatever the message, as in a real workshop."""
    m = PREFIX.match(prompt)
    if not m:
        return None
    mode = "team" if m.group(1).lower() == "agents" else "session"
    return (f"Probandia: the message starts with `{m.group(1)} :`: run the research with `--mode {mode}` "
            f"(new or resume), without asking the run mode.")


def digest(payload, environ, harness):
    prompt = str(payload.get("prompt") or payload.get("user_prompt") or "")
    prefix = _run_mode_prefix(prompt)
    if not (RESUME.search(prompt) or prefix) or harness not in ("claude-code", "codex", "droid", "grok"):
        return None
    from probandia import digest as d
    from probandia.errors import ProbandiaError
    from probandia.project import find_project
    from probandia.research import find_research

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        return None
    context = [prefix] if prefix else []
    if RESUME.search(prompt):
        try:
            research = find_research(project, fallback=True)
        except ProbandiaError:
            research = None
        if research is not None:
            from probandia.config import load

            lines = d.lines_for(project, research, load(project, environ, strict=False), environ)
            d.seen(project, _session(payload, environ), research.id, lines)   # E6: resume then gives the changes
            context.append("Probandia state digest:\n" + "\n".join(lines))
    if not context:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(context)}}


# log


# Grok Build sends toolName and toolInput (docs.x.ai/build/features/hooks, read 17 Oct. 2026)
def _tool_name(payload):
    return str(payload.get("tool_name") or payload.get("toolName") or (payload.get("toolCall") or {}).get("name")
               or "")


def _tool_input(payload):
    out = payload.get("tool_input") or payload.get("toolInput") or (payload.get("toolCall") or {}).get("args") or {}
    return out if isinstance(out, dict) else {}


def log_native_search(payload, environ, harness=None):
    tool = _tool_name(payload)
    if tool not in WEB_SEARCH_TOOLS:
        return None
    from probandia.errors import ProbandiaError
    from probandia.lifecycle import current_pass
    from probandia.project import find_project
    from probandia.providers import searchlog
    from probandia.research import find_research

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
        research = find_research(project, fallback=True)
    except ProbandiaError:
        return None  # outside a project, or no research in progress: stay silent
    tool_input = _tool_input(payload)
    query = tool_input.get("query") or tool_input.get("q") or ""
    if not query:
        return None
    urls = searchlog.urls_in(payload.get("tool_response") or payload.get("tool_output") or {})
    harness = harness or _harness(payload, environ)
    filters = {k: tool_input[k] for k in ("allowed_domains", "blocked_domains") if tool_input.get(k)}
    filters["session"] = _session(payload, environ)
    e = searchlog.entry(query, "native", f"native:{harness}", "opaque",
                        "positive" if urls else "negative", research.id, current_pass(research),
                        len(urls), filters=filters)
    actor = {"harness": harness, "agent": (payload.get("agent_type") or "session").split(":")[-1],
             "session": filters["session"]}
    searchlog.append(project, research.family, [e], actor, "native search", dedupe=False)
    from probandia.config import load

    try:   # T55: its URLs kept for cache.days, for the guard's G-16
        searchlog.keep_native(project, research, harness, e, tool_input, urls,
                              load(project, environ, strict=False).get("cache.days"))
    except OSError:
        pass
    return e


def _mcp(tool, cat=None):
    """(provider, operation) of an MCP tool: ``catalogue.mcp_tool`` (T49)."""
    from probandia.providers import catalogue

    return catalogue.mcp_tool(tool, cat)


# What an answer says it cost, by the unit of the provider's free tier.
REPORTED = {"credit": ("creditsUsed", "credits_used", "credits"),
            "dollar": ("usageTotalUsd", "costDollars.total", "costDollars", "cost_usd"),
            "token": ("usage.tokens", "tokens")}


def _answer_parts(response):
    """The JSON objects an MCP tool answered: the answer itself, or the JSON texts
    of its ``content`` blocks."""
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return []
    parts = [response] if isinstance(response, dict) else []
    blocks = response.get("content") if isinstance(response, dict) else response
    for block in blocks if isinstance(blocks, list) else []:
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, str) and text.lstrip()[:1] in "{[":
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                parts.append(parsed)
    return parts


def reported_units(response, unit):
    """The units an MCP answer reports it used (``creditsUsed`` of Firecrawl,
    ``costDollars`` of Exa, ``usageTotalUsd`` of an Apify run, Jina's tokens), or
    None when it says nothing: the catalogue's cost is then counted."""
    from probandia.providers.base import dig

    for part in _answer_parts(response):
        for path in REPORTED.get(unit, ()):
            value = dig(part, path)
            if value is None and isinstance(part.get("data"), dict):
                value = dig(part["data"], path)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            return float(value)
    return None


def log_mcp_search(payload, environ, harness=None):
    """A web search made through an MCP server (``mcp__tavily__tavily_search``, a
    connector such as ``mcp__claude_ai_Firecrawl__firecrawl_search``) goes into the
    search log, as the engine's own searches do: a provider's search under its id,
    any other web search under ``mcp:<server>``. Probandia's own server logs itself."""
    tool = _tool_name(payload)
    if not tool.startswith("mcp__") or tool.count("__") < 2 or "probandia" in tool.lower():
        return None
    server, name = tool.split("__")[1], tool.split("__", 2)[2].lower()
    if "search" not in name:
        return None
    provider, operation = _mcp(tool)
    if provider is None and "web" not in name:
        return None  # a search in Slack or Linear is not a web search
    if provider is not None and operation != "search":
        return None  # ScrapeGraph's search extracts (T49)
    tool_input = _tool_input(payload)
    query = next((str(tool_input[k]) for k in ("query", "q", "search_query", "objective") if tool_input.get(k)), "")
    if not query:
        return None
    from probandia.errors import ProbandiaError
    from probandia.lifecycle import current_pass
    from probandia.project import find_project
    from probandia.providers import searchlog
    from probandia.research import find_research

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
        research = find_research(project, fallback=True)
    except ProbandiaError:
        return None
    urls = searchlog.urls_in(payload.get("tool_response") or payload.get("tool_output") or {})
    harness = harness or _harness(payload, environ)
    filters = {"tool": tool, "session": _session(payload, environ)}
    e = searchlog.entry(query, "provider", provider or f"mcp:{server.lower()}", "opaque",
                        "positive" if urls else "negative", research.id, current_pass(research),
                        len(urls), filters=filters)
    actor = {"harness": harness, "agent": (payload.get("agent_type") or "session").split(":")[-1],
             "session": filters["session"]}
    searchlog.append(project, research.family, [e], actor, "MCP search")
    return e


TRIM_AT, KEEP = 8000, 2000   # characters of an MCP page: beyond TRIM_AT, the agent gets the first KEEP
BROWSER_SERVER = re.compile(r"chrome|browser|playwright|puppeteer", re.I)


def _response_text(response):
    """The text of an MCP answer (a string, or text blocks), or None when it holds more than text."""
    if isinstance(response, str):
        return response
    blocks = response.get("content") if isinstance(response, dict) else response
    if not blocks or not isinstance(blocks, list) or \
            not all(isinstance(b, dict) and b.get("type") == "text" for b in blocks):
        return None
    return "\n".join(str(b.get("text") or "") for b in blocks)


def trim_mcp_read(payload, environ, harness):
    """Claude Code only (token-economy D3): a page an MCP reader (scrape, read, extract,
    crawl, not a search) returned beyond TRIM_AT characters, during an open pass, goes
    whole into the research's ``work/reads/``; the agent gets its start and the path,
    through PostToolUse's ``updatedToolOutput``, in the shape the tool answered."""
    tool = _tool_name(payload)
    if harness != "claude-code" or not tool.startswith("mcp__") or tool.count("__") < 2 \
            or "probandia" in tool.lower() or _mcp(tool)[1] in (None, "search") \
            or BROWSER_SERVER.search(tool.split("__")[1]):   # a browser's page tree holds the refs it clicks
        return None
    response = payload.get("tool_response")
    text = _response_text(response)
    if text is None or len(text) <= TRIM_AT:
        return None
    from probandia import events
    from probandia.errors import ProbandiaError
    from probandia.lifecycle import pass_state
    from probandia.project import find_project
    from probandia.research import find_research
    from probandia.util.ids import ulid

    try:
        research = find_research(find_project(None, environ, payload.get("cwd") or os.getcwd()), fallback=True)
    except ProbandiaError:
        return None
    if not pass_state(events.read(research.events_path))[1]:
        return None
    name = re.sub(r"[^a-z0-9_-]+", "-", tool.split("__", 2)[2].lower())
    path = os.path.join(research.work, "reads", f"{name}-{ulid()}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    short = f"{text[:KEEP]}\n…\n[full page, {len(text)} characters: {path}; grep that file, or Read it]"
    if isinstance(response, str):
        out = short
    elif isinstance(response, dict):
        out = dict(response, content=[{"type": "text", "text": short}])
    else:
        out = [{"type": "text", "text": short}]
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": out}}


def unconsulted_page(payload, environ):
    """T59: a page ``WebFetch`` returned that did not load (a challenge, an empty shell, an error code), as
    the detector judges its answer: the agent is told that no negative can come from it, and to ``read``
    it. A page that loaded says nothing."""
    tool = _tool_name(payload)
    if tool.lower() not in FETCH_TOOLS:
        return None
    from probandia.reading.detector import OK, classify_fetch

    response = payload.get("tool_response") or payload.get("tool_output")
    tool_input = _tool_input(payload)
    url = str(tool_input.get("url") or "")
    if isinstance(response, dict):
        status, _rule = classify_fetch(response.get("code"), response.get("result"), response.get("bytes"))
        url = url or str(response.get("url") or "")
    else:
        status, _rule = classify_fetch(None, response)
    if status == OK:
        return None
    from probandia.errors import ProbandiaError
    from probandia.i18n import _
    from probandia.project import find_project

    try:
        find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        return None
    text = _("page NOT CONSULTED ({status}): no negative from it; read {url}").format(status=status, url=url)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": f"Probandia: {text}"}}


def log_tokens(payload, environ, harness=None):
    """What the agent that stops used, read from its transcript (``tokens``), with
    the research and its open pass."""
    from probandia import events, tokens
    from probandia.errors import ProbandiaError
    from probandia.project import find_project
    from probandia.research import find_research

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        return None
    research, windows = None, []
    try:
        r = find_research(project, fallback=True)
        research, windows = r.id, tokens.windows_of(events.read(r.events_path))
    except ProbandiaError:
        pass
    try:
        return tokens.record(project, payload, harness or _harness(payload, environ),
                             _session(payload, environ), research, windows)
    except OSError:
        return None


def log_provider_call(payload, environ):
    """An MCP tool of a catalogued provider (``mcp__tavily__…``) uses its free quota:
    the ledger counts it, as the engine's own calls are counted, at the cost the
    answer reports when it reports one."""
    tool = _tool_name(payload)
    if not tool.startswith("mcp__"):
        return None
    from probandia.errors import ProbandiaError
    from probandia.ledger import Ledger
    from probandia.lifecycle import current_pass
    from probandia.project import find_project
    from probandia.providers import catalogue
    from probandia.research import find_research

    cat = catalogue.load()
    provider, operation = _mcp(tool, cat)
    if provider is None or operation is None:   # a status or a balance costs nothing
        return None
    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        return None
    research, pass_no = None, None
    try:
        r = find_research(project, fallback=True)
        research, pass_no = r.id, current_pass(r)
    except ProbandiaError:
        pass
    from probandia.util import envfile

    # the keys of the .env files decide whose counter pays (cli.md § 4.4)
    ledger = Ledger(project, cat, environ=envfile.merged(environ, project))
    units = reported_units(payload.get("tool_response") or payload.get("tool_output"),
                           cat[provider].get("unit"))
    if units is None:
        units = ledger.cost(provider, operation)
    return ledger.record(provider, operation, units, "hook", research, pass_no, note=f"MCP {tool}")


LEAD_NAMES = {"team-lead", "lead", "main"}  # the lead of a Claude Code team is the orchestrator


def _inbox_name(name):
    name = re.sub(r'[\\/:*?"<>|\s]+', "-", str(name or "").strip()).strip("-.")
    return "orchestrator" if name.lower() in LEAD_NAMES else name or "all"


LEARNED_TOOLS = {"Skill": ("skill", "name", "command"), "Agent": ("subagent_type", "agent_type", "name"),
                 "Task": ("subagent_type", "agent_type", "name")}


def log_learned_use(payload, environ):
    """A learned skill or agent (``probandia-<name>``) loaded or started: one more use
    in the library (optimize 5.1.9). The plugin's own skills and agents are not counted."""
    tool = _tool_name(payload)
    if tool not in LEARNED_TOOLS:
        return None
    tool_input = _tool_input(payload)
    name = next((str(tool_input[k]) for k in LEARNED_TOOLS[tool] if tool_input.get(k)), "")
    name = name.split(":")[-1].strip()
    if not name.startswith("probandia-"):
        return None
    from probandia.errors import ProbandiaError
    from probandia.library import record_use
    from probandia.project import find_project

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
    except ProbandiaError:
        project = None
    failed = isinstance(payload.get("tool_response"), dict) and bool(payload["tool_response"].get("is_error"))
    return record_use(project, name, environ, ok=not failed)


def log_team_message(payload, environ):
    """A message sent with the harness's own tool (``SendMessage`` in Claude Code)
    during a team research: the relay keeps a copy in the recipient's inbox, so the
    orchestrator and the log see every exchange. A JSON body ``{type, from, body,
    refs}`` keeps its fields; plain text is a ``finding``."""
    tool = _tool_name(payload)
    if tool not in MESSAGE_TOOLS:
        return None
    tool_input = _tool_input(payload)
    to = next((tool_input[k] for k in ("to", "recipient", "target") if tool_input.get(k)), None)
    raw = next((tool_input[k] for k in ("message", "content", "body") if tool_input.get(k)), None)
    if not to or raw is None:
        return None
    from probandia import team
    from probandia.errors import ProbandiaError
    from probandia.project import find_project
    from probandia.research import find_research

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
        research = find_research(project, fallback=True)
    except ProbandiaError:
        return None
    if ((research.meta() or {}).get("run") or {}).get("mode") != "team":
        return None
    msg = raw
    if isinstance(raw, str):
        try:
            msg = json.loads(raw)
        except ValueError:
            msg = raw
    if not isinstance(msg, dict):
        msg = {"body": raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)}
    type_ = msg.get("type") if msg.get("type") in team.TYPES else "finding"
    sender = msg.get("from") or (payload.get("agent_type") or "orchestrator").split(":")[-1]
    body = msg.get("body")
    if body is None:
        body = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    refs = msg.get("refs") if isinstance(msg.get("refs"), list) else []
    return team.send(research, _inbox_name(sender), _inbox_name(to), type_,
                     body if isinstance(body, str) else json.dumps(body, ensure_ascii=False),
                     [str(r) for r in refs], via=tool)


# verify


def _held_pass(payload, environ, harness):
    """(project, research, pass) when a pass is open and this session holds its lock, else None."""
    from probandia import events
    from probandia.errors import ProbandiaError
    from probandia.lifecycle import pass_state
    from probandia.project import find_project
    from probandia.research import find_research
    from probandia.util.locks import Locks, same_session

    try:
        project = find_project(None, environ, payload.get("cwd") or os.getcwd())
        research = find_research(project, environ=environ, fallback=True)
    except ProbandiaError:
        return None
    last, open_ = pass_state(events.read(research.events_path))
    if not open_:
        return None
    info, expired = Locks(project).status(f"research:{research.id}")
    me = {"harness": harness, "session": _session(payload, environ)}
    if info is None or expired or not same_session(info.get("owner"), me):
        return None
    return project, research, last


def verify(payload, environ, harness):
    """At the end of a turn with a pass open by this session, one short message when
    there is something to say (G4): the light rules the pass's own work fails, or a
    pass with no web search nor MCP call yet; then the tools of the pass."""
    if harness not in ("claude-code", "codex", "droid", "grok"):
        return None
    from probandia import verify as v
    from probandia.config import load
    from probandia.lifecycle import tool_counts

    held = _held_pass(payload, environ, harness)
    if held is None:
        return None
    project, research, last = held
    config = load(project, environ, strict=False)
    failed = [f"{rule} {msg}" for rule, status, msg in v.run(project, research, config, light=True, pass_no=last)
              if status == "FAIL"]
    tools = tool_counts(project, research, last)   # FL-D7: the tools of the pass so far
    if not (tools["web"] or tools["mcp"]):   # FL-D1: the first salvo always holds web searches
        failed.append("no web search and no MCP call yet in this pass")
    if not failed:
        return None
    text = "Probandia: " + "; ".join(failed[:3])
    text += (f"; tools of pass {last}: web {tools['web']}, MCP {tools['mcp']}, archives {tools['archive']}, "
             f"engine {tools['engine']}")
    return {"systemMessage": text}
