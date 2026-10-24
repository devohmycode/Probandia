"""Citations after Evidence Explained: typed sources, models, the cite engine and command (GPS6)."""
import glob
import json
import os
import re
import unittest

from probandia import cite
from probandia.errors import SchemaError
from probandia.util import yamlio
from probandia.util.schema import load_schema, validate_document
from tests import ROOT
from tests.unit.test_data_layer import RID, Project

FIX = os.path.join(ROOT, "tests", "fixtures")


CATALOGUE = os.path.join(ROOT, "catalogues", "citations")
LANGS = ("en", "fr")


def catalogue(lang):
    return yamlio.load(os.path.join(CATALOGUE, lang + ".yaml"))


def typed_sources():
    return yamlio.load(os.path.join(FIX, "sources", "valid", "typed.yaml"))["sources"]


class Format(Project):
    """GPS6-T1: a source takes a type, the fields of its type and layers; older sources stay valid."""

    def test_older_sources_files_stay_valid(self):
        for path in (os.path.join(FIX, "sources", "valid", "fixture-family.yaml"),
                     os.path.join(self.family, "index", "sources.yaml")):
            if os.path.exists(path):
                validate_document("sources", yamlio.load(path), path)

    def test_the_example_covers_every_type(self):
        types = load_schema("sources", 1)["$defs"]["source"]["properties"]["type"]["enum"]
        self.assertEqual(sorted({s["type"] for s in typed_sources()}), sorted(types))

    def test_sources_and_proposals_share_the_source_format(self):
        def source_def(name):
            defs = load_schema(name, 1)["$defs"]
            return json.dumps([defs["source"], defs["layer"], defs["sday"]], sort_keys=True)
        self.assertEqual(source_def("sources"), source_def("proposal"))

    def test_a_layered_source_goes_through_apply(self):
        source = typed_sources()[0]
        (code, out), _doc = self.propose_and_apply(sources=[source])
        self.assertEqual(code, 0, out)
        written = {s["id"]: s for s in self.index("sources")["sources"]}[source["id"]]
        self.assertEqual(written["type"], "parish-register")
        self.assertEqual(written["layers"][0]["form"], "online-image")
        self.assertEqual(written["names"], ["Nicolas Hugot", "Pierre Hugot", "Marie Vernier"])


