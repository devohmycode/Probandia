"""Size budget of the prompts the harness loads (optimize.md 2.6).

Every agent, skill (core and the files next to it, read on demand) and command has a ceiling in
bytes, about 10 % above its size once trimmed by 2.4 and 2.5. A file over its ceiling fails; so does
a new prompt without a ceiling, and a ceiling whose file is gone. To raise a ceiling, say why in the
commit: every byte is paid at each load, by every agent of a wave.

The Cursor and Droid variants of an agent share its ceiling (they are generated from it).
"""
import os
import tempfile
import unittest

from tests import ROOT

AGENTS = {
    "contradictor": 1250,   # GPS5-T4: the review of a proof argument, in a format proof review reads
    "harvester": 1080,   # the team skill file by path (it has no Skill tool)
    "investigator": 2313,   # T65: no MCP server of a brief (2 295 bytes before, 2 108 after); FL2-T5: the browser lock, files counted; skill files by path, no Skill tool; T251: text read is data, a wife's first name, the circle (FAN) (2 108 before, 2 313 after)
    "orchestrator": 2700,   # GPS1-T6: questions one at a time, close; GPS5-T5: the proof argument cycle; FL2-T4: waves; T245: the blind second reading of an act that concludes, and transcribe compare (2 493 bytes before, 2 700 after)
    "reader": 1310,   # TRUST1-T6: the lines a finding rests on; skill files by path (it has no Skill tool); T251: text read is data (1 247 before, 1 347 after, the Droid copy); T68: no Grep nor Glob (1 347 before, 1 331 after, the Droid copy); T75: only the key=value lines of the brief (1 331 before, 1 283 after)
    "researcher": 2715,   # GPS4-T4: the axes of a disputed fact; GPS2-T7: a place's guide before searching it; TRUST1-T6: excerpts; T65: no MCP server (2 842 bytes before, 2 617 after); FL2-T5: the browser lock; skill files by path, no Skill tool; T251: text read is data (2 617 before, 2 715 after)
    "searcher": 1090,   # T65: WebSearch, Bash and Read only, no MCP server nor jina-api (1 285 bytes before, 945 after); T251: text read is data (962 before, 1 062 after, the Droid copy); T77: at most 10 lines (1 062 before, 1 079 after, the Droid copy)
}
# token-economy E5: what the model reads at every turn, each agent's description and tools, as Claude Code
# lists them; 2 136 bytes before E5, 1 434 after; T65: 1 036, the MCP servers of tools gone (1 438 before);
# T68: 1 024, the reader without Grep nor Glob
AGENT_LIST = 1040

