"""Self-learning: the managed section of AGENTS.md (optimize.md 5.2)."""
import os

from probandia import guard, memory
from probandia.util import yamlio
from tests import ROOT
from tests.unit.test_learning import LearningCase

USER_TEXT = "# Notes of the project\n\nKeep this paragraph exactly as it is.\n"
ENTRY = "Reports use the sober template, for printing"


class MemoryCase(LearningCase):
    def agents(self):
        return os.path.join(self.dir, "AGENTS.md")

    def claude(self):
        return os.path.join(self.dir, "CLAUDE.md")

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def put(self, path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def add(self, text=ENTRY, *more):
        code, out = self.call("memory", "add", text, *more, "--approve", "yes")
        self.assertEqual(code, 0, out)
        return out


class Section(MemoryCase):
    """5.2.2: one section between markers; the rest of the file untouched."""

    def test_the_file_is_created_when_missing(self):
        out = self.add(ENTRY, "--kind", "template")
        self.assertIn("ENTRY=M1\n", out)
        text = self.read(self.agents())
        self.assertTrue(text.startswith(memory.BEGIN))
        self.assertIn("- [M1] ", text)
        self.assertIn(f"(template) {ENTRY}", text)
        self.assertTrue(text.rstrip().endswith(memory.END))

    def test_writing_the_same_entry_twice_changes_nothing(self):
        self.put(self.agents(), USER_TEXT)
        self.add()
        first = self.read(self.agents())
        out = self.add("reports use the SOBER template,   for printing")
        self.assertIn("CHANGED=false\n", out)
        self.assertEqual(self.read(self.agents()), first)
        code, out = self.call("memory", "sync")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(self.agents()), first)

    def test_the_users_text_stays_intact(self):
        self.put(self.agents(), USER_TEXT + "\n## After\n\nMore of the user's text.\n")
        self.add()
        self.add("Archives of the Doubs: read the registers by their image")
        text = self.read(self.agents())
        self.assertTrue(text.startswith(USER_TEXT + "\n## After\n\nMore of the user's text.\n"))
        self.assertEqual(text.count(memory.BEGIN), 1)
        self.assertEqual(len(memory.load(self.agents())[1]), 2)

    def test_the_title_is_in_the_users_language(self):
        code, out = self.call("--lang", "fr", "memory", "add", ENTRY, "--approve", "yes")
        self.assertEqual(code, 0, out)
        self.assertIn("## Mémoire du projet (Probandia)", self.read(self.agents()))

    def test_a_claude_md_that_imports_agents_md_is_not_changed(self):
        self.put(self.claude(), "# Mine\n\n@AGENTS.md\n")
        self.add()
        self.assertEqual(self.read(self.claude()), "# Mine\n\n@AGENTS.md\n")
        self.assertNotIn(memory.BEGIN, self.read(self.claude()))

    def test_a_claude_md_gets_one_import_line_with_the_first_entry(self):
        self.put(self.claude(), "# Mine\n")
        code, out = self.call("memory", "add", ENTRY)
        self.assertIn("QUESTION=memory_add\n", out)
        self.assertIn("IMPORT=add\n", out)
        self.assertEqual(self.read(self.claude()), "# Mine\n")   # nothing before the answer
        self.add()
        self.add("Second entry about providers", "--kind", "provider")
        self.assertEqual(self.read(self.claude()), "# Mine\n\n@AGENTS.md\n")

    def test_duplicate_sections_become_one(self):
        self.add()
        text = self.read(self.agents())
        self.put(self.agents(), text + "\n" + text)
        self.assertIn((self.agents(), "duplicate"), memory.problems(self.dir, self.env))
        code, out = self.call("memory", "sync")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(self.agents()).count(memory.BEGIN), 1)


class Rules(MemoryCase):
    """5.2.3: no key, no presumed-living person."""

    def test_a_key_is_refused(self):
        for text in ("SERPER_API_KEY=abcd1234efgh", "the token: sk-abcdefghijklmnop1234",
                     "my key k1-secret-value-0123456789abcdefghij"):
            code, out = self.call("memory", "add", text, "--approve", "yes")
            self.assertNotEqual(code, 0, text)
            self.assertIn("REASON=refused", out)
        self.assertFalse(os.path.exists(self.agents()))

    def test_the_value_of_a_known_key_is_refused(self):
        code, out = self.call("memory", "add", "Brave answers with Kx7Q2 fast", "--approve", "yes",
                              env={"BRAVE_API_KEY": "Kx7Q2"})
        self.assertEqual(code, 0, out)   # too short to be told apart from words
        code, out = self.call("memory", "add", "Brave works with abcdefgh", "--approve", "yes",
                              env={"BRAVE_API_KEY": "abcdefgh"})
        self.assertIn("REASON=refused", out)

    def test_a_living_person_is_refused(self):
        path = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        doc = yamlio.load(path)
        doc["persons"].append({"id": "camille-vernier-1990", "names": {"given": "Camille", "surname": "VERNIER"},
                               "sex": "F", "living": True, "parents": {}, "spouses": [], "facts": []})
        yamlio.dump(path, doc)
        code, out = self.call("memory", "add", "Ask Camille Vernier before each pass", "--approve", "yes")
        self.assertIn("REASON=refused", out)
        self.assertIn("Camille VERNIER", out)

    def test_the_rules_are_in_the_skill(self):
        with open(os.path.join(ROOT, "skills", "research", "learning.md"), encoding="utf-8") as fh:
            text = fh.read()
        for words in ("MEMORY_CANDIDATES", "genealogical", "presumed-living", "key or secret",
                      "memory add", "QUESTION=memory_add", "--approve yes", "--supersedes", "G-10"):
            self.assertIn(words, text)


