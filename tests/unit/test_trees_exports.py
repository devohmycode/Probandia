import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import zipfile
from unittest import mock

from probandia import cli, events, gedcom, gedcom_import, grampsweb, svg, transcription, trees
from probandia.research import Research
from probandia.util import yamlio
from tests import ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
TREE = os.path.join(ROOT, "tests", "fixtures", "tree", "persons.yaml")
GOLDEN = os.path.join(ROOT, "tests", "golden")
GED = os.path.join(ROOT, "tests", "fixtures", "gedcom")
RID = "2026-09-30-parents-of-victor-hugo"
TODAY = datetime.date(2026, 10, 1)
SRC1 = "src-01J9ZK3M4X0000000000000001"


def tree_persons():
    return yamlio.load(TREE)["persons"]


def golden(name, text):
    path = os.path.join(GOLDEN, name)
    if os.environ.get("PROBANDIA_UPDATE_GOLDEN"):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class Project(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.family = os.path.join(self.dir, "families", "hugo")
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

    def use_tree(self):
        doc = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))
        known = {p["id"] for p in doc["persons"]}
        doc["persons"] += [p for p in tree_persons() if p["id"] not in known]
        for p in doc["persons"]:
            if p["id"] == "victor-hugo-1802":
                p["parents"] = {"father": "leopold-hugo-1773", "mother": "sophie-trebuchet-1772"}
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), doc)


class Mermaid(unittest.TestCase):
    def setUp(self):
        self.tree = trees.Tree(tree_persons(), today=TODAY)

    def test_couples_classes_hypotheses_and_living(self):
        root = "victor-hugo-1802"
        block = trees.mermaid_block(self.tree, self.tree.simplified(root))
        self.assertIn('P_victor_hugo_1802["Victor HUGO<br/>° 1802 x 1822 † 1885"]:::record', block)
        self.assertIn("P_leopold_hugo_1773 --> U_", block)
        self.assertIn("P_adele_foucher_1803 --> U_", block)  # the spouse is the children's other parent
        self.assertRegex(block, r"U_\d+ -\.-> P_leopold_hugo_1773")  # filiation on a hypothesis
        self.assertRegex(block, r"U_\d+ -\.-> P_adele_hugo_1830")
        self.assertIn(":::hypothesis", block)
        full = trees.mermaid_block(self.tree, list(self.tree.persons))
        self.assertIn('P_living_1["Living person"]:::living', full)
        self.assertNotIn("1932", full)
        self.assertNotIn("camille", full.lower())

    def test_refuted_link_not_drawn(self):
        persons = tree_persons()
        for p in persons:
            if p["id"] == "sophie-trebuchet-1772":
                p["facts"][0]["status"] = "refuted"
        tree = trees.Tree(persons, today=TODAY)
        block = trees.mermaid_block(tree, list(tree.persons))
        self.assertNotIn("-> P_sophie_trebuchet_1772", block)
        self.assertNotRegex(block, r"U_\d+ --> P_sophie_trebuchet_1772")

    def test_blocks_of_forty(self):
        persons = [{"id": f"p-{n}", "names": {"given": "X", "surname": f"N{n}"}, "living": False,
                    "parents": {"father": f"p-{2 * n}" if 2 * n < 200 else None,
                                "mother": f"p-{2 * n + 1}" if 2 * n + 1 < 200 else None},
                    "facts": [{"id": f"p-{n}.birth", "type": "birth", "status": "record",
                               "date": {"value": "1800"}}]} for n in range(1, 200)]
        tree = trees.Tree(persons, today=TODAY)
        blocks = trees.blocks(tree, "p-1")
        self.assertGreater(len(blocks), 1)
        self.assertTrue(all(len(b) <= 40 for b in blocks))
        self.assertEqual(len({p for b in blocks for p in b}), 199)
        md = trees.markdown(tree, "p-1")
        self.assertEqual(md.count("```mermaid"), len(blocks))


class Charts(unittest.TestCase):
    def setUp(self):
        self.tree = trees.Tree(tree_persons(), today=TODAY)

    def test_golden_svg(self):
        anc = svg.ancestors(self.tree, "victor-hugo-1802", 4)
        desc = svg.descendants(self.tree, "nicolas-hugot-1850", 4)
        self.assertEqual(anc, golden("ancestors.svg", anc))
        self.assertEqual(desc, golden("descendants.svg", desc))
        for chart in (anc, desc):
            self.assertEqual(chart.count('<g class="box'), chart.count("<title>"))
        self.assertIn("<title>Jean-Baptiste Joseph Anatole HUGOT, ° 1879 † 1960</title>", desc)
        self.assertIn(">Jean-Baptiste Joseph Anat…<", desc)  # cut at 26 characters
        self.assertIn("Living person", desc)
        self.assertNotIn("Camille", desc)

    def test_sosa_layout(self):
        anc = svg.ancestors(self.tree, "victor-hugo-1802", 3)
        # generation 2 (Sosa 4 to 7) is the third column, at x = 2 * (180 + 40)
        self.assertIn('transform="translate(440,', anc)
        self.assertIn("hypothesis", anc)

    def test_buchheim(self):
        pos = svg.layout(("r", [("a", [("a1", []), ("a2", []), ("a3", [])]), ("b", []),
                                ("c", [("c1", []), ("c2", []), ("c3", [])])]))
        self.assertEqual(pos["r"], (2.5, 0))
        self.assertEqual([pos[k][0] for k in ("a", "b", "c")], [1.0, 2.5, 4.0])
        xs = sorted(x for k, (x, d) in pos.items() if d == 2)
        self.assertEqual(xs, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])


