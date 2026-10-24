"""The guard: the rules a tool call must pass before it runs.

| Rule | Refused |
|---|---|
| G-1 | a field agent writing ``families/*/index/**``, ``**/events.jsonl``, ``**/report/**`` or ``**/research.yaml`` |
| G-2 | a field agent running ``apply``, ``event append``, ``render``, ``export``, ``git commit`` or ``git push`` |
| G-3 | a third-party reader or scraper (Jina, Firecrawl, Bright Data, ScrapeGraph, Tavily extract) aimed at a host marked ``third_party: forbidden``; aimed at a host that only looks like an archive portal (``ladder.ARCHIVE_HOST``, in no catalogue), allowed with a notice to use ``read`` or the browser |
| G-4 | an unattended run (``PROBANDIA_WORKER=1``) writing outside the research's ``work/`` folder |
| G-5 | a ``draft`` learned script run inside a pass without the user's approval |
| G-6 | a field agent reading the family index, ``events.jsonl`` or the rendered report raw: ``known`` and ``digest`` give the same, compact; the session agent or the orchestrator reading the family index raw in an open pass, in Claude Code (T257): ``known`` or ``status`` |
| G-7 | reading again a proposal ``propose`` has just stored (PRD K-8): its summary said what is in it; refused once, then allowed |
| G-9 | typing into a page with a browser tool while a ``login_required`` question waits: signing in is the user's (optimize 3.6) |
| G-8 | any agent writing in a folder of skills or agents (``.claude/skills``, ``.agents/skills``, ``.claude/agents``…): a learned skill or agent goes through ``library draft`` and ``library install``, after the user's approval |
| G-10 | any agent changing the managed section of ``AGENTS.md`` or ``CLAUDE.md`` (between ``<!-- probandia:begin -->`` and ``<!-- probandia:end -->``) with an edit tool or the shell: entries go through ``memory add`` and ``memory remove``, after the user's approval |
| G-11 | a field agent closing a research or changing its questions (``close``, ``question add``, ``edit``, ``answer``, ``unresolved``, ``reopen``): the orchestrator settles them (GPS1-T5); ``question list`` stays open, and the MCP tool ``question`` only lists |
| G-12 | a script or a shell command posing as a browser (``Mozilla/…`` User-Agent, ``fake_useragent``, ``cloudscraper``, ``impersonate=``) toward an archive portal: requests keep the engine's identity (token-economy A1) |
| G-13 | the session agent or the orchestrator reading an image of the family's folder in an open pass, in Claude Code: a register's views are a reader's (token-economy A7); refused at the first of the pass, then allowed with a notice that counts them; a view a transcription names (its ``Image`` row) opens freely, to check a doubt |
| G-14 | a reader reading a whole view of a register (``<archive>-<register>-<nnnn>.jpg``, as an archive saved it) of more than 2,500 tokens: it sees it on a sheet or small and reads the act in a crop cut at full size (token-economy J8, T73c); allowed without Pillow, which sheets and crops need |
| G-15 | during an open pass, an MCP tool of a search or reading provider (``catalogue.mcp_tool``, T49) or of a web service known by name: the engine's command that does the same instead (``search "<query>" --engine <provider>``, ``read <url>``, ``--map``, ``--crawl <n>``, ``--extract``), which counts the quota before the call; Claude in Chrome, Probandia's server and the servers off the web pass |
| G-16 | a native web search already run for the family within ``cache.days`` (same normalised query, same domains, any pass): refused once, with its date, its pass, its number of results and the file of its URLs; then allowed |
| G-17 | a ``WebFetch`` of a host of the archive catalogues, every time: ``read <url> --question "<prompt>"`` keeps its rate; of a page ``read`` keeps, once, with its file; any other page gets a notice to use ``read`` first, once per URL. A page ``read`` failed to read (``.probandia/read-failures.json``, for ``cache.days``) is fetched, with a notice once, unless its host forbids third parties |
| G-18 | any agent writing the workshop's ``commun/personnes.yaml`` in a project linked to it (``workshop.yaml``), with an edit tool or the shell: ``workshop push`` writes it, under the workshop's rules (WS4-T5); reading it stays open |
| W-3 | a native web search beyond the pass's budget or the session cap |

Field agents: researcher, investigator, harvester, reader, searcher,
contradictor. Claude Code names the subagent in ``agent_type``
(``probandia:<role>`` or ``<role>``); elsewhere ``PROBANDIA_AGENT`` may.

A call no rule refuses may still be rewritten: in Claude Code, the launch of a Probandia agent
takes the model and the effort chosen for its role (``agent_settings``, agent-models R3).
"""
import json
import os
import re
from urllib.parse import urlparse

FIELD_ROLES = {"researcher", "investigator", "harvester", "reader", "searcher", "contradictor"}
WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "write_file", "edit_file", "replace",
               "create_file", "str_replace_editor", "str_replace_based_edit_tool", "apply_patch",
               "write_to_file", "replace_file_content", "multi_replace_file_content",
               "search_replace", "edit_notebook", "delete_file",   # Grok Build's own (its tool table, 1.0.50)
               "create", "applypatch"}   # Factory Droid's (its log, 0.245, T259)
READ_TOOLS = {"read", "read_file", "readfile", "view_file", "view", "open_file", "notebookread", "cat"}
SHELL_READ = re.compile(r"(^|[\s;|&(])(cat|type|Get-Content|gc|head|tail|less|more|bat)(\s|$)", re.I)
READ_PROTECTED = ((re.compile(r"(^|/)families/[^/]+/index(/|$)"), "known <research>"),
                  (re.compile(r"(^|/)events\.jsonl$"), "digest <research>"),
                  (re.compile(r"(^|/)report/[^/]+\.(md|html|json)$"), "digest <research> or known <research>"))