class Commands(MemoryCase):
    """5.2.4: add, list, remove, sync."""

    def test_add_asks_and_writes_nothing_before_the_answer(self):
        code, out = self.call("memory", "add", ENTRY)
        self.assertEqual(code, 3, out)   # a question
        self.assertIn("STATUS=ASK\n", out)
        self.assertIn("QUESTION=memory_add\n", out)
        self.assertIn("- show=- [M1] ", out)
        self.assertFalse(os.path.exists(self.agents()))
        code, out = self.call("memory", "add", ENTRY, "--approve", "no")
        self.assertIn("REASON=declined", out)
        self.assertFalse(os.path.exists(self.agents()))

    def test_list_remove_and_supersedes(self):
        self.add()
        self.add("Serper for old newspapers", "--kind", "provider")
        code, out = self.call("memory", "list")
        self.assertIn("ENTRIES=2\n", out)
        self.assertIn("(provider) Serper for old newspapers", out)
        out = self.add("Brave for old newspapers, Serper as a fallback", "--kind", "provider", "--supersedes", "M2")
        self.assertIn("ENTRY=M3\n", out)
        self.assertIn("REPLACED=1\n", out)
        items = memory.load(self.agents())[1]
        self.assertEqual([x["id"] for x in items], ["M1", "M3"])
        archive = self.read(os.path.join(self.dir, memory.ARCHIVE))
        self.assertIn("[M2]", archive)
        self.assertIn("M3", archive)
        code, out = self.call("memory", "remove", "M1")
        self.assertIn("QUESTION=memory_remove\n", out)
        code, out = self.call("memory", "remove", "m1", "--approve", "yes")
        self.assertEqual(code, 0, out)
        self.assertEqual([x["id"] for x in memory.load(self.agents())[1]], ["M3"])
        out = self.add("A new one")
        self.assertIn("ENTRY=M4\n", out)   # ids never come back

    def test_sync_adopts_a_hand_edit_and_rewrites_the_section(self):
        self.add()
        text = self.read(self.agents()).replace("for printing", "for print and screen")
        self.put(self.agents(), text)
        self.assertIn((self.agents(), "edited"), memory.problems(self.dir, self.env))
        code, out = self.call("memory", "sync")
        self.assertEqual(code, 0, out)
        self.assertEqual(memory.problems(self.dir, self.env), [])
        self.assertIn("for print and screen", self.read(self.agents()))


class Sobriety(MemoryCase):
    """5.2.5: a capped section; merge or archive beyond it."""

    def fill(self):
        for n in range(36):
            self.add(f"Decision number {n} about the work")

    def test_an_entry_over_the_cap_asks_to_merge_or_archive(self):
        self.fill()
        before = self.read(self.agents())
        code, out = self.call("memory", "add", "One more decision", "--approve", "yes")
        self.assertIn("QUESTION=memory_full\n", out)
        self.assertIn("CHOICES=merge|archive|no\n", out)
        self.assertIn("- oldest=[M1]", out)
        self.assertEqual(self.read(self.agents()), before)
        out = self.add("One more decision", "--overflow", "archive")
        self.assertIn("ARCHIVED=1\n", out)
        self.assertTrue(memory.fits(memory.section_of(self.read(self.agents()))))
        self.assertIn("[M1]", self.read(os.path.join(self.dir, memory.ARCHIVE)))

    def test_merging_frees_room(self):
        self.fill()
        out = self.add("Decisions 0 to 2 about the work", "--supersedes", "M1,M2,M3")
        self.assertIn("REPLACED=3\n", out)


