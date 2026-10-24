"""The settings in the terminal application (docs/parameters-tui.md): the Change window's control by the
setting's type, Reset, the file written, the filters, Add, Validate and Differences; the keys of the
providers set unseen; the screen Help, read from the engine."""
import os
import unittest
from unittest import mock

from tests.unit.test_tui_app import AppCase

try:
    import textual
except ImportError:
    textual = None


@unittest.skipUnless(textual, "requires the tui extra")
class Settings(AppCase):
    def settings(self, app):
        return [r[0] for r in self.table(app, "#config-settings")]

    async def opened(self, app, pilot, key):
        """The Change window of ``key``, from its line of the Settings."""
        app.screen.query_one("#config-settings").move_cursor(row=self.settings(app).index(key))
        app.screen.query_one("#config-set").press()
        await self.until(pilot, lambda: type(app.screen).__name__ == "ChangeScreen")

    async def confirmed(self, app, pilot, yes="y"):
        app.screen.query_one("#change-next").press()
        await self.asked(pilot)
        await pilot.press(yes)
        await self.settle(pilot)

    @staticmethod
    def written(answer, *action):
        return [c.args for c in answer.call_args_list if c.args[:2] in (action or (("config", "set"),
                                                                                    ("config", "unset")))]

    async def test_each_type_has_its_control(self):
        """A box for a bool, a list for an enum, a number for an int, boxes for a list of known items, a text
        otherwise: each gives config set the value as it takes it."""
        from textual.widgets import Checkbox, Input, Select, SelectionList

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for key, kind, value, text in (("hooks.guard", Checkbox, False, "false"),
                                               ("proof.standard", Select, "warn", "warn"),
                                               ("search.max_parallel", Input, "5", "5"),
                                               ("http.contact", Input, "me@example.org", "me@example.org")):
                    await self.opened(app, pilot, key)
                    control = app.screen.query_one("#change-value")
                    self.assertIsInstance(control, kind, key)
                    control.value = value
                    await self.confirmed(app, pilot)
                await self.opened(app, pilot, "report.formats")
                boxes = app.screen.query_one("#change-value", SelectionList)
                self.assertEqual(sorted(boxes.selected), ["html", "md"])
                boxes.deselect("html")
                boxes.select("json")
                await self.confirmed(app, pilot)
            self.assertEqual(self.written(answer), [
                ("config", "set", "hooks.guard", "false"), ("config", "set", "proof.standard", "warn"),
                ("config", "set", "search.max_parallel", "5"), ("config", "set", "http.contact", "me@example.org"),
                ("config", "set", "report.formats", "md,json")])
            rows = {r[0]: r[1] for r in self.table(app, "#config-settings")}
            self.assertEqual((rows["search.max_parallel"], rows["report.formats"]), ("5", "md,json"))

    async def test_a_refused_value_never_reaches_config_set(self):
        """Out of its bounds, or against its pattern: the window says why, with the registry's words, and stays."""
        from textual.widgets import Static

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for key, value, bounds in (("search.max_parallel", "12", "from 1 to 8"),
                                           ("http.contact", "nobody", None)):
                    await self.opened(app, pilot, key)
                    if bounds:
                        self.assertIn(bounds, " ".join(self.text(w) for w in app.screen.query(Static)))
                    app.screen.query_one("#change-value").value = value
                    app.screen.query_one("#change-next").press()
                    await self.calm(pilot)
                    self.assertEqual(type(app.screen).__name__, "ChangeScreen")
                    self.assertIn(f"invalid value '{value}' for {key}", self.text(app.screen.query_one("#change-error")))
                    await pilot.press("escape")
                    await self.settle(pilot)
            self.assertEqual(self.written(answer), [])

    async def test_an_ordered_list_is_reordered(self):
        from textual.widgets import SelectionList

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                await self.opened(app, pilot, "reading.readers")
                boxes = app.screen.query_one("#change-value", SelectionList)
                boxes.highlighted = 2   # jina
                app.screen.query_one("#change-up").press()
                await self.calm(pilot)
                self.assertEqual([boxes.get_option_at_index(i).value for i in range(boxes.option_count)],
                                 ["firecrawl", "jina", "tavily", "parallel"])
                self.assertEqual(boxes.highlighted, 1)
                await self.confirmed(app, pilot)
            self.assertEqual(self.written(answer), [("config", "set", "reading.readers", "firecrawl,jina,tavily,parallel")])

    async def test_the_file_chosen_then_reset(self):
        """Written in the local file (--local) or the user's (--user); Reset removes it from the file that sets
        it, once confirmed; a setting at its default has nothing to reset."""
        from textual.widgets import Select

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for layer in ("local", "user"):
                    await self.opened(app, pilot, "report.mode")
                    app.screen.query_one("#change-value", Select).value = "living"
                    app.screen.query_one("#change-layer", Select).value = layer
                    await self.confirmed(app, pilot)
                row = next(r for r in self.table(app, "#config-settings") if r[0] == "report.mode")
                self.assertEqual(row[1:3], ["living", "local"])   # local wins over user
                app.screen.query_one("#config-reset").press()
                await self.asked(pilot)
                await pilot.press("y")
                await self.settle(pilot)
                row = next(r for r in self.table(app, "#config-settings") if r[0] == "report.mode")
                self.assertEqual(row[1:3], ["living", "user"])
                app.screen.query_one("#config-settings").move_cursor(row=self.settings(app).index("tree.format"))
                app.screen.query_one("#config-reset").press()
                await self.calm(pilot)
                self.assertNotEqual(type(app.screen).__name__, "ConfirmScreen")
            self.assertEqual(self.written(answer), [("config", "set", "report.mode", "living", "--local"),
                                                    ("config", "set", "report.mode", "living", "--user"),
                                                    ("config", "unset", "report.mode", "--local")])
            with open(os.path.join(self.dir, "probandia.local.toml"), encoding="utf-8") as fh:
                self.assertNotIn("living", fh.read())

    async def test_outside_a_project_the_user_file_only(self):
        from textual.widgets import Select

        outside = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(outside)
        app = self.app(cwd=outside)
        async with app.run_test(size=self.SIZE) as pilot:
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                app.pane("config").change("report.mode")   # config show needs a project: a key given
                await self.until(pilot, lambda: type(app.screen).__name__ == "ChangeScreen")
                self.assertTrue(app.screen.query_one("#change-layer", Select).disabled)
                app.screen.query_one("#change-value", Select).value = "living"
                await self.confirmed(app, pilot)
            self.assertEqual(self.written(answer), [("config", "set", "report.mode", "living", "--user")])

    async def test_filters(self):
        from textual.widgets import Checkbox, Select

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            every = self.table(app, "#config-settings")
            app.screen.query_one("#config-by-grade", Select).value = "expert"
            await self.settle(pilot)
            rows = self.table(app, "#config-settings")
            self.assertTrue(rows and len(rows) < len(every) and all(r[3] == "expert" for r in rows))
            app.screen.query_one("#config-by-domain", Select).value = "hooks"
            await self.settle(pilot)
            self.assertEqual([r[0] for r in self.table(app, "#config-settings")],
                             ["hooks.guard", "hooks.digest", "hooks.journal", "hooks.verify"])
            app.screen.query_one("#config-by-grade", Select).clear()
            app.screen.query_one("#config-by-domain", Select).clear()
            app.screen.query_one("#config-changed", Checkbox).value = True
            await self.settle(pilot)
            changed = [r for r in every if r[2] != "default"]
            self.assertEqual(self.table(app, "#config-settings"), changed)

    async def test_add_the_rate_of_a_host(self):
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for host, rate in (("not a host", "5/min"), ("archives.example.org", "5 a minute"),
                                   ("archives.example.org", "5/min")):
                    app.screen.query_one("#config-add").press()
                    await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                    app.screen.query_one("#add-host").value = host
                    app.screen.query_one("#add-rate").value = rate
                    app.screen.query_one("#ask-next").press()
                    await self.calm(pilot)
                    if rate == "5/min" and host != "not a host":
                        await self.asked(pilot)
                        await pilot.press("y")
                        await self.settle(pilot)
                    else:
                        self.assertIn("not a host name" if host == "not a host" else "invalid value",
                                      self.text(app.screen.query_one("#config-explain")))
            self.assertEqual(self.written(answer), [("config", "set", "hosts.archives.example.org.rate", "5/min")])
            self.assertIn("hosts.archives.example.org.rate", self.settings(app))

    async def test_validate_differences_and_the_wizard_cancelled(self):
        settings = os.path.join(self.dir, "probandia.toml")
        with open(settings, encoding="utf-8") as fh:
            before = fh.read()
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("config")
            await self.settle(pilot)
            app.screen.query_one("#config-validate").press()
            await self.settle(pilot)
            self.assertIn("every layer is valid", self.text(app.screen.query_one("#config-explain")))
            app.screen.query_one("#config-diff").press()
            await self.settle(pilot)
            self.assertIn("Every setting has its default value", self.text(app.screen.query_one("#config-explain")))
            app.screen.query_one("#config-wizard").press()
            await self.asked(pilot)
            await pilot.press("y")
            await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")   # its first question
            await pilot.press("escape")
            await self.settle(pilot)
            self.assertIn("nothing was done", " ".join(n.message for n in app._notifications))
        with open(settings, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)


