"""The free-tier catalogue: ``catalogues/providers.toml``, one table per provider.

A provider is usable when:
- it is listed in ``providers.enabled``;
- its key is set (when it needs one);
- it does not require a card, unless ``providers.allow_card_required`` is true;
- it does not reuse the content sent to it, unless ``providers.allow_content_reuse`` is true.

Several entries may share one key: one entry per API of a platform that counts
each API's quota apart (OpenWeb Ninja, decision 1.2 of optimize.md). Each entry
keeps its own quota in the ledger; ``doctor`` checks the key once, and
``quota show`` lists the entries together under their ``platform``.

Reading has tiers, cheapest first (``TIERS``): a reader declares in ``costs`` the
ones it offers. The ladder reads at the cheapest and goes one tier up only when
the detector finds the page unrendered. Anti-bot tiers (premium or residential
proxy, stealth mode) are never used, even when an entry declares them.

``kind`` says what an entry is for (``KINDS``): ``search``, ``read``, ``extract``
(a page turned into JSON after an instruction: ``read --extract``) or ``model``.
``usable(..., kind="search")`` or ``kind="read"`` never gives an extraction entry,
as it never gives a model.

``mcp_tools`` names the tools of a provider's own MCP server and the operation each
makes: ``mcp_tool`` attributes an MCP call to its entry, whatever its server is named (T49).
"""
import datetime
import re
import tomllib

from probandia import paths
from probandia.util.fs import read_text

KINDS = ("search", "read", "extract", "model")
# B: Bing, through SerpApi's Bing engine (optimize.md 1.11).
FAMILIES = ("G", "B", "Br", "E", "M", "Ma", "X", "P", "Px", "opaque")
KEYWORD_FAMILIES = ("G", "B", "Br", "E", "M", "Ma")
MAX_AGE_DAYS = 90   # the default of catalogues.max_age_days (TRUST4-T2)
# Reading tiers, cheapest first. A cost missing for a tier falls back to the one
# below it, then to ``search``.
TIERS = ("read", "read_js")
TIER_BELOW = {"read_premium": "read_js", "read_js": "read", "read": "search"}


def path():
    return paths.data("catalogues", "providers.toml")


_CACHE = {}


def load(file=None):
    """{id: entry}, each entry with its ``id``."""
    file = file or path()
    if file not in _CACHE:
        data = tomllib.loads(read_text(file))
        _CACHE[file] = {pid: dict(entry, id=pid) for pid, entry in data.items()}
    return _CACHE[file]


def key_env(entry):
    auth = entry.get("auth") or {}
    return auth.get("env")


def has_key(entry, environ):
    env = key_env(entry)
    return not env or bool(environ.get(env)) or entry.get("key_optional", False)


def tiers(entry):
    """The reading tiers ``entry`` offers, cheapest first."""
    costs = entry.get("costs") or {}
    return [t for t in TIERS if t in costs] or ["read"]


def platform(entry):
    """The platform an entry belongs to: its ``platform``, otherwise its id."""
    return entry.get("platform") or entry["id"]


def shared_keys(catalogue=None):
    """{key variable: [ids]} of the keys that more than one entry uses."""
    by_key = {}
    for pid, e in (catalogue or load()).items():
        env = key_env(e)
        if env:
            by_key.setdefault(env, []).append(pid)
    return {env: ids for env, ids in by_key.items() if len(ids) > 1}


def _disabled(config):
    try:
        return config.get("providers.disabled")
    except KeyError:   # a configuration that predates the setting
        return None


def why_unusable(entry, config, environ):
    """None when the provider can be used; otherwise a short reason code."""
    enabled = config.get("providers.enabled") if config else None
    if enabled is not None and entry["id"] not in enabled:
        return "not-enabled"
    if config and entry["id"] in (_disabled(config) or []):
        return "not-enabled"
    if entry.get("card_required") and not (config and config.get("providers.allow_card_required")):
        return "card-required"
    if entry.get("content_reuse") and not (config and config.get("providers.allow_content_reuse")):
        return "content-reuse"
    if not has_key(entry, environ):
        return "no-key"
    return None


def does(entry, operation):
    """True when the catalogue prices ``operation`` for ``entry`` and its adapter makes
    it (``map``, ``crawl``, ``extract``: T228; ``search_advanced``: search --depth advanced)."""
    from probandia.providers import adapters

    cls = adapters.REGISTRY.get(entry["id"])
    if operation not in (entry.get("costs") or {}) or cls is None:
        return False
    return cls.does(operation)


