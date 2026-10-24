"""The console's forms (T85): drawn from the engine's parser, built on demand, run headless."""
import argparse
import os
import unittest
from unittest import mock

from probandia import cli, i18n
from tests.unit.test_tui_app import AppCase, textual


def form(*words):
    from probandia.cli.tui_forms import build_form

    return build_form(cli.build_parser(), words)


def values(f, **given):
    """One value per field of ``f``: ``given`` by destination, empty otherwise."""
    empty = {"flag": False, "optional": (False, "")}
    return [given.get(x.dest, empty.get(x.kind)) for x in f.fields]


@unittest.skipUnless(textual, "requires the tui extra")
class Schemas(unittest.TestCase):
    """The fields of a form and the command line they make, without a screen."""

    def test_fields_follow_the_parser(self):
        usage = form("usage")
        kinds = {x.name: x.kind for x in usage.fields}
        self.assertEqual(kinds["--families"], "flag")
        self.assertEqual(kinds["--watch"], "optional")
        self.assertEqual(kinds["--alert"], "optional")
        self.assertNotIn("--json", kinds)          # the global options are the application's
        self.assertNotIn("--project", kinds)
        self.assertEqual(usage.argv(values(usage, families=True)), ["usage", "--families"])
        self.assertEqual(usage.argv(values(usage, watch=(True, ""))), ["usage", "--watch"])
        self.assertEqual(usage.argv(values(usage, watch=(True, "5"), provider="tavily")),
                         ["usage", "tavily", "--watch", "5"])

    def test_choices_lists_and_defaults(self):
        verify = form("verify")
        self.assertEqual(verify.argv(values(verify, rule="V-1 V-2", research="r1")),
                         ["verify", "r1", "--rule", "V-1", "--rule", "V-2"])
        new = form("new")
        mode = next(x for x in new.fields if x.option == "--mode")
        self.assertEqual(mode.kind, "choice")
        self.assertEqual(next(x for x in new.fields if x.option == "--agents").kind, "number")
        keys = form("keys")   # a positional left at its default stays: the next one keeps its place
        self.assertEqual(keys.argv(values(keys, action="list", name="TAVILY_API_KEY")),
                         ["keys", "list", "TAVILY_API_KEY"])
        calls = next(x for x in form("quota").fields if x.option == "--calls")
        self.assertEqual(calls.words("1"), [])   # an option at its default is left out

    def test_actions_of_a_command(self):
        config = form("config")
        self.assertIn("set", config.actions)
        setting = form("config", "set")
        self.assertEqual([x.dest for x in setting.fields if x.positional], ["key", "value"])
        self.assertEqual(setting.missing(values(setting, key="report.mode")).dest, "value")
        self.assertEqual(setting.argv(values(setting, key="report.mode", value="living", user=True)),
                         ["config", "set", "report.mode", "living", "--user"])

    def test_a_secret_is_redacted(self):
        from probandia.cli.tui_forms import Form

        p = argparse.ArgumentParser(prog="x")
        p.add_argument("--token")
        p.add_argument("--name")
        f = Form(("x",), p)
        given = values(f, token="s3cr3t-value", name="Hugo")
        self.assertEqual(f.argv(given), ["x", "--token", "s3cr3t-value", "--name", "Hugo"])
        self.assertEqual(f.argv(given, redact=True), ["x", "--token", "<redacted>", "--name", "Hugo"])


