"""Report templates and their designer (optimize.md § 4)."""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from probandia import cli, events
from probandia.i18n import Translator
from probandia.report import designer
from probandia.report import render as R
from probandia.report import template as T
from probandia.util import yamlio
from tests import ROOT
from tests.unit import test_report as TR

GOLDEN = os.path.join(ROOT, "tests", "golden", "templates")
DESIGNER_JS = os.path.join(ROOT, "designer", "designer.js")
NODE = shutil.which("node")
STATUS_CLASS = re.compile(r' class="status-[a-z]+"')


def golden(test, name, text):
    path = os.path.join(GOLDEN, name)
    if os.environ.get("PROBANDIA_UPDATE_GOLDEN"):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    with open(path, encoding="utf-8") as fh:
        test.assertEqual(text, fh.read(), name)


def node(script, payload):
    """Runs ``script`` with ``D`` (designer.js) and ``input`` (the payload) defined;
    returns what it prints as JSON."""
    code = f"const D = require({json.dumps(DESIGNER_JS)});\n" \
           "const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + script
    done = subprocess.run([NODE, "-e", code], input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", check=True)
    return json.loads(done.stdout)


def trapped(snippet, where="</article>"):
    return T.parse(T.builtin().text.replace(where, snippet + where, 1), "default.html")


class Extraction(TR.ReportProject):
    """4.2: the default template gives the report the engine wrote before templates."""

    def renders(self):
        report = self.build()
        events.append(self.log, TR.ERRATUM)
        report = self.build()
        report.manual = [{"archive": "familysearch", "url": "https://www.familysearch.org/ark:/1"}]
        yield "journal-fr", R.to_html(report, Translator("fr"))
        yield "journal-en", R.to_html(self.build(lang="en"), Translator("en"))

    def test_default_renders_byte_for_byte_as_before(self):
        for name, html in self.renders():
            with self.subTest(name=name):
                with open(os.path.join(GOLDEN, "before", f"{name}.html"), encoding="utf-8") as fh:
                    before = fh.read()
                # the only additions: the status classes of the notes and their calls (4.8), and the
                # main landmark around the article (T123)
                self.assertEqual(unmain(STATUS_CLASS.sub("", html)), before)
                self.assertIn('<sup class="status-record">', html)
                golden(self, f"default-{name}.html", html)

    def test_the_engine_holds_no_stylesheet_any_more(self):
        self.assertFalse(hasattr(R, "CSS"))
        self.assertIn("<style>", T.builtin().text)


class LivingExtraction(TR.ReportProject):
    mode = "living"

    def test_living_report_unchanged(self):
        html = R.to_html(self.build(), Translator("fr"))
        with open(os.path.join(GOLDEN, "before", "living-fr.html"), encoding="utf-8") as fh:
            self.assertEqual(unmain(html), fh.read())


def unmain(html):
    """The report without the main landmark of T123, as it was before."""
    return html.replace("<main><article>", "<article>", 1).replace("</article></main>", "</article>", 1)


class Base(TR.ReportProject):
    def setUp(self):
        super().setUp()
        self.user = os.path.join(self.tmp.name, "user")
        self.env["HOME"] = self.env["USERPROFILE"] = os.path.join(self.tmp.name, "home")

    def put(self, folder, tid, **changes):
        """A copy of a built-in template under another id, in ``folder``."""
        text = T.builtin("print").text.replace('content="print"', f'content="{tid}"', 1)
        for old, new in changes.items():
            text = text.replace(old, new)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{tid}.html")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return path

    def values(self, out):
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line and not line.startswith("-"))

    def family_yaml(self):
        return os.path.join(self.dir, "families", "hugo", "family.yaml")


