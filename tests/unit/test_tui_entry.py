"""The dependency-free entry point of ``probandia tui``: the terminal checked first, the
missing extra explained, the command of a form run with the engine's prompts."""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from probandia import cli, i18n
from tests import ROOT
from tests.unit.test_tui_app import context, textual

# Textual missing: neither it nor the module of the application imports
NO_TEXTUAL = {"textual": None, "textual.app": None, "probandia.cli.tui_app": None}


class Terminal(io.StringIO):
    """A terminal with no descriptor, as a test can have one."""

    def isatty(self):
        return True


class EntryPoint(unittest.TestCase):
    def test_missing_extra_explains_installation(self):
        out = Terminal()
        with mock.patch.dict(sys.modules, NO_TEXTUAL):
            code = cli.main(["tui", "--output-format", "contract"], stdout=out, stdin=Terminal(), environ={},
                            cwd=tempfile.gettempdir())
        self.assertEqual(code, 2)
        self.assertIn('uv tool install "probandia[tui]"', out.getvalue())
        self.assertIn("REASON=tui-unavailable", out.getvalue())

    def test_no_terminal_builds_no_application(self):
        """T86: the output is not a terminal; the application is never built."""
        app_module = mock.Mock()
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"probandia.cli.tui_app": app_module}):
            code = cli.main(["tui"], stdout=out, stdin=Terminal(), environ={}, cwd=tempfile.gettempdir())
        self.assertEqual(code, 2)
        self.assertIn("REASON=tui-needs-terminal", out.getvalue())
        app_module.make_app.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "only Windows takes the NUL device for a terminal")
    def test_the_nul_device_is_not_a_terminal(self):
        """T86: ``probandia tui <NUL >NUL`` once started the application with no screen,
        and never returned."""
        from probandia.cli import tui_cmd
        from probandia.cli.asking import terminal

        app_module = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp:
            ctx = context(tmp, {})
            with open(os.devnull, encoding="utf-8") as nul_in, open(os.devnull, "w", encoding="utf-8") as nul_out:
                self.assertTrue(nul_in.isatty())   # what fooled the old check
                self.assertFalse(terminal(nul_in) or terminal(nul_out))
                ctx.stdin, ctx.stdout = nul_in, nul_out
                start = time.perf_counter()
                with mock.patch.dict(sys.modules, {"probandia.cli.tui_app": app_module}):
                    result = tui_cmd.run(ctx)
                elapsed = time.perf_counter() - start
            self.assertEqual((result.values["REASON"], result.exit_code), ("tui-needs-terminal", 2))
            self.assertLess(elapsed, 1)
            app_module.make_app.assert_not_called()
            env = {k: v for k, v in os.environ.items() if not k.startswith(("PROBANDIA_", "CLAUDE"))}
            env.update(PROBANDIA_CONFIG_DIR=os.path.join(tmp, "u"), PROBANDIA_DATA_DIR=os.path.join(tmp, "d"))
            launched = subprocess.run([sys.executable, os.path.join(ROOT, "run_probandia.py"), "tui"], cwd=tmp,
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, timeout=60)
            self.assertEqual(launched.returncode, 2)   # and the command itself returns

    def test_no_terminal_and_no_textual(self):
        """T86: without Textual and without a terminal, the terminal is what is missing first."""
        out = io.StringIO()
        with mock.patch.dict(sys.modules, NO_TEXTUAL):
            code = cli.main(["tui"], stdout=out, environ={}, cwd=tempfile.gettempdir())
        self.assertEqual(code, 2)
        self.assertIn("REASON=tui-needs-terminal", out.getvalue())
        self.assertNotIn("tui-unavailable", out.getvalue())

    def test_normal_cli_does_not_import_interfaces(self):
        script = '''
import sys
from probandia import cli
cli.build_parser()
assert not any(n.split('.')[0] in ('textual', 'rich') for n in sys.modules)
'''
        env = dict(os.environ, PYTHONPATH=os.path.abspath("src"))
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_execution_preserves_engine_code_and_terminal_prompts(self):
        from probandia.cli.tui_cmd import execute
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        with tempfile.TemporaryDirectory() as folder:
            out, inp = Terminal(), Terminal("fixture-tui-key\n")
            env = {"PROBANDIA_CONFIG_DIR": folder, "PROBANDIA_DATA_DIR": folder}
            code = execute(["keys", "set", "SERPER_API_KEY"], stdout=out, stdin=inp,
                           environ=env, cwd=folder)
            self.assertEqual(code, 0, out.getvalue())
            self.assertNotIn("fixture-tui-key", out.getvalue())
            with open(os.path.join(folder, ".env"), encoding="utf-8") as saved:
                self.assertIn("fixture-tui-key", saved.read())
            code = execute(["status"], stdout=out, stdin=inp, environ=env, cwd=folder)
            self.assertEqual(code, 6)

    def test_help_names_the_screens(self):
        """T108: ``tui --help``, in English then in French, names each screen with its key, the palette and the
        console, without importing Textual; with Textual, these keys are the application's bindings."""
        from probandia.cli.tui_cmd import PALETTE_KEY, RUN_KEY, SCREENS
        from probandia.i18n import _

        self.addCleanup(i18n.activate, "en")
        for lang, home in (("en", "Home"), ("fr", "Accueil")):
            out = io.StringIO()
            with mock.patch.dict(sys.modules, NO_TEXTUAL), contextlib.redirect_stdout(out), \
                    self.assertRaises(SystemExit) as exited:
                cli.main(["-l", lang, "tui", "--help"], stdout=io.StringIO(), environ={}, cwd=tempfile.gettempdir())
            self.assertEqual(exited.exception.code, 0)
            text = out.getvalue()
            self.assertIn(f"  1  {home} ", text)
            for n, (_name, title) in enumerate(SCREENS, 1):
                self.assertRegex(text, rf"\n  {n}  {re.escape(_(title))} ", (lang, title))
            for key in (PALETTE_KEY, RUN_KEY):
                self.assertIn(key.title(), text)
        if textual is None:
            return
        from probandia.cli.tui_app import bindings
        from probandia.cli.tui_forms import FormsScreen

        keys = {b.action: b.key for b in bindings()}
        self.assertEqual([keys[f"show('{name}')"] for name, _title in SCREENS],
                         [str(n) for n in range(1, len(SCREENS) + 1)])
        self.assertEqual(keys["command_palette"], PALETTE_KEY)
        self.assertEqual(next(b.key for b in FormsScreen.BINDINGS if b.action == "run"), RUN_KEY)

    def test_preview_redacts_sensitive_fields(self):
        from probandia.cli.tui_cmd import execute
        out = io.StringIO()
        with mock.patch.object(cli, "main", return_value=0) as main:
            execute(["some-command", "test-secret"], stdout=out, stdin=None, environ={},
                    cwd=tempfile.gettempdir(), preview_args=["some-command", "<redacted>"])
        self.assertNotIn("test-secret", out.getvalue())
        self.assertIn("test-secret", main.call_args.args[0])



if __name__ == "__main__":
    unittest.main()