STORED_PROPOSAL = re.compile(r"(^|/)work/proposals/([0-9A-HJKMNP-TV-Z]{26})\.yaml$")
FRESH_SECONDS = 15 * 60   # a proposal stored less than this long ago was just summarised by propose
SHELL_TOOLS = {"bash", "shell", "run_command", "run_shell_command", "exec_command", "terminal", "powershell",
               "run_terminal_command", "run_terminal_cmd", "execute"}
WEB_SEARCH_TOOLS = {"websearch", "web_search", "search_web", "web_search_preview"}
# matched on the path made relative to the project, "/"-separated, ".." resolved, any case (T141)
PROTECTED = (re.compile(r"(^|/)families/[^/]+/index(/|$)", re.I), re.compile(r"(^|/)events\.jsonl$", re.I),
             re.compile(r"(^|/)report(/|$)", re.I), re.compile(r"(^|/)research\.yaml$", re.I))
# PowerShell's cmdlets and their aliases, and an interpreter given its code inline (T142)
SHELL_WRITE = re.compile(r"(>>?|\btee\b|\bsed\s+-i|\bcp\b|\bmv\b|\brm\b|\btouch\b|\bdd\b|Set-Content|Out-File|"
                         r"Add-Content|Remove-Item|Copy-Item|Move-Item|New-Item|Rename-Item|Clear-Content|"
                         r"Tee-Object|Set-Item|\b(cpi|mi|ni|ren|rni|copy|move|del|erase|sc|ac|clc)\b)", re.I)
INLINE_CODE = re.compile(r"\b(python[0-9.]*|py|node|nodejs|deno|bun|perl|ruby|php|pwsh|powershell)(\.exe)?\b"
                         r"[^\n;|&]*?\s(-[a-z]*[ce]\b|-r\b|-Command\b|-EncodedCommand\b|-p\b|-(\s|$)|eval\b)", re.I)
PATH_TOKEN = re.compile(r"[^\s;|&<>'\"`()=,]+")
ENGINE_WRITES = re.compile(r"(run_probandia\.py|\bprobandia\b|-m\s+probandia)[^\n;|&]*?\s"
                           r"(apply|event\s+append|render|export)\b")
GIT_WRITES = re.compile(r"\bgit\b[^\n;|&]*?\s(commit|push)\b")
SCRAPERS = re.compile(r"jina|firecrawl|bright_?data|scrapegraph|tavily[_-]?extract|tavily.*__.*extract", re.I)
URL = re.compile(r"https?://[^\s\"'<>]+")
LIBRARY_SCRIPT = re.compile(r"library[/\\]connectors[/\\]([A-Za-z0-9_.-]+\.py)")
BROWSER_UA = re.compile(r"Mozilla/\d|fake_useragent|cloudscraper|impersonate\s*=", re.I)
SCRIPT_FILE = re.compile(r"\.(py|sh|bash|ps1|js|mjs|cjs|ts)$", re.I)
FAMILY_IMAGE = re.compile(r"(^|/)families/([^/]+)/(.+/)?([^/]+\.(jpe?g|png|webp|gif|tiff?))$", re.I)
IMAGE_NAME = re.compile(r"[^\s/\\|()]+\.(?:jpe?g|png|webp|gif|tiff?)\b", re.I)
MAIN_ROLES = {"", "session", "orchestrator"}   # Claude Code gives no agent_type to the main agent
NEW_TEXT = ("content", "file_text", "CodeContent", "new_string", "new_str", "ReplacementContent")
SESSION_CAPPED = ("claude-code",)


class Call:
    """One tool call, whatever the harness's payload looks like."""

    def __init__(self, payload, environ):
        call = payload.get("toolCall") or {}
        # Grok Build sends toolName and toolInput (camelCase: its hooks' contract, docs of 12 Oct. 2026); its
        # docs name no agent field, agentType is read in case it gives one
        self.tool = str(payload.get("tool_name") or payload.get("toolName") or call.get("name") or payload.get("tool")
                        or "")
        self.input = (payload.get("tool_input") or payload.get("toolInput") or call.get("args") or payload.get("args")
                      or {})
        if not isinstance(self.input, dict):
            self.input = {"value": self.input}
        self.command = str(self.input.get("command") or payload.get("command") or "")
        if self.command and not self.tool:
            self.tool = "Shell"
        agent = str(payload.get("agent_type") or payload.get("agentType") or environ.get("PROBANDIA_AGENT") or "")
        self.agent = re.sub(r"^probandia-", "", agent.split(":")[-1].strip().lower())  # OpenCode names
        self.cwd = payload.get("cwd") or os.getcwd()

    @property
    def name(self):
        return self.tool.split("__")[-1].lower() if self.tool.startswith("mcp__") else self.tool.lower()

    def is_write(self):
        return self.name in WRITE_TOOLS

    def is_shell(self):
        return self.name in SHELL_TOOLS or bool(self.command)

    def paths(self):
        """The files a write tool would write."""
        out = [self.input.get(k) for k in ("file_path", "path", "notebook_path", "filePath", "TargetFile",
                                           "target_file", "AbsolutePath") if isinstance(self.input.get(k), str)]
        patch = self.input.get("input") or self.input.get("patch") or ""
        if isinstance(patch, str):
            out += re.findall(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch, re.M)
        return [p for p in out if p]

    def is_read(self):
        return self.name in READ_TOOLS

    def read_paths(self):
        """The files a read tool, or a shell command that prints files, would read."""
        if self.is_read():
            return self.paths()
        if self.is_shell() and SHELL_READ.search(self.command):
            return [tok.strip("'\"") for tok in re.split(r"[\s;|&<>]+", self.command)
                    if "/" in tok.replace("\\", "/") or tok.endswith((".yaml", ".jsonl", ".md", ".html", ".json"))]
        return []

    def text(self):
        return json.dumps(self.input, ensure_ascii=False)