class Resolution(Base):
    """4.3: from --template to default, each level in turn."""

    def test_each_level(self):
        code, out = self.call("render", "--formats", "html")
        self.assertEqual((self.values(out)["TEMPLATE"], self.values(out)["TEMPLATE_ORIGIN"]),
                         ("default", "default built-in"))
        self.put(os.path.join(self.user, "templates"), "mine")
        self.call("config", "set", "report.template", "mine", "--user")
        out = self.call("render", "--formats", "html")[1]
        self.assertEqual(self.values(out)["TEMPLATE"], "mine")
        self.assertTrue(self.values(out)["TEMPLATE_ORIGIN"].startswith("user "), out)
        self.call("config", "set", "report.template", "high-contrast")
        out = self.call("render", "--formats", "html")[1]
        self.assertEqual(self.values(out)["TEMPLATE"], "high-contrast")
        self.assertTrue(self.values(out)["TEMPLATE_ORIGIN"].startswith("project "), out)
        doc = yamlio.load(self.family_yaml())
        doc["template"] = "family-book"
        yamlio.dump(self.family_yaml(), doc)
        out = self.call("render", "--formats", "html")[1]
        self.assertEqual((self.values(out)["TEMPLATE"], self.values(out)["TEMPLATE_ORIGIN"]), ("family-book", "family"))
        self.set_meta(template="print")
        out = self.call("render", "--formats", "html")[1]
        self.assertEqual((self.values(out)["TEMPLATE"], self.values(out)["TEMPLATE_ORIGIN"]), ("print", "research"))
        out = self.call("render", "--formats", "html", "--template", "default")[1]
        self.assertEqual((self.values(out)["TEMPLATE"], self.values(out)["TEMPLATE_ORIGIN"]), ("default", "--template"))
        code, out = self.call("config", "show", "--origin")
        self.assertIn("report.template=high-contrast  # project", out)

    def test_the_project_hides_the_user_which_hides_the_engine(self):
        self.put(os.path.join(self.user, "templates"), "print", **{"Sober and serif": "User copy"})
        self.assertEqual(T.find("print", self.dir, None, self.env).scope, "user")
        self.put(os.path.join(self.dir, "templates"), "print", **{"Sober and serif": "Project copy"})
        tpl = T.find("print", self.dir, None, self.env)
        self.assertEqual(tpl.scope, "project")
        self.assertIn("Project copy", tpl.text)

    def test_an_unknown_template_stops_the_render(self):
        code, out = self.call("render", "--template", "nowhere")
        self.assertNotEqual(code, 0)
        self.assertIn("REASON=unknown-template", out)


class Security(unittest.TestCase):
    """4.4: trapped or incomplete templates are refused."""

    def test_the_shipped_templates_pass(self):
        ids = sorted(t.id for t in T.available(None, None, {"PROBANDIA_CONFIG_DIR": tempfile.gettempdir() + "/none"}))
        self.assertEqual(ids, ["default", "family-book", "habillage", "high-contrast", "print"])
        for tid in ids:
            self.assertEqual(T.check(T.builtin(tid)), [], tid)

    def test_trapped_templates(self):
        for snippet in ("<script>alert(1)</script>", '<p onmouseover="x()">', '<a href="javascript:x()">',
                        '<a href="https://example.org">', '<img src="https://example.org/a.png">',
                        "<style>@import 'https://x/a.css';</style>", "<style>p{background:url(https://x/a)}</style>",
                        '<iframe src="data:text/html,x"></iframe>', '<link rel="stylesheet" href="#x">',
                        '<meta http-equiv="refresh" content="0">', "<style>p{behavior:url(#x)}</style>"):
            with self.subTest(snippet=snippet):
                self.assertTrue(T.check(trapped(snippet)), snippet)
        self.assertEqual(T.check(trapped('<img src="data:image/png;base64,AAAA" alt="">')), [])

    def test_incomplete_templates(self):
        base = T.builtin().text
        cases = {
            "no slot body": base.replace("<!-- probandia:slot body -->", "<!-- x -->", 1),
            "no <meta name=\"probandia:contract\">": base.replace('<meta name="probandia:contract" content="1">\n', ""),
            "contract 2": base.replace('probandia:contract" content="1"', 'probandia:contract" content="2"'),
            "unknown slot footer": base.replace("</article>", "<!-- probandia:slot footer -->x<!-- /probandia:slot -->"
                                                "</article>"),
            "unknown label": base.replace("</article>", "<!-- probandia:label Nothing -->x<!-- /probandia:label -->"
                                          "</article>"),
            "contrast": base.replace("--ink: #1b1b1b", "--ink: #dddddd"),
            "bytes": base.replace("</article>", "<!--" + "x" * T.MAX_BYTES + "--></article>"),
        }
        for words, text in cases.items():
            with self.subTest(case=words):
                reasons = T.check(T.parse(text, "default.html"))
                self.assertTrue(any(words in r for r in reasons), reasons)
        self.assertTrue(T.check(T.parse(base, "other.html")))   # the file is named after the id


