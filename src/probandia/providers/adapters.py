"""The search and reading adapters, and the quota synchronisation of each provider.

Every adapter turns the provider's answer into ``Result`` objects and a
``Usage``; an unexpected answer raises ``ProviderError``. ``sync`` reads a
provider's own count of what is left, where it gives one.
"""
import datetime
import json
import time
import urllib.parse

from probandia.providers import catalogue
from probandia.providers.base import Adapter, Page, ProviderError, Usage, dig

REGISTRY = {}


def adapter(cls):
    REGISTRY[cls.id] = cls
    return cls


def make(provider, client, entry, environ):
    return REGISTRY[provider](client, entry, environ)


def _bearer(key):
    return {"Authorization": f"Bearer {key}"}


def _post_json(client, url, body, headers, timeout=None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers)
    return client.request("POST", url, headers=h, body=json.dumps(body).encode("utf-8"), api=True,
                          **({"timeout": timeout} if timeout else {}))


def _get(client, url, params=None, headers=None):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    return client.get(full, headers=headers or {}, api=True)


# Google index


@adapter
class SerpApi(Adapter):
    """Google through SerpApi. A search SerpApi serves from its one-hour cache is
    free (its documentation, 2 October 2026): it costs no unit here either."""

    id, family = "serpapi", "G"
    engine = "google"
    now = staticmethod(time.time)

    def params(self, q):
        params = {"engine": self.engine, "q": q.compose(), "num": min(q.max, 100), "api_key": self.key}
        if q.lang:
            params["hl"] = q.lang
        if q.country:
            params["gl"] = q.country.lower()
        return params

    def search(self, q):
        resp = _get(self.client, self.entry["base_url"], self.params(q))
        data = self._json(resp)
        usage = Usage(0.0 if serpapi_cached(data, self.now()) else self.estimate(q))
        items = data.get("organic_results")
        if items is None:
            if dig(data, "search_information.organic_results_state") == "Fully empty":
                return [], usage
            self._missing(resp, "organic_results")
        return self.results(items, "title", "link", "snippet", "date"), usage


@adapter
class SerpApiBing(SerpApi):
    """Bing through SerpApi, on the same account: an index family of its own (B)."""

    id, family = "serpapi_bing", "B"
    engine = "bing"

    def params(self, q):
        params = {"engine": "bing", "q": q.compose(), "count": min(q.max, 50), "api_key": self.key}
        if q.country:
            params["cc"] = q.country.upper()
        return params


SERPAPI_CACHE_SECONDS = 3600
SERPAPI_FRESH_SECONDS = 60


def serpapi_cached(data, now):
    """True when the answer is a search made earlier and kept by SerpApi's cache:
    its ``search_metadata.created_at`` is more than a minute old (and less than
    the hour the cache keeps it). To confirm against a live answer."""
    created = dig(data, "search_metadata.created_at")
    if not isinstance(created, str):
        return False
    try:
        when = datetime.datetime.strptime(created.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    age = now - when.replace(tzinfo=datetime.timezone.utc).timestamp()
    return SERPAPI_FRESH_SECONDS < age <= SERPAPI_CACHE_SECONDS + SERPAPI_FRESH_SECONDS


def sync_serpapi(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], {"api_key": key})
    data = _check(resp, "serpapi")
    left = data.get("plan_searches_left", data.get("total_searches_left"))
    if left is None:
        raise ProviderError("serpapi", resp.status, resp.body, "serpapi: no plan_searches_left")
    return {"left": float(left), "used": data.get("this_month_usage")}


@adapter
class Serper(Adapter):
    id, family = "serper", "G"

    def search(self, q):
        params = {"q": q.compose(), "num": min(q.max, 100)}
        if q.country:
            params["gl"] = q.country.lower()
        if q.lang:
            params["hl"] = q.lang
        resp = _get(self.client, self.entry["base_url"], params, {"X-API-KEY": self.key})
        data = self._json(resp)
        items = data.get("organic")
        if items is None:
            if "searchParameters" in data:
                return [], Usage(float(data.get("credits", self.estimate(q))))
            self._missing(resp, "organic")
        return (self.results(items, "title", "link", "snippet", "date"),
                Usage(float(data.get("credits", self.estimate(q)))))


def sync_serper(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], headers={"X-API-KEY": key})
    data = _check(resp, "serper")
    if "balance" not in data:
        raise ProviderError("serper", resp.status, resp.body, "serper: no balance in the answer")
    return {"left": float(data["balance"])}


@adapter
class SearchApi(Adapter):
    id, family = "searchapi", "G"

    def search(self, q):
        params = {"engine": "google", "q": q.compose()}
        if q.lang:
            params["hl"] = q.lang
        if q.country:
            params["gl"] = q.country.lower()
        resp = _get(self.client, self.entry["base_url"], params, _bearer(self.key))
        data = self._json(resp)
        items = data.get("organic_results")
        if items is None:
            if dig(data, "search_metadata.status") == "Success":
                return [], Usage(self.estimate(q))
            self._missing(resp, "organic_results")
        return self.results(items, "title", "link", "snippet", "date"), Usage(self.estimate(q))


def sync_searchapi(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], headers=_bearer(key))
    data = _check(resp, "searchapi")
    left = dig(data, "account.remaining_credits")
    if left is None:
        raise ProviderError("searchapi", resp.status, resp.body, "searchapi: no remaining_credits")
    return {"left": float(left), "used": dig(data, "account.current_month_usage"),
            "period_start": dig(data, "subscription.period_start")}


# OpenWeb Ninja: one entry per API (decision 1.2), one key for all of them


