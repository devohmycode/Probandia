import base64
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.parse

from probandia import archives, cli
from probandia.archives.finder import find, load_catalogue
from probandia.reading.cache import Cache
from probandia.reading.ladder import Reader, forbidden_hosts
from probandia.util import yamlio
from probandia.util.http import Client
from probandia.util.schema import validate_document
from tests import ROOT
from tests.integration import test_sample_project as sample

FIX = os.path.join(ROOT, "tests", "fixtures")
REC = os.path.join(FIX, "http", "archives")


def _normal(url):
    """A URL without its key, and with sorted parameters."""
    p = urllib.parse.urlsplit(url)
    q = sorted((k, "KEY" if k in ("wskey", "username", "api_key") else v)
               for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True))
    q = [(k, "USER" if k == "username" else v) for k, v in q]
    return (p.scheme, p.netloc, p.path, urllib.parse.urlencode(q))


class Replay:
    """Answers each request with the recorded answer of the same URL."""

    def __init__(self, archive, overrides=None):
        self.answers = {}
        folder = os.path.join(REC, archive)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                fx = json.load(fh)
            if name[0].isdigit():
                self.answers[_normal(fx["request"]["url"])] = fx
        self.overrides = overrides or {}
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        if url.endswith("/robots.txt"):
            return 200, {}, b"", url
        self.calls.append(url)
        fx = self.overrides.get("*") or self.answers.get(_normal(url))
        if fx is None:
            return 404, {}, b"no recorded answer for " + url.encode(), url
        if "body_base64" in fx:
            raw = base64.b64decode(fx["body_base64"])
        else:
            b = fx["body"]
            raw = b.encode("utf-8") if isinstance(b, str) else json.dumps(b).encode("utf-8")
        return fx["status"], fx.get("headers", {}), raw, url


def recorded(archive, name):
    with open(os.path.join(REC, archive, name), encoding="utf-8") as fh:
        return json.load(fh)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = os.path.join(self.tmp.name, "data")
        shutil.copytree(os.path.join(FIX, "cog"), os.path.join(data, "insee"))
        shutil.copytree(os.path.join(FIX, "archives-data", "bnl"), os.path.join(data, "bnl"))
        self.data = data

    def context(self, archive, overrides=None, environ=None, sleep=None, clock=None):
        self.replay = Replay(archive, overrides)
        kw = {}
        if clock:
            kw["clock"] = clock
        client = Client(os.path.join(self.tmp.name, "state"), None, None, self.replay,
                        sleep=sleep or (lambda s: None), **kw)
        return archives.Context(client, None, environ or {"GEONAMES_USERNAME": "USER"}, self.data,
                                work=os.path.join(self.tmp.name, "work"))


class Witnesses(Base):
    def test_every_built_in_witness_passes_on_its_fixtures(self):
        for archive_id in archives.BUILT_IN:
            with self.subTest(archive=archive_id):
                module = archives.load(archive_id)
                w = module.WITNESS
                result = archives.run(module, w["operation"], dict(w["args"]), self.context(archive_id))
                self.assertTrue(archives.witness_passed(w, result), (result.status, result.failure, result.n))

    def test_connectors_declare_their_interface(self):
        for archive_id in archives.BUILT_IN:
            module = archives.load(archive_id)
            self.assertEqual(module.ARCHIVE, archive_id)
            self.assertIn(module.WITNESS["operation"], module.OPERATIONS)
            for name, op in module.OPERATIONS.items():
                self.assertTrue(op.doc, f"{archive_id}.{name}")
                for p in op.required:
                    self.assertIn(p, op.params)