class Commands(Base):
    """4.5: list, show, check, import, export, use."""

    def test_the_six_commands(self):
        code, out = self.call("template", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("TEMPLATES=5", out)
        self.assertIn("* default [builtin]", out)
        code, out = self.call("template", "show", "family-book")
        self.assertIn("NOTES=chapter", out)
        self.assertIn("CHECK=ok", out)
        exported = os.path.join(self.tmp.name, "out", "book.html")
        code, out = self.call("template", "export", "family-book", exported)
        self.assertEqual(code, 0, out)
        with open(exported, encoding="utf-8") as fh:
            text = fh.read().replace('content="family-book"', 'content="our-book"', 1)
        mine = os.path.join(self.tmp.name, "our-book.html")
        with open(mine, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        self.assertEqual(self.call("template", "check", mine)[0], 0)
        code, out = self.call("template", "import", mine)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "templates", "our-book.html")))
        code, out = self.call("template", "use", "our-book", "--level", "family", "--research", TR.RID)
        self.assertEqual(code, 0, out)
        self.assertEqual(yamlio.load(self.family_yaml())["template"], "our-book")
        code, out = self.call("template", "use", "print", "--level", "research", "--research", TR.RID)
        self.assertEqual(yamlio.load(os.path.join(self.rdir, "research.yaml"))["template"], "print")
        code, out = self.call("template", "use", "high-contrast")
        with open(os.path.join(self.dir, "probandia.toml"), encoding="utf-8") as fh:
            self.assertIn('report.template = "high-contrast"', fh.read())
        code, out = self.call("template", "list")
        self.assertIn("our-book [project]", out)
        for line in out.splitlines():
            self.assertLess(len(out.splitlines()), 41, line)

    def test_import_refuses_a_trapped_template_and_an_overwrite(self):
        bad = os.path.join(self.tmp.name, "bad.html")
        with open(bad, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(trapped("<script>x</script>").text.replace('content="default"', 'content="bad"', 1))
        code, out = self.call("template", "import", bad)
        self.assertNotEqual(code, 0)
        self.assertIn("a script", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "templates", "bad.html")))
        path = self.put(os.path.join(self.tmp.name, "a"), "twice")
        self.assertEqual(self.call("template", "import", path)[0], 0)
        self.put(os.path.join(self.tmp.name, "a"), "twice", **{"Sober and serif": "Changed"})
        code, out = self.call("template", "import", path)
        self.assertIn("REASON=exists", out)
        self.assertEqual(self.call("template", "import", path, "--replace")[0], 0)

    def test_the_skill_describes_them(self):
        text = ""
        for name in ("SKILL.md", "templates.md"):
            with open(os.path.join(ROOT, "skills", "report", name), encoding="utf-8") as fh:
                text += fh.read()
        self.assertIn("skills/report/templates.md", text)
        for words in ("template list", "template show", "template check", "template import", "template export",
                      "template use", "template designer", "render --all"):
            self.assertIn(words, text)


