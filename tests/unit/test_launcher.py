import os
import subprocess
import sys
import unittest

from tests import ROOT

LAUNCHER = os.path.join(ROOT, "run_probandia.py")


def run(*args, python=sys.executable, cwd=None, env=None):
    """Runs the launcher in an isolated interpreter (-I: no user site, no PYTHON* variables)."""
    return subprocess.run(
        [python, "-I", LAUNCHER, *args],
        capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env,
    )


class Launcher(unittest.TestCase):
    """The launcher puts src/ on sys.path and calls probandia.cli.main."""

    def test_help_runs(self):
        r = run("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("probandia", r.stdout)

    def test_python_dash_m(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
        r = subprocess.run([sys.executable, "-m", "probandia", "--version"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("probandia", r.stdout)

    def test_old_python_is_refused_in_one_line(self):
        """T160: under Python 3.10 the launcher says so, code 2, before any import of the engine."""
        code = ("import runpy, sys\n"
                "sys.version_info = (3, 10, 12, 'final', 0)\n"
                f"sys.argv = [{LAUNCHER!r}, '--version']\n"
                f"runpy.run_path({LAUNCHER!r}, run_name='__main__')\n")
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(r.stderr, "Python 3.11 or later is required (this is Python 3.10)\n")
        self.assertEqual(r.stdout, "")

    def test_no_top_level_bin(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "bin")))


class HookOutsideProject(unittest.TestCase):
    """token-economy G3: outside any project, a hook answers without loading the engine."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(self.out)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("PROBANDIA_")}
        self.env.update(PROBANDIA_CONFIG_DIR=os.path.join(self.tmp.name, "user"), PROBANDIA_SESSION="test")

    def hook(self, cwd, *args, tool="Bash"):
        """(what the hook printed, the probandia modules it loaded)."""
        import json

        code = ("import runpy, sys\n"
                f"sys.argv = [{LAUNCHER!r}, 'hook', *{list(args)!r}]\n"
                "try:\n"
                f"    runpy.run_path({LAUNCHER!r}, run_name='__main__')\n"
                "except SystemExit:\n"
                "    pass\n"
                "sys.stderr.write(' '.join(m for m in sys.modules if m.startswith('probandia')))\n")
        payload = json.dumps({"tool_name": tool, "tool_input": {"command": "ls"}, "cwd": cwd})
        r = subprocess.run([sys.executable, "-I", "-c", code], input=payload, capture_output=True, text=True,
                           encoding="utf-8", cwd=cwd, env=self.env)
        return r.stdout, r.stderr.split()

    def test_outside_a_project_the_engine_is_not_loaded(self):
        for args, answer in ((("guard",), ""), (("guard", "--harness", "antigravity"), '{"allowTool": true}\n'),
                             (("log",), ""), (("verify",), ""), (("digest",), ""), (("session",), "")):
            with self.subTest(args=args):
                out, modules = self.hook(self.out, *args)
                self.assertEqual(out, answer)
                self.assertNotIn("probandia.cli", modules)
                self.assertNotIn("probandia.hooks", modules)
        self.assertEqual(os.listdir(self.out), [])   # nothing written
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "user")))

    def test_inside_a_project_or_for_a_learned_skill_the_engine_runs(self):
        import shutil

        project = os.path.join(self.tmp.name, "project")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), project)
        self.assertIn("probandia.hooks", self.hook(os.path.join(project, "families"), "guard")[1])
        self.assertIn("probandia.hooks", self.hook(self.out, "log", tool="Skill")[1])   # counted anywhere

    def test_the_launcher_knows_the_hook_functions_and_the_learned_tools(self):
        import runpy

        from probandia import hooks

        launcher = runpy.run_path(LAUNCHER)
        self.assertEqual(tuple(launcher["HOOK_FUNCTIONS"]), hooks.FUNCTIONS)
        self.assertEqual(set(launcher["LEARNED_TOOLS"]), set(hooks.LEARNED_TOOLS))


class LazyStart(unittest.TestCase):
    """T145: a launch imports its own command only: ``--version`` and the guard load no ``*_cmd`` module."""

    setUp = HookOutsideProject.setUp

    def launch(self, cwd, args, stdin=""):
        code = ("import runpy, sys\n"
                f"sys.argv = [{LAUNCHER!r}, *{list(args)!r}]\n"
                "try:\n"
                f"    runpy.run_path({LAUNCHER!r}, run_name='__main__')\n"
                "except SystemExit:\n"
                "    pass\n"
                "sys.stderr.write(' '.join(m for m in sys.modules if m.startswith('probandia')))\n")
        r = subprocess.run([sys.executable, "-I", "-c", code], input=stdin, capture_output=True, text=True,
                           encoding="utf-8", cwd=cwd, env=dict(self.env, CLAUDECODE="1"))
        return r.stdout, r.stderr.split()

    def test_version_and_guard_load_no_command_module(self):
        import json
        import shutil

        project = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), project)
        payload = json.dumps({"session_id": "t145", "cwd": project, "hook_event_name": "PreToolUse",
                              "tool_name": "Bash", "tool_input": {"command": "python .probandia/pb.py status"}})
        for args, stdin in ((["--version"], ""), (["hook", "guard"], payload)):
            with self.subTest(args=args):
                out, modules = self.launch(project, args, stdin)
                self.assertIn("probandia.cli", modules)   # the engine did run
                self.assertEqual([m for m in modules if m.startswith("probandia.cli.") and m.endswith("_cmd")], [])
        self.assertTrue(out.startswith("{") or out == "", out)

    def test_a_command_still_finds_its_own_module(self):
        out, modules = self.launch(self.out, ["dates", "1802"])
        self.assertIn("probandia.cli.lang_cmd", modules)
        self.assertNotIn("probandia.cli.lifecycle_cmd", modules)
        self.assertIn("STATUS=OK", out)

    def test_the_hook_forms_of_the_manifests_skip_argparse(self):
        from probandia import cli

        args = cli._fast_call(["hook", "guard", "--harness", "cursor"])
        self.assertEqual((args.command, args.function, args.harness, args.project), ("hook", "guard", "cursor", None))
        self.assertEqual(cli._fast_call(["hook", "log"]).harness, "cli")
        for argv in (["hook"], ["hook", "--help"], ["hook", "guard", "--harness", "nowhere"],
                     ["hook", "guard", "-p", "x"], ["status", "guard"]):
            with self.subTest(argv=argv):
                self.assertIsNone(cli._fast_call(argv))   # argparse reads, and refuses, the rest
