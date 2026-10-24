"""token-economy A5: image tools that write a file and say what reading it costs; IIIF manifest, sheet, rotation."""
import importlib.util
import io
import json
import os
import struct
import tempfile
import unittest
from unittest import mock

from probandia import archives, cli, images
from probandia.util.http import Client

PILLOW = importlib.util.find_spec("PIL") is not None


def jpeg(width, height, text=""):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (width, height), (240, 230, 210))
    ImageDraw.Draw(im).text((20, 20), text, fill="black")
    out = io.BytesIO()
    im.save(out, "JPEG")
    return out.getvalue()


MANIFEST_V3 = {"type": "Manifest", "items": [
    {"id": f"c{n}", "type": "Canvas", "label": {"fr": [f"vue {n}"]}, "width": 1768, "height": 2643,
     "items": [{"type": "AnnotationPage", "items": [{"type": "Annotation", "body": {
         "id": f"https://iiif.example.org/img/{n}/full/max/0/default.jpg",
         "service": [{"id": f"https://iiif.example.org/img/{n}", "type": "ImageService3"}]}}]}]}
    for n in range(1, 11)]}
MANIFEST_V2 = {"@type": "sc:Manifest", "sequences": [{"canvases": [
    {"label": "f1", "width": 100, "height": 200, "images": [{"resource": {
        "@id": "https://iiif.example.org/v2/1/full/full/0/default.jpg",
        "service": {"@id": "https://iiif.example.org/v2/1"}}}]}]}]}


@unittest.skipUnless(PILLOW, "Pillow is not installed")
class Tools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.views = []
        for n in range(10):
            path = os.path.join(self.tmp.name, f"v{n}.jpg")
            with open(path, "wb") as fh:
                fh.write(jpeg(1768, 2643, f"vue {n}"))
            self.views.append(path)

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ={"PROBANDIA_CONFIG_DIR": self.tmp.name}, cwd=self.tmp.name)
        return code, out.getvalue()

    def value(self, out, key):
        return next((x.split("=", 1)[1] for x in out.splitlines() if x.startswith(key + "=")), None)

    def test_a_sheet_of_ten_views_is_one_image_to_read(self):
        code, out = self.call("image", "sheet", *self.views, "--labels", ",".join(str(80 + n) for n in range(10)))
        self.assertEqual(code, 0, out)
        w, h = (int(x) for x in self.value(out, "PX").split("x"))
        self.assertLessEqual(w * h, images.SHEET_MAX_PX)
        self.assertEqual(int(self.value(out, "TOKENS_EST")), round(w * h / 750))
        self.assertTrue(os.path.isfile(self.value(out, "FILE")))

    def test_crop_and_rotate(self):
        code, out = self.call("image", "crop", self.views[0], "--region", "0,0,0.5,0.25")
        self.assertEqual((code, self.value(out, "PX")), (0, "884x661"), out)
        self.assertEqual(self.value(out, "REGION"), "0,0,884,661")   # T73c: in pixels, what region= returns
        code, out = self.call("image", "rotate", self.views[0], "--turn", "90")
        self.assertEqual((code, self.value(out, "PX")), (0, "2643x1768"), out)
        code, out = self.call("image", "crop", self.views[0], "--region", "2,2,0.1,0.1")
        self.assertEqual((code, self.value(out, "REASON")), (1, "region"), out)
        # J7: a page is not an act (1,768 x 2,643 px, 6,230 tokens); --whole when the act fills it
        code, out = self.call("image", "crop", self.views[0], "--region", "0,0,1,1")
        self.assertEqual((code, self.value(out, "REASON"), self.value(out, "TOKENS_EST")), (1, "region-large", "6230"),
                         out)
        code, out = self.call("image", "crop", self.views[0], "--region", "0,0,1,1", "--whole")
        self.assertEqual((code, self.value(out, "PX")), (0, "1768x2643"), out)

    def test_without_pillow_the_command_stops(self):
        with mock.patch.object(images, "_pil", side_effect=images.NoPillow("no Pillow")):
            code, out = self.call("image", "rotate", self.views[0], "--turn", "90")
        self.assertEqual((code, self.value(out, "STATUS"), self.value(out, "REASON")), (4, "STOP", "no-pillow"), out)