class Mass(Base):
    """4.6: render --all, the template's fingerprint, V-13."""

    def test_render_all_and_verify(self):
        code, out = self.call("render", "--all")
        self.assertEqual(code, 0, out)
        self.assertIn("RESEARCHES=1", out)
        data = json.loads(self.read("report.json"))
        self.assertEqual(data["template"], T.builtin().fingerprint())
        self.assertEqual(R.validate(data), [])
        self.put(os.path.join(self.dir, "templates"), "ours")
        self.call("template", "use", "ours")
        self.call("render", "--all", "--family", "hugo")
        self.assertIn('<meta name="dcterms.modified"', self.read("report.html"))
        self.assertIn("font: 15px/1.5", self.read("report.html"))
        self.assertEqual(json.loads(self.read("report.json"))["template"]["id"], "ours")
        self.assertIn("V-13=PASS", self.call("verify", TR.RID, "--rule", "V-13")[1])
        self.put(os.path.join(self.dir, "templates"), "ours", **{"Sober and serif": "Edited"})
        out = self.call("verify", TR.RID, "--rule", "V-13")[1]
        self.assertIn("V-13=FAIL", out)
        self.assertIn("changed since", out)
        os.remove(os.path.join(self.dir, "templates", "ours.html"))
        self.assertIn("no longer exists", self.call("verify", TR.RID, "--rule", "V-13")[1])
        code, out = self.call("render", "--all", "--family", "nobody")
        self.assertNotEqual(code, 0)


