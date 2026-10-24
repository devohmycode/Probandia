"""FL5: the volet, a group of passes (FL-D8), and the dated refutation of a fact (FL-D10)."""
import os

from probandia import events
from tests.unit.test_analyses import fact
from tests.unit.test_data_layer import RID, Project


class Volets(Project):
    def value(self, out, key):
        return next(line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "="))

    def facts(self):
        return {f["id"]: f for p in self.index("persons")["persons"] for f in p.get("facts", [])}

    def test_a_volet_then_a_refutation_dated_in_it(self):
        self.assertEqual(self.call("volet", "open", RID)[0], 2)   # a volet has a title
        code, out = self.call("volet", "open", RID, "--title", "Les parents", "--established", "né à Besançon",
                              "--opening", "le registre de 1847")
        self.assertEqual((code, self.value(out, "VOLET"), self.value(out, "FROM_PASS")), (0, "1", "2"), out)
        (code, out), _doc = self.propose_and_apply(
            facts=[fact("jean-martin-1849.birth.2", "birth", "1847", status="index")])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.facts()["jean-martin-1849.birth.2"]["volet"], 1)   # stamped by the engine
        refute = {"fact": "jean-martin-1849.birth.2", "reason": "the index misread the year",
                  "cause": "faulty-index"}
        (code, out), _doc = self.propose_and_apply(refutations=[refute])
        self.assertEqual(code, 0, out)
        f = self.facts()["jean-martin-1849.birth.2"]
        self.assertEqual(f["status"], "refuted")   # refuted, never deleted
        self.assertEqual((f["refuted_in"]["pass"], f["refuted_in"]["volet"]), (2, 1))
        revised = [e for e in events.read(self.log) if e["type"] == "fact.revised"][-1]
        self.assertEqual((revised["id"], revised["payload"]["before"], revised["payload"]["after"]),
                         (f["refuted_in"]["event"], "index", "refuted"))
        (code, out), _doc = self.propose_and_apply(refutations=[refute])
        self.assertNotEqual(code, 0)
        self.assertIn("already refuted", out)
        (code, out), _doc = self.propose_and_apply(refutations=[dict(refute, fact="jean-martin-1849.death")])
        self.assertIn("no such fact", out)
        self.assertEqual(self.call("verify", RID, "--light")[0] in (0, 1), True)
        self.assertEqual(self.call("render", RID)[0], 0)
        with open(os.path.join(self.rdir, "report", "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("Volet 1 — Les parents", md)
        self.assertIn("**Acquis**\n\n- né à Besançon", md)
        self.assertLess(md.index("Volet 1 — Les parents"), md.index("Passe 2"))
        self.assertIn("Réfuté au volet 1, passe 2", md)

    def test_the_next_pass_belongs_to_the_volet_and_a_short_volet_warns(self):
        self.call("volet", "open", RID, "--title", "Les parents")
        code, out = self.call("resume", RID, "--mode", "session")
        self.call("plan", RID)
        self.assertEqual(code, 0, out)
        started = [e for e in events.read(self.log) if e["type"] == "pass.started"][-1]
        self.assertEqual((started["pass"], started["payload"]["volet"]), (2, 1))
        self.assertEqual(self.call("pass", "end", RID, "--summary", "x")[0], 0)
        code, out = self.call("volet", "open", RID, "--title", "Les grands-parents")
        self.assertEqual((self.value(out, "STATUS"), self.value(out, "VOLET"), self.value(out, "FROM_PASS")),
                         ("WARN", "2", "3"))
        self.assertIn("fewer than four chapters", out)
        code, out = self.call("volet", "list", RID)
        self.assertEqual(self.value(out, "VOLETS"), "2")
        self.assertIn("volet=2 from pass 3: Les grands-parents", out)