class Scopes(MemoryCase):
    """5.2.6: the user's file only on its own approval."""

    def test_the_user_scope_asks_on_its_own(self):
        self.add()
        code, out = self.call("memory", "add", "Answer me in French", "--kind", "preference", "--scope", "user",
                              "--for", "claude-code")
        self.assertIn("QUESTION=memory_add\n", out)
        self.assertIn("SCOPE=user\n", out)
        self.assertIn("on its own", out)
        target = os.path.join(self.env["HOME"], ".claude", "CLAUDE.md")
        self.assertFalse(os.path.exists(target))
        code, out = self.call("memory", "add", "Answer me in French", "--kind", "preference", "--scope", "user",
                              "--for", "claude-code", "--approve", "yes")
        self.assertEqual(code, 0, out)
        self.assertIn("(preference) Answer me in French", self.read(target))
        self.assertNotIn("Answer me in French", self.read(self.agents()))

    def test_codex_uses_its_global_agents_md_and_others_are_refused(self):
        self.add("Answer me in French", "--scope", "user", "--for", "codex")
        self.assertIn("Answer me in French", self.read(os.path.join(self.env["HOME"], ".codex", "AGENTS.md")))
        code, out = self.call("memory", "add", "x y z", "--scope", "user", "--harness", "cursor", "--approve")
        self.assertNotEqual(code, 0, out)
        self.assertIn("no verified user file", out)


class Checks(MemoryCase):
    """5.2.7: doctor and the guard."""

    def doctor(self):
        code, out = self.call("doctor", "--harness", "codex", env={"PWD": self.dir})
        return out

    def test_doctor_reports_a_missing_import_a_duplicate_and_a_hand_edit(self):
        self.add()
        self.assertIn("MEMORY_ISSUES=0\n", self.doctor())
        self.put(self.claude(), "# Mine\n")
        out = self.doctor()
        self.assertIn("MEMORY_ISSUES=1\n", out)
        self.assertIn("CLAUDE.md does not import AGENTS.md", out)
        text = self.read(self.agents())
        self.put(self.agents(), text.replace("sober", "plain") + "\n" + text)
        out = self.doctor()
        self.assertIn("MEMORY_ISSUES=3\n", out)
        self.assertIn("more than one managed section", out)
        self.assertIn("edited by hand", out)

    def test_an_unmatched_marker(self):
        self.put(self.agents(), USER_TEXT + memory.BEGIN + "\n- [M1] 2026-10-03 x\n")
        self.assertEqual(memory.problems(self.dir, self.env), [(self.agents(), "unmatched")])
        code, out = self.call("memory", "add", ENTRY, "--approve", "yes")
        self.assertNotEqual(code, 0, out)
        self.assertEqual(self.read(self.agents()), USER_TEXT + memory.BEGIN + "\n- [M1] 2026-10-03 x\n")

    def check(self, tool, tool_input):
        return guard.check({"tool_name": tool, "tool_input": tool_input, "cwd": self.dir}, self.env, "claude-code")

    def test_the_guard_keeps_the_section_to_memory(self):
        self.put(self.agents(), USER_TEXT)
        self.add()
        text = self.read(self.agents())
        refused = self.check("Edit", {"file_path": self.agents(), "old_string": "sober template",
                                      "new_string": "plain template"})
        self.assertEqual(refused[0], "G-10")
        self.assertIn("memory add", refused[1])
        self.assertIsNone(self.check("Edit", {"file_path": self.agents(), "old_string": "exactly as it is",
                                              "new_string": "as it is"}))
        self.assertEqual(self.check("Write", {"file_path": "AGENTS.md", "content": USER_TEXT})[0], "G-10")
        self.assertIsNone(self.check("Write", {"file_path": self.agents(), "content": "# New head\n\n" +
                                               text[len(USER_TEXT):]}))
        self.assertEqual(self.check("Edit", {"file_path": self.claude(), "old_string": "x",
                                             "new_string": memory.BEGIN})[0], "G-10")
        self.assertEqual(self.check("Bash", {"command": "sed -i s/sober/plain/ AGENTS.md"})[0], "G-10")
        self.assertIsNone(self.check("Bash", {"command": 'probandia memory add "x" > out.txt'}))


class PassEnd(MemoryCase):
    """5.2.8: the end of a pass proposes the memory in the same question."""

    def test_pass_end_proposes_the_sign_ins_of_the_pass(self):
        from probandia import logins
        from tests.unit.test_library import RID

        code, out = self.call("resume", RID, "--mode", "session", env={"CLAUDECODE": "1"})
        self.call("plan", RID, env={"CLAUDECODE": "1"})
        self.assertEqual(code, 0, out)
        logins.set_state(self.dir, "familysearch", "confirmed", research=RID)
        code, out = self.call("pass", "end", RID, "--summary", "done", env={"CLAUDECODE": "1"})
        self.assertEqual(code, 0, out)
        self.assertIn("MEMORY_CANDIDATES=1\n", out)
        self.assertIn("- memory=login familysearch asks for a sign-in in the browser\n", out)
        self.assertIn("in one question", out)
        self.assertIn("memory add", out)