class OpenWebNinja(Adapter):
    """The APIs of OpenWeb Ninja: ``x-api-key``, an envelope ``{status,
    request_id, data}``; ``items`` is where the results lie in it."""

    family = "G"
    items = "data"
    fields = ("title", "link", "snippet", None)

    def params(self, q):
        return {"query": q.compose()}

    def search(self, q):
        resp = _get(self.client, self.entry["base_url"], self.params(q), {"x-api-key": self.key})
        _not_subscribed(self.id, resp)
        data = self._json(resp)
        if isinstance(data, dict) and data.get("status") not in (None, "OK"):
            raise ProviderError(self.id, resp.status, resp.body)
        items = data if isinstance(data, list) else dig(data, self.items)
        if items is None and self.empty(data):
            items = []
        if not isinstance(items, list):
            self._missing(resp, self.items)
        return self.results(items, *self.fields), Usage(self.estimate(q))

    def empty(self, data):
        return False


@adapter
class OpenWebNinjaSearch(OpenWebNinja):
    id = "openwebninja_search"
    items = "data.organic_results"
    fields = ("title", "url", "snippet", None)

    def params(self, q):
        params = {"q": q.compose(), "num": min(q.max, 100)}
        if q.lang:
            params["hl"] = q.lang
        if q.country:
            params["gl"] = q.country.lower()
        return params

    def empty(self, data):
        return dig(data, "data.total_organic_results") == 0


@adapter
class OpenWebNinjaNews(OpenWebNinja):
    id = "openwebninja_news"
    fields = ("title", "link", "snippet", "published_datetime_utc")

    def params(self, q):
        params = {"query": q.compose(), "limit": min(q.max, 100)}
        if q.lang:
            params["lang"] = q.lang
        if q.country:
            params["country"] = q.country.upper()
        return params


@adapter
class OpenWebNinjaBooks(OpenWebNinja):
    """Google Books. On 2 October 2026 it answered no book at all, even for the
    query ``genealogy``: an empty answer is a failure, never "no book names it"."""

    id = "openwebninja_books"
    fields = ("title", "view_url", "subtitle", None)

    def search(self, q):
        results, usage = super().search(q)
        if not results:
            raise ProviderError(self.id, 200, b"", f"{self.id}: an empty answer is not trusted "
                                "(Google Books answered no book even for common queries)")
        return results, usage


def _not_subscribed(provider, resp):
    """An account must subscribe to each API, even to its free plan: until then
    a search answers 403 and ``/usage`` 404, saying so (seen live, 2 October 2026)."""
    if resp.status in (403, 404) and "subscri" in resp.text.lower():
        raise ProviderError(provider, resp.status, resp.body,
                            f"{provider}: not subscribed to this API; subscribe to its free plan "
                            "at https://app.openwebninja.com")


def sync_openwebninja(client, entry, environ, key):
    """``/usage`` of one API (``api_id``). A quota marked ``exceeded`` has nothing left."""
    provider = entry["id"]
    resp = _get(client, entry["introspection"]["url"], {"api_id": entry["api_id"]},
                {"x-api-key": key})
    _not_subscribed(provider, resp)
    data = _check(resp, provider)
    quota = dig(data, "data.quotas.0") or {}
    left = 0 if dig(data, "data.status") == "exceeded" else quota.get("remaining")
    if left is None:
        raise ProviderError(provider, resp.status, resp.body, f"{provider}: no quotas[].remaining")
    return {"left": float(left), "used": quota.get("used"),
            "period_start": dig(data, "data.period_start"),
            "period_end": quota.get("reset_at") or dig(data, "data.period_end")}


# Brave


def brave_left(headers):
    """The monthly value of ``X-RateLimit-Remaining: <per second>, <per month>``.

    None when the plan has no monthly cap: Brave's credit plans answer a monthly
    limit of 0 (``X-RateLimit-Limit: 50, 0``, seen live on 1 October 2026), which
    means no count to read, not an exhausted quota."""
    value = headers.get("x-ratelimit-remaining")
    if not value:
        return None
    limit = [p.strip() for p in (headers.get("x-ratelimit-limit") or "").split(",")]
    if len(limit) > 1 and limit[-1] == "0":
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) < 2:
        return None
    try:
        return float(parts[-1])
    except ValueError:
        return None


@adapter
class Brave(Adapter):
    id, family = "brave", "Br"

    def search(self, q):
        params = {"q": q.compose(), "count": min(q.max, 20)}
        if q.country:
            params["country"] = q.country.upper()
        if q.lang:
            params["search_lang"] = q.lang
        if q.date_from and q.date_to:
            params["freshness"] = f"{q.date_from}to{q.date_to}"
        resp = _get(self.client, self.entry["base_url"], params,
                    {"X-Subscription-Token": self.key, "Accept": "application/json"})
        data = self._json(resp)
        items = dig(data, "web.results")
        if items is None:
            if data.get("type") == "search":
                return [], Usage(self.estimate(q), {"left": brave_left(resp.headers)})
            self._missing(resp, "web.results")
        return (self.results(items, "title", "url", "description", "page_age"),
                Usage(self.estimate(q), {"left": brave_left(resp.headers)}))


# other keyword indexes

STAAN_MARKETS = {"fr": "fr-fr", "de": "de-de", "en": "en-gb"}