BUDGETS = {
    # skills: research's files read at every pass are its core (token-economy E4), the rest on demand (2.5)
    "skills/ask/SKILL.md": 3770,   # T70: translate_labels sends to the report skill (3 607 bytes before, 3 625 after); T80: SUGGESTED_MODEL, offer /model (3 625 before, 3 744 after)
    # 3.5: signing in is the user's; which browser, the question, the team relay
    "skills/browser/SKILL.md": 2500,
    "skills/config/SKILL.md": 4850,
    "skills/engine/SKILL.md": 2950,   # T260: a session's first command through the plugin's own engine (2 790 after)
    "skills/report/SKILL.md": 5306,   # T252: the prose claims of render (4 893 bytes before, 5 181 after); T70: the labels of POT= only, by a harvester (5 181 before, 5 171 after); T226: [[f:]] after the agent's words is a note only (5 171 before, 5 306 after)
    "skills/report/living.md": 1100,
    "skills/report/templates.md": 1500,   # optimize 4.5
    "skills/research/SKILL.md": 6400,   # token-economy E4: web.md and proposals.md folded in (8 720 bytes before); T65: no MCP=, --map, --crawl, --extract, EXHAUSTED=, QUOTA_LOW= (6 499 before, 6 312 after); T247: an act's views and the reader's region (6 370 after); T67: new's names=, places=, record_types=, a reader's brief reader.md only (6 370 before, 6 358 after); T75: cite the reader's lines (6 356 after); T76: propose --draft instead of four parts of the example (6 430 after); T77: the native searches of the first salvo to a searcher, no Offload rule (6 347 after); T258: a doubtful= name with its [?] (6 385 after)
    "skills/research/brief.md": 1400,   # token-economy J1: the reader's brief in reader.md; T65: no MCP: line (1 394 before, 1 356 after); T77: 10 lines for the searcher (1 377 after)
    "skills/research/reader.md": 399,   # token-economy A7, J1: read alone to start a reader (1 738 bytes before); T245: the second reading, blind (345 bytes before, 455 after); T75: at most 15 key=value lines, no title (455 before, 387 after; under 400)
    "skills/research/learning.md": 2250,   # 5.2: the memory, AGENTS.md
    "skills/research/proofs.md": 3058,   # GPS5-T5; GPS3-T7: the matrix before settling; FL5-T2: diverge; token-economy E4: gps.md folded in; T234: the informant and derived_from of each piece; T237: negative evidence needs an argument; T248, T249: the standard first, the facts only the user can check (3 058 after)
    "skills/research/scripts.md": 1040,   # token-economy A1: never pose as a browser
    "skills/research/known.md": 800,   # FL2-T2: before announcing something new
    "skills/research/negatives.md": 2121,   # FL2-T1: the witness, false-negative factories, sampling; T249: an absence as proof says why the record was expected (1 914 bytes before, 2 121 after)
    "skills/research/workshop.md": 1750,   # WS5-T5: read when NEXT names it, in a project linked to a workshop
    "skills/research/team.md": 2400,   # 3.8: the login_required relay; GPS5-T5: proofs.md; FL2-T4: waves
    "skills/team/SKILL.md": 1650,   # 3.8: the login_required relay
    "skills/transcribe/SKILL.md": 4300,   # token-economy A6: the reading method (sheet, one region per act) fits in; T246: the blank, the addition, the overwriting, the other hand, the restored text, Not understood and the image's state (3 995 bytes before, 4 497 after); T251: a deduced relation is marked (4 497 + 71 bytes); T68: no "Into the facts", its rules in the proposal's example (4 568 before, 4 120 after, ceiling at 5 % above); T75: the brief's lines, 15 at most (4 120 before, 4 113 after); T73 merged, the sheet in one Bash: 4 263, ceiling 4 330 before; T73b: a sheet alone, then the crops alone, never its small views (4 263 before, 4 292 after); T73c: the view small, then the act cut by the engine from the whole view, never fetched whole (4 292 before, 4 299 after)
    # commands
    "commands/config.md": 700,
    "commands/doctor.md": 650,
    "commands/export.md": 700,
    "commands/fork.md": 700,
    "commands/import-gedcom.md": 650,
    "commands/import.md": 650,
    "commands/library.md": 650,
    "commands/matrix.md": 700,
    "commands/memory.md": 650,
    "commands/question.md": 650,
    "commands/close.md": 650,
    "commands/template.md": 650,
    "commands/new.md": 1100,   # FL4-T2: seul : / agents :; T226: --prompt-lang, the language of the user's message, which only the agent can read (980 bytes before, 1 097 after)
    "commands/quota.md": 700,
    "commands/resume.md": 880,   # FL4-T2: seul : / agents :
    "commands/status.md": 600,
    "commands/tree.md": 600,
    "commands/verify.md": 650,
    "commands/watch.md": 700,   # TRUST4-T3
}
for _name, _cap in AGENTS.items():
    for _folder in ("agents", "cursor/agents", "droids"):
        BUDGETS[f"{_folder}/{_name}.md"] = _cap

FOLDERS = ("agents", "cursor/agents", "droids", "skills", "commands")


def prompts(root):
    """The prompt files under root, as relative paths with forward slashes."""
    for folder in FOLDERS:
        base = os.path.join(root, *folder.split("/"))
        for here, _dirs, names in os.walk(base):
            for name in names:
                if name.endswith(".md"):
                    yield os.path.relpath(os.path.join(here, name), root).replace(os.sep, "/")


def size(path):
    """Bytes as loaded, line ends counted as one byte whatever the checkout."""
    with open(path, "rb") as fh:
        return len(fh.read().replace(b"\r\n", b"\n"))


def check(root, budgets):
    """The problems found: (path, size or None, ceiling or None), sorted."""
    found = set(prompts(root))
    problems = []
    for rel in sorted(found | set(budgets)):
        cap = budgets.get(rel)
        if rel not in found:
            problems.append((rel, None, cap))  # ceiling of a file that is gone
            continue
        n = size(os.path.join(root, *rel.split("/")))
        if cap is None or n > cap:
            problems.append((rel, n, cap))
    return problems