class Models(unittest.TestCase):
    """GPS6-T2: catalogues/citations/ has the three forms of every type, in English and French."""

    def test_every_language_validates(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                doc = catalogue(lang)
                validate_document("citations", doc, lang)
                self.assertEqual(doc["lang"], lang)

    def test_required_fields_are_the_same_in_every_language(self):
        for level in ("required", "recommended"):
            fields = [{t: m[level] for t, m in catalogue(lang)["types"].items()} for lang in LANGS]
            self.assertEqual(fields[0], fields[1], level)

    def test_only_required_fields_stand_outside_a_group(self):
        """GPS-D10: a recommended or optional field that is empty drops its group, never leaves a hole."""
        for lang in LANGS:
            for source_type, model in catalogue(lang)["types"].items():
                for form in ("full", "first", "short"):
                    top = re.sub(r"\[[^\[\]]*\]", "", model[form])
                    while re.search(r"\[[^\[\]]*\]", top):
                        top = re.sub(r"\[[^\[\]]*\]", "", top)
                    with self.subTest(lang=lang, type=source_type, form=form):
                        self.assertLessEqual(set(re.findall(r"\{(\w+)\}", top)), set(model["required"]))

    def test_templates_are_well_formed(self):
        fields = set(load_schema("sources", 1)["$defs"]["source"]["properties"]) | {"name"}
        layer_fields = set(load_schema("sources", 1)["$defs"]["layer"]["properties"])
        for lang in LANGS:
            doc = catalogue(lang)
            models = [(f"types.{t}.{form}", m[form], fields)
                      for t, m in doc["types"].items() for form in ("full", "first", "short")]
            models += [(f"layers.{f}.{form}", m[form], layer_fields)
                       for f, m in doc["layers"].items() for form in ("full", "first")]
            models.append(("page", doc["page"], fields))
            for where, template, known in models:
                with self.subTest(lang=lang, model=where):
                    depth = 0
                    for ch in template:
                        depth += {"[": 1, "]": -1}.get(ch, 0)
                        self.assertGreaterEqual(depth, 0)
                    self.assertEqual(depth, 0)
                    self.assertLessEqual(set(re.findall(r"\{(\w+)\}", template)), known)

    def test_the_header_states_the_rule_of_gps_d7(self):
        for lang in LANGS:
            with open(os.path.join(CATALOGUE, lang + ".yaml"), encoding="utf-8") as fh:
                head = fh.read(1200)
            self.assertIn("Evidence Explained", head)
            self.assertIn("own words", head)

    def test_broken_models_are_refused_with_the_path(self):
        for path in sorted(glob.glob(os.path.join(FIX, "citations", "invalid", "*.yaml"))):
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    expected = fh.readline()[len("# expect: "):].strip()
                with self.assertRaises(SchemaError) as cm:
                    validate_document("citations", yamlio.load(path), path)
                self.assertIn(expected, [issue.path for issue in cm.exception.errors])


class Engine(unittest.TestCase):
    """GPS6-T3: cite.format applies the model of a type, in each form and language."""

    def setUp(self):
        self.sources = {s["type"]: s for s in typed_sources()}

    def test_every_type_every_form_every_language(self):
        for source_type, source in self.sources.items():
            for lang in LANGS:
                forms = cite.forms(source, lang)
                with self.subTest(type=source_type, lang=lang):
                    self.assertEqual(set(forms), {"full", "first", "short"})
                    for form, text in forms.items():
                        self.assertTrue(text.endswith("."), (form, text))
                        self.assertNotIn("?]", text)
                        self.assertNotIn("{", text)
                        self.assertNotIn("[", text)
                    self.assertLess(len(forms["short"]), len(forms["first"]))

    def test_a_layered_baptism(self):
        source = self.sources["parish-register"]
        self.assertEqual(
            cite.format(source, "first", "fr"),
            "Paroisse de Châtillon-le-Duc, Baptêmes, mariages, sépultures, 1780-1792, 3 E 160/4, f° 12 v°, "
            "baptême de Nicolas Hugot, 14 mars 1785 ; Archives départementales du Doubs ; images en ligne, "
            "Registres paroissiaux et d'état civil, Archives départementales du Doubs "
            "(https://archives.doubs.fr/ark:/12345/example, consulté le 4 octobre 2026), vue 27.")
        self.assertEqual(
            cite.format(source, "short", "en"),
            "Châtillon-le-Duc parish, Baptêmes, mariages, sépultures, 1780-1792, folio 12 v°, baptism, Nicolas Hugot, "
            "14 March 1785.")
        full = cite.format(source, "full", "en")
        self.assertTrue(full.startswith("Châtillon-le-Duc parish. Baptêmes"), full)
        self.assertIn(" Online images, Registres paroissiaux", full)

    def test_dates_partial_and_first_of_the_month(self):
        cat = cite.catalogue("fr")
        self.assertEqual(cite.write_date("1785-03-01", cat), "1er mars 1785")
        self.assertEqual(cite.write_date("1842-06", cat), "juin 1842")
        self.assertEqual(cite.write_date("1836", cite.catalogue("en")), "1836")

    def test_a_missing_required_field_is_reported_not_invented(self):
        source = dict(self.sources["civil-registration"], register=None)
        self.assertEqual(cite.missing(source), ["register"])
        self.assertIn("[register?]", cite.format(source, "first", "en"))

    def test_a_missing_recommended_field_drops_its_group(self):
        source = dict(self.sources["notarial-act"], act=None, act_date=None)
        self.assertEqual(cite.missing(source), [])
        self.assertEqual(cite.lacking(source), ["act", "act_date"])
        self.assertEqual(cite.format(source, "short", "fr"), "Maître Girardot, Besançon, Pierre Hugot.")

    def test_an_untyped_source_keeps_the_sentence(self):
        source = {"id": "src-01JA0000000000000000000009", "repository": "Archives municipales de Besançon",
                  "reference": "E-1802-N", "image_no": "45"}
        sentence = cite.sentence(source)
        self.assertEqual(cite.forms(source, "fr"), {"full": sentence, "first": sentence, "short": sentence})
        self.assertEqual(cite.missing(source), [])
        self.assertEqual(cite.ensure(source)["citation"], sentence)

    def test_ensure_fills_the_first_note_of_a_typed_source(self):
        source = self.sources["book"]
        self.assertEqual(cite.ensure(source, "en")["citation"], cite.format(source, "first", "en"))

    def test_a_regional_tag_falls_back_to_its_language(self):
        source = self.sources["census"]
        self.assertEqual(cite.format(source, "short", "fr-CA"), cite.format(source, "short", "fr"))
        self.assertEqual(cite.format(source, "short", "de"), cite.format(source, "short", "en"))


class Command(Project):
    """GPS6-T4: cite takes --type, its fields and a layer; --as picks one form; --lang the language."""

    BAPTISM = ["--form", "--type", "parish-register", "--jurisdiction", "Châtillon-le-Duc", "--register",
               "BMS 1780-1792", "--act", "baptism", "--act-date", "1785-03-14", "--names", "Nicolas Hugot",
               "--repository", "AD Doubs", "--layer", "online-image", "--layer-image", "27"]

    def test_three_forms(self):
        code, out = self.call("cite", *self.BAPTISM)
        self.assertEqual(code, 0, out)
        self.assertIn("FULL=Châtillon-le-Duc parish. BMS 1780-1792. AD Doubs. Online images.\n", out)
        self.assertIn("CITATION=Châtillon-le-Duc parish, BMS 1780-1792, baptism of Nicolas Hugot, 14 March 1785; "
                      "AD Doubs; online images, image 27.\n", out)
        self.assertIn("SHORT=Châtillon-le-Duc parish, BMS 1780-1792, baptism, Nicolas Hugot, 14 March 1785.\n", out)

    def test_one_form_in_french(self):
        code, out = self.call("cite", *self.BAPTISM, "--as", "short", "--lang", "fr")
        self.assertIn("FORM=short\nCITATION=Paroisse de Châtillon-le-Duc, BMS 1780-1792, baptême, Nicolas Hugot, "
                      "14 mars 1785.\n", out)
        self.assertNotIn("FULL=", out)

    def test_the_form_asks_for_the_fields_of_the_type(self):
        code, out = self.call("cite", "--form", "--type", "census", "--jurisdiction", "Auxon-Dessous")
        self.assertIn("STATUS=WARN", out)
        self.assertIn("MISSING=act_date,repository", out)
        self.assertIn("missing: --act-date, --repository", out)
        code, out = self.call("cite", "--form", "--type", "notarial-act", "--notary", "Me Girardot",
                              "--repository", "AD Doubs")
        self.assertIn("STATUS=OK", out)
        self.assertIn("LACKING=act,act_date,reference", out)

    def test_an_untyped_form_is_unchanged(self):
        code, out = self.call("cite", "--form", "--repository", "AD Doubs", "--reference", "3 E 41")
        self.assertIn("CITATION=AD Doubs, 3 E 41.\n", out)
        self.assertNotIn("FULL=", out)

    def test_a_typed_source_of_the_family(self):
        source = typed_sources()[0]
        self.propose_and_apply(sources=[source])
        code, out = self.call("cite", source["id"], "--as", "full")
        self.assertEqual(code, 0, out)
        self.assertIn("CITATION=Châtillon-le-Duc parish. Baptêmes, mariages, sépultures, 1780-1792, 3 E 160/4.", out)


from tests.unit import test_report  # noqa: E402

BIRTH = {"id": "src-01J9ZK3M4X0000000000000001", "type": "civil-registration",
         "repository": "Archives municipales de Besançon", "jurisdiction": "Besançon",
         "register": "Naissances, 1802", "reference": "E-1802-N", "act": "birth", "act_no": "112",
         "act_date": "1802-02-27", "names": ["Victor Hugo"],
         "layers": [{"form": "online-image", "by": "FamilySearch", "image_no": "45",
                     "url": "https://example.org/amb/e-1802-n/45", "accessed": "2026-09-30"}]}


class InTheReport(test_report.ReportProject):
    """GPS6-T5: the first mention of a typed source gives its first note, the next ones its short note;
    the list of sources gives its full form, sorted by repository then type."""

    def setUp(self):
        super().setUp()
        index = os.path.join(self.dir, "families", "hugo", "index")
        doc = yamlio.load(os.path.join(index, "sources.yaml"))
        doc["sources"] = [BIRTH if s["id"] == BIRTH["id"] else s for s in doc["sources"]]
        yamlio.dump(os.path.join(index, "sources.yaml"), doc)
        persons = yamlio.load(os.path.join(index, "persons.yaml"))
        for p in persons["persons"]:
            for f in p.get("facts", []):
                if f["id"] == "leopold-hugo-1773.birth":
                    f["source"] = BIRTH["id"]
        yamlio.dump(os.path.join(index, "persons.yaml"), persons)

    def test_first_note_then_short_note(self):
        from tests.unit.test_human import golden

        code, out = self.call("render", "--formats", "md")
        self.assertEqual(code, 0, out)
        md = self.read("report.md")
        notes = [line for line in md.splitlines() if line.startswith("[^")]
        golden(self, "citations-report", "\n".join(notes) + "\n")
        self.assertIn("acte de naissance n° 112 de Victor Hugo, 27 février 1802 ; Archives municipales de "
                      "Besançon ; images en ligne", notes[0])
        self.assertTrue(notes[1].endswith("Besançon, Naissances, 1802, naissance n° 112, "
                                          "Victor Hugo, 27 février 1802."), notes[1])
        sources = md[md.index('<a id="s-sources">'):]
        self.assertIn("- Besançon. État civil, Naissances, 1802, E-1802-N. Archives municipales de "
                      "Besançon. Images en ligne, FamilySearch, https://example.org/amb/e-1802-n/45.", sources)


class Gedcom(unittest.TestCase):
    """GPS6-T6: TITL is the list entry, a REPO record the repository, NOTE the first note, PAGE what is
    proper to the record; an import reads them back, in GEDCOM 7 and 5.5.1."""

    PERSON = {"id": "victor-hugo-1802", "names": {"given": "Victor", "surname": "HUGO"}, "sex": "M",
              "living": False, "parents": {"father": None, "mother": None}, "spouses": [],
              "facts": [{"id": "victor-hugo-1802.birth", "type": "birth", "status": "record",
                         "date": {"value": "1802-02-26", "qualifier": "exact"}, "source": BIRTH["id"]}]}

    def export(self, version):
        from probandia import gedcom

        return gedcom.Export([self.PERSON], [BIRTH], lang="fr", version=version).text()

    def test_the_parts_of_a_typed_citation(self):
        from probandia import gedcom

        for version in (7, 551):
            with self.subTest(version=version):
                roots = gedcom.parse(self.export(version))
                sour = next(r for r in roots if r.tag == "SOUR")
                self.assertEqual(sour.text("TITL"), cite.format(BIRTH, "full", "fr"))
                self.assertEqual(sour.text("NOTE"), cite.format(BIRTH, "first", "fr"))
                repo = next(r for r in roots if r.tag == "REPO")
                self.assertEqual(sour.first("REPO").value, repo.xref)
                self.assertEqual(sour.first("REPO").text("CALN"), "E-1802-N")
                self.assertEqual(repo.text("NAME"), "Archives municipales de Besançon")
                birth = next(r for r in roots if r.tag == "INDI").first("BIRT")
                self.assertEqual(birth.first("SOUR").text("PAGE"),
                                 "n° 112, naissance, Victor Hugo, 27 février 1802, vue 45")

    def test_export_then_import_keeps_the_citation(self):
        import tempfile

        from probandia import gedcom_import

        for version in (7, 551):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "tree.ged")
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(self.export(version))
                imp = gedcom_import.Import(tmp, "hugo", path)
                [(doc, _reasons)] = imp.proposals([])
                [source] = doc["sources"]
                self.assertEqual(source["repository"], "Archives municipales de Besançon")
                self.assertEqual(source["title"], cite.format(BIRTH, "full", "fr"))
                self.assertEqual(source["reference"], "E-1802-N")
                self.assertEqual(source["item"], "n° 112, naissance, Victor Hugo, 27 février 1802, vue 45")
                self.assertEqual(source["citation"], cite.format(BIRTH, "first", "fr"))