class Manche(Base):
    """token-economy A4: a view of a register of the Manche in two engine calls, from recorded answers."""

    def test_the_register_then_its_view(self):
        ctx = self.context("ad50")
        ad50 = archives.load("ad50")
        found = archives.run(ad50, "registers", {"commune": "Octeville", "type": "death", "from": 1876,
                                                 "to": 1876}, ctx)
        # the filter "Commune ou paroisse" also matches Octeville-l'Avenel
        self.assertEqual([(r["detail"], r["cote"], r["from"], r["to"]) for r in found.rows],
                         [(607643, "5 Mi 716", 1873, 1877), (617779, "5 Mi 910", 1873, 1882)])
        self.assertIn("Décès", found.rows[0]["types"])
        self.assertNotIn("viewer", found.rows[0])   # J1: kept aside, not copied back by the agent
        view = archives.run(ad50, "view", {"detail": 607643, "view": 89}, ctx)
        self.assertEqual((view.rows[0]["view"], view.rows[0]["views"]), (89, 323))
        self.assertTrue(view.rows[0]["url"].endswith("/_recherche-images/download/607643/image/1918347/88"))
        with open(view.path, "rb") as fh:
            self.assertEqual(fh.read(2), b"\xff\xd8")
        self.assertEqual(len(self.replay.calls), 3)   # the search, the views, the view
        os.remove(os.path.join(self.tmp.name, "work", "ad50-viewers.json"))
        again = archives.run(ad50, "view", {"detail": 607643, "view": 89}, ctx)   # not kept: its page
        self.assertEqual(again.rows[0]["views"], 323)
        self.assertEqual(len(self.replay.calls), 6)   # the register's page, the views, the view
        archives.run(ad50, "view", {"detail": 607643, "view": 90}, ctx)
        self.assertEqual(len(self.replay.calls), 8)   # kept from the page: the views, the view
        tables = archives.run(ad50, "registers", {"commune": "Octeville", "type": "decennial_tables",
                                                  "from": 1876, "to": 1876}, ctx)
        self.assertEqual([r["detail"] for r in tables.rows], [607655, 617763])

    def test_without_a_view_the_number_of_views(self):
        """token-economy J8: readers fetched view 1, 3,600 tokens once read, only to learn how many there are."""
        ctx = self.context("ad50")
        ad50 = archives.load("ad50")
        archives.run(ad50, "registers", {"commune": "Octeville", "type": "death", "from": 1876, "to": 1876}, ctx)
        views = archives.run(ad50, "view", {"detail": 607643}, ctx)
        self.assertEqual((views.status, views.rows, views.path), ("ok", [{"detail": 607643, "views": 323}], None))
        self.assertEqual(len(self.replay.calls), 2)   # the search, the views: no image

    def test_a_small_view_is_kept_as_such_in_a_project(self):
        """token-economy J10: a view asked under 2,000 px finds the act; the whole one saved over it is read."""
        from probandia import images

        ctx = self.context("ad50")
        ad50 = archives.load("ad50")
        archives.run(ad50, "registers", {"commune": "Octeville", "type": "death", "from": 1876, "to": 1876}, ctx)
        ctx.project = os.path.join(self.tmp.name, "project")
        small = archives.run(ad50, "view", {"detail": 607643, "view": 89, "size": 800}, ctx)
        self.assertTrue(small.rows[0]["url"].endswith("/show/607643/image/1918347/88?size=!800,800"))
        self.assertTrue(images.is_small(ctx.project, small.path))
        whole = archives.run(ad50, "view", {"detail": 607643, "view": 89}, ctx)
        self.assertEqual(whole.path, small.path)   # one name for both
        self.assertFalse(images.is_small(ctx.project, whole.path))

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_the_views_on_one_sheet_in_one_call(self):
        """T73: a reader paid a Bash and a Read for each view; one sheet shows views from..to, small (J10).
        T73b: the small views are not saved, and a view saved whole before stays whole."""
        from probandia import images
        from probandia.guard import WHOLE_VIEW

        ctx = self.context("ad50")
        ad50 = archives.load("ad50")
        ctx.project = os.path.join(self.tmp.name, "project")
        archives.run(ad50, "registers", {"commune": "Octeville", "type": "death", "from": 1876, "to": 1876}, ctx)
        whole = archives.run(ad50, "view", {"detail": 607643, "view": 89}, ctx)
        with open(whole.path, "rb") as fh:
            before = fh.read()
        sheet = archives.run(ad50, "sheet", {"detail": 607643, "from": 88, "to": 90}, ctx)
        self.assertEqual((sheet.status, sheet.rows), ("ok", [{"detail": 607643, "from": 88, "to": 90, "views": 323}]))
        self.assertEqual([u.rsplit("/", 1)[1] for u in self.replay.calls[3:]],   # the views, then each one small
                         ["1918347", "87?size=!660,660", "88?size=!660,660", "89?size=!660,660"])
        # three top bands, one under the other: 291 tokens; 535x600 px and 428 at 800 px (T73)
        self.assertEqual(images.size_of(sheet.path), (441, 495))
        self.assertIsNone(WHOLE_VIEW.search(sheet.path.replace(os.sep, "/")))   # G-14: not a whole view
        self.assertTrue(images.is_small(ctx.project, sheet.path))
        folder = os.path.dirname(sheet.path)
        self.assertEqual(sorted(os.listdir(folder)), ["ad50-607643-0089.jpg", "ad50-607643-sheet-88-90.jpg"])
        with open(whole.path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(images.is_small(ctx.project, whole.path))
        for bad in ({"from": 0, "to": 3}, {"from": 5, "to": 4}, {"from": 1, "to": 21}, {"from": 320, "to": 324}):
            with self.subTest(bad=bad):
                self.assertEqual(archives.run(ad50, "sheet", dict(bad, detail=607643), ctx).status, "failed")

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_a_sheet_costs_a_third_less_than_at_t73(self):
        """T73b: at equal views, a sheet holds at least 30 % fewer pixels (TOKENS_EST) than at T73 (views at
        800 px, 1,150,000 px at most): ten double pages 1,419 tokens before, 968 now."""
        from PIL import Image

        from probandia import images
        from probandia.archives.ad50 import SHEET_PX

        def view(w, h, px):   # a plain page of the size the site answers to ?size=!px,px
            k, buf = px / max(w, h), io.BytesIO()
            Image.new("RGB", (round(w * k), round(h * k)), (240, 229, 209)).save(buf, "JPEG")
            return buf

        out = os.path.join(self.tmp.name, "sheet.jpg")
        for w, h in ((2800, 1866), (2800, 2203), (1768, 2643)):   # two double pages, a single page
            for n in (1, 3, 10, 20):
                before = images.sheet([view(w, h, 800) for _ in range(n)], out, max_px=1_150_000)["TOKENS_EST"]
                after = images.sheet([view(w, h, SHEET_PX) for _ in range(n)], out)["TOKENS_EST"]
                self.assertLessEqual(after, 0.7 * before, (w, h, n, before, after))
        self.assertEqual((before, after), (1537, 997))   # twenty single pages
        self.assertEqual(images.sheet([view(2800, 1866, SHEET_PX) for _ in range(10)], out)["PX"], "660x1100")

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_a_sheet_then_the_view_small_then_the_act_cut_at_full_size(self):
        """T73c: readers fetched whole views (refused by G-14) and cut half pages, 1,500 to 2,250 tokens each, to
        look for the act. The view asked small places it; the same call with the region seen on it cuts the act
        alone from the whole view, at full size, and the whole view never reaches the disk."""
        from types import SimpleNamespace

        from PIL import Image

        from probandia import guard, images
        from probandia.errors import ProbandiaError

        ctx = self.context("ad50")
        ad50 = archives.load("ad50")
        ctx.project = os.path.join(self.tmp.name, "project")

        def read(path):   # what G-14 answers a reader reading the file
            call = SimpleNamespace(agent="reader", is_read=lambda: True, paths=lambda: [path], cwd=ctx.project)
            return guard.g14(call, None)

        archives.run(ad50, "registers", {"commune": "Octeville", "type": "death", "from": 1876, "to": 1876}, ctx)
        sheet = archives.run(ad50, "sheet", {"detail": 607643, "from": 88, "to": 90}, ctx)
        small = archives.run(ad50, "view", {"detail": 607643, "view": 90, "size": 900}, ctx)
        self.assertEqual(images.size_of(small.path), (900, 600))   # 720 tokens
        self.assertTrue(images.is_small(ctx.project, small.path))   # J10: it places the act, never transcribed
        self.assertIsNone(read(small.path))
        args = {"detail": 607643, "view": 90, "size": 900, "region": "450,200,450,300"}   # as seen on the small view
        act = archives.run(ad50, "view", args, ctx)
        self.assertTrue(self.replay.calls[-1].endswith("/_recherche-images/download/607643/image/1918347/89"))
        self.assertEqual(os.path.basename(act.path), "ad50-607643-0090-450_200_450_300.jpg")
        self.assertEqual(images.size_of(act.path), (1400, 934))   # the whole view's pixels (x 3.11), 1,743 tokens
        self.assertEqual(act.rows[0]["region"], "1400,622,1400,934")   # on the whole view: the reader's region=
        with Image.open(act.path) as im:   # the act's dark block, the page around it
            self.assertLess(im.convert("L").getpixel((700, 467)), 80)
            self.assertGreater(im.convert("L").getpixel((20, 10)), 200)
        self.assertFalse(images.is_small(ctx.project, act.path))   # transcribe new takes it
        self.assertIsNone(read(act.path))
        with self.assertRaises(ProbandiaError) as err:   # a whole page is not an act
            archives.run(ad50, "view", dict(args, region="450,0,450,600"), ctx)
        self.assertEqual(err.exception.values["REASON"], "region-large")
        folder = os.path.dirname(act.path)   # no whole view, no empty file
        self.assertEqual(sorted(os.listdir(folder)), [os.path.basename(act.path), "ad50-607643-0090.jpg",
                                                      os.path.basename(sheet.path)])
        self.assertEqual(images.size_of(small.path), (900, 600))   # the small view is not saved over
        whole = os.path.join(folder, "ad50-607643-0091.jpg")   # a whole view saved before T73c is refused
        with open(whole, "wb") as fh:
            fh.write(base64.b64decode(recorded("ad50", "11.json")["body_base64"]))
        self.assertTrue(read(whole).startswith("ad50-607643-0091.jpg is a whole view, 6966 tokens"), read(whole))
        self.assertIn('"region"', read(whole))

    def test_the_transcribe_skill_says_sheet_then_view_small_then_the_act_cut(self):   # T73, T73b, T73c
        with open(os.path.join(ROOT, "skills", "transcribe", "SKILL.md"), encoding="utf-8") as fh:
            text = " ".join(fh.read().split())
        for words in ("alone in a message", "Never fetch or read a whole view", "ad50.sheet",
                      "never half pages cut to search", '"size": 900', '"region": "x,y,w,h"',
                      "cut from the whole view at full size"):
            self.assertIn(words, text)


class ScriptRedirect(unittest.TestCase):
    """token-economy A1: the cookie of a plain redirect page is replayed under the engine's identity."""

    def test_the_cookie_is_kept_and_the_page_asked_again(self):
        seen = []

        def transport(method, url, headers, body, timeout):
            seen.append((url, headers.get("Cookie"), headers.get("User-Agent")))
            if "Cookie" not in headers:
                return 200, {"Set-Cookie": "bot=abc; path=/"}, (
                    b"<html><script>window.location.href='/redirect_T" + url.split("example.org", 1)[1].encode()
                    + b"';</script></html>"), url
            if url.endswith("/robots.txt"):
                return 200, {}, b"User-agent: *\nDisallow: /private/\n", url
            return 200, {"X-Probandia-Cookie": "bot=renewed"}, b"<html>" + b"x" * 3000 + b"</html>", url

        with tempfile.TemporaryDirectory() as tmp:
            client = Client(os.path.join(tmp, "state"), None, None, transport, sleep=lambda s: None)
            page = client.get("https://example.org/page")
            self.assertEqual((page.status, len(page.body)), (200, 3013))
            self.assertEqual(client.cookies["example.org"], {"bot": "renewed"})   # renewed on the redirect
            self.assertTrue(all(ua.startswith("Probandia/") for _u, _c, ua in seen))
            self.assertIn(("https://example.org/redirect_T/robots.txt", "bot=abc"), [(u, c) for u, c, _ua in seen])
            self.assertFalse(client.allowed_by_robots("https://example.org/private/x"))   # the real robots.txt

    def test_no_cookie_no_replay(self):
        def transport(method, url, headers, body, timeout):
            return 200, {}, b"<script>window.location.href='/elsewhere';</script>", url

        with tempfile.TemporaryDirectory() as tmp:
            client = Client(os.path.join(tmp, "state"), None, None, transport, sleep=lambda s: None)
            self.assertIn(b"elsewhere", client.get("https://example.org/a", api=True).body)
            self.assertEqual(client.cookies, {})


class Operations(Base):
    ARK = "ark:/12148/bpt6k5356122w"

    def test_gallica(self):
        ctx = self.context("gallica")
        g = archives.load("gallica")
        content = archives.run(g, "content", {"ark": self.ARK, "query": "Besançon"}, ctx)
        self.assertEqual((content.n, content.rows[0]["page"]), (1, 2))
        self.assertIn("Besançon", content.rows[0]["snippet"])
        text = archives.run(g, "text", {"ark": self.ARK, "page": 2}, ctx)
        # the recorded raw text page is an ALTCHA challenge: the same OCR comes from the ALTO
        self.assertIn("not consulted (challenge)", text.rows[0]["note"])
        self.assertGreater(len(text.text), 100)
        alto = archives.run(g, "alto", {"ark": self.ARK, "page": 2}, ctx)
        self.assertGreater(alto.n, 0)
        image = archives.run(g, "image", {"ark": self.ARK, "page": 2, "region": "0,0,400,300",
                                          "width": 200}, ctx)
        with open(image.path, "rb") as fh:
            self.assertEqual(fh.read(2), b"\xff\xd8")  # a JPEG
        search = archives.run(g, "search", {"query": "Hugo", "type": "fascicule"}, ctx)
        self.assertTrue(search.rows[0]["ark"].startswith("ark:/12148/"))

    def test_openarchives_record_and_wikitree_ancestors(self):
        oa = archives.run(archives.load("openarchives"), "search", {"name": "Hugo"},
                          self.context("openarchives"))
        first = oa.rows[0]
        rec = archives.run(archives.load("openarchives"), "record",
                           {"archive": first["archive"], "identifier": first["identifier"]},
                           self.context("openarchives"))
        self.assertEqual(rec.status, "ok")
        anc = archives.run(archives.load("wikitree"), "ancestors", {"key": "Lincoln-7", "depth": 1},
                           self.context("wikitree"))
        self.assertEqual(sorted(r["id"] for r in anc.rows), ["Hawke-3", "Lincoln-6"])

    def test_a_challenge_is_not_a_zero(self):
        gov = archives.run(archives.load("gov"), "search", {"name": "Octeville"},
                           self.context("gov", {"*": recorded("gov", "challenge.json")}))
        self.assertEqual(gov.status, "failed")
        self.assertIn("not consulted (challenge)", gov.failure)
        loc = archives.run(archives.load("loc"), "search", {"query": "Victor Hugo"},
                           self.context("loc", {"*": recorded("loc", "challenge.json")}))
        self.assertEqual(loc.status, "failed")
        gn = archives.run(archives.load("geonames"), "search", {"name": "Octeville"},
                          self.context("geonames", {"*": recorded("geonames", "limit.json")}))
        self.assertIn("daily limit", gn.failure)

    def test_bad_parameters(self):
        from probandia.errors import UsageError
        with self.assertRaises(UsageError):
            archives.run(archives.load("gallica"), "text", {"ark": self.ARK}, self.context("gallica"))
        with self.assertRaises(UsageError):
            archives.run(archives.load("gallica"), "search", {"query": "x", "colour": 1},
                         self.context("gallica"))

    def test_gallica_rate_under_load(self):
        now = [1000.0]
        waits = []

        def sleep(s):
            waits.append(s)
            now[0] += s
        ctx = self.context("gallica", sleep=sleep, clock=lambda: now[0])
        g = archives.load("gallica")
        for _ in range(10):
            archives.run(g, "content", {"ark": self.ARK, "query": "Besançon"}, ctx)
        self.assertAlmostEqual(sum(waits), 9 * 12, delta=0.5)  # 5 per minute: one every 12 s


class Catalogue(unittest.TestCase):
    def test_the_departmental_archives_of_france(self):
        # token-economy A2: the 101 departments, each with its name, hosts and platform
        from probandia.archives.coverage import DEPARTMENTS, places_in

        doc = yamlio.load(os.path.join(ROOT, "catalogues", "archives-fr-ad.yaml"))
        validate_document("archives", doc, "archives-fr-ad.yaml")
        ad = {e["id"]: e for e in doc["archives"]}
        self.assertEqual(sorted(ad), sorted(f"ad{code.lower()}" for code in DEPARTMENTS))
        self.assertEqual(len(ad), 101)
        for e in ad.values():
            self.assertTrue(e["name"] and e["access"]["hosts"] and e["platform"], e["id"])
        self.assertEqual((ad["ad50"]["platform"], ad["ad50"]["access"]["hosts"]), ("arkotheque", ["www.archives-manche.fr"]))
        cat = load_catalogue()
        self.assertTrue(all(f"ad{code.lower()}" in cat for code in DEPARTMENTS))
        best, browser = find("acte de décès, Octeville (Manche), 1876", place_only=True)
        self.assertEqual(best[0][1], "ad50")   # A4: its connector comes first
        self.assertNotIn("openarchives", [b[1] for b in best[:1]])
        # a department's name inside a longer one is not that department
        self.assertEqual(places_in("Val-d'Oise"), ["FR-95", "FR"])
        self.assertEqual(places_in("Agen, Lot-et-Garonne"), ["FR-47", "FR"])
        self.assertEqual(places_in("Loire et Haute-Loire"), ["FR-43", "FR", "FR-42"])
        self.assertEqual(places_in("Saint-Denis, La Réunion"), ["FR-974", "FR"])

    def test_the_package_catalogues_are_parsed_once_and_each_caller_gets_its_copy(self):
        # T27: about 150 ms a parse, and the commands of a pass ask for it again and again
        from unittest import mock
        from probandia.archives import finder

        with mock.patch.dict(finder._PARSED, clear=True), \
                mock.patch.object(finder.yamlio, "load", wraps=finder.yamlio.load) as load:
            first = load_catalogue()
            first["socface"]["coverage"]["absent"] = ["FR-50"]
            second = load_catalogue()
        self.assertEqual(load.call_count, len(finder.CATALOGUES))
        self.assertNotEqual(second["socface"]["coverage"].get("absent"), ["FR-50"])

    def test_validates(self):
        doc = yamlio.load(os.path.join(ROOT, "catalogues", "archives.yaml"))
        validate_document("archives", doc, "archives.yaml")
        cat = load_catalogue()
        for archive_id in archives.BUILT_IN:
            self.assertEqual(cat[archive_id]["access"]["connector"], archive_id)
            self.assertIn("witness", cat[archive_id])

    def test_one_witness_per_archive(self):
        """TRUST4-T1: the catalogue's witness is the one that runs; a connector's own WITNESS says the same."""
        cat = load_catalogue()
        for archive_id, module in archives.connectors().items():
            with self.subTest(archive=archive_id):
                self.assertEqual(getattr(module, "WITNESS", None), cat[archive_id]["witness"],
                                 "the witness of the module and of catalogues/archives.yaml differ")
                self.assertIs(archives.witness_of(module, catalogue=cat), cat[archive_id]["witness"])

        class Learned:
            ARCHIVE = "learned-only"
            WITNESS = {"operation": "search", "args": {}, "expect": {}}

        self.assertIs(archives.witness_of(Learned, catalogue=cat), Learned.WITNESS)

    def test_forbidden_hosts_block_the_reader_apis(self):
        hosts = forbidden_hosts(None, ROOT)
        self.assertIn("francearchives.gouv.fr", hosts)
        self.assertIn("rechercher.patrimoines-archives.morbihan.fr", hosts)
        url = "https://rechercher.patrimoines-archives.morbihan.fr/ark:/42067/x"
        calls = []

        def transport(method, u, headers, body, timeout):
            calls.append(u)
            with open(os.path.join(FIX, "pages", "anubis-challenge.html"), "rb") as fh:
                return 200, {}, fh.read(), u
        tmp = tempfile.mkdtemp()
        reader = Reader(Client(tmp, None, None, transport, sleep=lambda s: None), Cache(tmp), None, {},
                        forbidden=hosts)
        result = reader.read(url, max_step=4)
        self.assertEqual(result.status, "challenge")
        self.assertIn(("reader", "forbidden-host"), result.tried)
        self.assertFalse(any("r.jina.ai" in c or "firecrawl" in c for c in calls))


class Find(unittest.TestCase):
    def test_census_of_1872_in_morbihan(self):
        best, browser = find("census of 1872 in Morbihan")
        self.assertEqual(len(best), 5)
        top = {a for _s, a, o, _op, _e in best}
        self.assertNotIn("openarchives", top)  # C5: no French census there
        self.assertNotIn("matchid", top)  # deaths since 1970 only
        self.assertEqual({e["id"] for e in browser} & {"ad56", "socface"}, {"ad56", "socface"})
        self.assertIn("openarchives.search", {f"{a}.{o}" for _s, a, o, _op, _e in find("census of 1872 in Belgique")[0]})

    def test_the_case_finds_the_manche_first(self):
        # C5, a bench case: Open Archives covered "FR" (its only French source is INSEE since
        # 1970), and the "état" of "état civil" named AGATHA, the Archives de l'État en Belgique
        for need in ("acte de décès, Octeville (Manche), 1876",
                     "acte de décès, état civil, Octeville (Manche), 1876"):
            with self.subTest(need=need):
                best, browser = find(need, limit=3, place_only=True)
                self.assertEqual([a for _s, a, _o, _op, _e in best[:2]], ["ad50", "ad50"])
                self.assertFalse({"openarchives", "arch_be"} & {a for _s, a, _o, _op, _e in best})
                self.assertNotIn("arch_be", [e["id"] for e in browser[:3]])
                # death 3, the department itself 4 (the whole country: 2), its years 2, "Manche" in its doc 2
                self.assertEqual(next(s for s, a, o, _op, _e in best if (a, o) == ("ad50", "view")), 11)
        self.assertEqual(find("archives de l'état civil", limit=None, place_only=True)[1], [])

    def test_command(self):
        out = io.StringIO()
        project = tempfile.mkdtemp()
        with open(os.path.join(project, "probandia.toml"), "w") as fh:
            fh.write("schema = 1\n")
        cli.main(["archive", "find", "census of 1872 in Belgique"], stdout=out,
                 environ={"PROBANDIA_CONFIG_DIR": project}, cwd=project)
        lines = [l for l in out.getvalue().splitlines() if l.startswith("- operation=")]
        self.assertEqual(len(lines), 3)   # token-economy F3: three operations, --all for the rest
        self.assertIn("(name:str, place:str, type:str, from:int, to:int, max:int)", out.getvalue())

        def found(*argv):
            out = io.StringIO()
            cli.main(["archive", "find", *argv], stdout=out, environ={"PROBANDIA_CONFIG_DIR": project}, cwd=project)
            text = out.getvalue().splitlines()
            return ([l for l in text if l.startswith("- operation=")], [l for l in text if l.startswith("- browser=")])

        self.assertGreater(len(found("census of 1872 in Morbihan", "--all")[0]), 3)
        self.assertEqual(found("death records 1876")[1], [])   # no place: no browser archive...
        self.assertTrue(found("death records 1876", "--all")[1])
        self.assertTrue(found("a HathiTrust volume")[1][0].startswith("- browser=hathitrust "))   # ...unless named

    def test_a_browser_archive_shows_its_guide(self):
        # a real session of 6 Oct. 2026 spent ~50 browser calls finding how to read AD92
        out = io.StringIO()
        project = tempfile.mkdtemp()
        with open(os.path.join(project, "probandia.toml"), "w") as fh:
            fh.write("schema = 1\n")
        cli.main(["archive", "find", "marriage 1910 Hauts-de-Seine"], stdout=out,
                 environ={"PROBANDIA_CONFIG_DIR": project}, cwd=project)
        text = out.getvalue()
        self.assertIn("- browser=ad92 ", text)
        guide = [l for l in text.splitlines() if l.startswith("- guide=ad92: ")]
        self.assertEqual(len(guide), 5)
        self.assertTrue(any("iipsrv.fcgi" in l for l in guide))
        self.assertIn("researcher subagent", text)
        self.assertNotIn("guide=ad56", text)   # an archive without a guide shows none

    def test_a_site_the_need_names_comes_first_with_its_guide(self):
        # FL3: the readings measured in a real workshop (Persée, HathiTrust, eluxemburgensia)
        from probandia.archives.finder import find

        for need, archive, step in (("article in Persée", "persee", "renderPage"),
                                    ("a HathiTrust volume", "hathitrust", "/cgi/pt/search"),
                                    ("eluxemburgensia newspaper", "eluxemburgensia", "viewer2")):
            with self.subTest(archive=archive):
                browser = find(need)[1]
                self.assertEqual(browser[0]["id"], archive)
                self.assertTrue(any(step in line for line in browser[0]["guide"]))
        self.assertEqual(find("a HathiTrust volume")[1][0]["access"]["third_party"], "forbidden")

    def test_plan_names_the_guided_browser_archives_of_its_place(self):
        from types import SimpleNamespace

        from probandia.cli.search_cmd import browser_guided

        ctx = SimpleNamespace(project=None)
        doc = {"question": "Le mariage de Nicolas HUGOT", "axes": {   # an invented person
            "places": ["Hauts-de-Seine"], "record_types": ["marriage"], "window": {"from": 1908, "to": 1912}}}
        self.assertEqual(browser_guided(ctx, doc), ["ad92"])
        doc["axes"]["places"] = ["Morbihan"]
        self.assertEqual(browser_guided(ctx, doc), [])   # ad56 has no guide
        doc["axes"]["places"] = []
        self.assertEqual(browser_guided(ctx, doc), [])   # no place: no announcement


class WitnessRun(Base):
    def setUp(self):
        super().setUp()
        self.project = os.path.join(self.tmp.name, "project")
        shutil.copytree(os.path.join(FIX, "project"), self.project)

    def call(self, archive_id, *argv):
        from unittest import mock

        from probandia.cli import archive_cmd

        def make(ctx):
            c = self.context(archive_id)
            c.project = self.project
            return c
        out = io.StringIO()
        with mock.patch.object(archive_cmd, "_context", make):
            code = cli.main(list(argv), stdout=out, cwd=self.project,
                            environ={"PROBANDIA_CONFIG_DIR": self.tmp.name, "PROBANDIA_SESSION": "t"})
        return code, out.getvalue()

    def searches(self):
        return yamlio.load(os.path.join(self.project, "families", "hugo", "index",
                                        "searches.yaml"))["searches"]

    def test_witness_writes_its_result(self):
        code, out = self.call("openarchives", "archive", "run", "openarchives.witness")
        self.assertEqual(code, 0, out)
        self.assertIn("PASSED=true", out)
        last = self.searches()[-1]
        self.assertEqual((last["kind"], last["engine"]), ("archive", "openarchives"))
        self.assertTrue(last["witness"]["passed"])
        self.assertEqual(last["witness"]["operation"], "openarchives.search")

    def test_a_zero_inherits_the_witness_of_the_day(self):
        self.call("openarchives", "archive", "run", "openarchives.witness")
        from unittest import mock
        empty = {"status": 200, "headers": {}, "body": {"query": {}, "response": {"number_found": 0, "docs": []}}}
        with mock.patch.object(Replay, "__call__", lambda s, m, u, h, b, t: (
                (200, {}, b"", u) if u.endswith("robots.txt") else (200, {}, json.dumps(empty["body"]).encode(), u))):
            code, out = self.call("openarchives", "archive", "run", "openarchives.search",
                                  "--args", '{"name": "Zzyzx"}')
        last = self.searches()[-1]
        self.assertEqual(last["result"], "negative")
        self.assertTrue(last["witness"]["passed"])


class UnexpectedAnswer(WitnessRun):
    """T151: an exception of a connector other than ConnectorError is a failed call, logged, not an internal error."""

    def test_a_value_error_is_a_logged_failure(self):
        from unittest import mock

        module = archives.load("openarchives")
        with mock.patch.object(module, "run", side_effect=ValueError("no JSON object could be decoded")):
            code, out = self.call("openarchives", "archive", "run", "openarchives.search",
                                  "--args", '{"name": "Hugo"}', "--yes")
        self.assertNotEqual(code, 10, out)
        self.assertIn(out.splitlines()[0], ("STATUS=FAIL", "STATUS=WARN"))
        self.assertIn("FAILURE=unexpected-answer", out.splitlines(), out)
        last = self.searches()[-1]
        self.assertEqual((last["engine"], last["result"]), ("openarchives", "failed"))
        self.assertIn("ValueError", last["failure"])


class SilentFailure(WitnessRun):
    """PRD criterion 17 (T226): a portal that answers with an Anubis challenge page is reported as not consulted,
    through the command, and no negative is recorded."""

    def test_an_anubis_page_records_no_negative(self):
        own = self.context
        self.context = lambda archive, *a, **k: own(archive, {"*": recorded("gov", "challenge.json")})
        code, out = self.call("gov", "archive", "run", "gov.search", "--args", '{"name": "Octeville"}', "--yes")
        self.assertNotEqual(out.splitlines()[0], "STATUS=OK", out)
        self.assertIn("not consulted (challenge)", out)
        gov = [s for s in self.searches() if s.get("engine") == "gov"]
        self.assertEqual([s["result"] for s in gov], ["failed"])
        self.assertIn("challenge", gov[0]["failure"])
        self.assertFalse([s for s in self.searches() if s.get("result") == "negative" and s.get("engine") == "gov"])


class ReaderAdvice(WitnessRun):
    """T67: the advice to hand a register's views to a reader came with every archive run that saw views, and stayed
    in the agent's context: once a pass is enough."""

    ADVICE = "a register's views go to a reader subagent"
    REGISTERS = '{"commune": "Octeville", "type": "death", "from": 1876, "to": 1876}'

    def run_ad50(self, operation, args, *more):
        code, out = self.call("ad50", "archive", "run", f"ad50.{operation}", "--args", args, *more)
        self.assertEqual(code, 0, out)
        return out

    def test_the_reader_advice_comes_once_a_pass(self):
        self.assertIn(self.ADVICE, self.run_ad50("registers", self.REGISTERS))
        self.assertNotIn(self.ADVICE, self.run_ad50("view", '{"detail": 607643, "view": 89}'))   # same pass
        self.assertNotIn(self.ADVICE, self.run_ad50("registers", self.REGISTERS, "--agent", "reader"))
        code, out = self.call("ad50", "resume", "2026-09-30-parents-of-victor-hugo")   # pass 2
        self.assertEqual(code, 0, out)
        self.assertIn("PASS=2", out)
        self.assertIn(self.ADVICE, self.run_ad50("registers", self.REGISTERS))
        self.assertNotIn(self.ADVICE, self.run_ad50("view", '{"detail": 607643, "view": 89}'))


class Stale(unittest.TestCase):
    """TRUST4-T2: archive stale, and one setting for the age of every catalogue entry."""

    setUp = sample.Sample.setUp
    call = sample.Sample.call

    def test_archive_stale(self):
        import datetime
        import json

        from probandia.archives.finder import load_catalogue

        checked = [str((e.get("state") or {}).get("checked") or "") for e in load_catalogue().values()]
        newest = max(datetime.date.fromisoformat(c) for c in checked if c)
        days = (datetime.date.today() - newest).days
        code, out = self.call("archive", "stale", "--days", str(days + 1000), "--json")
        found = json.loads(out)
        stale = [x["archive"] for x in found["data"]["stale"]]
        never = [aid for aid, e in load_catalogue().items() if not (e.get("state") or {}).get("checked")]
        self.assertEqual(sorted(stale), sorted(never))
        code, out = self.call("archive", "stale", "--days", "0")
        self.assertEqual(out.splitlines()[0], "STATUS=WARN")
        self.assertIn("- stale=", out)
        # the setting gives the default
        self.call("config", "set", "catalogues.max_age_days", "365")
        code, out = self.call("archive", "stale")
        self.assertIn("DAYS=365", out)
        code, out = self.call("providers", "stale")
        self.assertIn("DAYS=365", out)

    def test_one_place_reads_the_setting(self):
        from probandia.providers import catalogue

        self.assertEqual(catalogue.max_age_days(None), 90)
        self.assertEqual(catalogue.stale([("a", 10), ("b", 100), ("c", None)], 90), ["b", "c"])
        for rel in ("src/probandia/doctor.py", "src/probandia/cli/usage_cmd.py", "src/probandia/board.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                self.assertNotIn("MAX_AGE_DAYS = 90", fh.read(), rel)