@unittest.skipUnless(textual, "requires the tui extra")
class ProviderKeys(AppCase):
    async def test_a_key_set_is_never_shown(self):
        """Set the key: the .env chosen, a confirmation, then the key typed in the masked field keys set opens;
        it is written, and never in a command's arguments, a notification, a text or a table. Remove the key
        takes it out of its file, once confirmed."""
        from textual.widgets import DataTable, Input, Select, Static

        secret = "fixture-secret-9876543210"
        user_env = os.path.join(self.env["PROBANDIA_CONFIG_DIR"], ".env")
        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("providers")
            await self.settle(pilot)
            self.assertIn("keys read from", self.text(app.screen.query_one("#pane-providers .title")))
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                keys = [r[0] for r in self.table(app, "#providers-keys")]
                app.screen.query_one("#providers-keys").move_cursor(row=keys.index("SERPER_API_KEY"))
                app.screen.query_one("#key-set").press()
                await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                app.screen.query_one("#key-where", Select).value = "user"
                app.screen.query_one("#ask-next").press()
                await self.asked(pilot)
                await pilot.press("y")
                await self.until(pilot, lambda: type(app.screen).__name__ == "AskScreen")
                field = app.screen.query_one("#answer", Input)
                self.assertTrue(field.password)
                field.value = secret
                await pilot.press("enter")
                await self.settle(pilot)
                with open(user_env, encoding="utf-8") as fh:
                    self.assertIn(f"SERPER_API_KEY={secret}", fh.read())
                row = next(r for r in self.table(app, "#providers-keys") if r[0] == "SERPER_API_KEY")
                self.assertEqual(row[1:3], ["yes", "user .env"])
                seen = [repr(c) for c in answer.call_args_list] + [n.message for n in app._notifications]
                seen += [str(c) for t in app.screen.query(DataTable) for i in range(t.row_count) for c in t.get_row_at(i)]
                seen += [self.text(w) for w in app.screen.query(Static)]
                self.assertEqual([x for x in seen if secret in x], [])
                self.assertIn(("keys", "set", "SERPER_API_KEY"), [c.args for c in answer.call_args_list])

                app.screen.query_one("#key-unset").press()
                await self.asked(pilot)
                await pilot.press("y")
                await self.settle(pilot)
            with open(user_env, encoding="utf-8") as fh:
                self.assertNotIn("SERPER_API_KEY", fh.read())

    async def test_cap_cache_life_and_stale(self):
        from textual.widgets import Input

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.show("providers")
            await self.settle(pilot)
            stale = {x["provider"] for x in app.answer("providers", "stale")["data"]["stale"]}
            rows = self.table(app, "#providers-list")
            self.assertEqual({r[0] for r in rows if r[-1] == "yes"}, stale)
            app.screen.query_one("#providers-list").move_cursor(row=[r[0] for r in rows].index("serper"))
            with mock.patch.object(app, "answer", wraps=app.answer) as answer:
                for button, value in (("provider-cap", "100"), ("provider-ttl", "3")):
                    app.screen.query_one(f"#{button}").press()
                    await self.until(pilot, lambda: type(app.screen).__name__ == "ChangeScreen")
                    app.screen.query_one("#change-value", Input).value = value
                    app.screen.query_one("#change-next").press()
                    await self.asked(pilot)
                    await pilot.press("y")
                    await self.settle(pilot)
            self.assertEqual([c.args for c in answer.call_args_list if c.args[:2] == ("config", "set")],
                             [("config", "set", "providers.serper.monthly_cap", "100"),
                              ("config", "set", "providers.serper.cache_ttl", "3")])


