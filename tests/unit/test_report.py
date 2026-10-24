import datetime
import glob
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, events
from probandia.i18n import Translator
from probandia.indexes import FamilyIndexes
from probandia.report import numbering
from probandia.report import render as R
from probandia.report.living import names_in_query
from probandia.util import yamlio
from tests import ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
GOLDEN = os.path.join(ROOT, "tests", "golden")
RID = "2026-09-30-parents-of-victor-hugo"
TODAY = datetime.date(2026, 10, 1)
ACTOR = {"harness": "claude-code", "agent": "session", "model": "claude-opus-5-5"}


def sid(n):
    return "01J9ZM" + f"{n:020d}"


def eid(n):
    return "01M3V8" + f"{n:020d}"


def ev(n, type_, payload, pass_no, minute=None):
    return {"id": eid(n), "ts": f"2026-09-30T19:{(minute if minute is not None else n) % 60:02d}:00Z",
            "pass": pass_no, "actor": ACTOR, "type": type_, "payload": payload, "refs": [],
            "supersedes": None}


def section(n, title, body, parent=None, kind="section", facts=(), position=None):
    s = {"id": sid(n), "parent": sid(parent) if parent else None, "kind": kind, "title": title,
         "body_md": body, "facts": list(facts)}
    if position is not None:
        s["position"] = position
    return {"section": s}


JOURNAL = [
    ev(1, "section.added", section(1, "Acte de naissance", "Victor : [[f:victor-hugo-1802.birth]]. "
                                   f"Voir [[s:{sid(2)}]].\n\n<script>alert(1)</script>", kind="chapter",
                                   facts=["victor-hugo-1802.birth"]), 1),
    ev(2, "section.added", section(2, "Le père présumé", "[[p:leopold-hugo-1773]] : "
                                   "[[f:leopold-hugo-1773.birth]].", parent=1), 1),
    ev(3, "section.added", section(3, "Détail", "Une sous-section.", parent=2, kind="subsection"), 1),
    ev(4, "branch.added", {"root": "victor-hugo-1802", "persons": ["victor-hugo-1802", "leopold-hugo-1773"]}, 1),
    ev(5, "pass.started", {"n": 2, "run": {"mode": "session"}, "instructions": []}, 2),
    ev(6, "section.added", section(6, "Vérifications", "Les index concordent. [[p:camille-vernier-1966]] "
                                   "est citée.", kind="chapter"), 2),
    # an invented living person, unrelated to the Hugos: her own branch
    ev(11, "branch.added", {"root": "camille-vernier-1966", "persons": ["camille-vernier-1966"]}, 2, minute=6),
    ev(7, "section.added", section(7, "Index", "Une table.\n\n| a | b |\n|---|---|\n| 1 | 2 |", parent=6), 2),
    ev(8, "pass.ended", {"n": 2, "summary": "", "units": {}, "native_searches": 0, "duration_s": 1}, 2),
]

ERRATUM = [
    ev(9, "pass.started", {"n": 3, "run": {"mode": "session"}, "instructions": []}, 3),
    ev(10, "fact.revised", {"fact": "leopold-hugo-1773.birth", "before": "1773", "after": "1773-11-15",
                            "wrong": "vers 1773", "reason": "relecture de l'index", "cause": "misreading"}, 3),
]

LIVING = [
    ev(1, "section.added", section(1, "Synthèse", "Le père est probablement [[p:leopold-hugo-1773]].",
                                   kind="chapter"), 1),
    ev(2, "section.added", section(2, "Analyse des actes", "Chapitre du modèle.", kind="chapter", position=1), 1),
    ev(3, "section.added", section(3, "L'acte de 1802", "Première lecture.", parent=2), 1),
    ev(4, "section.added", section(4, "Complément", "Un complément.", parent=2), 1),
]

REWRITE = [
    ev(5, "pass.started", {"n": 2, "run": {"mode": "session"}, "instructions": []}, 2),
    ev(6, "section.replaced", {"section": sid(3), "title": "L'acte de 1802", "body_md": "Seconde lecture.",
                               "reason": "l'image a été relue"}, 2),
    ev(7, "section.merged", {"sections": [sid(4)], "into": sid(3), "reason": "doublon"}, 2),
]