class TreeCommand(Project):
    def test_html_md_and_svg(self):
        self.use_tree()
        code, out = self.call("tree", "--root", "nicolas-hugot-1850")
        self.assertEqual(code, 0, out)
        folder = os.path.join(self.family, "trees")
        with open(os.path.join(folder, "tree.html"), encoding="utf-8") as fh:
            page = fh.read()
        for needle in ('id="tree-data"', "<noscript><svg", "f3.createChart", "d3js.org", 'class="legend"',
                       "Personne vivante", "prouvé par un acte"):
            self.assertIn(needle, page)
        markup = re.sub(r"<(script|style)\b.*?</\1>", "", page, flags=re.S)
        self.assertFalse(re.search(r"<(script|link|img)[^>]+(src|href)=", markup))
        self.assertNotIn("camille", page.lower().split('id="tree-data"')[1].split("</script>")[0])
        data = json.loads(re.search(r'id="tree-data">(.*?)</script>', page, re.S).group(1))
        living = [p for p in data["people"] if p["data"]["status"] == "living"]
        self.assertTrue(living and all(p["data"]["years"] == "" for p in living))
        with open(os.path.join(folder, "tree.md"), encoding="utf-8") as fh:
            self.assertIn("```mermaid", fh.read())
        self.assertTrue(os.path.isfile(os.path.join(folder, "ancestors.svg")))

    def files(self, *argv):
        shutil.rmtree(os.path.join(self.family, "trees"), ignore_errors=True)
        code, out = self.call("tree", *argv)
        self.assertEqual(code, 0, out)
        return self.value(out, "FILES"), sorted(os.listdir(os.path.join(self.family, "trees")))

    def test_the_setting_tree_format(self):
        """T113: tree reads tree.format; without it, all four files; an option given wins."""
        self.use_tree()
        self.assertEqual(self.files(), ("4", ["ancestors.svg", "descendants.svg", "tree.html", "tree.md"]))
        with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
            fh.write('\n[tree]\nformat = "md"\n')
        self.assertEqual(self.files(), ("1", ["tree.md"]))
        self.assertEqual(self.files("--format", "html")[0], "3")
        self.assertEqual(self.files("--format", "all")[0], "4")


