import datetime
import tempfile
import unittest

from probandia import config
from probandia.ledger import Ledger
from probandia.project import create_project
from probandia.providers import accounts, catalogue

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)
KEYS = {"SERPAPI_API_KEY": "k", "OPENWEBNINJA_API_KEY": "k", "APIFY_TOKEN": "k", "EXA_API_KEY": "k"}


class Accounts(unittest.TestCase):
    """One record per free-tier account (cli.md § 4.2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        create_project(self.tmp.name)
        self.env = dict(KEYS, PROBANDIA_CONFIG_DIR=self.tmp.name + "/u")
        self.cat = catalogue.load()
        self.ledger = Ledger(self.tmp.name, self.cat, clock=lambda: NOW)
        self.cfg = config.load(self.tmp.name, self.env)

    def by_id(self):
        return {a["account"]: a for a in accounts.accounts(self.cat, self.ledger, self.cfg, self.env, 10)}

    def test_shared_pools_appear_once(self):
        found = self.by_id()
        self.assertNotIn("apify_reader", found)
        self.assertNotIn("serpapi_bing", found)
        apify = found["apify"]
        self.assertEqual(apify["entries"], ["apify", "apify_reader"])
        self.assertEqual(set(apify["pays"]), {"search", "read"})
        self.assertEqual(apify["section"], "last-resort")
        # OpenWeb Ninja's APIs have quotas of their own
        self.assertIn("openwebninja_news", found)

    def test_out_of_service_entries(self):
        serpapi = self.by_id()["serpapi"]
        self.assertEqual(serpapi["state"], "ready")
        self.assertEqual(serpapi["out"], {"serpapi_bing": "not-enabled"})
        self.assertEqual(self.by_id()["staan"]["state"], "no-key")

    def test_units(self):
        found = self.by_id()
        self.ledger.record("exa", "search", 0.42)
        exa = self.by_id()["exa"]
        self.assertEqual(exa["unit"], "dollar")
        self.assertAlmostEqual(exa["left"], 8.58)
        self.assertEqual(found["jina"]["pays"]["read"], 3000)
        self.assertIsNone(found["marginalia"]["left"])
        self.assertIsNone(found["marginalia"]["pays"]["search"])

    def test_renewal(self):
        found = self.by_id()
        self.assertEqual(found["serpapi"]["renewal"]["kind"], "reset")
        self.assertEqual(found["serper"]["renewal"], {"kind": "first-use", "at": None, "months": 6})
        self.assertEqual(found["jina"]["renewal"]["kind"], "never")

    def test_families(self):
        usable, missing = accounts.families(self.cat, self.ledger, self.cfg, self.env, 10)
        self.assertEqual(usable, ["G", "Ma"])
        self.assertIn("Br", missing)
        self.assertEqual(missing["Br"], [("brave", "card-required")])


if __name__ == "__main__":
    unittest.main()
