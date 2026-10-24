"""Headless tests of the look of the application in a terminal (version-1.0.0 T94 to T96): the
snapshots of its screens in ``tests/golden/tui/``, its layout in 80 x 24, the theme it keeps,
titles that are sentences. Apart from ``test_tui_app``, so that the ``tui`` job runs them in a
process of their own. ``PROBANDIA_UPDATE_GOLDEN=1`` writes the snapshots again."""
import contextlib
import datetime
import os
import re
from unittest import mock

from probandia import i18n
from tests import ROOT
from tests.unit.test_human import golden
from tests.unit.test_tui_app import AppCase, propose

SNAPSHOTS = os.path.join(ROOT, "tests", "golden", "tui")
NOW = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.timezone.utc)
# What draws a frame, a bar or an arrow: box drawing, blocks, geometric shapes, Textual's icon
FRAMES = re.compile("[─-◿⭘]")


@contextlib.contextmanager
def stopped_clocks():
    """The clocks the screens read, stopped at ``NOW``: a snapshot does not change with the day."""
    from probandia import doctor
    from probandia.cli import providers_cmd, usage_cmd, views
    from probandia.util import fs

    ages = doctor.catalogue_ages
    with mock.patch.object(views, "_now", lambda: NOW), mock.patch.object(usage_cmd, "_now", lambda: NOW), \
            mock.patch.object(providers_cmd, "_today", lambda: NOW.date()), \
            mock.patch.object(fs, "utc_now", lambda: NOW), \
            mock.patch.object(doctor, "catalogue_ages", lambda path=None, today=None: ages(path, today or NOW.date())):
        yield