def _norm(path, cwd):
    path = str(path).replace("\\", "/")
    if not os.path.isabs(path) and not re.match(r"^[A-Za-z]:/", path):
        path = os.path.join(cwd, path).replace("\\", "/")
    return os.path.normpath(path).replace("\\", "/")


def _in_project(path, cwd, project=None):
    """``path`` absolute, "/"-separated and ``..`` resolved, then relative to the project when
    it lies inside: a folder above the project named ``report`` protects nothing."""
    p = _norm(path, cwd)
    if project:
        root = _norm(project, cwd).rstrip("/")
        if p.lower().startswith(root.lower() + "/"):
            return p[len(root) + 1:]
    return p


def _protected(path, cwd=None, project=None):
    p = _in_project(path, cwd or os.getcwd(), project)
    return any(rx.search(p) for rx in PROTECTED)


def _shell_writes_protected(command, cwd=None, project=None):
    if not (SHELL_WRITE.search(command) or INLINE_CODE.search(command)):
        return False
    return any(_protected(tok, cwd, project) for tok in PATH_TOKEN.findall(command))


def g1(call, ctx):
    if call.agent not in FIELD_ROLES:
        return None
    if call.is_write():
        for p in call.paths():
            if _protected(p, call.cwd, ctx.get("project")):
                return f"a {call.agent} may not write {p}: field agents write proposals in work/"
    if call.is_shell() and _shell_writes_protected(call.command, call.cwd, ctx.get("project")):
        return f"a {call.agent} may not change the indexes, the events, the report or research.yaml"
    return None


def g2(call, ctx):
    if call.agent not in FIELD_ROLES:
        return None
    if call.is_shell() and (ENGINE_WRITES.search(call.command) or GIT_WRITES.search(call.command)):
        return f"a {call.agent} may not apply, append events, render, export or commit: the orchestrator does"
    if call.tool.startswith("mcp__") and "probandia" in call.tool.lower() and \
            call.name in ("apply", "event", "event_append", "render", "export"):
        return f"a {call.agent} may not call {call.name}"
    return None


class Notice(str):
    """What a rule says without refusing: the call runs, and the agent is told."""


def catalogue_hosts(project):
    """(every host of the archive catalogues, those marked ``third_party: forbidden``)."""
    from probandia.archives.finder import load_catalogue

    listed, forbidden = set(), set()
    for entry in load_catalogue(project).values():
        access = entry.get("access") or {}
        hosts = {h.lower() for h in access.get("hosts") or []}
        listed |= hosts
        if access.get("third_party") == "forbidden":
            forbidden |= hosts
    return listed, forbidden


def _among(host, hosts):
    return any(host == h or host.endswith("." + h) for h in hosts)


def g3(call, ctx):
    """Refused on a catalogue host that forbids third-party readers; only a notice on a
    host that merely looks like an archive portal (token-economy A8): the expression may err."""
    if not (call.tool.startswith("mcp__") and SCRAPERS.search(call.tool)):
        return None
    from probandia.reading.ladder import is_portal

    listed, forbidden = catalogue_hosts(ctx["project"])
    notice = None
    for url in URL.findall(call.text()):
        host = (urlparse(url).hostname or "").lower()
        if _among(host, forbidden):
            return f"{host} forbids third-party readers: read it with the engine (read) or the browser"
        if notice is None and is_portal(host, ()) and not _among(host, listed):
            notice = Notice(f"{host} looks like an archive portal no catalogue lists: read it with the engine "
                            "(read) or the browser rather than a third-party reader")
    return notice


def g4(call, ctx):
    if ctx["environ"].get("PROBANDIA_WORKER") != "1" or ctx.get("research") is None:
        return None
    work = _norm(ctx["research"].work, call.cwd)
    targets = list(call.paths()) if call.is_write() else []
    if call.is_shell() and SHELL_WRITE.search(call.command):
        targets += [t for t in re.findall(r">>?\s*(\S+)", call.command)]
    for t in targets:
        if not (_norm(t, call.cwd) + "/").startswith(work + "/"):
            return f"an unattended run writes only in {ctx['research'].work}"
    return None


def g5(call, ctx):
    if not call.is_shell():
        return None
    m = LIBRARY_SCRIPT.search(call.command)
    if not m or ctx.get("research") is None or not ctx.get("open_pass"):
        return None
    from probandia.util import yamlio

    project = ctx["project"]
    manifest = os.path.join(project, "library", "manifest.yaml")
    scripts = (yamlio.load(manifest) or {}).get("scripts") or [] if os.path.isfile(manifest) else []
    script = next((s for s in scripts if os.path.basename(s.get("path") or "") == m.group(1)), None)
    if script is None or script.get("status") != "draft":
        return None
    approved = os.path.join(project, ".probandia", "approved-scripts.json")
    try:
        with open(approved, encoding="utf-8") as fh:
            ok = {(a.get("id"), a.get("sha256")) for a in json.load(fh)}
    except (OSError, ValueError, AttributeError):
        ok = set()
    if (script["id"], script.get("sha256")) in ok:
        return None
    return f"the learned script {script['id']} is a draft: ask the user first (library run --approve)"


def w3(call, ctx):
    # an MCP server's search is a provider call, paid from its quota, not from the native budget
    if call.tool.startswith("mcp__") or call.name not in WEB_SEARCH_TOOLS or ctx.get("research") is None \
            or not ctx.get("open_pass"):
        return None
    from probandia.budget import native_budget

    b = native_budget(ctx["project"], ctx["research"], ctx["config"], ctx["environ"], ctx["harness"])
    if b["left"] <= 0:
        return (f"the native search budget is used up ({b['used']}/{b['per_pass']} this pass): "
                "continue with the engine's search command")
    return None


