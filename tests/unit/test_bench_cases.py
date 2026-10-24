"""The cases of the public benchmark (TRUST5): their admission, and their scoring."""
import datetime
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from probandia import excerpt as X
from probandia import transcription as T
from probandia.util import yamlio
from tests import ROOT

CASE = "birth-of-yves-tanguy-1815"
FAMILY = "tanguy"
RID = "2026-10-05-birth-of-yves-tanguy"
S1, S2 = "src-01JA0000000000000000000101", "src-01JA0000000000000000000102"
LINES = ["N° 12 Tanguy Yves", "L'an mil huit cent quinze, le trois mai, aux Ormes,",
         "est né Yves, fils de Hervé Tanguy, laboureur, et de Marie Le Gall."]


def load_tool(name):
    sys.path.insert(0, os.path.join(ROOT, "bench"))
    spec = importlib.util.spec_from_file_location(f"bench_{name}", os.path.join(ROOT, "bench", f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fact(fid, value, status="record", source=S1, **extra):
    return dict({"id": fid, "type": fid.split(".")[1], "status": status, "date": {"value": value},
                 "source": source, "research": RID, "pass": 1}, **extra)


def person(pid, given, surname, facts):
    return {"id": pid, "names": {"given": given, "surname": surname}, "sex": "M", "living": "auto",
            "parents": {"father": None, "mother": None}, "spouses": [], "facts": facts}


def make_case(base):
    """An invented case, admitted as it is: the tests change one thing at a time."""
    folder = os.path.join(base, CASE)
    for side in ("project", "solution"):
        fam = os.path.join(folder, side, "families", FAMILY)
        os.makedirs(fam)
        with open(os.path.join(folder, side, "probandia.toml"), "w", encoding="utf-8") as fh:
            fh.write('schema = 1\ngrade = "essential"\n')
        yamlio.dump(os.path.join(fam, "family.yaml"), {"schema": 1, "id": FAMILY, "name": "TANGUY",
                                                       "surnames": ["Tanguy"], "language": "fr"})
    fam = os.path.join(folder, "solution", "families", FAMILY)
    path = T.path_for(fam, S1)
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(T.template(S1, "vue 4", "fr", "cursive", LINES))
    birth = fact("yves-tanguy-1815.birth", "1815-05-03", place={"id": None, "as_written": "Les Ormes"},
                 excerpt=X.from_lines(LINES, 2, 3))
    death = fact("yves-tanguy-1815.death", "1879", status="index", source=S2)
    yamlio.dump(os.path.join(fam, "index", "persons.yaml"),
                {"schema": 1, "persons": [person("yves-tanguy-1815", "Yves", "TANGUY", [birth, death])]})
    yamlio.dump(os.path.join(fam, "index", "sources.yaml"), {"schema": 1, "sources": [
        {"id": S1, "repository": "Archives départementales de Valombre", "rights": "free",
         "transcription": f"evidence/transcriptions/{S1}.md", "url": "https://archives.valombre.example/ec/12"},
        {"id": S2, "repository": "Archives départementales de Valombre", "rights": "free",
         "url": "https://archives.valombre.example/td/9"}]})
    rdir = os.path.join(fam, "research", RID)
    os.makedirs(rdir)
    yamlio.dump(os.path.join(rdir, "research.yaml"), {"schema": 1, "id": RID, "family": FAMILY,
                                                      "question": "Quand est né Yves TANGUY ?", "status": "closed"})
    open(os.path.join(rdir, "events.jsonl"), "w").close()
    yamlio.dump(os.path.join(folder, "case.yaml"), {
        "schema": 1, "id": CASE, "title": "The birth of Yves TANGUY, 1815",
        "question": "Quand et où est né Yves TANGUY, mort en 1879 ?", "language": "fr", "family": FAMILY,
        "research": RID,
        "expected": [{"person": "Yves TANGUY", "type": "birth", "year": 1815, "place": "Les Ormes",
                      "fact": "yves-tanguy-1815.birth"},
                     {"person": "Yves TANGUY", "type": "marriage", "abstain": True}],
        "sources": [{"id": S1, "licence": "Licence Ouverte 2.0"}, {"id": S2, "licence": "Licence Ouverte 2.0"}]})
    return folder


class Admission(unittest.TestCase):
    """TRUST5-T2: bench/cases.py check admits a case only under TRUST-D9."""

    @classmethod
    def setUpClass(cls):
        cls.cases = load_tool("cases")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = make_case(self.tmp.name)
        self.today = datetime.date(2026, 10, 5)

    def check(self, catalogue=None):
        return self.cases.check(self.folder, self.today, catalogue if catalogue is not None else {})

    def persons(self, change):
        path = os.path.join(self.folder, "solution", "families", FAMILY, "index", "persons.yaml")
        doc = yamlio.load(path)
        change(doc["persons"])
        yamlio.dump(path, doc)

    def test_admitted(self):
        self.assertEqual(self.check(), [])

    def test_a_descendant_who_may_be_alive(self):
        self.persons(lambda ps: ps.append(person("lea-tanguy-1990", "Léa", "TANGUY",
                                                 [fact("lea-tanguy-1990.birth", "1990", status="index", source=S2)])))
        self.assertIn("lea-tanguy-1990: no death proven: the case may only name persons dead for more than 100 years",
                      self.check())

    def test_dead_less_than_a_hundred_years_ago(self):
        self.persons(lambda ps: ps[0]["facts"][1]["date"].update(value="1950"))
        self.assertIn("yves-tanguy-1815: died in 1950, less than 100 years ago", self.check())

    def test_an_archive_read_in_the_browser_only(self):
        catalogue = {"advb": {"access": {"mode": "browser", "hosts": ["archives.valombre.example"]}}}
        self.assertIn(f"{S1}: advb is read in the browser only: a replay could not read it", self.check(catalogue))
        catalogue = {"fs": {"access": {"mode": "html", "hosts": ["archives.valombre.example"]},
                            "login": {"required": True}}}
        self.assertIn(f"{S2}: fs needs a session: a replay could not read it", self.check(catalogue))

    def test_a_source_without_its_licence(self):
        doc = yamlio.load(os.path.join(self.folder, "case.yaml"))
        doc["sources"] = doc["sources"][:1]
        yamlio.dump(os.path.join(self.folder, "case.yaml"), doc)
        self.assertEqual(self.check(), [f"{S2}: cited by the solution, but not in case.yaml with its licence"])

    def test_the_excerpt_from_the_case_files_only(self):
        """TRUST-D3 made precise: an excerpt found in a cache does not count for a public case."""
        from probandia.reading.cache import Cache, make_key

        page = "Tables décennales. TANGUY Yves, 3 mai 1815."
        url = "https://archives.valombre.example/td/9"
        solution = os.path.join(self.folder, "solution")
        Cache(solution).put("http", make_key("http", url), {"text": page}, "ok", 86400)
        quoted = X.from_page(page, X.offset_of(page, "TANGUY Yves"), len("TANGUY Yves"), url=url)
        self.persons(lambda ps: ps[0]["facts"][1].update(excerpt=quoted))
        self.assertEqual(self.check(), ["yves-tanguy-1815.death: excerpt: the page is not kept on this computer"])
        kept = X.page_paths(solution, FAMILY, S2)[0]
        os.makedirs(os.path.dirname(kept))
        with open(kept, "w", encoding="utf-8") as fh:
            fh.write(f"<!-- {url} -->\n{page}\n")
        self.assertEqual(self.check(), [])

    def test_an_answer_without_its_passage(self):
        self.persons(lambda ps: ps[0]["facts"][0].pop("excerpt"))
        self.assertEqual(self.check(), ["yves-tanguy-1815.birth: gives an expected answer but does not quote its "
                                        "passage"])

    def test_not_solved_and_the_answer_in_the_project(self):
        self.persons(lambda ps: ps[0]["facts"][0]["date"].update(value="1830"))
        os.makedirs(os.path.join(self.folder, "project", "families", FAMILY, "research", "x"))
        found = self.check()
        self.assertIn("project/: holds a research: the starting project must not hold the answer", found)
        self.assertIn("solution/: 0 of 1 expected answers found", found)
        self.assertIn("solution/: falsely promoted: yves-tanguy-1815.birth", found)

    def test_command(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(self.cases.main(["check", self.folder]), 0)
        self.assertIn(f"{CASE}: admitted", out.getvalue())
        renamed = os.path.join(self.tmp.name, "other-name")
        shutil.move(self.folder, renamed)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(self.cases.main(["check", renamed]), 1)
        self.assertIn(f"  - the folder must be named {CASE}", out.getvalue())


class Scoring(unittest.TestCase):
    """TRUST5-T4: bench/run.py scores a public case, its solution or a project played from it."""

    @classmethod
    def setUpClass(cls):
        cls.runner = load_tool("run")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = make_case(self.tmp.name)

    def main(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code = self.runner.main(list(argv))
        return code, out.getvalue()

    def test_the_solution(self):
        code, out = self.main("--case", self.folder, "--out", os.path.join(self.tmp.name, "r.md"))
        self.assertEqual(code, 0, out)
        self.assertIn(f"| {CASE} | 1/1 | 0.0 | 0 | 1/1 |", out)
        self.assertIn("- findings quoting their passage, found again: 1/1", out)

    def test_a_played_project_that_does_not_quote(self):
        played = os.path.join(self.tmp.name, "played")
        shutil.copytree(os.path.join(self.folder, "solution"), played)
        path = os.path.join(played, "families", FAMILY, "index", "persons.yaml")
        doc = yamlio.load(path)
        doc["persons"][0]["facts"][0].pop("excerpt")
        yamlio.dump(path, doc)
        code, out = self.main("--case", self.folder, "--played", played, "--out", os.path.join(self.tmp.name, "r.md"))
        self.assertEqual(code, 0, out)
        self.assertIn("- findings quoting their passage, found again: 0/1", out)

    def test_a_bench_folder_holds_cases(self):
        code, out = self.main("--bench-dir", self.tmp.name, "--out", os.path.join(self.tmp.name, "r.md"))
        self.assertEqual(code, 0, out)
        self.assertIn(f"| {CASE} | 1/1 |", out)
        self.assertEqual(self.main("--case", self.folder, "--case", self.folder, "--played", "x")[0], 2)