class TokensWithoutPillow(unittest.TestCase):
    """token-economy I2: TOKENS_EST on every image an archive operation writes, Pillow or not."""

    PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 1768, 2643) + b"\x08\x02\x00\x00\x00"
    JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"   # APP0, then the frame header
            b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 400, 1000) + b"\x03" + b"\x00" * 9 + b"\xff\xd9")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_the_size_comes_from_the_header(self):
        self.assertEqual(images.size_of(self.write("a.png", self.PNG)), (1768, 2643))
        self.assertEqual(images.size_of(self.write("b.jpg", self.JPEG)), (1000, 400))
        self.assertIsNone(images.size_of(self.write("c.json", b"{}")))
        self.assertIsNone(images.size_of(self.write("d.jpg", self.JPEG[:26])))   # cut in the frame header
        if PILLOW:
            self.assertEqual(images.size_of(self.write("e.jpg", jpeg(321, 123))), (321, 123))

    def test_an_archive_image_says_what_reading_it_costs(self):
        import types

        from probandia.cli.archive_cmd import _render

        result = archives.OperationResult(path=self.write("view.jpg", self.JPEG))
        with mock.patch.object(images, "_pil", side_effect=images.NoPillow("no Pillow")):
            r = _render(types.SimpleNamespace(project=self.tmp.name), "iiif", "region", result, None)
        self.assertEqual((r.values["PX"], r.values["TOKENS_EST"]), ("1000x400", round(1000 * 400 / 750)))

    def test_a_view_goes_to_a_reader(self):
        # token-economy A7: the session agent and the orchestrator are told, at the view, that a reader reads it
        import types

        from probandia.cli.archive_cmd import _render

        view = archives.OperationResult(path=self.write("view.jpg", self.JPEG))
        listed = archives.OperationResult(rows=[{"detail": 607643, "cote": "5 Mi 716"}])   # J1: no viewer
        found = archives.OperationResult(rows=[{"title": "A book", "url": "https://example.org/b"}])
        for agent, result, told in ((None, view, True), ("orchestrator", listed, True), ("reader", view, False),
                                    ("researcher", view, False), (None, found, False)):
            ctx = types.SimpleNamespace(project=self.tmp.name, args=types.SimpleNamespace(agent=agent))
            r = _render(ctx, "ad50", "view", result, None)
            self.assertEqual(any("reader subagent" in line for line in r.lines), told, (agent, r.lines))

    def test_the_research_skill_looks_at_the_cost_first(self):
        from tests import ROOT

        with open(os.path.join(ROOT, "skills", "research", "SKILL.md"), encoding="utf-8") as fh:
            self.assertIn("`TOKENS_EST=`", fh.read())


class Manifests(unittest.TestCase):
    def test_views_of_a_manifest_version_2_and_3(self):
        from probandia.archives.iiif import views

        v3 = views(MANIFEST_V3)
        self.assertEqual((len(v3), v3[0]["label"], v3[0]["image"]), (10, "vue 1", "https://iiif.example.org/img/1"))
        v2 = views(MANIFEST_V2)
        self.assertEqual((v2[0]["view"], v2[0]["image"], v2[0]["height"]), (1, "https://iiif.example.org/v2/1", 200))


@unittest.skipUnless(PILLOW, "Pillow is not installed")
class IiifSheet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.urls = []

        def transport(method, url, headers, body, timeout):
            if url.endswith("/robots.txt"):
                return 200, {}, b"", url
            self.urls.append(url)
            if url.endswith("manifest.json"):
                return 200, {"content-type": "application/json"}, json.dumps(MANIFEST_V3).encode(), url
            return 200, {"content-type": "image/jpeg"}, jpeg(1000, 400, url[-40:]), url

        client = Client(os.path.join(self.tmp.name, "state"), None, None, transport, sleep=lambda s: None)
        self.ctx = archives.Context(client, None, {}, self.tmp.name, work=os.path.join(self.tmp.name, "work"))
        self.iiif = archives.load("iiif")

    def test_manifest_sheet_and_rotation(self):
        found = archives.run(self.iiif, "manifest", {"url": "https://iiif.example.org/manifest.json"}, self.ctx)
        self.assertEqual(len(found.rows), 10)
        sheet = archives.run(self.iiif, "sheet", {"url": "https://iiif.example.org/manifest.json", "from": 8,
                                                  "to": 10}, self.ctx)
        self.assertEqual([r["view"] for r in sheet.rows], [8, 9, 10])
        self.assertTrue(any("/img/9/pct:0,0,100,25/660,/0/default.jpg" in u for u in self.urls), self.urls)
        with open(sheet.path, "rb") as fh:
            self.assertEqual(fh.read(2), b"\xff\xd8")
        archives.run(self.iiif, "region", {"url": "https://iiif.example.org/img/9", "region": "full",
                                           "rotation": 90}, self.ctx)
        self.assertIn("/90/default.jpg", self.urls[-1])
