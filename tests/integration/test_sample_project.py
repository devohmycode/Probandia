"""The PRD's acceptance scenarios, replayed offline on ``tests/sample-project/`` (SPECS § 14.4).

Criteria 3, 4, 10 to 12 and 17 need a provider, a harness or a recorded page:
they are covered by ``tests/unit`` (quotas, hooks, reading ladder) and by the
live checks written up in the tasks.
"""
import builtins
import datetime
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from probandia import cli, events, gedcom
from probandia.research import Research
from probandia.util import yamlio
from tests import ROOT

SAMPLE = os.path.join(ROOT, "tests", "sample-project")
SAMPLE_GPS = os.path.join(ROOT, "tests", "sample-project-gps")
RID = "2026-09-01-ancestors-of-louis-marchand"
GPS_RID = "2026-09-04-birth-of-henri-marchand"   # GPS8-T4: a research carried to its closing in strict
GOLDEN = os.path.join(ROOT, "tests", "golden", "sample")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def golden(test, name, text):
    """``text`` equals the reference rendering ``name``; PROBANDIA_UPDATE_GOLDEN=1 writes it."""
    path = os.path.join(GOLDEN, name)
    if os.environ.get("PROBANDIA_UPDATE_GOLDEN"):
        os.makedirs(GOLDEN, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    with open(path, encoding="utf-8") as fh:
        test.assertEqual(text, fh.read(), name)


def tree_hash(folder):
    out = {}
    for base, _d, files in os.walk(folder):
        for f in files:
            with open(os.path.join(base, f), "rb") as fh:
                out[os.path.relpath(os.path.join(base, f), folder)] = hashlib.sha256(fh.read()).hexdigest()
    return out


class Sample(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(SAMPLE, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "PROBANDIA_SESSION": "sample",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"), "LANG": "en_US.UTF-8"}
        for k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
            if k in os.environ:
                self.env[k] = os.environ[k]
        self.research = Research(self.dir, "marchand", RID)

    def call(self, *argv, env=None, cwd=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=cwd or self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        return next((line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "=")), None)

    def test_the_sample_is_sound(self):
        persons = yamlio.load(os.path.join(self.dir, "families", "marchand", "index", "persons.yaml"))["persons"]
        self.assertEqual(len(persons), 30)
        self.assertIsNone(events.check_chain(self.research.events_path))
        self.call("render", RID)
        code, out = self.call("verify", RID)
        self.assertEqual(code, 0, out)

    def test_9_every_rule_passes_on_a_clean_research(self):
        # PRD criterion 9, its second half (T226): on a clean research, every rule prints PASS, none WARN
        self.call("render", RID)
        code, out = self.call("verify", RID, "--all")
        self.assertEqual(code, 0, out)
        rules = [line[2:].split("=")[0] for line in out.splitlines() if line.startswith("- V-")]
        self.assertEqual(rules, [f"V-{n}" for n in range(1, 21)], out)
        self.assertEqual([line for line in out.splitlines() if line.startswith("- V-") and "=PASS" not in line], [])

    def test_2_first_research(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        q = "Who were the parents of Louis MARCHAND, born in 1898 in Bourg-Vert?"
        code, out = self.call("new", q, cwd=empty)
        self.assertEqual((code, self.value(out, "QUESTION")), (3, "run_mode"))  # E-1: who runs it
        code, out = self.call("new", q, "--mode", "session", "--prompt-lang", "fr", cwd=empty)
        self.assertEqual(code, 0, out)
        rid = self.value(out, "RESEARCH")
        for d in ("families/marchand/index", "families/marchand/research", ".probandia"):
            self.assertTrue(os.path.isdir(os.path.join(empty, d)), d)
        code, out = self.call("render", rid, cwd=empty)
        report = os.path.join(empty, "families", "marchand", "research", rid, "report")
        with open(os.path.join(report, "report.md"), encoding="utf-8") as fh:
            self.assertIn("## Sommaire", fh.read())
        self.assertTrue(os.path.isfile(os.path.join(report, "report.html")))

    def test_5_resume_from_the_digest(self):
        before = events.read_lines(self.research.events_path)
        opened = []
        real = builtins.open

        def spy(path, *a, **k):
            opened.append(str(path))
            return real(path, *a, **k)
        self.call("render", RID)
        with mock.patch("builtins.open", spy):
            code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual(code, 0, out)
        self.assertLessEqual(int(self.value(out, "DIGEST_LINES")), 60)
        self.assertIn("grandparents found", out)
        self.assertFalse([p for p in opened if os.sep + "report" + os.sep in os.path.normpath(p)])
        after = events.read_lines(self.research.events_path)
        self.assertEqual(after[:len(before)], before)
        self.assertEqual({json.loads(line)["pass"] for line in after[len(before):]}, {3})

    def test_6_journal_erratum(self):
        self.call("render", RID, "--formats", "md,json")
        report = os.path.join(self.research.folder, "report")
        first = json.loads(read(os.path.join(report, "report.json")))
        self.call("resume", RID, "--mode", "session")
        self.call("plan", RID)
        fact = "louis-marchand-1898.birth"  # cited by [[f:…]] in pass 1
        payload = os.path.join(self.tmp.name, "rev.json")
        with open(payload, "w", encoding="utf-8") as fh:
            json.dump({"fact": fact, "before": "1898", "after": "1897", "wrong": "1898",
                       "reason": "the register is of 1897", "cause": "misreading"}, fh)
        code, out = self.call("event", "append", RID, "--type", "fact.revised", "--payload-file", payload)
        self.assertEqual(code, 0, out)
        self.call("render", RID, "--formats", "md,json")
        second = json.loads(read(os.path.join(report, "report.json")))
        self.assertEqual(first["sections"][0], second["sections"][0])  # pass 1 is byte-identical
        md = read(os.path.join(report, "report.md"))
        self.assertIn("†E1", md)
        self.assertIn("erreur de lecture", md)

    def test_7_living_rewrite(self):
        code, out = self.call("new", "Where did Henri MARCHAND live?", "--family", "marchand", "--mode", "session",
                              "--report-mode", "living", "--lang", "fr")
        rid = self.value(out, "RESEARCH")
        sec = os.path.join(self.tmp.name, "s.json")
        with open(sec, "w", encoding="utf-8") as fh:
            json.dump({"section": {"parent": None, "kind": "chapter", "title": "Résidences",
                                   "body_md": "Bourg-Vert en 1898.", "facts": []}}, fh)
        code, out = self.call("event", "append", rid, "--type", "section.added", "--payload-file", sec)
        sid = self.value(out, "SECTION")
        self.call("render", rid, "--formats", "md,json")
        with open(sec, "w", encoding="utf-8") as fh:
            json.dump({"section": sid, "title": "Résidences", "body_md": "Bourg-Vert, puis Saint-Aubry.",
                       "reason": "the census of 1906"}, fh)
        self.call("event", "append", rid, "--type", "section.replaced", "--payload-file", sec)
        self.call("render", rid, "--formats", "md,json")
        md = read(os.path.join(self.dir, "families", "marchand", "research", rid, "report", "report.md"))
        self.assertIn(f'<a id="s-{sid.lower()}"></a>', md)
        self.assertIn("puis Saint-Aubry", md)
        self.assertIn("the census of 1906", md)

    def test_8_fork(self):
        before = tree_hash(self.research.folder)
        code, out = self.call("fork", RID, "--at", "1", "--name", "branch-roussel")
        self.assertEqual(code, 0, out)
        child = Research(self.dir, "marchand", self.value(out, "RESEARCH"))
        self.assertEqual(child.meta()["forked_from"], {"research": RID, "pass": 1})
        self.call("plan", child.id)
        self.call("pass", "end", child.id, "--summary", "x")
        self.assertEqual(tree_hash(self.research.folder), before)

    def test_9_verification(self):
        path = os.path.join(self.dir, "families", "marchand", "index", "persons.yaml")
        doc = yamlio.load(path)
        doc["persons"][0]["facts"].append({"id": "louis-marchand-1898.residence", "type": "residence",
                                            "status": "index", "source": None, "research": RID})
        yamlio.dump(path, doc)
        spath = os.path.join(self.dir, "families", "marchand", "index", "searches.yaml")
        doc = yamlio.load(spath)
        doc["searches"][1]["witness"] = None
        yamlio.dump(spath, doc)
        code, out = self.call("verify", RID)
        self.assertEqual(code, 1, out)
        self.assertIn("V-2=FAIL", out)
        self.assertIn("V-3=FAIL", out)

    def test_13_self_learning(self):
        script = os.path.join(self.tmp.name, "valombre.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("def run(args, http):\n    return [{'q': args.get('q')}]\n")
        self.call("resume", RID, "--mode", "session")
        self.call("plan", RID)
        self.call("library", "save", script, "--id", "valombre-index", "--purpose", "births in the Valombre index",
                  "--witness-args", '{"q": "MARCHAND"}')
        self.call("library", "test", "valombre-index")
        self.call("pass", "end", RID, "--summary", "connector written")
        self.call("resume", RID, "--mode", "session")
        code, out = self.call("library", "find", "Valombre births")
        self.assertIn("valombre-index [tested]", out)
        code, out = self.call("library", "run", "valombre-index", "--research", RID, "--args", '{"q": "ROUSSEL"}')
        self.assertEqual(code, 0, out)
        used = [e for e in events.read(self.research.events_path) if e["type"] == "library.used"]
        self.assertEqual((len(used), used[0]["pass"], used[0]["payload"]["version"]), (1, 4, 1))

    def test_14_trees_and_exports(self):
        self.call("render", RID, "--formats", "md,html")
        md = read(os.path.join(self.research.folder, "report", "report.md"))
        self.assertIn("```mermaid", md)
        code, out = self.call("tree", "--family", "marchand")
        self.assertEqual(code, 0, out)
        trees_dir = os.path.join(self.dir, "families", "marchand", "trees")
        self.assertTrue(os.path.isfile(os.path.join(trees_dir, "tree.html")))
        self.assertIn("```mermaid", read(os.path.join(trees_dir, "tree.md")))
        code, out = self.call("export", "gedcom7", "--family", "marchand")
        path = os.path.join(self.dir, out.split("FILE=")[1].split()[0])
        with zipfile.ZipFile(path) as z:
            roots = gedcom.parse(z.read("gedcom.ged").decode("utf-8-sig"))
        self.assertEqual(sum(1 for r in roots if r.tag == "INDI"), 30)
        code, out = self.call("export", "gedcom551", "--family", "marchand")
        self.assertEqual(code, 0, out)
        code, out = self.call("import-gedcom", os.path.join(self.dir, out.split("FILE=")[1].split()[0]),
                              "--family", "marchand")
        self.assertEqual(self.value(out, "MATCHED"), "30")  # every person of the export finds itself

    def test_15_language(self):
        self.call("render", RID, "--formats", "md")
        md = read(os.path.join(self.research.folder, "report", "report.md"))
        self.assertIn("## Sommaire", md)
        self.call("--lang", "en", "render", RID, "--formats", "md")
        md = read(os.path.join(self.research.folder, "report", "report.md"))
        self.assertIn("## Contents", md)

    def test_16_configuration(self):
        code, out = self.call("config", "show")
        self.assertEqual(code, 0, out)
        self.assertIn("grade", out)
        self.call("config", "set", "report.mode", "living")
        code, out = self.call("config", "explain", "report.mode")
        self.assertIn("living", out)


    def test_privacy_of_a_living_descendant(self):
        path = os.path.join(self.dir, "families", "marchand", "index", "persons.yaml")
        doc = yamlio.load(path)
        year = datetime.date.today().year - 40
        doc["persons"].append({"id": f"lea-marchand-{year}", "names": {"given": "Léa", "surname": "MARCHAND"},
                               "sex": "F", "living": "auto", "parents": {"father": doc["persons"][0]["id"],
                                                                         "mother": None}, "spouses": [],
                               "facts": [{"id": f"lea-marchand-{year}.birth", "type": "birth", "status": "record",
                                          "date": {"value": f"{year}-04-02"}, "source": None}]})
        yamlio.dump(path, doc)
        self.call("tree", "--family", "marchand", "--root", doc["persons"][0]["id"])
        page = read(os.path.join(self.dir, "families", "marchand", "trees", "tree.html"))
        data = page.split('id="tree-data">')[1].split("</script>")[0]
        self.assertNotIn("Léa", data)
        self.assertNotIn("lea-marchand", data)


class SampleGPS(unittest.TestCase):
    """GPS8-T4: the sample family, with a second research that meets the Genealogical Proof Standard."""

    call = Sample.call
    value = Sample.value

    def setUp(self):
        Sample.setUp(self)
        shutil.rmtree(self.dir)
        shutil.copytree(SAMPLE_GPS, self.dir)

    def test_gps_a_complete_case(self):
        """GPS8-T4 and the acceptance of GPS8: the birth of Henri MARCHAND, from its questions to the closing in
        strict, offline; the report matches its reference rendering."""
        rid = GPS_RID
        research = Research(self.dir, "marchand", rid)
        self.assertEqual(self.call("config", "set", "proof.standard", "strict")[0], 0)
        code, out = self.call("verify", rid, "--standard")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "CONFORM"), self.value(out, "QUESTIONS")), ("2", "2"))
        established = " ".join(f"{k}=established" for k in ("exhaustive", "citations", "analysis", "conflicts",
                                                              "argument"))
        for q in ("Q1", "Q2"):
            self.assertIn(f"{q}=conform {established}", out)
        code, out = self.call("matrix", rid)
        self.assertEqual(self.value(out, "HOLES"), "0", out)
        code, out = self.call("render", rid, "--formats", "md,html")
        self.assertEqual(code, 0, out)
        folder = os.path.join(research.folder, "report")
        for name in ("report.md", "report.html"):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                golden(self, f"gps-{name}", fh.read())
        with open(os.path.join(folder, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        for part in ('<aside class="standard" role="note"',            # the box of conformity
                     "Éléments du Genealogical Proof Standard établis : 5 sur 5",
                     'id="s-coverage-q1"', "ac_bourg_vert: “MARCHAND Bourg-Vert naissances 1870”",   # the coverage
                     'id="s-analysis-an-henri-marchand-1870-birth"',   # the correlation table
                     'id="s-proof-pf-q1-' + rid + '"', "le contradicteur",   # the argument
                     "Bourg-Vert, état civil, naissances, 1870",       # a typed citation, its first note
                     '<figure class="timeline">'):                      # the timeline
            self.assertIn(part, html)
        code, out = self.call("verify", rid)
        self.assertEqual(code, 0, out)
        code, out = self.call("close", rid)
        self.assertEqual((code, self.value(out, "CLOSED")), (0, "true"), out)
        self.assertEqual(research.meta()["status"], "closed")
