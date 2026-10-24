"""Working with an existing workshop of the prototype (docs/workshop-sync.md)."""
import hashlib
import io
import os
import shutil
import tempfile
import unittest

from probandia import cli
from probandia.util import yamlio
from probandia.util.schema import validate_document
from tests import ROOT

WORKSHOP = os.path.join(ROOT, "tests", "fixtures", "workshop")
CRLF = os.path.join(ROOT, "tests", "fixtures", "workshop-crlf")
FACT_KEYS = ("naissance", "bapteme", "mariage", "deces", "inhumation", "residence", "profession")


def people_bytes(folder):
    with open(os.path.join(folder, "commun", "personnes.yaml"), "rb") as fh:
        return fh.read()


class Fixture(unittest.TestCase):
    """WS1-T1: the test workshop looks like the real one."""

    def test_two_line_endings_same_data(self):
        lf, crlf = people_bytes(WORKSHOP), people_bytes(CRLF)
        self.assertNotIn(b"\r", lf)
        self.assertEqual(crlf.count(b"\r\n"), lf.count(b"\n"))
        self.assertEqual(yamlio.loads(crlf.decode("utf-8")), yamlio.loads(lf.decode("utf-8")))

    def test_the_shapes_of_the_real_workshop(self):
        text = people_bytes(WORKSHOP).decode("utf-8")
        data = yamlio.loads(text)
        self.assertTrue(text.startswith("# ─"))                        # a header of comments
        self.assertEqual(text.count("  # ═══ GÉNÉRATION"), 2)            # section banners
        self.assertRegex(text, r"\n    naissance: \{[^}]*,\n {16}\S")  # a flow map on several lines
        self.assertIn("\n  - epoux: ", text)                             # unions in block style
        self.assertEqual(data["meta"]["racine"], "victor-hugo-1802")
        facts = [f for p in data["personnes"] for k in FACT_KEYS if isinstance(p.get(k), dict) for f in [p[k]]]
        facts += [f for p in data["personnes"] for f in p.get("recherches") or []] + data["unions"]
        for f in facts:
            self.assertTrue({"statut", "volet", "chapitre", "annee"} <= set(f), f)
        dates = {f.get("date") for f in facts}
        self.assertTrue({"14 août 2026 à 10 h 30", "vers 1885"} <= dates)
        reports = {name: yamlio.load(os.path.join(WORKSHOP, "rapports", name, "rapport.yaml"))["origine"]
                   for name in ("hugo-besancon", "paris-1822")}
        self.assertEqual(reports, {"hugo-besancon": True, "paris-1822": False})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "workshop")   # the project is the workshop itself, as in the author's
        shutil.copytree(WORKSHOP, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "PROBANDIA_SESSION": "test",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"), "LANG": "en_US.UTF-8"}

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        for line in out.splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    def link(self):
        return yamlio.load(os.path.join(self.dir, "workshop.yaml"))

    def imported(self):
        """The test workshop imported by new, as in the author's session: the id of the research opened."""
        code, out = self.call("new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                              "--workshop", "import")
        self.assertEqual(code, 0, out)
        return self.value(out, "RESEARCH")


class ImportLink(Base):
    """WS1-T3: import writes workshop.yaml with what Probandia's records cannot hold."""

    def test_the_link_of_an_import(self):
        code, out = self.call("new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                              "--workshop", "import")
        self.assertEqual(code, 0, out)
        link = self.link()
        validate_document("workshop-link", link, "workshop.yaml")
        self.assertEqual((link["adapter"], link["root"]), ("prototype", "."))
        self.assertEqual(link["families"], {"hugo": ["victor-hugo-1802", "leopold-hugo-1773",
                                                     "sophie-trebuchet-1772"]})
        self.assertEqual(link["persons"]["victor-hugo-1802"],
                         {"workshop": "victor-hugo-1802", "generation": "II", "volet": "I", "chapitre": "I"})
        self.assertEqual(link["facts"]["victor-hugo-1802.death"],
                         {"person": "victor-hugo-1802", "key": "deces", "index": None, "annee": 1885,
                          "date_text": "vers 1885", "volet": "II", "chapitre": "II", "rapport": "hugo-besancon"})
        self.assertEqual(link["facts"]["leopold-hugo-1773.marriage"],
                         {"person": "leopold-hugo-1773", "key": "unions", "index": 0, "annee": 1797,
                          "date_text": "1797", "volet": "II", "chapitre": "II", "rapport": None})
        self.assertEqual(list(link["researches"].values()), [{"rapport": "hugo-besancon", "origine": True}])
        with open(os.path.join(self.dir, "commun", "personnes.yaml"), "rb") as fh:
            self.assertEqual(link["synced"]["sha256"], hashlib.sha256(fh.read()).hexdigest())
        with open(os.path.join(self.dir, "work", "import-report.md"), encoding="utf-8") as fh:
            report = fh.read()
        self.assertNotIn("generation", report.split("## Not converted")[1])
        self.assertIn("| volet, chapitre, annee, generation | workshop.yaml | 5 facts, 3 persons |", report)

    def test_the_link_says_imported_without_the_import_report(self):
        # WS1-T4: workshop.yaml, not work/import-report.md, tells that the workshop was imported
        from probandia.importer import workshop_pending

        code, out = self.call("new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                              "--workshop", "import")
        self.assertEqual(code, 0, out)
        os.remove(os.path.join(self.dir, "work", "import-report.md"))
        self.assertFalse(workshop_pending(self.dir))
        code, out = self.call("new", "Who was Sophie Trébuchet?", "--mode", "session", "--family", "hugo")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.value(out, "WORKSHOP"))

    def test_a_second_import_is_refused_towards_pull(self):
        code, out = self.call("new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                              "--workshop", "import")
        self.assertEqual(code, 0, out)
        code, out = self.call("import", self.dir)
        self.assertEqual(code, 2, out)
        self.assertEqual(self.value(out, "REASON"), "already-imported")
        self.assertIn("workshop pull", out)


class Link(Base):
    """WS1-T5: a research tied to a report of the workshop, its volet and chapter asked once."""

    def test_the_report_asked_once_then_its_last_markers(self):
        rid = self.imported()
        code, out = self.call("workshop", "link", rid)
        self.assertEqual(code, 3, out)
        self.assertEqual((self.value(out, "QUESTION"), self.value(out, "CHOICES")),
                         ("workshop_report", "hugo-besancon|paris-1822|new"))
        code, out = self.call("workshop", "link", rid, "--report", "hugo-besancon")
        self.assertEqual(code, 3, out)
        self.assertEqual(self.value(out, "QUESTIONS"), "workshop_volet|workshop_chapitre")
        # the report of origin owns the facts without a rapport key: its last ones are II, II
        self.assertEqual((self.value(out, "DEFAULT_WORKSHOP_VOLET"), self.value(out, "DEFAULT_WORKSHOP_CHAPITRE")),
                         ("II", "II"))
        code, out = self.call("workshop", "link", rid, "--report", "hugo-besancon", "--volet", "iii",
                              "--chapitre", "IV")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.link()["researches"][rid],
                         {"rapport": "hugo-besancon", "origine": True, "volet": "III", "chapitre": "IV"})
        code, out = self.call("workshop", "link", rid)   # asked once: answered from the link afterwards
        self.assertEqual((code, self.value(out, "CHANGED"), self.value(out, "VOLET")), (0, "false", "III"))

    def test_new_report_and_wrong_values(self):
        rid = self.imported()
        code, out = self.call("workshop", "link", rid, "--report", "new")
        self.assertEqual((code, self.value(out, "REASON")), (2, "no-report"))
        self.assertIn("nouveau_rapport.py", out)
        code, out = self.call("workshop", "link", rid, "--report", "elsewhere")
        self.assertEqual((code, self.value(out, "REASON")), (2, "unknown-report"))
        code, out = self.call("workshop", "link", rid, "--report", "paris-1822", "--volet", "3", "--chapitre", "I")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-roman"))

    def test_headless_takes_the_last_markers_or_refuses(self):
        rid = self.imported()
        env = {"PROBANDIA_HEADLESS": "1"}
        code, out = self.call("workshop", "link", rid, env=env)
        self.assertEqual((code, self.value(out, "REASON")), (2, "report-needed"))
        code, out = self.call("workshop", "link", rid, "--report", "paris-1822", env=env)
        self.assertEqual((code, self.value(out, "REASON")), (2, "markers-needed"))   # no fact of its own yet
        code, out = self.call("workshop", "link", rid, "--report", "hugo-besancon", env=env)
        self.assertEqual((code, self.value(out, "VOLET"), self.value(out, "CHAPITRE")), (0, "II", "II"))

    def test_a_project_without_workshop(self):
        shutil.rmtree(self.dir)
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), self.dir)
        code, out = self.call("workshop", "link", "2026-09-30-parents-of-victor-hugo")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-linked"))


class Acceptance(Base):
    """WS1 acceptance: import the test workshop, open a research, tie it to the report that is not the
    origin: workshop.yaml is valid and names it. A second import refuses, pointing to workshop pull."""

    def test_ws1(self):
        rid = self.imported()
        code, out = self.call("workshop", "link", rid, "--report", "paris-1822", "--volet", "III",
                              "--chapitre", "I")
        self.assertEqual(code, 0, out)
        link = self.link()
        validate_document("workshop-link", link, "workshop.yaml")
        self.assertEqual(link["researches"][rid],
                         {"rapport": "paris-1822", "origine": False, "volet": "III", "chapitre": "I"})
        code, out = self.call("import", self.dir)
        self.assertEqual((code, self.value(out, "REASON")), (2, "already-imported"))
        self.assertIn("workshop pull", out)


class Synced(unittest.TestCase):
    """WS4: the test workshop imported, a research tied to paris-1822, and three changes: a new fact in
    Probandia (Sophie's death), a divergent one (Victor's death, a day and a record), and a fact added by hand
    in the workshop (Victor's burial)."""

    def setUp(self):
        from tests.unit.test_workshop_mapping import imported_workshop

        src, self.research = imported_workshop()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shutil.copytree(src, tmp.name, dirs_exist_ok=True)
        self.dir = os.path.join(tmp.name, "workshop")
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "user"), "PROBANDIA_SESSION": "test",
                    "CLAUDE_CONFIG_DIR": os.path.join(tmp.name, "claude"), "LANG": "en_US.UTF-8"}
        self.people = os.path.join(self.dir, "commun", "personnes.yaml")

    call = Base.call
    value = Base.value
    link = Base.link

    def changes(self, hand=True):
        from probandia.indexes import FamilyIndexes

        code, out = self.call("workshop", "link", self.research, "--report", "paris-1822", "--volet", "III",
                              "--chapitre", "I")
        self.assertEqual(code, 0, out)
        idx = FamilyIndexes(self.dir, "hugo")
        doc = idx.load("persons")
        by = {p["id"]: p for p in doc["persons"]}
        by["sophie-trebuchet-1772"]["facts"].append({
            "id": "sophie-trebuchet-1772.death", "type": "death", "status": "record",
            "date": {"value": "1821-06-27", "qualifier": "exact", "calendar": "gregorian"},
            "place": {"id": None, "as_written": "Paris"}, "source": None, "note": "", "research": self.research})
        death = next(f for f in by["victor-hugo-1802"]["facts"] if f["type"] == "death")
        death.update(status="record", date={"value": "1885-05-22", "qualifier": "exact", "calendar": "gregorian"})
        idx.write({"persons": doc}, {"harness": "cli", "agent": "test"}, "test")
        if hand:
            with open(self.people, encoding="utf-8") as fh:
                text = fh.read()
            text = text.replace("    recherches:\n", '    inhumation: {date: "1er juin 1885", annee: 1885, lieu: '
                                '"Paris", statut: acte, volet: II, chapitre: II}\n    recherches:\n', 1)
            with open(self.people, "w", encoding="utf-8") as fh:
                fh.write(text)

    def people_text(self):
        with open(self.people, encoding="utf-8") as fh:
            return fh.read()


