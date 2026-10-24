"""G-1 on every way of naming a protected path (T141) and every way of writing it
from a shell (T142)."""
import os
import shutil
import tempfile
import unittest

from probandia import guard
from tests import ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
INDEX = "families/hugo/index/persons.yaml"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.dir = os.path.join(cls.tmp.name, "project")
        shutil.copytree(FIXTURE, cls.dir)
        cls.env = {"PROBANDIA_CONFIG_DIR": os.path.join(cls.tmp.name, "user"), "PROBANDIA_SESSION": "test"}

    def check(self, tool, tool_input, agent="researcher", cwd=None):
        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": cwd or self.dir, "agent_type": agent}
        return guard.check(payload, self.env, "claude-code")

    def assertRefused(self, tool, tool_input, **kw):
        answer = self.check(tool, tool_input, **kw)
        self.assertIsNotNone(answer, tool_input)
        self.assertEqual(answer[0], "G-1", (tool_input, answer))


class NormalisedPath(Base):
    """T141: the path is compared once made relative to the project, ``..`` resolved."""

    def test_four_forms_of_the_index(self):
        forms = ["Families/Hugo/INDEX/persons.yaml",                      # case changed
                 "families/hugo/work/../index/persons.yaml",              # ..
                 "families\\hugo\\index\\persons.yaml",                   # backslashes
                 "./families/hugo/index/persons.yaml"]                    # relative
        for form in forms:
            self.assertRefused("Edit", {"file_path": form, "old_string": "a", "new_string": "b"})
            self.assertRefused("Write", {"file_path": os.path.join(self.dir, form), "content": "x"})
        # relative to a working folder inside the family
        self.assertRefused("Write", {"file_path": "index/persons.yaml", "content": "x"},
                           cwd=os.path.join(self.dir, "families", "hugo"))
        self.assertRefused("Write", {"file_path": "../index/persons.yaml", "content": "x"},
                           cwd=os.path.join(self.dir, "families", "hugo", "work"))

    def test_proposals_stay_open(self):
        self.assertIsNone(self.check("Write", {"file_path": "families/hugo/work/proposals/x.yaml", "content": "x"}))
        self.assertIsNone(self.check("Write", {"file_path": "families/hugo/index/../work/x.yaml", "content": "x"}))

    def test_a_folder_above_the_project_protects_nothing(self):
        root = os.path.join(self.tmp.name, "report", "families", "x", "index")
        os.makedirs(root, exist_ok=True)
        shutil.copytree(FIXTURE, os.path.join(root, "p"), dirs_exist_ok=True)
        cwd = os.path.join(root, "p")
        self.assertIsNone(self.check("Write", {"file_path": "families/hugo/work/a.yaml", "content": "x"}, cwd=cwd))
        self.assertEqual(self.check("Write", {"file_path": INDEX, "content": "x"}, cwd=cwd)[0], "G-1")


class ShellWrites(Base):
    """T142: PowerShell's cmdlets and their aliases, and an interpreter given its code inline."""

    def test_powershell_writes(self):
        for command in (f"Copy-Item x.yaml {INDEX}", f"Move-Item -Path x.yaml -Destination {INDEX}",
                        f"New-Item -ItemType File -Path {INDEX} -Force", f"Rename-Item {INDEX} old.yaml",
                        f"Clear-Content {INDEX}", f"Get-Content x.yaml | Tee-Object -FilePath {INDEX}",
                        f"cpi x.yaml {INDEX}", f"mi x.yaml {INDEX}", f"ni {INDEX}", f"ren {INDEX} old.yaml",
                        f"copy-item x.yaml '{INDEX}'", f'COPY-ITEM x.yaml "{INDEX}"'):
            for tool in ("PowerShell", "Bash"):
                self.assertRefused(tool, {"command": command})

    def test_inline_code(self):
        for command in (f"python -c \"open('{INDEX}', 'w').write('x')\"",
                        f"python3 -c \"import pathlib; pathlib.Path('{INDEX}').write_text('x')\"",
                        "py -c \"open(r'families\\hugo\\index\\persons.yaml','w')\"",
                        f"node -e \"require('fs').writeFileSync('{INDEX}', 'x')\"",
                        f"python - <<'EOF'\nopen('{INDEX}', 'w').write('x')\nEOF"):
            self.assertRefused("Bash", {"command": command})

    def test_what_stays_open(self):
        for command in ("Copy-Item x.yaml families/hugo/work/x.yaml", "python -c \"print(1)\"",
                        "node -e \"console.log(1)\"", "python run_probandia.py known 2026"):
            self.assertIsNone(self.check("Bash", {"command": command}), command)

    def test_the_orchestrator_may(self):
        self.assertIsNone(self.check("PowerShell", {"command": f"Copy-Item x.yaml {INDEX}"}, agent="orchestrator"))


if __name__ == "__main__":
    unittest.main()