@adapter
class Staan(Adapter):
    id, family = "staan", "E"

    def search(self, q):
        params = {"q": q.compose()[:400], "market": STAAN_MARKETS.get((q.lang or "fr")[:2], "fr-fr")}
        resp = _get(self.client, self.entry["base_url"], params, _bearer(self.key))
        if resp.status == 201:
            resp.status = 200
        data = self._json(resp)
        items = dig(data, "web.results")
        if not isinstance(items, list):
            self._missing(resp, "web.results")
        return self.results(items, "title", "url", "snippet", "published_date"), Usage(self.estimate(q))


@adapter
class Marginalia(Adapter):
    id, family = "marginalia", "Ma"

    @property
    def key(self):
        env = (self.entry.get("auth") or {}).get("env")
        return self.environ.get(env) or (self.entry.get("auth") or {}).get("default", "public")

    def search(self, q):
        resp = _get(self.client, self.entry["base_url"], {"query": q.compose(), "count": min(q.max, 100)},
                    {"API-Key": self.key})
        data = self._json(resp)
        if not isinstance(data.get("results"), list):
            self._missing(resp, "results")
        left = resp.headers.get("api-remaining-daily-capacity")
        return (self.results(data["results"], "title", "url", "description"),
                Usage(self.estimate(q), {"daily_left": float(left) if left else None}))


# semantic engines


@adapter
class Exa(Adapter):
    id, family = "exa", "X"
    advanced = True

    def search(self, q):
        body = {"query": q.compose(), "type": "deep" if q.depth == "advanced" else "auto", "numResults": min(q.max, 100),
                "contents": {"highlights": True}}
        if q.country:
            body["userLocation"] = q.country.upper()
        if q.date_from:
            body["startPublishedDate"] = q.date_from
        if q.date_to:
            body["endPublishedDate"] = q.date_to
        resp = _post_json(self.client, self.entry["base_url"], body, {"x-api-key": self.key})
        data = self._json(resp)
        if not isinstance(data.get("results"), list):
            self._missing(resp, "results")
        for item in data["results"]:
            item["_snippet"] = " ".join(item.get("highlights") or []) or (item.get("text") or "")[:300]
        cost = dig(data, "costDollars.total")
        return (self.results(data["results"], "title", "url", "_snippet", "publishedDate"),
                Usage(float(cost) if cost is not None else self.estimate(q), {"costDollars": cost}))


@adapter
class Parallel(Adapter):
    id, family = "parallel", "P"
    advanced = True

    def search(self, q):
        # sent always: without it the API's mode is advanced, five times dearer
        body = {"objective": q.text, "search_queries": [q.compose()],
                "mode": "advanced" if q.depth == "advanced" else "fast",
                "advanced_settings": {"max_results": min(q.max, 20)}}
        if q.date_from:
            body["advanced_settings"]["source_policy"] = {"after_date": q.date_from}
        resp = _post_json(self.client, self.entry["base_url"], body, {"x-api-key": self.key})
        data = self._json(resp)
        if not isinstance(data.get("results"), list):
            self._missing(resp, "results")
        for item in data["results"]:
            item["_snippet"] = " ".join(item.get("excerpts") or [])[:500]
        return (self.results(data["results"], "title", "url", "_snippet", "publish_date"),
                Usage(self.estimate(q), {"usage": data.get("usage")}))

    def read(self, url, tier="read", **options):
        """A page's full text through ``/v1/extract`` (Markdown). ``full_content`` must
        sit inside ``advanced_settings`` (a top-level one is a 422); without an objective
        the excerpts add nothing. A URL Parallel could not read is in ``errors``."""
        body = {"urls": [url], "advanced_settings": {"full_content": True}}
        resp = _post_json(self.client, self.entry["extract_url"], body, {"x-api-key": self.key},
                          timeout=120)   # a live fetch takes 60 to 90 s
        data = self._json(resp)
        items = data.get("results")
        if not isinstance(items, list):
            self._missing(resp, "results")
        if not items:
            # reported as 422 like Tavily's failed URL: neither a page nor counted
            errors = data.get("errors") or []
            first = errors[0] if errors and isinstance(errors[0], dict) else {}
            # seen on 20 Oct. 2026: {"url", "error_type": "connect_error", "http_status_code": null, "content": null}
            why = first.get("error_type") or first.get("message") or first.get("error")
            if why and first.get("http_status_code"):
                why = f"{why}, HTTP {first['http_status_code']}"
            raise ProviderError(self.id, 422, resp.body,
                                f"{self.id}: the page was not read" + (f" ({why})" if why else ""))
        item = items[0]
        text = item.get("full_content") if isinstance(item, dict) else None
        if text is None and isinstance(item, dict) and item.get("excerpts"):
            text = "\n\n".join(item["excerpts"])
        if text is None:
            self._missing(resp, "full_content")
        return (Page(text, item.get("url") or url, 200, item.get("title") or ""),
                Usage(float(self.cost("read")), {"usage": data.get("usage")}))


@adapter
class GeminiGrounding(Adapter):
    """Google Search grounding: the web sources are in ``groundingMetadata``.
    Its free tier may reuse the prompts sent: never used with living persons,
    and only when providers.allow_content_reuse is true."""

    id, family = "gemini_grounding", "G"

    def search(self, q):
        prompt = (f"Genealogical research: {q.compose()}. List the online sources that mention it "
                  f"(records, indexes, trees, newspapers).")
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}]}
        resp = _post_json(self.client, self.entry["base_url"], body, {"x-goog-api-key": self.key})
        data = self._json(resp)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            self._missing(resp, "candidates")
        meta = candidates[0].get("groundingMetadata")
        if meta is None:
            return [], Usage(self.estimate(q))  # the model answered without searching
        chunks = [c.get("web") for c in meta.get("groundingChunks", []) if c.get("web")]
        return self.results(chunks, "title", "uri", "title"), Usage(self.estimate(q),
                                                                  {"queries": meta.get("webSearchQueries")})


