"""Headless tests of the Probandia application in a terminal (CLI15), on a copy of
the sample project: ``App.run_test()`` and its pilot, without a screen."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

from probandia import cli, i18n
from tests import ROOT

try:
    import textual
    from textual.widgets import Static
except ImportError:
    textual = None

RID = "2026-09-01-ancestors-of-louis-marchand"


def context(project, environ, *argv):
    """The Context ``probandia tui`` hands the application."""
    args = cli.build_parser().parse_args([*argv, "tui"])
    for k, v in cli.GLOBAL_DEFAULTS.items():
        if not hasattr(args, k):
            setattr(args, k, v)
    return cli.Context(args, environ, project)


@unittest.skipUnless(textual, "requires the tui extra")
class AppCase(unittest.IsolatedAsyncioTestCase):
    SIZE = (140, 45)

    def _setupAsyncioRunner(self):
        import _socket
        import asyncio

        def loop_factory():
            # Windows constructs asyncio's internal wakeup socket on loopback.
            with mock.patch("socket.socket.connect", _socket.socket.connect):
                return asyncio.new_event_loop()

        self._asyncioRunner = asyncio.Runner(debug=False, loop_factory=loop_factory)

    handling = [0]   # the messages whose handler has not returned yet, every widget together (``quiet``)

    def setUp(self):
        from textual.message_pump import MessagePump

        dispatch = MessagePump._dispatch_message

        async def counted(pump, message):
            AppCase.handling[0] += 1
            try:
                await dispatch(pump, message)
            finally:
                AppCase.handling[0] -= 1

        AppCase.handling[0] = 0
        patcher = mock.patch.object(MessagePump, "_dispatch_message", counted)
        patcher.start()
        self.addCleanup(patcher.stop)
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"),
                    "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"), "PROBANDIA_PAGER": "none"}

    def app(self, *argv, cwd=None):
        from probandia.cli.tui_app import make_app

        app = make_app(context(cwd or self.dir, self.env, *argv))
        self.addAsyncCleanup(self.drain, app)   # before the copy of the project is removed
        return app

    @staticmethod
    async def drain(app):
        """Waits for a read still running in its thread: nothing holds a file of the copy
        when it is removed."""
        import asyncio

        for lock in (app.lock, app.file_lock):
            await asyncio.to_thread(lock.acquire)
            lock.release()

    async def settle(self, pilot):
        """Pauses until no read nor action is under way and what they read is shown: the
        screens read in threads (T88), and a read shown may start another."""
        app = pilot.app
        for _turn in range(1000):
            await pilot.pause()
            if not app.busy() and self.quiet(app):
                await pilot.pause()
                if not app.busy() and self.quiet(app):
                    return
        self.fail("the reads never ended")

    @staticmethod
    def quiet(app):
        """Every widget of the screens mounted, and no message waiting nor under way in them or in
        the application: a key pressed, a button pressed, a screen pushed have had all their effects.
        A paused loop alone does not tell it under load: a chain of messages may still be going."""
        nodes = [app, *(n for screen in app.screen_stack for n in screen.walk_children(with_self=True))]
        # private to Textual 8, read only; the messages under way are counted by setUp's wrapper
        return not AppCase.handling[0] and all(
            n._is_mounted and not n._next_callbacks and n._pending_message is None and n._message_queue.empty()
            for n in nodes)

    async def calm(self, pilot):
        """Pauses until the application is quiet (``quiet``), a read in a thread or a command
        waiting for an answer left running: what a key or a button does in the loop is done."""
        await self.until(pilot, lambda: True, tries=2000)

    @staticmethod
    def text(widget):
        return str(widget.content)

    async def until(self, pilot, condition, tries=200):
        """Pauses until ``condition()`` holds and the application is quiet: what a chain of messages
        builds (a form, a screen and its fields) is there after a number of turns of the loop, never
        after a fixed time, and a screen pushed is mounted before it is read."""
        for _turn in range(tries):
            try:
                if self.quiet(pilot.app) and condition():
                    return
            except Exception:   # not built yet: NoMatches, an attribute still None
                pass
            await pilot.pause()
        self.assertTrue(self.quiet(pilot.app), "the application never went quiet")
        self.assertTrue(condition())

    async def asked(self, pilot):
        """Pauses until the question of an action is shown: a button's message goes up through
        the tabs and the panes before the application asks."""
        await self.until(pilot, lambda: type(pilot.app.screen).__name__ == "ConfirmScreen")

    def event(self, research=RID):
        """An event added to the log of ``research``, as an agent adds one."""
        from probandia import events

        path = os.path.join(self.dir, "families", "marchand", "research", research, "events.jsonl")
        events.append(path, [events.make("instruction.added", {"text": "look at the census first"},
                                         {"harness": "cli", "agent": "session"}, 2)])

    def table(self, app, selector):
        """The cells of a DataTable, row by row."""
        from textual.widgets import DataTable

        t = app.screen.query_one(selector, DataTable)
        return [[str(c) for c in t.get_row_at(i)] for i in range(t.row_count)]


class Skeleton(AppCase):
    """CLI15-T1: the screens and their keys, the palette, the help, the theme, the refresh."""

    async def test_every_screen_has_its_key(self):
        """T92: the six screens of decision T6 and Help, each by its key and without the palette, its
        tab beginning with that key; the help shows the keys of the bindings, and nothing
        else; ``/`` reaches the filter of every screen that shows a list."""
        from textual.widgets import DataTable, Input, TabbedContent

        from probandia.cli import tui_app

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            tabs = app.screen.query_one("#screens", TabbedContent)
            self.assertEqual([name for name, _title in tui_app.SCREENS],
                             ["home", "quotas", "researches", "family", "proposals", "config", "help"])
            for n, (name, _title) in reversed(list(enumerate(tui_app.SCREENS, 1))):
                await pilot.press(str(n))
                await self.calm(pilot)
                self.assertEqual(tabs.active, name)
                self.assertTrue(str(tabs.get_tab(name).label).startswith(f"{n} "), tabs.get_tab(name).label)
            await pilot.press("2")
            for key, part in (("right_square_bracket", "providers"), ("left_square_bracket", "quotas")):
                await pilot.press(key)   # the parts of a screen
                await self.calm(pilot)
                self.assertEqual(app.shown()[0].id, f"pane-{part}")

            await pilot.press("question_mark")
            await self.calm(pilot)
            shown = self.table(app, "#help-keys")
            self.assertIn("ctrl+p", [b.key for b in type(app).BINDINGS])   # the palette, in words of its own
            self.assertEqual(sorted(x for row in shown for x in row[::2] if x),
                             sorted(app.get_key_display(b) for b in type(app).BINDINGS))
            await pilot.press("escape")
            await self.calm(pilot)

            for name in tui_app.PANES:
                app.show(name)
                await self.settle(pilot)
                if not any(p.query(DataTable) for p in app.shown()):
                    continue   # the report: a document, not a list
                app.set_focus(None)
                await pilot.press("slash")
                self.assertIsInstance(app.focused, Input, name)
                self.assertEqual(app.focused.id, "filter", name)

    async def test_keys_after_the_filter(self):
        """T93: Escape leaves a field; out of the fields the keys of the screens work, and the
        focus is put on the main widget of each screen shown, never in a hidden one; j, k, g
        and G move the line; Enter opens the file of a research, Backspace comes back."""
        from textual.widgets import DataTable, Input, TabbedContent, Tree

        from probandia.cli.tui_app import displayed

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            tabs = app.screen.query_one("#screens", TabbedContent)

            async def press(*keys):
                await pilot.press(*keys)
                await self.settle(pilot)
                self.assertTrue(app.focused is None or displayed(app.focused), (keys, app.focused))

            await self.settle(pilot)
            self.assertEqual(app.focused.id, "home-researches")
            await press("2")
            self.assertEqual(app.focused.id, "quotas-accounts")
            await press("slash", *"abc", "escape", "3")
            self.assertEqual((tabs.active, app.focused.id), ("researches", "researches-list"))
            self.assertEqual(app.pane("quotas").word(), "abc")   # typed in the filter, not taken as keys
            await press("slash", "tab", "2")
            self.assertEqual(tabs.active, "quotas")
            app.pane("quotas").query_one("#filter", Input).value = ""
            await press("4")
            self.assertIsInstance(app.focused, Tree)
            await press("2")
            self.assertEqual(tabs.active, "quotas")

            table = app.focused
            self.assertIsInstance(table, DataTable)
            for key, row in (("j", 1), ("j", 2), ("k", 1), ("G", table.row_count - 1), ("g", 0)):
                await press(key)
                self.assertEqual(table.cursor_row, row, key)

            await press("3", "enter")   # the file of the research
            self.assertEqual(app.focused.id, "research-passes")
            await press("backspace")
            self.assertEqual(app.focused.id, "researches-list")
            await press("right_square_bracket")   # its report: the focus in it
            self.assertIn(app.pane("report"), app.focused.ancestors_with_self)
            await press("backspace")
            self.assertEqual(app.focused.id, "researches-list")

    async def test_palette_help_and_theme(self):
        from textual.widgets import TabbedContent

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("ctrl+p")
            await self.calm(pilot)
            await pilot.press(*"Go to Library")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await self.calm(pilot)
            self.assertEqual(app.screen.query_one("#screens", TabbedContent).active, "config")
            self.assertEqual([p.id for p in app.shown()], ["pane-library"])
            await pilot.press("question_mark")
            await self.calm(pilot)
            self.assertEqual(type(app.screen).__name__, "HelpScreen")
            await pilot.press("escape")
            theme = app.theme
            await pilot.press("t")
            self.assertNotEqual(app.theme, theme)

    async def test_a_watched_file_refreshes_the_screen(self):
        from probandia.cli import board_cmd

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            with mock.patch.object(board_cmd, "welcome", wraps=board_cmd.welcome) as board:
                app.tick()
                await self.settle(pilot)
                board.assert_not_called()   # nothing changed: nothing is read
                self.event()
                app.tick()
                await self.settle(pilot)
                board.assert_called_once()

    async def test_a_tick_on_a_screen_being_built_or_taken_down(self):
        from textual.css.query import NoMatches

        from probandia.cli import board_cmd, tui_app

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            self.event()

            def gone(pane, **_kw):
                raise NoMatches("No nodes match '.title'")
            with mock.patch.object(tui_app.Pane, "refresh_data", gone):
                app.tick()   # seen on a loaded machine: the timer fires while the panes are taken down
            from textual.widgets import TabbedContent

            with mock.patch.object(TabbedContent, "active_pane", new_callable=mock.PropertyMock, return_value=None):
                app.tick()   # seen on a loaded machine too: the tabs being built show no pane yet
                app.action_part(1)
            self.assertTrue(app.is_running)
            with mock.patch.object(board_cmd, "welcome", wraps=board_cmd.welcome) as board:
                app.tick()   # the next tick reads the screen again
                await self.settle(pilot)
                board.assert_called_once()

    async def test_outside_a_project(self):
        app = self.app(cwd=self.tmp.name)
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.calm(pilot)
            self.assertIn("Not in a project", self.text(app.screen.query_one("#pane-researches .title")))



class HomeAndQuotas(AppCase):
    """CLI15-T2: the data of board and of usage."""

    async def test_home_shows_the_board(self):
        from probandia.cli import board_cmd

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            b = board_cmd.welcome(app.ctx).extra
            rows = self.table(app, "#home-researches")
            self.assertEqual([r[0] for r in rows], [x["research"] for x in b["researches"]])
            self.assertEqual([r[0] for r in self.table(app, "#home-accounts")], [a["name"] for a in b["accounts"]])
            self.assertEqual(len(self.table(app, "#home-next")), len(b["next"]))
            self.assertIn("1 family · 1 research · ",self.text(app.screen.query_one("#pane-home .title")))

    async def test_quotas_show_usage_filter_and_sync(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("2")
            await self.settle(pilot)
            usage = app.engine("usage")["data"]["accounts"]
            rows = self.table(app, "#quotas-accounts")
            self.assertEqual([r[0] for r in rows], [a["name"] for a in usage])
            await pilot.press("slash")
            await pilot.press(*"serpapi")
            await self.calm(pilot)
            self.assertEqual([r[0] for r in self.table(app, "#quotas-accounts")],
                             [a["name"] for a in usage if "serpapi" in (a["account"] + a["name"]).lower()])
            with mock.patch.object(app, "engine", wraps=app.engine) as engine:
                app.action_sync()
                await self.settle(pilot)
                engine.assert_called_with("usage", "--sync")


class ResearchesAndReport(AppCase):
    """CLI15-T3: the list and the file of a research, its log as it grows, its report."""

    async def test_list_file_and_live_log(self):
        from probandia import events

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.settle(pilot)
            self.assertEqual([r[0] for r in self.table(app, "#researches-list")], [RID])
            self.assertIn("Who were the ancestors of Louis MARCHAND?",
                          self.text(app.screen.query_one("#research-head")))
            self.assertEqual([r[0] for r in self.table(app, "#research-passes")], ["1", "2"])
            log = self.table(app, "#research-log")
            self.assertEqual((len(log), log[-1][2]), (28, "pass closed"))
            path = os.path.join(self.dir, "families", "marchand", "research", RID, "events.jsonl")
            events.append(path, [events.make("instruction.added", {"text": "search Les Ormes first"},
                                             {"harness": "cli", "agent": "session"}, 2)])
            app.tick()   # the look at the watched files, once a second
            await self.settle(pilot)
            log = self.table(app, "#research-log")
            self.assertEqual(len(log), 29)
            self.assertEqual(log[-1][2:], ["instruction", "search Les Ormes first"])

    async def test_filter(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await pilot.press("slash", *"closed")
            await self.settle(pilot)
            self.assertEqual(self.table(app, "#researches-list"), [])

    async def test_report_rendered(self):
        import markdown_it
        from textual.widgets import MarkdownViewer

        from probandia import _vendor

        # Textual's Markdown parses with the copy the engine vendors, first on sys.path
        self.assertEqual(os.path.dirname(os.path.dirname(markdown_it.__file__)), _vendor.VENDOR_DIR)
        self.assertEqual(cli.main(["render", RID], stdout=__import__("io").StringIO(), environ=self.env,
                                  cwd=self.dir), 0)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("report")
            viewer = app.screen.query_one("#report-viewer", MarkdownViewer)

            def headings():
                return " ".join(str(label) for _level, label, _id in viewer.table_of_contents.table_of_contents or [])
            await self.until(pilot, lambda: "Les parents de Louis" in headings())
            with mock.patch("webbrowser.open") as browser:
                await pilot.press("o")
            self.assertTrue(browser.call_args.args[0].endswith("report/report.html"))

    async def test_no_report_yet(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("report")
            await self.settle(pilot)
            self.assertIn("No report yet", self.text(app.screen.query_one("#pane-report .title")))


PROPOSAL = "01JB0000000000000000000P01"


def propose(case, pass_no=2, **changes):
    """A proposal of the test, stored by ``propose`` as a researcher would."""
    import io

    from probandia.util import yamlio

    doc = {"schema": 1, "id": PROPOSAL, "research": RID, "pass": pass_no,
           "author": {"harness": "claude-code", "agent": "researcher"},
           "facts": [{"id": "louise-perrin-1818.death", "type": "death",
                      "date": {"value": "1880", "qualifier": "exact"}, "status": "index",
                      "source": "src-01JA0000000000000000000005"}]}
    doc.update(changes)
    path = os.path.join(case.tmp.name, "proposal.yaml")
    yamlio.dump(path, doc)
    out = io.StringIO()
    case.assertEqual(cli.main(["propose", RID, path, "--agent", "researcher"], stdout=out, environ=case.env,
                              cwd=case.dir), 0, out.getvalue())


def persons_file(case):
    return os.path.join(case.dir, "families", "marchand", "index", "persons.yaml")


class FamilyAndProposals(AppCase):
    """CLI15-T4: the Sosa tree and a person's file; the review of the proposals."""

    async def test_sosa_tree_and_person(self):
        from textual.widgets import Tree

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("4")
            await self.settle(pilot)
            tree = app.screen.query_one("#family-tree", Tree)
            first = tree.root.children[0]
            self.assertEqual(str(first.label), "1  Louis MARCHAND (1898-1970)")
            self.assertEqual([str(n.label) for n in first.children],
                             ["2  Henri MARCHAND (1870-1931)", "3  Jeanne ROUSSEL (1874-1950)"])
            self.assertEqual(str(first.children[0].children[0].label)[:3], "4  ")
            tree.move_cursor(first.children[0])
            await self.settle(pilot)
            self.assertIn("henri-marchand-1870", self.text(app.screen.query_one("#person-head")))
            self.assertEqual([r[0] for r in self.table(app, "#person-facts")], ["birth", "death", "marriage"])

    async def test_find_a_person(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("4", "slash", *"Marchant", "enter")
            await self.settle(pilot)
            found = self.table(app, "#family-found")
            self.assertEqual(len(found), 5)
            self.assertTrue(all(r[4] == "variant" for r in found))

    async def test_living_persons_are_masked(self):
        from textual.widgets import Tree

        from probandia.util import yamlio

        doc = yamlio.load(persons_file(self))
        doc["persons"][0]["living"] = True
        yamlio.dump(persons_file(self), doc)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("4")
            await self.settle(pilot)
            first = app.screen.query_one("#family-tree", Tree).root.children[0]
            self.assertEqual(str(first.label), "1  Living person")
            self.assertIn("Living person", self.text(app.screen.query_one("#person-head")))
            self.assertEqual(self.table(app, "#person-facts"), [])
            tree = app.screen.query_one("#family-tree", Tree)
            tree.move_cursor(first.children[0])
            await self.settle(pilot)
            self.assertIn(["child", "louis-marchand-1898", "Living person"], self.table(app, "#person-relatives"))

    async def test_a_proposal_is_read_then_applied(self):
        from probandia.util import yamlio

        propose(self)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("5")
            await self.settle(pilot)
            self.assertEqual([r[0] for r in self.table(app, "#proposals-list")], [PROPOSAL])
            self.assertEqual([r[0] for r in self.table(app, "#proposal-facts")], ["louise-perrin-1818.death"])
            self.assertIn("every rule of apply passes", self.text(app.screen.query_one("#proposal-head")))
            await pilot.click("#proposal-apply")
            await self.asked(pilot)
            self.assertEqual(type(app.screen).__name__, "ConfirmScreen")
            await pilot.press("y")
            await self.settle(pilot)
            # the list is read again after the command's thread: a turn or more after the settle, under load
            await self.until(pilot, lambda: self.table(app, "#proposals-list") == [], tries=2000)
        louise = next(p for p in yamlio.load(persons_file(self))["persons"] if p["id"] == "louise-perrin-1818")
        self.assertIn("louise-perrin-1818.death", [f["id"] for f in louise["facts"]])

    async def test_a_proposal_set_aside_needs_a_reason(self):
        propose(self)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("5")
            await self.settle(pilot)
            for reason in ("", "a duplicate"):
                app.screen.query_one("#proposal-drop").press()   # the notice may cover the button
                await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                await pilot.press(*reason, "enter")
                await self.calm(pilot)
            await self.asked(pilot)   # asked once: the first time, no reason
            await pilot.press("y")
            await self.settle(pilot)
            await self.until(pilot, lambda: self.table(app, "#proposals-list") == [], tries=2000)


class OtherScreens(AppCase):
    """CLI15-T5: Providers and keys, Configuration, Library, Diagnostic and Team."""

    async def screen(self, app, pilot, name):
        app.show(name)
        await self.settle(pilot)

    async def test_providers_and_keys(self):
        self.env["SERPER_API_KEY"] = "fixture-secret-0123456789"
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.screen(app, pilot, "providers")
            providers = app.engine("providers", "list")["data"]["providers"]
            self.assertEqual([r[0] for r in self.table(app, "#providers-list")], [x["provider"] for x in providers])
            keys = self.table(app, "#providers-keys")
            serper = next(r for r in keys if r[0] == "SERPER_API_KEY")
            self.assertEqual(serper[1], "yes")
            self.assertRegex(serper[3], "^[0-9a-f]{8}$")   # a fingerprint, never the key
            self.assertNotIn("fixture-secret", repr(keys))

    async def test_configuration(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.screen(app, pilot, "config")
            rows = self.table(app, "#config-settings")
            self.assertEqual(len(rows), app.engine("config", "show", "--all")["values"]["COUNT"])
            self.assertIn("report.mode", [r[0] for r in rows])
            self.assertIn("Settings of the essential grade", self.text(app.screen.query_one("#pane-config .title")))

    async def test_library(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.screen(app, pilot, "library")
            self.assertEqual(len(self.table(app, "#library-scripts")),
                             len(app.engine("library", "list")["data"]["scripts"]))
            self.assertIn("nothing in the library yet", self.text(app.screen.query_one("#pane-library .title")))

    async def test_diagnostic_releases_an_expired_lock_only(self):
        import io
        import json

        agent = dict(self.env, CLAUDECODE="1", PROBANDIA_SESSION="agent-session")
        cli.main(["lock", "take", f"research:{RID}"], stdout=io.StringIO(), environ=agent, cwd=self.dir)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.screen(app, pilot, "diagnostic")
            self.assertEqual([r[0] for r in self.table(app, "#doctor-tools")],
                             [x["tool"] for x in app.engine("doctor")["data"]["tools"]])
            self.assertEqual(self.table(app, "#diagnostic-locks")[0][:2], [f"research-{RID}", "held"])
            app.screen.query_one("#lock-release").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.settle(pilot)
            self.assertEqual(self.table(app, "#diagnostic-locks")[0][1], "held")   # a live lock stays
            path = os.path.join(self.dir, ".probandia", "locks", f"research-{RID}.json")
            with open(path, encoding="utf-8") as fh:
                info = json.load(fh)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(dict(info, expires="2026-01-01T00:00:00Z"), fh)
            app.refresh_screen()
            await self.settle(pilot)
            app.screen.query_one("#lock-release").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.settle(pilot)
            self.assertEqual(self.table(app, "#diagnostic-locks"), [])

    async def test_team_reads_without_consuming(self):
        import io

        out = io.StringIO()
        cli.main(["team", "send", RID, "--to", "researcher", "--from", "orchestrator", "--body", "look at 1818"],
                 stdout=out, environ=self.env, cwd=self.dir)
        self.assertIn("STATUS=OK", out.getvalue())
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.screen(app, pilot, "team")
            self.assertEqual([r[1:] for r in self.table(app, "#team-messages")],
                             [["orchestrator", "researcher", "task", "look at 1818"]])
            self.assertIn("40 native searches left", self.text(app.screen.query_one("#pane-team .title")))
        out = io.StringIO()
        cli.main(["team", "inbox", RID, "--agent", "researcher"], stdout=out, environ=self.env, cwd=self.dir)
        self.assertIn("look at 1818", out.getvalue())   # still unread


class Themes(AppCase):
    """T94: Config, Themes: the themes listed, a theme of one's own made, saved, used and deleted from
    the form, each through the engine once confirmed; its sample drawn as it is typed."""

    async def test_a_theme_made_saved_used_and_deleted(self):
        from textual.widgets import Input

        from probandia.config import themes

        app = self.app()
        self.assertTrue(app.has_class("-compact-buttons") and app.has_class("-section-titles"))
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("themes")
            await self.settle(pilot)
            self.assertEqual([r[0] for r in self.table(app, "#themes-list")], ["dark", "light"])
            self.assertIn("2 themes · in use: dark", self.text(app.screen.query_one("#pane-themes .title")))
            self.assertEqual(app.screen.query_one("#theme-name", Input).value, "dark")
            primary = app.screen.query_one("#theme-color-primary", Input)
            self.assertEqual(primary.value, themes.PALETTES["dark"]["primary"])

            pane = app.pane("themes")
            pane.pressed("theme-new")
            await self.calm(pilot)
            self.assertEqual(app.screen.query_one("#theme-name", Input).value, "theme-1")
            primary.value = "#12345"
            await self.calm(pilot)
            self.assertTrue(primary.has_class("-invalid"))
            pane.pressed("theme-save")   # a wrong colour: nothing asked, nothing written
            await self.calm(pilot)
            self.assertIn("To correct first: Main", self.text(app.screen.query_one("#theme-note")))
            primary.value = "#123456"
            await self.calm(pilot)
            self.assertFalse(primary.has_class("-invalid"))
            self.assertEqual(str(app.screen.query_one("#theme-swatch-primary").styles.background.hex), "#123456")
            app.screen.query_one("#theme-layout-buttons").value = "tall"
            await self.calm(pilot)
            self.assertEqual(pane.edited["layout"]["buttons"], "tall")
            self.assertEqual(app.theme_name, "dark")   # the form changes nothing of the application

            app.screen.query_one("#theme-save").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.settle(pilot)
            found, problems = themes.load(self.env)
            self.assertEqual(problems, {})
            self.assertEqual(found["theme-1"]["colors"]["primary"], "#123456")
            self.assertEqual(found["theme-1"]["layout"]["buttons"], "tall")
            self.assertEqual([r[0] for r in self.table(app, "#themes-list")], ["dark", "light", "theme-1"])
            self.assertEqual(pane.chosen(), "theme-1")

            app.screen.query_one("#theme-use").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.settle(pilot)
            self.assertEqual((app.theme_name, app.theme), ("theme-1", "probandia-theme-1"))
            self.assertFalse(app.has_class("-compact-buttons"))
            with open(os.path.join(self.env["PROBANDIA_CONFIG_DIR"], "config.toml"), encoding="utf-8") as fh:
                self.assertIn('theme = "theme-1"', fh.read())
            await pilot.press("escape", "t")   # out of the name, then the next theme: after the last, the dark
            await self.settle(pilot)
            self.assertEqual(app.theme, "probandia")
            self.assertTrue(app.has_class("-compact-buttons"))

            app.screen.query_one("#theme-delete").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.settle(pilot)
            self.assertFalse(os.path.exists(themes.path_of("theme-1", self.env)))
            self.assertEqual([r[0] for r in self.table(app, "#themes-list")], ["dark", "light"])

    async def test_a_theme_of_ones_own_is_kept(self):
        from probandia.config import themes

        themes.save("wide", "light", None, [("tree_width", "70"), ("section_titles", "false")], self.env)
        self.env["PROBANDIA_TUI_THEME"] = "wide"
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            self.assertEqual(app.theme, "probandia-wide")
            self.assertFalse(app.has_class("-section-titles"))
            app.show("family")
            await self.settle(pilot)
            self.assertEqual(app.screen.query_one("#family-tree").styles.width.value, 70)

class Console(AppCase):
    """CLI15-T6: the palette opens the forms of CLI14, and a form runs its command in the application (T107)."""

    async def test_a_command_run_from_the_palette(self):
        from textual.widgets import Tree

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("ctrl+p")
            await self.calm(pilot)
            await pilot.press(*"Form: usage")
            await pilot.pause(0.3)
            await pilot.press("enter")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormsScreen")
            tree = app.screen.query_one(Tree)
            self.assertEqual(str(tree.cursor_node.label), "usage")
            self.assertEqual(app.screen.command(), ["usage"])
            await pilot.press("ctrl+r")
            await self.until(pilot, lambda: "Exit code" in self.text(app.screen.query_one("#form-result")), 2000)
            out = self.text(app.screen.query_one("#form-result"))
            self.assertIn("Exit code: 0", out)
            self.assertIn("Command: probandia usage --output-format human", out)
            self.assertNotIn("STATUS=", out)
            self.assertTrue(app.is_running)

    async def test_q_goes_back_from_the_forms(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms("research")
            await pilot.pause(0.3)
            self.assertEqual(type(app.screen).__name__, "FormsScreen")
            await pilot.press("q")
            await self.calm(pilot)
            self.assertEqual(type(app.screen).__name__, "Main")


class Guards(AppCase):
    """CLI15-T7: the application writes nothing itself, reads a research an agent
    holds, asks before acting, shows no key and masks the living (cli.md § 8.5)."""

    AGENT = {"CLAUDECODE": "1", "PROBANDIA_SESSION": "agent-session"}

    def agent_takes_the_research(self):
        import io

        code = cli.main(["lock", "take", f"research:{RID}"], stdout=io.StringIO(), environ=dict(self.env, **self.AGENT),
                        cwd=self.dir)
        self.assertEqual(code, 0)

    async def test_screens_write_nothing_and_connect_nowhere(self):
        """T109, seen as it runs (the audit hook): every screen, part and tab shown, filtered, read again and
        looked at by the tick, and a confirmation refused, write no file, connect nowhere and start no
        process; after a yes, only the command confirmed writes; t writes the user's settings, nothing else."""
        from probandia.cli import tui_app

        propose(self)   # a proposal to read
        pause = ("research", "pause", RID, "--yes")
        app = self.app()
        with audited(app) as done:
            async with app.run_test(size=self.SIZE) as pilot:
                for name in tui_app.PANES:
                    app.show(name)
                    await self.settle(pilot)
                    for pane in app.shown():
                        for box in pane.query_children("#filter"):
                            box.value = "a"
                            await self.settle(pilot)
                            box.value = ""
                    app.refresh_screen()
                    await self.settle(pilot)
                    app.tick()
                    await self.settle(pilot)
                app.show("researches")
                await self.settle(pilot)
                app.screen.query_one("#research-pause").press()
                await self.asked(pilot)
                await pilot.press("n")
                await self.settle(pilot)
                self.assertEqual(done, [])

                app.screen.query_one("#research-pause").press()
                await self.asked(pilot)
                await pilot.press("y")
                await self.settle(pilot)
                self.assertTrue(done)
                self.assertEqual({argv for _event, _path, argv in done}, {pause}, done)
                done.clear()
                await pilot.press("t")
                await self.settle(pilot)
        folder = self.env["PROBANDIA_CONFIG_DIR"]
        self.assertTrue(done)
        for event, path, argv in done:   # config.toml, the copy written first, or its folder made
            self.assertEqual(argv[:4], ("config", "set", "tui.theme", "light"), (event, path))
            self.assertTrue(path == folder or (os.path.dirname(path) == folder and "config.toml" in path),
                            (event, path))

    async def test_a_research_an_agent_holds_is_read_only(self):
        self.agent_takes_the_research()
        propose(self)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.settle(pilot)
            for bid in ("#research-pause", "#research-close"):
                self.assertTrue(app.screen.query_one(bid).disabled, bid)
            self.assertIn("Read only: claude-code/session is writing this research",
                          self.text(app.screen.query_one("#research-lock")))
            await pilot.press("5")
            await self.settle(pilot)
            for bid in ("#proposal-apply", "#proposal-drop"):
                self.assertTrue(app.screen.query_one(bid).disabled, bid)
            self.assertIn("Read only", self.text(app.screen.query_one("#proposal-lock")))

    async def test_a_free_research_can_be_acted_on(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.settle(pilot)
            self.assertFalse(app.screen.query_one("#research-pause").disabled)
            self.assertEqual(self.text(app.screen.query_one("#research-lock")), "")

    async def test_nothing_runs_without_a_yes(self):
        from probandia.util import yamlio

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                app.screen.query_one("#research-pause").press()
                await self.asked(pilot)
                self.assertEqual(type(app.screen).__name__, "ConfirmScreen")
                await pilot.press("n")
                await self.settle(pilot)
                self.assertNotIn("pause", [c.args[1] for c in answer.call_args_list if len(c.args) > 1])
            meta = os.path.join(self.dir, "families", "marchand", "research", RID, "research.yaml")
            self.assertEqual(yamlio.load(meta)["status"], "open")
            app.screen.query_one("#research-pause").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.settle(pilot)
            self.assertEqual(yamlio.load(meta)["status"], "paused")

    async def test_no_key_on_any_screen(self):
        from textual.widgets import DataTable

        secret = "fixture-secret-9876543210"
        self.env.update(SERPER_API_KEY=secret, TAVILY_API_KEY="tvly-" + secret)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            seen = []
            for name in __import__("probandia.cli.tui_app", fromlist=["PANES"]).PANES:
                app.show(name)
                await self.settle(pilot)
                for t in app.screen.query(DataTable):
                    seen += [str(c) for i in range(t.row_count) for c in t.get_row_at(i)]
                seen += [self.text(w) for w in app.screen.query(Static)]
            self.assertTrue(any("SERPER_API_KEY" in x for x in seen))
            self.assertFalse([x for x in seen if secret in x])

    async def test_the_living_are_masked(self):
        from textual.widgets import Tree

        from probandia.util import yamlio

        doc = yamlio.load(persons_file(self))
        doc["persons"][0]["living"] = True
        yamlio.dump(persons_file(self), doc)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("4")
            await self.settle(pilot)
            labels = [str(n.label) for n in app.screen.query_one("#family-tree", Tree).root.children]
            self.assertEqual(labels, ["1  Living person"])
            await pilot.press("slash", *"Louis", "enter")
            await self.settle(pilot)
            self.assertNotIn("Louis MARCHAND", repr(self.table(app, "#family-found")))


class Failures(AppCase):
    """T87: a command that fails is said on its screen, with its reason; the application goes on."""

    LOG = ".probandia/logs/internal-01JB0000000000000000000L01.log"

    async def test_a_failing_command_is_shown_not_raised(self):
        from probandia.cli import board_cmd, commands, tui_app
        from probandia.cli.output import Result

        # the screens run a command's handler in this process (T88): a handler that prints
        # instead of answering, one that raises, one that answers an internal error
        def not_json(spec, ctx):
            ctx.stdout.write("a line outside the contract\n")

        def raises(spec, ctx):
            raise RuntimeError("the engine broke")

        def internal(spec, ctx):
            return Result("FAIL", {"REASON": "internal-error", "LOG": self.LOG},
                          ["internal error; details in the log"], exit_code=10)

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            app.research = None   # chosen by the board; without it the report runs a command, `research list`
            for fake, said in (((commands.Command, "run", not_json), ["tui-no-json", "a line outside the contract"]),
                               ((commands.Command, "run", raises),
                                ["failed: internal-error", "details in .probandia/logs/internal-"]),
                               ((commands.Command, "run", internal), ["failed: internal-error", f"details in {self.LOG}"]),
                               ((Result, "to_json", mock.Mock(side_effect=RuntimeError("the reader broke"))),
                                ["tui-engine-raised", "RuntimeError: the reader broke"])):
                # the home screen reads an engine function, not a command: it breaks too
                with mock.patch.object(*fake), \
                        mock.patch.object(board_cmd, "welcome", side_effect=RuntimeError("the board broke")):
                    for name in tui_app.PANES:
                        app.show(name)
                        await self.calm(pilot)
                        app.refresh_screen()   # read under this failure, the screen already shown included
                        await self.settle(pilot)
                        title = self.text(app.screen.query_one(f"#pane-{name} .title"))
                        for words in (["internal error: RuntimeError: the board broke"] if name == "home" else said):
                            self.assertIn(words, title, (said, name))
                        self.assertTrue(app.is_running)
            app.show("quotas")   # the engine back: the screens read again
            await self.settle(pilot)
            app.refresh_screen()
            await self.settle(pilot)
            self.assertIn("accounts ready", self.text(app.screen.query_one("#pane-quotas .title")))

    async def test_a_research_removed_while_shown(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.settle(pilot)
            self.assertEqual(app.research, RID)
            shutil.rmtree(os.path.join(self.dir, "families", "marchand", "research", RID))
            app.tick()   # the look at the watched files: the log is gone
            await self.settle(pilot)
            self.assertIn(f"The research {RID} no longer exists",
                          self.text(app.screen.query_one("#pane-researches .title")))
            self.assertEqual(self.table(app, "#research-log"), [])
            self.assertIsNone(app.research)
            for name in ("report", "team", "family", "researches"):   # the screens that follow the research
                app.show(name)
                await self.settle(pilot)
            with mock.patch("webbrowser.open") as browser:
                await pilot.press("o")
            browser.assert_not_called()
            self.assertTrue(app.is_running)


# T109: what the application does, seen as it runs by Python's audit hook. A hook cannot be removed: it
# records only while a test holds AUDIT, and names the engine command each thread was running then.
AUDIT = None
RUNNING = threading.local()
CHANGES = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.truncate", "shutil.rmtree"}   # writes, no open
PROCESSES = {"subprocess.Popen", "os.system", "os.startfile", "os.posix_spawn", "os.spawn", "os.exec"}


def _audit(event, args):
    if AUDIT is None:
        return
    if event == "open":
        path, mode, flags = args
        if not isinstance(path, str) or not ((set(mode or "") & set("wax+"))
                                             or (mode is None and flags & (os.O_WRONLY | os.O_RDWR))):
            return
    elif event == "socket.connect":
        path = args[1]
    elif event in CHANGES or event in PROCESSES:
        path = args[0]
    else:
        return
    if "__pycache__" not in str(path):   # Python's own, a module imported for the first time
        AUDIT.append((event, str(path), getattr(RUNNING, "argv", None)))


@contextlib.contextmanager
def audited(app):
    """[(event, file, address or program, the engine command its thread ran)]: the files opened to write,
    removed, renamed or made, the connections and the processes, by any thread, while in the block. A
    command of the console (``execute``) is named by its arguments: ([its argv], [its line])."""
    global AUDIT
    if not getattr(audited, "hooked", False):
        sys.addaudithook(_audit)
        audited.hooked = True

    def marked(run):
        def call(*argv, **kwargs):
            RUNNING.argv = argv
            try:
                return run(*argv, **kwargs)
            finally:
                RUNNING.argv = None
        return call

    AUDIT = []
    try:
        with mock.patch.object(app, "answer", marked(app.answer)), mock.patch.object(app, "execute",
                                                                                     marked(app.execute)):
            yield AUDIT
    finally:
        AUDIT = None


def fork(case, name, *more):
    out = io.StringIO()
    case.assertEqual(cli.main(["fork", RID, "--at", "2", "--name", name, *more, "--no-pass"], stdout=out,
                              environ=case.env, cwd=case.dir), 0, out.getvalue())
    return next(x.split("=", 1)[1] for x in out.getvalue().splitlines() if x.startswith("RESEARCH="))


class Functions(AppCase):
    """T97 to T101: what each screen does (cli.md § 8.3), every action an engine command."""

    async def test_home_opens_and_copies(self):
        """T97: Enter on a research of the home opens Researches on it; c copies the command that
        resumes it, and runs nothing; an event added meanwhile shows among the Events."""
        from textual.widgets import TabbedContent

        from probandia.cli import board_cmd

        second = fork(self, "second-look")
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            ids = [r[0] for r in self.table(app, "#home-researches")]
            app.screen.query_one("#home-researches").move_cursor(row=ids.index(second))
            await self.settle(pilot)
            self.assertEqual(self.text(app.screen.query_one("#home-events-head")), f"Events · {second}")
            with mock.patch.object(app, "copy_to_clipboard") as clip, mock.patch.object(app, "answer") as answer, \
                    mock.patch.object(board_cmd, "welcome") as board, mock.patch("subprocess.Popen") as process:
                await pilot.press("c")
                await self.calm(pilot)
            clip.assert_called_once_with(f"/probandia:resume {second}")
            for spy in (answer, board, process):
                spy.assert_not_called()

            self.event(second)   # an agent writes
            app.tick()
            await self.settle(pilot)
            self.assertEqual(self.table(app, "#home-events")[-1][1:], ["instruction", "look at the census first"])

            await pilot.press("enter")
            await self.settle(pilot)
            self.assertEqual(app.screen.query_one("#screens", TabbedContent).active, "researches")
            listed = app.screen.query_one("#researches-list")
            self.assertEqual((app.research, self.table(app, "#researches-list")[listed.cursor_row][0]),
                             (second, second))
            self.assertIn("Who were the ancestors of Louis MARCHAND?", self.text(app.screen.query_one("#research-head")))

    async def test_quotas_history_calendar_copy(self):
        """T98: on a counter of 30 days, the curve of an account has 30 points that add up to its
        units, and follows a line added; the calendar sorts the accounts by the date they renew;
        c copies the accounts shown as CSV, and writes no file."""
        import csv
        import datetime
        import json

        from textual.widgets import DataTable, Sparkline

        from probandia.cli import usage_cmd

        now = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.timezone.utc)
        counter = os.path.join(self.env["PROBANDIA_DATA_DIR"], "quotas", "ledger.jsonl")
        os.makedirs(os.path.dirname(counter))

        def line(days_ago, units):   # a search counted on SerpApi without a key, as the engine files it
            ts = (now - datetime.timedelta(days=days_ago, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            return json.dumps({"ts": ts, "provider": "serpapi", "operation": "search", "units": units,
                               "source": "response", "key": "public", "project": "0123abcd"}) + "\n"

        with open(counter, "w", encoding="utf-8") as fh:
            fh.writelines([line(d, d % 4 + 1) for d in range(30)] + [line(30, 100), line(5, 0)])
        with mock.patch.object(usage_cmd, "_now", lambda: now):
            app = self.app()
            async with app.run_test(size=self.SIZE) as pilot:
                await pilot.press("2")
                await self.settle(pilot)
                table = app.screen.query_one("#quotas-accounts", DataTable)
                table.move_cursor(row=[k.value for k in table.rows].index("serpapi"))
                await self.settle(pilot)
                curve = app.screen.query_one("#quotas-history", Sparkline)
                self.assertEqual((len(curve.data), sum(curve.data)), (30, sum(d % 4 + 1 for d in range(30))))
                self.assertEqual(curve.data[-1], 1)   # today, last
                with open(counter, "a", encoding="utf-8") as fh:
                    fh.write(line(0, 5))
                app.tick()
                await self.settle(pilot)
                self.assertEqual((curve.data[-1], sum(curve.data)), (6, sum(d % 4 + 1 for d in range(30)) + 5))
                self.assertIn("the last 30 days: 78 searches", self.text(app.screen.query_one("#quotas-history-head")))

                accounts = app.engine("usage")["data"]["accounts"]
                dated = sorted((a for a in accounts if a["renews_at"] and a["renews"] in ("reset", "expires")),
                               key=lambda a: (a["renews_at"], a["name"]))
                self.assertGreater(len({a["renews_at"] for a in dated}), 1)
                self.assertEqual([r[1] for r in self.table(app, "#quotas-calendar")], [a["name"] for a in dated])

                await pilot.press("slash", *"serp", "escape")
                with mock.patch.object(app, "copy_to_clipboard") as clip, audited(app) as done:
                    await pilot.press("c")
                    await self.calm(pilot)
                self.assertEqual(done, [])   # no file written: the hook of T109
                rows = list(csv.reader(io.StringIO(clip.call_args.args[0])))
                self.assertEqual(rows[0], [str(c.label) for c in table.columns.values()])
                self.assertEqual(rows[1:], self.table(app, "#quotas-accounts"))
                self.assertTrue(rows[1:] and all("serp" in r[0].lower() for r in rows[1:]), rows)

    async def test_fork_from_the_file(self):
        """T99: the fork asks its pass and its name, then a confirmation; n runs nothing, y runs
        fork --no-pass, and the fork is chosen in the list; a research an agent holds cannot be forked."""
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("3")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for yes in ("n", "y"):
                    app.screen.query_one("#research-fork").press()
                    await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                    self.assertEqual(app.screen.query_one("#fork-at").value, "2")   # its last pass done
                    app.screen.query_one("#fork-name").value = "second-look"
                    await pilot.press("enter")
                    await self.asked(pilot)
                    await pilot.press(yes)
                    await self.settle(pilot)
                    forks = [c.args for c in answer.call_args_list if c.args[0] == "fork"]
                    self.assertEqual(forks, [] if yes == "n" else
                                     [("fork", RID, "--at", "2", "--name", "second-look", "--no-pass")])
            ids = [r[0] for r in self.table(app, "#researches-list")]
            made = next(x for x in ids if x.endswith("-second-look"))
            listed = app.screen.query_one("#researches-list")
            self.assertEqual((app.research, ids[listed.cursor_row]), (made, made))

            agent = dict(self.env, CLAUDECODE="1", PROBANDIA_SESSION="agent-session")
            self.assertEqual(cli.main(["lock", "take", f"research:{made}"], stdout=io.StringIO(), environ=agent,
                                      cwd=self.dir), 0)
            app.tick()
            await self.settle(pilot)
            self.assertTrue(app.screen.query_one("#research-fork").disabled)
            self.assertIn("Read only: claude-code/session is writing this research",
                          self.text(app.screen.query_one("#research-lock")))

    async def test_cite_and_open_the_tree(self):
        """T100: Cite shows and copies the citation person gives a fact, asking the engine nothing;
        o on the Family writes the HTML tree when it is missing or older than the index, then opens
        it; o on Researches opens the report; a presumed-living person has nothing to cite."""
        from textual.widgets import Tree

        from probandia.util import yamlio

        doc = yamlio.load(persons_file(self))
        doc["persons"][0]["living"] = True   # Louis, the root
        yamlio.dump(persons_file(self), doc)
        self.assertEqual(cli.main(["render", RID], stdout=io.StringIO(), environ=self.env, cwd=self.dir), 0)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("4")
            await self.settle(pilot)
            self.assertFalse(app.screen.query_one("#person-cite").display)   # a living person: no Cite
            with mock.patch.object(app, "copy_to_clipboard") as clip:
                await pilot.press("c")
                await self.calm(pilot)
            clip.assert_not_called()

            tree = app.screen.query_one("#family-tree", Tree)
            tree.move_cursor(app.screen.query_one("#pane-family").nodes[2])
            await self.settle(pilot)
            facts = app.engine("person", "henri-marchand-1870")["data"]["facts"]
            cited = next(i for i, f in enumerate(facts) if f["citation"])
            app.screen.query_one("#person-facts").move_cursor(row=cited)
            with mock.patch.object(app, "copy_to_clipboard") as clip, mock.patch.object(app, "answer") as answer:
                app.screen.query_one("#person-cite").press()
                await self.calm(pilot)
            answer.assert_not_called()
            clip.assert_called_once_with(facts[cited]["citation"])
            self.assertEqual(self.text(app.screen.query_one("#person-citation")), facts[cited]["citation"])

            html = os.path.join(self.dir, "families", "marchand", "trees", "tree.html")
            tree_argv = ("tree", "--family", "marchand", "--format", "html")
            with mock.patch("webbrowser.open") as browser, mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for step, written in enumerate((True, False, True)):   # missing; fresh; older than the index
                    await pilot.press("o")
                    if written:
                        await self.asked(pilot)
                        await pilot.press("y")
                    await self.settle(pilot)
                    self.assertEqual([c.args for c in answer.call_args_list if c.args[0] == "tree"],
                                     [tree_argv] if written else [])
                    self.assertTrue(browser.call_args.args[0].endswith("trees/tree.html"))
                    # three opens once on macOS at GitHub (24 October 2026): which step, and what opened them
                    self.assertEqual(browser.call_count, 1, (step, browser.call_args_list, answer.call_args_list,
                                                             [type(s).__name__ for s in app.screen_stack]))
                    answer.reset_mock()
                    browser.reset_mock()
                    if not written:
                        later = os.path.getmtime(html) + 10
                        os.utime(persons_file(self), (later, later))   # the index changed since
                self.assertTrue(os.path.isfile(html))
                await pilot.press("3", "o")
                await self.settle(pilot)
                self.assertTrue(browser.call_args.args[0].endswith("report/report.html"))

    async def test_a_read_shown_keeps_the_next_proposal(self):
        """n pressed just before a read of the proposals is shown (a file an agent wrote, read again
        at the tick): the move stays, the read does not put the cursor back on the proposal before."""
        ids = [PROPOSAL[:-1] + n for n in "12"]
        for pid in ids:
            propose(self, id=pid)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("5")
            await self.settle(pilot)
            pane = app.pane("proposals")
            self.assertEqual(pane.selected[0], ids[0])
            every = pane.read(None)
            pane.step(1)   # its RowHighlighted is not read yet when the read is shown
            pane.show(every)
            await self.settle(pilot)
            self.assertEqual(pane.selected[0], ids[1])
            self.assertEqual(app.screen.query_one("#proposals-list").cursor_row, 1)

    async def test_review_three_proposals(self):
        """T102: three proposals reviewed without the mouse: n and p go from one to another, the detail shows
        the entries of the index each would add or change; a runs proposals apply once confirmed, x asks the
        reason then runs proposals drop, and the next one is shown; the hook of T109 records writes from the
        commands confirmed only."""
        from probandia.util import yamlio

        def death(person, year, source):
            return {"id": f"{person}.death", "type": "death", "date": {"value": str(year), "qualifier": "exact"},
                    "status": "index", "source": source}

        sources = yamlio.load(os.path.join(self.dir, "families", "marchand", "index", "sources.yaml"))["sources"]
        records = dict(next(s for s in sources if s["id"] == "src-01JA0000000000000000000004"), item="1850, p. 2")
        ids = [PROPOSAL[:-1] + n for n in "123"]
        propose(self, id=ids[0])
        propose(self, id=ids[1], facts=[death("catherine-le-roux-1820", 1885, "src-01JA0000000000000000000005")])
        propose(self, id=ids[2], facts=[death("etienne-perrin-1790", 1850, records["id"])], sources=[records])
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("5")

            async def shown(*keys):
                await pilot.press(*keys)
                await self.settle(pilot)
                return app.pane("proposals").selected[0], self.table(app, "#proposal-changes")

            self.assertEqual(await shown(), (ids[0], [["facts", "louise-perrin-1818.death", "added"]]))
            self.assertEqual([r[0] for r in self.table(app, "#proposals-list")], ids)
            self.assertEqual((await shown("n"))[0], ids[1])
            self.assertEqual(await shown("n"), (ids[2], [["sources", records["id"], "modified"],
                                                         ["facts", "etienne-perrin-1790.death", "added"]]))
            self.assertEqual((await shown("n"))[0], ids[2])   # the last one stays
            self.assertEqual((await shown("p"))[0], ids[1])

            with audited(app) as done:
                await pilot.press("a")
                await self.asked(pilot)
                self.assertEqual(await shown("y"), (ids[2], [["sources", records["id"], "modified"],
                                                             ["facts", "etienne-perrin-1790.death", "added"]]))
                self.assertEqual([r[0] for r in self.table(app, "#proposals-list")], [ids[0], ids[2]])
                await pilot.press("x")
                await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                await pilot.press(*"a duplicate", "enter")
                await self.asked(pilot)
                self.assertEqual((await shown("y"))[0], ids[0])
                await pilot.press("a")
                await self.asked(pilot)
                await shown("n")   # refused: nothing runs
            self.assertEqual([r[0] for r in self.table(app, "#proposals-list")], [ids[0]])
        self.assertTrue(done)
        self.assertEqual({argv for _event, _path, argv in done},
                         {("proposals", "apply", ids[1], "--yes"),
                          ("proposals", "drop", ids[2], "--reason", "a duplicate", "--yes")})
        facts = {f["id"] for p in yamlio.load(persons_file(self))["persons"] for f in p.get("facts", [])}
        self.assertEqual((("catherine-le-roux-1820.death" in facts), ("etienne-perrin-1790.death" in facts)),
                         (True, False))

    async def test_check_a_key_and_sign_up(self):
        """T103: checking a key asks first, saying network and free; on y, keys check runs (its readings of
        the accounts simulated) and the key's line says what it answered, never its value; Sign up runs keys
        signup, and the browser (simulated) gets the page of the catalogue."""
        from textual.widgets import DataTable

        from probandia.providers import adapters, catalogue
        from probandia.providers.base import ProviderError

        secret = "fixture-secret-0123456789"
        self.env["SERPER_API_KEY"] = secret
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("providers")
            await self.settle(pilot)
            keys = app.screen.query_one("#providers-keys")
            keys.move_cursor(row=[r[0] for r in self.table(app, "#providers-keys")].index("SERPER_API_KEY"))
            seen = []
            readings = (({"left": 2500.0}, "valid"), (ProviderError("serper", 401, b"{}"), "refused"),
                        (ProviderError("serper", 403, b"{}", "serper: subscribe to a plan first"), "not subscribed"))
            with mock.patch.object(app, "answer", wraps=app.answer) as answer, \
                    mock.patch.object(adapters, "sync") as sync:
                for yes, (reading, said) in [("n", readings[0])] + [("y", r) for r in readings]:
                    sync.side_effect = [reading]
                    app.screen.query_one("#provider-check").press()
                    await self.asked(pilot)
                    self.assertIn("over the network", self.text(app.screen.query_one("#question")))
                    self.assertIn("nothing is spent", self.text(app.screen.query_one("#question")))
                    await pilot.press(yes)
                    await self.settle(pilot)
                    checks = [c.args for c in answer.call_args_list if c.args[:2] == ("keys", "check")]
                    if yes == "n":
                        self.assertEqual(checks, [])
                        continue
                    self.assertEqual(checks[-1], ("keys", "check", "SERPER_API_KEY"))
                    row = next(r for r in self.table(app, "#providers-keys") if r[0] == "SERPER_API_KEY")
                    self.assertEqual(row[-1], said)
                    seen += [str(c) for t in app.screen.query(DataTable) for i in range(t.row_count)
                             for c in t.get_row_at(i)] + [self.text(w) for w in app.screen.query(Static)]
                    seen += [n.message for n in app._notifications]
            self.assertEqual(sync.call_count, 3)
            self.assertFalse([x for x in seen if secret in x])

            providers = [r[0] for r in self.table(app, "#providers-list")]
            app.screen.query_one("#providers-list").move_cursor(row=providers.index("serper"))
            entry = catalogue.load()["serper"]
            with mock.patch("webbrowser.open", return_value=True) as browser:
                app.screen.query_one("#provider-signup").press()
                await self.settle(pilot)
            browser.assert_called_once_with(entry.get("signup_url") or entry["source_url"])

    async def test_explain_set_grade_roles(self):
        """T104: Enter on a setting shows what config explain prints; Change asks a value: one the registry
        refuses is said with the engine's reason and changes nothing, one it takes shows with its layer once
        confirmed; Grade runs config grade once confirmed; the table Roles has the lines of config roles."""
        from textual.widgets import Select

        settings = os.path.join(self.dir, "probandia.toml")
        with open(settings, encoding="utf-8") as fh:
            before = fh.read()
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("6")
            await self.settle(pilot)
            self.assertEqual([r[0] for r in self.table(app, "#config-roles")],
                             [x["role"] for x in app.engine("config", "roles")["data"]["roles"]])
            table = app.screen.query_one("#config-settings")
            row = [r[0] for r in self.table(app, "#config-settings")].index("report.mode")
            table.focus()
            table.move_cursor(row=row)
            # the cursor and the focus are messages too: Enter before them went elsewhere (Ubuntu CI, 24 October 2026)
            await self.until(pilot, lambda: table.has_focus and table.cursor_row == row)
            await pilot.press("enter")
            await self.until(pilot, lambda: "report.mode" in self.text(app.screen.query_one("#config-explain")))
            explained = self.text(app.screen.query_one("#config-explain"))
            self.assertIn("report.mode", explained)
            self.assertIn(app.engine("config", "explain", "report.mode")["lines"][0], explained)   # its help

            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for yes in ("n", "y"):   # an enum: a list of its values
                    app.screen.query_one("#config-set").press()
                    await self.until(pilot, lambda: type(app.screen).__name__ == "ChangeScreen")
                    app.screen.query_one("#change-value", Select).value = "living"
                    app.screen.query_one("#change-next").press()
                    await self.asked(pilot)
                    await pilot.press(yes)
                    await self.settle(pilot)
                    with open(settings, encoding="utf-8") as fh:
                        written = fh.read()
                    row = next(r for r in self.table(app, "#config-settings") if r[0] == "report.mode")
                    if yes == "n":
                        self.assertEqual((written, row[1:3]), (before, ["journal", "default"]))
                self.assertEqual(row[1:3], ["living", "project"])
                self.assertIn("living", self.text(app.screen.query_one("#config-explain")))   # explained again
                self.assertEqual([c.args for c in answer.call_args_list if c.args[:2] == ("config", "set")],
                                 [("config", "set", "report.mode", "living")])

                app.screen.query_one("#config-grade").press()
                await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                app.screen.query_one("#config-grade", Select).value = "advanced"
                app.screen.query_one("#ask-next").press()
                await self.asked(pilot)
                await pilot.press("y")
                await self.settle(pilot)
                self.assertIn(("config", "grade", "advanced"), [c.args for c in answer.call_args_list])
            self.assertIn("Settings of the advanced grade", self.text(app.screen.query_one("#pane-config .title")))

    async def test_test_then_trust_a_script(self):
        """T105: Test asks first, saying the network; on y, library test plays the witness (its run simulated)
        and the state and the runs passed are said, or the reason witness-failed; Approve asks first, and the
        state shown becomes the one library trust answers; neither runs without a y."""
        from probandia.library import Library

        source = os.path.join(self.tmp.name, "census.py")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("def run(args):\n    return []\n")
        out = io.StringIO()
        self.assertEqual(cli.main(["library", "save", source, "--id", "census-reader", "--purpose", "reads a census",
                                   "--hosts", "archives.example.org", "--witness-args", "{}"], stdout=out,
                                  environ=self.env, cwd=self.dir), 0, out.getvalue())
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("library")
            await self.settle(pilot)

            def level():
                return next(r for r in self.table(app, "#library-scripts") if r[0] == "census-reader")[2]

            self.assertEqual(level(), "draft")
            with mock.patch.object(app, "answer", wraps=app.answer) as answer, mock.patch.object(Library, "run") as run:
                for button, yes, ran, said, state in (
                        ("test", "n", None, "", "draft"), ("trust", "n", None, "", "draft"),
                        ("test", "y", (False, None, "no answer from archives.example.org"),
                         "failed: witness-failed · no answer from archives.example.org", "draft"),
                        ("test", "y", (True, [{"page": 1}], None), "census-reader · tested · 1 run passed", "tested"),
                        ("trust", "y", None, "census-reader · trusted", "trusted")):
                    run.return_value = ran
                    app.screen.query_one(f"#library-{button}").press()
                    await self.asked(pilot)
                    if button == "test":
                        self.assertIn("over the network", self.text(app.screen.query_one("#question")))
                    await pilot.press(yes)
                    await self.settle(pilot)
                    self.assertIn(said, self.text(app.screen.query_one("#library-outcome")))
                    self.assertEqual(level(), state)
            self.assertEqual([c.args for c in answer.call_args_list if c.args[:1] == ("library",) and c.args[1] != "list"],
                             [("library", "test", "census-reader")] * 2 + [("library", "trust", "census-reader")])
            self.assertEqual(run.call_count, 2)

    async def test_logs_cache_and_purge(self):
        """T106: on a project with a cache and logs, the table Logs lists the files of .probandia/logs with their
        size and date, and Enter shows the last lines of the one chosen without opening it to write; the table
        Cache is cache stats; Purge asks first, saying how many entries and bytes go, then runs cache clear with
        the provider chosen and --yes; on n, no command runs."""
        import json
        import time

        from probandia.cli import tui_app
        from probandia.i18n import formats

        cache = os.path.join(self.dir, ".probandia", "cache")
        for folder, n in (("tavily", 3), ("http", 1)):
            os.makedirs(os.path.join(cache, folder))
            for i in range(n):
                with open(os.path.join(cache, folder, f"{folder}-{i}.json"), "w", encoding="utf-8") as fh:
                    json.dump({"created": time.time() - 86400 * i, "ttl": 0, "by": folder, "payload": {"n": i}}, fh)
        tavily = sum(os.path.getsize(os.path.join(cache, "tavily", x)) for x in os.listdir(os.path.join(cache, "tavily")))
        folder = os.path.join(self.dir, ".probandia", "logs")
        os.makedirs(folder)
        internal = "internal-01JB0000000000000000000L01.log"
        with open(os.path.join(folder, internal), "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(f"line {i}\n" for i in range(50))
        with open(os.path.join(folder, "agents.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write('{"agent": "researcher"}\n')
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("diagnostic")
            await self.settle(pilot)
            listed = {r[0]: r[1:] for r in self.table(app, "#diagnostic-logs")}
            self.assertEqual(set(listed), {internal, "agents.jsonl"})
            self.assertEqual(listed[internal][0], formats.number(os.path.getsize(os.path.join(folder, internal))))
            self.assertTrue(listed[internal][1])   # when it was written
            stats = app.engine("cache", "stats")["data"]["cache"]
            self.assertEqual([(r[0], r[1]) for r in self.table(app, "#diagnostic-cache")],
                             [(x["provider"], formats.number(x["entries"])) for x in stats])
            self.assertEqual([x["provider"] for x in stats], ["tavily", "http"])

            logs = app.screen.query_one("#diagnostic-logs")
            logs.move_cursor(row=list(listed).index(internal))
            logs.focus()
            with audited(app) as done:
                await pilot.press("enter")
                await self.settle(pilot)
            self.assertEqual(done, [])   # read, not opened to write
            shown = self.text(app.screen.query_one("#diagnostic-log")).splitlines()
            self.assertEqual(shown[1:], [f"line {i}" for i in range(50 - tui_app.LOG_LINES, 50)])

            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for yes in ("n", "y"):
                    app.screen.query_one("#diagnostic-cache").move_cursor(row=0)   # tavily
                    app.screen.query_one("#cache-purge").press()
                    await self.asked(pilot)
                    self.assertIn(f"Remove the 3 cache entries of tavily ({formats.number(tavily)} bytes)?",
                                  self.text(app.screen.query_one("#question")))
                    await pilot.press(yes)
                    await self.settle(pilot)
                    clears = [c.args for c in answer.call_args_list if c.args[0] == "cache" and c.args[1] == "clear"]
                    self.assertEqual(clears, [] if yes == "n" else [("cache", "clear", "--provider", "tavily", "--yes")])
            self.assertEqual([r[0] for r in self.table(app, "#diagnostic-cache")], ["http"])
            self.assertEqual(os.listdir(os.path.join(cache, "tavily")), [])

    async def test_choose_root_and_family(self):
        """T101: on a project of two families, the selector goes from one to the other; the root is
        the subject of the research chosen, not the first person of the index; a person chosen in
        their file becomes the root, numbered 1."""
        from textual.widgets import Select, Tree

        from probandia.util import yamlio

        fork(self, "other-look", "--new-family", "roussel")
        doc = yamlio.load(persons_file(self))
        doc["persons"].append(doc["persons"].pop(0))   # Louis, the subject, last of the index
        yamlio.dump(persons_file(self), doc)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            app.research = RID
            await pilot.press("4")
            await self.settle(pilot)
            pane, tree = app.screen.query_one("#pane-family"), app.screen.query_one("#family-tree", Tree)
            choice = app.screen.query_one("#family-choice", Select)
            self.assertEqual(choice.value, "marchand")
            self.assertEqual(str(tree.root.children[0].label), "1  Louis MARCHAND (1898-1970)")
            for family in ("roussel", "marchand"):
                choice.value = family
                await self.settle(pilot)
                self.assertIn(f"Family {family} · ", self.text(pane.query_one(".title")))
            tree.move_cursor(pane.nodes[2])
            await self.settle(pilot)
            app.screen.query_one("#person-root").press()
            await self.settle(pilot)
            first = tree.root.children[0]
            self.assertEqual(str(first.label), "1  Henri MARCHAND (1870-1931)")
            self.assertTrue(str(first.children[0].label).startswith("2  "))


class KeysDuringTheFirstRead(AppCase):
    """A key of the list pressed while the screen's first read is under way is not lost: the pane
    holds it, and plays it on the list once it is shown (Home and Researches)."""

    async def check(self, screen, pane, table_id, *keys):
        from probandia.cli import tui_app

        fork(self, "second-look")
        gate = threading.Event()
        cls = getattr(tui_app, pane)
        real = cls.read

        def slow(self_, context):
            gate.wait(10)
            return real(self_, context)

        app = self.app()
        with mock.patch.object(cls, "read", slow):
            async with app.run_test(size=self.SIZE) as pilot:
                if screen:
                    await pilot.press(screen)
                await self.until(pilot, lambda: isinstance(app.focused, cls))   # waiting, the pane holds the keys
                await pilot.press(*keys)
                await self.calm(pilot)
                gate.set()
                await self.settle(pilot)
                table = app.screen.query_one(table_id)
                self.assertEqual(table.row_count, 2)
                self.assertIs(app.focused, table)
                self.assertEqual(table.cursor_row, 1, keys)
                self.assertEqual(app.research, table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    async def test_home(self):
        await self.check(None, "HomePane", "#home-researches", "j")

    async def test_researches(self):
        await self.check("3", "ResearchesPane", "#researches-list", "down", "up", "down")


if __name__ == "__main__":
    unittest.main()
