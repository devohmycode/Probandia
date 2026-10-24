"""Reading and writing the workshop's personnes.yaml line by line (docs/workshop-sync.md, WS2)."""
import datetime
import os
import unittest

from probandia.lang.dates import french, read
from probandia.util import yamlio
from probandia.workshop.prototype import render, scan
from tests import ROOT

WORKSHOP = os.path.join(ROOT, "tests", "fixtures", "workshop")
CRLF = os.path.join(ROOT, "tests", "fixtures", "workshop-crlf")


def people_text(folder):
    with open(os.path.join(folder, "commun", "personnes.yaml"), encoding="utf-8", newline="") as fh:
        return fh.read()


class Scan(unittest.TestCase):
    """WS2-T1: every person and every key found, with the same spans in CRLF and LF."""

    def test_every_person_and_key(self):
        text = people_text(WORKSHOP)
        data = yamlio.loads(text)
        layout = scan.Layout(text)
        self.assertEqual([p.id for p in layout.persons], [p["id"] for p in data["personnes"]])
        for p, raw in zip(layout.persons, data["personnes"]):
            self.assertEqual(list(p.keys), list(raw), p.id)
            for key, (a, b) in p.keys.items():
                # each span read alone gives the key's value back
                chunk = "".join(layout.lines[a:b]).replace("  - id:", "    id:", 1)
                self.assertEqual(yamlio.loads(_dedent(chunk)), {key: raw[key]}, (p.id, key))
        self.assertEqual(len(layout.unions), len(data["unions"]))
        a, b = layout.unions[0]
        self.assertEqual(yamlio.loads("".join(layout.lines[a:b]))[0], data["unions"][0])
        (a, b), = layout.person("victor-hugo-1802").items["recherches"]
        self.assertEqual((b - a, layout.lines[a][:9]), (2, "      - {"))
        self.assertEqual(layout.lines[layout.updated].rstrip(), "  mis_a_jour: 2026-08-10")
        self.assertEqual(len([b for b in layout.banners if "GÉNÉRATION" in b[1]]), 2)

    def test_same_spans_in_crlf_and_lf(self):
        lf, crlf = scan.Layout(people_text(WORKSHOP)), scan.Layout(people_text(CRLF))
        self.assertEqual((lf.newline, crlf.newline), ("\n", "\r\n"))
        self.assertEqual([(p.id, p.start, p.end, p.keys, p.items) for p in lf.persons],
                         [(p.id, p.start, p.end, p.keys, p.items) for p in crlf.persons])
        self.assertEqual((lf.unions, lf.top, lf.updated, lf.banners, lf.persons_end),
                         (crlf.unions, crlf.top, crlf.updated, crlf.banners, crlf.persons_end))

    def test_braces_skip_quotes_escapes_and_comments(self):
        # T266: the depth now goes from one character that matters to the next
        for line, depth in (('    deces: {date: "1885", lieu: "Paris",', 1), ('k: {a: "x # y {"}  # {', 0),
                            ('k: {n: "il dit \\"{\\""}', 0), ("k: it's {", 1),
                            ('k: "\\\\" {', 1), ("# {", 0), ("k: a#b {", 1), ("       note: x}", -1)):
            with self.subTest(line):
                self.assertEqual(scan.braces(line), depth)


def _dedent(chunk):
    return "\n".join(line[4:] for line in chunk.replace("\r\n", "\n").split("\n"))


