"""The adapter interface of search and reading providers.

Adapters use the engine's HTTP client and nothing else. An unexpected answer
raises ``ProviderError`` with the HTTP status and a 200-character excerpt; an
adapter never returns an empty list in place of an error.
"""
import json
from dataclasses import dataclass, field

from probandia.errors import ProbandiaError


@dataclass
class Query:
    text: str
    exact: bool = False
    site: str | None = None
    filetype: str | None = None
    lang: str | None = None
    country: str | None = None
    date_from: str | None = None     # ISO date
    date_to: str | None = None
    max: int = 10
    depth: str = "standard"          # "advanced": a deeper, dearer search (search --depth)

    def compose(self):
        """The query string with its operators (quotes, site:, filetype:)."""
        text = self.text
        if self.exact and not text.startswith('"'):
            text = f'"{text}"'
        if self.site:
            text += f" site:{self.site}"
        if self.filetype:
            text += f" filetype:{self.filetype}"
        return text


@dataclass
class Result:
    title: str
    url: str
    snippet: str
    date: str | None
    provider: str
    family: str
    rank: int


@dataclass
class Usage:
    units: float
    reported: dict = field(default_factory=dict)


@dataclass
class Page:
    text: str
    final_url: str
    status: int
    title: str = ""


class ProviderError(ProbandiaError):
    """An answer the adapter did not expect: never read as "no results"."""

    reason = "provider-error"

    def __init__(self, provider, status, body, message=None, retry_after=None):
        excerpt = body if isinstance(body, str) else body.decode("utf-8", "replace")
        excerpt = " ".join(excerpt.split())[:200]
        super().__init__(message or f"{provider}: HTTP {status}: {excerpt}",
                         values={"PROVIDER": provider, "HTTP": status})
        self.provider = provider
        self.status = status
        self.excerpt = excerpt
        self.retry_after = retry_after


def dig(obj, path, default=None):
    """``dig(d, "a.b.0.c")``."""
    cur = obj
    for part in path.split(".") if path else []:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        else:
            return default
    return cur


class Adapter:
    """A provider reached through the engine's HTTP client."""

    id = ""
    family = "opaque"
    unit_per_call = 1.0

    def __init__(self, client, entry, environ):
        self.client = client
        self.entry = entry
        self.environ = environ

    @property
    def key(self):
        env = (self.entry.get("auth") or {}).get("env")
        return self.environ.get(env, "") if env else ""

    # True when search() honours Query.depth "advanced" (priced as costs.search_advanced)
    advanced = False

    def estimate(self, query):
        costs = self.entry.get("costs") or {}
        if query.depth == "advanced" and "search_advanced" in costs:
            return costs["search_advanced"]
        return costs.get("search", self.unit_per_call)

    # The operations beyond search and read (T228): what a provider's MCP server
    # offered the agents, and the engine now does itself (read --map, --crawl, --extract).
    OPERATIONS = ("map", "crawl", "extract")

    @classmethod
    def does(cls, operation):
        """True when this adapter makes ``operation`` (it overrides the method)."""
        if operation == "search_advanced":
            return cls.advanced
        return getattr(cls, operation, None) not in (None, getattr(Adapter, operation, None))

    def cost(self, operation, pages=1):
        """The catalogue's units for one ``operation``: per call, or per page (or URL
        returned) for an operation listed in the entry's ``per_page``."""
        costs = self.entry.get("costs") or {}
        unit = costs.get(operation, costs.get("search", self.unit_per_call))
        return unit * max(1, pages) if operation in (self.entry.get("per_page") or ()) else unit

    def map(self, url, limit=100, search=None):
        """The URLs of a site, from ``url``: ``([url, ...], Usage)``."""
        raise NotImplementedError(f"{self.id}: no map")

    def crawl(self, url, limit=10, include=None, wait=60.0):
        """The pages of a site, followed from ``url``: ``([Page, ...], Usage)``. At most
        ``limit`` pages, and never longer than ``wait`` seconds; ``include`` keeps
        the paths that match one of its patterns (regular expressions)."""
        raise NotImplementedError(f"{self.id}: no crawl")

    def extract(self, url, instruction, schema=None):
        """The page turned into JSON after ``instruction`` (and ``schema``, a JSON
        schema): ``(object, Usage)``."""
        raise NotImplementedError(f"{self.id}: no extract")

    def _json(self, resp):
        if resp.status != 200:
            ra = resp.headers.get("retry-after")
            raise ProviderError(self.id, resp.status, resp.body, retry_after=ra)
        try:
            return json.loads(resp.text)
        except ValueError:
            raise ProviderError(self.id, resp.status, resp.body,
                                f"{self.id}: the answer is not JSON")

    def _missing(self, resp, what):
        raise ProviderError(self.id, resp.status, resp.body, f"{self.id}: no {what} in the answer")

    def results(self, items, title, url, snippet, date=None):
        out = []
        for i, item in enumerate(items, start=1):
            u = dig(item, url)
            if not u:
                continue
            out.append(Result(title=dig(item, title) or "", url=u, snippet=dig(item, snippet) or "",
                              date=dig(item, date) if date else None, provider=self.id,
                              family=self.family, rank=len(out) + 1))
        return out
