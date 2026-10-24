"""The MCP server of Probandia, over stdio, with no SDK (SPECS § 12.6).

JSON-RPC 2.0, one message per line. Stateless: every call stands alone, and
``server/discover`` (revision of 28 July 2026) describes the server; the
``initialize`` handshake of earlier revisions (25 November 2025 and before) is
answered too. No sampling.

Each tool runs the engine command of the same name in the same process, so the
server keeps the engine's rules: budgets and free-tier stops, the search log,
the detector and the cache rules. It adds its own checks for what a harness
without hooks would not block: no ``apply``, ``event append``, ``lock`` or
``config set``, ``question`` only lists (GPS1), and no operation aimed at a host whose archive forbids
third-party readers (``third_party: forbidden``), unless the operation belongs
to that archive.

A result is the text of the output contract, at most 4,096 bytes, with
``DETAILS=`` when it is cut; ``FAIL`` and ``STOP`` are ``isError: true``.
"""
import io
import json
import os
import re
import sys
from urllib.parse import urlparse

from probandia import __version__

SUPPORTED_VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LATEST = SUPPORTED_VERSIONS[0]
SERVER_INFO = {"name": "probandia", "version": __version__}
MAX_BYTES = 4096


def _s(desc, **extra):
    return dict({"type": "string", "description": desc}, **extra)


def _i(desc):
    return {"type": "integer", "description": desc}


def _b(desc):
    return {"type": "boolean", "description": desc}


def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TOOLS = {
    "dates": ("Parse a genealogical date (Latin, Republican, Julian, feasts) or compute a birth range from an age.",
              _schema({"text": _s("the date as written"), "julian": _s("a Julian date to convert"),
                       "age": _i("an age, with on"), "on": _s("YYYY-MM-DD, the date the age was given")})),
    "export": ("Export a family: GEDCOM 7 (GEDZIP) or GEDCOM 5.5.1.",
               _schema({"family": _s("family slug"), "format": _s("gedcom7 or gedcom551",
                                                                   enum=["gedcom7", "gedcom551"])}, ["format"])),
    "find_operation": ("Find the archive connector operations that fit a need (code mode): the 5 best, with "
                       "their parameters.", _schema({"need": _s("the need, in words")}, ["need"])),
    "known": ("What the family already knows: facts, negatives, hypotheses and gaps.",
              _schema({"research": _s("research id or prefix"), "names": _s("surnames, comma-separated"),
                       "places": _s("places, comma-separated"), "window": _s("years: 1840-1860")})),
    "library_find": ("Find learned scripts and query recipes for a need: the 5 best.",
                     _schema({"need": _s("the need, in words")}, ["need"])),
    "places": ("Historical place names and their current forms.",
               _schema({"name": _s("the place as written"), "as_of": _i("the year of the record")}, ["name"])),
    "plan": ("Plan the next searches of a research within the free quotas.",
             _schema({"research": _s("research id or prefix"), "question_type": _s("birth, parents, …")})),
    "propose": ("Store a proposal of facts, sources, searches and sections; the orchestrator applies it.",
                _schema({"research": _s("research id or prefix"),
                         "proposal": {"type": "object", "description": "the proposal (SPECS § 5.7)"}},
                        ["research", "proposal"])),
    # read only, like the rest of the server: a harness without hooks would not enforce G-11, so the
    # questions change only through the engine's command line (question add, answer, unresolved…)
    "question": ("The questions of a research, with their status and conclusion (read only).",
                 _schema({"research": _s("research id or prefix")})),
    "quota": ("Free-tier usage of the providers.",
              _schema({"action": _s("show or estimate", enum=["show", "estimate"]), "provider": _s("provider id")})),
    "read": ("Read a page through the reading ladder, with the passages that answer a question.",
             _schema({"url": _s("the page"), "question": _s("what the passages must answer"),
                      "links": _s("only the links whose text or address holds this"),
                      "grep": _s("only the lines that hold this, with one line of context"),
                      "select": _s("only one block: a tag, .class, #id or tag.class")}, ["url"])),
    "render": ("Render the report of a research.", _schema({"research": _s("research id or prefix")})),
    "run_operation": ("Run one archive connector operation (code mode).",
                      _schema({"operation": _s("<archive>.<operation>"),
                               "args": {"type": "object", "description": "its parameters"},
                               "research": _s("research id: the run goes to its search log")}, ["operation"])),
    "search": ("Provider web search, within the free quotas, written to the search log.",
               _schema({"query": _s("the query"), "engine": _s("a provider id, or auto"),
                        "negative": _b("prove an absence"), "exact": _b("exact phrase"), "site": _s("a site"),
                        "filetype": _s("a file type"), "lang": _s("language"), "from": _i("first year"),
                        "to": _i("last year"), "max": _i("results, at most 10"),
                        "depth": _s("advanced: deeper and dearer (Tavily, Exa, Parallel, Linkup)",
                                    enum=["standard", "advanced"])}, ["query"])),
    "tree": ("Write a family's tree: html (offline viewer) or md (Mermaid).",
             _schema({"family": _s("family slug"), "format": _s("html or md", enum=["html", "md"])})),
    "variants": ("Spelling variants of a surname, and of a given name.",
                 _schema({"surname": _s("the surname"), "given": _s("a given name"),
                          "paleo": _b("add the reading confusions")}, ["surname"])),
    "verify": ("Check a research against the proof rules V-1 to V-20.",
               _schema({"research": _s("research id or prefix"), "light": _b("the light rules only")})),
}