class Render(unittest.TestCase):
    """WS2-T2: five facts of the test workshop rendered: the same values, the same text."""

    def test_five_facts_as_written(self):
        text = people_text(WORKSHOP)
        data, layout = yamlio.loads(text), scan.Layout(text)
        victor, leopold = layout.persons[0], layout.persons[1]
        cases = [(victor.keys["naissance"], "    naissance: ", data["personnes"][0]["naissance"]),
                 (victor.keys["deces"], "    deces: ", data["personnes"][0]["deces"]),
                 (victor.items["recherches"][0], "      - ", data["personnes"][0]["recherches"][0]),
                 (leopold.keys["naissance"], "    naissance: ", data["personnes"][1]["naissance"])]
        for (a, b), prefix, fact in cases:
            with self.subTest(prefix=prefix, fact=fact.get("date")):
                lines = render.flow(fact, prefix)
                self.assertEqual(lines, [x.rstrip("\n") for x in layout.lines[a:b]])
                self.assertTrue(all(len(x) <= render.WIDTH for x in lines))
                back = yamlio.loads("\n".join(lines).replace(prefix, "k: ", 1).replace("      - ", "k: ", 1))
                self.assertEqual(back["k"], fact)
        a, b = layout.unions[0]
        lines = render.block(data["unions"][0])
        self.assertEqual(lines, [x.rstrip("\n") for x in layout.lines[a:b]])
        self.assertEqual(yamlio.loads("\n".join(lines))[0], data["unions"][0])

    def test_quotes_and_plain(self):
        lines = render.flow({"date": "vers 1850", "annee": 1850, "statut": "acte", "volet": "III",
                             "note": 'il dit "oui"'}, "    deces: ")
        self.assertEqual(lines, ['    deces: {date: "vers 1850", annee: 1850, statut: acte, volet: III, '
                                 'note: "il dit \\"oui\\""}'])
        self.assertEqual(yamlio.loads(lines[0].strip())["deces"]["note"], 'il dit "oui"')
        self.assertEqual(render.block({"epoux": "a-1", "epouse": "b-2", "annee": 1929, "date": "1929",
                                       "lieu": "Nancy"}),
                         ["  - epoux: a-1", "    epouse: b-2", "    annee: 1929", '    date: "1929"',
                          "    lieu: Nancy"])
        # T175: a union whose husband the workshop does not know, as it writes it
        lines = render.block({"epoux": None, "epouse": "b-2", "annee": 1750})
        self.assertEqual(lines, ["  - epoux: null", "    epouse: b-2", "    annee: 1750"])
        self.assertIsNone(yamlio.loads("\n".join(lines))[0]["epoux"])


class Dates(unittest.TestCase):
    """WS2-T3: the dates of the workshop, read then written back."""

    # the dates of docs/workshop-sync.md (Constats, WS2-T3), and how a workshop writes them
    WRITTEN = {"16 déc. 1847": ("1847-12-16", "exact", None), "vers 1850": ("1850", "about", None),
               "29 juil. 1984": ("1984-07-29", "exact", None), "sept. 1929": ("1929-09", "exact", None),
               "avant 1890": ("1890", "before", None), "entre 1839 et 1849": ("1839", "between", "1849"),
               "1er janv. 1850": ("1850-01-01", "exact", None), "après 1850": ("1850", "after", None)}
    # read, but written otherwise: their own text stays in date.original, which the push writes back
    KEPT = {"1839-1849": ("1839", "between", "1849"), "9 oct. 1930 à 5 h 30": ("1930-10-09", "exact", None),
            "14 août 2026 à 10 h 30": ("2026-08-14", "exact", None), "26 février 1802": ("1802-02-26", "exact", None)}

    def test_round_trip(self):
        for text, want in self.WRITTEN.items():
            with self.subTest(text=text):
                d = read(text)
                self.assertEqual((d["iso"], d["qualifier"], d["end"]), want)
                self.assertEqual(french(d["iso"], d["qualifier"], d["end"]), text)
        for text, want in self.KEPT.items():
            with self.subTest(text=text):
                d = read(text)
                self.assertEqual((d["iso"], d["qualifier"], d["end"]), want)
                again = read(french(d["iso"], d["qualifier"], d["end"]))
                self.assertEqual((again["iso"], again["qualifier"], again["end"]), want)


