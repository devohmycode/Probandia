import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

from probandia.util import yamlio
from tests import ROOT

SAMPLE = os.path.join(ROOT, "tests", "sample-project")
RID = "2026-09-01-ancestors-of-louis-marchand"


def runner():
    spec = importlib.util.spec_from_file_location("bench_run", os.path.join(ROOT, "bench", "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Bench(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = self.tmp.name
        self.project = os.path.join(self.bench, "projects", "marchand")
        shutil.copytree(SAMPLE, self.project)
        self.run = runner()

    def main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()):   # the report it prints would fill the test output
            return self.run.main(list(argv))

    def question(self, name, expected, run=None):
        doc = {"id": name, "project": "projects/marchand", "research": RID, "expected": expected}
        if run:
            doc["run"] = run
        yamlio.dump(os.path.join(self.bench, f"{name}.yaml"), doc)

    def test_metrics(self):
        self.question("good", [{"person": "Henri MARCHAND", "type": "birth", "year": 1870, "place": "Bourg-Vert"},
                               {"person": "Louise PERRIN", "type": "birth", "abstain": True}], {"tokens": 1200})
        self.question("wrong", [{"person": "henri-marchand-1870", "type": "birth", "year": 1880},
                                {"person": "Jeanne ROUSSEL", "type": "birth", "abstain": True}])
        persons = os.path.join(self.project, "families", "marchand", "index", "persons.yaml")
        doc = yamlio.load(persons)
        doc["persons"][0]["facts"][0]["source"] = "src-01JA0000000000000000000099"
        yamlio.dump(persons, doc)
        ledger = os.path.join(self.project, ".probandia", "ledger.jsonl")
        os.makedirs(os.path.dirname(ledger), exist_ok=True)   # the sample may carry an untracked .probandia/
        with open(ledger, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"provider": "exa", "research": RID, "pass": 1, "units": 1, "paid": 0.25}) + "\n")
        out = os.path.join(self.bench, "report.md")
        self.assertEqual(self.main("--bench-dir", self.bench, "--out", out), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("| good | 1/1 | 0.0 | 1 | 1/1 | 1200 | 0.25 | 0 | 0:30:00 |", text)
        self.assertRegex(text, r"\| wrong \| 0/1 \| [1-9][0-9.]* \| 1 \| 0/1 \|")
        self.assertIn("wrong: false promotions henri-marchand-1870.birth, jeanne-roussel-1874.birth", text)
        for metric in ("findings", "false promotions", "facts without a citation", "justified abstentions",
                       "tokens", "amount paid", "native searches", "duration"):
            self.assertIn(f"- {metric}:", text)

    def test_a_fact_proven_on_an_online_tree_is_a_false_promotion(self):
        # an online tree never proves a fact (P-2, V-2): the grader counts it even when it gives the right answer
        self.question("tree", [{"person": "Henri MARCHAND", "type": "birth", "year": 1870, "place": "Bourg-Vert"}])
        sources = os.path.join(self.project, "families", "marchand", "index", "sources.yaml")
        doc = yamlio.load(sources)
        cited = next(s for s in doc["sources"] if s["id"] == "src-01JA0000000000000000000002")
        cited["type"] = "online-tree"
        yamlio.dump(sources, doc)
        out = os.path.join(self.bench, "report.md")
        self.assertEqual(self.main("--bench-dir", self.bench, "--out", out), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("tree: false promotions henri-marchand-1870.birth", text)

    def test_tokens_by_harness_and_model(self):
        # version-1.0.0 T38: the main thread on one model, the readers on another, with the research's run
        self.question("good", [{"person": "Henri MARCHAND", "type": "birth", "year": 1870}])
        os.makedirs(os.path.join(self.project, ".probandia"), exist_ok=True)
        row = {"research": RID, "pass": 1, "harness": "claude-code", "input": 10, "output": 100, "cache_read": 0,
               "cache_write": 0}
        with open(os.path.join(self.project, ".probandia", "tokens.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(row, role="session", model="claude-opus-5-5")) + "\n")
            fh.write(json.dumps(dict(row, role="reader", model="claude-sonnet-5-5", output=10)) + "\n")
        out = os.path.join(self.bench, "report.md")
        self.assertEqual(self.main("--bench-dir", self.bench, "--out", out), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("## Tokens by harness and model", text)
        self.assertIn("| good | claude-code | claude-opus-5-5 | session | — | 10 | 100 | 0 | 0 | 0 | 510 |", text)
        self.assertIn("| good | claude-code | claude-sonnet-5-5 | session | — | 10 | 10 | 0 | 0 | 0 | 60 |", text)

    def test_the_run_of_the_passes(self):
        class Research:
            def meta(self):
                return {"run": {"mode": "session"}}

        started = [{"type": "pass.started", "payload": {"run": {"mode": "subagent", "model": "opus", "effort": e}}}
                   for e in ("high", "high", "medium")]
        self.assertEqual(self.run.run_settings(Research(), started),
                         {"mode": "subagent", "model": "opus", "effort": "high, medium"})
        self.assertEqual(self.run.run_settings(Research(), []), {"mode": "session", "model": None, "effort": None})

    def results_json(self, *extra):
        """version-1.0.0 T39: a question without research:, scored to results.json."""
        question = os.path.join(self.bench, "q.yaml")
        yamlio.dump(question, {"id": "parents", "project": "projects/marchand",
                               "expected": [{"person": "Henri MARCHAND", "type": "birth", "year": 1870}]})
        out = os.path.join(self.bench, "results.json")
        code = self.main("--question", question, "--out", os.path.join(self.bench, "r.md"), "--json", out, *extra)
        return code, out

    def test_results_json(self):
        from probandia.util.schema import validate_document

        os.makedirs(os.path.join(self.project, ".probandia"), exist_ok=True)
        with open(os.path.join(self.project, ".probandia", "tokens.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"research": RID, "pass": 1, "role": "session", "harness": "claude-code",
                                 "model": "claude-opus-5-5", "input": 10, "output": 100, "cache_read": 0,
                                 "cache_write": 0}) + "\n")
        code, out = self.results_json("--harness-version", "2.1.287", "--effort", "high")
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        doc = validate_document("bench-result", json.loads(text), out)
        case = doc["cases"][0]
        self.assertEqual((doc["probandia"], case["id"], case["harness"], case["model"], case["effort"], case["mode"]),
                         (self.run.probandia.__version__, "parents", {"name": "claude-code", "version": "2.1.287"},
                          "claude-opus-5-5", "high", "session"))
        self.assertEqual((case["metrics"]["findings"], case["tokens"]["weighted"], case["duration_s"]), (1, 510, 1800))
        for private in ("marchand", "henri", RID.lower(), self.bench.lower().replace("\\", "/"),
                        self.bench.lower().replace("\\", "\\\\")):
            self.assertNotIn(private, text.lower())   # no person, no research id, no path
        try:
            import jsonschema
        except ImportError:   # a development dependency
            return
        with open(os.path.join(ROOT, "schemas", "bench-result-1.json"), encoding="utf-8") as fh:
            jsonschema.validate(doc, json.load(fh))

    def test_the_example_is_valid(self):
        from probandia.util.schema import validate_document

        path = os.path.join(ROOT, "schemas", "examples", "bench-result-1.json")
        with open(path, encoding="utf-8") as fh:
            validate_document("bench-result", json.load(fh), path)

    def test_a_project_with_several_researches_needs_research(self):
        shutil.rmtree(self.project)
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project-gps"), self.project)
        self.assertEqual(self.results_json()[0], 2)

    def test_duplicates(self):
        # version-1.0.0 T40: a birth proven twice is one duplicate; two residences of different years are not
        persons = os.path.join(self.project, "families", "marchand", "index", "persons.yaml")
        doc = yamlio.load(persons)
        henri = next(p for p in doc["persons"] if p["id"] == "henri-marchand-1870")
        birth = next(f for f in henri["facts"] if f["type"] == "birth")
        henri["facts"].append(dict(birth, id="henri-marchand-1870.birth.2", date={"value": "1871", "qualifier": "exact"}))
        for n, year in ((1, "1900"), (2, "1905")):
            henri["facts"].append(dict(birth, id="henri-marchand-1870.residence" + (f".{n}" if n > 1 else ""),
                                       type="residence", date={"value": year, "qualifier": "exact"}))
        yamlio.dump(persons, doc)
        code, out = self.results_json()
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["cases"][0]["metrics"]["duplicates"], 1)
        with open(os.path.join(self.bench, "r.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("- duplicates (an event of a person proven again): 1", text)
        self.assertIn("- parents: duplicates henri-marchand-1870.birth.2", text)

    def test_the_place_under_another_writing(self):
        # version-1.0.0 T233: the commune is found at the head of a longer place as written, never in another name
        def fact(written, ident=None):
            return {"place": {"id": ident, "as_written": written}}

        want = {"place": "Besançon"}
        for written in ("Besançon", "besancon", "Besançon, paroisse Saint-Jean", "Besançon, village de Chamars",
                        "Besançon (Doubs)", "Besançon village de Chamars", "village de Chamars, Besançon",
                        "au village de Chamars[?] en cette commune (Besançon)", "né à Besançon"):
            self.assertTrue(self.run._place_ok(want, fact(written)), written)
        for written in ("Besançon-les-Bains", "Nancy", "Chamars, village de Besançon", "Besançan[?]"):
            self.assertFalse(self.run._place_ok(want, fact(written)), written)
        for written in ("Auxons [Les Auxons?]", "né aux Auxons", "Les Auxons, hameau de Valentin"):
            self.assertTrue(self.run._place_ok({"place": "Les Auxons"}, fact(written)), written)
        self.assertTrue(self.run._place_ok(want, fact("Chamars", "besancon")))
        self.assertFalse(self.run._place_ok({"place": "Bourgvert"}, fact("Bourg-Vert", "bourg-vert")))
        self.assertTrue(self.run._place_ok({"place": "Bourgvert"}, fact("Bourg-Vert", "bourg-vert"),
                                           {"bourg-vert": ["Bourg-Vert", "Bourgvert"]}))
        self.assertTrue(self.run._place_ok({}, fact("Nancy")))
        self.assertTrue(self.run._place_ok(want, fact("Besançon Gd Duché de Bourgogne")))   # no comma before
        self.assertFalse(self.run._place_ok(want, fact("Besançon-les-Bains Doubs")))
        two_names = {"place": ["Les Auxons", "Auxon-Dessus"]}   # a commune known under two names
        self.assertTrue(self.run._place_ok(two_names, fact("Auxon-Dessus, Doubs")))
        self.assertTrue(self.run._place_ok(two_names, fact("aux Auxons")))
        self.assertFalse(self.run._place_ok(two_names, fact("Auxon-Dessous")))

    def test_a_longer_place_is_found(self):
        # version-1.0.0 T233: a longer place as written, found through the family's places.yaml
        persons = os.path.join(self.project, "families", "marchand", "index", "persons.yaml")
        doc = yamlio.load(persons)
        henri = next(p for p in doc["persons"] if p["id"] == "henri-marchand-1870")
        birth = next(f for f in henri["facts"] if f["type"] == "birth")
        birth["place"] = {"id": "bourg-vert", "as_written": "Bourg-Vert, hameau des Ormeaux"}
        yamlio.dump(persons, doc)
        self.question("good", [{"person": "Henri MARCHAND", "type": "birth", "year": 1870, "place": "Bourgvert"}])
        out = os.path.join(self.bench, "report.md")
        self.assertEqual(self.main("--bench-dir", self.bench, "--out", out), 0)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("| good | 1/1 | 0.0 |", fh.read())

    def result(self, name, *cases):
        """A results.json made by hand: (case, model, weighted tokens, findings, duration) per entry."""
        doc = {"schema": 1, "probandia": "0.9.41", "date": "2026-10-13", "cases": [
            {"id": case, "harness": {"name": "claude-code", "version": None}, "model": model, "effort": "high",
             "mode": "session", "duration_s": duration, "passes": 1,
             "metrics": {"findings": findings, "expected": 2, "false_promotions": 0.0, "false_count": 0,
                         "uncited": 0, "abstentions": 0, "abstain_expected": 0, "quoted": 0, "facts": 4,
                         "proven": 4, "duplicates": 0, "native": 0, "paid": 0},
             "tokens": {"weighted": weighted, "kinds": None}, "by_model": []}
            for case, model, weighted, findings, duration in cases]}
        path = os.path.join(self.bench, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_compare(self):
        # version-1.0.0 T41: three runs of each column; the T33 rule gives each column its verdict
        files = [self.result(f"{n}.json", ("parents", "opus", 100 + 10 * i, 2, 1000 + 100 * i),
                             ("parents", "sonnet", 50 + 10 * i, (2, 1, 2)[i], 1300 + 100 * i),
                             *([("birth", "opus", 300, 1, 600), ("birth", "sonnet", 200, 1, 500)] if i == 0 else []))
                 for i, n in enumerate("abc")]
        out = os.path.join(self.bench, "compare.md")
        self.assertEqual(self.main("--compare", *files, "--out", out), 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("## parents\n\n| Metric | claude-code / opus / high (3 runs) | "
                      "claude-code / sonnet / high (3 runs) |\n|---|---|---|\n", text)
        self.assertIn("| tokens (weighted) | 110 [100–120] | 60 [50–70] lower |", text)
        self.assertIn("| findings | 2 [2–2] | 2 [1–2] inconclusive |", text)
        self.assertIn("| duration (s) | 1100 [1000–1200] | 1400 [1300–1500] higher |", text)
        self.assertIn("| claude-code / opus / high (1 run) | claude-code / sonnet / high (1 run) |", text)
        self.assertIn("| tokens (weighted) | 300 [300–300] | 200 [200–200] too few runs |", text)

    def test_the_verdict(self):
        v = self.run.verdict
        self.assertEqual(v([5, 6, 7], [1, 2, 3]), "lower")
        self.assertEqual(v([5, 6, 7], [8, 9, 10]), "higher")
        self.assertEqual(v([5, 6, 7], [4, 5, 9]), "inconclusive")
        self.assertEqual(v([5, 6], [1, 2, 3]), "too few runs")
        self.assertEqual(v([5, 6, 7], [1, 2, None]), "too few runs")   # a run without the value is not a run

    def test_compare_refuses_what_is_not_a_result(self):
        path = os.path.join(self.bench, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "cases": []}, fh)
        self.assertEqual(self.main("--compare", path), 2)

    def test_needs_the_bench_dir(self):
        self.assertEqual(self.main("--bench-dir", os.path.join(self.bench, "missing")), 2)