class ReportTrees(Project):
    def test_branch_tree_in_the_pass_and_in_trees(self):
        self.use_tree()
        r = Research(self.dir, "hugo", RID)
        e = events.make("branch.added", {"root": "victor-hugo-1802",
                                         "persons": ["victor-hugo-1802"]}, {"harness": "cli", "agent": "s"}, 1,
                        now=datetime.datetime(2026, 9, 30, 19, 0, tzinfo=datetime.timezone.utc))
        events.append(r.events_path, [e])
        code, out = self.call("render", RID, "--formats", "md,html,json")
        self.assertEqual(code, 0, out)
        with open(os.path.join(r.folder, "report", "report.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("## 1 Passe 1", md)
        self.assertLess(md.index("## 1 Passe 1"), md.index("```mermaid"))
        self.assertLess(md.index("```mermaid"), md.index("## 2 Méthode"))
        with open(os.path.join(r.folder, "report", "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('<figure class="tree"><svg', html)
        self.assertTrue(os.path.isfile(os.path.join(r.folder, "trees", "pass-1.md")))
        self.assertTrue(os.path.isfile(os.path.join(r.folder, "trees", "pass-1.svg")))
        with open(os.path.join(r.folder, "report", "report.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["trees"][0]["root"], "victor-hugo-1802")
        from probandia import verify

        self.assertEqual(verify.run(self.dir, r, rules=["V-8"])[0][1], "PASS")


class PublicDomain(unittest.TestCase):
    def test_one_public_domain(self):
        """GEDCOM tags, the HTTP contact, the report's $schema, the schemas' $id: the domain chosen by T3."""
        import glob
        import types
        import urllib.parse

        from probandia import SITE
        from probandia.report import render
        from probandia.util import http

        model = types.SimpleNamespace(lang="en", mode="journal", generated="", through_pass=1, chapters=[],
                                      errata=[], revisions={}, trees=[], method=None, log=None)
        urls = [*gedcom.SCHEMA.values(), http.DEFAULT_CONTACT, render.to_data(model, "r", "arabic")["$schema"]]
        for path in glob.glob(os.path.join(ROOT, "schemas", "*.json")):
            with open(path, encoding="utf-8") as fh:
                urls.append(json.load(fh)["$id"])
        for path in glob.glob(os.path.join(ROOT, "site", "gedcom", "v1", "*.md")):
            with open(path, encoding="utf-8") as fh:
                urls += re.findall(r"https://[^\s`)]+", fh.read())
        self.assertGreater(len(urls), 30)
        hosts = {urllib.parse.urlsplit(u).netloc for u in urls}
        self.assertEqual(hosts, {urllib.parse.urlsplit(SITE).netloc}, sorted(urls))


class Gedcom7(Project):
    def export(self, *args):
        code, out = self.call("export", "gedcom7", *args)
        self.assertEqual(code, 0, out)
        path = os.path.join(self.dir, self.value(out, "- FILE") or out.split("FILE=")[1].split()[0])
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            data = z.read("gedcom.ged")
        return names, data

    def test_gedzip(self):
        self.use_tree()
        os.makedirs(os.path.join(self.family, "evidence", "images"))
        with open(os.path.join(self.family, "evidence", "images", "e-1802-n-45.jpg"), "wb") as fh:
            fh.write(b"jpeg")
        names, data = self.export()
        self.assertEqual(names, ["gedcom.ged", "media/e-1802-n-45.jpg"])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        text = data.decode("utf-8-sig")
        for line in ("2 VERS 7.0", "2 TAG _STATUS https://probandia.replit.app/gedcom/v1/status", "1 LANG fr",
                     "1 FILE media/e-1802-n-45.jpg", "2 FORM image/jpeg", "3 QUAY 3", "2 _STATUS record",
                     "1 NAME Living //", "2 DATE ABT 1773", "0 TRLR"):
            self.assertIn(line + "\n", text)
        self.assertRegex(text, r"0 @H1@ _HYPO Who was the father")
        self.assertRegex(text, r"0 @N1@ _NEGA ")
        self.assertNotIn("TRÉBUCHET/\n1 SEX M\n1 BIRT", text)  # Jean-François's refuted birth is left out
        roots = gedcom.parse(text)
        self.assertEqual(sum(1 for r in roots if r.tag == "INDI"), 13)

    def test_exclude_and_refuted(self):
        self.use_tree()
        _names, data = self.export("--living", "exclude", "--include-refuted")
        text = data.decode("utf-8-sig")
        self.assertNotIn("Living //", text)
        self.assertIn("2 _STATUS refuted", text)

    def add_a_living_person(self):
        """T241: a person presumed living, with an unlikely name, named by a birth act, a hypothesis and a
        negative search; and a source of a dead person whose free citation names her too."""
        sid, other = "src-01J9ZK3M4X0000000000000077", "src-01J9ZK3M4X0000000000000078"
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))
        persons["persons"].append({
            "id": "zelie-sentinelle-1990", "names": {"given": "Zélie", "surname": "SENTINELLE"}, "sex": "F",
            "living": "auto", "parents": {"father": None, "mother": None}, "spouses": [],
            "facts": [{"id": "zelie-sentinelle-1990.birth", "type": "birth",
                       "date": {"value": "1990-05-06", "qualifier": "exact"}, "status": "record", "source": sid}]})
        for p in persons["persons"]:
            if p["id"] == "victor-hugo-1802":
                p["facts"][0]["source"] = other
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), persons)
        sources = yamlio.load(os.path.join(self.family, "index", "sources.yaml"))
        sources["sources"] += [
            {"id": sid, "type": "civil-registration", "jurisdiction": "Nancy", "register": "Naissances 1990",
             "repository": "Mairie de Nancy", "act": "birth", "act_no": "412", "act_date": "1990-05-06",
             "names": ["Zélie SENTINELLE"]},
            {"id": other, "repository": "Archives municipales de Besançon", "collection": "État civil",
             "citation": "Acte cité aussi pour SENTINELLE Zélie, sa descendante"}]
        yamlio.dump(os.path.join(self.family, "index", "sources.yaml"), sources)
        hypotheses = yamlio.load(os.path.join(self.family, "index", "hypotheses.yaml"))
        hypotheses["hypotheses"][0]["question"] = "Is Victor an ancestor of Zélie Sentinelle?"
        yamlio.dump(os.path.join(self.family, "index", "hypotheses.yaml"), hypotheses)
        searches = yamlio.load(os.path.join(self.family, "index", "searches.yaml"))
        searches["searches"][0]["query"] = "SENTINELLE Zélie Nancy"
        yamlio.dump(os.path.join(self.family, "index", "searches.yaml"), searches)

    def test_nothing_names_a_living_person(self):
        self.add_a_living_person()
        exports = []
        for args in ((), ("--living", "exclude")):
            exports.append(self.export(*args)[1])
            code, out = self.call("export", "gedcom551", *args)
            self.assertEqual(code, 0, out)
            for name in os.listdir(os.path.join(self.dir, "exports")):
                if name.endswith(".ged"):
                    with open(os.path.join(self.dir, "exports", name), "rb") as fh:
                        exports.append(fh.read())
        for data in exports:
            text = data.decode("utf-8-sig", errors="replace").upper()
            self.assertNotIn("SENTINELLE", text)
            self.assertNotIn("1990", text)
        self.assertIn(b"Archives municipales de Besan", exports[0])   # the dead person's source stays, plain

    def test_dates(self):
        self.assertEqual(gedcom.date_value({"value": "1802-02-26"}), "26 FEB 1802")
        self.assertEqual(gedcom.date_value({"value": "1820", "qualifier": "about"}), "ABT 1820")
        self.assertEqual(gedcom.date_value({"value": "1818", "qualifier": "between", "end": "1822"}),
                         "BET 1818 AND 1822")
        self.assertEqual(gedcom.date_value({"value": "1795-01-14", "calendar": "julian"}), "JULIAN 3 JAN 1795")
        self.assertEqual(gedcom.date_value({"value": "1803-09-26", "calendar": "republican"}),
                         "FRENCH_R 3 VEND 12")
        self.assertEqual(gedcom.date_value({"value": "1795-01-14", "calendar": "julian"}, version=5),
                         "@#DJULIAN@ 3 JAN 1795")


class Views(Project):
    """T247: an act on two views, and where it is on its view."""

    SRC = "src-01J9ZK3M4X0000000000000081"
    export = Gedcom7.export

    def views(self, *names):
        folder = os.path.join(self.family, "evidence", "images")
        os.makedirs(folder, exist_ok=True)
        for name in names:
            os.makedirs(os.path.dirname(os.path.join(folder, name)), exist_ok=True)   # ad50/0012.png
            with open(os.path.join(folder, name), "wb") as fh:
                fh.write(name.encode())
        return [f"evidence/images/{name}" for name in names]

    def propose(self, source):
        path = transcription.path_for(self.family, self.SRC)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(transcription.template(self.SRC, ", ".join(source.get("images") or []), lines=[
                "N° 9 Hugo Abel", "Léopold Hugo, officier, a présenté un enfant", "{margin: marié le 3 mai 1822}"]))
        proposal = {"schema": 1, "id": "01J9ZM00000000000000000081", "research": RID, "pass": 1,
                    "author": {"harness": "cli", "agent": "reader"}, "sources": [source],
                    "facts": [{"id": "leopold-hugo-1773.occupation", "type": "occupation", "status": "record",
                               "value": "officier", "source": self.SRC,
                               "excerpt": {"lines": "2", "region": "2:pct:5,40,90,25"}}]}
        draft = os.path.join(self.tmp.name, "p.yaml")
        yamlio.dump(draft, proposal)
        code, out = self.call("propose", RID, draft)
        self.assertEqual(code, 0, out)
        return self.call("apply", proposal["id"])

    def test_a_source_on_two_views_is_applied_and_exported_whole(self):
        self.use_tree()
        views = self.views("e-1798-n-12.jpg", "e-1798-n-13.jpg")
        code, out = self.propose({"id": self.SRC, "repository": "Archives municipales de Besançon",
                                  "rights": "free", "images": views})
        self.assertEqual(code, 0, out)
        sources = {s["id"]: s for s in yamlio.load(os.path.join(self.family, "index", "sources.yaml"))["sources"]}
        self.assertEqual((sources[self.SRC]["image"], sources[self.SRC]["images"]), (views[0], views))
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))["persons"]
        fact = next(f for p in persons for f in p["facts"] if f["id"] == "leopold-hugo-1773.occupation")
        self.assertEqual(fact["excerpt"]["region"], "2:pct:5,40,90,25")
        self.assertEqual(fact["excerpt"]["text"], "Léopold Hugo, officier, a présenté un enfant")
        names, data = self.export()
        self.assertIn("media/e-1798-n-12.jpg", names)
        self.assertIn("media/e-1798-n-13.jpg", names)
        text = data.decode("utf-8-sig")
        self.assertRegex(text, r"0 @O\d+@ OBJE\n1 FILE media/e-1798-n-12.jpg\n2 FORM image/jpeg\n"
                               r"1 FILE media/e-1798-n-13.jpg\n2 FORM image/jpeg\n")
        code, out = self.call("export", "gedcom551")
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.dir, out.split("FILE=")[1].split()[0]), encoding="utf-8") as fh:
            ged = fh.read()
        self.assertIn("1 FILE ../families/hugo/evidence/images/e-1798-n-13.jpg\n", ged)

    def test_the_image_is_the_first_view(self):
        views = self.views("a.jpg", "b.jpg")
        code, out = self.propose({"id": self.SRC, "repository": "Archives municipales de Besançon",
                                  "image": views[1], "images": views})
        self.assertEqual(code, 1, out)
        self.assertIn("P-2: source src-01J9ZK3M4X0000000000000081: its image evidence/images/b.jpg is not the first "
                      "of its images", out)

    def test_a_person_presumed_living_has_no_media(self):
        views = self.views("e-zoe-3.jpg", "e-zoe-4.jpg")
        sources = yamlio.load(os.path.join(self.family, "index", "sources.yaml"))
        sources["sources"].append({"id": self.SRC, "repository": "Mairie de Nancy", "rights": "free",
                                   "image": views[0], "images": views})
        yamlio.dump(os.path.join(self.family, "index", "sources.yaml"), sources)
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))
        persons["persons"].append({
            "id": "zoe-vivante", "names": {"given": "Zoé", "surname": "VIVANTE"}, "sex": "F", "living": "auto",
            "parents": {"father": None, "mother": None}, "spouses": [],
            "facts": [{"id": "zoe-vivante.birth", "type": "birth", "status": "record", "source": self.SRC,
                       "date": {"value": "1995-03-04", "qualifier": "exact"}}]})
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), persons)
        names, data = self.export()
        self.assertFalse([n for n in names if "e-zoe-" in n], names)
        self.assertNotIn("e-zoe-", data.decode("utf-8-sig"))
        # born a century earlier, she is dead: both views go into the archive
        persons["persons"][-1]["facts"][0]["date"]["value"] = "1795-03-04"
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), persons)
        os.remove(os.path.join(self.dir, "exports", os.listdir(os.path.join(self.dir, "exports"))[0]))
        names, _data = self.export()
        self.assertEqual([n for n in names if "e-zoe-" in n], ["media/e-zoe-3.jpg", "media/e-zoe-4.jpg"])

    # PRD criterion 14, the exports with images: the archive keeps every view, the FILE lines name entries of
    # it and no other, and a view no file holds is left out, said, rather than written as a reference to nothing

    def cite_views(self, images):
        """A dead person (born 1795) whose birth a free source on these views gives: the views are exported."""
        sources = yamlio.load(os.path.join(self.family, "index", "sources.yaml"))
        for s in sources["sources"]:   # the fixture's own view is no file of this folder: out of the picture
            s.pop("image", None)
            s.pop("images", None)
        sources["sources"].append({"id": self.SRC, "repository": "Archives municipales de Besançon", "rights": "free",
                                   "image": images[0], "images": images})
        yamlio.dump(os.path.join(self.family, "index", "sources.yaml"), sources)
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))
        persons["persons"].append({
            "id": "ancetre-test", "names": {"given": "Jean", "surname": "TEST"}, "sex": "M", "living": "auto",
            "parents": {"father": None, "mother": None}, "spouses": [],
            "facts": [{"id": "ancetre-test.birth", "type": "birth", "status": "record", "source": self.SRC,
                       "date": {"value": "1795-03-04", "qualifier": "exact"}}]})
        yamlio.dump(os.path.join(self.family, "index", "persons.yaml"), persons)

    def archive(self):
        """(path of the GEDZIP, its entries, its gedcom.ged, the answer of export)."""
        code, out = self.call("export", "gedcom7")
        self.assertEqual(code, 0, out)
        path = os.path.join(self.dir, out.split("FILE=")[1].split()[0])
        with zipfile.ZipFile(path) as z:
            names, text = z.namelist(), z.read("gedcom.ged").decode("utf-8-sig")
        return path, names, text, out

    def assert_no_orphan(self, names, text):
        files = [urllib.parse.unquote(f) for f in re.findall(r"^1 FILE (.*)$", text, re.M)]
        self.assertEqual([f for f in files if f not in names], [], "a FILE names no entry of the archive")
        self.assertEqual(len(set(files)), len(files), "two FILE lines name one entry")

    def test_two_views_with_one_file_name_keep_both(self):
        images = self.views("ad50/0012.png", "ad51/0012.png")   # two registers, the same view number
        self.cite_views(images)
        path, names, text, _out = self.archive()
        self.assertEqual(sorted(n for n in names if n.startswith("media/")), ["media/0012-2.png", "media/0012.png"])
        self.assertEqual(re.findall(r"^1 FILE (.*)$", text, re.M), ["media/0012.png", "media/0012-2.png"])
        with zipfile.ZipFile(path) as z:   # the second view did not replace the first
            self.assertEqual((z.read("media/0012.png"), z.read("media/0012-2.png")),
                             (b"ad50/0012.png", b"ad51/0012.png"))
        self.assert_no_orphan(names, text)

    def test_a_file_name_with_a_space_or_an_accent_is_written_as_a_uri(self):
        self.cite_views(self.views("Vue 7 été.png"))
        _path, names, text, _out = self.archive()
        self.assertIn("media/Vue 7 été.png", names)   # the entry keeps its name; GEDCOM 7's FILE is a URI
        self.assertIn("1 FILE media/Vue%207%20%C3%A9t%C3%A9.png\n", text)
        self.assert_no_orphan(names, text)

    def test_a_view_no_file_holds_is_left_out_and_said(self):
        images = self.views("e-1795-1.jpg")
        gone, url = "evidence/images/e-1795-2.jpg", "https://example.org/vue.jpg"
        self.cite_views(images + [gone, url])
        _path, names, text, out = self.archive()
        self.assertEqual(names, ["gedcom.ged", "media/e-1795-1.jpg"])
        self.assertEqual(re.findall(r"^1 FILE (.*)$", text, re.M), ["media/e-1795-1.jpg"])
        self.assertIn("STATUS=WARN", out)
        self.assertIn("MEDIA_MISSING=2", out)
        self.assertIn(f"{gone}, {url}", out)
        self.assert_no_orphan(names, text)
        code, out = self.call("export", "gedcom551")   # 5.5.1 points at the family's folder: the same views
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.dir, out.split("FILE=")[1].split()[0]), encoding="utf-8") as fh:
            ged = fh.read()
        self.assertEqual(re.findall(r"^1 FILE (.*)$", ged, re.M), ["../families/hugo/evidence/images/e-1795-1.jpg"])
        self.assertNotIn("vue.jpg", ged)   # the URL view, and e-1795-2, are named nowhere
        self.assertNotIn("e-1795-2", ged)

    def test_a_source_whose_views_are_all_gone_has_no_media_object(self):
        self.cite_views(["evidence/images/e-1795-9.jpg"])
        _path, names, text, out = self.archive()
        self.assertEqual(names, ["gedcom.ged"])
        self.assertNotIn("OBJE", text)
        self.assertIn("MEDIA=0", out)
        self.assertIn("MEDIA_MISSING=1", out)


