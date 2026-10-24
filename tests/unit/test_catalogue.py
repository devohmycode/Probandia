"""The free-tier catalogue: the kinds of its entries, and what ``usable`` gives for each."""
import os
import tempfile
import unittest

from probandia.config import registry
from probandia.ledger import Ledger
from probandia.providers import accounts, adapters, catalogue
from tests import ROOT


class Config:
    def __init__(self, **values):
        self.values = {"providers.enabled": list(registry.PROVIDERS), "providers.allow_card_required": False,
                       "providers.allow_content_reuse": False}
        self.values.update({k.replace("__", "."): v for k, v in values.items()})

    def get(self, key):
        if key in self.values:
            return self.values[key]
        raise KeyError(key)


class Kinds(unittest.TestCase):
    def setUp(self):
        self.cat = catalogue.load()

    def test_every_entry_has_a_known_kind(self):
        for pid, entry in self.cat.items():
            with self.subTest(provider=pid):
                self.assertIn(entry.get("kind"), catalogue.KINDS)

    def test_every_entry_may_be_enabled(self):
        self.assertEqual(set(self.cat), set(registry.PROVIDERS))

    def test_scrapegraph_is_an_extract_entry(self):
        e = self.cat["scrapegraph"]
        self.assertEqual(e["kind"], "extract")
        self.assertGreater((e.get("free") or {}).get("amount", 0), 0)
        self.assertGreater((e.get("costs") or {}).get("extract", 0), 0)
        self.assertTrue(e.get("source_url", "").startswith("https://"))
        self.assertEqual(catalogue.key_env(e), "SGAI_API_KEY")
        with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as fh:
            self.assertIn("SGAI_API_KEY=", fh.read())
        env = {"SGAI_API_KEY": "test-key"}
        cfg = Config(providers__allow_content_reuse=True)   # its free plan may reuse what is sent
        for kind in ("search", "read"):
            self.assertNotIn("scrapegraph", catalogue.usable(cfg, env, kind))
        self.assertEqual(catalogue.usable(cfg, env, "extract"), ["scrapegraph"])
        self.assertEqual(catalogue.usable(cfg, {}, "extract"), [])   # no key
        # its free plan may train on the pages sent: off until the user allows it
        self.assertEqual(catalogue.usable(Config(), env, "extract"), [])
        self.assertEqual(catalogue.why_unusable(e, Config(), env), "content-reuse")
        # shown with the readers, never among the searches
        self.assertEqual(accounts.role(e), "read")

    def test_scrapegraph_balance(self):
        from tests.unit.test_adapters import ENV, client, fixture

        tmp = tempfile.mkdtemp()
        fx = fixture("scrapegraph", "credits.json")
        c = client(fx, tmp)
        info = adapters.sync("scrapegraph", c, self.cat["scrapegraph"], dict(ENV, SGAI_API_KEY="k"),
                             Ledger(tmp, self.cat))
        self.assertEqual((info["left"], info["used"]), (485.0, 15))
        method, url, headers, _body = c.transport.sent[0]
        self.assertEqual((method, url), ("GET", "https://v2-api.scrapegraphai.com/api/credits"))
        self.assertEqual(headers.get("SGAI-APIKEY"), "k")


if __name__ == "__main__":
    unittest.main()
