"""Headless tests of the speed of the application in a terminal (version-1.0.0 T88 to
T91): the screens read in threads and keep what they read, keep their place when read
again, watch their own files, and show a long report or a long log at once. Apart from
``test_tui_app``, so that the ``tui`` job runs them in a process of their own."""
import os
import unittest
from unittest import mock

from probandia import cli
from tests.unit.test_tui_app import RID, AppCase, persons_file

# tools/ci_local.py sets it: its jobs load the machine (some 34 processes on 16 cores) and make any time
# vary tenfold; there the assertions of time are skipped and the rest of these tests runs. The times are
# checked on a calm machine before a sprint of the TUI is merged (AGENTS.md), and on GitHub's runners.
TIMED = not os.environ.get("CI_LOCAL_NO_TIMING")


def fast_enough(case, took, limit, msg=None):
    if TIMED:
        case.assertLess(took, limit, msg)


class Speed(AppCase):
    """T88: the screens read in threads, and keep what they read until a watched file changes."""

    def counted(self, app):
        """A spy on every engine command the screens run."""
        return mock.patch.object(app, "answer", wraps=app.answer)

    async def test_the_filter_reads_nothing_again(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("2")
            await self.settle(pilot)
            every = len(self.table(app, "#quotas-accounts"))
            with self.counted(app) as answer:
                await pilot.press("slash", *"serp")
                await self.settle(pilot)
                answer.assert_not_called()
            rows = self.table(app, "#quotas-accounts")
            self.assertTrue(rows and len(rows) < every)
            self.assertTrue(all("serp" in r[0].lower() for r in rows), rows)

    async def test_an_unchanged_screen_is_not_read_again(self):
        from probandia.cli import board_cmd

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            for key in ("2", "3", "4", "6"):
                await pilot.press(key)
                await self.settle(pilot)
            with self.counted(app) as answer, mock.patch.object(board_cmd, "welcome", wraps=board_cmd.welcome) as board:
                for key in ("1", "2", "3", "4", "6", "2"):
                    await pilot.press(key)
                    await self.settle(pilot)
                answer.assert_not_called()
                board.assert_not_called()
                app.tick()   # nothing changed: nothing is read
                await self.settle(pilot)
                answer.assert_not_called()
                await pilot.press("r")   # r reads the screen anyway
                await self.settle(pilot)
                self.assertEqual([c.args for c in answer.call_args_list], [("usage",)])

    async def test_a_slow_read_does_not_freeze_the_keys(self):
        import time

        from textual.widgets import TabbedContent

        from probandia.cli import tui_app

        app = self.app()
        answer, switch = app.answer, tui_app.Main.on_tabbed_content_tab_activated
        switched = []

        def slow(*argv):
            time.sleep(2)
            return answer(*argv)

        def timed(screen, event):   # the switch handled: the screen is drawn next
            switch(screen, event)
            switched.append(time.monotonic())

        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            with mock.patch.object(app, "answer", slow), \
                    mock.patch.object(tui_app.Main, "on_tabbed_content_tab_activated", timed):
                t0 = time.monotonic()
                await pilot.press("2")   # the pilot then waits for an idle process: not counted
                self.assertEqual(app.screen.query_one("#screens", TabbedContent).active, "quotas")
                fast_enough(self, switched[0] - t0, 0.2)
                self.assertTrue(app.screen.query_one("#quotas-accounts").loading)   # its LoadingIndicator
                await pilot.press("1")   # the keys go on meanwhile
                self.assertEqual(app.screen.query_one("#screens", TabbedContent).active, "home")
                await pilot.press("2")
                await self.settle(pilot)
            self.assertFalse(app.screen.query_one("#quotas-accounts").loading)
            self.assertTrue(self.table(app, "#quotas-accounts"))


class Place(AppCase):
    """T89: read again, a screen keeps its cursor, its selection and its tree as they were."""

    def row_key(self, table):
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    async def test_a_refresh_keeps_the_place(self):
        import io

        from textual.widgets import DataTable, Tree

        from probandia import events
        from probandia.util import yamlio

        out = io.StringIO()
        self.assertEqual(cli.main(["fork", RID, "--at", "2", "--name", "second-look", "--no-pass"], stdout=out,
                                  environ=self.env, cwd=self.dir), 0, out.getvalue())
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            # Quotas: the cursor on the fourth line, then a watched file changes
            await pilot.press("2")
            await self.settle(pilot)
            table = app.screen.query_one("#quotas-accounts", DataTable)
            table.move_cursor(row=3)
            await self.calm(pilot)
            key = self.row_key(table)
            os.makedirs(os.path.join(self.dir, ".probandia"), exist_ok=True)
            with open(os.path.join(self.dir, ".probandia", "ledger.jsonl"), "a", encoding="utf-8"):
                pass   # a ledger appears
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                app.tick()
                await self.settle(pilot)
                self.assertEqual([c.args for c in answer.call_args_list], [("usage",)])   # read again
            self.assertEqual((table.cursor_row, self.row_key(table)), (3, key))

            # Researches: the second one chosen, then its log grows
            await pilot.press("3")
            await self.settle(pilot)
            ids = [r[0] for r in self.table(app, "#researches-list")]
            others = [x for x in ids if x != RID]
            self.assertTrue(others, (ids, self.text(app.pane("researches").query_one(".title"))))
            second = others[0]
            listed = app.screen.query_one("#researches-list", DataTable)
            listed.move_cursor(row=ids.index(second))
            await self.settle(pilot)
            self.assertEqual(app.research, second)
            shown = len(self.table(app, "#research-log"))
            path = os.path.join(self.dir, "families", "marchand", "research", second, "events.jsonl")
            events.append(path, [events.make("instruction.added", {"text": "look at the census first"},
                                             {"harness": "cli", "agent": "session"}, 2)])
            app.tick()
            await self.settle(pilot)
            self.assertEqual(app.research, second)
            self.assertEqual(self.row_key(listed), second)
            self.assertEqual(len(self.table(app, "#research-log")), shown + 1)

            # Family: a person chosen in the tree, a branch folded, then the index changes
            await pilot.press("4")
            await self.settle(pilot)
            pane, tree = app.screen.query_one("#pane-family"), app.screen.query_one("#family-tree", Tree)
            pane.nodes[3].collapse()
            tree.move_cursor(pane.nodes[2])
            await self.settle(pilot)
            self.assertIn("henri-marchand-1870", self.text(app.screen.query_one("#person-head")))
            doc = yamlio.load(persons_file(self))
            doc["persons"][0]["facts"][0]["note"] = "read again"
            yamlio.dump(persons_file(self), doc)
            app.tick()   # the Family watches the index (T90)
            await self.settle(pilot)
            self.assertEqual(tree.cursor_node.data, "henri-marchand-1870")
            self.assertIs(tree.cursor_node, pane.nodes[2])   # the tree was built anew
            self.assertEqual({n: node.is_expanded for n, node in pane.nodes.items() if n < 4},
                             {1: True, 2: True, 3: False})
            self.assertIn("henri-marchand-1870", self.text(app.screen.query_one("#person-head")))


class Watching(AppCase):
    """T90: each screen watches its own files, and only the screen concerned reads again."""

    async def test_each_screen_watches_its_files(self):
        import io

        from probandia.util import yamlio

        self.assertEqual(cli.main(["render", RID], stdout=io.StringIO(), environ=self.env, cwd=self.dir), 0)
        research = os.path.join(self.dir, "families", "marchand", "research", RID)
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            for name in ("quotas", "researches", "report", "family"):   # each screen read once
                app.show(name)
                await self.settle(pilot)

            async def reads(name, change=None):
                """The screens that read, ``name`` shown, then ``change`` made and the tick."""
                with mock.patch.object(app, "reading", wraps=app.reading) as reading:
                    app.show(name)
                    await self.settle(pilot)
                    if change:
                        change()
                        app.tick()
                        await self.settle(pilot)
                return sorted({c.args[0].__self__.id for c in reading.call_args_list})

            def persons():
                doc = yamlio.load(persons_file(self))
                doc["persons"][0]["facts"][0]["note"] = "read again"
                yamlio.dump(persons_file(self), doc)

            def report():
                with open(os.path.join(research, "report", "report.md"), "a", encoding="utf-8") as fh:
                    fh.write("\nA line added by the agent.\n")

            def meta():
                doc = yamlio.load(os.path.join(research, "research.yaml"))
                doc["question"] += " (asked again)"
                yamlio.dump(os.path.join(research, "research.yaml"), doc)

            self.assertEqual(await reads("quotas", persons), [])   # Quotas does not watch the index
            self.assertEqual(await reads("family"), ["pane-family"])   # the Family does: read when shown
            self.assertEqual(await reads("family", persons), ["pane-family"])   # and at the tick
            self.assertEqual(await reads("quotas"), [])
            # the report in the file of the research: the list, which watches the index, reads when shown
            self.assertEqual(await reads("report"), ["pane-researches"])
            self.assertEqual(await reads("report", report), ["pane-report"])
            self.assertIn("A line added by the agent", app.screen.query_one("#report-viewer").document.source)
            self.assertEqual(await reads("file", meta), ["pane-researches"])
            self.assertIn("(asked again)", self.text(app.screen.query_one("#research-head")))


class Fast(AppCase):
    """T91: an unchanged report is not rendered again; a long log shows its last events at
    once, and the earlier ones on demand."""

    async def test_report_and_log_are_fast(self):
        import time

        from textual.widgets import Button, DataTable, MarkdownViewer

        from probandia import events
        from probandia.cli import tui_app

        research = os.path.join(self.dir, "families", "marchand", "research", RID)
        events.append(os.path.join(research, "events.jsonl"),
                      [events.make("instruction.added", {"text": f"note {i}"}, {"harness": "cli", "agent": "session"}, 2)
                       for i in range(20000)])
        shown = []

        def timed(show):   # the time a screen has shown what it read
            def timing(pane, *args):
                show(pane, *args)
                shown.append(time.monotonic())
            return timing

        took_log = []

        async def first_log(pilot):   # from the key to the log of screen 3 shown, the first time it is shown
            with mock.patch.object(tui_app.ResearchesPane, "show_log", timed(tui_app.ResearchesPane.show_log)):
                shown.clear()
                t0 = time.monotonic()
                await pilot.press("3")   # the log, in the file of the research
                await self.settle(pilot)
                took_log.append(shown[0] - t0)

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            await first_log(pilot)   # a log of 20 000 events: the last ones at once
            rows = self.table(app, "#research-log")
            self.assertEqual(len(rows), tui_app.LOG_PAGE)
            self.assertEqual(rows[-1][3], "note 19999")
            earlier = app.screen.query_one("#research-earlier", Button)
            self.assertTrue(earlier.display)
            self.assertIn(str(tui_app.LOG_PAGE), str(earlier.label))

            # the report, a tab of the file
            app.show("report")
            await self.settle(pilot)
            button = app.screen.query_one("#report-render", Button)
            self.assertIn(str(button.label), self.text(app.screen.query_one("#pane-report .title")))

            # a report of 136 KB appears, as render writes it
            text, n = "# Report on the ancestors of Louis MARCHAND\n\n", 0
            while len(text.encode("utf-8")) < 136 * 1024:
                n += 1
                text += f"## Section {n}\n\n" + f"Paragraph {n}: Louis MARCHAND, born in 1898 at Bourg-Vert. " * 20 + "\n\n"
            os.makedirs(os.path.join(research, "report"), exist_ok=True)
            with open(os.path.join(research, "report", "report.md"), "w", encoding="utf-8") as fh:
                fh.write(text)
            app.tick()
            viewer = app.screen.query_one("#report-viewer", MarkdownViewer)

            def headings():
                return [str(label) for _level, label, _id in viewer.table_of_contents.table_of_contents or []]
            await self.until(pilot, lambda: f"Section {n}" in headings(), tries=2000)   # rendered once
            await self.settle(pilot)
            read, started = tui_app.ReportPane.read, []

            def timed_read(pane, *args):
                started.append(time.monotonic())
                return read(pane, *args)

            with mock.patch.object(viewer.document, "update", wraps=viewer.document.update) as update, \
                    mock.patch.object(tui_app.ReportPane, "show", timed(tui_app.ReportPane.show)), \
                    mock.patch.object(tui_app.ReportPane, "read", timed_read):
                took = []
                for _turn in range(5):
                    app.refresh_screen()   # read again: the same report
                    await self.settle(pilot)
                    took.append(shown[-1] - started[-1])
                # from its read to its display, the best of five: the wait of the thread for a
                # free processor is not the report's, and other programs make it vary
                fast_enough(self, min(took), 0.05, took)
                update.assert_not_called()

            app.show("file")
            await self.settle(pilot)

            # the earlier ones on demand, the cursor on the same event
            log = app.screen.query_one("#research-log", DataTable)
            log.move_cursor(row=5)
            await self.calm(pilot)
            at = log.coordinate_to_cell_key(log.cursor_coordinate).row_key.value
            earlier.press()
            await self.settle(pilot)
            rows = self.table(app, "#research-log")
            self.assertEqual(len(rows), 2 * tui_app.LOG_PAGE)
            self.assertEqual(rows[0][3], f"note {20000 - 2 * tui_app.LOG_PAGE}")
            self.assertEqual(log.coordinate_to_cell_key(log.cursor_coordinate).row_key.value, at)
            self.assertEqual(rows[log.cursor_row][3], f"note {20000 - tui_app.LOG_PAGE + 5}")

        # the log, the best of three launches: as for the report, the wait for a free processor is
        # not the log's (the local CI runs some 34 processes on 16 cores; 0.03 to 0.10 s at rest)
        for _launch in range(2):
            if not TIMED or min(took_log) < 0.5:
                break
            async with self.app().run_test(size=self.SIZE) as pilot:
                await self.settle(pilot)
                await first_log(pilot)
        fast_enough(self, min(took_log), 0.5, took_log)


if __name__ == "__main__":
    unittest.main()
