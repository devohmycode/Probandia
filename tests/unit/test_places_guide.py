"""Locality guides: jurisdictions, repositories, the places guide command, the report (GPS2)."""
import os
import unittest

from probandia.util import yamlio
from probandia.util.schema import validate_document
from tests import ROOT
from tests.unit.test_data_layer import RID, Project

FIX = os.path.join(ROOT, "tests", "fixtures")


def guided_place():
    return yamlio.load(os.path.join(FIX, "places", "valid", "guide.yaml"))["places"][0]


class Format(Project):
    """GPS2-T1: places.yaml takes jurisdictions, repositories and a guide; older files stay valid."""

    def test_older_places_files_stay_valid(self):
        for path in (os.path.join(FIX, "places", "valid", "fixture-family.yaml"),
                     os.path.join(self.family, "index", "places.yaml")):
            if os.path.exists(path):
                validate_document("places", yamlio.load(path), path)

    def test_a_guided_place_goes_through_apply(self):
        place = guided_place()
        (code, out), _doc = self.propose_and_apply(places=[place])
        self.assertEqual(code, 0, out)
        written = {p["id"]: p for p in self.index("places")["places"]}["auxon-dessous"]
        self.assertEqual([(j["level"], j["name"]) for j in written["jurisdictions"]][:3],
                         [("parish", "Auxon-Dessous"), ("commune", "Auxon-Dessous"), ("commune", "Les Auxons")])
        self.assertEqual(written["repositories"][0]["archive"], "ad25")
        self.assertEqual(written["guide"]["built"], "2026-10-04")


def summary(jurisdictions, level=None):
    return [(j["level"], j["name"], j["from"], j["to"]) for j in jurisdictions if level in (None, j["level"])]


class CommuneHistory(unittest.TestCase):
    """GPS2-T2: the INSEE COG gives a commune's mergers, new names and departments, with their dates.
    The rows of tests/fixtures/cog are copied from the 2024 COG files."""

    @classmethod
    def setUpClass(cls):
        from probandia.lang.places import Cog

        cls.cog = Cog(os.path.join(FIX, "cog"))

    def test_merged_auxon_dessous(self):
        h = self.cog.history("25034")
        self.assertEqual(summary(h, "commune"), [("commune", "Auxon-Dessous", None, "2014-12-31"),
                                                 ("commune", "Les Auxons", "2015-01-01", None)])
        self.assertEqual(summary(h, "department"), [("department", "Doubs", None, None)])
        self.assertEqual(summary(h, "canton"), [("canton", "Besançon-3", "2015-03-22", None)])
        self.assertTrue(all(j["source"] == "insee-cog" for j in h))
        self.assertEqual(h[0]["note"], "INSEE 25034")

    def test_renamed_saint_mandrier(self):
        """Saint-Mandrier was cut out of La Seyne-sur-Mer in 1950, and renamed Saint-Mandrier-sur-Mer in 1951."""
        self.assertEqual(summary(self.cog.history("83153"), "commune"),
                         [("commune", "La Seyne-sur-Mer", None, "1950-04-23"),
                          ("commune", "Saint-Mandrier", "1950-04-24", "1951-04-18"),
                          ("commune", "Saint-Mandrier-sur-Mer", "1951-04-19", None)])

    def test_stable_besancon(self):
        h = self.cog.history("25056")
        self.assertEqual(summary(h, "commune"), [("commune", "Besançon", None, None)])
        self.assertEqual(summary(h, "arrondissement"), [("arrondissement", "Besançon", None, None)])

    def test_two_mergers_in_a_row(self):
        self.assertEqual(summary(self.cog.history("50383"), "commune"),
                         [("commune", "Octeville", None, "2000-02-27"),
                          ("commune", "Cherbourg-Octeville", "2000-02-28", "2015-12-31"),
                          ("commune", "Cherbourg-en-Cotentin", "2016-01-01", None)])

    def test_department_names_and_codes(self):
        from probandia.lang.places import _department_names

        self.assertEqual(_department_names("22", "Côtes-d'Armor", None, None),
                         [("Côtes-du-Nord", None, "1990-02-26"), ("Côtes-d'Armor", "1990-02-27", None)])
        self.assertEqual(_department_names("78", "Yvelines", None, "1967-12-31"),
                         [("Seine-et-Oise", None, "1967-12-31")])
        self.assertEqual(_department_names("25", "Doubs", "2015-01-01", None), [("Doubs", "2015-01-01", None)])

    def test_an_unknown_code(self):
        self.assertEqual(self.cog.history("99999"), [])

    def test_the_connector(self):
        import shutil
        import tempfile
        import types

        from probandia.archives import insee_cog

        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(os.path.join(FIX, "cog"), os.path.join(tmp, "insee"))
            rows = insee_cog.run("history", {"code": "25034"}, types.SimpleNamespace(data_dir=tmp, environ={})).rows
        self.assertEqual([r["title"] for r in rows][:2], ["commune Auxon-Dessous", "commune Les Auxons"])

    def test_without_the_canton_files(self):
        """An installation with only the two files of before still reads the history."""
        import shutil
        import tempfile

        from probandia.lang.places import Cog

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("v_commune_2024.csv", "v_mvt_commune_2024.csv"):
                shutil.copy(os.path.join(FIX, "cog", name), tmp)
            h = Cog.load(tmp).history("25034")
        self.assertEqual([j["level"] for j in h], ["commune", "commune", "department"])


