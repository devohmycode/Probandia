import io
import os
import tempfile
import unittest

from probandia import cli
from probandia.errors import NotInProject
from probandia.project import LAYOUT_DIRS, create_project, find_project


def call(*argv, cwd, environ=None):
    out = io.StringIO()
    code = cli.main(list(argv), stdout=out, environ=environ or {}, cwd=cwd)
    return code, out.getvalue()


class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "proj")
        create_project(self.root)
        self.deep = os.path.join(self.root, "families", "hugo", "research")
        os.makedirs(self.deep)
        self.outside = os.path.join(self.tmp.name, "outside")
        os.makedirs(self.outside)

    def test_upward_search(self):
        self.assertEqual(find_project(environ={}, cwd=self.deep), self.root)

    def test_option_first(self):
        other = os.path.join(self.tmp.name, "other")
        create_project(other)
        env = {"PROBANDIA_PROJECT": other}
        self.assertEqual(find_project(self.root, env, cwd=self.outside), self.root)
        self.assertEqual(find_project(None, env, cwd=self.deep), other)

    def test_option_without_project_file(self):
        with self.assertRaises(NotInProject):
            find_project(self.outside, {}, cwd=self.deep)

    def test_none(self):
        with self.assertRaises(NotInProject) as cm:
            find_project(None, {}, cwd=self.outside)
        self.assertEqual(cm.exception.exit_code, 6)

    def test_command_outside_a_project_exits_6(self):
        for argv in (["status"], ["resume"], ["lock", "status", "research:r"], ["config", "show"]):
            code, out = call(*argv, cwd=self.outside)
            self.assertEqual(code, 6, argv)
            self.assertIn("REASON=no-project", out)


class Creation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_config_init_writes_the_layout(self):
        code, out = call("config", "init", cwd=self.dir)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "probandia.toml")))
        for d in LAYOUT_DIRS:
            self.assertTrue(os.path.isdir(os.path.join(self.dir, *d.split("/"))), d)
        with open(os.path.join(self.dir, ".gitignore"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().split(), ["work/", ".probandia/", "probandia.local.toml", ".env"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".env")))
        with open(os.path.join(self.dir, ".env.example"), encoding="utf-8") as fh:
            env = fh.read()
        self.assertIn("\nTAVILY_API_KEY=\n", env)
        with open(os.path.join(self.dir, "probandia.toml"), "rb") as fh:
            import tomllib
            self.assertEqual(tomllib.load(fh)["schema"], 1)

    def test_init_is_idempotent(self):
        call("config", "init", cwd=self.dir)
        with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
            fh.write("# mine\n")
        code, out = call("config", "init", "--project", self.dir, cwd=self.dir)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("STATUS=WARN"))
        with open(os.path.join(self.dir, "probandia.toml"), encoding="utf-8") as fh:
            self.assertIn("# mine", fh.read())

    def test_init_inside_a_project_writes_nothing(self):
        call("config", "init", cwd=self.dir)
        sub = os.path.join(self.dir, "families")
        code, out = call("config", "init", cwd=sub)
        self.assertTrue(out.startswith("STATUS=WARN"))
        self.assertFalse(os.path.exists(os.path.join(sub, "probandia.toml")))

    def test_existing_gitignore_is_completed(self):
        with open(os.path.join(self.dir, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("*.bak\nwork/\n")
        create_project(self.dir)
        with open(os.path.join(self.dir, ".gitignore"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "*.bak\nwork/\n\n.probandia/\nprobandia.local.toml\n.env\n")

    def test_env_variable_target(self):
        target = os.path.join(self.dir, "p2")
        code, out = call("config", "init", cwd=self.dir, environ={"PROBANDIA_PROJECT": target})
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(target, "probandia.toml")))
