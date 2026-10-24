import glob
import io
import os
import shutil
import tempfile
import unittest

from probandia import chronology, cli
from probandia.lang import calendars, places, variants
from probandia.lang.dates import Unrecognized, read
from probandia.util import yamlio
from tests import ROOT

FIX = os.path.join(ROOT, "tests", "fixtures")
CASES = yamlio.load(os.path.join(FIX, "dates", "cases.yaml"))


def call(*argv, cwd=None, environ=None):
    out = io.StringIO()
    code = cli.main(list(argv), stdout=out, environ=environ or {}, cwd=cwd or tempfile.gettempdir())
    return code, out.getvalue()


def values(out):
    return dict(line.split("=", 1) for line in out.splitlines() if not line.startswith("- "))


class Dates(unittest.TestCase):
    def test_known_cases(self):
        for case in CASES["readable"]:
            with self.subTest(text=case["text"]):
                r = read(case["text"], case.get("read_as", "gregorian"))
                self.assertEqual((r["iso"], r["end"], r["qualifier"], r["calendar"]),
                                 (case["iso"], case.get("end"), case.get("qualifier", "exact"),
                                  case.get("calendar", "gregorian")))

    def test_never_guessed(self):
        for text in CASES["unreadable"]:
            with self.subTest(text=text):
                with self.assertRaises(Unrecognized):
                    read(text)
                code, out = call("dates", text)
                self.assertEqual(code, 1)
                self.assertIn("REASON=unrecognized", out)

    def test_command(self):
        code, out = call("dates", "18 brumaire an VIII")
        self.assertEqual(code, 0)
        self.assertEqual(values(out), {"STATUS": "OK", "ISO": "1799-11-09", "QUALIFIER": "exact",
                                       "CALENDAR": "republican", "ORIGINAL": "18 brumaire an VIII"})

    def test_ninth_month_abbreviation_is_november(self):
        self.assertEqual(read("9bre 1780")["iso"], "1780-11")
        self.assertEqual(read("7bre 1780")["iso"], "1780-09")

    def test_age_range(self):
        code, out = call("dates", "--age", "34", "--on", "1850-03-12")
        v = values(out)
        self.assertEqual((v["ISO"], v["END"], v["QUALIFIER"]), ("1815-03-13", "1816-03-12", "between"))
        v = values(call("dates", "--age", "1", "--on", "1852-02-29")[1])
        self.assertEqual((v["ISO"], v["END"]), ("1850-03-01", "1851-02-28"))

    def test_julian(self):
        v = values(call("dates", "--julian", "1700-02-18")[1])
        self.assertEqual((v["ISO"], v["CALENDAR"]), ("1700-02-28", "julian"))
        v = values(call("dates", "--julian", "1582-10-04")[1])
        self.assertEqual(v["ISO"], "1582-10-14")  # the eve of the reform

    def test_republican_table(self):
        self.assertEqual(calendars.republican_to_gregorian(1, 1, 1), (1792, 9, 22))
        self.assertIsNone(calendars.republican_to_gregorian(2, 13, 6))  # year II not leap
        self.assertEqual(calendars.republican_to_gregorian(3, 13, 6), (1795, 9, 22))

    def test_easter(self):
        self.assertEqual(calendars.easter_gregorian(2024), (2024, 3, 31))
        self.assertEqual(calendars.easter_gregorian(1818), (1818, 3, 22))  # earliest possible
        self.assertEqual(calendars.easter_julian(2024), (2024, 4, 22))  # Orthodox Easter: 5 May


