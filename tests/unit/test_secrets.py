"""A key passed in the URL is never written (T137): SerpApi, SerpApi Bing, ZenRows
and ScraperAPI put it in the query string. Through ``search`` and ``read``, on a
success, an HTTP 500 that echoes the request and a network error that names it,
the sentinel key is found in no file of the project, of the data folder, nor in
any output (contract, JSON, human)."""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli
from probandia.cli import reading_cmd, search_cmd
from probandia.util.http import Client, redact
from tests import ROOT
from tests.unit.test_adapters import fixture

SENTINEL = "SENTINELKEY0123456789abcdef"
PAGE = "https://families.example.org/hugo"
FORMATS = ("contract", "json", "human")


def answer(provider, name):
    fx = fixture(provider, name)
    body = fx["body"] if isinstance(fx["body"], str) else json.dumps(fx["body"])
    return fx["status"], fx.get("headers", {}), body.encode("utf-8")


class Transport:
    """``mode``: ok, 500 (the body echoes the URL asked, as some error pages do) or
    down (the error names the URL)."""

    def __init__(self, routes, mode):
        self.routes, self.mode, self.urls = routes, mode, []

    def __call__(self, method, url, headers, body, timeout):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return 200, {}, b"", url
        route = next((v for k, v in self.routes.items() if url.startswith(k)), None)
        if route is None:
            return 404, {}, b"not found", url
        if self.mode == "500":
            return 500, {"Content-Type": "text/plain"}, f"Internal error while serving {url}".encode(), url
        if self.mode == "down":
            raise OSError(f"connection reset while fetching {url}")
        return route + (url,)


class NoKeyWritten(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), self.project)
        self.outputs = []

    def env(self, **extra):
        env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "config"),
               "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "data"), "PROBANDIA_SESSION": "s",
               "SERPAPI_API_KEY": SENTINEL, "ZENROWS_API_KEY": SENTINEL, "SCRAPERAPI_API_KEY": SENTINEL}
        env.update(extra)
        return env

    def call(self, transport, env, *argv):
        def client(ctx):
            return Client(os.path.join(self.project, ".probandia"), None, ctx.config, transport,
                          sleep=lambda s: None)

        def reader(ctx, work=None, _transport=None):
            built = build(ctx, work, transport)
            built.client.sleep = lambda s: None
            return built

        build = reading_cmd.build_reader
        out = io.StringIO()
        # the archive catalogues say nothing of keys: not loaded, for speed
        with mock.patch.object(search_cmd, "_client", client), \
                mock.patch.object(reading_cmd, "build_reader", reader), \
                mock.patch.multiple("probandia.reading.ladder", archive_hosts=lambda *a: set(),
                                    forbidden_hosts=lambda *a: set(), login_sites=lambda *a: {}):
            code = cli.main(list(argv) + ["--yes"], stdout=out, environ=env, cwd=self.project,
                            stdin=io.StringIO())
        self.outputs.append(out.getvalue())
        return code, out.getvalue()

    def assert_nowhere(self):
        for output in self.outputs:
            self.assertNotIn(SENTINEL, output)
        for top, _dirs, files in os.walk(self.tmp.name):
            for name in files:
                with open(os.path.join(top, name), "rb") as fh:
                    self.assertNotIn(SENTINEL.encode(), fh.read(), os.path.join(top, name))

    def test_search(self):
        for engine, provider in (("serpapi", "serpapi"), ("serpapi_bing", "serpapi_bing")):
            for mode in ("ok", "500", "down"):
                for fmt in FORMATS:
                    transport = Transport({"https://serpapi.com/": answer(provider, "search-ok.json")}, mode)
                    self.call(transport, self.env(PROBANDIA_PROVIDERS_ENABLED=engine), "search", f"Hugo Besançon 1802 {mode} {fmt}", "--engine", engine,
                              "--output-format", fmt)
                    self.assertTrue(any(SENTINEL in u for u in transport.urls), (mode, fmt, self.outputs[-1]))
        self.assert_nowhere()

    def test_read(self):
        for provider, base in (("zenrows", "https://api.zenrows.com/"), ("scraperapi", "https://api.scraperapi.com/")):
            env = self.env(PROBANDIA_READING_LADDER="reader", PROBANDIA_PROVIDERS_ENABLED=provider)
            for mode in ("ok", "500", "down"):
                for fmt in FORMATS:
                    transport = Transport({base: answer(provider, "read-ok.json")}, mode)
                    self.call(transport, env, "read", PAGE, "--fresh", "--output-format", fmt)
                    self.assertTrue(any(SENTINEL in u for u in transport.urls), (provider, mode, fmt, self.outputs[-1]))
        self.assert_nowhere()


class Redact(unittest.TestCase):
    def test_masks_every_key_parameter(self):
        url = f"https://x.test/?q=a&api_key={SENTINEL}&apikey={SENTINEL}&key={SENTINEL}&token={SENTINEL}&u=b"
        out = redact(url)
        self.assertNotIn(SENTINEL, out)
        self.assertIn("q=a", out)
        self.assertIn("u=b", out)
        self.assertEqual(redact("plain text, api_key: none"), "plain text, api_key: none")


if __name__ == "__main__":
    unittest.main()