# opaque engines


@adapter
class Tavily(Adapter):
    id, family = "tavily", "opaque"
    advanced = True

    def search(self, q):
        body = {"query": q.compose(), "max_results": min(q.max, 20),
                "search_depth": "advanced" if q.depth == "advanced" else "basic",
                "include_usage": True}
        if q.country:
            body["country"] = q.country
        if q.date_from:
            body["start_date"] = q.date_from
        if q.date_to:
            body["end_date"] = q.date_to
        resp = _post_json(self.client, self.entry["base_url"], body, _bearer(self.key))
        data = self._json(resp)
        if not isinstance(data.get("results"), list):
            self._missing(resp, "results")
        out = self.results(data["results"], "title", "url", "content", "published_date")
        units = dig(data, "usage.credits", self.estimate(q))
        return out, Usage(units, {"usage": data.get("usage")})

    def read(self, url, tier="read", **options):
        """A page's text through ``/extract`` (basic depth, Markdown): a read, not a
        structured extraction (T232). A URL Tavily could not read is an error."""
        body = {"urls": url, "extract_depth": "basic", "format": "markdown", "include_usage": True}
        resp = _post_json(self.client, self.entry["extract_url"], body, _bearer(self.key))
        data = self._json(resp)
        items = data.get("results")
        if not isinstance(items, list):
            self._missing(resp, "results")
        if not items:
            # a 200 whose URL is among failed_results: no page, and not billed. It is
            # reported as 422 (unprocessable), so that the ladder neither reads it as
            # a page nor counts it.
            failed = data.get("failed_results") or []
            why = failed[0].get("error") if failed and isinstance(failed[0], dict) else None
            raise ProviderError(self.id, 422, resp.body,
                                f"{self.id}: the page was not read" + (f" ({why})" if why else ""))
        item = items[0]
        if not isinstance(item, dict) or item.get("raw_content") is None:
            self._missing(resp, "raw_content")
        return (Page(item["raw_content"], item.get("url") or url, 200, ""),
                Usage(self._units(data, "read", 1), {"usage": data.get("usage")}))

    def _units(self, data, operation, pages):
        """What the answer reports, or the catalogue's price: Tavily bills map, crawl
        and extract by tens and fives of pages, and reports 0 until a ten is reached."""
        reported = dig(data, "usage.credits")
        if isinstance(reported, (int, float)) and reported > 0:
            return float(reported)
        return float(self.cost(operation, pages))

    def map(self, url, limit=100, search=None):
        # ``search`` is not sent as ``instructions``: those cost 2 a ten instead of 1
        body = {"url": url, "limit": limit, "max_depth": 2, "allow_external": False, "include_usage": True}
        resp = _post_json(self.client, self.entry["map_url"], body, _bearer(self.key))
        data = self._json(resp)
        urls = data.get("results")
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            self._missing(resp, "results")
        urls = urls[:limit]
        return urls, Usage(self._units(data, "map", len(urls)), {"usage": data.get("usage")})

    def crawl(self, url, limit=10, include=None, wait=60.0):
        body = {"url": url, "limit": limit, "max_depth": 2, "allow_external": False, "extract_depth": "basic",
                "format": "markdown", "include_usage": True, "timeout": max(10, min(150, int(wait)))}
        if include:
            body["select_paths"] = list(include)
        resp = _post_json(self.client, self.entry["crawl_url"], body, _bearer(self.key))
        data = self._json(resp)
        items = data.get("results")
        if not isinstance(items, list):
            self._missing(resp, "results")
        pages = [Page(item.get("raw_content") or "", item.get("url") or url, 200, "")
                 for item in items[:limit] if isinstance(item, dict) and item.get("url")]
        return pages, Usage(self._units(data, "crawl", len(pages)), {"usage": data.get("usage")})


def sync_tavily(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], headers=_bearer(key))
    data = _check(resp, "tavily")
    usage, limit = dig(data, "account.plan_usage"), dig(data, "account.plan_limit")
    if usage is None or limit is None:
        raise ProviderError("tavily", resp.status, resp.body, "tavily: no plan_usage in the answer")
    return {"left": limit - usage, "used": usage}


@adapter
class Linkup(Adapter):
    id, family = "linkup", "opaque"
    advanced = True

    def search(self, q):
        body = {"q": q.compose(), "depth": "deep" if q.depth == "advanced" else "standard", "outputType": "searchResults",
                "maxResults": q.max}
        if q.date_from:
            body["fromDate"] = q.date_from
        if q.date_to:
            body["toDate"] = q.date_to
        resp = _post_json(self.client, self.entry["base_url"], body, _bearer(self.key))
        data = self._json(resp)
        if not isinstance(data.get("results"), list):
            self._missing(resp, "results")
        return self.results(data["results"], "name", "url", "content"), Usage(self.estimate(q))


def sync_linkup(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], headers=_bearer(key))
    data = _check(resp, "linkup")
    if "balance" not in data:
        raise ProviderError("linkup", resp.status, resp.body, "linkup: no balance in the answer")
    return {"left": float(data["balance"])}