def _capabilities():
    return {"tools": {"listChanged": False}, "resources": {"listChanged": False}}


def _code_mode(project, environ):
    if not project:
        return True
    try:
        from probandia.config import load

        return bool(load(project, environ, strict=False).get("mcp.code_mode"))
    except Exception:  # noqa: BLE001
        return True


def _tools(project=None, environ=None):
    """The tools, in alphabetical order, which keeps prompt caches valid. With
    ``mcp.code_mode`` off, each connector operation is a tool of its own as well."""
    out = [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in sorted(TOOLS.items())]
    if not _code_mode(project, environ or os.environ):
        from probandia.archives import connectors

        for archive, module in sorted(connectors(project).items()):
            for op, spec in sorted(module.OPERATIONS.items()):
                props = {k: {"type": "integer" if t is int else "string"} for k, t in spec.params.items()}
                out.append({"name": f"op_{archive}_{op}".replace("-", "_"), "description": spec.doc,
                            "inputSchema": _schema(props, spec.required)})
        out.sort(key=lambda t: t["name"])
    return out


# running a tool


def _project(environ, cwd):
    from probandia.errors import NotInProject
    from probandia.project import find_project

    try:
        return find_project(None, environ, cwd)
    except (NotInProject, OSError):
        return None


def _opt(argv, flag, value):
    if value is not None and value != "" and value is not False:
        argv += [flag] if value is True else [flag, str(value)]


def argv_for(name, a):
    """The engine command line of a tool call."""
    if name == "dates":
        argv = ["dates"] + ([a["text"]] if a.get("text") else [])
        _opt(argv, "--julian", a.get("julian"))
        _opt(argv, "--age", a.get("age"))
        _opt(argv, "--on", a.get("on"))
    elif name == "export":
        argv = ["export", a["format"]]
        _opt(argv, "--family", a.get("family"))
    elif name == "find_operation":
        argv = ["archive", "find", a["need"]]
    elif name == "known":
        argv = ["known"] + ([a["research"]] if a.get("research") else [])
        for k in ("names", "places", "window"):
            _opt(argv, f"--{k}", a.get(k))
    elif name == "library_find":
        argv = ["library", "find", a["need"]]
    elif name == "places":
        argv = ["places", a["name"]]
        _opt(argv, "--as-of", a.get("as_of"))
    elif name == "plan":
        argv = ["plan"] + ([a["research"]] if a.get("research") else [])
        _opt(argv, "--question-type", a.get("question_type"))
    elif name == "question":
        argv = ["question", "list"]
        _opt(argv, "--research", a.get("research"))
    elif name == "quota":
        argv = ["quota", a.get("action") or "show"] + ([a["provider"]] if a.get("provider") else [])
    elif name == "read":
        argv = ["read", a["url"]]
        for key in ("question", "links", "grep", "select"):
            _opt(argv, f"--{key}", a.get(key))
    elif name == "render":
        argv = ["render"] + ([a["research"]] if a.get("research") else [])
    elif name == "run_operation":
        argv = ["archive", "run", a["operation"], "--args", json.dumps(a.get("args") or {}, ensure_ascii=False)]
        _opt(argv, "--research", a.get("research"))
    elif name == "search":
        argv = ["search", a["query"]]
        for k, flag in (("engine", "--engine"), ("negative", "--negative"), ("exact", "--exact"),
                        ("site", "--site"), ("filetype", "--filetype"), ("from", "--from"), ("to", "--to"),
                        ("depth", "--depth")):
            _opt(argv, flag, a.get(k))
        _opt(argv, "--max", min(int(a.get("max") or 10), 10))
        if a.get("lang"):
            argv = ["--lang", a["lang"]] + argv
    elif name == "tree":
        argv = ["tree", "--format", a.get("format") or "html"]
        _opt(argv, "--family", a.get("family"))
    elif name == "variants":
        argv = ["variants", a["surname"]]
        _opt(argv, "--given", a.get("given"))
        _opt(argv, "--paleo", bool(a.get("paleo")))
    elif name == "verify":
        argv = ["verify"] + ([a["research"]] if a.get("research") else [])
        _opt(argv, "--light", bool(a.get("light")))
    else:
        raise KeyError(name)
    return argv


