"""Excerpts: the passage of its source a fact reads (TRUST1)."""
import importlib.util
import json
import os
import shutil
import unittest

from probandia import excerpt as X
from probandia.util import yamlio
from probandia.util.schema import SchemaError, validate_document
from tests import ROOT
from tests.integration import test_sample_project as sample
from tests.unit import test_data_layer

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
SRC1 = "src-01J9ZK3M4X0000000000000001"
LINES = ["L'an mil huit cent soixante-dix, le quatorze mars,", "à dix heures du matin, devant nous,",
         "est comparu Pierre MARCHAND, cultivateur,", "lequel nous a présenté un enfant",
         "du sexe masculin, né ce jour, qu'il a nommé Henri."]


class Excerpt(unittest.TestCase):
    def test_from_lines(self):
        e = X.from_lines(LINES, 3, 5)
        self.assertEqual(e["kind"], "transcription")
        self.assertEqual(e["lines"], [3, 5])
        self.assertTrue(e["text"].startswith("est comparu Pierre MARCHAND"))
        self.assertEqual(e["sha256"], X.digest(" ".join(LINES[2:5])))
        self.assertEqual(X.digest("a  b\n c"), X.digest("a b c"))
        with self.assertRaises(ValueError):
            X.from_lines(LINES, 4, 6)
        with self.assertRaises(ValueError):
            X.from_lines(["x" * 300, "y" * 300], 1, 2)

    def test_from_page(self):
        page = "Titre\n\nPremier   paragraphe.\nLe second dit Henri MARCHAND, né en 1870."
        at = X.offset_of(page, "Henri MARCHAND, né en 1870")
        e = X.from_page(page, at, len("Henri MARCHAND, né en 1870"), url="https://example.org/p", captured="2026-10-05")
        self.assertEqual((e["text"], e["captured"]), ("Henri MARCHAND, né en 1870", "2026-10-05"))
        self.assertEqual(X.locate(e, text=page), [])
        self.assertEqual(X.locate(e, text=page.replace("1870", "1871")), ["the page does not contain it"])
        self.assertEqual(X.locate(e, text=None), ["the page is not kept on this computer"])

    def test_locate_in_a_transcription(self):
        e = X.from_lines(LINES, 3, 3)
        self.assertEqual(X.locate(e, lines=LINES), [])
        changed = list(LINES)
        changed[2] = "est comparu Pierre MARCHANT, cultivateur,"
        self.assertEqual(X.locate(e, lines=changed),
                         ["lines 3-3 do not read so; the closest is line 3: est comparu Pierre MARCHANT, cultivateur,"])
        self.assertEqual(X.locate(e, lines=LINES[:2]), ["lines 3-3 are not in the transcription, which has 2"])
        self.assertEqual(X.locate(dict(e, text=e["text"] + "!"), lines=LINES), ["its text does not match its sha256"])


class Schema(unittest.TestCase):
    """TRUST1-T1: the excerpt of a fact, optional."""

    def persons(self):
        return yamlio.load(os.path.join(FIXTURES, "persons", "valid", "fixture-family.yaml"))

    def test_accepted_and_refused(self):
        doc = self.persons()
        validate_document("persons", doc, "without")   # a fact without an excerpt stays valid
        fact = doc["persons"][0]["facts"][0]
        fact["excerpt"] = X.from_lines(LINES, 1, 2)
        validate_document("persons", doc, "with")
        for key in ("text", "sha256", "kind"):
            broken = dict(X.from_lines(LINES, 1, 2))
            del broken[key]
            fact["excerpt"] = broken
            with self.assertRaises(SchemaError, msg=key):
                validate_document("persons", doc, "broken")
        fact["excerpt"] = dict(X.from_lines(LINES, 1, 2), sha256="abc")
        with self.assertRaises(SchemaError):
            validate_document("persons", doc, "short sha256")


