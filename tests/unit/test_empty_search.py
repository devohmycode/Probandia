"""A search that finds nothing proves nothing: it is logged as ``empty``, never as a
negative (seen in the review of optimize 2.14: V-3 failed on it)."""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli
from probandia.cli import search_cmd
from probandia.indexes import FamilyIndexes
from probandia.util.http import Client
from tests import REUSE, ROOT
from tests.unit.test_adapters import fixture

RESEARCH = "2026-09-01-ancestors-of-louis-marchand"


class EmptySearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"), **REUSE, "TAVILY_API_KEY": "k",
                    "CLAUDECODE": "1", "PROBANDIA_SESSION": "s"}
        self.call("resume", RESEARCH, "--mode", "session")

    def call(self, *argv):
        def transport(method, url, headers, body, timeout):
            if url.startswith("https://api.tavily.com/search"):
                fx = fixture("tavily", "search-empty.json")
                return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url
            return 404, {}, b"", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        out = io.StringIO()
        with mock.patch.object(search_cmd, "_client", make_client):
            code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.dir, stdin=io.StringIO())
        return code, out.getvalue()

    def test_the_first_salvo_is_native(self):
        # the engine's search spends a provider's quota: it waits for the pass's first native search
        code, out = self.call("search", "PERRYN Les Ormes", "--engine", "tavily", "--research", RESEARCH)
        self.assertEqual(code, 0, out)
        self.assertIn("REASON=native-first", out)
        self.assertFalse([s for s in FamilyIndexes(self.dir, "marchand").items("searches")
                          if s["query"].startswith("PERRYN")])
        code, out = self.call("search", "PERRYN Les Ormes", "--negative", "--research", RESEARCH)
        self.assertNotEqual(code, 2, out)
        self.assertNotIn("native-first", out)   # a negative needs the providers' index families

    def test_logged_as_empty_and_verify_passes(self):
        self.call("search", "--log-native", "--query", "Perrin Les Ormes", "--results", "0", "--research", RESEARCH)
        code, out = self.call("search", "PERRYN Les Ormes", "--engine", "tavily", "--research", RESEARCH)
        self.assertEqual(code, 0, out)
        logged = [s for s in FamilyIndexes(self.dir, "marchand").items("searches") if s["query"].startswith("PERRYN")]
        self.assertEqual([s["result"] for s in logged], ["empty"])
        code, out = self.call("verify", RESEARCH, "--rule", "V-3")
        self.assertIn("- V-3=PASS", out)
        code, out = self.call("known", RESEARCH)
        self.assertIn("NEGATIVES=1\n", out)      # the sample's one negative, not this search


if __name__ == "__main__":
    unittest.main()
