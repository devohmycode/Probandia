"""The guides of guides/ stay true to the engine (version-1.0.0 T189, T194 to T196).

The French guide names every user command and every genealogist's tool of the help, keeps no trace of
the removed ``.mcp.json``, and its relative links, like the open archives guide's, reach a file git keeps.
"""
import re
import subprocess
import unittest
from pathlib import Path

from probandia.cli.commands import COMMANDS
from probandia.cli.helptext import GROUPS

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "guides"
GUIDE = GUIDES / "guide-utilisation.md"
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def ignored(path):
    """True when .gitignore excludes the path; None when git cannot tell."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", str(path)],
                             capture_output=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(out.returncode)


class GuideTest(unittest.TestCase):
    def setUp(self):
        self.text = GUIDE.read_text(encoding="utf-8")

    def test_names_every_user_command_and_tool(self):
        names = {c.name for c in COMMANDS if not c.engine} | {n for _t, group in GROUPS for n in group}
        missing = sorted(n for n in names if not re.search(rf"(`|probandia ){re.escape(n)}\b", self.text))
        self.assertEqual(missing, [])

    def test_no_removed_mcp_json(self):
        self.assertNotIn(".mcp.json", self.text)

    def test_codex_agents_only_for_the_roles(self):
        for paragraph in self.text.split("\n\n"):
            if "codex-agents" in paragraph:
                self.assertIn("rôles", paragraph)

    def test_relative_links_reach_a_kept_file(self):
        for guide in sorted(GUIDES.glob("*.md")):
            for target in LINK.findall(guide.read_text(encoding="utf-8")):
                if "://" in target:
                    continue
                path = (guide.parent / target).resolve()
                with self.subTest(guide=guide.name, link=target):
                    self.assertTrue(path.exists())
                    self.assertIsNot(ignored(path), True)

    def test_readme_links_the_guides(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("guides/guide-utilisation.md", readme)


if __name__ == "__main__":
    unittest.main()