class Write(unittest.TestCase):
    """WS2-T4 to T6 and WS2 acceptance: the four insertions on a CRLF copy add lines only, plus mis_a_jour."""

    def setUp(self):
        import shutil
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "personnes.yaml")
        shutil.copyfile(os.path.join(CRLF, "commun", "personnes.yaml"), self.path)
        with open(self.path, "rb") as fh:
            self.before = fh.read()

    def writer(self):
        from probandia.workshop.prototype.write import Writer

        return Writer(self.path)

    def four(self, w):
        w.add_fact("sophie-trebuchet-1772", "deces", {"date": "27 juin 1821", "annee": 1821, "lieu": "Paris",
                                                      "statut": "acte", "volet": "III", "chapitre": "I",
                                                      "rapport": "paris-1822", "source": "Acte de décès, Paris."})
        w.add_fact("victor-hugo-1802", "recherches", {"date": "2 sept. 2026", "annee": 2026,
                                                      "fait": "relevé des tables décennales", "statut": "index",
                                                      "volet": "III", "chapitre": "I"})
        w.add_union({"epoux": "victor-hugo-1802", "epouse": "adele-foucher-1803", "annee": 1822,
                     "date": "12 oct. 1822", "lieu": "Paris", "statut": "acte", "volet": "III", "chapitre": "I",
                     "rapport": "paris-1822"})
        w.add_person({"id": "adele-foucher-1803", "nom": "FOUCHER", "prenoms": "Adèle", "sexe": "F",
                      "statut": "acte", "volet": "III", "chapitre": "I", "rapport": "paris-1822"},
                     [("naissance", {"date": "27 sept. 1803", "annee": 1803, "lieu": "Paris", "statut": "acte",
                                     "volet": "III", "chapitre": "I", "source": "Acte de naissance, Paris."})])
        w.add_refutation("leopold-hugo-1773", "naissance", None, "III")
        w.touch(datetime.date(2026, 10, 17))

    def test_acceptance(self):
        import difflib

        w = self.writer()
        self.four(w)
        w.write()
        with open(self.path, "rb") as fh:
            after = fh.read()
        old, new = self.before.decode("utf-8"), after.decode("utf-8")
        self.assertEqual(new.count("\r\n"), new.count("\n"))            # CRLF kept, inserted lines included
        diff = [x for x in difflib.ndiff(old.splitlines(), new.splitlines()) if x[:1] in "+-"]
        self.assertEqual([x for x in diff if x.startswith("- ")], ["-   mis_a_jour: 2026-08-10"])
        self.assertIn("+   mis_a_jour: 2026-10-17", diff)
        self.assertEqual(len([x for x in diff if x.startswith("+ ")]), len(new.splitlines()) - len(old.splitlines()) + 1)
        self.assertEqual([x for x in old.splitlines() if x.lstrip().startswith("#")],
                         [x for x in new.splitlines() if x.lstrip().startswith("#") and "Probandia" not in x])
        data = yamlio.loads(new)
        self.assertEqual(data["personnes"][2]["deces"]["date"], "27 juin 1821")
        self.assertEqual(data["personnes"][0]["recherches"][1]["fait"], "relevé des tables décennales")
        self.assertEqual(data["unions"][1]["epouse"], "adele-foucher-1803")
        self.assertEqual(data["personnes"][3]["id"], "adele-foucher-1803")
        self.assertEqual(data["personnes"][1]["naissance"]["volet_refute"], "III")
        self.assertEqual(str(data["meta"]["mis_a_jour"]), "2026-10-17")
        self.assertIn("\r\n  # Ajouts de Probandia — à reclasser\r\n", new)

    def test_changed_between_reading_and_writing_is_stop(self):
        from probandia.workshop.prototype.write import Changed

        w = self.writer()
        self.four(w)
        with open(self.path, "ab") as fh:
            fh.write(b"# by hand\r\n")
        with self.assertRaises(Changed):
            w.write()
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), self.before + b"# by hand\r\n")

    def test_malformed_is_fail_with_the_file_intact(self):
        from probandia.workshop.prototype.write import Malformed

        w = self.writer()
        self.four(w)
        w.inserts.append((w.layout.persons[0].keys["naissance"][1], ["    deces2: {date: oops"], False))
        with self.assertRaises(Malformed):
            w.write()
        w = self.writer()
        w.inserts.append((w.layout.persons[0].keys["naissance"][1], ["    profession: \"maire\""], False))
        with self.assertRaises(Malformed):                               # reads, but not as planned
            w.write()
        with self.assertRaises(Malformed):                               # a one-line flow map
            self.writer().add_refutation("sophie-trebuchet-1772", "naissance", None, "III")
        with self.assertRaises(Malformed):                               # never a second birth
            self.writer().add_fact("victor-hugo-1802", "naissance", {"annee": 1802})
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), self.before)

    def test_each_insertion_alone_adds_lines_only(self):
        import difflib

        for n in range(5):
            with self.subTest(n=n):
                with open(self.path, "wb") as fh:
                    fh.write(self.before)
                w = self.writer()
                self.four(w)
                w.inserts = [w.inserts[n]]
                w.replaced = {}
                import copy as _copy
                expected = _copy.deepcopy(w.data)
                w.expected = expected
                text = w.result()
                diff = [x for x in difflib.ndiff(self.before.decode().splitlines(), text.splitlines())
                        if x[:1] in "+-"]
                self.assertFalse([x for x in diff if x.startswith("- ")])
                self.assertTrue(diff)
                self.assertEqual(text.count("\r\n"), text.count("\n"))