@adapter
class Jina(Adapter):
    id, family = "jina", "opaque"

    def search(self, q):
        if not self.key:
            raise ProviderError(self.id, 0, "", "jina: search needs JINA_API_KEY")
        params = {"q": q.compose(), "num": min(q.max, 20)}
        if q.country:
            params["gl"] = q.country
        if q.lang:
            params["hl"] = q.lang
        resp = _get(self.client, self.entry["search_url"], params,
                    dict(_bearer(self.key), Accept="application/json"))
        if resp.status == 422 and "No search results" in resp.text:
            return [], Usage(self.estimate(q))
        data = self._json(resp)
        if not isinstance(data.get("data"), list):
            self._missing(resp, "data")
        tokens = dig(data, "meta.usage.tokens") or resp.headers.get("x-usage-tokens")
        return (self.results(data["data"], "title", "url", "description", "date"),
                Usage(float(tokens) if tokens else self.estimate(q)))

    def read(self, url):
        headers = {"Accept": "application/json"}
        if self.key:
            headers.update(_bearer(self.key))
        resp = _get(self.client, self.entry["base_url"] + url, headers=headers)
        data = self._json(resp)
        page = data.get("data")
        if not isinstance(page, dict) or "content" not in page:
            self._missing(resp, "content")
        tokens = dig(page, "usage.tokens", self.entry["costs"]["read"])
        return (Page(page["content"], page.get("url") or url, int(page.get("httpStatus") or 200),
                     page.get("title") or ""), Usage(float(tokens)))


@adapter
class Firecrawl(Adapter):
    id, family = "firecrawl", "opaque"

    def search(self, q):
        body = {"query": q.compose(), "limit": min(q.max, 100)}
        if q.country:
            body["country"] = q.country.upper()
        resp = _post_json(self.client, self.entry["search_url"], body, _bearer(self.key))
        data = self._json(resp)
        web = dig(data, "data.web")
        if not isinstance(web, list):
            self._missing(resp, "data.web")
        units = data.get("creditsUsed", self.estimate(q))
        return self.results(web, "title", "url", "description"), Usage(float(units))

    def read(self, url):
        resp = _post_json(self.client, self.entry["base_url"],
                          {"url": url, "formats": ["markdown"], "onlyMainContent": True},
                          _bearer(self.key))
        data = self._json(resp)
        md = dig(data, "data.markdown")
        if md is None:
            self._missing(resp, "data.markdown")
        meta = dig(data, "data.metadata", {}) or {}
        return (Page(md, meta.get("sourceURL") or meta.get("url") or url,
                     int(meta.get("statusCode") or 200), meta.get("title") or ""),
                Usage(float(data.get("creditsUsed", self.entry["costs"]["read"]))))

    # map, crawl and extract (T228): docs.firecrawl.dev/api-reference, read on 14 October 2026

    now = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    POLL = 2.0

    def map(self, url, limit=100, search=None):
        body = {"url": url, "limit": limit, "sitemap": "include", "includeSubdomains": False}
        if search:
            body["search"] = search
        resp = _post_json(self.client, self.entry["map_url"], body, _bearer(self.key))
        data = self._json(resp)
        links = data.get("links")
        if data.get("success") is False or not isinstance(links, list):
            self._missing(resp, "links")
        urls = [x.get("url") if isinstance(x, dict) else x for x in links]
        urls = [u for u in urls if isinstance(u, str) and u][:limit]
        return urls, Usage(float(data.get("creditsUsed", self.cost("map"))))

    def crawl(self, url, limit=10, include=None, wait=60.0):
        """An asynchronous job: started, then its state read every ``POLL`` seconds
        until it is done or ``wait`` is spent; a job still running then is cancelled,
        and the pages it had read are kept (and counted)."""
        body = {"url": url, "limit": limit, "sitemap": "include", "allowExternalLinks": False,
                "allowSubdomains": False, "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}
        if include:
            body["includePaths"] = list(include)
        auth = _bearer(self.key)
        resp = _post_json(self.client, self.entry["crawl_url"], body, auth)
        started = self._json(resp)
        job = started.get("id")
        if not job:
            self._missing(resp, "id")
        status_url = f"{self.entry['crawl_url'].rstrip('/')}/{job}"
        deadline = self.now() + wait
        data, pages, credits = {}, [], None
        while True:
            resp = _get(self.client, status_url, headers=auth)
            data = self._json(resp)
            state = data.get("status")
            if state not in ("scraping", "completed", "failed", "cancelled"):
                self._missing(resp, "status")
            credits = data.get("creditsUsed", credits)
            if state != "scraping" or self.now() + self.POLL > deadline:
                break
            self.sleep(self.POLL)
        if data.get("status") == "scraping":
            self.client.request("DELETE", status_url, headers=auth, api=True)
        items = data.get("data")
        if not isinstance(items, list):
            self._missing(resp, "data")
        nxt = data.get("next")
        while isinstance(nxt, str) and nxt and len(items) < limit and self.now() < deadline:
            more = self._json(_get(self.client, nxt, headers=auth))
            if not isinstance(more.get("data"), list):
                break
            items += more["data"]
            nxt = more.get("next")
        for item in items[:limit]:
            meta = item.get("metadata") or {}
            if item.get("markdown") is None:
                continue
            title = meta.get("title")
            pages.append(Page(item["markdown"], meta.get("sourceURL") or meta.get("url") or url,
                              int(meta.get("statusCode") or 200),
                              " ".join(title) if isinstance(title, list) else (title or "")))
        if data.get("status") == "failed" and not pages:
            raise ProviderError(self.id, resp.status, resp.body, f"{self.id}: the crawl failed")
        units = float(credits) if credits is not None else float(self.cost("crawl", len(pages)))
        return pages, Usage(units, {"status": data.get("status"), "total": data.get("total")})

    def extract(self, url, instruction, schema=None):
        """The JSON format of ``/v2/scrape``: 1 credit for the page, 4 for the extraction."""
        fmt = {"type": "json", "prompt": instruction}
        if schema:
            fmt["schema"] = schema
        resp = _post_json(self.client, self.entry["extract_url"],
                          {"url": url, "formats": [fmt], "onlyMainContent": True}, _bearer(self.key))
        data = self._json(resp)
        found = dig(data, "data.json")
        if found is None:
            self._missing(resp, "data.json")
        return found, Usage(float(data.get("creditsUsed", self.cost("extract"))))


def sync_firecrawl(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], headers=_bearer(key))
    data = _check(resp, "firecrawl")
    left = dig(data, "data.remainingCredits")
    if left is None:
        raise ProviderError("firecrawl", resp.status, resp.body, "firecrawl: no remainingCredits")
    return {"left": float(left), "period_start": dig(data, "data.billingPeriodStart"),
            "period_end": dig(data, "data.billingPeriodEnd")}