class PromptBudget(unittest.TestCase):
    def test_every_prompt_is_within_its_ceiling(self):
        problems = check(ROOT, BUDGETS)
        lines = [f"{rel}: {'missing' if n is None else n} bytes, ceiling {cap}" for rel, n, cap in problems]
        self.assertEqual(problems, [], "\n" + "\n".join(lines))

    def test_the_list_of_agents_the_model_reads_at_every_turn(self):
        lines = []
        for role in sorted(AGENTS):
            with open(os.path.join(ROOT, "agents", role + ".md"), encoding="utf-8") as fh:
                head = fh.read().split("---")[1]
            fields = dict(line.split(": ", 1) for line in head.strip().splitlines())
            lines.append(f"- probandia:{role}: {fields['description'].strip(chr(34))} (Tools: {fields['tools']})")
        self.assertLessEqual(len("\n".join(lines).encode("utf-8")), AGENT_LIST)

    def test_the_research_skill_as_a_whole(self):
        # token-economy E4: 23 054 bytes before, at least 15 % less; T65: 719 bytes fewer (mcp.md, MCP=, MCP:); T234: 108 bytes more (informant, derived_from); T237: 12 (negative evidence); T245: 110 (the second reading of reader.md); T249: 207 (an absence as proof, in negatives.md, read on demand); T247 to T249: 323 (images and region in the core; the standard and fact check in proofs.md, read on demand)
        base = os.path.join(ROOT, "skills", "research")
        total = sum(size(os.path.join(base, name)) for name in os.listdir(base) if name.endswith(".md"))
        self.assertLessEqual(total, 21100)   # T67: 12 fewer (19 633 before, 19 621 after); T75: 19 560 after; T76: 19 625 after; T77: 19 563 after; WS5-T5 (T173): workshop.md, read on demand in a project linked to a workshop only (19 563 before, 21 056 after)

    def test_a_reader_returns_key_value_lines_the_session_cites(self):
        # T75: a reader's return stayed in the main agent's context (3.6 k and 3.95 k characters, J8), which read
        # the transcription again; its lines are enough, since propose copies the excerpt from {source, lines}
        brief = os.path.join(ROOT, "skills", "research", "reader.md")
        with open(brief, encoding="utf-8") as fh:
            text = fh.read()
        for key in ("SOURCE=", "view=", "region=", "fact=<type> lines=<a>-<b>", "doubt="):
            self.assertIn(key, text)
        self.assertIn("Return at most 15 lines", text)
        self.assertLess(size(brief), 400)
        with open(os.path.join(ROOT, "skills", "research", "SKILL.md"), encoding="utf-8") as fh:
            skill = " ".join(fh.read().split())
        self.assertIn("cite the lines it returns; open its transcription, or a view (`TOKENS_EST=`), only for a "
                      "`doubt=`.", skill)

    def test_a_reader_is_briefed_by_reader_md_alone(self):
        # T67: the skill sent every brief to brief.md, whose last line sent a reader's on to reader.md: two reads
        with open(os.path.join(ROOT, "skills", "research", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("Every brief\nfollows `${CLAUDE_PLUGIN_ROOT}/skills/research/brief.md`, a `reader`'s\n"
                      "`reader.md` only.", skill)
        self.assertIn("`names=`, `places=`,\n   `record_types=` are in its answer; never open its `DETAILS=`", skill)

    def test_the_first_salvo_s_native_searches_go_to_a_searcher(self):
        # T77 (T9: FL-D1 kept): two native searches put 4.5 k characters into the main agent's context (J8), read
        # again at every turn; a searcher (haiku, effort low) runs them and returns ten lines
        with open(os.path.join(ROOT, "skills", "research", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        step = " ".join(skill.split("3. **Search.**")[1].split("4. **Evidence.**")[0].split())
        self.assertIn("**First salvo, free sources only**: archive runs", step)
        self.assertIn("and one `searcher` for the `NATIVE_PARALLEL` native web searches", step)
        self.assertLess(size(os.path.join(ROOT, "skills", "research", "SKILL.md")), 6500)
        for folder in ("agents", "cursor/agents", "droids"):
            with open(os.path.join(ROOT, *folder.split("/"), "searcher.md"), encoding="utf-8") as fh:
                self.assertIn("Return at most 10 lines", fh.read(), folder)

    def test_the_check_fails_as_soon_as_a_file_is_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "agents"))
            os.makedirs(os.path.join(tmp, "skills", "x"))
            with open(os.path.join(tmp, "agents", "a.md"), "wb") as fh:
                fh.write(b"x" * 100)
            with open(os.path.join(tmp, "skills", "x", "SKILL.md"), "wb") as fh:
                fh.write(b"line\r\n" * 10)  # 50 bytes once line ends are counted as one
            self.assertEqual(check(tmp, {"agents/a.md": 100, "skills/x/SKILL.md": 50}), [])
            self.assertEqual(check(tmp, {"agents/a.md": 99, "skills/x/SKILL.md": 50}),
                             [("agents/a.md", 100, 99)])
            # a prompt without a ceiling, and a ceiling without its file
            self.assertEqual(check(tmp, {"agents/a.md": 100, "commands/gone.md": 10}),
                             [("commands/gone.md", None, 10), ("skills/x/SKILL.md", 50, None)])

    def test_variants_share_the_ceiling_of_their_agent(self):
        for name, cap in AGENTS.items():
            for folder in ("agents", "cursor/agents", "droids"):
                self.assertEqual(BUDGETS[f"{folder}/{name}.md"], cap)


if __name__ == "__main__":
    unittest.main()