class Forms(AppCase):
    """The console's screen, over the application."""

    def outside(self):
        return self.app(cwd=self.tmp.name)

    async def test_every_user_command_and_no_engine_command(self):
        from textual.widgets import Tree

        app = self.outside()
        expected = [c.name for c in cli.commands.COMMANDS if not c.engine and c.name != "tui"]
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms()
            await self.until(pilot, lambda: app.screen.current)
            tree = app.screen.query_one("#forms-commands", Tree)
            self.assertEqual([str(n.label) for n in tree.root.children], expected)
            for node in list(tree.root.children):
                tree.move_cursor(node)
                await self.until(pilot, lambda: app.screen.current.words == (str(node.label),))
                self.assertIn("probandia " + str(node.label), self.text(app.screen.query_one("#form-description")))

    async def test_the_cursor_runs_through_the_commands_then_quits(self):
        """Forms mounted and removed faster than they are drawn, then the application
        closed in the middle: nothing fails (the Select of Textual 0.89 did)."""
        from textual.widgets import Tree

        app = self.outside()
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms()
            await pilot.pause()
            tree = app.screen.query_one("#forms-commands", Tree)
            for node in list(tree.root.children):
                tree.move_cursor(node)
            await pilot.press(*["down", "up"] * 10)
            await app.action_quit()
        self.assertFalse(app.is_running)

    async def test_french_labels_and_help(self):
        from textual.widgets import Input, Tree

        i18n.activate("fr")
        self.addCleanup(i18n.activate, "en")
        app = self.outside()
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms("usage")
            await self.until(pilot, lambda: app.screen.current.words == ("usage",))
            self.assertEqual(app.screen.query_one("#forms-search", Input).placeholder, "Chercher…")
            await self.until(pilot, lambda: str(app.screen.query_one("#forms-commands", Tree).cursor_node.label) == "usage")
            await pilot.press("f1")
            await self.calm(pilot)
            self.assertEqual(type(app.screen).__name__, "CommandHelp")
            self.assertIn("Aide de la commande", str(app.screen.query_one("VerticalScroll").border_title))
            await pilot.press("escape")
            await self.calm(pilot)
            self.assertEqual(type(app.screen).__name__, "FormsScreen")

    async def ran(self, pilot):
        """Pauses until the console's command has ended and its output fills the panel."""
        await self.until(pilot, lambda: not pilot.app.screen.running
                         and "Exit code" in self.text(pilot.app.screen.query_one("#form-result")), tries=2000)
        return self.text(pilot.app.screen.query_one("#form-result"))

    async def asked(self, pilot, screen):
        await self.until(pilot, lambda: type(pilot.app.screen).__name__ == screen, tries=2000)

    async def test_the_console_runs_in_place(self):
        """T107: a form's command runs in the application, which stays open: its line, then its readable
        output in a panel. Its yes-or-no question comes up in ConfirmScreen, and n gives the engine's exit
        code; the key it asks for is typed in a masked field, and shown nowhere. Commands follow one another
        without launching the application again; the audit hook (T109) sees their writes, and only theirs."""
        from textual.widgets import Checkbox, Input, Select, Tree

        from probandia.errors import EXIT_STOP
        from tests.unit.test_tui_app import CHANGES, audited

        secret = "fixture-console-key-0123456789"
        env_file = os.path.join(self.env["PROBANDIA_CONFIG_DIR"], ".env")
        app = self.outside()
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms("usage")
            await self.until(pilot, lambda: app.screen.query("FieldRow"))
            row = next(r for r in app.screen.query("FieldRow") if r.field.option == "--families")
            row.query_one(Checkbox).value = True   # the checkbox comes from the parser, not from a form of its own
            await self.calm(pilot)
            self.assertEqual(self.text(app.screen.query_one("#form-preview")), "$ probandia usage --families")
            with mock.patch.object(app, "copy_to_clipboard") as copy:
                await pilot.press("ctrl+y")
            copy.assert_called_once_with("probandia usage --families")
            with audited(app) as done:
                await pilot.press("ctrl+r")
                out = await self.ran(pilot)
                self.assertTrue(out.startswith("Command: probandia usage --families --output-format human\n"), out)
                self.assertNotIn("STATUS=", out)
                self.assertIn("Exit code: 0", out)
                self.assertTrue(app.is_running)
                self.assertEqual(type(app.screen).__name__, "FormsScreen")

                tree = app.screen.query_one("#forms-commands", Tree)   # the next command, in the same console
                tree.move_cursor(next(n for n in tree.root.children if n.data == ("keys",)))
                await self.until(pilot, lambda: app.screen.current.words == ("keys",))
                rows = {r.field.dest: r for r in app.screen.query("FieldRow")}
                rows["action"].query_one(Select).value = "set"
                rows["name"].query_one(Input).value = "FIXTURE_API_KEY"
                await self.calm(pilot)
                await pilot.press("ctrl+r")
                await self.asked(pilot, "AskScreen")
                self.assertTrue(app.screen.query_one(Input).password)
                await pilot.press(*secret)
                self.assertEqual(app.screen.query_one(Input).value, secret)
                self.assertNotIn(secret, app.export_screenshot())   # typed unseen
                await pilot.press("enter")
                out = await self.ran(pilot)
                self.assertIn("Command: probandia keys set FIXTURE_API_KEY --output-format human\n", out)
                self.assertIn("Exit code: 0", out)
                with open(env_file, encoding="utf-8") as fh:
                    self.assertIn(secret, fh.read())
                self.assertNotIn(secret, self.text(app.screen.query_one("#form-preview")) + out)
                self.assertNotIn(secret, app.export_screenshot())
                written = list(done)

                await pilot.press("ctrl+r")   # once more: the key is there, the engine asks before replacing it
                await self.asked(pilot, "ConfirmScreen")
                self.assertIn("FIXTURE_API_KEY is already set", self.text(app.screen.query_one("#question")))
                await pilot.press("n")
                out = await self.ran(pilot)
                self.assertIn("nothing was done", out)
                self.assertIn(f"Exit code: {EXIT_STOP}", out)
                self.assertEqual(done, written)   # n: nothing written
                self.assertTrue(app.is_running)
        self.assertTrue(written)
        folder = self.env["PROBANDIA_CONFIG_DIR"]
        for event, path, argv in written:   # the key's file, the copy written first, its folder made: by keys set
            self.assertIn(event, {"open", *CHANGES}, (event, path))
            self.assertEqual(argv[0][:2], ["keys", "set"], (event, path))
            self.assertIn(folder, (path, os.path.dirname(path)), (event, path))

    async def test_the_console_asks_its_choices(self):
        """T107: the questions of an ASK, in the application's window: a list for fixed choices, a field for a
        number that may be another; the command runs again with the answers."""
        from textual.widgets import Input, Select

        from probandia.research import find_research

        app = self.app()
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms("new")
            await self.until(pilot, lambda: app.screen.query("FieldRow"))
            next(r for r in app.screen.query("FieldRow") if r.field.dest == "question").query_one(Input).value = \
                "Who were the parents of Henri Marchand?"
            await pilot.press("ctrl+r")
            await self.asked(pilot, "AskScreen")
            self.assertIn("Who runs this research?", self.text(app.screen.query("Static").first()))
            mode = app.screen.query_one(Select)
            self.assertEqual(mode.value, "session")   # the default the command offers
            mode.value = "team"
            app.screen.query_one("#ask-next").press()
            for number in ("7", "3"):   # agents, passes: numbers, another one allowed
                await self.until(pilot, lambda: app.screen.query(Input) and type(app.screen).__name__ == "AskScreen",
                                 tries=2000)
                field = app.screen.query_one(Input)
                field.value = number
                app.screen.query_one("#ask-next").press()
                await self.until(pilot, lambda: not field.is_attached, tries=2000)
            out = await self.ran(pilot)
            self.assertIn("Exit code: 0", out)
        folder = os.path.join(self.dir, "families", "marchand", "research")
        rid = next(x for x in os.listdir(folder) if "henri" in x)
        run = find_research(self.dir, rid).meta()["run"]
        self.assertEqual((run["mode"], run["max_agents"]), ("team", 7))

    async def test_a_required_field_left_empty(self):
        app = self.outside()
        async with app.run_test(size=self.SIZE) as pilot:
            app.open_forms("find")
            await self.until(pilot, lambda: app.screen.query("FieldRow"))
            await pilot.press("ctrl+r")
            await self.calm(pilot)
            self.assertTrue(app.is_running)
            self.assertFalse(app.screen.running or app.screen.query_one("#form-output").display)   # nothing ran
            self.assertEqual(app.focused.parent.field.dest, "name")

    async def test_forms_are_built_on_demand(self):
        """No command's form is described while the console is not open: the screens,
        the palette's list of forms and the help describe none."""
        from probandia.cli import tui_app, tui_forms

        app = self.app()
        with mock.patch.object(tui_forms, "build_form", wraps=tui_forms.build_form) as build:
            async with app.run_test(size=self.SIZE) as pilot:
                for name, _title in tui_app.SCREENS:
                    app.show(name)
                    await self.calm(pilot)
                await pilot.press("ctrl+p")
                await self.calm(pilot)
                await pilot.press(*"Form: us")
                await pilot.pause(0.3)
                await pilot.press("escape")
                await self.calm(pilot)
                self.assertEqual(build.call_count, 0)
                app.open_forms("usage")
                await self.until(pilot, lambda: app.screen.current)
                self.assertEqual([c.args[1] for c in build.call_args_list], [("usage",)])


if __name__ == "__main__":
    unittest.main()