class Quote(test_data_layer.Project):
    """TRUST1-T2: the excerpt of lines of a transcription, ready for a proposal."""

    def value(self, out, key):
        return next((line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "=")), None)

    def transcription(self):
        folder = os.path.join(self.family, "evidence", "transcriptions")
        os.makedirs(folder, exist_ok=True)
        shutil.copy(os.path.join(FIXTURES, "transcription", f"{SRC1}.md"), folder)

    def test_quote(self):
        self.transcription()
        code, out = self.call("transcribe", "quote", SRC1, "--lines", "3-5")
        self.assertEqual(code, 0, out)
        found = json.loads(out.split("- excerpt=", 1)[1].splitlines()[0])
        self.assertEqual(found["lines"], [3, 5])
        self.assertTrue(found["text"].startswith("par devant nous officier de l'état civil"))
        self.assertEqual(self.value(out, "DIGEST"), found["sha256"])
        code, out = self.call("transcribe", "quote", SRC1, "--lines", "6-9")
        self.assertEqual(code, 2, out)
        self.assertIn("lines 6-9 are not in the transcription, which has 7", out)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_a_small_view_or_what_is_made_from_it_is_never_transcribed(self):
        # J10, the guard of J2 alone: a small view and a whole one share a name, a crop is named anything
        from PIL import Image

        from probandia import images

        folder = os.path.join(self.rdir, "work", "images")
        os.makedirs(folder)
        view = os.path.join(folder, "ad50-607643-0090.jpg")
        Image.new("RGB", (800, 600), "white").save(view)
        images.mark_small(self.dir, view)   # as ad50.view does with "size": 800
        act = os.path.join(folder, "act54.jpg")
        code, text = self.call("image", "crop", view, "--region", "0,0,0.5,0.5", "--out", act)
        self.assertEqual(code, 0, text)
        for small in (view, act):
            code, text = self.call("transcribe", "new", "--image", small)
            self.assertEqual(code, 2, text)
            self.assertIn("REASON=small-view", text)
        # the whole view saved over it, and the act cropped again from it: transcribed
        Image.new("RGB", (2800, 2100), "white").save(view)
        images.mark_small(self.dir, view, False)   # as ad50.view does without "size"
        code, text = self.call("image", "crop", view, "--region", "0,0,0.4,0.4", "--out", act)
        self.assertEqual(code, 0, text)
        for whole in (view, act):
            self.assertEqual(self.call("transcribe", "new", "--image", whole)[0], 0, whole)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_a_small_view_copied_or_renamed_outside_the_engine_is_never_transcribed(self):
        # T69: the mark follows the image's bytes, not its path; a cp or a mv run by Bash keeps it
        from PIL import Image

        from probandia import images

        folder = os.path.join(self.rdir, "work", "images")
        os.makedirs(folder)
        view = os.path.join(folder, "ad50-607643-0090.jpg")
        Image.new("RGB", (800, 600), "white").save(view)
        images.mark_small(self.dir, view)   # as ad50.view does with "size": 800
        shutil.copy(view, os.path.join(self.dir, "act.jpg"))   # a copy outside the engine
        code, text = self.call("transcribe", "new", "--image", "act.jpg")
        self.assertEqual(code, 2, text)
        self.assertIn("REASON=small-view", text)
        os.replace(view, os.path.join(folder, "act54.jpg"))   # a rename outside the engine
        code, text = self.call("transcribe", "new", "--image", os.path.join(folder, "act54.jpg"))
        self.assertEqual(code, 2, text)
        self.assertIn("REASON=small-view", text)
        # a whole view copied the same way is transcribed, and saved over the copy, it clears it
        whole = os.path.join(folder, "ad50-607643-0091.jpg")
        Image.new("RGB", (2800, 2100), "white").save(whole)
        images.mark_small(self.dir, whole, False)
        shutil.copy(whole, os.path.join(self.dir, "act.jpg"))
        self.assertEqual(self.call("transcribe", "new", "--image", "act.jpg")[0], 0)

    def test_a_source_to_come(self):
        # token-economy B5: the id of a record read before its source is proposed, never `import ulid`
        from probandia.util.ids import is_ulid

        code, out = self.call("transcribe", "new", "--image", "work/dl/view-12.jpg")
        self.assertEqual(code, 0, out)
        source = self.value(out, "SOURCE")
        self.assertTrue(source.startswith("src-") and is_ulid(source[4:]), source)
        entry = json.loads(out.split("- source=", 1)[1].splitlines()[0])
        self.assertEqual(entry, {"id": source, "image": "work/dl/view-12.jpg",
                                 "transcription": f"evidence/transcriptions/{source}.md"})
        with open(os.path.join(self.dir, self.value(out, "DETAILS")), encoding="utf-8") as fh:
            self.assertIn(f"| Source | {source} |", fh.read())
        self.assertEqual(os.path.normpath(X.transcription_path(self.dir, "hugo", entry)),
                         os.path.normpath(os.path.join(self.dir, self.value(out, "DETAILS"))))
        self.assertEqual(self.call("transcribe", "new")[0], 2)   # the image read is required
        self.assertEqual(self.call("transcribe", "check")[0], 2)   # the others still need their target
        code, out = self.call("id", "new", "--prefix", "src")
        self.assertEqual(code, 0, out)
        self.assertRegex(self.value(out, "ID"), r"^src-[0-7][0-9A-HJKMNP-TV-Z]{25}$")
        self.assertTrue(is_ulid(self.value(self.call("id", "new")[1], "ID")))
        self.assertEqual(self.call("id", "new", "--prefix", "Src-")[0], 2)

    def test_an_image_of_the_family_named_from_its_folder(self):
        # T224: given from the project, the image was kept as families/hugo/evidence/…, which a source reads
        # from the family's folder
        folder = os.path.join(self.family, "evidence", "images")
        os.makedirs(folder)
        with open(os.path.join(folder, "act.jpg"), "wb") as fh:
            fh.write(b"\xff\xd8\xff\xd9")
        code, out = self.call("transcribe", "new", "--image", "families/hugo/evidence/images/act.jpg")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out.split("- source=", 1)[1].splitlines()[0])["image"], "evidence/images/act.jpg")

    def test_the_template_names_the_transcription(self):
        code, out = self.call("transcribe", "template", SRC1)
        self.assertEqual(code, 0, out)
        self.assertIn("propose this file as the source's transcription", out)
        path = self.value(out, "DETAILS")   # a path from the project, which an excerpt resolves too
        self.assertEqual(X.transcription_path(self.dir, "hugo", {"id": "x", "transcription": path}),
                         os.path.join(self.dir, path))