class Status(Synced):
    """WS4-T1: workshop status, its contract, its readable screen and its JSON."""

    def test_the_contract(self):
        code, out = self.call("workshop", "status")
        self.assertEqual(code, 0, out)
        self.assertEqual([self.value(out, k) for k in ("ADAPTER", "ROOT", "LINKED", "NEW", "SAME", "DIVERGENT",
                                                       "WORKSHOP_ONLY", "CHANGED_SINCE_SYNC", "NEXT")],
                         ["prototype", ".", "true", "0", "5", "0", "0", "false", "-"])
        self.changes()
        code, out = self.call("workshop", "status")
        self.assertEqual([self.value(out, k) for k in ("NEW", "SAME", "DIVERGENT", "WORKSHOP_ONLY",
                                                       "CHANGED_SINCE_SYNC", "NEXT")],
                         ["1", "4", "1", "1", "true", "workshop push"])
        self.assertIn("- divergent=victor-hugo-1802.death precision: date, statut", out)
        self.assertLessEqual(len(out.splitlines()), 40)
        code, out = self.call("workshop", "status", self.research)   # one research: its own facts only
        self.assertEqual([self.value(out, k) for k in ("NEW", "SAME", "WORKSHOP_ONLY")], ["1", "0", "0"])

    def test_the_screen_and_the_json(self):
        import json

        self.changes()
        code, out = self.call("--output-format", "human", "workshop", "status")
        self.assertEqual(code, 1 if "WARN" in out else 0, out)
        for words in ("adapter", "prototype", "workshop only", "changed since sync", "workshop push"):
            self.assertIn(words, out)
        code, out = self.call("--json", "workshop", "status")
        doc = json.loads(out)
        self.assertEqual((doc["status"], doc["values"]["NEW"], doc["values"]["CHANGED_SINCE_SYNC"]),
                         ("WARN", 1, True))
        rows = {r["fact"]: r for r in doc["data"]["facts"]}
        self.assertEqual(rows["sophie-trebuchet-1772.death"]["class"], "new")
        self.assertEqual(rows["victor-hugo-1802.death"]["workshop"]["date"], "vers 1885")
        self.assertEqual(rows["victor-hugo-1802.inhumation"]["class"], "workshop-only")

    def test_a_project_without_workshop(self):
        shutil.rmtree(self.dir)
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), self.dir)
        code, out = self.call("workshop", "status")
        self.assertEqual((code, self.value(out, "LINKED")), (0, "false"))
        code, out = self.call("workshop", "diff")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-linked"))