# Unblocking readers (decision 1.1): admitted without their anti-bot options, and
# never on an archive portal (the reading ladder keeps them off those hosts).


class AntiBotRefused(ProviderError):
    """An anti-bot option asked of an unblocking reader: refused (decision 1.1)."""

    reason = "anti-bot-refused"

    def __init__(self, provider, option):
        super().__init__(provider, 0, b"", f"{provider}: {option} is an anti-bot option, never used")
        self.option = option


def _refuse(provider, options, forbidden, tier):
    if tier not in catalogue.TIERS:
        raise AntiBotRefused(provider, tier)
    for name, value in options.items():
        if name in forbidden and value not in (None, False, "false", "0"):
            raise AntiBotRefused(provider, name)


@adapter
class ZenRows(Adapter):
    """``read`` tiers: plain (1 credit), ``read_js`` (5). The premium proxy, its
    country and the adaptive stealth mode are refused. A 404 or 410 of the target
    is billed by ZenRows: it is a page, and its credits are counted."""

    id, family = "zenrows", "opaque"
    FORBIDDEN = ("premium_proxy", "proxy_country", "mode", "antibot")
    BILLED_ERRORS = (404, 410)

    def read(self, url, tier="read", **options):
        _refuse(self.id, options, self.FORBIDDEN, tier)
        params = {"apikey": self.key, "url": url, "response_type": "markdown", "original_status": "true"}
        if tier == "read_js":
            params["js_render"] = "true"
        params.update({k: v for k, v in options.items() if k in ("wait", "wait_for")})
        resp = _get(self.client, self.entry["base_url"], params)
        if resp.status not in (200,) + self.BILLED_ERRORS:
            raise ProviderError(self.id, resp.status, resp.body, retry_after=resp.headers.get("retry-after"))
        # X-Request-Credits: the credits charged (X-Request-Cost is the same in dollars)
        credits = resp.headers.get("x-request-credits")
        units = float(credits) if credits else float((self.entry.get("costs") or {}).get(tier, 1))
        final = resp.headers.get("zr-final-url") or url
        return Page(resp.text, final, resp.status, ""), Usage(units)


def sync_zenrows(client, entry, environ, key):
    """``/v1/subscriptions/self/details``: its ``usage`` is in dollars, so only a
    count in credits is read (``credit_limit`` and ``usage_credits``, otherwise the
    key's cap)."""
    resp = _get(client, entry["introspection"]["url"], headers={"X-API-Key": key})
    data = _check(resp, "zenrows")
    if data.get("credit_limit") is not None and data.get("usage_credits") is not None:
        left = data["credit_limit"] - data["usage_credits"]
    else:
        left = dig(data, "api_key.caps.0.remaining_credits")
    if left is None:
        raise ProviderError("zenrows", resp.status, resp.body, "zenrows: no count in credits")
    return {"left": float(left), "period_start": data.get("period_starts_at"),
            "period_end": data.get("period_ends_at")}


@adapter
class ScraperApi(Adapter):
    """``read`` tiers: plain (1 credit), ``read_js`` (``render=true``, 10). The
    premium and ultra-premium pools are refused. Every call carries ``max_cost``,
    the tier's credits: a protected or costly domain (a search engine costs 25) is
    refused by ScraperAPI, unbilled, instead of being paid more. A 404 is billed."""

    id, family = "scraperapi", "opaque"
    FORBIDDEN = ("premium", "ultra_premium")
    BILLED_ERRORS = (404,)

    def _params(self, url, tier, options):
        _refuse(self.id, options, self.FORBIDDEN, tier)
        params = {"api_key": self.key, "url": url}
        if tier == "read_js":
            params["render"] = "true"
        return params

    def urlcost(self, url, tier="read", **options):
        """The credits ScraperAPI would charge for the page (``/account/urlcost``),
        or None when the answer does not say."""
        resp = _get(self.client, self.entry["cost_url"], self._params(url, tier, options))
        if resp.status != 200:
            raise ProviderError(self.id, resp.status, resp.body)
        cost = resp.headers.get("sa-credit-cost")
        if cost is None:
            try:
                data = json.loads(resp.text)
            except ValueError:
                data = {}
            cost = data.get("credits", data.get("cost")) if isinstance(data, dict) else None
        return None if cost is None else float(cost)

    def read(self, url, tier="read", **options):
        params = self._params(url, tier, options)
        units = float((self.entry.get("costs") or {}).get(tier, 1))
        params.update({"output_format": "markdown", "max_cost": int(units)})
        params.update({k: v for k, v in options.items() if k in ("country_code", "wait_for_selector")})
        resp = _get(self.client, self.entry["base_url"], params)
        if resp.status not in (200,) + self.BILLED_ERRORS:
            raise ProviderError(self.id, resp.status, resp.body, retry_after=resp.headers.get("retry-after"))
        cost = resp.headers.get("sa-credit-cost")
        final = resp.headers.get("sa-final-url") or url
        return Page(resp.text, final, resp.status, ""), Usage(float(cost) if cost else units)


