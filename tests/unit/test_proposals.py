"""T120: the validation of the proposals an import writes, from the note of GPS6 (4 Oct. 2026):
every proposal is checked, the first included, and none is written when one is refused."""
import os
import unittest
from unittest import mock

from probandia import gedcom_import
from tests.unit.test_trees_exports import GED, RID, Project


class ImportedProposals(Project):
    def test_the_first_invalid_proposal_is_refused_by_name(self):
        self.refused(0)

    def test_a_later_one_refused_leaves_the_first_unwritten(self):
        self.refused(-1)

    def refused(self, which):
        real = gedcom_import.Import.proposals

        def first_broken(imp, *args, **kwargs):
            found = real(imp, *args, **kwargs)
            self.assertGreater(len(found), 1)
            found[which][0]["facts"][0]["status"] = "certain"   # not a status of the schema
            self.first = found[which]
            return found

        with mock.patch.object(gedcom_import.Import, "proposals", first_broken):
            code, out = self.call("import-gedcom", os.path.join(GED, "oldtree-551-ansel.ged"))
        self.assertEqual(code, 1, out)   # REASON=schema
        doc, why = self.first
        self.assertIn(f"proposal {doc['id']} ({', '.join(why)})", out)
        self.assertIn("$.facts[0].status", out)
        folder = os.path.join(self.family, "research", RID, "work", "proposals")
        self.assertEqual(os.listdir(folder) if os.path.isdir(folder) else [], [])   # not one of them written


if __name__ == "__main__":
    unittest.main()
