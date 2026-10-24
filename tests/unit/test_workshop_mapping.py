"""A fact of Probandia as a fact of the workshop, and the comparison of the two (docs/workshop-sync.md, WS3)."""
import io
import os
import re
import shutil
import tempfile
import unittest

from probandia import cli
from probandia.util import yamlio
from tests import ROOT

WORKSHOP = os.path.join(ROOT, "tests", "fixtures", "workshop")
# the prefix check of the workshop's outils/validation.py, as docs/workshop-sync.md describes it: a divergence
# note starts with the marker in capitals, accent included, a space, a colon, a space, then its text
VALIDATION_PREFIX = re.compile(r"^DIVERGENCE NON TRANCHÉE : \S")
_CACHE = {}


def imported_workshop():
    """A folder holding the test workshop imported by new, made once per run and copied by each test."""
    if "dir" not in _CACHE:
        tmp = tempfile.mkdtemp(prefix="pb-ws-")
        folder = os.path.join(tmp, "workshop")
        shutil.copytree(WORKSHOP, folder)
        env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp, "user"), "PROBANDIA_SESSION": "test",
               "CLAUDE_CONFIG_DIR": os.path.join(tmp, "claude"), "LANG": "en_US.UTF-8"}
        out = io.StringIO()
        code = cli.main(["new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                         "--workshop", "import"], stdout=out, environ=env, cwd=folder)
        assert code == 0, out.getvalue()
        rid = next(x.split("=", 1)[1] for x in out.getvalue().splitlines() if x.startswith("RESEARCH="))
        _CACHE.update(dir=tmp, research=rid)
    return _CACHE["dir"], _CACHE["research"]


def tearDownModule():
    if "dir" in _CACHE:
        shutil.rmtree(_CACHE.pop("dir"), ignore_errors=True)


class Imported(unittest.TestCase):
    def setUp(self):
        src, self.research = imported_workshop()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shutil.copytree(src, tmp.name, dirs_exist_ok=True)
        self.tmp = tmp.name
        self.dir = os.path.join(tmp.name, "workshop")
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "user"), "PROBANDIA_SESSION": "test",
                    "CLAUDE_CONFIG_DIR": os.path.join(tmp.name, "claude"), "LANG": "en_US.UTF-8"}

    def ctx(self):
        from probandia import workshop
        from probandia.workshop.prototype.mapping import Context

        return Context(self.dir, workshop.load(self.dir))

    def people(self):
        return yamlio.load(os.path.join(self.dir, "commun", "personnes.yaml"))

    def index(self, name):
        from probandia.indexes import FamilyIndexes

        return FamilyIndexes(self.dir, "hugo").load(name)

    def write_index(self, name, doc):
        from probandia.indexes import FamilyIndexes

        FamilyIndexes(self.dir, "hugo").write({name: doc}, {"harness": "cli", "agent": "test"}, "test")


class Mapping(Imported):
    """WS3-T1: the facts imported from the test workshop, translated back, give the workshop's facts, key for key."""

    def test_the_way_back_of_the_import(self):
        from probandia.workshop.prototype.mapping import translate_all

        ctx = self.ctx()
        people = self.people()
        by_wid = {p["id"]: p for p in people["personnes"]}
        done = 0
        for _person, fact, t in translate_all(ctx):
            with self.subTest(fact=fact["id"]):
                self.assertTrue(t.linked)
                if t.key == "unions":
                    original = people["unions"][t.index]
                else:
                    value = by_wid[t.person][t.key]
                    original = value[t.index] if t.index is not None else value
                self.assertEqual(t.fact, original)
                done += 1
        self.assertEqual(done, 5)

    def test_a_new_fact_takes_the_markers_of_its_research(self):
        from probandia.workshop.prototype.mapping import translate

        link = yamlio.load(os.path.join(self.dir, "workshop.yaml"))
        link["researches"][self.research] = {"rapport": "paris-1822", "origine": False, "volet": "III",
                                             "chapitre": "I"}
        yamlio.dump(os.path.join(self.dir, "workshop.yaml"), link)
        ctx = self.ctx()
        sophie = ctx.by_pid["sophie-trebuchet-1772"]
        fact = {"id": "sophie-trebuchet-1772.death", "type": "death", "status": "record",
                "date": {"value": "1821-06-27", "qualifier": "exact", "calendar": "gregorian"},
                "place": {"id": None, "as_written": "Paris"}, "source": None, "note": "",
                "uncertain_reading": "« Trébuchet » ou « Trébuchey »", "research": self.research, "volet": 2}
        t = translate(ctx, sophie, fact)
        self.assertEqual((t.person, t.key, t.index, t.linked), ("sophie-trebuchet-1772", "deces", None, False))
        self.assertEqual(t.fact, {"date": "27 juin 1821", "annee": 1821, "lieu": "Paris", "statut": "acte",
                                  "volet": "III", "chapitre": "I", "rapport": "paris-1822",
                                  "note": "LECTURE INCERTAINE : « Trébuchet » ou « Trébuchey »"})
        fact.update(status="refuted", refuted_in={"pass": 3, "volet": 4}, uncertain_reading=None)
        self.assertEqual(translate(ctx, sophie, fact).fact["volet_refute"], "III")
        del link["researches"][self.research]["volet"]
        yamlio.dump(os.path.join(self.dir, "workshop.yaml"), link)
        t = translate(self.ctx(), sophie, fact)
        self.assertEqual((t.fact["volet"], t.fact["volet_refute"]), ("II", "IV"))   # FL-D12: from the fact itself


