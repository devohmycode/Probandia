"""``doctor``: the harness and its capabilities, the keys present (names only),
Python, the optional tools and the age of the catalogue entries.

It never prints a secret value: keys are reported by their variable name.
"""
import datetime
import importlib.util
import os
import shutil
import sys
import tomllib

from probandia.cli.output import Result
from probandia.harness import CAPABILITIES, DEGRADATIONS, degradations, detect
from probandia.i18n import _
from probandia.util.fs import read_text

# Variables that hold secrets. Only their names are ever printed.
SECRET_VARIABLES = (
    "BRAVE_API_KEY", "TAVILY_API_KEY", "LINKUP_API_KEY", "STAAN_API_KEY", "PARALLEL_API_KEY",
    "EXA_API_KEY", "SERPAPI_API_KEY", "MARGINALIA_API_KEY", "SERPER_API_KEY", "SEARCHAPI_API_KEY",
    "OPENWEBNINJA_API_KEY", "FIRECRAWL_API_KEY", "JINA_API_KEY", "SGAI_API_KEY",
    "ZENROWS_API_KEY", "SCRAPERAPI_API_KEY", "APIFY_TOKEN", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
    "EUROPEANA_API_KEY", "GEONAMES_USERNAME", "PROBANDIA_GRAMPS_PASSWORD",
)


# How to install each optional tool, by system: alternatives, each one a command
# or steps joined by " && ". Shown, never run: doctor installs nothing itself.
INSTALL = {
    "playwright": {"any": ["{python} -m pip install playwright && {python} -m playwright install chromium"]},
    "tesseract": {"windows": ["winget install UB-Mannheim.TesseractOCR", "scoop install tesseract"],
                  "linux": ["sudo apt install tesseract-ocr tesseract-ocr-fra"],
                  "darwin": ["brew install tesseract tesseract-lang"]},
    # T119: the engine's own Python, with pip, or a virtual environment made by uv, which has none
    "pillow": {"any": ['{python} -m pip install "Pillow>=12,<13"',
                       'uv pip install --python {python} "Pillow>=12,<13"']},
}