class Rule(Project):
    """GPS6-T7: V-17 asks a typed source cited by the research the fields its model requires; a recommended
    field missing only warns (GPS-D10)."""

    def v17(self, standard="off"):
        from probandia import verify
        from probandia.research import Research

        class Config:
            def get(self, key):
                return standard if key == "proof.standard" else None

        return verify.run(self.dir, Research(self.dir, "hugo", RID), Config(), ["V-17"])[0][1:]

    def use(self, source):
        path = os.path.join(self.family, "index", "sources.yaml")
        doc = yamlio.load(path)
        doc["sources"] = [source if s["id"] == source["id"] else s for s in doc["sources"]]
        yamlio.dump(path, doc)

    def test_each_case(self):
        self.assertEqual(self.v17("strict"), ("PASS", ""))   # no typed source: as before
        self.use(BIRTH)
        self.assertEqual(self.v17("strict"), ("PASS", ""))
        self.use(dict(BIRTH, act=None))
        self.assertEqual(self.v17(), ("PASS", ""))
        self.assertEqual(self.v17("warn"), ("WARN", f"{BIRTH['id']} (civil-registration): no act"))
        self.assertEqual(self.v17("strict")[0], "WARN")
        self.use(dict(BIRTH, register=None))
        self.assertEqual(self.v17(), ("WARN", f"{BIRTH['id']} (civil-registration): missing register"))
        self.assertEqual(self.v17("strict")[0], "FAIL")

    def test_a_source_the_research_does_not_cite_is_not_checked(self):
        self.use(dict(BIRTH, id="src-01J9ZK3M4X0000000000000003", register=None))
        self.assertEqual(self.v17("strict"), ("PASS", ""))