class Diff(Synced):
    """WS4-T2: workshop diff, and the lines a push would insert, against reference files."""

    def test_reference_outputs(self):
        from tests.unit.test_human import golden

        folder = os.path.join(ROOT, "tests", "golden", "workshop")
        self.changes()
        code, out = self.call("workshop", "diff")
        self.assertEqual(code, 0, out)
        golden(self, "diff", out, folder)
        code, out = self.call("workshop", "diff", "--format", "yaml")
        self.assertEqual(code, 0, out)
        golden(self, "diff", out, folder, ".yaml")


class Push(Synced):
    """WS4-T3 and WS4 acceptance without pull: status, diff, push --dry-run, push, status."""

    def marriage(self):
        from probandia.indexes import FamilyIndexes

        idx = FamilyIndexes(self.dir, "hugo")
        doc = idx.load("persons")
        victor = next(p for p in doc["persons"] if p["id"] == "victor-hugo-1802")
        victor["facts"].append({"id": "victor-hugo-1802.marriage", "type": "marriage", "status": "record",
                                "date": {"value": "1822-10-12", "qualifier": "exact", "calendar": "gregorian"},
                                "place": {"id": None, "as_written": "Paris"}, "source": None, "note": "",
                                "research": self.research})
        victor["spouses"].append({"person": "adele-foucher-1803", "marriage": "victor-hugo-1802.marriage"})
        doc["persons"].append({"id": "adele-foucher-1803", "names": {"given": "Adèle", "surname": "FOUCHER"},
                               "sex": "F", "living": "auto", "parents": {"father": None, "mother": None},
                               "spouses": [{"person": "victor-hugo-1802", "marriage": "victor-hugo-1802.marriage"}],
                               "facts": []})
        idx.write({"persons": doc}, {"harness": "cli", "agent": "test"}, "test")

    def test_acceptance(self):
        import difflib

        self.changes(hand=False)
        self.marriage()
        before = self.people_text()
        code, out = self.call("workshop", "status")
        self.assertEqual([self.value(out, k) for k in ("NEW", "DIVERGENT", "NEXT")], ["2", "1", "workshop push"])
        code, out = self.call("workshop", "diff")
        self.assertIn("+ victor-hugo-1802.marriage", out)
        code, out = self.call("workshop", "push", "--dry-run")
        self.assertEqual((code, self.value(out, "PUSHED"), self.value(out, "PERSONS"), self.value(out, "DRY_RUN")),
                         (0, "2", "1", "true"), out)
        self.assertEqual(self.people_text(), before)                     # nothing written
        code, out = self.call("workshop", "push", "--agent", "researcher")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-allowed"))
        code, out = self.call("workshop", "push")
        self.assertEqual((code, self.value(out, "PUSHED"), self.value(out, "PERSONS")), (0, "2", "1"), out)
        after = self.people_text()
        diff = [x for x in difflib.ndiff(before.splitlines(), after.splitlines()) if x[:1] in "+-"]
        self.assertEqual([x for x in diff if x.startswith("- ")], ["-   mis_a_jour: 2026-08-10"])
        self.assertIn("+   # Ajouts de Probandia — à reclasser", diff)
        self.assertIn("+   - id: adele-foucher-1803", diff)
        self.assertIn("+   - epoux: victor-hugo-1802", diff)
        code, out = self.call("workshop", "status")
        self.assertEqual([self.value(out, k) for k in ("NEW", "DIVERGENT", "CHANGED_SINCE_SYNC", "NEXT")],
                         ["0", "1", "false", "workshop diff"])
        link = self.link()
        validate_document("workshop-link", link, "workshop.yaml")
        self.assertEqual(link["facts"]["victor-hugo-1802.marriage"]["key"], "unions")
        self.assertEqual(link["persons"]["adele-foucher-1803"]["workshop"], "adele-foucher-1803")
        self.assertEqual(link["synced"]["pushed"], 2)
        from probandia import events
        from probandia.research import Research

        log = events.read(Research(self.dir, "hugo", self.research).events_path)
        pushed = [e for e in log if e["type"] == "workshop.pushed"]
        self.assertEqual(sorted(pushed[0]["payload"]["facts"]), ["sophie-trebuchet-1772.death",
                                                                  "victor-hugo-1802.marriage"])
        code, out = self.call("verify", self.research)
        self.assertNotIn("V-1 FAIL", out)

    def test_accept_a_divergent_fact(self):
        self.changes(hand=False)
        code, out = self.call("workshop", "push", "--accept", "victor-hugo-1802.birth")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-divergent"))
        code, out = self.call("workshop", "push", "--accept", "victor-hugo-1802.death")
        self.assertEqual((code, self.value(out, "PUSHED"), self.value(out, "DIVERGENT")), (0, "2", "0"), out)
        self.assertIn('    deces: {date: "22 mai 1885", annee: 1885, lieu: "Paris", statut: acte,', self.people_text())
        code, out = self.call("workshop", "status")
        self.assertEqual([self.value(out, k) for k in ("NEW", "SAME", "DIVERGENT")], ["0", "6", "0"])

    def test_a_changed_file_stops_the_push(self):
        from probandia import workshop as ws

        self.changes(hand=False)
        plan = ws.Plan(ws.State(self.dir, self.link()))
        with open(self.people, "a", encoding="utf-8") as fh:
            fh.write("# by hand\n")
        from probandia.workshop.prototype.write import Changed

        with self.assertRaises(Changed):
            ws.push(self.dir, plan, {"harness": "cli", "agent": "session"})
        self.assertTrue(self.people_text().endswith("# by hand\n"))
        self.assertNotIn("sophie-trebuchet-1772.death", self.link()["facts"])