class Look(AppCase):
    """T94: the screens as they look, in 80 x 24 and 140 x 45; nothing out of the screen; the
    theme kept from one launch to the next; titles that say things, not the contract's keys."""

    def language(self, lang):
        i18n.activate(lang)
        self.addCleanup(i18n.activate, "en")

    async def snapshots(self, size, names, *argv, suffix=""):
        """Each screen of ``names`` shown in turn in one application, as an SVG compared with
        ``tests/golden/tui/<name><suffix>-<w>x<h>.svg``, the project's path written ``<projet>``."""
        app = self.app(*argv)
        app.animation_level = "none"
        with stopped_clocks():
            async with app.run_test(size=size) as pilot:
                await self.settle(pilot)
                app.title = app.title.replace(self.dir, "<projet>")
                for name in names:
                    app.show(name)
                    await self.settle(pilot)
                    await self.calm(pilot)
                    svg = app.export_screenshot(simplify=True)
                    self.assertNotIn(self.dir, svg)
                    if "--plain" in argv:   # T96: frames in ASCII, or none
                        self.assertIsNone(FRAMES.search(svg), FRAMES.findall(svg)[:10])
                    golden(self, f"{name}{suffix}-{size[0]}x{size[1]}", svg, SNAPSHOTS, ".svg")

    async def test_snapshots(self):
        from probandia.cli.tui_app import SCREENS

        for size in ((80, 24), (140, 45)):
            await self.snapshots(size, [name for name, _title in SCREENS])
        self.env["PROBANDIA_TUI_THEME"] = "light"   # the setting the t key writes
        await self.snapshots((80, 24), ["home"], suffix="-light")
        del self.env["PROBANDIA_TUI_THEME"]
        await self.snapshots((80, 24), ["home"], "--plain", suffix="-plain")
        self.language("fr")
        await self.snapshots((80, 24), ["home"], "--lang", "fr", suffix="-fr")

    async def test_no_color_keeps_the_meaning(self):
        """T96: with ``--no-color``, every screen is in shades of grey, and what colour said
        is said otherwise: each status shown is a word or a sign, the tab shown and the line
        under the cursor are in reverse video."""
        from textual.widgets import DataTable

        from probandia.cli.tui_app import PANES

        app = self.app("--no-color")
        async with app.run_test(size=self.SIZE) as pilot:
            for name in PANES:
                app.show(name)
                await self.settle(pilot)
                drawn = "\n".join(x for x in app.export_screenshot().splitlines() if "<circle" not in x)
                # the window's three dots and the default text colour of Rich's SVG left out
                colours = set(re.findall(r"#([0-9a-f]{6})\b", drawn)) - {"c5c8c6"}
                self.assertTrue(colours and all(c[:2] == c[2:4] == c[4:] for c in colours), (name, colours))
                tab = app.screen.query_one("#screens").query_one("Tab.-active")
                self.assertTrue(tab.rich_style.reverse, name)
                for pane in app.shown():
                    for table in pane.query(DataTable):
                        self.assertTrue(table.get_component_rich_style("datatable--cursor").reverse)
                        fields = [c.value for c in table.columns]
                        for i in range(table.row_count):
                            for field, value in zip(fields, table.get_row_at(i)):
                                if field in ("status", "state", "verdict", "present", "installed", "reason"):
                                    self.assertRegex(str(value), r"\w|[✓✗⚠?■—]", (name, field))

    async def test_nothing_overflows_80x24(self):
        """In 80 x 24, the widgets of the screen hold in it, and the main widget of each screen,
        its part or its file's tab, starts within it."""
        from probandia.cli.tui_app import PANES

        app = self.app()
        async with app.run_test(size=(80, 24)) as pilot:
            whole = app.screen.region
            for name in PANES:
                app.show(name)
                await self.settle(pilot)
                for widget in app.screen.children:
                    self.assertTrue(whole.contains_region(widget.region), (name, widget, widget.region))
                for pane in app.shown():
                    self.assertTrue(whole.contains_region(pane.region), (name, pane.region))
                    main = pane.main().region
                    self.assertTrue(whole.contains(main.x, main.y), (name, pane.id, main))

    async def test_the_theme_is_remembered(self):
        """t changes the theme, and the engine keeps it in the user's settings: the next
        application starts with it."""
        seen = []
        for launch in range(2):
            app = self.app()
            async with app.run_test(size=self.SIZE) as pilot:
                await self.settle(pilot)
                seen.append(app.theme)
                if not launch:
                    await pilot.press("t")
                    await self.settle(pilot)
                    seen.append(app.theme)
        self.assertEqual(seen, ["probandia", "probandia-light", "probandia-light"])
        with open(os.path.join(self.env["PROBANDIA_CONFIG_DIR"], "config.toml"), encoding="utf-8") as fh:
            self.assertIn('theme = "light"', fh.read())

    async def test_titles_are_sentences(self):
        """In French, no title of a screen holds a key of the contract its commands answered:
        neither in capitals, nor as ``key=value``, nor in small letters before its value, as the
        titles of the tables did (``providers 22 · ready 2``)."""
        from textual.widgets import Static

        from probandia.cli import human
        from probandia.cli.tui_app import PANES

        propose(self)   # a proposal to read
        self.language("fr")
        app = self.app("--lang", "fr")
        answered, answer = [], app.answer

        def spy(*argv):
            d = answer(*argv)
            answered.append(d)
            return d

        titles = []
        with mock.patch.object(app, "answer", spy):
            async with app.run_test(size=self.SIZE) as pilot:
                for name in PANES:
                    app.show(name)
                    await self.settle(pilot)
                    for pane in app.shown():
                        titles += [(name, self.text(w)) for w in pane.query(Static)
                                   if w.has_class("title") or (w.id or "").endswith("-head")]
        values = {(k, v) for d in answered for k, v in (d.get("values") or {}).items()}
        self.assertTrue({"RESEARCH_STATUS", "VERDICT", "PROVIDERS", "GRADE"} <= {k for k, _v in values})
        for name, text in titles:
            for key, value in values:
                self.assertIsNone(re.search(rf"\b{key}\b", text), (name, key, text))
                self.assertNotIn(f"{key.lower()}=", text, (name, text))
                self.assertNotIn(f"{human.humanize(key)} {value}", text, (name, text))


# T95: what a cell never shows. The fields of identifiers (a research, a source, a variable...)
# and of free text (a summary, a question, a message...) say what their files say.
IDENTIFIERS = {"research", "proposal", "person", "source", "command", "hypothesis", "search", "scope", "provider",
               "variable", "fingerprint", "key", "tool", "script", "rule", "role", "archive", "reference", "family",
               "place", "author", "unlocks", "holder", "from", "to", "fact", "how", "option"}
