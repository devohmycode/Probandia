import io
import os
import tempfile
import unittest
from unittest import mock

from probandia import cli
from probandia.project import create_project
from probandia.util import envfile


class Parse(unittest.TestCase):
    def test_syntax(self):
        text = ("﻿# comment\n\nTAVILY_API_KEY=tvly-1\nexport BRAVE_API_KEY = 'BSA 2' \n"
                'FIRECRAWL_API_KEY="fc-3 # not a comment"\nJINA_API_KEY=jina-4 # a comment\n'
                "not a line\nEMPTY=\n")
        self.assertEqual(envfile.parse(text), {
            "TAVILY_API_KEY": "tvly-1", "BRAVE_API_KEY": "BSA 2",
            "FIRECRAWL_API_KEY": "fc-3 # not a comment", "JINA_API_KEY": "jina-4", "EMPTY": ""})

    def test_template_lists_every_key_empty(self):
        from probandia.doctor import SECRET_VARIABLES

        values = envfile.parse(envfile.TEMPLATE)
        self.assertEqual(set(values.values()), {""})
        self.assertEqual([v for v in SECRET_VARIABLES if v not in values], [])

    def test_repository_example_is_the_template(self):
        from tests import ROOT

        with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), envfile.TEMPLATE)


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = os.path.join(self.tmp.name, "user")
        self.project = os.path.join(self.tmp.name, "project")
        os.makedirs(self.user)
        create_project(self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": self.user, "PROBANDIA_SESSION": "test"}

    def write(self, folder, text):
        with open(os.path.join(folder, ".env"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_precedence(self):
        self.write(self.user, "TAVILY_API_KEY=user\nBRAVE_API_KEY=user\nJINA_API_KEY=user\n")
        self.write(self.project, "TAVILY_API_KEY=project\nBRAVE_API_KEY=project\n")
        out = envfile.merged(dict(self.env, BRAVE_API_KEY="environment"), self.project)
        self.assertEqual(out["TAVILY_API_KEY"], "project")
        self.assertEqual(out["BRAVE_API_KEY"], "environment")
        self.assertEqual(out["JINA_API_KEY"], "user")
        self.assertEqual(out[envfile.FILES_VARIABLE].split(os.pathsep),
                         [os.path.join(self.user, ".env"), os.path.join(self.project, ".env")])

    def test_no_file(self):
        out = envfile.merged(self.env, None)
        self.assertEqual(out, self.env)

    def test_doctor_sees_the_keys_without_printing_them(self):
        self.write(self.project, "TAVILY_API_KEY=tvly-secret\nFIRECRAWL_API_KEY=fc-secret\n")
        out = io.StringIO()
        cli.main(["doctor"], stdout=out, environ=self.env, cwd=self.project)
        text = out.getvalue()
        self.assertIn("TAVILY_API_KEY", text)
        self.assertIn("FIRECRAWL_API_KEY", text)
        self.assertIn("- keys read from .env\n", text)   # relative to the project (optimize 2.11)
        self.assertNotIn("secret", text)
        self.assertNotIn("unknown variable", text)


@unittest.skipIf(os.name == "nt", "POSIX rights")
class Rights(unittest.TestCase):
    """The .env of the keys is born 0600: never readable by others, not even
    between its replace and a chmod (T138)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "u", ".env")

    def test_the_temporary_file_is_0600_before_the_keys(self):
        seen = []
        fdopen = os.fdopen

        def watch(fd, *a, **kw):
            seen.append(os.fstat(fd).st_mode & 0o777)
            return fdopen(fd, *a, **kw)

        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        with mock.patch("os.fdopen", watch):
            envfile.set_value(self.path, "LINKUP_API_KEY", "lk-SECRET")
        self.assertEqual(seen, [0o600])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_keys_set_on_a_0644_file_leaves_it_0600(self):
        from tests.unit.test_keyboard import TTY

        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("SERPER_API_KEY=x\n")
        os.chmod(self.path, 0o644)
        project = os.path.join(self.tmp.name, "p")
        create_project(project)
        env = {"PROBANDIA_CONFIG_DIR": os.path.dirname(self.path), "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"),
               "NO_COLOR": "1", "PROBANDIA_PAGER": "none"}
        code = cli.main(["keys", "set", "LINKUP_API_KEY"], stdout=io.StringIO(), environ=env, cwd=project,
                        stdin=TTY("lk-NEW\n"))
        self.assertEqual(code, 0)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