class Gedcom551(Project):
    def test_header_lines_and_media(self):
        self.use_tree()
        os.makedirs(os.path.join(self.family, "evidence", "images"), exist_ok=True)   # a view no file holds is left out
        with open(os.path.join(self.family, "evidence", "images", "e-1802-n-45.jpg"), "wb") as fh:
            fh.write(b"jpeg")
        doc = yamlio.load(os.path.join(self.family, "index", "sources.yaml"))
        doc["sources"][0]["citation"] = "x" * 600
        doc["sources"][0]["repository"] = "Archives " + "très " * 80
        yamlio.dump(os.path.join(self.family, "index", "sources.yaml"), doc)
        code, out = self.call("export", "gedcom551")
        self.assertEqual(code, 0, out)
        path = os.path.join(self.dir, out.split("FILE=")[1].split()[0])
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for line in ("1 CHAR UTF-8", "2 VERS 5.5.1", "2 FORM LINEAGE-LINKED", "1 SUBM @U1@", "0 @U1@ SUBM",
                     "2 NOTE Status: record", "1 FILE ../families/hugo/evidence/images/e-1802-n-45.jpg"):
            self.assertIn(line + "\n", text)
        self.assertNotIn("_STATUS", text)
        self.assertNotIn("_HYPO", text)
        self.assertIn("NOTE Hypothesis: Who was the father", text)
        self.assertTrue(all(len(line) <= 255 for line in text.splitlines()))
        self.assertIn("\n2 CONC ", text)
        title = next(r for r in gedcom.parse(text) if r.tag == "SOUR").text("TITL")
        self.assertEqual(title, "Archives " + "très " * 80 + ", État civil, Besançon")


