import copy
import os
import unittest

from probandia.errors import SchemaError
from probandia.proof import source_types
from probandia.util import yamlio
from tests import ROOT

FRANCE = ("parish_registers", "civil_registers", "decennial_tables", "census", "notarial",
          "military_registers", "registration", "press")


class Catalogue(unittest.TestCase):
    def setUp(self):
        self.doc = source_types.load()

    def test_france_is_complete(self):
        types = source_types.by_id(self.doc)
        self.assertEqual(set(FRANCE) - set(types), set())
        for tid in FRANCE:
            self.assertIsNotNone(source_types.rule(types[tid], "FR"), tid)

    def test_every_rule_and_exception_cites_its_references(self):
        for t in self.doc["types"]:
            for rule in t["rules"]:
                self.assertTrue(all(r["title"].strip() for r in rule["references"]), t["id"])
                for x in rule.get("exceptions") or []:
                    self.assertTrue(x["references"], (t["id"], x["places"]))

    def test_the_coverage_types_are_those_of_the_archives(self):
        archives = yamlio.load(os.path.join(ROOT, "catalogues", "archives.yaml"))["archives"]
        known = {c for a in archives for c in a["coverage"]["types"]}
        new = {c for t in self.doc["types"] for c in t["coverage"]} - known
        # these records have no archive of the catalogue yet: a guide's repositories can hold them
        self.assertEqual(new, {"decennial_table", "succession"})

    def test_savoy_and_paris(self):
        civil = source_types.rule(source_types.by_id(self.doc)["civil_registers"], "FR")
        effects = {x["effect"]: x for x in civil["exceptions"]}
        self.assertEqual(effects["replaced"]["by"], "parish_registers")
        self.assertEqual(effects["replaced"]["places"], ["FR-73", "FR-74"])
        self.assertEqual((effects["destroyed"]["from"], effects["destroyed"]["to"]), (1792, 1859))


class Checks(unittest.TestCase):
    def setUp(self):
        self.doc = yamlio.load(os.path.join(ROOT, "tests", "fixtures", "source-types", "valid", "minimal.yaml"))

    def paths(self, doc):
        with self.assertRaises(SchemaError) as cm:
            source_types.check(doc)
        return [i.path for i in cm.exception.errors]

    def test_the_fixture_passes(self):
        self.assertIs(source_types.check(self.doc), self.doc)

    def test_duplicate_id(self):
        doc = copy.deepcopy(self.doc)
        doc["types"][1]["id"] = "civil_registers"
        self.assertIn("$.types[1].id", self.paths(doc))

    def test_replaced_needs_a_known_type(self):
        doc = copy.deepcopy(self.doc)
        x = doc["types"][0]["rules"][0]["exceptions"][0]
        x["by"] = "baptisms"
        self.assertEqual(self.paths(doc), ["$.types[0].rules[0].exceptions[0].by"])
        del x["by"]
        self.assertEqual(self.paths(doc), ["$.types[0].rules[0].exceptions[0].by"])
        x["effect"], x["by"] = "destroyed", "parish_registers"
        self.assertEqual(self.paths(doc), ["$.types[0].rules[0].exceptions[0].by"])

    def test_years_in_order_and_places_in_the_country(self):
        doc = copy.deepcopy(self.doc)
        doc["types"][1]["rules"][0]["to"] = 1500
        x = doc["types"][0]["rules"][0]["exceptions"][0]
        x["places"] = ["DE-BY"]
        self.assertEqual(self.paths(doc), ["$.types[0].rules[0].exceptions[0].places", "$.types[1].rules[0].to"])