def usable(config, environ, kind=None, catalogue=None, operation=None):
    """The ids of the usable providers, in catalogue order; with ``operation``, only
    those that make it."""
    cat = catalogue or load()
    return [pid for pid, e in cat.items()
            if (kind is None or e.get("kind") == kind) and (operation is None or does(e, operation))
            and why_unusable(e, config, environ) is None]


MCP_OPERATIONS = ("search", "read", "map", "crawl", "extract")
# What a tool's name says it does, once the provider's own name is taken out of it
# ("firecrawl_crawl" is a crawl, "firecrawl_search" a search): the first that matches.
MCP_GUESS = (("search", re.compile("search")), ("map", re.compile("map")), ("crawl", re.compile("crawl")),
             ("extract", re.compile("extract")), ("read", re.compile("scrape|read|fetch|markdown")))
# a tool that only looks at the account or at a job already paid for makes no operation
MCP_FREE = re.compile("status|credit|usage|feedback|monitor|history|cancel|stop")


def _words(name):
    return [w for w in re.split(r"[^a-z0-9]+", str(name).lower()) if w]


def _heads(cat):
    return {pid.split("_")[0] for pid in cat} | {e["platform"] for e in cat.values() if e.get("platform")}


def _tool_key(name):
    return "_".join(_words(name))


def mcp_operation(name, cat=None):
    """The operation an MCP tool's own name (``tavily_map``) suggests, its provider's
    word left out; None when it says nothing (``firecrawl_credit_usage``)."""
    heads = _heads(cat or load())
    rest = "_".join(w for w in _words(name) if w not in heads)
    if MCP_FREE.search(rest):
        return None
    return next((op for op, rx in MCP_GUESS if rx.search(rest)), None)


def mcp_tool(tool, cat=None):
    """T49: ``(provider, operation)`` of an MCP tool ``mcp__<server>__<tool>``, or
    ``(None, guessed operation)`` when no catalogue entry is behind it. The operation is
    one of ``MCP_OPERATIONS``, or None for a tool that makes none (a status, a balance).

    The server's name is compared word by word with the entries' ids (``claude_ai_Exa``
    and ``plugin_exa_exa`` are Exa's, ``hexagon`` is no one's); a server whose name says
    nothing (a claude.ai connector named by a UUID) is known by its tool, when an entry's
    ``mcp_tools`` lists it. ``mcp_tools`` also gives the operation; a tool it does not list
    gets the one its name suggests, or, when the entry prices a single operation, that one
    (every tool of ScrapeGraph extracts). Among the entries of one platform, the one whose
    ``api_id`` the tool names, else the one of the operation's kind."""
    cat = cat or load()
    parts = str(tool).split("__", 2)
    if len(parts) < 3 or parts[0] != "mcp":
        return None, None
    server, name = set(_words(parts[1])), _tool_key(parts[2])
    found = [pid for pid in cat if pid.split("_")[0] in server or cat[pid].get("platform") in server]
    if not found:
        found = [pid for pid in cat if name in {_tool_key(t) for t in cat[pid].get("mcp_tools") or {}}]
    listed = next((op for pid in found for t, op in (cat[pid].get("mcp_tools") or {}).items()
                   if _tool_key(t) == name), None)
    op = listed or mcp_operation(name, cat)
    if not found:
        return None, op
    by_api = [pid for pid in found if cat[pid].get("api_id") and cat[pid]["api_id"] in name]
    kind = "read" if op in ("read", "crawl", "extract", "map") else "search"
    pid = (by_api or [p for p in found if cat[p].get("kind") == kind] or found)[0]
    priced = [o for o in MCP_OPERATIONS if o in (cat[pid].get("costs") or {})]
    if listed is None and op not in priced and len(priced) == 1 and not MCP_FREE.search(name):
        op = priced[0]
    return pid, op


def max_age_days(config=None):
    """TRUST4-T2: the days after which a catalogue entry is stale, the one place that reads the setting."""
    value = config.get("catalogues.max_age_days") if config is not None else None
    return int(value) if value else MAX_AGE_DAYS


def stale(ages_, days):
    """The names of ``ages_`` ([(name, age in days or None)]) older than ``days``, or never checked."""
    return [name for name, age in ages_ if age is None or age > days]


def ages(catalogue=None, today=None):
    """[(id, days since checked)]."""
    today = today or datetime.date.today()
    out = []
    for pid, e in (catalogue or load()).items():
        checked = e.get("checked")
        out.append((pid, (today - checked).days if isinstance(checked, datetime.date) else None))
    return out