def system_name():
    """``windows``, ``linux`` or ``darwin``."""
    return {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")


def git_bash(environ):
    """The Git Bash that Claude Code would run hooks in under Windows, or None:
    ``CLAUDE_CODE_GIT_BASH_PATH``, else Git's ``bash.exe`` on the PATH (never WSL's, in System32
    or WindowsApps), beside a ``git.exe`` of the PATH, or in Git's install folders."""
    given = environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if given:
        return given if os.path.isfile(given) else None
    candidates = []
    for folder in (environ.get("PATH") or "").split(";"):
        low = folder.lower().replace("/", "\\").rstrip("\\")
        if not folder or low.endswith(("\\system32", "\\windowsapps")):
            continue
        candidates.append(os.path.join(folder, "bash.exe"))
        if os.path.isfile(os.path.join(folder, "git.exe")):  # <Git>\cmd\git.exe -> <Git>\bin\bash.exe
            candidates.append(os.path.join(os.path.dirname(folder.rstrip("\\/")), "bin", "bash.exe"))
    for var, sub in (("ProgramFiles", "Git"), ("ProgramFiles(x86)", "Git"), ("LOCALAPPDATA", "Programs\\Git")):
        if environ.get(var):
            candidates.append(os.path.join(environ[var], sub, "bin", "bash.exe"))
    return next((c for c in candidates if os.path.isfile(c)), None)


def install_commands(tool, system=None):
    """The commands that install ``tool`` on ``system``, or []."""
    ways = INSTALL.get(tool, {})
    exe = getattr(sys, "executable", "") or "python"
    python = f'"{exe}"' if " " in exe else exe
    return [w.replace("{python}", python) for w in (ways.get(system or system_name()) or ways.get("any", []))]


def _module(name):
    return importlib.util.find_spec(name) is not None


def optional_tools():
    """{tool: (present, purpose message id)}."""
    return {
        "playwright": (_playwright_ready(), _("headless browser for pages that need one")),
        "tesseract": (shutil.which("tesseract") is not None, _("OCR of printed records")),
        "pillow": (_module("PIL"), _("sheets of views, crops and turns of images")),
    }


def _playwright_ready():
    from probandia.reading.browser import browser_state

    return browser_state() == "ready"


def catalogue_path():
    from probandia.paths import data

    return data("catalogues", "providers.toml")


def catalogue_ages(path=None, today=None):
    """[(provider, age in days)] of the free-tier catalogue, or None when it is absent."""
    path = path or catalogue_path()
    if not os.path.isfile(path):
        return None
    data = tomllib.loads(read_text(path))
    today = today or datetime.date.today()
    out = []
    for name, entry in data.items():
        checked = entry.get("checked") if isinstance(entry, dict) else None
        if isinstance(checked, datetime.date):
            out.append((name, (today - checked).days))
        else:
            out.append((name, None))
    return out


def codex_agents(project):
    """The Probandia agents ``install --harness codex`` wrote in ``project`` (``.codex/agents/``)."""
    folder = os.path.join(project, ".codex", "agents") if project else ""
    try:
        return sorted(n for n in os.listdir(folder) if n.startswith("probandia-") and n.endswith(".toml"))
    except OSError:
        return []


def secret_variables(cat=None):
    """The key variables to look for: the known ones, then those of the catalogue,
    each once, even when several entries share it."""
    from probandia.providers import catalogue

    try:
        envs = [catalogue.key_env(e) for e in (cat or catalogue.load()).values()]
    except (OSError, ValueError):
        envs = []
    return list(dict.fromkeys(list(SECRET_VARIABLES) + [e for e in envs if e]))


def workshop_state(project, r):
    """WS6-T3: a project linked to its workshop: WORKSHOP=linked, its adapter, whether its check
    (outils/verifier.py) is there, and WORKSHOP_STALE when personnes.yaml changed since the last sync."""
    from probandia import workshop as ws

    try:
        link = ws.load(project)
        if link is None:
            return
        folder = ws.root(project, link)
        stale = ws.file_sha(ws.people_path(folder)) != (link.get("synced") or {}).get("sha256")
    except Exception:   # noqa: BLE001 — doctor never fails on the workshop
        return
    r.set("WORKSHOP", "linked")
    r.set("WORKSHOP_ADAPTER", link.get("adapter"))
    r.set("WORKSHOP_VERIFIER", "present" if os.path.isfile(os.path.join(folder, "outils", "verifier.py"))
          else "absent")
    r.set("WORKSHOP_STALE", stale)
    if stale:
        if r.status == "OK":
            r.status = "WARN"
        r.line(_("the workshop's personnes.yaml changed since the last sync: workshop status, then workshop pull"))


def run(harness_arg=None, environ=None, python=None, cat=None, system=None, config=None):
    environ = os.environ if environ is None else environ
    harness, how = detect(harness_arg, environ)
    caps = CAPABILITIES.get(harness, CAPABILITIES["cli"])
    version = python or sys.version_info
    r = Result("OK", {"HARNESS": harness, "DETECTED_BY": how, "SUPPORT": caps["support"],
                      "PYTHON": ".".join(str(v) for v in version[:3])})
    # agents run the engine with the Python their harness finds, maybe not the one of this terminal
    r.set("PYTHON_PATH", getattr(sys, "executable", "") or "")
    if tuple(version[:2]) < (3, 11):
        r.status = "FAIL"
        r.line(_("Python 3.11 or later is required"))
    # T130: the plugin's hooks and MCP entries run `python`; some systems only have python3
    if harness != "cli" and not shutil.which("python", path=environ.get("PATH")):
        r.status = "WARN" if r.status == "OK" else r.status
        r.set("PYTHON_COMMAND", "missing")
        r.line(_("no python command on the PATH: the plugin's hooks and MCP server run python; make it the "
                 "Python 3 (on Debian or Ubuntu: apt install python-is-python3)"))
    # T130: without Git Bash, Claude Code runs hooks in PowerShell, where their "$(command -v ...)" fails
    if harness == "claude-code" and (system or system_name()) == "windows" and not git_bash(environ):
        r.status = "WARN" if r.status == "OK" else r.status
        r.set("GIT_BASH", "missing")
        r.line(_("no Git Bash: Claude Code would run Probandia's hooks in PowerShell, where they fail; install "
                 "Git for Windows, or point CLAUDE_CODE_GIT_BASH_PATH to its bash.exe"))

    yes, no = _("yes"), _("no")
    r.line(_("web search: {value}").format(value=caps["web_search"] or no))
    r.line(_("subagents: {value}").format(value=yes if caps["subagents"] else no))
    r.line(_("question tool: {value}").format(value=caps["question"] or no))
    r.line(_("messages between agents: {value}").format(value=caps["messaging"] or no))
    r.line(_("hooks: {value}").format(value=yes if caps["hooks"] else no))
    r.line(_("MCP server: {value}").format(value=yes if caps["mcp"] else no))
    r.line(_("effort levels: {value}").format(value=", ".join(caps["efforts"]) or no))
    from probandia.project import find_project

    cwd = os.getcwd() if environ is os.environ else environ.get("PWD") or os.getcwd()
    try:
        project = find_project(None, environ, cwd)
    except Exception:   # noqa: BLE001 — outside a project
        project = None
    degraded = degradations(harness)
    # T11, T124: Codex plugins hold no subagents, but `install --harness codex` writes them in the project
    apart = codex_agents(project) if harness == "codex" else []
    if apart:
        degraded = [m for m in degraded if m != DEGRADATIONS["subagents"]]
        r.set("AGENTS_APART", len(apart))
        r.line(_("subagents: {count} Probandia agents installed apart in {path}").format(
            count=len(apart), path=os.path.join(".codex", "agents")))
    for message in degraded:
        r.line(_("degraded: {what}").format(what=_(message)))
    if harness == "cli":
        r.line(_("no harness detected: pass --harness, or run doctor from your agent"))

    variables = secret_variables(cat)
    present = [v for v in variables if environ.get(v)]
    r.set("KEYS", ",".join(present))
    r.set("KEYS_MISSING", len(variables) - len(present))
    from probandia.providers import catalogue

    try:
        shared = catalogue.shared_keys(cat)
    except (OSError, ValueError):
        shared = {}
    try:
        entries = (cat or catalogue.load()).items()
    except (OSError, ValueError):
        entries = []
    # quota sync reads these balances from the provider's account, at no cost
    readable = [pid for pid, e in entries if (e.get("introspection") or {}).get("method") == "endpoint"
                and environ.get(catalogue.key_env(e) or "")]
    r.set("BALANCES", ",".join(readable))
    for env, ids in shared.items():
        r.line(_("{key}: one key for {count} entries ({names}), {state}").format(
            key=env, count=len(ids), names=", ".join(ids),
            state=_("present") if environ.get(env) else _("missing")))
    read = [p for p in (environ.get("PROBANDIA_ENV_FILES") or "").split(os.pathsep) if p]
    for path in read:
        r.line(_("keys read from {path}").format(path=path))
    if not read:
        from probandia.util.envfile import user_file

        r.line(_("no .env file: keys can go in {path}, or in .env at the root of a project").format(
            path=user_file(environ)))

    missing, tools = [], []
    for tool, (found, purpose) in optional_tools().items():
        tools.append({"tool": tool, "installed": found, "purpose": purpose,
                      "install": [] if found else install_commands(tool, system)})
        if not found:
            missing.append(tool)
            r.line(_("optional, not installed: {tool} ({purpose})").format(tool=tool, purpose=purpose))
    r.set("OPTIONAL_MISSING", ",".join(missing))
    r.table("tools", tools, ["tool", "installed", "purpose", "install"])
    r.view = "doctor"
    r.extra = {"caps": caps, "degraded": [_(m) for m in degraded], "keys": present,
               "keys_known": len(variables), "shared": {env: (ids, bool(environ.get(env)))
                                                       for env, ids in shared.items()},
               "env_files": read, "user_env": None if read else _user_env(environ), "old": []}

    # optimize 5.1.9: learned elements nobody uses, or that fail more than they pass
    try:
        from probandia.library import health

        problems = health(project, environ)   # outside a project: the user's library only
    except Exception:   # noqa: BLE001 — doctor never fails on the library
        problems = []
    r.set("LIBRARY_ISSUES", len(problems))
    for scope, sid, problem in problems:
        r.line(_("library: {id} ({scope}) {problem}").format(id=sid, scope=scope, problem=problem))

    # optimize 5.2.7: the managed section of AGENTS.md
    from probandia import memory

    try:
        found = memory.problems(project, environ)
    except Exception:   # noqa: BLE001 — doctor never fails on the memory
        found = []
    r.set("MEMORY_ISSUES", len(found))
    for path, code in found:
        if r.status == "OK":
            r.status = "WARN"
        r.line(_("memory: {file} {problem}").format(file=os.path.basename(path), problem=memory.describe(code)))

    # a prototype workshop never imported, as a project or before its first new: its researches would start blind
    from probandia.importer import workshop_pending

    if workshop_pending(project or cwd):
        if r.status == "OK":
            r.status = "WARN"
        r.set("WORKSHOP", "pending")
        r.line(_("this folder is a prototype workshop that was never imported; "
                 "to start from what it establishes: probandia import ."))
    elif project:
        workshop_state(project, r)

    # agent-models R4: what silently overrides the model and the effort chosen for each agent role
    if harness == "claude-code" and config is not None:
        try:
            found = agent_overrides(environ, project, config)
        except Exception:   # noqa: BLE001 — doctor never fails on the roles
            found = []
        for line in found:
            if r.status == "OK":
                r.status = "WARN"
            r.line(line)

    # what every call to the model reads again before any work (the token analysis of 6 Oct. 2026)
    from probandia import tokens

    base = tokens.base_context(project) if project else None
    if base:
        r.set("CONTEXT_BASE", base[0])
        if base[0] > tokens.BASE_HEAVY:
            if r.status == "OK":
                r.status = "WARN"
            r.line(heavy_base_line(base[0]))

    ages = catalogue_ages()
    if ages is None:
        r.set("CATALOGUE", "absent")
        r.line(_("the free-tier catalogue is not installed"))
    else:
        from probandia.providers import catalogue as providers

        days = providers.max_age_days(config)
        old = providers.stale(ages, days)
        oldest = max((age for _n, age in ages if age is not None), default=0)
        r.set("CATALOGUE", len(ages))
        r.set("CATALOGUE_OLDEST_DAYS", oldest)
        if old:
            if r.status == "OK":
                r.status = "WARN"
            r.line(_("catalogue entries older than {days} days: {names}").format(
                days=days, names=", ".join(old)))
        r.extra["old"] = old
        r.extra["days"] = days
    return r


def _claude_settings(environ, project):
    """The settings files of Claude Code that apply here, read as JSON (an unreadable one is skipped)."""
    import json

    user = os.path.join(environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                        "settings.json")
    paths = [user] + ([os.path.join(project, ".claude", n) for n in ("settings.json", "settings.local.json")]
                      if project else [])
    out = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append((path, data))
    return out


def agent_overrides(environ, project, config):
    """Lines on what makes Claude Code ignore the model or the effort chosen for a role: two variables,
    in the environment or a settings file's ``env``, and a model ``availableModels`` leaves out or
    ``deniedModels`` names (documentation of Claude Code read on 12 Oct. 2026)."""
    from probandia import roles

    settings = _claude_settings(environ, project)
    variables = dict(environ)
    for _path, data in settings:
        env = data.get("env")
        if isinstance(env, dict):
            variables.update({k: str(v) for k, v in env.items()})
    out = []
    if variables.get("CLAUDE_CODE_EFFORT_LEVEL"):
        out.append(_("CLAUDE_CODE_EFFORT_LEVEL={value} sets the effort of every agent: the efforts chosen "
                     "for the roles (config roles) are ignored").format(value=variables["CLAUDE_CODE_EFFORT_LEVEL"]))
    if variables.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "").lower() in ("1", "true", "yes"):
        out.append(_("CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set: every agent runs on one model, and the models "
                     "chosen for the roles (config roles) are ignored"))
    chosen = {role: e["model"] for role, e in roles.resolve(config).items() if roles.chosen(e).get("model")}
    for path, data in settings:
        allowed, denied = data.get("availableModels"), data.get("deniedModels")
        for role, model in sorted(chosen.items()):
            if (isinstance(allowed, list) and model not in allowed) or (isinstance(denied, list) and model in denied):
                out.append(_("{role}: the model {model} is refused by {file}").format(
                    role=role, model=model, file=path))
    return out


def heavy_base_line(tokens_at_start):
    from probandia.tokens import PLUGIN_BASE

    return _("each call to the model first reads {n} tokens again, Probandia's part about {p}: turn off, "
             "for this project, the plugins and MCP servers it does not need (enabledPlugins in "
             ".claude/settings.json)").format(n=f"{tokens_at_start:,}".replace(",", " "), p=f"{PLUGIN_BASE:,}".replace(",", " "))


def _user_env(environ):
    from probandia.util.envfile import user_file

    return user_file(environ)
