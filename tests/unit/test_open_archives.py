"""Optimize 6.19: public API and browser-only sources; no live HTTP."""
import unittest

from probandia import archives
from probandia.archives.finder import find, load_catalogue
from probandia.errors import UsageError
from probandia.reading.ladder import forbidden_hosts
from tests.unit.test_archives import Base
from tests import ROOT


class DDB(Base):
    def run_search(self, overrides=None, **args):
        return archives.run(archives.load("ddb"), "search", {"query": "Goethe", **args},
                            self.context("ddb", overrides))

    def test_public_search_preserves_identifiers_and_rights(self):
        result = self.run_search(max=1)
        self.assertEqual(result.status, "ok")
        self.assertGreater(result.count, 0)
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row["title"], "Goethe")
        self.assertTrue(row["url"].endswith(row["id"]))
        self.assertTrue(row["rights"])
        self.assertNotIn("api_key", result.url)

    def test_invalid_answer_is_failure_not_negative(self):
        for body in ({}, {"response": {"numFound": 0}},
                     {"response": {"numFound": 1, "docs": [{}]}},
                     {"response": {"numFound": -1, "docs": []}}, []):
            with self.subTest(body=body):
                result = self.run_search({"*": {"status": 200, "body": body}})
                self.assertEqual(result.status, "failed")

    def test_inconsistent_or_inexact_zero_cannot_support_negative(self):
        for body in ({"response": {"numFound": 0, "docs": [{"id": "x"}]}},
                     {"response": {"numFound": 0, "docs": [], "numFoundExact": False}},
                     {"responseHeader": {"status": 1},
                      "response": {"numFound": 0, "docs": []}}):
            self.assertEqual(self.run_search({"*": {"status": 200, "body": body}}).status,
                             "failed")

    def test_zero_results_is_success(self):
        result = self.run_search({"*": {"status": 200,
                                  "body": {"response": {"numFound": 0, "docs": []}}}})
        self.assertEqual((result.status, result.n), ("ok", 0))

    def test_http_and_non_json_errors(self):
        for status, body in ((403, "denied"), (200, "<html>challenge</html>")):
            result = self.run_search({"*": {"status": status, "body": body}})
            self.assertEqual(result.status, "failed")

    def test_bounded_requests(self):
        for args in ({"max": 0}, {"max": 101}, {"offset": -1}, {"query": " "}):
            with self.subTest(args=args), self.assertRaises(UsageError):
                self.run_search(**args)


class BrowserSources(unittest.TestCase):
    IDS = ("matricula", "delpher", "memoiredeshommes", "leonore", "arolsen", "arch_be")

    def test_sources_are_discoverable_and_protected(self):
        cat = load_catalogue()
        _, browser = find("", limit=100)
        ids = {entry["id"] for entry in browser}
        protected = forbidden_hosts(None, ROOT)
        for archive in self.IDS:
            with self.subTest(archive=archive):
                entry = cat[archive]
                self.assertIn(archive, ids)
                self.assertEqual(entry["access"]["mode"], "browser")
                self.assertNotIn("connector", entry["access"])
                self.assertEqual(entry["access"]["third_party"], "forbidden")
                self.assertTrue(set(entry["access"]["hosts"]) <= set(protected))
                self.assertIn("https://", entry["terms"])
                self.assertGreaterEqual(entry["state"]["checked"], "2026-10-05")   # a later re-reading counts

    def test_belgian_images_require_user_login(self):
        self.assertTrue(load_catalogue()["arch_be"]["login"]["required"])

    def test_named_archive_is_visible_in_three_browser_suggestions(self):
        for name, expected in (("Matricula", "matricula"), ("Delpher", "delpher"),
                               ("Léonore", "leonore"), ("Arolsen", "arolsen"),
                               ("Mémoire des hommes", "memoiredeshommes"), ("AGATHA", "arch_be")):
            with self.subTest(name=name):
                _, browser = find(name)
                self.assertEqual(browser[0]["id"], expected)

    def test_named_archive_survives_record_type_filter(self):
        for need, expected in (("Léonore acte France", "leonore"),
                               ("Arolsen décès Allemagne", "arolsen")):
            with self.subTest(need=need):
                _, browser = find(need)
                self.assertEqual(browser[0]["id"], expected)
