"""The settings registry: the single description of every setting.

Each setting has a dotted key, a type, a default, a grade (1 Essential,
2 Advanced, 3 Expert), its allowed values, its environment variable, its
command flag, whether a harness exposes it as a plugin option, and a help
message id. A key never changes when its setting moves to another grade.

Some keys hold a placeholder, such as ``roles.<role>.model``: the registry
expands them into concrete keys (``roles.researcher.model``).
"""
import re

from probandia.i18n import N_

TYPES = ("str", "int", "bool", "enum", "list")
GRADES = {1: "essential", 2: "advanced", 3: "expert"}
GRADE_NUMBERS = {v: k for k, v in GRADES.items()}

EFFORTS = ("low", "medium", "high", "xhigh", "max")
ROLES = ("orchestrator", "researcher", "investigator", "harvester", "reader", "contradictor",
         "searcher")
QUESTION_TYPES = ("birth", "marriage", "death", "parents", "children", "residence", "migration",
                  "identity", "negative", "general")
PROVIDERS = ("serpapi", "serpapi_bing", "serper", "searchapi", "brave", "staan", "marginalia", "exa", "parallel",
             "tavily", "linkup", "gemini_grounding", "jina", "firecrawl", "openrouter",
             "openwebninja_search", "openwebninja_news", "openwebninja_books", "apify",
             "apify_reader", "zenrows", "scraperapi", "scrapegraph")
# Every provider is listed; those whose free tier requires a card (brave) or
# reuses content (gemini_grounding) stay off until providers.allow_card_required
# or providers.allow_content_reuse is true.
# SerpApi's Bing engine stays off by default: on 2 October 2026 it answered 4
# exact genealogical queries out of 5 with unrelated pages (Microsoft support,
# Yelp, Gartner). providers.enabled puts it back.
DEFAULT_PROVIDERS = tuple(p for p in PROVIDERS if p != "serpapi_bing")
ARCHIVES = ("ad50", "gallica", "matchid", "openarchives", "wikitree", "europeana", "loc", "wayback", "bnl",
            "geonames", "gov", "insee_cog", "iiif", "ddb")
# Routing items that are not provider or archive ids.
ROUTING_TOKENS = ("library", "family-index", "coverage", "native")
LADDER_STEPS = ("cache", "api", "http", "extract", "reader", "browser", "user-browser", "archive")
# T256: the readers of the ladder's reader step; Firecrawl and Tavily, whose free tiers
# come back each month, before Jina, whose grant does not; Parallel's extract last: a page
# it has not cached takes it a minute or more
READERS = ("firecrawl", "tavily", "jina", "parallel")
LANGUAGE_SOURCES = ("arg", "research", "env", "setting", "harness", "prompt", "os", "default")

ROLE_DEFAULTS = {
    "orchestrator": ("sonnet", "high"),
    "researcher": ("sonnet", "medium"),
    "investigator": ("opus", "high"),
    "harvester": ("haiku", "low"),
    "reader": ("sonnet", "medium"),
    "contradictor": ("opus", "high"),
    "searcher": ("haiku", "low"),
}

_FIRST_ROUND = ["library", "matchid", "openarchives", "gallica", "serpapi", "staan", "marginalia"]
ROUTING_DEFAULTS = {
    "birth": _FIRST_ROUND, "marriage": _FIRST_ROUND, "death": _FIRST_ROUND,
    "parents": _FIRST_ROUND, "children": _FIRST_ROUND,
    "residence": ["openarchives", "gallica", "loc", "europeana", "wikitree", "exa", "parallel"],
    "migration": ["openarchives", "gallica", "loc", "europeana", "wikitree", "exa", "parallel"],
    "identity": ["family-index", "openarchives", "wikitree", "serpapi"],
    "negative": ["coverage"],
    "general": ["native", "tavily", "linkup"],
}

LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
TEMPLATE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
RATE_RE = re.compile(r"^[1-9][0-9]*/(s|min|h|day)$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$")   # an alias (opus), an id, a provider/model
CONTACT_RE = re.compile(r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$|^https?://\S+$")
THEME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")   # dark, light, or a file of themes/ (config.themes)

PLACEHOLDERS = {
    "role": ROLES,
    "question_type": QUESTION_TYPES,
    "id": PROVIDERS,
    "host": HOST_RE,
}


class Setting:
    def __init__(self, key, type, default, grade, help, values=None, flag=None, harness=False,
                 env_aliases=(), items=None, check=None, values_text=None, ordered=False):
        assert type in TYPES and grade in GRADES, key
        self.key = key
        self.type = type
        self.default = default
        self.grade = grade
        self.help = help
        self.values = values          # enum: allowed values; int: (min, max)
        self.items = items            # list: allowed items, or None for any string
        self.ordered = ordered        # list: the order of its items means something
        self.check = check            # str: a compiled pattern the value must match
        self.flag = flag
        self.harness = harness
        self.env = env_name(key)
        self.env_aliases = tuple(env_aliases)
        self.values_text = values_text

    @property
    def is_pattern(self):
        return "<" in self.key

    @property
    def harness_key(self):
        """The plugin option name: dots become underscores."""
        return self.key.replace(".", "_")

    def describe_values(self):
        """The allowed values, as one line of text."""
        if self.values_text:
            return self.values_text
        if self.type == "enum":
            return ", ".join(v if v else '""' for v in self.values)
        if self.type == "int" and self.values:
            return f"{self.values[0]} to {self.values[1]}"
        if self.type == "bool":
            return "true, false"
        if self.type == "list" and self.items:
            return "list of: " + ", ".join(self.items)
        if self.type == "list":
            return "list of strings"
        return "text"

    def expand(self, default_only=False):
        """Concrete (key, default) pairs of a pattern setting."""
        if not self.is_pattern:
            return [(self.key, self.default)]
        name = re.search(r"<([a-z_]+)>", self.key).group(1)
        domain = PLACEHOLDERS[name]
        if not isinstance(domain, tuple):
            return []  # open domain (hosts): no concrete key by default
        out = []
        for value in domain:
            key = self.key.replace(f"<{name}>", value)
            default = self.default(value) if callable(self.default) else self.default
            out.append((key, default))
        return out

    def __repr__(self):
        return f"Setting({self.key!r})"


def env_name(key):
    """report.mode -> PROBANDIA_REPORT_MODE; placeholders stay as <NAME>."""
    out = []
    for part in re.split(r"(<[a-z_]+>)", key):
        out.append(part if part.startswith("<") else re.sub(r"[.\-]", "_", part).upper())
    return "PROBANDIA_" + "".join(out).upper()


def _role_default(index):
    return lambda role: ROLE_DEFAULTS[role][index]


S = Setting
SETTINGS = [
    # Essential: grade 1
    S("language", "str", "auto", 1, N_("Language of reports: auto, or a BCP-47 tag such as en or fr"),
      check=LANGUAGE_RE, flag="--lang", harness=True, env_aliases=("PROBANDIA_LANG",),
      values_text="auto, or a BCP-47 tag (en, fr, fr-CA…)"),
    S("report.mode", "enum", "journal", 1, N_("Report mode: a journal with errata, or a living report"),
      values=("journal", "living"), flag="--report-mode", harness=True),
    S("report.numbering", "enum", "arabic", 1, N_("Numbering of chapters and sections"),
      values=("arabic", "roman", "roman-outline"), flag="--numbering", harness=True,
      values_text="arabic, roman; also roman-outline (expert)"),
    S("report.formats", "list", ["md", "html"], 1, N_("Formats of the report"),
      items=("md", "html", "json"), flag="--format", harness=True),
    S("tree.format", "enum", "all", 1, N_("Format of the family tree: html, md or all"),
      values=("html", "md", "all"), flag="--tree-format", harness=True),
    S("run.mode", "enum", "ask", 1, N_("Who runs a research: ask, the session agent, a subagent or a team"),
      values=("ask", "session", "subagent", "team"), flag="--mode", harness=True),
    S("search.max_parallel", "int", 3, 1, N_("Web searches run in parallel"),
      values=(1, 8), flag="--parallel", harness=True),
    S("grade", "enum", "essential", 1, N_("Settings grade: how many settings are shown"),
      values=("essential", "advanced", "expert"), flag="--grade", harness=True),
    # Advanced: grade 2
    S("run.model", "str", "", 2, N_("Model of the subagent; empty for the harness default"),
      flag="--model", values_text="model alias or id; empty for the harness default"),
    S("run.effort", "enum", "", 2, N_("Effort of the subagent; empty for the harness default"),
      values=("",) + EFFORTS, flag="--effort"),
    S("team.max_agents", "int", None, 2, N_("Number of agents in a team; asked when unset"),
      values=(1, 20), flag="--agents"),
    S("team.effort", "enum", None, 2, N_("Effort of the team's agents; asked when unset"),
      values=EFFORTS, flag="--effort"),
    S("team.max_passes", "int", None, 2, N_("Passes a team may run; asked when unset"),
      values=(1, 10), flag="--passes"),
    S("search.model", "str", "", 2, N_("Model of the web searchers; empty for a small model"),
      values_text="model alias or id"),
    S("search.effort", "enum", "low", 2, N_("Effort of the web searchers"), values=EFFORTS),
    S("roles.<role>.model", "str", _role_default(0), 2, N_("Model of one agent role"),
      check=MODEL_RE, values_text="model alias or id"),
    S("roles.<role>.effort", "enum", _role_default(1), 2, N_("Effort of one agent role"),
      values=EFFORTS),
    # agent-models R6: one model per harness, where roles.<role>.model does not fit its form
    S("roles.<role>.models", "list", [], 2, N_("Model of one agent role in one harness: harness:model items"),
      values_text="harness:model items, such as cursor:claude-opus-5, codex:gpt-6.1-sol"),
    S("providers.enabled", "list", list(DEFAULT_PROVIDERS), 2, N_("Providers that may be used"),
      items=PROVIDERS),
    # what providers disable writes: only the providers turned off, so that one
    # added to the catalogue later is not left off by a frozen list
    S("providers.disabled", "list", [], 2, N_("Providers turned off, whatever providers.enabled says"),
      items=PROVIDERS),
    S("providers.allow_card_required", "bool", False, 2,
      N_("Allow providers whose free tier requires a credit card")),
    S("providers.allow_content_reuse", "bool", False, 2,
      N_("Allow providers that may reuse the content sent to them")),
    S("budget.reserve_percent", "int", 10, 2, N_("Share of each free quota kept in reserve"),
      values=(0, 50)),
    S("archives.enabled", "list", list(ARCHIVES), 2, N_("Archive connectors that may be used"),
      items=ARCHIVES),
    S("catalogues.max_age_days", "int", 90, 2,
      N_("Days after which an entry of the providers' or archives' catalogue is stale"), values=(7, 365)),
    S("cache.days", "int", 7, 2, N_("Days a cached response stays valid"), values=(0, 90),
      flag="--fresh"),
    S("web.negative_families", "int", 2, 2,
      N_("Independent index families a web negative needs"), values=(2, 4)),
    S("proof.standard", "enum", "off", 2,
      N_("How the Genealogical Proof Standard is checked: off, warn (close asks), strict (close refuses)"),
      values=("off", "warn", "strict")),
    S("workshop.sync", "enum", "ask", 2,
      N_("After an apply in a project linked to its workshop: off, ask (once a pass) or auto (push the new facts)"),
      values=("off", "ask", "auto")),
    S("workshop.check", "str", "", 2,
      N_("The workshop's own check, run in its folder after a push (python outils/verifier.py); empty: recalled")),
    S("privacy.living_years", "int", 100, 2,
      N_("A person born less than this many years ago is presumed living"), values=(70, 120)),
    S("report.simplified_trees", "bool", True, 2, N_("Show simplified trees in reports")),
    S("report.timeline", "enum", "main", 2,
      N_("Timelines in reports: the main persons of the research, all its persons, or none"),
      values=("main", "all", "off")),
    S("report.template", "str", "habillage", 2, N_("Template of the HTML report: an id of template list"),
      check=TEMPLATE_RE, values_text="habillage, default, or the id of a template"),
    S("report.images", "enum", "folder", 2,
      N_("Views of the acts in the HTML report: files of a views folder next to it, embedded in the file, or none"),
      values=("folder", "inline", "off")),
    S("library.save", "enum", "ask", 2, N_("Saving the scripts that agents write"),
      values=("ask", "auto", "off")),
    S("http.contact", "str", "", 2, N_("Contact sent in the User-Agent of web requests"),
      check=CONTACT_RE, env_aliases=("PROBANDIA_CONTACT",),
      values_text="e-mail address or URL"),
    # version-1.0.0 T94: written by the t key of probandia tui, with config set --user
    S("tui.theme", "str", "dark", 2, N_("Theme of the terminal interface: dark, light or one of yours"),
      check=THEME_RE, values_text="dark, light, or the name of one of your themes (config theme list)"),
    # Expert: grade 3
    S("routing.<question_type>", "list", lambda t: list(ROUTING_DEFAULTS[t]), 3,
      N_("Providers and archives tried first for one type of question"),
      items=PROVIDERS + ARCHIVES + ROUTING_TOKENS, ordered=True),
    S("providers.<id>.monthly_cap", "int", None, 3,
      N_("A lower monthly cap for one provider; never above its free tier"),
      values=(0, 10_000_000)),
    S("providers.<id>.cache_ttl", "int", None, 3,
      N_("A shorter cache life, in days, for one provider"), values=(0, 90)),
    S("hosts.<host>.rate", "str", None, 3, N_("Request rate for one host, such as 5/min"),
      check=RATE_RE, values_text="<n>/s, <n>/min, <n>/h or <n>/day"),
    S("reading.per_search", "int", 3, 3, N_("Pages a wave plans to read for each search"),
      values=(0, 20)),
    S("reading.ladder", "list", list(LADDER_STEPS), 3, N_("Steps of the reading ladder, in order"),
      items=LADDER_STEPS, ordered=True),
    S("reading.readers", "list", list(READERS), 3,
      N_("Readers of the ladder's reader step, in order; the unblocking readers come after them"),
      items=READERS, ordered=True),
    # optimize 2.11: what read puts in an agent's context; the full text stays in DETAILS.
    # The defaults are the old values until the review of 2.14 measures them.
    S("reading.max_passages", "int", 12, 3, N_("Passages read returns for a question"), values=(1, 30)),
    S("reading.passage_chars", "int", 500, 3, N_("Characters of each passage read returns"),
      values=(100, 2000)),
    # T230: read --crawl <n> reads at most this many pages, whatever n asks
    S("read.crawl_max_pages", "int", 20, 3, N_("Pages read --crawl reads at most"), values=(1, 200)),
    S("report.number_pattern", "str", "", 3, N_("Custom numbering pattern, such as {I}.{A}.{1}"),
      values_text="pattern such as {I}.{A}.{1}"),
    S("templates.dir", "str", "", 3, N_("Folder of user report templates")),
    S("locales.dir", "str", "", 3, N_("Folder of user message catalogues")),
    S("library.auto_trust_after", "int", 0, 3,
      N_("Successful runs before a tested script is trusted; 0 for never"), values=(0, 1000)),
    S("hooks.guard", "bool", True, 3, N_("Run the guard hook")),
    S("hooks.digest", "bool", True, 3, N_("Run the digest hook")),
    S("hooks.journal", "bool", True, 3, N_("Run the journal hook")),
    S("hooks.verify", "bool", True, 3, N_("Run the verify hook")),
    S("mcp.code_mode", "bool", True, 3, N_("Expose the MCP server as two meta-tools")),
    S("digest.max_lines", "int", 60, 3, N_("Lines of the state digest"), values=(20, 200)),
    S("locks.expiry_minutes", "int", 30, 3, N_("Minutes before a lock expires"), values=(1, 1440)),
    S("language.detection_order", "list", list(LANGUAGE_SOURCES), 3,
      N_("Order of the sources of the report language"), items=LANGUAGE_SOURCES, ordered=True),
    S("search.native", "bool", True, 3, N_("Use the harness's own web search")),
    S("search.native_max_per_pass", "int", 40, 3, N_("Native web searches per pass"),
      values=(0, 200)),
    S("witness.max_age_hours", "int", 24, 3, N_("Hours a witness search stays valid"),
      values=(1, 8760)),
    S("negatives.recheck_days", "int", 365, 3,
      N_("Days before a negative without a recheck rule expires"), values=(1, 36500)),
    S("gramps.url", "str", "", 3, N_("Address of the Gramps Web server")),
    S("gramps.user", "str", "", 3, N_("User on the Gramps Web server")),
]
del S

BY_KEY = {s.key: s for s in SETTINGS}

# Keys of a configuration file that are not settings.
META_KEYS = ("schema",)

# PROBANDIA_* variables that are not settings.
OTHER_VARIABLES = ("PROBANDIA_CONFIG_DIR", "PROBANDIA_PROJECT", "PROBANDIA_WORKER",
                   "PROBANDIA_BENCH_DIR", "PROBANDIA_SESSION", "PROBANDIA_GRAMPS_PASSWORD",
                   "PROBANDIA_ENV_FILES", "PROBANDIA_HARNESS", "PROBANDIA_AGENT",
                   "PROBANDIA_HEADLESS", "PROBANDIA_DATA_DIR", "PROBANDIA_OUTPUT",
                   "PROBANDIA_PAGER", "PROBANDIA_YAML_PURE")
# What each of them does (help settings).
VARIABLE_HELP = {
    "PROBANDIA_CONFIG_DIR": N_("the folder of config.toml and of your .env"),
    "PROBANDIA_PROJECT": N_("the root of the project, instead of -p"),
    "PROBANDIA_WORKER": N_("1: a pass nobody watches (the guard G-4 keeps it in work/)"),
    "PROBANDIA_BENCH_DIR": N_("the folder of the bench"),
    "PROBANDIA_SESSION": N_("the id of the session, for the locks"),
    "PROBANDIA_GRAMPS_PASSWORD": N_("the password of Gramps Web (a key, not a setting)"),
    "PROBANDIA_ENV_FILES": N_("other .env files to read"),
    "PROBANDIA_HARNESS": N_("the harness, instead of --harness"),
    "PROBANDIA_AGENT": N_("the role of the agent, instead of --agent"),
    "PROBANDIA_HEADLESS": N_("no visible browser"),
    "PROBANDIA_DATA_DIR": N_("the folder of the engine's data"),
    "PROBANDIA_OUTPUT": N_("the form of the output, instead of --output-format"),
    "PROBANDIA_PAGER": N_("the pager of long screens"),
    "PROBANDIA_YAML_PURE": N_("1: read YAML with the pure Python parser, even where libyaml is installed"),
}


def _pattern_regex(setting):
    parts = re.split(r"(<[a-z_]+>)", setting.key)
    rx = "".join("(?P<p>.+)" if p.startswith("<") else re.escape(p) for p in parts)
    return re.compile(f"^{rx}$")


_PATTERNS = [(s, _pattern_regex(s)) for s in SETTINGS if s.is_pattern]


# Settings renamed or removed: old key -> the key that replaces it (STABILITY.md). A file that sets
# an old key gets a WARN naming the new one; an old key still in SETTINGS keeps its own meaning
# (here: roles.py reads it while the role's key is left alone), one no longer there is read as the new key.
RENAMED = {
    "run.model": "roles.orchestrator.model",
    "run.effort": "roles.orchestrator.effort",
    "search.model": "roles.searcher.model",
    "search.effort": "roles.searcher.effort",
}


def lookup(key):
    """The Setting of a concrete key, or None. Placeholders must take an allowed value."""
    if key in BY_KEY and not BY_KEY[key].is_pattern:
        return BY_KEY[key]
    for setting, rx in _PATTERNS:
        m = rx.match(key)
        if m:
            name = re.search(r"<([a-z_]+)>", setting.key).group(1)
            domain = PLACEHOLDERS[name]
            value = m.group("p")
            ok = value in domain if isinstance(domain, tuple) else bool(domain.match(value))
            if ok:
                return setting
    return None


def default_of(key):
    setting = lookup(key)
    if setting is None:
        raise KeyError(key)
    if callable(setting.default):
        value = _pattern_regex(setting).match(key).group("p")
        return setting.default(value)
    return _copy(setting.default)


def _copy(value):
    return list(value) if isinstance(value, list) else value


def concrete_keys(max_grade=3):
    """Every concrete key up to a grade, with its default, in registry order."""
    out = []
    for s in SETTINGS:
        if s.grade <= max_grade:
            out.extend((k, _copy(d)) for k, d in s.expand())
    return out


def by_grade(grade):
    return [s for s in SETTINGS if s.grade == grade]


def env_lookup(variable):
    """The concrete key named by a PROBANDIA_* variable, or None."""
    for s in SETTINGS:
        if not s.is_pattern and (variable == s.env or variable in s.env_aliases):
            return s.key
    for s, _ in _PATTERNS:
        prefix, _, suffix = s.env.partition("<")
        suffix = suffix.partition(">")[2]
        if variable.startswith(prefix) and variable.endswith(suffix) and len(variable) > len(prefix + suffix):
            middle = variable[len(prefix): len(variable) - len(suffix)].lower()
            name = re.search(r"<([a-z_]+)>", s.key).group(1)
            domain = PLACEHOLDERS[name]
            if isinstance(domain, tuple) and middle in domain:
                return s.key.replace(f"<{name}>", middle)
    return None


def harness_settings():
    return [s for s in SETTINGS if s.harness]