class Apply(Quote):
    """TRUST1-T4 and T5: apply finds each excerpt word for word, and keeps the page it quotes."""

    assertRejected = test_data_layer.Apply.assertRejected

    def fact(self, excerpt, source=SRC1, fid="victor-hugo-1802.residence", status="record"):
        return {"id": fid, "type": "residence", "status": status, "value": "Besançon", "source": source,
                "excerpt": excerpt}

    def test_a_transcription_quoted_word_for_word(self):
        self.transcription()
        lines = X.transcription_lines(self.dir, "hugo", {"id": SRC1})
        (code, out), _doc = self.propose_and_apply(facts=[self.fact(X.from_lines(lines, 4, 4))])
        self.assertEqual(code, 0, out)
        fact = next(f for p in self.index("persons")["persons"] for f in p["facts"]
                    if f["id"] == "victor-hugo-1802.residence")
        self.assertEqual(fact["excerpt"]["lines"], [4, 4])
        altered = X.from_lines([line.replace("vingt-huit", "vingt-neuf") for line in lines], 4, 4)
        self.assertRejected("excerpt of fact victor-hugo-1802.occupation: lines 4-4 do not read so; the "
                            "closest is line 4: Léopold Hugot[?], chef de bataillon, âgé de vingt-huit ans",
                            facts=[self.fact(altered, fid="victor-hugo-1802.occupation")])

    def test_an_excerpt_by_reference(self):
        # token-economy B4: {source, lines} is resolved by propose into what transcribe quote gives
        self.transcription()
        code, out = self.call("transcribe", "quote", SRC1, "--lines", "4")
        quoted = json.loads(out.split("- excerpt=", 1)[1].splitlines()[0])
        stored = []
        for excerpt in (quoted, {"source": SRC1, "lines": 4}, {"lines": "4-4"}):
            doc, path = self.proposal(facts=[self.fact(excerpt)])
            code, out = self.call("propose", test_data_layer.RID, path)
            self.assertEqual(code, 0, out)
            self.assertIn("- verdict=would-apply", out)
            stored.append(yamlio.load(os.path.join(self.dir, self.value(out, "DETAILS")))["facts"])
        self.assertEqual(stored[1], stored[0])   # the same fact as the long form
        self.assertEqual(stored[2], stored[0])
        code, out = self.call("apply", doc["id"])
        self.assertEqual(code, 0, out)
        fact = next(f for p in self.index("persons")["persons"] for f in p["facts"]
                    if f["id"] == "victor-hugo-1802.residence")
        self.assertEqual(fact["excerpt"], quoted)
        for excerpt, why in (({"lines": "6-9"}, "lines 6-9 are not in the transcription, which has 7"),
                             ({"source": "src-01J9ZK3M4X0000000000000002", "lines": "1"}, "cites src-01J9ZK3M4X")):
            _doc, path = self.proposal(facts=[self.fact(excerpt)])
            code, out = self.call("propose", test_data_layer.RID, path)
            self.assertEqual(code, 2, out)
            self.assertIn("REASON=excerpt", out)
            self.assertIn(why, out)

    def test_a_transcription_not_in_the_engines_form(self):
        # I1, 11 Oct. 2026: a transcription written freehand gave "which has 0"; propose now says why
        folder = os.path.join(self.family, "evidence", "transcriptions")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{SRC1}.md"), "w", encoding="utf-8") as fh:
            fh.write("# Transcription\n\nDu huit ventôse an dix de la République\n")
        _doc, path = self.proposal(facts=[self.fact({"lines": "1-2"})])
        code, out = self.call("propose", test_data_layer.RID, path)
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=excerpt", out)
        self.assertIn(f"the transcription of {SRC1} has no numbered line (no section Diplomatic transcription)", out)
        self.assertIn(f"`transcribe check families/hugo/evidence/transcriptions/{SRC1}.md` lists what to fix", out)

    def test_a_second_reading_does_not_replace_the_first(self):
        # T265: Codex proposed the source again with its blind second reading; the facts read the first
        self.transcription()
        lines = X.transcription_lines(self.dir, "hugo", {"id": SRC1})
        (code, out), _doc = self.propose_and_apply(facts=[self.fact(X.from_lines(lines, 4, 4))])
        self.assertEqual(code, 0, out)
        folder = os.path.join(self.family, "evidence", "transcriptions")
        with open(os.path.join(folder, f"{SRC1}.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(folder, f"{SRC1}.2.md"), "w", encoding="utf-8") as fh:
            fh.write(text.replace("vingt-huit", "vingt-neuf"))
        source = next(s for s in self.index("sources")["sources"] if s["id"] == SRC1)
        second = dict(source, transcription=f"evidence/transcriptions/{SRC1}.2.md")
        self.assertRejected(f"P-2: source {SRC1}: its transcription would become evidence/transcriptions/"
                            f"{SRC1}.2.md, where the excerpt of fact victor-hugo-1802.residence no longer reads "
                            "(lines 4-4 do not read so", sources=[second])
        with open(os.path.join(folder, f"{SRC1}.2.md"), "w", encoding="utf-8") as fh:
            fh.write(text)   # a reading where every excerpt still reads may take its place
        (code, out), _doc = self.propose_and_apply(sources=[second])
        self.assertEqual(code, 0, out)

    def test_an_image_kept_outside_the_project(self):
        # T264: the reader saved the act in a temporary folder, and the source named it with a comment
        outside = os.path.join(self.tmp.name, "hg1")
        os.makedirs(outside)
        act = os.path.join(outside, "act.jpg").replace(os.sep, "/")
        with open(act, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xd9")
        source = next(s for s in self.index("sources")["sources"] if s["id"] == SRC1)
        self.assertRejected(f"P-2: source {SRC1}: its image holds more than a path",
                            sources=[dict(source, image=f"{act} (355x232 px, low resolution)")])
        self.assertRejected(f"P-2: source {SRC1}: its image {act}2 is outside the project and is not found",
                            sources=[dict(source, image=act + "2")])
        (code, out), _doc = self.propose_and_apply(sources=[dict(source, image=act, images=[act])])
        self.assertEqual(code, 0, out)
        kept = next(s for s in self.index("sources")["sources"] if s["id"] == SRC1)
        self.assertEqual((kept["image"], kept["images"]), (f"evidence/images/{SRC1}-act.jpg",
                                                           [f"evidence/images/{SRC1}-act.jpg"]))
        with open(os.path.join(self.family, "evidence", "images", f"{SRC1}-act.jpg"), "rb") as fh:
            self.assertEqual(fh.read(), b"\xff\xd8\xff\xd9")

    def test_without_its_transcription(self):
        quoted = X.from_lines(["une ligne"], 1, 1)
        self.assertRejected("excerpt of fact victor-hugo-1802.residence: no transcription",
                            facts=[self.fact(quoted)])

    def page(self, url, text):
        from probandia.reading.cache import Cache, make_key

        Cache(self.dir).put("http", make_key("http", url), {"text": text, "final_url": url}, "ok", 86400)

    def test_a_page_kept_where_its_rights_allow(self):
        from probandia.research import Research

        free, url = "src-01J9ZK3M4X0000000000000002", "https://example.org/oa/1"
        text = "Index des naissances.\n\nHugo Victor, Besançon, 26 février 1802."
        self.archive("free")   # the site is an archive of the catalogue, its images free
        self.page(url, text)
        at = X.offset_of(text, "Hugo Victor, Besançon")
        quoted = X.from_page(text, at, len("Hugo Victor, Besançon"), url=url)
        (code, out), _doc = self.propose_and_apply(facts=[self.fact(quoted, free, status="index")])
        self.assertEqual(code, 0, out)
        kept = os.path.join(self.family, "evidence", "pages", f"{free}.md")
        self.assertEqual(X.read_page(kept), text)
        source = next(s for s in self.index("sources")["sources"] if s["id"] == free)
        self.assertEqual(source["sha256"], X.digest(text))
        # a source whose rights are restricted keeps its page in the research's work folder only
        closed = {"id": "src-01J9ZK3M4X0000000000000009", "repository": "Archives privées", "rights": "restricted",
                  "url": "https://example.org/private/9"}
        self.page(closed["url"], text)
        quoted = dict(quoted, url=closed["url"])
        (code, out), _doc = self.propose_and_apply(
            sources=[closed], facts=[self.fact(quoted, closed["id"], fid="victor-hugo-1802.residence.2",
                                               status="index")])
        self.assertEqual(code, 0, out)
        work = os.path.join(Research(self.dir, "hugo", test_data_layer.RID).work, "pages", f"{closed['id']}.md")
        self.assertTrue(os.path.isfile(work))
        self.assertFalse(os.path.exists(os.path.join(self.family, "evidence", "pages", f"{closed['id']}.md")))

    def archive(self, rights):
        """The site example.org as an archive of the project's catalogue."""
        os.makedirs(os.path.join(self.dir, "library"), exist_ok=True)
        yamlio.dump(os.path.join(self.dir, "library", "archives.yaml"), {"schema": 1, "archives": [
            {"id": "example", "name": "Example archive", "nature": "image", "image_rights": rights,
             "coverage": {"types": ["birth"], "places": ["LU"]},
             "access": {"mode": "html", "hosts": ["example.org"]}}]})

    def test_a_site_the_catalogue_does_not_know_stays_in_work(self):
        """TRUST-D2, made precise: rights: free is what an agent wrote; an unknown site is not copied into
        the family's evidence."""
        from probandia.research import Research

        free, url = "src-01J9ZK3M4X0000000000000002", "https://example.org/oa/1"
        text = "Index des naissances. Hugo Victor, Besançon, 26 février 1802."
        self.page(url, text)
        quoted = X.from_page(text, X.offset_of(text, "Hugo Victor"), len("Hugo Victor"), url=url)
        (code, out), _doc = self.propose_and_apply(facts=[self.fact(quoted, free, status="index")])
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.family, "evidence", "pages", f"{free}.md")))
        work = Research(self.dir, "hugo", test_data_layer.RID).work
        self.assertTrue(os.path.isfile(os.path.join(work, "pages", f"{free}.md")))
        self.assertFalse(X.may_keep({"rights": "free", "url": url}, {}))
        self.assertFalse(X.may_keep({"rights": "free", "url": url},
                                    {"x": {"image_rights": "restricted", "access": {"hosts": ["example.org"]}}}))
        self.assertTrue(X.may_keep({"rights": "free", "url": url},
                                   {"x": {"image_rights": "free", "access": {"hosts": ["example.org"]}}}))

    def test_a_page_that_does_not_say_it(self):
        url = "https://example.org/oa/1"
        self.page(url, "Index des naissances. Hugo Victor, Besançon, 26 février 1802.")
        quoted = X.from_page("Hugo Victor, Pontarlier", 0, 23, url=url)
        self.assertRejected("excerpt of fact victor-hugo-1802.residence: the page does not contain it",
                            facts=[self.fact(quoted, "src-01J9ZK3M4X0000000000000002", status="index")])