class Hypotheses(Imported):
    """WS3-T3: an open branch becomes the note « DIVERGENCE NON TRANCHÉE : a ; b », which passes the workshop's check."""

    def test_the_note_of_a_divergence(self):
        from probandia.workshop.prototype.mapping import translate

        ctx = self.ctx()
        leopold = ctx.by_pid["leopold-hugo-1773"]
        birth = next(f for f in leopold["facts"] if f["type"] == "birth")
        note = translate(ctx, leopold, birth).fact["note"]   # the imported divergence: the workshop's own sentence
        self.assertEqual(note, "DIVERGENCE NON TRANCHÉE : né à Nancy selon l'index, à Besançon selon l'arbre en ligne")
        self.assertRegex(note, VALIDATION_PREFIX)
        doc = self.index("hypotheses")
        h = doc["hypotheses"][0]
        h["question"] = "Where was Léopold born?"
        h["hypotheses"] = [{"id": "a", "statement": "à Nancy", "status": "open"},
                           {"id": "b", "statement": "à Besançon", "status": "open"}]
        self.write_index("hypotheses", doc)
        note = translate(self.ctx(), leopold, birth).fact["note"]
        self.assertEqual(note, "DIVERGENCE NON TRANCHÉE : à Nancy ; à Besançon")
        self.assertRegex(note, VALIDATION_PREFIX)
        h["closed"], h["outcome"] = "2026-10-17", "a"                    # a branch settled goes as a plain fact
        h["hypotheses"][1]["status"] = "rejected"
        self.write_index("hypotheses", doc)
        self.assertNotIn("note", translate(self.ctx(), leopold, birth).fact)

    def test_a_divergent_analysis(self):
        from probandia.workshop.prototype.mapping import translate

        doc = self.index("hypotheses")
        doc["hypotheses"] = []
        self.write_index("hypotheses", doc)
        self.write_index("analyses", {"schema": 1, "analyses": [{
            "id": "an-leopold-hugo-1773-birth", "person": "leopold-hugo-1773", "fact_kind": "birth",
            "status": "divergent", "reason": "l'index dit Nancy, l'arbre en ligne Besançon",
            "items": [{"fact": "leopold-hugo-1773.birth", "asserts": "Nancy"}]}]})
        ctx = self.ctx()
        leopold = ctx.by_pid["leopold-hugo-1773"]
        note = translate(ctx, leopold, leopold["facts"][0]).fact["note"]
        self.assertEqual(note, "DIVERGENCE NON TRANCHÉE : l'index dit Nancy, l'arbre en ligne Besançon")
        self.assertRegex(note, VALIDATION_PREFIX)