@unittest.skipUnless(textual, "requires the tui extra")
class Help(AppCase):
    async def test_help_lists_every_setting_and_takes_one_to_the_settings(self):
        from textual.widgets import DataTable, TabbedContent

        from probandia.config import registry

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            await pilot.press("7")
            await self.settle(pilot)
            rows = self.table(app, "#help-settings")
            self.assertEqual(sorted(r[0] for r in rows), sorted(s.key for s in registry.SETTINGS))
            for key, line in (("report.mode", "report.mode"), ("roles.<role>.model", "roles.orchestrator.model")):
                app.show("help")
                await self.settle(pilot)
                table = app.screen.query_one("#help-settings", DataTable)
                table.move_cursor(row=[r[0] for r in self.table(app, "#help-settings")].index(key))
                table.focus()
                await pilot.press("enter")
                await self.settle(pilot)
                self.assertEqual(app.screen.query_one("#screens", TabbedContent).active, "config")
                settings = app.screen.query_one("#config-settings", DataTable)
                self.assertEqual(str(settings.get_row_at(settings.cursor_row)[0]), line)
            for part, tid, count in (("help-layers", "#help-layers", 7),
                                     ("help-variables", "#help-variables", len(registry.OTHER_VARIABLES)),
                                     ("help-providers", "#help-conditions", 5)):
                app.show(part)
                await self.settle(pilot)
                self.assertEqual(len(self.table(app, tid)), count, part)
            app.show("help-options")
            await self.settle(pilot)
            self.assertIn("-p, --project <path>", [r[0] for r in self.table(app, "#help-options")])
