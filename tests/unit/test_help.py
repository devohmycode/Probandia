import contextlib
import io
import unittest

from probandia import cli, i18n
from probandia.cli import helptext


class Terminal(io.StringIO):
    def isatty(self):
        return True


def run(argv, terminal=True):
    out = Terminal() if terminal else io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = cli.main(argv, stdout=out, environ={})
        except SystemExit as stop:   # argparse prints its help and exits
            code = stop.code
    return code, out.getvalue()


class Help(unittest.TestCase):
    """The readable help groups the commands; the contract's lists them all (cli.md § 6.8)."""

    def setUp(self):
        i18n.activate("en")

    def test_readable_help_hides_the_engine(self):
        code, out = run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("Research", out)
        self.assertIn("Genealogist's tools", out)
        self.assertNotIn("[engine]", out)
        self.assertNotIn("  propose", out)

    def test_with_another_global_option(self):
        self.assertIn("Research", run(["--help", "--plain"])[1])

    def test_all_shows_every_command(self):
        out = run(["--help", "--all"])[1]
        self.assertIn("[engine] provider search", out)

    def test_contract_help_is_unchanged(self):
        out = run(["--help"], terminal=False)[1]
        self.assertIn("[engine] provider search", out)
        for spec in cli.commands.COMMANDS:
            self.assertIn(spec.name, out)

    def test_every_grouped_command_exists(self):
        names = {c.name for c in cli.commands.COMMANDS}
        for _title, group in helptext.GROUPS:
            self.assertLessEqual(set(group), names)

    def test_every_user_command_is_in_a_group(self):
        """T115: the readable help names every command a person types."""
        grouped = {n for _title, group in helptext.GROUPS for n in group}
        self.assertEqual([c.name for c in cli.commands.COMMANDS if not c.engine and c.name not in grouped], [])

    def test_every_action_is_named_in_its_help_line(self):
        """T115: each choice of a command's action, as it is typed, in its line of help."""
        import argparse
        import re

        sub = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        for spec in cli.commands.COMMANDS:
            p = sub.choices[spec.name]
            nested = next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)
            action = next((a for a in p._actions if a.dest == "action"), None)
            choices = list(nested.choices if nested else action.choices or [] if action else [])
            missing = [x for x in choices if not re.search(r"(?<![\w-])" + re.escape(x) + r"(?![\w-])", spec.help)]
            self.assertEqual(missing, [], f"{spec.name}: {spec.help}")

    def test_every_action_is_named_in_its_slash_command(self):
        """version-1.0.0 T193: the argument-hint of commands/<name>.md names each choice of the command's action."""
        import argparse
        import os
        import re

        from tests import ROOT

        sub = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        folder = os.path.join(ROOT, "commands")
        checked = 0
        for name in sorted(os.listdir(folder)):
            p = sub.choices[name[:-3]]
            action = next((a for a in p._actions if a.dest == "action"), None)
            if action is None or not action.choices:
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                hint = re.search(r'^argument-hint: "(.*)"$', fh.read(), re.M).group(1)
            missing = [x for x in action.choices if not re.search(r"(?<![\w-])" + re.escape(x) + r"(?![\w-])", hint)]
            self.assertEqual(missing, [], name)
            checked += 1
        self.assertGreaterEqual(checked, 6)

    def test_examples_under_each_user_command(self):
        for spec in cli.commands.COMMANDS:
            if spec.slash:
                out = run([spec.name, "--help"], terminal=False)[1]
                self.assertIn("examples:", out, spec.name)

    def test_subjects(self):
        for subject in helptext.TOPICS:
            code, out = run(["help", subject], terminal=False)
            self.assertEqual(code, 0, out)
            self.assertGreaterEqual(out.count("\n- "), 3, subject)
        self.assertIn("probandia help quotas", run(["help"], terminal=False)[1])

    def test_settings_subject_reads_the_code(self):
        """help settings (docs/parameters-tui.md): every setting of the registry, the seven layers highest
        first, the conditions by the reasons of catalogue.why_unusable, the variables and the common options."""
        import json

        from probandia.config import LAYERS, registry

        code, out = run(["help", "settings", "--json"], terminal=False)
        self.assertEqual(code, 0, out)
        data = json.loads(out)["data"]
        self.assertEqual([x["key"] for x in data["settings"]], [s.key for s in registry.SETTINGS])
        mode = next(x for x in data["settings"] if x["key"] == "report.mode")
        self.assertEqual((mode["domain"], mode["grade"], mode["default"], mode["variable"], mode["option"]),
                         ("report", "essential", "journal", "PROBANDIA_REPORT_MODE", "--report-mode"))
        self.assertEqual([x["layer"] for x in data["layers"]], list(reversed(LAYERS)))
        self.assertEqual({x["reason"] for x in data["conditions"]},
                         {"not-enabled", "card-required", "content-reuse", "no-key"})
        self.assertEqual([x["variable"] for x in data["variables"]], list(registry.OTHER_VARIABLES))
        self.assertIn("-p, --project <path>", [x["option"] for x in data["options"]])
        self.assertIn("probandia help settings", run(["help"], terminal=False)[1])

    def test_files_names_the_folder_export_writes_to(self):
        import os
        import shutil
        import tempfile

        from tests import ROOT

        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), project)
            out = io.StringIO()
            code = cli.main(["export", "gedcom7", "--family", "hugo"], stdout=out, cwd=project,
                            environ={"PROBANDIA_CONFIG_DIR": os.path.join(tmp, "user")})
            self.assertEqual(code, 0, out.getvalue())
            written = next(line.split("=", 1)[1] for line in out.getvalue().splitlines() if "FILE=" in line)
        folder = written.replace(os.sep, "/").split("/")[0] + "/"
        lines = helptext.TOPICS["files"]
        self.assertTrue(any(line.startswith(folder) and "export" in line for line in lines), (folder, lines))
        self.assertFalse(any(line.startswith("families/") and "export" in line for line in lines), lines)

    def test_commands_cited_by_the_subjects_parse(self):
        """Each command a subject cites, such as ``config grade advanced``, is one the parser takes,
        and the setting it names exists: its words from the command's name, the fewest that parse."""
        import re

        from probandia.config import registry
        from probandia.errors import UsageError

        parser = cli.build_parser()
        names = {spec.name for spec in cli.commands.COMMANDS}
        cited = 0
        for subject, lines in helptext.TOPICS.items():
            for line in lines:
                for m in re.finditer(r"(?<![\w.-])([a-z][a-z-]*)((?: [a-z0-9][\w.-]*)+)", line):
                    if m.group(1) not in names:
                        continue
                    words = [m.group(1)] + m.group(2).split()
                    for n in range(1, len(words) + 1):
                        try:
                            with contextlib.redirect_stderr(io.StringIO()):
                                args = parser.parse_args(words[:n])
                        except (SystemExit, UsageError):
                            continue
                        break
                    else:
                        self.fail(f"help {subject}: {' '.join(words)} does not parse")
                    if getattr(args, "key", None) is not None and m.group(1) == "config":
                        self.assertIsNotNone(registry.lookup(args.key), f"help {subject}: {' '.join(words[:n])}")
                    cited += 1
        self.assertGreaterEqual(cited, 4)


if __name__ == "__main__":
    unittest.main()