FREE_TEXT = {"summary", "what", "question", "body", "query", "help", "purpose", "why", "remedy", "install", "alert",
             "citation", "value", "default", "name", "window", "account"}
ENGLISH = {"open", "paused", "closed", "ready", "no-key", "card-required", "content-reuse", "not-enabled",
           "exhausted", "expired", "held", "valid", "due", "yes", "no", "true", "false", "none", "(unset)", "default",
           "user", "project", "environment", "record", "birth", "death", "marriage", "baptism", "burial", "father",
           "mother", "child", "spouse", "exact", "variant", "would-apply", "would-reject", "search", "read",
           "extract", "searches", "credits", "requests", "tokens", "pass", "fail", "warn", "passed", "failed", "task",
           "destroyed", "missing", "draft", "tested", "trusted", "essential", "advanced", "never", "request",
           "credit", "token", "dollar"}
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class Clear(AppCase):
    """T95: no raw value on any screen, in French: no Python list, no ``key=value``, no
    date as the files write it, no word of the engine's vocabularies left in English."""

    def setUp(self):
        super().setUp()
        import io

        from probandia import cli
        from tests.unit.test_tui_app import RID

        self.rid = RID
        propose(self)
        agent = dict(self.env, CLAUDECODE="1", PROBANDIA_SESSION="agent-session")
        for argv, env in ((["verify", RID], self.env), (["lock", "take", "family:marchand"], agent),
                          (["team", "send", RID, "--to", "researcher", "--from", "orchestrator", "--body", "look"],
                           self.env)):
            cli.main(argv, stdout=io.StringIO(), environ=env, cwd=self.dir)
        self.env["SERPER_API_KEY"] = "fixture-secret-0123456789"
        i18n.activate("fr")   # after the commands above, which set the language of their own
        self.addCleanup(i18n.activate, "en")

    def seen(self, app):
        """[(field or None, text)] of the panes shown: their cells, their titles and heads,
        and the labels of the tree."""
        from textual.widgets import DataTable, Static, Tree

        out = []
        for pane in app.shown():
            for table in pane.query(DataTable):
                fields = [c.value for c in table.columns]
                out += [(f, str(v)) for i in range(table.row_count) for f, v in zip(fields, table.get_row_at(i))]
            out += [(None, self.text(w)) for w in pane.query(Static)
                    if w.has_class("title") or (w.id or "").endswith("-head")]
            for tree in pane.query(Tree):
                out += [(None, str(node.label)) for node in tree.root.children]
        return out

    async def test_no_raw_value_on_screen(self):
        from probandia.cli.tui_app import PANES

        app = self.app("--lang", "fr")
        async with app.run_test(size=self.SIZE) as pilot:
            seen = []
            for name in PANES:
                app.show(name)
                await self.settle(pilot)
                seen += [(name, *x) for x in self.seen(app)]
            fields = {f for _n, f, _t in seen}
            self.assertTrue({"status", "state", "verdict", "unit", "type", "relation", "match", "renews"} & fields)
            for name, field, text in seen:
                where = (name, field, text)
                self.assertNotIn("['", text, where)
                self.assertNotIn("{'", text, where)
                self.assertIsNone(re.search(r"\b[a-z]+:\d", text), where)   # about:1896
                if field in IDENTIFIERS | FREE_TEXT:
                    continue
                self.assertNotIn("=", text, where)
                self.assertIsNone(ISO_DATE.search(text.replace(self.rid, "<research>")), where)
                if field:
                    self.assertNotIn(text.strip().lower(), ENGLISH, where)

            await pilot.press("ctrl+p")   # the palette: Probandia's commands, none of Textual's
            await pilot.pause(0.3)
            from textual.command import CommandList

            listed = app.screen.query_one(CommandList)
            prompts = [str(listed.get_option_at_index(i).prompt) for i in range(listed.option_count)]
            self.assertTrue(prompts and all(p.startswith(("Aller à", "Console")) for p in prompts), prompts)
            await pilot.press("escape")