class Recorded:
    """Recorded answers of GOV (trimmed pages) and Wikidata, under tests/fixtures/http/places/guide."""

    FOLDER = os.path.join(FIX, "http", "places", "guide")

    def __init__(self):
        self.calls = []

    def get(self, url, params):
        import re

        if "gov.genealogy.net" in url:
            name = f"gov-{url.rsplit('/', 1)[-1]}.html"
        else:
            name = "wikidata-" + re.sub(r"[^A-Za-z0-9]+", "-", params.get("ids") or params.get("srsearch")).strip("-") \
                + ".json"
        self.calls.append(name)
        path = os.path.join(self.FOLDER, name)
        if not os.path.exists(path):
            raise OSError(f"no recorded answer {name}")
        with open(path, encoding="utf-8") as fh:
            return fh.read()


class Jurisdictions(unittest.TestCase):
    """GPS2-T3: parish and diocese for a German place (GOV) and a French one (rule of 1790 and
    catalogue, GPS-D9), and the old cantons of Wikidata; all on recorded answers."""

    def test_german_place_through_its_church(self):
        from probandia.lang.jurisdictions import gov_jurisdictions

        found, notes = gov_jurisdictions("MORORF_W5449", Recorded(), name="Mörsdorf")
        self.assertEqual(notes, [])
        church = [(j["level"], j["name"]) for j in found if j["level"] in ("parish", "parish-group", "deanery", "diocese")]
        self.assertEqual(church, [("parish", "Mörsdorf (St. Kastor)"), ("parish-group", "PG Treis-Karden"),
                                  ("deanery", "Cochem-Zell"), ("diocese", "Trier")])
        self.assertIn(("municipality", "Treis", "1816", "1932"), summary(found))
        self.assertIn(("canton", "Castellaun", "1798", "1814"), summary(found))
        self.assertIn(("district", "Cochem-Zell", "1969", "2014-06-30"), summary(found))   # clipped to its Amt
        self.assertTrue(all(j["source"].startswith("gov:") for j in found))

    def test_french_place_by_rule_and_catalogue(self):
        from probandia.lang.jurisdictions import french_church
        from probandia.lang.places import Cog

        church = french_church(Cog(os.path.join(FIX, "cog")).history("25034"))
        self.assertEqual(summary(church), [("parish", "Auxon-Dessous", None, "1790"), ("diocese", "Besançon", "1802", None)])
        self.assertTrue(all(j["derived"] for j in church))
        self.assertEqual([j["source"] for j in church], ["rule:parish-1790", "catalogue:dioceses-fr"])

    def test_a_commune_created_later_follows_its_parish(self):
        from probandia.lang.jurisdictions import french_church
        from probandia.lang.places import Cog

        church = french_church(Cog(os.path.join(FIX, "cog")).history("83153"))
        self.assertEqual(church[0]["name"], "La Seyne-sur-Mer")

    def test_a_department_outside_the_catalogue(self):
        from probandia.lang.jurisdictions import french_church

        history = [{"level": "commune", "name": "Beaulieu", "from": None, "to": None},
                   {"level": "department", "name": "Cantal", "from": None, "to": None, "note": "department 15"}]
        church = french_church(history)
        self.assertEqual([j["level"] for j in church], ["parish"])
        self.assertIn("not in catalogues/dioceses-fr.yaml", church[0]["note"])

    def test_old_canton_from_wikidata(self):
        from probandia.lang.jurisdictions import wikidata_jurisdictions

        found, notes = wikidata_jurisdictions(Recorded(), insee="25034")
        self.assertEqual(notes, [])
        self.assertEqual(summary(found), [("canton", "Audeux", None, "2015-03-21")])
        self.assertEqual(found[0]["source"], "wikidata:Q1475879")

    def test_gov_periods(self):
        from probandia.lang.jurisdictions import _period

        self.assertEqual(_period("(1972 -)"), ("1972", None))
        self.assertEqual(_period("(- 1934-05-31)"), (None, "1934-05-31"))
        self.assertEqual(_period("(1798 - 1834)"), ("1798", "1834"))
        self.assertEqual(_period(""), (None, None))
        self.assertEqual(_period("(um 1800 -)"), (None, None))

    def test_a_challenge_or_a_missing_page_is_said(self):
        from probandia.lang.jurisdictions import gov_jurisdictions

        class Challenge:
            def get(self, url, params):
                return "<html><title>Making sure you're not a bot!</title><script id=anubis_version></script></html>"

        found, notes = gov_jurisdictions("MORORF_W5449", Challenge())
        self.assertEqual((found, notes), ([], ["gov: challenge page"]))
        found, notes = gov_jurisdictions("XXXXXX", Recorded())
        self.assertEqual(found, [])
        self.assertEqual(notes, ["gov: failed (OSError)"])

    def test_the_page_budget(self):
        from probandia.lang.jurisdictions import gov_jurisdictions

        found, notes = gov_jurisdictions("MORORF_W5449", Recorded(), name="Mörsdorf", budget=3)
        self.assertIn("gov: page budget spent", notes)
        full, _notes = gov_jurisdictions("MORORF_W5449", Recorded(), name="Mörsdorf")
        self.assertLess(len(found), len(full))