class Pull(Synced):
    """WS3-T5, WS4-T4: a date corrected and a fact added by hand in the workshop become a proposal apply
    accepts; the cycle « change, pull, apply, status » ends at CHANGED_SINCE_SYNC=false."""

    def test_the_cycle(self):
        text = self.people_text().replace('deces: {date: "vers 1885", annee: 1885,',
                                          'deces: {date: "22 mai 1885", annee: 1885,', 1)
        text = text.replace("    recherches:\n", '    inhumation: {date: "1er juin 1885", annee: 1885, lieu: '
                            '"Paris", statut: acte, volet: II, chapitre: II, source: "Registre des inhumations, '
                            'Paris.", image: images/ec-1802-112.jpg}\n    recherches:\n', 1)
        with open(self.people, "w", encoding="utf-8") as fh:
            fh.write(text)
        code, out = self.call("workshop", "status")
        self.assertEqual([self.value(out, k) for k in ("DIVERGENT", "WORKSHOP_ONLY", "CHANGED_SINCE_SYNC")],
                         ["1", "1", "true"])
        code, out = self.call("workshop", "pull", "--agent", "researcher")
        self.assertEqual((code, self.value(out, "REASON")), (2, "not-allowed"))
        code, out = self.call("workshop", "pull")
        self.assertEqual((code, self.value(out, "PULLED"), self.value(out, "CORRECTED")), (0, "2", "1"), out)
        proposal = self.value(out, "PROPOSAL")
        self.assertEqual(self.value(out, "NEXT"), f"apply {proposal}")
        code, out = self.call("apply", proposal)
        self.assertEqual(code, 0, out)
        code, out = self.call("workshop", "status")
        self.assertEqual([self.value(out, k) for k in ("NEW", "DIVERGENT", "WORKSHOP_ONLY", "CHANGED_SINCE_SYNC")],
                         ["0", "0", "0", "false"], out)
        from probandia.indexes import FamilyIndexes

        facts = {f["id"]: f for p in FamilyIndexes(self.dir, "hugo").items("persons") for f in p["facts"]}
        self.assertEqual(facts["victor-hugo-1802.death"]["status"], "refuted")      # never deleted
        self.assertEqual(facts["victor-hugo-1802.death.2"]["date"]["original"], "22 mai 1885")
        self.assertEqual(facts["victor-hugo-1802.burial"]["place"]["as_written"], "Paris")
        validate_document("workshop-link", self.link(), "workshop.yaml")

    def test_nothing_to_pull(self):
        code, out = self.call("workshop", "pull")
        self.assertEqual((code, self.value(out, "PULLED"), self.value(out, "NEXT")), (0, "0", "-"))