class Variants(unittest.TestCase):
    def test_hugo_and_victor(self):
        project = os.path.join(FIX, "project")
        code, out = call("variants", "Hugo", "--given", "Victor", cwd=project)
        self.assertEqual(code, 0)
        forms = [l[7:].split(" ")[0] for l in out.splitlines() if l.startswith("- form=")]
        kinds = [l.split(" ")[2] for l in out.splitlines() if l.startswith("- form=")]
        self.assertEqual(forms[:2], ["Hugot", "Hugues"])  # attested first
        self.assertEqual(kinds[:2], ["attested"] * 2)
        for f in ("Huggo", "Hugos"):
            self.assertIn(f, forms)
        self.assertLessEqual(len(forms), 12)
        given = [l[8:].split(" ")[0] for l in out.splitlines() if l.startswith("- given=")]
        self.assertEqual(given, ["Viktor", "Victoris"])

    def test_without_a_project(self):
        forms = [f for f, kind, d in variants.surname_forms("Becker")]
        for f in ("Bekker", "Beker", "Beckher"):
            self.assertIn(f, forms)

    def test_scribal_forms_keep_a_phonetic_code(self):
        from probandia.lang.phonetic import koelner, soundex2
        for name in ("Becker", "Meyer", "Schmidt", "Lefebvre", "Weiss"):
            for form, rule in variants.scribal_forms(name):
                self.assertTrue(soundex2(form) == soundex2(name) or koelner(form) == koelner(name),
                                (name, form))

    def test_rules(self):
        forms = [f for f, k, d in variants.surname_forms("Meyer")]
        self.assertEqual(forms[:3], ["Meier", "Maier", "Mayer"])
        self.assertIn("Mueller", [f for f, k, d in variants.surname_forms("Müller")])
        self.assertNotIn("Maertin", [f for f, k, d in variants.surname_forms("Martin")])

    def test_particles(self):
        # a bench case: LA FONTAINE and FONTAINE, not five scribal forms first
        forms = variants.surname_forms("LAFONTAINE")
        self.assertEqual([f for f, k, d in forms[:2]], ["LA FONTAINE", "FONTAINE"])
        self.assertEqual({k for f, k, d in forms[:2]}, {"particle"})
        for rule in ("double", "final"):
            self.assertLessEqual(sum(1 for f, k, d in forms if d == rule), 2, rule)
        self.assertEqual([f for f, k, d in variants.surname_forms("La Fontaine")][:2], ["Lafontaine", "Fontaine"])
        self.assertEqual([f for f, k, d in variants.surname_forms("D’Artois")][:2], ["Dartois", "Artois"])
        self.assertEqual([f for f, k, d in variants.surname_forms("Deschamps")][:2], ["Des Champs", "Champs"])
        for name in ("Lambert", "Laurent", "Delcourt", "Fontaine", "Desaix"):  # no particle there
            self.assertEqual(variants.particle_forms(name), [], name)

    def test_paleo(self):
        forms = {f: k for f, k, d in variants.surname_forms("Bernard", paleo=True, limit=40)}
        self.assertEqual(forms.get("Dernard"), "paleo")
        self.assertEqual(forms.get("Bemard"), "paleo")  # rn read as m

    def test_given_names(self):
        self.assertGreaterEqual(len(variants.given_table()), 300)
        forms = dict(variants.given_forms("Jean"))
        self.assertEqual(forms["Joannes"], "la")
        self.assertEqual(forms["Joannis"], "la_gen")
        self.assertEqual(dict(variants.given_forms("Marie"))["Mariae"], "la_gen")
        self.assertIn("Wilhelm", dict(variants.given_forms("Guillaume")))
        self.assertEqual(variants.genitive("Leopoldus"), "Leopoldi")
        self.assertEqual(variants.genitive("Joannes Baptista"), "Joannis Baptistae")


class FakeHttp:
    """Recorded responses, by host."""

    FILES = {"gov.genealogy.net": "gov-octeville.html",
             "nominatim.openstreetmap.org": "nominatim-octeville.json",
             "www.wikidata.org": "wikidata-octeville.json",
             "whgazetteer.org": "whg-octeville.json"}

    def __init__(self):
        self.calls = []

    def get(self, url, params):
        host = url.split("/")[2]
        self.calls.append(host)
        with open(os.path.join(FIX, "http", "places", self.FILES[host]), encoding="utf-8") as fh:
            return fh.read()