class Compare(Imported):
    """WS3-T2 and the comparison of WS3 acceptance: new, same, divergent (precision, contradiction), workshop only."""

    def test_each_class(self):
        from probandia.workshop.prototype.compare import compare

        doc = self.index("persons")
        by = {p["id"]: p for p in doc["persons"]}
        victor, sophie, leopold = by["victor-hugo-1802"], by["sophie-trebuchet-1772"], by["leopold-hugo-1773"]
        sophie["facts"].append({"id": "sophie-trebuchet-1772.death", "type": "death", "status": "record",
                                "date": {"value": "1821-06-27", "qualifier": "exact", "calendar": "gregorian"},
                                "place": {"id": None, "as_written": "Paris"}, "source": None, "note": "",
                                "research": self.research})                                # new
        death = next(f for f in victor["facts"] if f["type"] == "death")
        death["date"] = {"value": "1885-05-22", "qualifier": "exact", "calendar": "gregorian"}  # a day in « vers 1885 »
        death["status"] = "record"                                                         # and a stronger status
        marriage = next(f for f in leopold["facts"] if f["type"] == "marriage")
        marriage["place"] = {"id": None, "as_written": "Besançon"}                          # Paris in the workshop
        self.write_index("persons", doc)
        path = os.path.join(self.dir, "commun", "personnes.yaml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("    recherches:\n", '    inhumation: {date: "1er juin 1885", annee: 1885, lieu: "Paris", '
                            "statut: acte, volet: II, chapitre: II}\n    recherches:\n", 1)   # added by hand
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        got = {e.id: (e.cls, e.nature, e.differs) for e in compare(self.ctx())}
        self.assertEqual(got, {
            "victor-hugo-1802.birth": ("same", None, []),
            "victor-hugo-1802.death": ("divergent", "precision", ["date", "statut"]),
            "leopold-hugo-1773.birth": ("same", None, []),
            "leopold-hugo-1773.marriage": ("divergent", "contradiction", ["lieu"]),
            "sophie-trebuchet-1772.birth": ("same", None, []),
            "sophie-trebuchet-1772.death": ("new", None, []),
            "victor-hugo-1802.inhumation": ("workshop-only", None, [])})
        e = next(e for e in compare(self.ctx()) if e.id == "leopold-hugo-1773.marriage")
        self.assertEqual((e.probandia["lieu"], e.workshop["lieu"]), ("Besançon", "Paris"))   # both values kept

    def test_differences(self):
        from probandia.workshop.prototype.compare import differences

        w = {"date": "vers 1850", "annee": 1850, "lieu": "Nancy", "statut": "index"}
        self.assertEqual(differences(dict(w), w), [])
        self.assertEqual(differences(dict(w, date="12 mars 1850"), w), [("date", "precision")])
        self.assertEqual(differences(dict(w, date="12 mars 1851", annee=1851), w), [("date", "contradiction")])
        self.assertEqual(differences(dict(w, statut="acte"), w), [("statut", "precision")])
        self.assertEqual(differences(dict(w, lieu="Besançon"), w), [("lieu", "contradiction")])
        self.assertEqual(differences(dict(w), dict(w, lieu=None)), [("lieu", "precision")])
        self.assertEqual(differences(dict(w, date="entre 1849 et 1851"), w), [("date", "precision")])
        self.assertEqual(differences(dict(w, statut="refute"), dict(w, volet_refute="III")), [])

    def test_a_refutation_is_new(self):
        from probandia.workshop.prototype.compare import compare

        doc = self.index("persons")
        victor = next(p for p in doc["persons"] if p["id"] == "victor-hugo-1802")
        death = next(f for f in victor["facts"] if f["type"] == "death")
        death.update(status="refuted", refuted_in={"pass": 2, "volet": 3})
        self.write_index("persons", doc)
        e = next(e for e in compare(self.ctx()) if e.id == "victor-hugo-1802.death")
        self.assertEqual((e.cls, e.nature, e.probandia["volet_refute"]), ("new", "refutation", "III"))


class MarriageForms(unittest.TestCase):
    """T175: the two other ways the real workshop writes a marriage come back as they were imported."""

    def test_on_the_person_and_with_a_husband_in_words(self):
        from probandia import workshop
        from probandia.workshop.prototype.compare import compare
        from probandia.workshop.prototype.mapping import Context

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = os.path.join(tmp.name, "workshop")
        shutil.copytree(WORKSHOP, folder)
        path = os.path.join(folder, "commun", "personnes.yaml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("    recherches:\n", '    conjoint: adele-foucher-1803\n    mariage: {date: "12 octobre 1822", '
                            'annee: 1822, lieu: "Paris", statut: acte, volet: I, chapitre: I}\n    recherches:\n', 1)
        text += ('\n  - epoux: null\n    conjoint_libre: "Victor LAHORIE"\n    epouse: sophie-trebuchet-1772\n'
                 '    annee: 1808\n    lieu: Paris\n    statut: hypothese\n    volet: II\n    chapitre: II\n')
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "user"), "PROBANDIA_SESSION": "test",
               "CLAUDE_CONFIG_DIR": os.path.join(tmp.name, "claude"), "LANG": "en_US.UTF-8"}
        out = io.StringIO()
        code = cli.main(["new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                         "--workshop", "import"], stdout=out, environ=env, cwd=folder)
        self.assertEqual(code, 0, out.getvalue())
        got = {(e.id, e.key): e.cls for e in compare(Context(folder, workshop.load(folder)))}
        self.assertEqual(got[("victor-hugo-1802.marriage", "mariage")], "same")
        self.assertEqual(got[("sophie-trebuchet-1772.marriage", "unions")], "same")
        self.assertNotIn("workshop-only", set(got.values()))