class SecondImport(Synced):
    """T170: a second import names only commands that exist, and import says what it reads."""

    def test_every_command_it_names_exists(self):
        import re

        code, out = self.call("import", self.dir)
        self.assertEqual((code, self.value(out, "REASON")), (2, "already-imported"))
        named = re.findall(r"\bworkshop (status|diff|push|pull|link)\b", out)
        self.assertEqual(sorted(set(named)), ["diff", "pull", "status"])
        import contextlib

        for action in set(named):   # argparse prints the help and exits
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
                self.call("workshop", action, "--help")
            self.assertEqual(stop.exception.code, 0, action)
            self.assertIn("workshop", out.getvalue())

    def test_the_description_of_import(self):
        for path in ("src", "commands", "locales"):
            for folder, _dirs, files in os.walk(os.path.join(ROOT, path)):
                for name in files:
                    if name.endswith((".py", ".md", ".po", ".pot")):
                        with open(os.path.join(folder, name), encoding="utf-8") as fh:
                            self.assertFalse("of the prototype" in fh.read(), os.path.join(folder, name))


class Report(Synced):
    """WS5-T1, WS5-T2: the settings workshop.sync and workshop.check; after an apply, the report proposed."""

    def setUp(self):
        super().setUp()
        code, out = self.call("workshop", "link", self.research, "--report", "paris-1822", "--volet", "III",
                              "--chapitre", "I")
        self.assertEqual(code, 0, out)

    def proposal(self):
        from probandia.util.ids import ulid

        sid = f"src-{ulid()}"
        doc = {"schema": 1, "research": self.research, "pass": 1, "author": {"harness": "cli", "agent": "session"},
               "sources": [{"id": sid, "citation": "Tables décennales de Paris, 1813-1822."}],
               "facts": [{"id": "sophie-trebuchet-1772.death", "type": "death", "status": "index",
                          "date": {"value": "1821-06-27", "qualifier": "exact"},
                          "place": {"id": None, "as_written": "Paris"}, "source": sid, "note": ""}]}
        path = os.path.join(self.dir, "proposal.yaml")
        yamlio.dump(path, doc)
        code, out = self.call("propose", self.research, path)
        self.assertEqual(code, 0, out)
        return self.value(out, "PROPOSAL")

    def setting(self, value):
        with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
            fh.write(f'\n[workshop]\nsync = "{value}"\n')

    def test_config_shows_the_two_settings(self):
        code, out = self.call("--json", "config", "show", "--origin", "--all")
        self.assertEqual(code, 0, out)
        self.assertIn("workshop.sync", out)
        self.assertIn("workshop.check", out)
        from probandia.config.tomlfile import template

        self.assertIn('# workshop.sync = "ask"', template(1))

    def test_off_says_nothing(self):
        self.setting("off")
        code, out = self.call("apply", self.proposal())
        self.assertEqual((code, self.value(out, "WORKSHOP_NEW")), (0, None), out)

    def test_ask_once_a_pass(self):
        code, out = self.call("apply", self.proposal())
        self.assertEqual(code, 3, out)
        self.assertEqual([self.value(out, k) for k in ("QUESTION", "CHOICES", "WORKSHOP_NEW", "WORKSHOP_DIVERGENT")],
                         ["workshop_push", "push|later", "1", "0"])
        self.assertIn("workshop push", out)
        from probandia.indexes import FamilyIndexes

        facts = {f["id"] for p in FamilyIndexes(self.dir, "hugo").items("persons") for f in p["facts"]}
        self.assertIn("sophie-trebuchet-1772.death", facts)                   # applied all the same
        doc = yamlio.load(os.path.join(self.dir, "proposal.yaml"))
        doc["facts"][0].update(id="sophie-trebuchet-1772.burial", type="burial")
        yamlio.dump(os.path.join(self.dir, "proposal.yaml"), doc)
        code, out = self.call("propose", self.research, os.path.join(self.dir, "proposal.yaml"), "--apply")
        self.assertEqual((code, self.value(out, "APPLIED"), self.value(out, "WORKSHOP_NEW")), (0, "true", "2"), out)
        self.assertIsNone(self.value(out, "QUESTION"))                         # asked once in the pass
        self.assertIn("2 new fact(s) of this research are not in the workshop yet: workshop push", out)

    def test_auto_pushes_the_new_facts_only(self):
        self.setting("auto")
        self.changes(hand=False)   # Sophie's death new and Victor's death divergent, before the apply
        from probandia.indexes import FamilyIndexes

        idx = FamilyIndexes(self.dir, "hugo")
        doc = idx.load("persons")
        victor = next(p for p in doc["persons"] if p["id"] == "victor-hugo-1802")
        next(f for f in victor["facts"] if f["type"] == "death")["research"] = self.research   # found here
        idx.write({"persons": doc}, {"harness": "cli", "agent": "test"}, "test")
        doc_id = self.proposal_burial()
        code, out = self.call("apply", doc_id)
        self.assertEqual(code, 0, out)
        self.assertEqual([self.value(out, k) for k in ("WORKSHOP_PUSHED", "WORKSHOP_NEW", "WORKSHOP_DIVERGENT")],
                         ["2", "0", "1"])
        text = self.people_text()
        self.assertIn("inhumation: {", text)
        self.assertIn('deces: {date: "vers 1885"', text)                     # the divergent one stays

    def proposal_burial(self):
        doc_id = None
        from probandia.util.ids import ulid

        sid = f"src-{ulid()}"
        doc = {"schema": 1, "research": self.research, "pass": 1, "author": {"harness": "cli", "agent": "session"},
               "sources": [{"id": sid, "citation": "Registre des inhumations de Paris, 1821."}],
               "facts": [{"id": "sophie-trebuchet-1772.burial", "type": "burial", "status": "index",
                          "date": {"value": "1821-06-29", "qualifier": "exact"},
                          "place": {"id": None, "as_written": "Paris"}, "source": sid, "note": ""}]}
        path = os.path.join(self.dir, "proposal.yaml")
        yamlio.dump(path, doc)
        code, out = self.call("propose", self.research, path)
        self.assertEqual(code, 0, out)
        doc_id = self.value(out, "PROPOSAL")
        return doc_id