# Web services of search or reading outside the catalogue, known by their server's name (G-15)
WEB_SERVICES = re.compile(SCRAPERS.pattern + r"|perplexity|kagi|searx|duckduckgo|serp|zenrows|scraperapi|"
                          r"scrapingbee|oxylabs|apify|you_?com", re.I)
BROWSER_SERVER = re.compile(r"chrome|browser|playwright|puppeteer", re.I)
QUERY_KEYS = ("query", "q", "search_query", "objective")
URL_KEYS = ("url", "urls", "website_url", "start_url", "website")
ASK_KEYS = ("prompt", "user_prompt", "instructions", "question", "query", "objective")


def _quoted(text):
    return " ".join(str(text or "").replace('"', "'").split())[:160]


def _first(tool_input, keys):
    for k in keys:
        v = tool_input.get(k)
        if isinstance(v, list):
            v = next((x for x in v if isinstance(x, str) and x.strip()), None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def engine_command(provider, operation, tool_input, crawl_max=20):
    """The engine's command that makes what an MCP call would have made (T54)."""
    if operation == "search" or (operation is None and not _first(tool_input, URL_KEYS)):
        engine = f" --engine {provider}" if provider else ""
        return f'search "{_quoted(_first(tool_input, QUERY_KEYS)) or "<query>"}"{engine}'
    url = _first(tool_input, URL_KEYS) or "<url>"
    ask = _quoted(_first(tool_input, ASK_KEYS))
    if operation == "map":
        return f"read {url} --map"
    if operation == "crawl":
        limit = next((v for v in (tool_input.get(k) for k in ("limit", "max_pages", "maxPages", "max_breadth"))
                      if isinstance(v, int) and not isinstance(v, bool) and v > 0), crawl_max)
        return f"read {url} --crawl {min(limit, crawl_max)}" + (f' --question "{ask}"' if ask else "")
    if operation == "extract":
        return f'read {url} --extract "{ask or "<instruction>"}"'
    return f'read {url} --question "{ask}"' if ask else f"read {url}"


def g15(call, ctx):
    """T54: during an open pass, an MCP tool of a search or reading provider (attributed by ``mcp_tool``,
    T49, or a web service known by name) is refused, with the engine's command that does the same: the
    engine counts the quota before the call (PRD Q-6), keeps its cache and answers short. Claude in Chrome,
    Probandia's own server and the servers that do not touch the web pass; outside a pass, nothing is refused
    (the log hook counts the call)."""
    if not call.tool.startswith("mcp__") or call.tool.count("__") < 2 or not ctx.get("open_pass") \
            or ctx.get("research") is None or "probandia" in call.tool.lower():
        return None
    server = call.tool.split("__")[1]
    if BROWSER_SERVER.search(server):
        return None
    from probandia.providers import catalogue

    provider, operation = catalogue.mcp_tool(call.tool)
    if provider is None and not WEB_SERVICES.search(call.tool):
        return None   # Slack, Linear, a file system: not the web
    if provider is not None and operation is None:
        return None   # a job's status, a balance: nothing to count
    try:
        crawl_max = int(ctx["config"].get("read.crawl_max_pages"))
    except (KeyError, TypeError, ValueError):
        crawl_max = 20
    command = engine_command(provider, operation, call.input, crawl_max)
    who = provider or server
    return (f"during a pass, {who} goes through the engine, which counts its free quota before the call, keeps "
            f"its cache and answers short: {command}")


REPEATS = os.path.join(".probandia", "guard-repeats.json")


def _once(project, name, key):
    """True the first time ``key`` is seen in the memory file ``name`` (G-7's way): refuse then. Without a
    memory of the refusal, never refuse."""
    seen = os.path.join(project, name)
    try:
        with open(seen, encoding="utf-8") as fh:
            warned = set(json.load(fh))
    except (OSError, ValueError, TypeError):
        warned = set()
    if key in warned:
        return False
    warned.add(key)
    try:
        os.makedirs(os.path.dirname(seen), exist_ok=True)
        with open(seen, "w", encoding="utf-8") as fh:
            json.dump(sorted(warned), fh)
    except OSError:
        return False
    return True


def g16(call, ctx):
    """T55: a native web search already run for the family within ``cache.days`` (the same normalised
    query, the same domains), whatever the pass: the log hook kept its URLs. Refused once, then allowed."""
    if call.tool.startswith("mcp__") or call.name not in WEB_SEARCH_TOOLS or ctx.get("research") is None:
        return None
    query = str(call.input.get("query") or call.input.get("q") or "")
    if not query.strip():
        return None
    from probandia.providers import searchlog
    from probandia.reading.cache import Cache

    research = ctx["research"]
    key = searchlog.native_key(ctx["harness"], research.family, query, call.input)
    found = Cache(ctx["project"], research.work).live(searchlog.native_cache(ctx["harness"]), key)
    if found is None or not _once(ctx["project"], REPEATS, key):
        return None
    Cache(ctx["project"], research.work).served(searchlog.native_cache(ctx["harness"]), found[0])   # T64
    kept, path = found[0]["payload"], found[1]
    return (f"this web search was already run for the family on {str(kept.get('ts') or '')[:10]} (pass "
            f"{kept.get('pass')}, {kept.get('results')} results); its URLs are in {path}: use them, or another "
            "variant; run it again only if you must (allowed next time)")


FETCH_TOOLS = {"webfetch", "web_fetch", "fetch_url", "url_fetch"}


def _read_command(url, prompt):
    prompt = " ".join(str(prompt or "").replace('"', "'").split())[:160]
    return f'read {url} --question "{prompt}"' if prompt else f"read {url}"


def g17(call, ctx):
    """T57: a page goes through ``read`` first, which tries its cache, an archive's connector and polite HTTP
    (``robots.txt``, each host's rate) before any quota, and says when a page was not consulted. A
    ``WebFetch`` of an archive of the catalogue is refused, every time: its rate (Gallica's 5 a minute) is
    the engine's to keep; one of a page ``read`` keeps is refused once, with that file; any other gets a
    notice, once per URL. T66: a page ``read`` could not read lately is let through, with a notice once
    that says why; on a host that forbids third parties it is refused, the user's browser named."""
    if call.tool.startswith("mcp__") or call.name not in FETCH_TOOLS:
        return None
    url = str(call.input.get("url") or "").strip()
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    command = _read_command(url, call.input.get("prompt"))
    listed, forbidden = catalogue_hosts(ctx["project"])
    from probandia.reading.cache import failure_of

    failed = failure_of(ctx["project"], url)
    if failed is not None:   # T66: read could not read it; sending the fetch back to read would loop
        import time

        why = f"{failed.get('status')}, {time.strftime('%Y-%m-%d %H:%M', time.localtime(failed.get('at', 0)))}"
        if _among(host, forbidden):
            return (f"read could not read this page ({why}) and {host} forbids third parties: ask for the "
                    f"user's browser: read {url} --interactive")
        if _once(ctx["project"], REPEATS, "fetch-failed:" + url.split("#")[0]):
            return Notice(f"read could not read this page ({why}): fetched directly instead")
        return None
    if _among(host, listed):
        return f"{host} is an archive of the catalogue: read it with the engine, which keeps its rate: {command}"
    from probandia.reading.cache import Cache, page_read

    research = ctx.get("research")
    found = page_read(Cache(ctx["project"], research.work if research else None), url.split("#")[0])
    if found is not None:
        if _once(ctx["project"], REPEATS, "fetch-read:" + url):
            return (f"read has this page already, for free: {command}, or its text in {found[1]} "
                    "(payload.text); allowed next time")
        return None
    if _once(ctx["project"], REPEATS, "fetch:" + url):
        return Notice(f"read the page with the engine first, free and polite, which says when it was not "
                      f"consulted: {command}")
    return None


def g6(call, ctx):
    """Raw reads of what the engine summarises (optimize 2.10). The session agent and the
    orchestrator are held to the family index in an open pass, in Claude Code (T257): in
    t82-resume they read it by ``cat`` in 2 second passes of 3, despite the summary of ``resume``."""
    if call.agent in FIELD_ROLES:
        protected = READ_PROTECTED
    elif call.agent in MAIN_ROLES and ctx["harness"] in SESSION_CAPPED and ctx.get("research") is not None \
            and ctx.get("open_pass"):
        protected = (READ_PROTECTED[0][0], "known <research> or status"),
    else:
        return None
    for path in call.read_paths():
        p = _in_project(path, call.cwd, ctx.get("project"))   # "cat index/x.yaml" from the family folder too
        for rx, command in protected:
            if rx.search(p):
                return (f"a {call.agent or 'session agent'} does not read {p} raw: run {command}, which gives the same in a few "
                        "lines")
    return None


def g7(call, ctx):
    """A proposal propose has just stored and summarised: reading it again costs
    tokens for nothing (PRD K-8). Refused once per file, then allowed."""
    for path in call.read_paths():
        p = _norm(path, call.cwd)
        m = STORED_PROPOSAL.search(p)
        if not m or not os.path.isfile(p) or os.path.exists(p[: -len(".yaml")] + ".result"):
            continue
        import time

        if time.time() - os.path.getmtime(p) > FRESH_SECONDS:
            continue
        if not _once(ctx["project"], os.path.join(".probandia", "guard-reread.json"), m.group(2)):
            continue
        return (f"propose has just stored {m.group(2)} and printed its summary (facts, verdict, reasons): "
                "use that summary; read the file again only if you must change it")
    return None


def _skill_or_agent_folder(path):
    from probandia.learning import GUARDED

    p = "/" + str(path).replace("\\", "/").lstrip("/")
    return any(f"/{folder}/" in p for folder in GUARDED)


def g8(call, ctx):
    """No agent writes a skill or an agent where a harness loads it (optimize 5.1.8)."""
    targets = list(call.paths()) if call.is_write() else []
    if call.is_shell() and SHELL_WRITE.search(call.command):
        targets += [tok.strip("'\"") for tok in re.split(r"[\s;|&<>]+", call.command) if tok]
    for t in targets:
        if _skill_or_agent_folder(t):
            return (f"{t} is where a harness loads skills and agents: draft it with library draft, then "
                    "library install after the user approves")
    return None


BROWSER_TYPING = {"form_input", "browser_type", "browser_fill_form", "fill_form", "fill", "type", "type_text",
                  "input_text", "browser_input"}


def g9(call, ctx):
    """While the user is asked to sign in, no browser tool types into a page:
    never a username, a password, nor anything that would get past the screen."""
    if not call.tool.startswith("mcp__"):
        return None
    typing = call.name in BROWSER_TYPING or (call.name == "computer" and str(call.input.get("action", "")).lower()
                                             in ("type", "key", "left_click_drag"))
    if not typing:
        return None
    from probandia import logins

    waiting = logins.pending(ctx["project"])
    if waiting:
        return (f"{', '.join(waiting)} waits for the user to sign in: never type in the page; ask, wait for "
                "their answer, then read with --login connected")
    return None


MEMORY_FILES = ("agents.md", "claude.md")


def _memory_file(path, cwd):
    return os.path.basename(str(path).replace("\\", "/")).lower() in MEMORY_FILES


def _touches_section(call, path, cwd):
    """True when a write tool's call would change the managed section of ``path``."""
    from probandia import memory

    full = _norm(path, cwd)
    current = memory.read(full)
    section = memory.section_of(current)
    edits = call.input.get("edits") if isinstance(call.input.get("edits"), list) else []
    pieces = [call.input] + [e for e in edits if isinstance(e, dict)]
    content = call.input.get("content", call.input.get("file_text", call.input.get("CodeContent")))
    if isinstance(content, str):   # a whole new file
        return memory.section_of(content) != section and (section is not None or memory.BEGIN in content)
    for piece in pieces:
        old = str(piece.get("old_string") or piece.get("old_str") or piece.get("TargetContent") or "")
        new = str(piece.get("new_string") or piece.get("new_str") or piece.get("ReplacementContent") or "")
        if memory.BEGIN in new or memory.END in new or memory.BEGIN in old or memory.END in old:
            return True
        if section and old and old in current:
            start = current.find(old)
            s = current.find(memory.BEGIN)
            e = current.find(memory.END, s) + len(memory.END)
            if start < e and start + len(old) > s:
                return True
    patch = call.input.get("input") or call.input.get("patch") or ""
    if isinstance(patch, str) and patch and section:
        changed = [ln[1:].strip() for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
        body = [ln.strip() for ln in section.splitlines()]
        return any(c and (c in body or memory.BEGIN in c or memory.END in c) for c in changed)
    return False


def g10(call, ctx):
    """The managed section of AGENTS.md changes only through ``memory`` (optimize 5.2.7)."""
    if call.is_write():
        for p in call.paths():
            if _memory_file(p, call.cwd) and _touches_section(call, p, call.cwd):
                return (f"the section between the probandia markers of {os.path.basename(p)} is the engine's: "
                        "memory add or memory remove, after the user approves; edit only outside the markers")
    if call.is_shell() and SHELL_WRITE.search(call.command) and not ENGINE_CALL.search(call.command):
        from probandia import memory

        for tok in re.split(r"[\s;|&<>]+", call.command):
            tok = tok.strip("'\"")
            if tok and _memory_file(tok, call.cwd) and memory.section_of(memory.read(_norm(tok, call.cwd))):
                return (f"{tok} holds the engine's managed section: memory add or memory remove, after the "
                        "user approves; edit the rest of the file with an edit tool")
    return None


# The engine's command right after its name and global options: close, or a change to the questions.
QUESTION_WRITES = re.compile(r"(run_probandia\.py[\"']?|\bprobandia\b|-m\s+probandia)(\s+-[^\s]+(\s+[^-\s]\S*)?)*"
                             r"\s+(close|question\s+(add|edit|answer|unresolved|reopen))\b")


def g11(call, ctx):
    """A research's questions, and its closing, are the orchestrator's (GPS1-T5)."""
    if call.agent not in FIELD_ROLES:
        return None
    if call.is_shell() and QUESTION_WRITES.search(call.command):   # the MCP tool question only lists
        return (f"a {call.agent} may not close a research or settle its questions: the orchestrator does; "
                "question list reads them")
    return None


def _new_text(call):
    """What a write tool's call adds to a file, never the text it replaces."""
    edits = call.input.get("edits") if isinstance(call.input.get("edits"), list) else []
    new = [call.input.get(k) for k in NEW_TEXT] + [e.get("new_string") for e in edits if isinstance(e, dict)]
    patch = call.input.get("input") or call.input.get("patch") or ""
    new += [ln[1:] for ln in str(patch).splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    return "\n".join(str(t) for t in new if t)


def _contents(paths, cwd):
    out = []
    for p in paths:
        try:
            with open(_norm(p, cwd), encoding="utf-8", errors="replace") as fh:
                out.append(fh.read())
        except OSError:
            pass
    return "\n".join(out)


def g12(call, ctx):
    """Never pose as a browser toward an archive portal (token-economy A1): a cookie a
    plain redirect sets may be replayed under the engine's own User-Agent, nothing more."""
    if call.is_write():
        files = [p for p in call.paths() if SCRIPT_FILE.search(p)]
        if not files:
            return None
        new = _new_text(call)
        seen = new + "\n" + _contents(files, call.cwd)   # an edit may add the identity, the address being elsewhere
    elif call.is_shell():
        files = [t for t in (tok.strip("'\"") for tok in re.split(r"[\s;|&<>]+", call.command)) if SCRIPT_FILE.search(t)]
        new = seen = call.command + "\n" + _contents(files, call.cwd)   # a script it runs speaks for it
    else:
        return None
    if not BROWSER_UA.search(new):
        return None
    from probandia.paths import data_root
    from probandia.reading.ladder import archive_hosts, is_portal

    hosts = archive_hosts(ctx["project"], data_root())
    for url in URL.findall(seen):
        host = urlparse(url).hostname or ""
        if is_portal(host, hosts):
            return (f"{host} is an archive portal: never pose as a browser there; keep the engine's User-Agent "
                    "(its http client), and read a page that challenges it with the browser")
    return None


VIEWS_READ = os.path.join(".probandia", "guard-views.json")


def transcribed(project, family):
    """Names of the images the family's transcriptions are made from (their ``| Image |`` row)."""
    folder = os.path.join(project, "families", family, "evidence", "transcriptions")
    try:
        files = [f for f in os.listdir(folder) if f.endswith(".md")]
    except OSError:
        return set()
    names = set()
    for name in files:
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                head = fh.read(2048)
        except OSError:
            continue
        for line in head.splitlines():
            if line.startswith("| Image |"):
                names.update(n.lower() for n in IMAGE_NAME.findall(line))
    return names


def g13(call, ctx):
    """A register's views are a reader's (token-economy A7): an image the session agent or
    the orchestrator reads stays in its context until the pass ends. Claude Code only, which
    names a subagent in ``agent_type``. Refused at the first image of the pass, so that the
    reader comes to mind; then allowed, with a notice that counts them. A view a transcription
    is made from opens freely: reading it checks a doubt the reader marked (refused so at the
    bench, 11 Oct. 2026, and given up once)."""
    if ctx["harness"] not in SESSION_CAPPED or call.agent not in MAIN_ROLES or not call.is_read() \
            or ctx.get("research") is None or not ctx.get("open_pass"):
        return None
    images = [m for m in (FAMILY_IMAGE.search(str(p).replace("\\", "/")) for p in call.paths()) if m]
    if not images:
        return None
    known = {}
    if all(m.group(4).lower() in known.setdefault(m.group(2), transcribed(ctx["project"], m.group(2)))
           for m in images):
        return None
    seen = os.path.join(ctx["project"], VIEWS_READ)
    key = f"{ctx['research'].id}#{ctx.get('pass')}"
    try:
        with open(seen, encoding="utf-8") as fh:
            counts = dict(json.load(fh))
    except (OSError, ValueError, TypeError):
        counts = {}
    before = counts.get(key, 0) if isinstance(counts.get(key), int) else 0
    counts[key] = before + 1
    try:
        os.makedirs(os.path.dirname(seen), exist_ok=True)
        with open(seen, "w", encoding="utf-8") as fh:
            json.dump(counts, fh)
    except OSError:
        return None   # without a memory of the refusal, never refuse
    if before == 0:
        return ("a register's views go to a reader subagent, one per register or act (its brief: "
                "skills/research/reader.md): it finds the act, transcribes it and returns its lines, and the views "
                "stay out of your context; the view a transcription names opens freely, to check its doubts; "
                "read this one again if you need it")
    return Notice(f"{before} image(s) read by you this pass, each kept in your context until it ends: hand a "
                  "register's views to a reader subagent")


WHOLE_VIEW = re.compile(r"(^|/)([a-z][a-z0-9]*-\d+-\d{4}\.(jpe?g|png))$", re.I)   # ad50-607643-0090.jpg


def _pillow():
    from importlib.util import find_spec

    return find_spec("PIL") is not None


def g14(call, ctx):
    """A reader reading a whole view keeps 3,400 to 4,200 tokens in its context (Claude Code shrinks it to
    2,000 px): 46 % of the readers' images at the bench of J7 (12 Oct. 2026), a register's view 1 read to
    learn the register, views paged one by one. A sheet shows a view for 1,000 at most, a crop reads the act.
    Without Pillow neither can be made: the view is read."""
    if call.agent != "reader" or not call.is_read():
        return None
    from probandia import images

    for path in call.paths():
        m = WHOLE_VIEW.search(str(path).replace("\\", "/"))
        if not m:
            continue
        full = path if os.path.isabs(path) else os.path.join(call.cwd, path)
        size = images.size_of(full)
        if not size or images.tokens_est(*size) <= images.REGION_MAX_TOKENS or not _pillow():
            continue
        return (f"{m.group(2)} is a whole view, {images.tokens_est(*size)} tokens: never read whole; find the act on "
                f"a sheet, then on the view small (ad50.view \"size\": 900; on disk: image sheet <view> --band 1); "
                f"read the act alone, cut at full size (ad50.view, the same \"size\" and \"region\": \"x,y,w,h\" as "
                f"seen on it; on disk: image crop <view> --region x,y,w,h)")
    return None


ENGINE_CALL = re.compile(r"(run_probandia\.py|\bprobandia\b|-m\s+probandia)[^\n;|&]*?\smemory\b")

def _workshop_people(project):
    """The workshop's personnes.yaml of a linked project, "/"-separated, or None."""
    link = os.path.join(project, "workshop.yaml") if project else None
    if not link or not os.path.isfile(link):
        return None
    from probandia.util import yamlio

    try:
        root = (yamlio.load(link) or {}).get("root") or "."
    except Exception:  # noqa: BLE001 — an unreadable link protects the usual place
        root = "."
    return _norm(os.path.join(project, root, "commun", "personnes.yaml"), project).lower()


def g18(call, ctx):
    """In a project linked to its workshop, only ``workshop push`` writes personnes.yaml (WS4-T5)."""
    shell = call.is_shell() and (SHELL_WRITE.search(call.command) or INLINE_CODE.search(call.command))
    if not (call.is_write() or shell):
        return None
    people = _workshop_people(ctx.get("project"))
    if people is None:
        return None
    targets = list(call.paths()) if call.is_write() else [t.strip("'\"") for t in PATH_TOKEN.findall(call.command)]
    for t in targets:
        if _norm(t, call.cwd).lower() == people:
            return ("the workshop's personnes.yaml is written by workshop push only, under the workshop's rules: "
                    "apply the facts in Probandia, then workshop status and workshop push")
    return None


RULES = (("G-1", g1), ("G-2", g2), ("G-3", g3), ("G-4", g4), ("G-5", g5), ("G-6", g6), ("G-7", g7),
         ("G-8", g8), ("G-9", g9), ("G-10", g10), ("G-11", g11), ("G-12", g12), ("G-13", g13), ("G-14", g14),
         ("G-15", g15), ("G-16", g16), ("G-17", g17), ("G-18", g18), ("W-3", w3))


def check(payload, environ, harness):
    """(rule, reason) of the first rule refused, else of the first notice (a ``Notice``
    reason), or None. Silent outside a project."""
    from probandia import events
    from probandia.config import load
    from probandia.errors import ProbandiaError
    from probandia.lifecycle import pass_state
    from probandia.project import find_project
    from probandia.research import find_research

    call = Call(payload, environ)
    try:
        project = find_project(None, environ, call.cwd)
    except ProbandiaError:
        return None
    ctx = {"project": project, "environ": environ, "harness": harness, "research": None, "open_pass": False,
           "pass": 0}
    try:
        ctx["research"] = find_research(project, fallback=True)
        ctx["pass"], ctx["open_pass"] = pass_state(events.read(ctx["research"].events_path))
    except ProbandiaError:
        pass
    ctx["config"] = load(project, environ, strict=False)
    notice = None
    for rule, fn in RULES:
        reason = fn(call, ctx)
        if isinstance(reason, Notice):
            notice = notice or (rule, reason)
        elif reason:
            return rule, reason
    return notice


PLUGIN_AGENT = re.compile(r"^probandia:([a-z]+)$")
AGENTS_LOG = os.path.join(".probandia", "logs", "agents.jsonl")


def agent_settings(payload, environ, harness):
    """agent-models R3: the input of a launch of a Probandia agent, with the model and the effort the
    user chose for its role (``roles.<role>.*``, or the research's own for the orchestrator), else None.
    Claude Code only, whose hooks may rewrite a call's input (``updatedInput``: the whole input, every
    field copied; checked on 12 Oct. 2026, R1, without ``permissionDecision``). A value left to the agent's
    header is not touched; a model the Agent tool does not take as an alias is not passed. In Grok Build,
    the launch goes to the project's copy of the agent instead (``grok_copy``, R6)."""
    if harness == "grok":
        return grok_copy(payload, environ)
    if harness not in SESSION_CAPPED:
        return None
    call = Call(payload, environ)
    m = PLUGIN_AGENT.match(str(call.input.get("subagent_type") or "")) if call.name in ("agent", "task") else None
    from probandia import roles

    if not m or m.group(1) not in roles.ROLES:
        return None
    from probandia.config import load
    from probandia.errors import ProbandiaError
    from probandia.project import find_project
    from probandia.research import find_research

    try:
        project = find_project(None, environ, call.cwd)
    except ProbandiaError:
        return None
    role, run = m.group(1), None
    if role == "orchestrator":
        try:
            run = (find_research(project, fallback=True).meta() or {}).get("run")
        except ProbandiaError:
            run = None
    config = load(project, environ, strict=False)
    entry = roles.resolve(config, run)[role]
    wanted = roles.chosen(entry)
    own = roles.harness_models(config, role).get("claude-code")   # R6: claude-code:<model> first
    if own:
        wanted["model"], entry["model_from"] = own, config.origin(f"roles.{role}.models").layer
    if wanted.get("model") and wanted["model"] not in roles.CLAUDE_CODE_MODELS:
        del wanted["model"]
    updated = dict(call.input, **wanted)
    if updated == call.input:
        return None
    try:   # what each launch ran with, for whoever asks why a role cost what it did
        path = os.path.join(project, AGENTS_LOG)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from probandia.util.fs import iso, utc_now

        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": iso(utc_now()), "role": role, **wanted,
                                 "from": {f: entry[f"{f}_from"] for f in wanted}}) + "\n")
    except OSError:
        pass
    return updated