class Reader(unittest.TestCase):
    def test_ansel_and_conc(self):
        data = read = gedcom_import.read(os.path.join(GED, "oldtree-551-ansel.ged"))
        names = sorted(f"{p['given']} {p['surname']}" for p in data["persons"].values())
        self.assertEqual(names, ["François STRAßE", "Léopold HUGOT", "Sophie TRÉBUCHET", "Victor HUGO"])
        self.assertEqual(read["persons"]["@I1@"]["note"], "A long note that is cut into two lines by the old program.")
        self.assertEqual(read["persons"]["@I3@"]["events"][0]["place"], "Nantes")

    def test_gedcom7_cont_and_dates(self):
        data = gedcom_import.read(os.path.join(GED, "tree-7.ged"))
        self.assertEqual(data["version"], "7.0")
        jean = data["persons"]["@I1@"]
        self.assertEqual(jean["note"], "First line\nsecond line")
        self.assertEqual(jean["events"][1]["date"]["calendar"], "republican")
        self.assertEqual(jean["events"][1]["date"]["value"], "1803-09-26")
        self.assertEqual(gedcom.parse_date("@#DJULIAN@ 3 JAN 1795")["value"], "1795-01-14")
        self.assertIsNone(gedcom.parse_date("(sometime in spring)"))