class Rule4(Synced):
    """WS5-T3, WS5-T4: pass end keeps the workshop's rule 4, unless deferred with a reason; the digest says
    where the workshop stands."""

    def setUp(self):
        Synced.setUp(self)
        code, out = self.call("workshop", "link", self.research, "--report", "paris-1822", "--volet", "III",
                              "--chapitre", "I")
        self.assertEqual(code, 0, out)

    proposal = Report.proposal
    setting = Report.setting

    def test_refused_then_deferred(self):
        code, out = self.call("apply", self.proposal())
        self.assertEqual(code, 3, out)                                       # asked once: later
        code, out = self.call("pass", "end", self.research, "--summary", "a death found")
        self.assertEqual((code, self.value(out, "REASON"), self.value(out, "WORKSHOP_NEW")),
                         (2, "workshop-not-reported", "1"), out)
        code, out = self.call("pass", "end", self.research, "--summary", "a death found",
                              "--defer-workshop", "the chapter is not written yet")
        self.assertIn(code, (0, 1), out)
        self.assertEqual(self.value(out, "LOCK"), "released", out)
        from probandia import events
        from probandia.research import Research

        ended = [e for e in events.read(Research(self.dir, "hugo", self.research).events_path)
                 if e["type"] == "pass.ended"][-1]
        self.assertEqual(ended["payload"]["workshop_deferred"],
                         {"facts": 1, "reason": "the chapter is not written yet"})
        code, out = self.call("digest", self.research)
        self.assertIn("the chapter is not written yet", out)
        self.assertIn("WORKSHOP: 1 new, 0 divergent, workshop changed since the last sync: no", out)

    def test_the_digest_line_within_its_cap(self):
        from probandia.config import load as load_config
        from probandia.digest import build
        from probandia.research import Research

        self.changes()
        config = load_config(self.dir, self.env)
        lines = build(self.dir, Research(self.dir, "hugo", self.research), config)
        self.assertIn("WORKSHOP: 1 new, 0 divergent, workshop changed since the last sync: yes", lines)
        self.assertLessEqual(len(lines), config.get("digest.max_lines"))

    def test_off_and_a_project_without_workshop_close_as_before(self):
        self.setting("off")
        code, out = self.call("apply", self.proposal())
        self.assertEqual(code, 0, out)
        code, out = self.call("pass", "end", self.research, "--summary", "a death found")
        self.assertEqual(self.value(out, "LOCK"), "released", out)