GROK_LAUNCH = ("spawn_subagent", "task", "agent")


def grok_copy(payload, environ):
    """agent-models R6: in Grok Build, a plugin agent is ``probandia:<role>`` and keeps the plugin's header;
    the project's copy ``probandia-<role>`` (``.grok/agents/``, written by the session hook with the model and
    the effort chosen for the role, ``install/copies.py``) takes them. The launch goes to the copy when
    Probandia wrote one: the input with that ``subagent_type`` (``spawn_subagent`` takes no effort, and a
    model only when Grok shows it; Grok's built-in hooks docs, 1.0.50)."""
    call = Call(payload, environ)
    m = PLUGIN_AGENT.match(str(call.input.get("subagent_type") or "")) if call.name in GROK_LAUNCH else None
    if not m:
        return None
    from probandia.errors import ProbandiaError
    from probandia.install import copies
    from probandia.project import find_project

    try:
        project = find_project(None, environ, call.cwd)
    except ProbandiaError:
        return None
    path = copies.path_of(project, "grok", m.group(1))
    rel = os.path.relpath(path, project).replace(os.sep, "/")
    if rel not in copies.written(project, "grok") or not os.path.isfile(path):
        return None
    return dict(call.input, subagent_type=f"probandia-{m.group(1)}")


def updated(harness, tool_input, base=None):
    """The answer that rewrites a call's input, kept with a notice when there is one (``base``)."""
    out = dict(base or {})
    out.setdefault("hookSpecificOutput", {"hookEventName": "PreToolUse"})["updatedInput"] = tool_input
    return out


def refusal(harness, rule, reason, event="PreToolUse"):
    """The refusal in the harness's own format."""
    text = f"{rule}: {reason}"
    if harness == "cursor":
        return {"permission": "deny", "userMessage": f"Probandia — {text}", "agentMessage": text}
    if harness == "antigravity":
        return {"allowTool": False, "denyReason": text}
    if harness == "opencode":
        return {"permission": "deny", "reason": text}
    if harness == "grok":   # its documented PreToolUse answer; only an explicit deny blocks
        return {"decision": "deny", "reason": text}
    return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def notice(harness, rule, reason):
    """A call allowed with a word for the agent. Claude Code adds ``additionalContext``
    to the agent's context and keeps its own permission flow (no ``permissionDecision``);
    the other harnesses get what an allowed call gets, having no documented way to say it."""
    if harness != "claude-code":
        return allowed(harness)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": f"{rule}: {reason}"}}


def allowed(harness):
    """What an allowed call prints: nothing, except where silence would refuse it."""
    if harness == "antigravity":
        return {"allowTool": True}
    return None
