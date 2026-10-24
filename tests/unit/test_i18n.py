import ast
import io
import os
import re
import tempfile
import unittest
from unittest import mock

from probandia import cli, i18n
from probandia.cli.commands import COMMANDS
from probandia.cli.output import Result
from probandia.i18n import extract
from tests import SRC

# A data line prints a value, not a message: "report.mode=living  # project …".
DATA_LINE = re.compile(r'^[a-z][a-z0-9_."<>-]*=')


def untranslated(output):
    """The human lines of an output rendered in the pseudo-locale that are not wrapped."""
    bad = []
    for line in output.splitlines():
        if not line.startswith("- "):
            continue
        text = line[2:]
        if DATA_LINE.match(text):
            continue
        if not (text.startswith(i18n.PSEUDO_OPEN) and text.endswith(i18n.PSEUDO_CLOSE)):
            bad.append(text)
    return bad


class PseudoLocale(unittest.TestCase):
    """Every message a command prints goes through _()."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.dir, "user")}
        self.addCleanup(i18n.activate, "en")

    def call(self, *argv, env=None, cwd=None):
        out = io.StringIO()
        code = cli.main(list(argv) + ["--lang", "xx"], stdout=out,
                        environ=dict(self.env, **(env or {})), cwd=cwd or self.dir)
        return code, out.getvalue()

    def assertWrapped(self, output):
        self.assertEqual(untranslated(output), [], output)

    def test_commands(self):
        outside = os.path.join(self.dir, "outside")
        os.makedirs(outside)
        project = os.path.join(self.dir, "p")
        os.makedirs(project)
        runs = [
            (["status"], {}, outside),
            (["config", "init"], {}, project),
            (["config", "init"], {}, project),
            (["config", "show", "--origin"], {"PROBANDIA_NOPE": "1"}, project),
            (["config", "show", "--all"], {}, project),
            (["config", "set", "cache.days", "3"], {}, project),
            (["config", "set", "tree.format", "md", "--user"], {}, project),
            (["config", "set", "report.mode", "diary"], {}, project),
            (["config", "set", "nope", "1"], {}, project),
            (["config", "unset", "roles.reader.model"], {}, project),
            (["config", "explain", "cache.days"], {}, project),
            (["config", "validate"], {}, project),
            (["config", "validate"], {"PROBANDIA_GRADE": "guru"}, project),
            (["lock", "take", "family:x"], {"PROBANDIA_SESSION": "a"}, project),
            (["lock", "take", "family:x"], {"PROBANDIA_SESSION": "b"}, project),
            (["lock", "renew", "family:x"], {"PROBANDIA_SESSION": "b"}, project),
            (["lock", "take", "person:x"], {}, project),
            (["resume"], {}, project),
            (["no-such-command"], {}, project),
        ]
        for argv, env, cwd in runs:
            with self.subTest(argv=argv):
                code, out = self.call(*argv, env=env, cwd=cwd)
                self.assertWrapped(out)

    def test_cut_output(self):
        spec = next(c for c in COMMANDS if c.name == "doctor")
        with mock.patch.object(spec, "handler",
                               lambda ctx: Result("OK", lines=[i18n._("x")] * 100)), \
                mock.patch("tempfile.tempdir", self.dir):   # outside a project, the whole output goes there
            code, out = self.call("doctor")
        self.assertWrapped(out)

    def test_a_string_without_underscore_is_caught(self):
        """The check fails on a message added without _()."""
        spec = next(c for c in COMMANDS if c.name == "doctor")
        with mock.patch.object(spec, "handler", lambda ctx: Result("OK", lines=["forgot it"])):
            code, out = self.call("doctor")
        self.assertEqual(untranslated(out), ["forgot it"])


# Errors of the engine: their message is shown to the user. Built-in exceptions
# (ValueError...) report programming errors and are not translated.
PROBANDIA_ERRORS = ("ProbandiaError", "UsageError", "NotInProject", "LockHeld", "LockLost",
                    "NetworkError", "SchemaError", "SchemaVersionError", "ConfigError")

# Calls whose text argument is shown to the user.
MESSAGE_KEYWORDS = ("help", "description", "epilog", "title")


def _is_text(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip()) \
        or isinstance(node, ast.JoinedStr)


def _shown(path, start):
    """``path`` relative to ``start``, or absolute when they lie on two drives (Windows)."""
    try:
        return os.path.relpath(path, start)
    except ValueError:
        return path


def static_findings(package=os.path.join(SRC, "probandia")):
    """Literal strings given to a message slot without _()."""
    found = []
    start = os.path.dirname(package)   # SRC for the package: "probandia/cli/…"
    for folder, dirs, files in os.walk(package):
        dirs[:] = [d for d in dirs if d not in ("_vendor", "__pycache__")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                slots = []
                if fname == "line" and node.args:
                    slots.append(node.args[0])
                if fname in PROBANDIA_ERRORS:
                    slots.extend(node.args[:1])
                if fname == "Result" and len(node.args) >= 3:
                    slots.append(node.args[2])
                for kw in node.keywords:
                    if kw.arg in MESSAGE_KEYWORDS or kw.arg == "lines":
                        slots.append(kw.value)
                for slot in slots:
                    items = slot.elts if isinstance(slot, (ast.List, ast.Tuple)) else [slot]
                    for item in items:
                        if _is_text(item):
                            found.append(f"{_shown(path, start)}:{item.lineno}")
    return found


class StaticCheck(unittest.TestCase):
    def test_no_literal_message(self):
        self.assertEqual(static_findings(), [])

    def literal(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "m.py"), "w", encoding="utf-8") as fh:
            fh.write('r.line("plain")\nr.line(_("ok"))\nraise UsageError(f"x {y}")\n')
        return tmp.name

    def test_the_check_sees_a_literal(self):
        folder = self.literal()
        self.assertEqual(static_findings(folder),
                         [os.path.join(os.path.basename(folder), "m.py") + ":1",
                          os.path.join(os.path.basename(folder), "m.py") + ":3"])

    def test_the_check_names_the_file_across_two_drives(self):
        # Windows: relpath fails when the folder and its parent lie on two drives (C: and D:)
        folder = self.literal()
        with mock.patch("os.path.relpath", side_effect=ValueError("path is on mount 'C:', start on mount 'D:'")):
            found = static_findings(folder)
        self.assertEqual(found, [os.path.join(folder, "m.py") + ":1", os.path.join(folder, "m.py") + ":3"])


class Catalogues(unittest.TestCase):
    def test_template_and_english_catalogue_are_up_to_date(self):
        for path, content in extract.targets().items():
            with self.subTest(path=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path), "run: python -m probandia.i18n.extract")
                with open(path, encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), content, "run: python -m probandia.i18n.extract")

    def test_french_catalogue_is_complete(self):
        """T114: every message of the engine has its French, never empty nor fuzzy (D-6), with the
        same placeholders."""
        path = os.path.join(i18n.repo_locales_dir(), "fr", "LC_MESSAGES", "probandia.po")
        with open(path, encoding="utf-8") as fh:
            self.assertNotIn("#, fuzzy", fh.read())
        french = i18n.read_po(path)
        ids = [m[0] for m in extract.messages()]
        self.assertEqual([m for m in ids if not french.get(m)], [])
        fields = re.compile(r"\{[^{}]*\}")
        self.assertEqual([m for m in ids if sorted(fields.findall(m)) != sorted(fields.findall(french[m]))], [])

    def test_english_translates_nothing(self):
        """T145: ``activate`` does not read the repository's English catalogue, which gives each message
        itself."""
        path = os.path.join(i18n.repo_locales_dir(), "en", "LC_MESSAGES", "probandia.po")
        self.assertEqual({k: v for k, v in i18n.read_po(path).items() if v and v != k and k}, {})

    def test_template_has_the_messages(self):
        ids = [m[0] for m in extract.messages()]
        self.assertIn("Formats of the report", ids)
        self.assertIn("(above grade)", ids)
        self.assertGreater(len(ids), 80)

    def test_po_round_trip_and_fallbacks(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        tmp = folder.name
        d = os.path.join(tmp, "fr", "LC_MESSAGES")
        os.makedirs(d)
        with open(os.path.join(d, "probandia.po"), "w", encoding="utf-8") as fh:
            fh.write('msgid ""\nmsgstr "Language: fr\\n"\n\n'
                     'msgid "(above grade)"\nmsgstr "(au-dessus du grade)"\n\n'
                     '#, fuzzy\nmsgid "a message of no catalogue"\nmsgstr "faux"\n\n'
                     'msgid "line one\\n"\n"line two"\nmsgstr ""\n"ligne un\\n"\n"ligne deux"\n')
        self.addCleanup(i18n.activate, "en")
        i18n.activate("fr-CA", [tmp])
        self.assertEqual(i18n._("(above grade)"), "(au-dessus du grade)")
        self.assertEqual(i18n._("a message of no catalogue"), "a message of no catalogue")
        self.assertEqual(i18n._("line one\nline two"), "ligne un\nligne deux")
        self.assertEqual(i18n.fallbacks("fr-CA"), ["fr-CA", "fr", "en"])

    def test_plurals(self):
        self.addCleanup(i18n.activate, "en")
        i18n.activate("en")
        self.assertEqual(i18n.ngettext("one pass", "{n} passes", 2), "{n} passes")
        i18n.activate("xx")
        self.assertEqual(i18n.ngettext("one pass", "{n} passes", 1), "⟦one pass⟧")