LIVING_PERSON = {
    "id": "camille-vernier-1966", "names": {"given": "Camille", "surname": "VERNIER"}, "sex": "F",
    "living": "auto", "parents": {"father": None, "mother": None}, "spouses": [],
    "facts": [{"id": "camille-vernier-1966.birth", "type": "birth",
               "date": {"value": "1966-05-02", "qualifier": "exact"},
               "place": {"id": None, "as_written": "Metz"}, "status": "record", "research": RID}],
}


class ReportProject(unittest.TestCase):
    """A copy of the fixture project, with a fixed event log."""

    mode = "journal"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.rdir = os.path.join(self.dir, "families", "hugo", "research", RID)
        self.log = os.path.join(self.rdir, "events.jsonl")
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"),
                    "PROBANDIA_SESSION": "test", "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude")}
        persons = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        doc = yamlio.load(persons)
        doc["persons"].append(LIVING_PERSON)
        yamlio.dump(persons, doc)
        self.set_meta(mode=self.mode)
        events.append(self.log, LIVING if self.mode == "living" else JOURNAL)

    def set_meta(self, **changes):
        path = os.path.join(self.rdir, "research.yaml")
        meta = yamlio.load(path)
        meta.update(changes)
        yamlio.dump(path, meta)

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def build(self, lang="fr", style="arabic", pattern=""):
        meta = yamlio.load(os.path.join(self.rdir, "research.yaml"))
        docs = FamilyIndexes(self.dir, "hugo").load_all()
        return R.build_report(meta, events.read(self.log), docs, lang, Translator(lang),
                              numbering_style=style, pattern=pattern, today=TODAY)

    def read(self, name):
        with open(os.path.join(self.rdir, "report", name), encoding="utf-8") as fh:
            return fh.read()