class ImportGedcom(Project):
    def test_only_hypotheses_and_reasons(self):
        code, out = self.call("import-gedcom", os.path.join(GED, "oldtree-551-ansel.ged"))
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "PERSONS"), self.value(out, "MATCHED"), self.value(out, "PROPOSALS")),
                         ("4", "2", "3"))
        self.assertIn("victor-hugo-1802: surname HUGO sounds as HUGO", out)
        self.assertIn("birth 1802 and 1802, 0 year(s) apart", out)
        self.assertIn("francois-strasse-1853: no match in the family", out)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "work", "import", "oldtree-551-ansel.yaml")))
        folder = os.path.join(self.family, "research", RID, "work", "proposals")
        for name in sorted(os.listdir(folder)):
            code, out = self.call("apply", name[:-5])
            self.assertEqual(code, 0, out)
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))["persons"]
        imported = [f for p in persons for f in p["facts"] if "GEDCOM" in (f.get("note") or "")]
        self.assertEqual({f["status"] for f in imported}, {"hypothesis"})
        theo = next(p for p in persons if p["id"] == "victor-hugo-1802")
        self.assertIn("victor-hugo-1802.birth.2", [f["id"] for f in theo["facts"]])
        self.assertIn("matched because", next(f["note"] for f in theo["facts"] if f["id"].endswith("birth.2")))

    def test_no_match_on_the_name_alone(self):
        person = {"given": "Victor", "surname": "Hugo", "events": [
            {"type": "birth", "date": {"value": "1890"}, "place": "Metz", "sources": []}]}
        family = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))["persons"]
        self.assertEqual(gedcom_import.match(person, family), (None, []))


class GrampsWeb(Project):
    def test_restore_flow(self):
        calls = []

        def fake(method, url, data=None, token=None, content_type="application/json", timeout=120):
            calls.append((method, url))
            if url.endswith("/api/token/"):
                return 200, {"access_token": "jwt"}
            if "/file/restore" in url:
                return 202, {"task": {"id": "t1"}}
            if url.endswith("/api/tasks/t1"):
                n = sum(1 for c in calls if c[1].endswith("t1"))
                return 200, ({"state": "STARTED"} if n == 1 else
                             {"state": "SUCCESS", "result": {"to_add": {"people": 3}, "to_delete": {"people": 0}}})
            raise AssertionError(url)
        for k, v in (("gramps.url", "http://gw.test"), ("gramps.user", "owner"), ("grade", "expert")):
            self.call("config", "set", k, v)
        with mock.patch.object(grampsweb, "_request", fake), mock.patch.object(grampsweb.time, "sleep"):
            code, out = self.call("export", "gramps", "--dry-run", env={"PROBANDIA_GRAMPS_PASSWORD": "pw"})
        self.assertEqual(code, 0, out)
        self.assertIn(("POST", "http://gw.test/api/importers/ged/file/restore?dry_run=true"), calls)
        self.assertIn("- changes=to_add people 3", out)

    def test_at_a_terminal_the_dry_run_is_shown_and_a_no_restores_nothing(self):
        """T157: the question gives the dry run's counts; a no sends no restore."""
        class TTY(io.StringIO):
            def isatty(self):
                return True
        calls = []

        def fake(method, url, data=None, token=None, content_type="application/json", timeout=120):
            calls.append((method, url))
            if url.endswith("/api/token/"):
                return 200, {"access_token": "jwt"}
            if url.endswith("/file/restore?dry_run=true"):
                return 200, {"to_add": {"people": 3}, "to_delete": {"people": 2}}
            raise AssertionError(url)   # the restore itself
        for k, v in (("gramps.url", "http://gw.test"), ("gramps.user", "owner"), ("grade", "expert")):
            self.call("config", "set", k, v)
        out = TTY()
        with mock.patch.object(grampsweb, "_request", fake):
            code = cli.main(["export", "gramps"], stdout=out, stdin=TTY("n\n"), cwd=self.dir,
                            environ=dict(self.env, PROBANDIA_GRAMPS_PASSWORD="pw", NO_COLOR="1",
                                         PROBANDIA_PAGER="none"))
        out = out.getvalue()
        self.assertIn("to_add people 3; to_delete people 2", out)
        self.assertIn("[y/N]", out)
        self.assertEqual(code, 4, out)
        self.assertIn("declined", out)
        self.assertNotIn(("POST", "http://gw.test/api/importers/ged/file/restore"), calls)

    def test_needs_the_password(self):
        for k, v in (("gramps.url", "http://gw.test"), ("gramps.user", "owner"), ("grade", "expert")):
            self.call("config", "set", k, v)
        code, out = self.call("export", "gramps")
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=no-password", out)