class Places(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        shutil.copytree(os.path.join(FIX, "cog"), os.path.join(self.tmp.name, "insee"))
        self.env = {"PROBANDIA_DATA_DIR": self.tmp.name}
        self.cog = places.Cog(os.path.join(self.tmp.name, "insee"))

    def test_commune_merged_after_1943(self):
        code, out = call("places", "Octeville", "--as-of", "1900", "--offline", environ=self.env)
        v = values(out)
        self.assertEqual(code, 0, out)
        self.assertEqual((v["AS_OF"], v["CURRENT"]), ("Octeville", "Cherbourg-en-Cotentin"))
        v = values(call("places", "Octeville", "--as-of", "2010", "--offline", environ=self.env)[1])
        self.assertEqual(v["AS_OF"], "Cherbourg-Octeville")
        v = values(call("places", "Cherbourg", "--as-of", "1950", "--offline", environ=self.env)[1])
        self.assertEqual((v["AS_OF"], v["CURRENT"]), ("Cherbourg", "Cherbourg-en-Cotentin"))

    def test_equally_likely_asks(self):
        code, out = call("places", "Beaulieu", "--as-of", "1900", "--offline", environ=self.env)
        self.assertEqual(code, 3)
        v = values(out)
        self.assertEqual((v["STATUS"], v["QUESTION"]), ("ASK", "place_ambiguous"))
        self.assertEqual(v["CHOICES"], "insee:07028|insee:15020")
        self.assertIn("- answer with --choice <id>", out)
        code, out = call("places", "Beaulieu", "--as-of", "1900", "--offline", "--choice", "insee:15020",
                         environ=self.env)
        self.assertEqual(code, 0, out)
        self.assertIn("- place=insee:15020", out)
        self.assertNotIn("insee:07028", out)
        code, out = call("places", "Beaulieu", "--offline", "--choice", "insee:99999", environ=self.env)
        self.assertEqual(code, 2, out)

    def test_family_places_come_first(self):
        fam = [{"id": "besancon", "names_as_written": ["Vesontio"],
                "current_name": "Besançon", "lat": 47.24, "lon": 6.02}]
        found, notes = places.lookup("Vesontio", None, fam, self.cog, FakeHttp())
        self.assertEqual(found[0]["source"], "family")
        self.assertEqual(found[0]["current"], "Besançon")

    def test_cog_answers_before_the_network(self):
        http = FakeHttp()
        found, notes = places.lookup("Octeville", 1900, (), self.cog, http)
        self.assertEqual(http.calls, [])
        self.assertEqual(found[0]["codes"]["insee_then"], "50383")

    def test_online_order_with_recorded_responses(self):
        http = FakeHttp()
        found, notes = places.lookup("Octeville", 1900, (), None, http, environ={})
        self.assertEqual(http.calls, ["gov.genealogy.net"])  # GOV has the exact name
        self.assertEqual(found[0]["codes"], {"gov": "OCTLLEIN99EP"})
        self.assertTrue(any("GEONAMES_USERNAME" in n for n in notes))

    def test_each_gazetteer_parses_its_response(self):
        http = FakeHttp()
        osm = places.from_nominatim("Octeville", http)
        self.assertEqual((osm[0]["name"], osm[0]["score"]), ("Octeville", 2))
        wd = places.from_wikidata("Octeville", http)
        self.assertIn("Q2420328", [c["codes"]["wikidata"] for c in wd])
        whg = places.from_whg("Octeville", http)
        self.assertEqual((whg[0]["name"], whg[0]["lat"]), ("Octeville", 49.626118))

    def test_failing_gazetteer_does_not_stop_the_others(self):
        class Broken(FakeHttp):
            def get(self, url, params):
                if "gov" in url:
                    raise OSError("down")
                return super().get(url, params)
        found, notes = places.lookup("Octeville", None, (), None, Broken(), environ={})
        self.assertEqual(found[0]["source"], "nominatim")
        self.assertTrue(any(n.startswith("gov: failed") for n in notes))


class Chronology(unittest.TestCase):
    def test_fixtures(self):
        for path in sorted(glob.glob(os.path.join(FIX, "chronology", "*.yaml"))):
            doc = yamlio.load(path)
            with self.subTest(case=os.path.basename(path)):
                issues = chronology.check(doc["persons"])
                if not doc["expect"]:
                    self.assertEqual(issues, [])
                    continue
                self.assertEqual(len(issues), 1, issues)
                for fact_id in doc["expect"]:
                    self.assertIn(fact_id, issues[0])

    def test_rejected_by_apply_with_fact_ids(self):
        from probandia.proposals import check_chronology
        doc = yamlio.load(os.path.join(FIX, "chronology", "parent-younger-than-child.yaml"))
        issues = check_chronology(doc["persons"], {"luc-martin-1795"})
        self.assertTrue(issues[0].startswith("P-9: luc-martin-1795.birth"))