class Repositories(unittest.TestCase):
    """GPS2-T4: the archives that keep a place's records, from the catalogue and by department."""

    def test_doubs(self):
        from probandia.archives.repositories import repositories

        found = repositories(["FR-25", "FR"], (1700, 1900), departments=[("25", "Doubs")])
        self.assertEqual([r["archive"] for r in found],
                         ["ad25", "europeana", "familysearch", "gallica", "hathitrust", "leonore",
                          "memoiredeshommes", "persee", "socface"])   # FL3: persee and hathitrust hold French periodicals
        ad = found[0]
        self.assertEqual(ad["name"], "Archives départementales du Doubs")
        self.assertIn({"type": "baptism", "years": [1700, 1900]}, ad["holdings"])
        self.assertNotIn("matchid", [r["archive"] for r in found])   # deaths since 1970 only
        self.assertEqual({"type": "census", "years": [1836, 1900]},
                         {r["archive"]: r for r in found}["socface"]["holdings"][0])

    def test_where_to_look_first(self):
        # token-economy A3: after 1792 the decennial tables, then the register of the year; before, the parishes
        from probandia.archives.repositories import repositories

        ad50 = repositories(["FR-50", "FR"], (1870, 1880), departments=[("50", "Manche")])[0]
        self.assertEqual((ad50["archive"], ad50["url"]), ("ad50", "https://www.archives-manche.fr/"))
        self.assertTrue(ad50["note"].startswith("decennial tables of the commune first"))
        self.assertNotIn("parish", ad50["note"])
        early = repositories(["FR-50", "FR"], (1700, 1720), departments=[("50", "Manche")])[0]
        self.assertTrue(early["note"].startswith("before 1793, the parish registers"))
        # without the COG files, the gazetteer's label gives the department (the bench's "country not known")
        from probandia.lang import guide as G

        place = {"id": "valognes", "names_as_written": ["Valognes"], "current_name": "Valognes"}
        built, _notes = G.build(place, None, None, (1870, 1880),
                                context="Valognes, Cherbourg, Manche, Normandie, "
                                        "France métropolitaine, 50700, France")
        self.assertEqual((built["repositories"][0]["archive"], built["repositories"][0]["url"]),
                         ("ad50", "https://www.archives-manche.fr/"))
        # T261: the department is kept in the jurisdictions, where the matrix reads the country
        from probandia.proof import matrix

        self.assertEqual(matrix.regions(built), ["FR-50", "FR"])
        abroad, _notes = G.build({"id": "x", "names_as_written": ["X"], "current_name": "X"}, None, None,
                                 (1870, 1880), context="Vianden, Luxembourg")
        self.assertEqual(matrix.regions(abroad), ["LU"])

    def test_types_asked(self):
        from probandia.archives.repositories import repositories

        found = repositories(["FR-25", "FR"], (1880, 1990), types={"death"}, departments=[("25", "Doubs")])
        self.assertEqual([r["archive"] for r in found],
                         ["ad25", "familysearch", "matchid", "memoiredeshommes"])   # C5: Open Archives, not in France
        self.assertEqual({r["archive"]: r for r in found}["matchid"]["holdings"], [{"type": "death", "years": [1970, 1990]}])

    def test_a_department_without_a_catalogue_entry(self):
        from unittest import mock

        from probandia.archives import finder
        from probandia.archives.repositories import repositories

        found = repositories(["FR-15", "FR"], None, departments=[("15", "Cantal")])   # A2: every one has its entry
        self.assertEqual((found[0]["name"], found[0]["archive"]), ("Archives départementales du Cantal", "ad15"))
        with mock.patch.object(finder, "CATALOGUES", ("archives.yaml",)):   # an entry missing: the rule
            found = repositories(["FR-15", "FR"], None, departments=[("15", "Cantal")])
        self.assertEqual((found[0]["name"], found[0]["archive"], found[0]["holdings"]),
                         ("Archives départementales (Cantal)", None, []))
        self.assertEqual(found[0]["source"], "rule:departmental-archives")

    def test_absent_places_are_left_out(self):
        from probandia.archives.repositories import repositories

        self.assertNotIn("socface", [r["archive"] for r in repositories(["FR-50", "FR"], (1850, 1900))])


