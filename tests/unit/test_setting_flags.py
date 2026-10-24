import io
import os
import shutil
import tempfile
import unittest

from probandia import cli
from tests import ROOT

SAMPLE = os.path.join(ROOT, "tests", "sample-project")


class SettingFlags(unittest.TestCase):
    """The command options the settings registry names exist (SPECS § 4.2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = os.path.join(self.tmp.name, "sample")
        shutil.copytree(SAMPLE, self.project)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u"), "PROBANDIA_SESSION": "s1"}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.project)
        return code, out.getvalue()

    def test_parallel_reaches_the_settings(self):
        code, out = self.call("plan", "--parallel", "2")
        self.assertEqual(code, 0, out)
        self.assertIn("NATIVE_PARALLEL=2", out.splitlines())

    def test_search_mcp_is_gone(self):
        # T65: the engine searches and reads; plan names no MCP server, and the setting is unknown
        code, out = self.call("plan")
        self.assertEqual(code, 0, out)
        self.assertFalse([x for x in out.splitlines() if x.startswith("MCP=")], out)
        self.assertEqual(self.call("config", "explain", "search.mcp")[0], 2)
        self.assertEqual(self.call("config", "set", "search.mcp", "jina")[0], 2)

    def test_a_search_mcp_left_in_probandia_toml_fails_nothing(self):
        path = os.path.join(self.project, "probandia.toml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("[search]", "[search]\nmcp = [\"jina\"]", 1) if "[search]" in text
                     else text + '\n[search]\nmcp = ["jina", "claude_ai_Firecrawl"]\n')
        for argv in (("plan",), ("status",), ("config", "show"), ("search", "--log-native", "--query", "Hugo",
                                                                  "--results", "0")):
            code, out = self.call(*argv)
            self.assertEqual(code, 0, (argv, out))   # a warning at most
            self.assertNotIn("MCP=", out)

    def test_parallel_out_of_range(self):
        code, out = self.call("plan", "--parallel", "9")
        self.assertEqual(code, 2, out)
        self.assertIn("REASON=config", out)

    def test_tree_format_alias(self):
        code, out = self.call("tree", "--tree-format", "md")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