def proposal_of(test, research, fact_id, ftype, date, pass_no):
    """A proposal of one indexed fact, stored by propose; its id."""
    from probandia.util.ids import ulid

    sid = f"src-{ulid()}"
    doc = {"schema": 1, "research": research, "pass": pass_no, "author": {"harness": "cli", "agent": "session"},
           "sources": [{"id": sid, "citation": f"Tables décennales de Paris ({fact_id})."}],
           "facts": [{"id": fact_id, "type": ftype, "status": "index", "date": {"value": date, "qualifier": "exact"},
                      "place": {"id": None, "as_written": "Paris"}, "source": sid, "note": ""}]}
    path = os.path.join(test.dir, f"proposal-{ftype}.yaml")
    yamlio.dump(path, doc)
    code, out = test.call("propose", research, path)
    test.assertEqual(code, 0, out)
    return test.value(out, "PROPOSAL")


class Guide(Base):
    """WS5-T5 and WS5 acceptance: NEXT names skills/research/workshop.md in a linked project; a pass whose push
    is accepted closes, a pass left with a new fact not reported does not."""

    def test_next_of_new_resume_and_apply(self):
        from probandia.cli.workshop_cmd import GUIDE

        code, out = self.call("new", "Where did Victor Hugo die?", "--mode", "session", "--family", "hugo",
                              "--workshop", "import")
        self.assertEqual((code, self.value(out, "NEXT")), (0, GUIDE), out)
        rid = self.value(out, "RESEARCH")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, *GUIDE.split(" ", 1)[1].split("/"))))
        code, out = self.call("workshop", "link", rid, "--report", "paris-1822", "--volet", "III", "--chapitre", "I")
        code, out = self.call("apply", proposal_of(self, rid, "sophie-trebuchet-1772.death", "death",
                                                   "1821-06-27", 1))
        self.assertEqual((code, self.value(out, "NEXT")), (3, GUIDE), out)
        code, out = self.call("resume", rid, "--interrupted", "continue")
        self.assertEqual((code, self.value(out, "NEXT")), (0, GUIDE), out)

    def test_nothing_named_without_workshop(self):
        shutil.rmtree(self.dir)
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), self.dir)
        code, out = self.call("resume", "2026-09-30-parents-of-victor-hugo", "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertNotEqual(self.value(out, "NEXT"), "read skills/research/workshop.md")

    def test_ws5_acceptance(self):
        rid = self.imported()
        code, out = self.call("workshop", "link", rid, "--report", "paris-1822", "--volet", "III", "--chapitre", "I")
        self.assertEqual(code, 0, out)
        code, out = self.call("apply", proposal_of(self, rid, "sophie-trebuchet-1772.death", "death",
                                                   "1821-06-27", 1))
        self.assertEqual((code, self.value(out, "QUESTION")), (3, "workshop_push"), out)
        code, out = self.call("workshop", "push", rid)                            # the answer: push
        self.assertEqual((code, self.value(out, "PUSHED")), (0, "1"), out)
        code, out = self.call("pass", "end", rid, "--summary", "her death")
        self.assertEqual(self.value(out, "LOCK"), "released", out)
        code, out = self.call("resume", rid, "--mode", "session")
        self.assertEqual((code, self.value(out, "PASS")), (0, "2"), out)
        code, out = self.call("apply", proposal_of(self, rid, "sophie-trebuchet-1772.burial", "burial",
                                                   "1821-06-29", 2))
        self.assertEqual((code, self.value(out, "QUESTION")), (3, "workshop_push"), out)   # a new pass: asked again
        code, out = self.call("pass", "end", rid, "--summary", "her burial")              # the answer was: later
        self.assertEqual((code, self.value(out, "REASON")), (2, "workshop-not-reported"), out)


class Checks(Synced):
    """WS6 and its acceptance: workshop.check after a push, the reminder of build.py at pass end, doctor."""

    def setUp(self):
        Synced.setUp(self)
        self.changes(hand=False)

    def settings(self, check=None, chapitre="I"):
        code, out = self.call("workshop", "link", self.research, "--report", "paris-1822", "--volet", "III",
                              "--chapitre", chapitre)
        self.assertEqual(code, 0, out)
        if check:
            with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
                fh.write(f'\n[workshop]\ncheck = "{check}"\n')

    def test_a_correct_push_passes_the_check(self):
        self.settings("python outils/verifier.py")
        code, out = self.call("workshop", "push")
        self.assertEqual((code, self.value(out, "PUSHED"), self.value(out, "CHECK")), (0, "1", "passed"), out)
        self.assertIn("- check=6 facts checked, 0 error(s)", out)

    def test_a_failing_check_leaves_the_file_as_written(self):
        with open(os.path.join(self.dir, "outils", "fails.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys\nprint('one error')\nsys.exit(1)\n")
        self.settings("python outils/fails.py")
        code, out = self.call("workshop", "push")
        self.assertEqual((code, self.value(out, "CHECK"), self.value(out, "NEXT")),
                         (0, "failed", "python outils/fails.py"), out)
        self.assertIn("- check=one error", out)
        people = yamlio.loads(self.people_text())                          # still YAML, the fact in it
        self.assertEqual(people["personnes"][2]["deces"]["date"], "27 juin 1821")

    def test_an_unknown_chapter_is_refused_before_writing_and_checking(self):
        self.settings("python outils/verifier.py", chapitre="IX")
        before = self.people_text()
        code, out = self.call("workshop", "push")
        self.assertEqual([self.value(out, k) for k in ("PUSHED", "BLOCKED", "CHECK")], ["0", "1", None], out)
        self.assertIn("chapter IX is unknown to the report paris-1822", out)
        self.assertEqual(self.people_text(), before)

    def test_no_check_set_recalls_the_command(self):
        self.settings()
        code, out = self.call("workshop", "push")
        self.assertEqual(self.value(out, "CHECK"), "not-set")
        self.assertIn("python outils/verifier.py", out)

    def test_the_build_reminder_once_and_only_after_a_push(self):
        self.settings()
        code, out = self.call("pass", "end", self.research, "--summary", "nothing pushed",
                              "--defer-workshop", "kept for the next pass")
        self.assertEqual(self.value(out, "LOCK"), "released", out)
        self.assertIsNone(self.value(out, "WORKSHOP_BUILD"))
        self.assertNotIn("outils/build.py", out)
        code, out = self.call("resume", self.research, "--mode", "session")
        self.call("plan", self.research)
        self.assertEqual(code, 0, out)
        code, out = self.call("workshop", "push")
        self.assertEqual(self.value(out, "PUSHED"), "1", out)
        code, out = self.call("pass", "end", self.research, "--summary", "pushed")
        self.assertEqual(self.value(out, "WORKSHOP_BUILD"), "python outils/build.py", out)
        self.assertEqual(out.count("outils/build.py"), 2, out)              # the key, and its one line

    def test_doctor_linked_then_stale(self):
        code, out = self.call("doctor", env={"PWD": self.dir})
        self.assertEqual([self.value(out, k) for k in ("WORKSHOP", "WORKSHOP_ADAPTER", "WORKSHOP_VERIFIER",
                                                       "WORKSHOP_STALE")], ["linked", "prototype", "present", "false"])
        with open(self.people, "a", encoding="utf-8") as fh:
            fh.write("# by hand\n")
        code, out = self.call("doctor", env={"PWD": self.dir})
        self.assertEqual(self.value(out, "WORKSHOP_STALE"), "true", out)
        self.assertIn("workshop pull", out)