def _forbidden(operation, args, project):
    """The host of an operation's arguments whose archive forbids third-party
    readers, when the operation does not belong to that archive."""
    from probandia.archives.finder import load_catalogue

    archive = (operation or "").split(".")[0]
    owners = {}
    for entry in load_catalogue(project).values():
        access = entry.get("access") or {}
        if access.get("third_party") == "forbidden":
            for h in access.get("hosts") or []:
                owners[h.lower()] = entry["id"]
    for url in re.findall(r"https?://[^\s\"'<>]+", json.dumps(args or {}, ensure_ascii=False)):
        host = (urlparse(url).hostname or "").lower()
        for h, owner in owners.items():
            if (host == h or host.endswith("." + h)) and owner != archive:
                return host, owner
    return None


def _result(text, is_error):
    data = text.encode("utf-8")
    if len(data) > MAX_BYTES:
        text = data[: MAX_BYTES - 120].decode("utf-8", "ignore").rsplit("\n", 1)[0] + \
            "\n- … cut at 4,096 bytes\n"
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


def _spill(text, project):
    """A text over the limit goes to a details file, named in its last line."""
    if len(text.encode("utf-8")) <= MAX_BYTES or not project:
        return text
    from probandia.util.fs import atomic_write_text
    from probandia.util.ids import ulid

    path = os.path.join(project, ".probandia", "details", f"mcp-{ulid()}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, text)
    head = text.encode("utf-8")[: MAX_BYTES - 400].decode("utf-8", "ignore").rsplit("\n", 1)[0]
    head = "\n".join(line for line in head.splitlines() if not line.startswith("DETAILS="))
    return head + f"\n- … the full text is in the details file\nDETAILS={path}\n"


def call_tool(name, args, environ=None, cwd=None):
    """(text, is_error) of one tool call."""
    from probandia import cli

    environ = dict(os.environ if environ is None else environ)
    cwd = cwd or os.getcwd()
    project = _project(environ, cwd)
    args = args or {}
    if name not in TOOLS and not (name or "").startswith("op_"):
        return f"STATUS=FAIL\nREASON=unknown-tool\n- no tool {name}\n", True
    if name.startswith("op_"):
        archive, _sep, op = name[3:].partition("_")
        name, args = "run_operation", {"operation": f"{archive}.{op}", "args": args}
    if name == "run_operation":
        hit = _forbidden(args.get("operation"), args.get("args"), project)
        if hit:
            return (f"STATUS=FAIL\nREASON=third-party-forbidden\nHOST={hit[0]}\nARCHIVE={hit[1]}\n"
                    f"- {hit[1]} forbids third-party readers: use its own connector or the browser\n"), True
    if name == "propose":
        if not project:
            return "STATUS=FAIL\nREASON=no-project\n- not inside a Probandia project\n", True
        from probandia.research import find_research
        from probandia.util import yamlio
        from probandia.util.ids import ulid

        research = find_research(project, args.get("research"))
        doc = dict(args.get("proposal") or {})
        doc.setdefault("id", ulid())
        path = os.path.join(research.work, "proposals", f"incoming-{doc['id']}.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        yamlio.dump(path, doc)
        argv = ["propose", research.id, path]
    else:
        argv = argv_for(name, args)
    agent = environ.get("PROBANDIA_AGENT") or "session"
    harness = environ.get("PROBANDIA_HARNESS") or "cli"
    out = io.StringIO()
    code = cli.main(argv + ["--agent", agent, "--harness", harness], stdout=out, environ=environ, cwd=cwd)
    text = _spill(out.getvalue(), project)
    status = (text.splitlines() or ["STATUS=FAIL"])[0].split("=", 1)[-1]
    return text, code != 0 and status in ("FAIL", "STOP")


# resources


def _resources(project):
    """The settings and each research's digest. T72: no family index (``families/<f>/index/*.yaml``): a
    resource is read whole, past ``MAX_BYTES`` (a ``persons.yaml`` of 4,000 persons is megabytes), the
    guard's G-6 does not see it, and cutting it would hide whoever is further down; the ``known`` tool
    answers in a few lines instead."""
    if not project:
        return []
    out = [{"uri": "probandia://config", "name": "settings", "mimeType": "text/plain",
            "description": "the settings in effect, with their origins"}]
    from probandia.research import all_researches

    for r in all_researches(project):
        out.append({"uri": f"probandia://research/{r.id}/digest", "name": f"digest of {r.id}",
                    "mimeType": "text/plain"})
    return out


def read_resource(uri, environ=None, cwd=None):
    from probandia import cli

    environ = dict(os.environ if environ is None else environ)
    project = _project(environ, cwd or os.getcwd())
    if not project:
        raise LookupError("not inside a Probandia project")
    m = re.match(r"^probandia://(config|research/([^/]+)/digest)$", uri)
    if not m:
        raise LookupError(f"unknown resource {uri}")
    if m.group(1) == "config":
        out = io.StringIO()
        cli.main(["config", "show"], stdout=out, environ=environ, cwd=project)
        return out.getvalue(), "text/plain"
    from probandia import digest
    from probandia.config import load
    from probandia.research import find_research

    r = find_research(project, m.group(2))
    return "\n".join(digest.build(project, r, load(project, environ, strict=False))) + "\n", "text/plain"


# protocol


def handle(message, environ=None, cwd=None):
    """The response to one JSON-RPC message, or None for a notification."""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if msg_id is None:
        return None  # notifications (notifications/initialized…) need no answer
    environ = os.environ if environ is None else environ
    project = _project(environ, cwd or os.getcwd())
    try:
        if method == "initialize":
            asked = params.get("protocolVersion")
            result = {"protocolVersion": asked if asked in SUPPORTED_VERSIONS else LATEST,
                      "capabilities": _capabilities(), "serverInfo": SERVER_INFO}
        elif method == "server/discover":
            result = {"supportedVersions": list(SUPPORTED_VERSIONS), "capabilities": _capabilities(),
                      "serverInfo": SERVER_INFO}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tools(project, environ)}
        elif method == "tools/call":
            text, is_error = call_tool(params.get("name") or "", params.get("arguments") or {}, environ, cwd)
            result = _result(text, is_error)
        elif method == "resources/list":
            result = {"resources": _resources(project)}
        elif method == "resources/read":
            text, mime = read_resource(params.get("uri", ""), environ, cwd)
            result = {"contents": [{"uri": params.get("uri"), "mimeType": mime, "text": text}]}
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
    except LookupError as err:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32002, "message": str(err)}}
    except Exception as err:  # noqa: BLE001 — the server answers; it does not crash
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": f"internal error: {err}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve(stdin=None, stdout=None, environ=None, cwd=None):
    """Answers messages until standard input closes."""
    if stdin is None:
        stdin = sys.stdin
        try:   # MCP's stdio is UTF-8; a Windows pipe would otherwise read cp1252 (T131)
            stdin.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    stdout = stdout or sys.stdout
    state = {"cwd": cwd, "roots": False}

    def send(obj):
        stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        stdout.flush()

    def one(m):
        # T132: the harness starts the server in the plugin's folder; a client that has roots names the project
        if "method" not in m:
            if m.get("id") == ROOTS_ID:
                state["cwd"] = _root_project(m.get("result"), environ) or state["cwd"]
            return None   # an answer to the server's own request
        if m["method"] == "initialize":
            state["roots"] = bool(((m.get("params") or {}).get("capabilities") or {}).get("roots"))
        elif m["method"] in ("notifications/initialized", "notifications/roots/list_changed") and state["roots"]:
            send({"jsonrpc": "2.0", "id": ROOTS_ID, "method": "roots/list"})
        return handle(m, environ, state["cwd"])

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(message, list):
                responses = [r for r in (one(m) for m in message if isinstance(m, dict)) if r]
                response = responses or None
            elif isinstance(message, dict):
                response = one(message)
            else:
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if response is not None:
            send(response)


ROOTS_ID = "probandia-roots"


def _root_project(result, environ):
    """The first of the client's roots (``file://`` URIs, MCP ``roots/list``) inside a project, or None."""
    from urllib.request import url2pathname

    environ = os.environ if environ is None else environ
    for root in (result or {}).get("roots") or []:
        uri = urlparse(str((root or {}).get("uri") or ""))
        if uri.scheme == "file":
            found = _project(environ, url2pathname(uri.path))   # it unquotes
            if found:
                return found
    return None