class Designer(unittest.TestCase):
    """4.7 to 4.11: the designer page, its sample, its templates."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "designer", "sample.json"), encoding="utf-8") as fh:
            cls.sample = json.load(fh)

    def test_the_sample_is_up_to_date(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("mds", os.path.join(ROOT, "tools", "make_designer_sample.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with open(module.OUT, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), module.text(), "run: python tools/make_designer_sample.py")

    def test_the_page_is_self_contained(self):
        page = designer.page()
        self.assertNotIn("@@DATA@@", page)
        self.assertNotIn("@@CODE@@", page)
        self.assertEqual(page.lower().count("</script>"), 3)
        for needle in ("<link", "@import", "http://", "src=\"http", "src='http"):
            self.assertNotIn(needle, page.replace("https://www.familysearch.org", "").replace("http://www.w3.org", ""))
        self.assertNotRegex(page, r"<script[^>]+src=")
        for tid in ("default", "print", "family-book", "high-contrast"):
            self.assertIn(f'"{tid}"', page)

    def test_template_designer_writes_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "p")
            shutil.copytree(TR.FIXTURE, project)
            out = io.StringIO()
            code = cli.main(["template", "designer", "--no-open"], stdout=out, cwd=project,
                            environ={"PROBANDIA_CONFIG_DIR": os.path.join(tmp, "user")})
            self.assertEqual(code, 0, out.getvalue())
            path = os.path.join(project, "templates", "designer", "designer.html")
            self.assertTrue(os.path.isfile(path))
            self.assertNotIn("designer", [t.id for t in T.available(project, None, {})])

    def test_labels_follow_the_language(self):
        """4.10: one template, an English and a French report."""
        tpl = T.builtin("family-book")
        for lang, word in (("en", "Generated"), ("fr", "Généré")):
            out = T.fill(tpl, self.sample["slots"][lang]["chapter"], Translator(lang), lang)
            self.assertIn(f'<footer class="report-footer">{word} ', out)
            self.assertIn(f'<html lang="{lang}">', out)
            self.assertNotIn("probandia:", out)

    def test_the_references_of_each_template(self):
        """4.11: each template renders the sample report as it did."""
        for tpl in (T.builtin(t) for t in ("default", "print", "family-book", "high-contrast")):
            out = T.fill(tpl, self.sample["slots"]["fr"][tpl.notes], Translator("fr"), "fr")
            golden(self, f"sample-{tpl.id}-fr.html", out)


@unittest.skipUnless(NODE, "Node.js is not installed")
class DesignerCode(unittest.TestCase):
    """The designer's JavaScript, run by Node."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "designer", "sample.json"), encoding="utf-8") as fh:
            cls.sample = json.load(fh)

    def test_the_preview_is_what_the_engine_renders(self):
        """4.9: a template exported, then installed, renders as the preview showed it."""
        jobs = []
        for tid in ("default", "print", "family-book", "high-contrast"):
            tpl = T.builtin(tid)
            for lang in ("en", "fr"):
                jobs.append({"text": tpl.text, "lang": lang, "slots": self.sample["slots"][lang][tpl.notes],
                             "engine": T.fill(tpl, self.sample["slots"][lang][tpl.notes], Translator(lang), lang)})
        got = node("console.log(JSON.stringify(input.jobs.map(j => D.fill(j.text, j.slots, input.labels, j.lang))));",
                   {"jobs": jobs, "labels": self.sample["labels"]})
        for job, preview in zip(jobs, got):
            self.assertEqual(preview, job["engine"])

    def test_the_shipped_presets_are_up_to_date(self):
        got = node("const o = {}; for (const id of Object.keys(D.PRESETS)) o[id] = D.build(D.preset(id));"
                   "console.log(JSON.stringify(o));", {})
        for tid, text in got.items():
            self.assertEqual(T.builtin(tid).text, text, "run: node tools/make_templates.mjs")

    def test_every_setting_reaches_the_exported_template(self):
        """4.8: each setting changes the template, and opening it again gives the settings back."""
        changes = [
            ["colors.ink", "#222244"], ["colors.paper", "#fffdf5"], ["colors.link", "#003366"],
            ["colors.heading", "#330000"], ["colors.note", "#eeeeff"], ["colors.noteRule", "#000066"],
            ["colors.muted", "#444444"], ["colors.rule", "#aaaaaa"],
            ["font.body", "system-serif"], ["font.headings", "mono"], ["font.size", 18], ["font.lineHeight", 1.7],
            ["font.embedded", {"name": "Libre", "dataUrl": "data:font/woff2;base64,d09GMgAB"}],
            ["layout.width", 52], ["layout.marginX", 2], ["layout.marginTop", 4],
            ["titlePage.enabled", True], ["titlePage.subtitle", "Famille Marchand"],
            ["titlePage.logo", "data:image/png;base64,iVBORw0KGgo="],
            ["header.text", "Recherches Marchand"], ["header.research", True],
            ["footer.generated", False], ["footer.text", "Pour la famille"],
            ["toc.position", "none"], ["toc.depth", 1],
            ["statuses.record.color", "#006600"], ["statuses.record.mark", "✔"],
            ["statuses.refuted.mark", "×"], ["statuses.hypothesis.color", "#664400"],
            ["errata.style", "plain"], ["notes", "chapter"],
            ["tree.record", "#004400"], ["tree.line", "#111111"],
            ["print.paper", "Letter"], ["print.margin", 25], ["print.chapterBreak", True],
        ]
        script = """
const out = [];
const base = D.build(D.defaults());
for (const [path, value] of input.changes) {
  const s = D.defaults();
  const keys = path.split(".");
  let o = s;
  for (const k of keys.slice(0, -1)) o = o[k];
  o[keys[keys.length - 1]] = value;
  if (path === "titlePage.logo") s.titlePage.enabled = true;
  const text = D.build(s);
  out.push({path, changed: text !== base, back: JSON.stringify(D.read(text)) === JSON.stringify(s), text});
}
console.log(JSON.stringify(out));
"""
        for row in node(script, {"changes": changes}):
            with self.subTest(setting=row["path"]):
                self.assertTrue(row["changed"])
                self.assertTrue(row["back"])
                self.assertEqual(T.check(T.parse(row["text"], "my-template.html")), [])

    def test_contrast(self):
        got = node("console.log(JSON.stringify([D.contrast('#000000', '#ffffff'), D.contrast('#777777', '#ffffff'),"
                   "D.contrastPairs(D.defaults()).every(p => p.ok)]));", {})
        self.assertEqual(got[0], 21)
        self.assertLess(got[1], 4.5)
        self.assertTrue(got[2])
        self.assertAlmostEqual(T.contrast("#777777", "#ffffff"), got[1], places=1)


if __name__ == "__main__":
    unittest.main()