class NoNetwork:
    def get(self, url, params):
        raise AssertionError(f"no network call expected: {url}")


class GuideProject(Project):
    """The fixture project with the COG rows of tests/fixtures/cog installed; the gazetteers replaced."""

    def setUp(self):
        import shutil

        super().setUp()
        data = os.path.join(self.tmp.name, "data")
        shutil.copytree(os.path.join(FIX, "cog"), os.path.join(data, "insee"))
        self.env["PROBANDIA_DATA_DIR"] = data

    def guide(self, *argv, http=None):
        from unittest import mock

        http = http or NoNetwork()
        with mock.patch("probandia.lang.places.Http", lambda *a, **k: http):
            code, out = self.call("places", "guide", *argv, "--agent", "researcher", "--json")
        import json

        return code, json.loads(out)

    def apply(self, pid):
        code, out = self.call("apply", pid, "--agent", "orchestrator")
        self.assertEqual(code, 0, out)

    def second_family(self):
        import shutil

        martin = os.path.join(self.dir, "families", "martin")
        shutil.copytree(self.family, martin)
        meta = yamlio.load(os.path.join(martin, "family.yaml"))
        yamlio.dump(os.path.join(martin, "family.yaml"), dict(meta, id="martin", name="MARTIN"))
        os.rename(os.path.join(martin, "research", RID), os.path.join(martin, "research", "2026-10-01-martin"))
        return martin