def sync_scraperapi(client, entry, environ, key):
    """``/account``: ``requestCount`` of ``requestLimit``. During the 7-day trial
    the limit is larger than the monthly plan: only the plan counts (decision 1.2)."""
    resp = _get(client, entry["introspection"]["url"], {"api_key": key})
    data = _check(resp, "scraperapi")
    try:
        limit, used = float(data["requestLimit"]), float(data["requestCount"])
    except (KeyError, TypeError, ValueError):
        raise ProviderError("scraperapi", resp.status, resp.body, "scraperapi: no requestCount")
    plan = (entry.get("free") or {}).get("amount", limit)
    return {"left": max(0.0, min(limit, plan) - used), "used": used,
            "period_start": data.get("lastBillingDate")}


# Apify: a whitelist of actors, each run capped, its real cost read on the run


class ActorRefused(ProviderError):
    """An actor or a proxy group outside what the catalogue allows."""

    reason = "actor-refused"

    def __init__(self, provider, what):
        super().__init__(provider, 0, b"", f"{provider}: {what} is not allowed")


APIFY_API = "https://api.apify.com/v2"
APIFY_WAIT = 60


class Apify(Adapter):
    """A run of an allowed actor: started with its ceilings (``timeout``,
    ``memory``, ``maxItems``, ``maxTotalChargeUsd``), awaited, then its dataset
    read. The units are the run's ``usageTotalUsd``. No residential proxy."""

    operation = "search"

    def actor(self, name=None):
        allowed = (self.entry.get("actors") or {}).get(self.operation) or []
        name = name or (allowed[0] if allowed else None)
        if name not in allowed:
            raise ActorRefused(self.id, f"actor {name}")
        return name

    def run(self, actor, body, max_items):
        groups = (body.get("proxyConfiguration") or {}).get("apifyProxyGroups") or []
        if any("RESIDENTIAL" in str(g).upper() for g in groups):
            raise ActorRefused(self.id, "the residential proxy")
        limits = dict(self.entry.get("limits") or {})
        params = {"waitForFinish": APIFY_WAIT, "maxItems": max_items}
        for k in ("timeout", "memory"):
            if limits.get(k):
                params[k] = limits[k]
        if limits.get("max_units") is not None:
            params["maxTotalChargeUsd"] = limits["max_units"]
        auth = _bearer(self.key)
        url = f"{APIFY_API}/acts/{actor}/runs?" + urllib.parse.urlencode(params)
        resp = _post_json(self.client, url, body, auth)
        if resp.status not in (200, 201):
            raise ProviderError(self.id, resp.status, resp.body, retry_after=resp.headers.get("retry-after"))
        data = self._json_any(resp)
        polls = 0
        while dig(data, "data.status") in ("READY", "RUNNING", "TIMING-OUT", "ABORTING") and polls < 5:
            polls += 1
            data = self._json(_get(self.client, f"{APIFY_API}/actor-runs/{dig(data, 'data.id')}",
                                   {"waitForFinish": APIFY_WAIT}, auth))
        run = data.get("data") or {}
        usage = Usage(float(run.get("usageTotalUsd") or 0.0))
        if run.get("status") != "SUCCEEDED":
            raise ProviderError(self.id, resp.status, resp.body,
                                f"{self.id}: run {run.get('status')}, cost {usage.units:g} $")
        items = self._json(_get(self.client, f"{APIFY_API}/datasets/{run.get('defaultDatasetId')}/items",
                                {"clean": "true", "format": "json"}, auth))
        if not isinstance(items, list):
            self._missing(resp, "dataset items")
        return items, usage

    def _json_any(self, resp):
        try:
            return json.loads(resp.text)
        except ValueError:
            raise ProviderError(self.id, resp.status, resp.body, f"{self.id}: the answer is not JSON")


@adapter
class ApifySearch(Apify):
    """Google results through ``apify/google-search-scraper``: one item per page."""

    id, family = "apify", "G"

    def search(self, q):
        body = {"queries": q.compose(), "maxPagesPerQuery": 1}
        if q.country:
            body["countryCode"] = q.country.lower()
        if q.lang:
            body["languageCode"] = q.lang
        items, usage = self.run(self.actor(), body, 1)
        if any("organicResults" not in item for item in items):
            raise ProviderError(self.id, 200, b"", f"{self.id}: no organicResults in the dataset")
        organic = [r for item in items for r in item["organicResults"]]
        return self.results(organic[:q.max], "title", "url", "description"), usage


@adapter
class ApifyReader(Apify):
    """A page through ``apify/rag-web-browser``, given its URL, by plain HTTP and
    without a proxy."""

    id, family, operation = "apify_reader", "opaque", "read"

    def read(self, url, tier="read", actor=None, **options):
        _refuse(self.id, options, ("proxyConfiguration",), tier)
        body = {"query": url, "maxResults": 1, "outputFormats": ["markdown"],
                "scrapingTool": "browser-playwright" if tier == "read_js" else "raw-http",
                "proxyConfiguration": {"useApifyProxy": False}}
        items, usage = self.run(self.actor(actor), body, 1)
        if not items or "markdown" not in items[0]:
            raise ProviderError(self.id, 200, b"", f"{self.id}: no markdown in the dataset")
        item = items[0]
        return (Page(item["markdown"], dig(item, "metadata.url") or url,
                     int(dig(item, "crawl.httpStatusCode") or 200), dig(item, "metadata.title") or ""),
                usage)


