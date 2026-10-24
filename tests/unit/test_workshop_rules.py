"""The rules of the workshop, checked before any push (docs/workshop-sync.md, WS3-T4)."""
import os

from tests.unit import test_workshop_mapping as base

GOOD = {"date": "27 juin 1821", "annee": 1821, "lieu": "Paris", "statut": "acte", "volet": "III", "chapitre": "I",
        "rapport": "paris-1822"}


def tearDownModule():
    base.tearDownModule()


class Rules(base.Imported):
    def setUp(self):
        super().setUp()
        from probandia.util import yamlio

        path = os.path.join(self.dir, "workshop.yaml")
        link = yamlio.load(path)
        link["researches"][self.research] = {"rapport": "paris-1822", "origine": False, "volet": "III",
                                             "chapitre": "I"}
        yamlio.dump(path, link)
        self.context = self.ctx()

    def translation(self, fact, key="deces", person="sophie-trebuchet-1772", missing=None, research=True):
        from probandia.workshop.prototype.mapping import Translation

        t = Translation(f"{person}.x", person, key, None, fact, missing)
        t.research = self.context.link["researches"][self.research] if research else {}
        return t

    def blocked(self, t, adding=()):
        from probandia.workshop.prototype.rules import check

        return check(t, self.context, adding)

    def test_a_good_fact_goes(self):
        self.assertEqual(self.blocked(self.translation(dict(GOOD))), [])

    def test_each_rule_blocks_its_fact_alone(self):
        cases = [
            ("three-markers", {k: v for k, v in GOOD.items() if k != "chapitre"}, {}, "rule of the three markers"),
            ("three-markers", dict(GOOD, statut="certain"), {}, "acte, index, hypothese, refute"),
            ("roman", dict(GOOD, volet="3"), {}, "Roman numerals"),
            ("chapter", dict(GOOD, chapitre="IX"), {}, "written in order"),
            ("provenance", dict(GOOD, rapport="elsewhere"), {}, "its folder of rapports/"),
            ("provenance", dict(GOOD), {"research": False}, "workshop link"),
            ("refutation", dict(GOOD, statut="refute"), {}, "volet_refute"),
            ("image", dict(GOOD), {"missing": "ec-1821-9.jpg"}, "sources/"),
            ("id", dict(GOOD), {"person": "Sophie_T"}, "not an id of the workshop"),
            ("links", {"epoux": "victor-hugo-1802", "epouse": "adele-foucher-1803", **GOOD}, {"key": "unions"},
             "nor one this push adds"),
        ]
        for rule, fact, options, words in cases:
            with self.subTest(rule=rule, words=words):
                good = self.blocked(self.translation(dict(GOOD)))
                got = self.blocked(self.translation(fact, **options))
                self.assertEqual(good, [])
                self.assertEqual([r for r, _ in got], [rule])
                self.assertIn(words, got[0][1])

    def test_a_person_added_by_the_same_push_is_known(self):
        union = {"epoux": "victor-hugo-1802", "epouse": "adele-foucher-1803", **GOOD}
        self.assertEqual(self.blocked(self.translation(union, key="unions"), adding={"adele-foucher-1803"}), [])

    def test_the_next_chapter_is_known(self):
        # paris-1822 has no chapter yet: I is its next one, II is not
        self.assertEqual([r for r, _ in self.blocked(self.translation(dict(GOOD, chapitre="II")))], ["chapter"])
        origin = {"rapport": "hugo-besancon", "origine": True, "volet": "III", "chapitre": "III"}
        t = self.translation({k: v for k, v in GOOD.items() if k != "rapport"} | {"chapitre": "III"})
        t.research = origin   # its rapport.html and its facts go to II
        self.assertEqual(self.blocked(t), [])
        t.fact["chapitre"] = "IV"
        self.assertEqual([r for r, _ in self.blocked(t)], ["chapter"])