class GuideCommand(GuideProject):
    """GPS2-T5: places guide proposes the guide, apply writes it; the cache and --copy-from
    build it again without the network."""

    def test_propose_then_apply(self):
        code, r = self.guide("Auxon-Dessous", "--family", "hugo", http=Recorded())
        self.assertEqual(code, 0, r)
        self.assertEqual(r["values"]["PLACE"], "auxon-dessous")
        self.apply(r["values"]["PROPOSAL"])
        place = {p["id"]: p for p in self.index("places")["places"]}["auxon-dessous"]
        levels = {(j["level"], j["name"]) for j in place["jurisdictions"]}
        self.assertTrue({("parish", "Auxon-Dessous"), ("commune", "Auxon-Dessous"), ("commune", "Les Auxons"),
                         ("canton", "Audeux"), ("canton", "Besançon-3"), ("diocese", "Besançon"),
                         ("department", "Doubs")} <= levels)
        self.assertEqual(place["insee"], {"code": "25034"})
        self.assertEqual(place["repositories"][0]["archive"], "ad25")
        self.assertEqual(place["guide"]["sources"][:2], ["insee-cog", "rule:parish-1790"])
        self.assertIn("wikidata", place["guide"]["sources"])
        # A3: the departmental archives' address, and where to look first in them
        self.assertEqual(place["repositories"][0]["url"], "https://archives.doubs.fr/")
        first = [x for x in r["lines"] if x.startswith("first=ad25 https://archives.doubs.fr/ ")]
        self.assertTrue(first and "decennial tables of the commune first" in first[0], r["lines"])

    def test_the_agent_who_applies_stores_the_guide_at_once(self):
        # token-economy J9: left unapplied, the guide's proposal stopped `pass end` at the bench of J8
        import json
        from unittest import mock

        from probandia.proposals import pending
        from probandia.research import Research

        with mock.patch("probandia.lang.places.Http", lambda *a, **k: Recorded()):
            code, out = self.call("places", "guide", "Auxon-Dessous", "--family", "hugo", "--json")   # the session
        r = json.loads(out)
        self.assertEqual(code, 0, r)
        self.assertIs(r["values"]["APPLIED"], True)
        self.assertFalse([x for x in r["lines"] if "next: apply" in x], r["lines"])
        self.assertIn("auxon-dessous", {p["id"] for p in self.index("places")["places"]})
        self.assertNotIn(r["values"]["PROPOSAL"], pending(Research(self.dir, "hugo", RID)))

    def test_a_stored_guide_is_shown_not_rebuilt(self):
        code, r = self.guide("Auxon-Dessous", "--family", "hugo", http=Recorded())
        self.apply(r["values"]["PROPOSAL"])
        code, shown = self.guide("Auxon-Dessous", "--family", "hugo")
        self.assertEqual(code, 0, shown)
        self.assertNotIn("PROPOSAL", shown["values"])
        self.assertRegex(shown["values"]["STORED"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
        self.assertEqual(shown["data"]["jurisdictions"], r["data"]["jurisdictions"])
        code, again = self.guide("Auxon-Dessous", "--family", "hugo", "--refresh", http=Recorded())
        self.assertIn("PROPOSAL", again["values"])

    def test_the_cache_answers_offline(self):
        code, first = self.guide("Auxon-Dessous", "--family", "hugo", http=Recorded())
        code, again = self.guide("Auxon-Dessous", "--family", "hugo", "--offline")
        self.assertEqual(code, 0, again)
        self.assertEqual(again["values"]["CACHED"], 3)
        self.assertEqual(again["data"]["jurisdictions"], first["data"]["jurisdictions"])
        self.assertTrue(os.listdir(os.path.join(self.dir, ".probandia", "cache", "places")))

    def test_offline_without_cache(self):
        code, r = self.guide("Auxon-Dessous", "--family", "hugo", "--offline")
        self.assertEqual(code, 0, r)
        levels = [j["level"] for j in r["data"]["jurisdictions"]]
        self.assertNotIn("Audeux", [j["name"] for j in r["data"]["jurisdictions"]])
        self.assertIn("diocese", levels)
        self.assertTrue(any("offline" in line for line in r["lines"]))

    def test_the_department_in_brackets(self):
        # token-economy C3: the bench's place is in no gazetteer offline; its department names the archives
        for data in (None, "no-cog"):   # with the COG rows of the fixture, then without the COG
            if data:
                self.env["PROBANDIA_DATA_DIR"] = os.path.join(self.tmp.name, data)
            code, r = self.guide("Valognes (Manche)", "--family", "hugo", "--offline")
            self.assertEqual(code, 0, r)
            self.assertEqual(r["values"]["PLACE"], "valognes")
            self.assertTrue(any(x.startswith("first=ad50 https://www.archives-manche.fr/") for x in r["lines"]), r)
            self.assertIn("PROPOSAL", r["values"])

    def test_the_department_chooses_among_communes_of_one_name(self):
        code, r = self.guide("Beaulieu (Cantal)", "--family", "hugo", "--offline")
        self.assertEqual(code, 0, r)
        self.assertIn(("department", "Cantal"), {(j["level"], j["name"]) for j in r["data"]["jurisdictions"]})

    def test_a_place_found_nowhere_and_an_empty_guide(self):
        proposals = os.path.join(self.dir, "families", "hugo", "research", RID, "proposals")
        before = sorted(os.listdir(proposals)) if os.path.isdir(proposals) else []
        self.env["PROBANDIA_DATA_DIR"] = os.path.join(self.tmp.name, "no-cog")
        code, r = self.guide("Nulle-Part", "--family", "hugo", "--offline")
        self.assertEqual((code, r["values"]["REASON"]), (2, "no-place"))
        self.assertIn("insee: the COG files are not installed (places --update-cog)", r["lines"])
        # Besançon, offline and without the COG, has neither jurisdiction nor repository: said, not proposed
        code, r = self.guide("besancon", "--family", "hugo", "--offline")
        self.assertEqual((r["status"], r["values"]["JURISDICTIONS"], r["values"]["REPOSITORIES"]), ("WARN", 0, 0))
        self.assertNotIn("PROPOSAL", r["values"])
        self.assertIn("no jurisdiction and no repository found: nothing proposed", r["lines"])
        self.assertIn("insee: the COG files are not installed (places --update-cog)", r["lines"])
        self.assertEqual(sorted(os.listdir(proposals)) if os.path.isdir(proposals) else [], before)

    def test_copy_to_a_second_family(self):
        self.second_family()
        code, r = self.guide("Auxon-Dessous", "--family", "hugo", http=Recorded())
        self.apply(r["values"]["PROPOSAL"])
        code, copied = self.guide("auxon-dessous", "--family", "martin", "--copy-from", "hugo")
        self.assertEqual(code, 0, copied)
        self.assertEqual(copied["values"]["COPIED_FROM"], "hugo")
        self.apply(copied["values"]["PROPOSAL"])
        places = yamlio.load(os.path.join(self.dir, "families", "martin", "index", "places.yaml"))["places"]
        place = {p["id"]: p for p in places}["auxon-dessous"]
        self.assertEqual(place["guide"]["copied_from"], "hugo")
        self.assertEqual(place["jurisdictions"], {p["id"]: p for p in self.index("places")["places"]}["auxon-dessous"][
            "jurisdictions"])

    def test_copy_from_a_family_without_the_guide(self):
        self.second_family()
        code, r = self.guide("auxon-dessous", "--family", "martin", "--copy-from", "hugo")
        self.assertNotEqual(code, 0)
        self.assertEqual(r["values"]["REASON"], "no-guide")

    def test_without_a_project_it_only_shows(self):
        import io
        import json
        from unittest import mock

        from probandia import cli

        out = io.StringIO()
        with mock.patch("probandia.lang.places.Http", lambda *a, **k: NoNetwork()):
            code = cli.main(["places", "guide", "Auxon-Dessous", "--offline", "--json"], stdout=out, environ=self.env,
                            cwd=self.tmp.name)
        r = json.loads(out.getvalue())
        self.assertEqual(code, 0, r)
        self.assertNotIn("PROPOSAL", r["values"])
        self.assertEqual(r["values"]["JURISDICTIONS"], len(r["data"]["jurisdictions"]))

    def test_the_view(self):
        from unittest import mock

        with mock.patch("probandia.lang.places.Http", lambda *a, **k: Recorded()):
            code, out = self.call("places", "guide", "Auxon-Dessous", "--family", "hugo", "--agent", "researcher")
        self.assertEqual(code, 0, out)
        for part in ("Auxon-Dessous", "Les Auxons", "Audeux", "Archives départementales du Doubs", "apply"):
            self.assertIn(part, out)


class Acceptance(GuideProject):
    """GPS2 acceptance: places guide on a merged commune of the Doubs gives commune, canton, parish and diocese with
    their dates, and the repositories; applied, it is in the report's annex; no network call is made."""

    def test_auxon_dessous(self):
        recorded = Recorded()
        code, r = self.guide("Auxon-Dessous", "--family", "hugo", "--window", "1700-1900", http=recorded)
        self.assertEqual(code, 0, r)
        got = {(j["level"], j["name"], j["from"], j["to"]) for j in r["data"]["jurisdictions"]}
        self.assertTrue({("commune", "Auxon-Dessous", "", "2014-12-31"), ("commune", "Les Auxons", "2015-01-01", ""),
                         ("canton", "Audeux", "", "2015-03-21"), ("canton", "Besançon-3", "2015-03-22", ""),
                         ("parish", "Auxon-Dessous", "", "1790"), ("diocese", "Besançon", "1802", "")} <= got, got)
        self.assertEqual(r["data"]["repositories"][0]["name"], "Archives départementales du Doubs")
        self.apply(r["values"]["PROPOSAL"])
        code, out = self.call("question", "add", "Where did the family live in Auxon-Dessous?", "--place", "auxon-dessous",
                              "--research", RID)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.call("render", RID)[0], 0)
        with open(os.path.join(self.rdir, "report", "report.md"), encoding="utf-8") as fh:
            annex = fh.read().split('<a id="s-guides">')[1]
        for line in ("| commune | Auxon-Dessous | … | 31 décembre 2014 |", "| canton | Audeux | … | 21 mars 2015 |",
                     "| paroisse\\* | Auxon-Dessous | … | 1790 |", "| diocèse\\* | Besançon | 1802 | … |",
                     "Archives départementales du Doubs (`ad25`)"):
            self.assertIn(line, annex)
        self.assertTrue(all(not name.startswith("gov-") for name in recorded.calls))


class Prompts(unittest.TestCase):
    """GPS2-T7: before searching a place, the researcher reads its guide."""

    def test_the_researcher_and_the_skill_say_so(self):
        for parts in (("agents", "researcher.md"), ("cursor", "agents", "researcher.md"), ("droids", "researcher.md"),
                      ("skills", "research", "SKILL.md")):
            with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
                self.assertIn("`places guide <place>`", fh.read(), parts)


class ReportAnnex(Project):
    """GPS2-T6: the report's annex « Guides de localité »: each place of the research with a guide, its
    jurisdictions on a chart of dates (HTML), its repositories and the known gaps of their holdings."""

    def setUp(self):
        super().setUp()
        (code, out), _doc = self.propose_and_apply(places=[guided_place()])
        self.assertEqual(code, 0, out)
        gaps = os.path.join(self.family, "index", "gaps.yaml")
        yamlio.dump(gaps, {"schema": 1, "gaps": [{"archive": "ad25", "reference": "3 E 150", "window": {
            "from": 1793, "to": 1799}, "kind": "lacunary", "source": None}]})

    def report(self, ext="md"):
        code, out = self.call("render", RID)
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.rdir, "report", "report." + ext), encoding="utf-8") as fh:
            return fh.read()

    def ask_about_auxon_dessous(self):
        code, out = self.call("question", "add", "Where did the family live in Auxon-Dessous?", "--place", "auxon-dessous",
                              "--research", RID)
        self.assertEqual(code, 0, out)

    def test_a_place_the_research_does_not_name_stays_out(self):
        self.assertNotIn("Guides de localité", self.report())

    def test_a_jurisdiction_without_source(self):
        path = os.path.join(self.family, "index", "places.yaml")
        doc = yamlio.load(path)
        for p in doc["places"]:
            for j in p.get("jurisdictions") or []:
                j.pop("source", None)
        validate_document("places", doc, path)
        yamlio.dump(path, doc)
        self.ask_about_auxon_dessous()
        md = self.report()
        self.assertIn("| commune | Auxon-Dessous | 1790 | 31 décembre 2014 | — |", md)
        self.report("html")

    def test_markdown_and_html(self):
        from tests.unit.test_human import golden

        self.ask_about_auxon_dessous()
        md = self.report()
        chapter = md[md.index('<a id="s-guides">'):]
        chapter = chapter[:chapter.index("[^")] if "[^" in chapter else chapter
        golden(self, "guide-report", chapter)
        self.assertIn("| paroisse\\* | Auxon-Dessous | … | 1790 |", chapter)
        self.assertIn("| ad25 | 1793–1799 | registres lacunaires | 3 E 150 |", chapter)
        html = self.report("html")
        start = html.index('<section id="s-guides">')
        end = "</section>\n</section>"
        section = html[start:html.index(end, start) + len(end)]
        golden(self, "guide-report-html", section + "\n")
        self.assertIn('<figure class="timeline guide"><svg', section)
        self.assertIn("paroisse Auxon-Dessous: sans début connu – 1790", section)
        self.assertEqual(self.call("verify", RID, "--rule", "V-6")[0], 0)

    def test_by_the_place_of_a_fact(self):
        persons = os.path.join(self.family, "index", "persons.yaml")
        doc = yamlio.load(persons)
        fact = next(f for p in doc["persons"] for f in p.get("facts", []) if f.get("research") == RID)
        fact["place"] = {"id": None, "as_written": "Auxon-Dessous"}
        yamlio.dump(persons, doc)
        self.assertIn("Auxon-Dessous, aujourd'hui Les Auxons", self.report())

    def test_living_mode(self):
        from probandia import lifecycle
        from probandia.research import Research

        self.ask_about_auxon_dessous()
        lifecycle.update_meta(Research(self.dir, "hugo", RID), mode="living")
        md = self.report()
        body = md[md.index("<a id="):]   # past the table of contents
        self.assertLess(body.index('<a id="s-sources">'), body.index('<a id="s-guides">'))


if __name__ == "__main__":
    unittest.main()