def sync_apify(client, entry, environ, key):
    """``/v2/users/me/limits``: the dollars used in the monthly cycle, out of the
    free plan's credit (a higher limit set on the account does not count)."""
    resp = _get(client, entry["introspection"]["url"], headers=_bearer(key))
    data = _check(resp, entry["id"])
    used = dig(data, "data.current.monthlyUsageUsd")
    limit = dig(data, "data.limits.maxMonthlyUsageUsd")
    if used is None or limit is None:
        raise ProviderError(entry["id"], resp.status, resp.body, "apify: no monthlyUsageUsd")
    plan = (entry.get("free") or {}).get("amount", limit)
    return {"left": max(0.0, min(float(limit), plan) - float(used)), "used": float(used),
            "period_start": dig(data, "data.monthlyUsageCycle.startAt")}


@adapter
class ScrapeGraph(Adapter):
    """Structured extraction (T231): ``POST /api/extract`` with the page's URL, the
    instruction (``prompt``) and a JSON schema when given; the JSON comes back in
    ``json`` (docs.scrapegraphai.com/api-reference/endpoint/extract, 14 October
    2026). The answer reports tokens, not credits: the catalogue's cost is counted.
    Its stealth option (+5 credits) is never asked for. Its free plan may reuse
    what is sent (``content_reuse``): never with a living person's name."""

    id, family = "scrapegraph", "opaque"

    def extract(self, url, instruction, schema=None):
        body = {"url": url, "prompt": instruction}
        if schema:
            body["schema"] = schema
        resp = _post_json(self.client, self.entry["base_url"], body, {"SGAI-APIKEY": self.key})
        data = self._json(resp)
        if not isinstance(data, dict) or data.get("json") is None:
            self._missing(resp, "json")
        return data["json"], Usage(float(self.cost("extract")), {"usage": data.get("usage")})


def sync_scrapegraph(client, entry, environ, key):
    """``GET /api/credits``: ``remaining`` and ``used``, at no cost (its documentation,
    14 October 2026)."""
    resp = _get(client, entry["introspection"]["url"], headers={"SGAI-APIKEY": key})
    data = _check(resp, "scrapegraph")
    if data.get("remaining") is None:
        raise ProviderError("scrapegraph", resp.status, resp.body, "scrapegraph: no remaining in the answer")
    return {"left": float(data["remaining"]), "used": data.get("used")}


def sync_openrouter(client, entry, environ, key):
    resp = _get(client, entry["introspection"]["url"], headers=_bearer(key))
    data = _check(resp, "openrouter")
    free = dig(data, "data.free_model_daily_requests")
    if isinstance(free, dict) and free.get("remaining") is not None:
        return {"left": float(free["remaining"])}
    left = dig(data, "data.limit_remaining")
    if left is None:
        raise ProviderError("openrouter", resp.status, resp.body, "openrouter: no limit_remaining")
    return {"left": float(left)}


# shared


def _check(resp, provider):
    if resp.status != 200:
        raise ProviderError(provider, resp.status, resp.body, retry_after=resp.headers.get("retry-after"))
    try:
        return json.loads(resp.text)
    except ValueError:
        raise ProviderError(provider, resp.status, resp.body, f"{provider}: the answer is not JSON")


SYNC = {"tavily": sync_tavily, "linkup": sync_linkup, "firecrawl": sync_firecrawl,
        "openrouter": sync_openrouter, "serpapi": sync_serpapi, "serper": sync_serper,
        "searchapi": sync_searchapi, "serpapi_bing": sync_serpapi, "openwebninja_search": sync_openwebninja,
        "openwebninja_news": sync_openwebninja, "openwebninja_books": sync_openwebninja, "zenrows": sync_zenrows,
        "scraperapi": sync_scraperapi, "apify": sync_apify, "apify_reader": sync_apify,
        "scrapegraph": sync_scrapegraph}


def sync(provider, client, entry, environ, ledger):
    """Reads the provider's own count and records it. None: no introspection."""
    env = (entry.get("auth") or {}).get("env")
    key = environ.get(env, "") if env else ""
    fn = SYNC.get(provider)
    if fn is None:
        return None
    info = fn(client, entry, environ, key)
    ledger.update_reported(provider, left=info.get("left"), period_start=info.get("period_start"),
                           used=info.get("used"))
    return info


def exhausted_status(provider, status, body):
    """True when an error answer means the free quota is used up."""
    text = body if isinstance(body, str) else body.decode("utf-8", "replace")
    if provider == "tavily" and status in (432, 433):
        return True
    if provider == "linkup" and status == 429 and "INSUFFICIENT_FUNDS" in text:
        return True
    if provider == "serper" and status == 400 and "credits" in text.lower():
        return True
    if provider == "gemini_grounding" and "RESOURCE_EXHAUSTED" in text:
        return True
    if provider.startswith("openwebninja_") and status in (403, 429) and "exceeded" in text.lower():
        return True
    if provider == "scraperapi" and status == 403:
        return "exhausted the api credits" in text.lower()   # not max_cost, not a block
    if provider.startswith("apify") and status == 403:
        return "platform-feature-disabled" in text or "usage hard limit" in text.lower()
    if provider in ("zenrows", "scraperapi") and status == 429:
        return False    # too many requests at once, not the quota
    if status == 402:
        return True
    return status == 429