class Guidance(unittest.TestCase):
    """GPS6-T8: the researcher proposes a source with its type and required fields; the report skill sends
    to the catalogue instead of describing the models."""

    def read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_the_researcher_and_the_skills_say_so(self):
        for rel in ("agents/researcher.md", "cursor/agents/researcher.md", "droids/researcher.md"):
            self.assertIn("gets its `type` and the fields `cite --form --type <type>` asks for", self.read(rel), rel)
        self.assertIn("type and its fields, layers[]", self.read("skills/research/SKILL.md"))
        report = self.read("skills/report/SKILL.md")
        self.assertIn("`catalogues/citations/`", report)
        self.assertNotIn("first reference note", report)


class Series(unittest.TestCase):
    """GPS-D12: each citation type names its series of catalogues/source-types.yaml (GPS3); the two lists
    keep their ids and meet through this correspondence."""

    def test_every_series_exists_and_every_series_is_cited(self):
        from probandia.proof import source_types

        known = set(source_types.by_id(source_types.load()))
        named = {t: m["series"] for t, m in catalogue("en")["types"].items()}
        self.assertLessEqual({s for s in named.values() if s}, known)
        self.assertEqual({s for s in named.values() if s}, known)   # every series has a citation type
        self.assertEqual(cite.series("parish-register"), "parish_registers")
        self.assertEqual(cite.series("newspaper"), "press")
        self.assertIsNone(cite.series("online-tree"))
        self.assertIsNone(cite.series(None))

    def test_the_same_in_every_language(self):
        self.assertEqual(*[{t: m["series"] for t, m in catalogue(lang)["types"].items()} for lang in LANGS])