class Rule(unittest.TestCase):
    """TRUST2-T1: rule V-19, on the sample project of the GPS."""

    setUp = sample.SampleGPS.setUp
    call = sample.Sample.call

    def v19(self, standard=None):
        if standard:
            self.call("config", "set", "proof.standard", standard)
        code, out = self.call("verify", sample.GPS_RID, "--rule", "V-19")
        return next(line[len("- V-19="):] for line in out.splitlines() if line.startswith("- V-19="))

    def family(self, *parts):
        return os.path.join(self.dir, "families", "marchand", *parts)

    def test_found(self):
        self.assertEqual(self.v19("strict"), "PASS")

    def test_a_transcription_changed(self):
        path = self.family("evidence", "transcriptions", "src-01JA0000000000000000000007.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text.replace("soixante-dix", "soixante-et-onze"))
        self.assertTrue(self.v19().startswith("FAIL henri-marchand-1870.birth: lines 1-4 do not read so"))

    def test_a_page_not_kept_here(self):
        os.remove(self.family("evidence", "pages", "src-01JA0000000000000000000008.md"))
        self.assertEqual(self.v19(), "WARN henri-marchand-1870.birth.2: the page is not kept on this computer")

    def test_a_concluding_record_without_its_excerpt(self):
        path = self.family("index", "persons.yaml")
        doc = yamlio.load(path)
        for p in doc["persons"]:
            for f in p["facts"]:
                if f["id"] == "henri-marchand-1870.birth":
                    del f["excerpt"]
        yamlio.dump(path, doc)
        self.assertEqual(self.v19("off"), "PASS")
        self.assertEqual(self.v19("warn"), "WARN henri-marchand-1870.birth: no excerpt")
        self.assertEqual(self.v19("strict"), "FAIL henri-marchand-1870.birth: no excerpt")


class InTheNote(unittest.TestCase):
    """TRUST2-T2: the note of a fact quotes its excerpt; a person presumed living stays masked."""

    def context(self, living=()):
        from probandia.i18n import Translator
        from probandia.report.content import Context

        persons = [{"id": "lea-roy-1990", "names": {"given": "Léa", "surname": "ROY"}, "facts": []}]
        return Context([], persons, [], set(living), "fr", Translator("fr"), [], "journal")

    def test_quoted_with_where_it_is(self):
        ctx = self.context()
        self.assertEqual(ctx.excerpt(X.from_lines(LINES, 3, 3)),
                         "« est comparu Pierre MARCHAND, cultivateur, » (ligne 3 de la transcription)")
        self.assertEqual(ctx.excerpt(X.from_lines(LINES, 1, 2)).split("(")[-1], "lignes 1 à 2 de la transcription)")
        page = X.from_page("Né le *12* mars", 0, 15, captured="2026-09-04")
        self.assertEqual(ctx.excerpt(page), r"« Né le \*12\* mars » (page lue le 4 septembre 2026)")

    def test_a_living_person_is_masked(self):
        ctx = self.context(living={"lea-roy-1990"})
        quoted = X.from_lines(["témoin : Léa Roy, et ROY Léa sa cousine"], 1, 1)
        self.assertEqual(ctx.excerpt(quoted),
                         "« témoin : Personne vivante, et Personne vivante sa cousine » (ligne 1 de la transcription)")


class Gedcom(unittest.TestCase):
    """TRUST2-T4: the excerpt goes into the citation's DATA.TEXT, in GEDCOM 7 and 5.5.1."""

    setUp = sample.SampleGPS.setUp
    call = sample.Sample.call

    def test_text_of_the_citation(self):
        import zipfile

        from probandia import gedcom

        code, out = self.call("export", "gedcom7", "--family", "marchand")
        self.assertEqual(code, 0, out)
        with zipfile.ZipFile(os.path.join(self.dir, out.split("FILE=")[1].split()[0])) as z:
            text = z.read("gedcom.ged").decode("utf-8-sig")
        self.assertIn("4 TEXT MARCHAND Henri, 14 mars 1871", text)
        self.assertIn("4 TEXT N° 31 Marchand Henri L'an mil huit cent soixante-dix", text)
        roots = gedcom.parse(text)
        self.assertTrue(roots)
        code, out = self.call("export", "gedcom551", "--family", "marchand")
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.dir, out.split("FILE=")[1].split()[0]), encoding="utf-8-sig") as fh:
            old = fh.read()
        self.assertIn("4 TEXT MARCHAND Henri, 14 mars 1871", old)
        self.assertIn("5 CONC ", old)   # the act's passage, longer than a line of 5.5.1