class Numbering(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual([numbering.roman(n) for n in (1, 4, 9, 14, 40, 3999)],
                         ["I", "IV", "IX", "XIV", "XL", "MMMCMXCIX"])
        self.assertEqual([numbering.letters(n) for n in (1, 26, 27, 28, 52, 53)],
                         ["A", "Z", "AA", "AB", "AZ", "BA"])
        with self.assertRaises(ValueError):
            numbering.roman(4000)

    def test_pattern(self):
        self.assertEqual(numbering.parse_pattern("{I}.{A}.{1}.{a}"), (["I", "A", "1", "a"], "."))
        with self.assertRaises(ValueError):
            numbering.parse_pattern("x")


class Journal(ReportProject):
    def test_a_fact_cited_after_a_sentence_is_not_said_twice(self):
        # the criterion 2 trial of 24 October 2026: « … le 26 février 1802 Victor HUGO, naissance, 26 février
        # 1802, Besançon[^1] ». After the agent's words, a fact reference is its note only; alone, after a colon
        # or as a list item, it is the fact
        body = ("Victor naît à Besançon le 26 février 1802 [[f:victor-hugo-1802.birth]]. "
                "Son père : [[f:leopold-hugo-1773.birth]].\n\n- [[f:victor-hugo-1802.birth]]")
        events.append(self.log, [ev(12, "section.added", section(12, "Synthèse", body, kind="chapter"), 2)])
        md = R.to_markdown(self.build(), Translator("fr"))
        text = md.split("Synthèse", 1)[1]
        self.assertRegex(text, r"Victor naît à Besançon le 26 février 1802\[\^\d+\]\. ")
        self.assertRegex(text, r"Son père : Léopold HUGOT, naissance, vers 1773, Nanzig\[\^\d+\]\.")
        self.assertRegex(text, r"\n- Victor HUGO, naissance, 26 février 1802, Besançon\[\^\d+\]")

    def test_golden_files_of_the_three_styles(self):
        for style in ("arabic", "roman", "roman-outline"):
            with self.subTest(style=style):
                text = R.to_markdown(self.build(style=style), Translator("fr"))
                path = os.path.join(GOLDEN, f"report-{style}.md")
                if os.environ.get("PROBANDIA_UPDATE_GOLDEN"):
                    os.makedirs(GOLDEN, exist_ok=True)
                    with open(path, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(text)
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(text, fh.read())

    def test_paths_and_references(self):
        outline = self.build(style="roman-outline")
        by_id = {n.id: n for n in outline.model.walk()}
        self.assertEqual((by_id[sid(2)].number, by_id[sid(2)].path), ("A.", "I.A"))
        self.assertEqual((by_id[sid(3)].number, by_id[sid(3)].path), ("1.", "I.A.1"))
        self.assertIn(f"[§ I.A](#s-{sid(2).lower()})", outline.resolved["pass-1"])
        roman = self.build(style="roman")
        self.assertEqual({n.id: n.path for n in roman.model.walk()}[sid(3)], "I.1.1")
        custom = self.build(pattern="{i}-{a}-{1}")
        self.assertEqual({n.id: n.path for n in custom.model.walk()}[sid(3)], "i-a-1")

    def test_journal_chapters(self):
        report = self.build()
        titles = [c.title for c in report.model.chapters]
        self.assertEqual(titles, ["Passe 1 — Acte de naissance", "Passe 2 — Vérifications", "Méthode", "Sources"])
        self.assertIn(sid(1), report.model.chapters[0].aliases)
        self.assertEqual(R.rule_v6(report), ("PASS", []))

    def test_deterministic_bytes(self):
        code, out = self.call("render", "--formats", "md,html,json")
        self.assertEqual(code, 0, out)
        first = [self.read(n) for n in ("report.md", "report.html", "report.json")]
        code, out = self.call("render", "--formats", "md,html,json")
        self.assertEqual([self.read(n) for n in ("report.md", "report.html", "report.json")], first)
        data = json.loads(first[2])
        self.assertEqual(R.validate(data), [])
        self.assertEqual(data["generated"], "2026-09-30T19:08:00Z")

    def test_unresolved_reference_fails_v6(self):
        events.append(self.log, [ev(20, "section.added", section(20, "Erreur", "Voir [[s:01J9ZM00000000000000099999]] "
                                                                 "et [[p:nobody]].", kind="chapter"), 2)])
        report = self.build()
        self.assertEqual(R.rule_v6(report)[0], "FAIL")
        self.assertEqual(len(R.rule_v6(report)[1]), 2)
        code, out = self.call("render")
        self.assertIn("STATUS=WARN", out)
        self.assertIn("REASON=unresolved-references", out)

    def test_erratum_keeps_earlier_text(self):
        before = self.build()
        lines_before = events.read_lines(self.log)
        events.append(self.log, ERRATUM)
        after = self.build()
        self.assertEqual(events.read_lines(self.log)[:len(lines_before)], lines_before)
        self.assertEqual(before.data["sections"][0], after.data["sections"][0])
        md = R.to_markdown(after, Translator("fr"))
        self.assertIn("†E1", after.resolved[sid(2)])
        self.assertNotIn("†E1", before.resolved[sid(2)])
        self.assertIn("> **†** Erratum E1 — passe 3 : vers 1773 → 1773-11-15. Cause : erreur de lecture. "
                      "relecture de l'index.", md)
        self.assertIn("Errata", [c.title for c in after.model.chapters])
        self.assertEqual(after.data["errata"][0]["id"], "E1")
        html = R.to_html(after, Translator("fr"))
        self.assertIn('<aside class="erratum" role="note">', html)

    def test_html_is_self_contained_and_escapes_prose(self):
        html = R.to_html(self.build(), Translator("fr"))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        for needle in ("src=", "<link", "@import", "url("):
            self.assertNotIn(needle, html)
        self.assertIn('<html lang="fr">', html)
        self.assertIn("<nav", html)
        self.assertIn("@media print", html)
        self.assertIn("<table>", html)

    def test_french_and_english_labels(self):
        code, out = self.call("render", "--formats", "md")
        self.assertIn("LANG=fr", out)
        self.assertIn("LANG_SOURCE=research", out)
        md = self.read("report.md")
        for text in ("## Sommaire", "Passe 1", "## 3 Méthode", "26 février 1802", "Acte.", "vers 1773", "Index."):
            self.assertIn(text, md)
        code, out = self.call("--lang", "en", "render", "--formats", "md")
        self.assertIn("LANG=en", out)
        self.assertIn("LANG_SOURCE=arg", out)
        md = self.read("report.md")
        for text in ("## Contents", "Pass 1", "Method", "26 February 1802", "Record.", "about 1773"):
            self.assertIn(text, md)

    def test_living_person_masked(self):
        report = self.build()
        md = R.to_markdown(report, Translator("fr"))
        html = R.to_html(report, Translator("fr"))
        for text in (md, html, json.dumps(report.data["trees"], ensure_ascii=False)):
            self.assertNotIn("Camille", text)
            self.assertIn("Personne vivante", text)
        node = [n for tree in report.data["trees"] for n in tree["nodes"] if n["living"]][0]
        self.assertEqual(node["id"], "living-1")  # the slug would show the name and the birth year
        self.assertIn("```mermaid", md)

    def test_translate_labels_for_another_language(self):
        code, out = self.call("--lang", "pt", "render")
        self.assertEqual(code, 3, out)
        self.assertIn("QUESTION=translate_labels", out)
        self.assertIn("TARGET=locales/pt/LC_MESSAGES/probandia.po", out)
        self.assertIn("POT=locales/pt/LC_MESSAGES/report-labels.pot", out)   # T70: written next to TARGET=
        po = os.path.join(self.dir, "locales", "pt", "LC_MESSAGES", "probandia.po")
        with open(po, "w", encoding="utf-8") as fh:
            fh.write('msgid "Contents"\nmsgstr "Sumário"\n')
        code, out = self.call("--lang", "pt", "render", "--formats", "md")
        self.assertEqual(code, 0, out)
        self.assertIn("## Sumário", self.read("report.md"))
        self.assertIn("LABELS_MISSING=", out)   # T70: the other labels it asks for, still in English

    def test_broken_chain_stops(self):
        with open(self.log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write('{"id":"x","prev":"sha256:00"}\n')
        code, out = self.call("render")
        self.assertEqual(code, 1)
        self.assertIn("REASON=chain-broken", out)


class Living(ReportProject):
    mode = "living"

    def test_default_chapters_and_model_chapter(self):
        report = self.build()
        titles = [c.title for c in report.model.chapters]
        self.assertEqual(titles[:3], ["Synthèse", "Question et périmètre", "Personnes"])
        self.assertLess(titles.index("Analyse des actes"), titles.index("Sources"))
        self.assertIn(sid(1), report.model.chapters[0].aliases)

    def test_rewrite_keeps_anchor_and_adds_revision(self):
        code, out = self.call("render", "--formats", "md,json")
        self.assertEqual(code, 0, out)
        first_md = self.read("report.md")
        anchor = f'<a id="s-{sid(3).lower()}"></a>'
        self.assertIn(anchor, first_md)
        events.append(self.log, REWRITE)
        code, out = self.call("render", "--formats", "md,json")
        self.assertIn("SNAPSHOT=families/hugo/research/", out)
        md = self.read("report.md")
        self.assertIn(anchor, md)
        self.assertIn(f'<a id="s-{sid(4).lower()}"></a>', md)  # the merged section's anchor stays
        self.assertIn("Seconde lecture.", md)
        self.assertNotIn("Première lecture.", md)
        self.assertIn("Historique des révisions", md)
        self.assertIn("réécrite", md)
        self.assertIn("l'image a été relue", md)
        with open(os.path.join(self.rdir, "report", "history", "1.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), first_md)
        data = json.loads(self.read("report.json"))
        self.assertEqual(data["revisions"][0]["pass"], 2)
        self.assertEqual(R.validate(data), [])

    def test_an_error_of_pass_2_found_at_pass_3(self):
        # PRD criterion 7 (T226), the scenario of criterion 6: the section is rewritten, the report renumbered,
        # the anchor kept, and the revision history has its entry
        def node(report, n):
            return next(x for x in report.model.walk() if x.id == sid(n))
        events.append(self.log, [
            ev(5, "pass.started", {"n": 2, "run": {"mode": "session"}, "instructions": []}, 2),
            ev(6, "section.added", section(6, "Le baptême", "Baptisé à Nancy.", parent=2), 2)])
        before = self.build()
        number, anchor = node(before, 6).number, node(before, 6).anchor
        events.append(self.log, [
            ev(7, "pass.started", {"n": 3, "run": {"mode": "session"}, "instructions": []}, 3),
            ev(8, "section.replaced", {"section": sid(6), "title": "Le baptême", "body_md": "Baptisé à Besançon.",
                                       "reason": "l'acte nomme Besançon"}, 3),
            ev(9, "section.merged", {"sections": [sid(4)], "into": sid(3), "reason": "doublon"}, 3)])
        after = self.build()
        self.assertNotEqual(node(after, 6).number, number)   # one section less before it: renumbered
        self.assertEqual(node(after, 6).anchor, anchor)
        self.assertIn("Baptisé à Besançon.", after.resolved[sid(6)])
        self.assertEqual(sorted({r["pass"] for r in after.data["revisions"]}), [3])
        self.assertEqual(R.rule_v6(after)[0], "PASS")

    def test_persons_table_masks(self):
        md = R.to_markdown(self.build(), Translator("fr"))
        self.assertIn("| Personne vivante |", md)
        self.assertNotIn("Camille", md)
        self.assertIn("Victor HUGO", md)


class LivingQueries(ReportProject):
    def test_names_in_query(self):
        persons = FamilyIndexes(self.dir, "hugo").items("persons")
        self.assertEqual(names_in_query('"Camille Vernier" Metz', persons, today=TODAY), ["Camille VERNIER"])
        self.assertEqual(names_in_query("VERNIER Camille", persons, today=TODAY), ["Camille VERNIER"])
        self.assertEqual(names_in_query("Victor Hugo 1802", persons, today=TODAY), [])

    def test_search_warns(self):
        from probandia.cli import search_exec
        from probandia.cli.output import Result

        seen = {}

        def fake(ctx, research, pass_no, refuse_reuse=False):
            seen["refuse"] = refuse_reuse
            return Result("OK", {"RESULTS": 0})
        with mock.patch.object(search_exec, "_search", fake):
            code, out = self.call("search", "Camille Vernier Metz")
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("REASON=living-person-name", out)
        self.assertTrue(seen["refuse"])


class LanguageDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude")}

    def detect(self, **kw):
        from probandia.lang import detect

        kw.setdefault("environ", self.env)
        kw.setdefault("os_lookup", lambda: None)
        return detect.detect(**kw)

    def test_each_source_in_order(self):
        full = dict(arg="de", research="fr", setting="es", prompt="it")
        self.assertEqual(self.detect(**full), ("de", "arg"))
        full.pop("arg")
        self.assertEqual(self.detect(**full), ("fr", "research"))
        full.pop("research")
        self.assertEqual(self.detect(environ=dict(self.env, PROBANDIA_LANGUAGE="nl"), **full), ("nl", "env"))
        self.assertEqual(self.detect(environ=dict(self.env, PROBANDIA_LANG="pt-BR"), **full), ("pt-BR", "env"))
        self.assertEqual(self.detect(**full), ("es", "setting"))
        full.pop("setting")
        os.makedirs(self.env["CLAUDE_CONFIG_DIR"])
        with open(os.path.join(self.env["CLAUDE_CONFIG_DIR"], "settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"language": "Français"}, fh)
        self.assertEqual(self.detect(**full), ("fr", "harness"))
        os.remove(os.path.join(self.env["CLAUDE_CONFIG_DIR"], "settings.json"))
        self.assertEqual(self.detect(**full), ("it", "prompt"))
        self.assertEqual(self.detect(os_lookup=lambda: "ja"), ("ja", "os"))
        self.assertEqual(self.detect(), ("en", "default"))

    def test_session_language_and_order(self):
        from probandia.lang import detect

        project = os.path.join(self.tmp.name, "p")
        detect.remember_session_language(project, "fr_FR")
        self.assertEqual(self.detect(project=project), ("fr-FR", "prompt"))
        self.assertEqual(self.detect(arg="de", research="fr", order=["research", "arg"]), ("fr", "research"))

    def test_harness_mapping(self):
        from probandia.lang.detect import harness_value

        for text, tag in (("english", "en"), ("French", "fr"), ("français", "fr"), ("Deutsch", "de"),
                          ("español", "es"), ("japanese", "ja"), ("chinese", "zh"), ("klingon", None)):
            self.assertEqual(harness_value(text), tag, text)

    def test_os_sources(self):
        from probandia.lang import detect

        self.assertEqual(detect.os_language({"LANG": "de_DE.UTF-8"}, platform="linux"), "de-DE")
        self.assertEqual(detect.os_language({"LC_ALL": "C", "LANG": "fr_CA.UTF-8"}, platform="linux"), "fr-CA")
        self.assertIsNone(detect.os_language({"LANG": "POSIX"}, platform="linux"))
        with mock.patch.object(detect, "_windows_language", return_value="fr-FR"):
            self.assertEqual(detect.os_language({}, platform="win32"), "fr-FR")
        with mock.patch.object(detect, "_macos_language", return_value="pt-BR"):
            self.assertEqual(detect.os_language({}, platform="darwin"), "pt-BR")

    def test_windows_lookup(self):
        import locale

        from probandia.lang import detect

        fake = mock.MagicMock()
        fake.windll.kernel32.GetUserDefaultUILanguage.return_value = 0x040C
        with mock.patch.dict("sys.modules", {"ctypes": fake}):
            self.assertEqual(detect._windows_language(), detect.normalize(locale.windows_locale[0x040C]))

    def test_regional_fallback(self):
        t = Translator("fr-CA")
        self.assertFalse(t.missing)
        self.assertEqual(t("Contents"), "Sommaire")
        self.assertTrue(Translator("pt").missing)
        self.assertFalse(Translator("en-GB").missing)

    def test_new_research_records_its_language(self):
        from probandia.lang import detect
        from probandia.research import create_research

        tag, _source = self.detect(prompt="fr")
        project = os.path.join(self.tmp.name, "p")
        r = create_research(project, "hugo", "Qui étaient les parents de Victor ?", tag,
                            {"harness": "claude-code", "agent": "session"},
                            now=datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc))
        meta = r.meta()
        self.assertEqual(meta["language"], "fr")
        self.assertEqual(r.id, "2026-10-01-qui-etaient-les-parents-de-victor")
        self.assertEqual(detect.detect(research=meta["language"], environ=self.env)[0], "fr")

    def test_a_french_prompt_gives_a_french_research_on_an_english_machine(self):
        # PRD criterion 15: a French prompt and no setting. The engine cannot read the prompt: the agent
        # gives its language to `new`, and the research keeps it, whatever the machine speaks.
        from probandia.lang import detect

        folder = os.path.join(self.tmp.name, "p")
        os.makedirs(folder)
        env = dict(self.env, PROBANDIA_CONFIG_DIR=os.path.join(self.tmp.name, "u"),
                   PROBANDIA_DATA_DIR=os.path.join(self.tmp.name, "d"), PROBANDIA_SESSION="s")

        def call(*argv):
            out = io.StringIO()
            with mock.patch.object(detect, "os_language", return_value="en-US"):
                code = cli.main(list(argv), stdout=out, environ=env, cwd=folder, stdin=io.StringIO())
            return code, out.getvalue().splitlines()

        question = "Qui étaient les parents de Victor Hugo ?"
        code, lines = call("new", question, "--family", "hugo", "--no-pass", "--mode", "session")
        self.assertEqual(code, 0, lines)
        self.assertIn("LANG=en-US", lines)   # without the agent's word, the machine decides
        shutil.rmtree(folder)
        os.makedirs(folder)
        code, lines = call("new", question, "--family", "hugo", "--no-pass", "--mode", "session",
                           "--prompt-lang", "fr")
        self.assertEqual(code, 0, lines)
        self.assertIn("LANG=fr", lines)
        self.assertIn("LANG_SOURCE=prompt", lines)
        code, lines = call("render", "--formats", "md")   # nothing given again: the research remembers
        self.assertEqual(code, 0, lines)
        self.assertIn("LANG=fr", lines)
        self.assertIn("LANG_SOURCE=research", lines)
        md = glob.glob(os.path.join(folder, "families", "hugo", "research", "*", "report", "report.md"))
        with open(md[0], encoding="utf-8") as fh:
            self.assertIn("## Sommaire", fh.read())   # the labels follow the research
        # the interface stays in English: the research's language is the report's, not the engine's
        code, lines = call("--output-format", "human", "status")
        self.assertEqual(code, 0, lines)
        self.assertIn("Researches", lines)
        self.assertNotIn("Recherches", lines)

    def test_the_agent_is_told_to_give_the_prompt_language(self):
        # the engine reads --prompt-lang only: every copy of the `new` command says to give it, and the engine
        # skill no longer claims that the hooks keep the language for the session
        for path in ("commands/new.md", "cursor/commands/probandia-new.md"):
            with open(os.path.join(ROOT, *path.split("/")), encoding="utf-8") as fh:
                self.assertIn("--prompt-lang", fh.read(), path)
        with open(os.path.join(ROOT, "skills", "engine", "SKILL.md"), encoding="utf-8") as fh:
            engine = fh.read()
        self.assertIn("--prompt-lang", engine)
        self.assertNotIn("(language, report mode", engine)


class PseudoLocale(ReportProject):
    """Every label the engine writes into a report goes through the catalogue."""

    def test_rendered_labels_are_wrapped(self):
        import re

        from probandia.i18n import PSEUDO_CLOSE, PSEUDO_OPEN

        report = self.build(lang="xx")
        md = R.to_markdown(report, Translator("xx"))
        model_titles = {"Acte de naissance", "Le père présumé", "Détail", "Vérifications", "Index"}
        for line in md.splitlines():
            m = re.match(r"^#{2,4} (?:[0-9.IVXA-Za-z]+ )?(.*)$", line)
            if not m:
                continue
            title = m.group(1)
            if title in model_titles:
                continue  # written by the model, in the research's language
            label = title.split(" — ")[0]
            self.assertTrue(label.startswith(PSEUDO_OPEN) and label.endswith(PSEUDO_CLOSE), line)
        self.assertIn(f"{PSEUDO_OPEN}Living person{PSEUDO_CLOSE}", md)


class LabelsOnly(unittest.TestCase):
    """T70: a report in a language without labels had the model read and translate the engine's whole catalogue
    (some two thousand messages) for the hundred labels a report holds; now only those, by a small model."""

    def setUp(self):
        from tests.integration import test_sample_project as sample

        sample.Sample.setUp(self)
        self.rid = sample.RID

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env), cwd=self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        return next((line.split("=", 1)[1] for line in out.splitlines() if line.startswith(key + "=")), None)

    def write_po(self, target, entries):
        from probandia.i18n import quote_po

        path = os.path.join(self.dir, *target.split("/"))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            for msgid in entries:   # the fixture's translation: each label marked, its fields kept
                fh.write(f"msgid {quote_po(msgid)}\nmsgstr {quote_po('DE ' + msgid)}\n\n")

    def test_the_question_gives_the_labels_of_the_report_only(self):
        from probandia.i18n import read_po

        code, out = self.call("-l", "de", "render", self.rid)
        self.assertEqual(code, 3, out)
        self.assertIn("STATUS=ASK\n", out)
        self.assertIn("QUESTION=translate_labels\n", out)
        pot = self.value(out, "POT")
        self.assertEqual(pot, "locales/de/LC_MESSAGES/report-labels.pot")
        labels = read_po(os.path.join(self.dir, *pot.split("/")))
        self.assertLess(len(labels), 250)
        self.assertEqual(len(labels), int(self.value(out, "LABELS")))
        self.assertGreater(len(read_po(os.path.join(ROOT, "locales", "probandia.pot"))), 1500)   # the old POT=
        for label in ("Contents", "Sources", "proven by a record", "living person, masked"):   # the trees' legend
            self.assertIn(label, labels)
        self.assertNotIn("{date}", labels)   # nothing to translate
        self.assertNotIn("decennial_table", labels)   # a value of the data, not a label
        # the catalogue translated, the render succeeds in German
        target = self.value(out, "TARGET")
        self.assertEqual(target, "locales/de/LC_MESSAGES/probandia.po")
        self.write_po(target, labels)
        code, out = self.call("-l", "de", "render", self.rid, "--formats", "md,html")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=OK\n"), out)
        self.assertNotIn("LABELS_MISSING", out)
        report = os.path.join(self.dir, "families", "marchand", "research", self.rid, "report")
        with open(os.path.join(report, "report.md"), encoding="utf-8") as fh:
            self.assertIn("## DE Contents", fh.read())
        # a label the catalogue lacks, at a later render: that one only, without asking the user again
        self.write_po(target, [m for m in labels if m != "Sources"])
        code, out = self.call("-l", "de", "render", self.rid, "--formats", "md")
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=WARN\n", out)
        self.assertIn("LABELS_MISSING=1\n", out)
        self.assertEqual(list(read_po(os.path.join(self.dir, *self.value(out, "POT").split("/")))), ["Sources"])

    def test_the_report_skill_hands_it_to_the_harvester(self):
        with open(os.path.join(ROOT, "skills", "report", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("one `harvester` (Haiku, effort `low`) adds the `POT=`\n  entries to the `TARGET=` file", text)
        with open(os.path.join(ROOT, ".claude-plugin", "agents", "harvester.md"), encoding="utf-8") as fh:   # T267
            head = fh.read().split("---")[1]
        self.assertIn("model: haiku\neffort: low\n", head)