class Transcription(Project):
    def test_template_check_and_the_fact(self):
        code, out = self.call("transcribe", "template", SRC1)
        self.assertEqual(code, 0, out)
        code, out = self.call("transcribe", "check", SRC1)
        self.assertEqual(code, 1, out)
        self.assertIn("the table of persons is empty", out)
        shutil.copy(os.path.join(ROOT, "tests", "fixtures", "transcription", f"{SRC1}.md"),
                    os.path.join(self.family, "evidence", "transcriptions", f"{SRC1}.md"))
        code, out = self.call("transcribe", "check", SRC1, "--name", "Léopold Hugot")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "LINES"), self.value(out, "PERSONS"), self.value(out, "DOUBTS")),
                         ("7", "4", "1"))
        reading = self.value(out, "UNCERTAIN_READING")
        self.assertIn("'Hugot'[?] or 'Hugo'", reading)
        # the doubtful name goes on the fact, through a proposal
        proposal = {"schema": 1, "id": "01J9ZM00000000000000000077", "research": RID, "pass": 1,
                    "author": {"harness": "cli", "agent": "reader"},
                    "facts": [{"id": "leopold-hugo-1773.occupation", "type": "occupation", "status": "record",
                               "value": "officier", "source": SRC1, "uncertain_reading": reading}]}
        path = os.path.join(self.tmp.name, "p.yaml")
        yamlio.dump(path, proposal)
        self.call("propose", RID, path)
        code, out = self.call("apply", proposal["id"])
        self.assertEqual(code, 0, out)
        persons = yamlio.load(os.path.join(self.family, "index", "persons.yaml"))["persons"]
        fact = next(f for p in persons for f in p["facts"] if f["id"] == "leopold-hugo-1773.occupation")
        self.assertEqual(fact["uncertain_reading"], reading)

    def test_parts_and_notation(self):
        problems, parsed = transcription.check(transcription.template("src-x", "img.jpg"))
        self.assertIn("the diplomatic transcription is empty", problems)
        text = transcription.template("src-x", "img.jpg", lines=["Joseph Hugot[?] [&#8230;]", "witness"])
        problems, parsed = transcription.check(text.replace("- none", "- line 1: Hugot or Hugo", 1)
                                               .replace("|---|---|---|---|---|---|---|",
                                                        "|---|---|---|---|---|---|---|\n| child | Jean | Jean | | | | |"))
        self.assertEqual(problems, [])
        self.assertEqual(parsed["doubts"], [{"line": 1, "word": "Hugot"}])
        self.assertEqual(transcription.check_dates("le 31 février 1802"), [("31 février 1802", mock.ANY)])

    def test_the_blank_the_addition_the_other_hand_and_what_was_not_read(self):
        # T246: each mark a fact may rest on is a doubt; nothing restored or not understood is normalised
        lines = ["N° 7 Marchand Henri", "né le {blank} mars, fils de Pierre Marchand {above: et de Marie Lebrun}",
                 "le {over: 7 > 8} du mois, Jean {restored: Baptiste} Martin, témoin",
                 "{hand: reconnu le 3 mai 1872} {struck: Paul} dlle {margin: vu}"]
        text = (transcription.template(SRC1, "e-1870-7.jpg", lines=lines)
                .replace("| Image state | good |", "| Image state | faded, lines 3-4 |")
                .replace("## Normalised transcription\n\n…", "## Normalised transcription\n\nNumber 7, Marchand, "
                         "Henri, born on … March, son of Pierre Marchand and of Marie Lebrun; witness Jean Martin.")
                .replace("|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|\n| child | Henri | Henri | | | | |")
                .replace("## Not understood\n\n- none", "## Not understood\n\n- line 4: 'dlle' (an abbreviation?)"))
        problems, parsed = transcription.check(text)
        self.assertEqual(problems, [])
        self.assertEqual([(m["line"], m["kind"]) for m in parsed["marks"]],
                         [(2, "blank"), (2, "above"), (3, "over"), (3, "restored"), (4, "hand")])
        self.assertEqual(parsed["image_state"], "faded, lines 3-4")
        # the restored name, or the passage not understood, asserted by the normalised text
        for said, why in (("witness Jean Baptiste Martin.", "'Baptiste' is restored, not read"),
                          ("witness Jean Martin, dlle.", "'dlle' is not understood")):
            with self.subTest(said=said):
                problems, _parsed = transcription.check(text.replace("witness Jean Martin.", said))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(why, problems[0])
        # kept marked, it is not asserted
        problems, _parsed = transcription.check(text.replace("witness Jean Martin.",
                                                             "witness Jean {restored: Baptiste} Martin."))
        self.assertEqual(problems, [])
        path = os.path.join(self.family, "evidence", "transcriptions", f"{SRC1}.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        code, out = self.call("transcribe", "check", SRC1, "--name", "Pierre Marchand")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "DOUBTS"), "6")
        self.assertEqual(self.value(out, "IMAGE_STATE"), "faded, lines 3-4")
        self.assertIn("look for the register's other copy", out)
        doubts = [line[len("- doubt="):] for line in out.splitlines() if line.startswith("- doubt=")]
        self.assertEqual(doubts, ["line 2: {blank}", "line 2: {above: et de Marie Lebrun}", "line 3: {over: 7 > 8}",
                                  "line 3: {restored: Baptiste}", "line 4: {hand: reconnu le 3 mai 1872}",
                                  "not understood: line 4: 'dlle' (an abbreviation?)"])
        # the father's line: the blank and the addition go on his facts
        self.assertEqual(self.value(out, "UNCERTAIN_READING"), "line 2, {blank}; line 2, {above: et de Marie Lebrun}")
        code, out = self.call("transcribe", "check", SRC1, "--name", "Jean Martin")
        self.assertEqual(self.value(out, "UNCERTAIN_READING"), "line 3, {over: 7 > 8}; line 3, {restored: Baptiste}")

    def test_a_second_reading_made_blind_is_compared_with_the_first(self):
        # T245: the second reader's skeleton sits next to the first; compare lists where they differ
        evidence = os.path.join(self.family, "evidence", "transcriptions")
        os.makedirs(evidence, exist_ok=True)
        shutil.copy(os.path.join(ROOT, "tests", "fixtures", "transcription", f"{SRC1}.md"),
                    os.path.join(evidence, f"{SRC1}.md"))
        code, out = self.call("transcribe", "template", SRC1, "--second")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "DETAILS"), f"families/hugo/evidence/transcriptions/{SRC1}.2.md")
        self.assertIn("without opening the first transcription", out)
        with open(os.path.join(evidence, f"{SRC1}.md"), encoding="utf-8") as fh:
            first = fh.read()
        # the same words cut into other lines, punctuation and case aside, read alike
        same = first.replace("de la République, à dix heures du matin,\n3. par devant",
                             "de la République à dix heures du matin\n3. Par devant")
        with open(os.path.join(evidence, f"{SRC1}.2.md"), "w", encoding="utf-8") as fh:
            fh.write(same)
        code, out = self.call("transcribe", "compare", SRC1, f"{SRC1}.2", "--name", "Léopold Hugot")
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=OK", out)
        self.assertEqual(self.value(out, "DIVERGENCES"), "0")
        second = same.replace("Léopold Hugot[?], chef", "Léopold Hugo, chef").replace("à […] heures", "à six heures")
        with open(os.path.join(evidence, f"{SRC1}.2.md"), "w", encoding="utf-8") as fh:
            fh.write(second)
        code, out = self.call("transcribe", "compare", SRC1, f"{SRC1}.2", "--name", "Léopold Hugot")
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=WARN", out)
        self.assertEqual(self.value(out, "DIVERGENCES"), "2")
        doubts = [line for line in out.splitlines() if line.startswith("- doubt=")]
        self.assertEqual(doubts, ["- doubt=line 4: 'Hugot[?]' or 'Hugo'", "- doubt=line 5: '[…]' or 'six'"])
        # only the divergence on the person's line goes on the fact
        self.assertEqual(self.value(out, "UNCERTAIN_READING"), "line 4: 'Hugot[?]' or 'Hugo'")
        # two different acts, or one reading missing, are no comparison
        with open(os.path.join(evidence, f"{SRC1}.2.md"), "w", encoding="utf-8") as fh:
            fh.write(second.replace(f"| Source | {SRC1} |", "| Source | src-other |"))
        code, out = self.call("transcribe", "compare", SRC1, f"{SRC1}.2")
        self.assertEqual(code, 1, out)
        self.assertIn("not the same source", out)
        self.assertEqual(self.call("transcribe", "compare", SRC1)[0], 2)

    def test_readings_are_aligned_word_by_word(self):
        found = transcription.compare(["Jean Martin,", "tailleur, et Pierre"], ["Jean Martin tailleur", "et Paul"])
        self.assertEqual([(d["lines"], d["text"]) for d in found], [([2], "line 2: 'Pierre' or 'Paul'")])
        found = transcription.compare(["Jean Martin", "tailleur"], ["Jean", "Martin tailleur menuisier"])
        self.assertEqual([d["text"] for d in found], ["line 2: '' or 'menuisier'"])

    def test_region_sizes(self):
        self.assertEqual(transcription.region_size("full"), "1500,")
        self.assertEqual(transcription.region_size("0,0,4000,3000"), "!2576,2576")
        self.assertEqual(transcription.region_size("0,0,4000,3000", 5000), "2576,")

    def test_ocr_without_tesseract(self):
        with mock.patch("shutil.which", return_value=None):
            code, out = self.call("transcribe", "ocr", "page.png")
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=no-tesseract", out)

    def test_ocr_when_tesseract_fails_or_hangs(self):
        """T152: a failing Tesseract, here python running a script that exits 1, is REASON=tesseract-failed."""
        fake = os.path.join(self.tmp.name, "page.py")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.stderr.write('Failed loading language fra\\n')\nsys.exit(1)\n")
        with mock.patch("shutil.which", return_value=sys.executable):
            code, out = self.call("transcribe", "ocr", fake)
        self.assertNotIn(code, (0, 10), out)
        self.assertIn("REASON=tesseract-failed", out.splitlines(), out)
        self.assertIn("language pack fra", out)
        hang = subprocess.TimeoutExpired("tesseract", 120)
        with mock.patch("shutil.which", return_value="tesseract"), mock.patch("subprocess.run", side_effect=hang):
            code, out = self.call("transcribe", "ocr", "page.png")
        self.assertNotIn(code, (0, 10), out)
        self.assertIn("REASON=tesseract-failed", out.splitlines(), out)
        self.assertIn("no answer after 120 s", out)


class Skills(unittest.TestCase):
    def test_transcribe_skill(self):
        with open(os.path.join(ROOT, "skills", "transcribe", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertLess(len(text.splitlines()), 300)
        for needle in ("2,576", "[?]", "{margin:", "uncertain_reading", "transcribe check",
                       "transcribe new --image",   # token-economy B5
                       "{blank}", "{above:", "{over: a > b}", "{hand:", "{restored:", "**Not understood**",
                       "image state", "nothing restored or not understood goes into the normalised"):   # T246
            self.assertIn(needle, text)
        from probandia import transcription as T   # the skill's marks are the engine's
        for mark in re.findall(r"^\| `(\{[^`]*\})` \|", text, re.M):
            self.assertTrue(T.MARK.fullmatch(mark.replace("…", "x")) or mark.startswith(("{struck:", "{margin:")), mark)
