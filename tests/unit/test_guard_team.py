import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, events, hooks
from probandia.research import Research
from probandia.util import yamlio
from tests import REUSE, ROOT
from tests.unit.test_lifecycle import tree_hash

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
RID = "2026-09-30-parents-of-victor-hugo"


def writes(test):
    """A test that changes its project: it gets its own copy, even in a class that shares one."""
    test.writes = True
    return test


class Base(unittest.TestCase):
    shared = False   # T27: the tests of the class leave the project as they found it, but those marked @writes

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.shared:
            cls.shared_tmp = tempfile.TemporaryDirectory()
            cls.addClassCleanup(cls.shared_tmp.cleanup)
            shutil.copytree(FIXTURE, os.path.join(cls.shared_tmp.name, "project"))
            cls.shared_state = tree_hash(cls.shared_tmp.name)

    def setUp(self):
        if self.shared and not getattr(getattr(self, self._testMethodName), "writes", False):
            self.tmp = self.shared_tmp
            self.addCleanup(lambda: self.assertEqual(tree_hash(self.tmp.name), self.shared_state,
                                                     "this test changes the shared project: mark it @writes"))
        else:
            self.tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self.tmp.cleanup)
            shutil.copytree(FIXTURE, os.path.join(self.tmp.name, "project"))
        self.dir = os.path.join(self.tmp.name, "project")
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "PROBANDIA_SESSION": "test",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"), "LANG": "en_US.UTF-8"}
        self.research = Research(self.dir, "hugo", RID)

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        for line in out.splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    def hook(self, function, payload, harness="claude-code", env=None):
        payload = dict({"cwd": self.dir}, **payload)
        text = hooks.run(function, io.StringIO(json.dumps(payload)), dict(self.env, **(env or {})), harness)
        return json.loads(text) if text.strip() else None

    def open_pass(self, *extra):
        code, out = self.call("resume", RID, "--mode", "session", *extra)
        self.assertEqual(code, 0, out)
        self.call("plan", RID)   # T226: pass end checks V-1, a plan in each pass


class Guard(Base):
    shared = True

    def deny_reason(self, decision):
        return (decision or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason")

    def test_hooks_turned_off_by_their_settings(self):
        # hooks.guard, hooks.digest, hooks.journal (the log function) and hooks.verify
        path = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        write = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"},
                 "agent_type": "probandia:researcher"}
        self.assertTrue(self.deny_reason(self.hook("guard", write)).startswith("G-1: "))
        self.assertIsNone(self.hook("guard", write, env={"PROBANDIA_HOOKS_GUARD": "false"}))
        payload = {"cwd": self.dir}
        for function, var in (("guard", "PROBANDIA_HOOKS_GUARD"), ("digest", "PROBANDIA_HOOKS_DIGEST"),
                              ("log", "PROBANDIA_HOOKS_JOURNAL"), ("verify", "PROBANDIA_HOOKS_VERIFY")):
            self.assertTrue(hooks.enabled(function, payload, self.env))
            self.assertFalse(hooks.enabled(function, payload, dict(self.env, **{var: "false"})))
        self.assertTrue(hooks.enabled("session", payload, dict(self.env, PROBANDIA_HOOKS_DIGEST="false")))

    def test_g1_field_agent_writing_the_index(self):
        path = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        d = self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"},
                                "agent_type": "probandia:researcher"})
        self.assertTrue(self.deny_reason(d).startswith("G-1: "))
        self.assertEqual(d["hookSpecificOutput"]["permissionDecision"], "deny")
        # the session agent and the orchestrator may (through apply), and work/ is open to all
        self.assertIsNone(self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": path}}))
        work = os.path.join(self.research.work, "proposals", "p.yaml")
        self.assertIsNone(self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": work},
                                              "agent_type": "researcher"}))
        d = self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": "echo x > families/hugo/index/persons.yaml"},
                                "agent_type": "harvester"})
        self.assertTrue(self.deny_reason(d).startswith("G-1"))
        for target in ("report/report.md", "research.yaml", "x/events.jsonl"):
            d = self.hook("guard", {"tool_name": "Edit", "tool_input": {"file_path": target},
                                    "agent_type": "reader"})
            self.assertTrue(self.deny_reason(d).startswith("G-1"), target)

    def test_g1_the_same_refusal_in_grok_camel_case(self):
        # T126: Grok Build sends toolName and toolInput (docs.x.ai/build/features/hooks, read 17 Oct. 2026)
        path = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        edit = {"file_path": path, "old_string": "a", "new_string": "b"}
        claude = self.hook("guard", {"tool_name": "Edit", "tool_input": edit, "agent_type": "probandia:reader"})
        grok = self.hook("guard", {"toolName": "Edit", "toolInput": edit, "agentType": "probandia:reader"},
                         harness="grok")
        self.assertTrue(self.deny_reason(claude).startswith("G-1: "))
        self.assertEqual((grok["decision"], grok["reason"]), ("deny", self.deny_reason(claude)))

    def test_g2_field_agent_applying_or_committing(self):
        for command in ('python "/p/run_probandia.py" apply 01J9 --agent researcher',
                        "python run_probandia.py event append r --type section.added",
                        "python run_probandia.py render r", "git commit -m x", "git -C . push"):
            d = self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": command},
                                    "agent_type": "investigator"})
            self.assertTrue(self.deny_reason(d).startswith("G-2"), command)
        self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {
            "command": "python run_probandia.py propose r f.yaml"}, "agent_type": "researcher"}))
        self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {
            "command": "python run_probandia.py apply 01J9"}, "agent_type": "orchestrator"}))

    def test_g11_field_agent_closing_or_settling_questions(self):
        for command in ('python "/p/run_probandia.py" close r', "python run_probandia.py --agent x close",
                        "probandia question answer Q1 --conclusion a.birth",
                        "python -m probandia question unresolved Q2 --reason lost",
                        'python run_probandia.py question add "Where?"', "probandia question reopen Q1"):
            d = self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": command},
                                    "agent_type": "researcher"})
            self.assertTrue((self.deny_reason(d) or "").startswith("G-11"), command)
        for command in ("python run_probandia.py question list", "python run_probandia.py question",
                        "python run_probandia.py resume r --interrupted close"):
            self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": command},
                                                  "agent_type": "contradictor"}), command)
        self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {
            "command": "python run_probandia.py close r"}, "agent_type": "orchestrator"}))
        # the MCP tool only lists: nothing to refuse there
        self.assertIsNone(self.hook("guard", {"tool_name": "mcp__plugin_probandia_probandia__question",
                                              "tool_input": {"research": "r"}, "agent_type": "investigator"}))

    def test_g6_field_agent_reading_what_the_engine_summarises(self):
        index = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        for tool, inp, expected in (
                ("Read", {"file_path": index}, "known <research>"),
                ("Read", {"file_path": os.path.join(self.research.folder, "events.jsonl")}, "digest <research>"),
                ("view_file", {"AbsolutePath": os.path.join(self.research.folder, "report", "report.md")}, "digest"),
                ("Bash", {"command": "cat families/hugo/index/sources.yaml"}, "known <research>"),
                ("Bash", {"command": f"Get-Content {self.research.folder}/events.jsonl -Tail 20"}, "digest")):
            d = self.hook("guard", {"tool_name": tool, "tool_input": inp, "agent_type": "probandia:researcher"})
            reason = self.deny_reason(d)
            self.assertTrue(reason and reason.startswith("G-6: "), (tool, inp, d))
            self.assertIn(expected, reason)
        # the orchestrator and the session agent may; work/ and the transcriptions stay open
        self.assertIsNone(self.hook("guard", {"tool_name": "Read", "tool_input": {"file_path": index},
                                              "agent_type": "orchestrator"}))
        self.assertIsNone(self.hook("guard", {"tool_name": "Read", "tool_input": {"file_path": index}}))
        work = os.path.join(self.research.work, "notes.md")
        self.assertIsNone(self.hook("guard", {"tool_name": "Read", "tool_input": {"file_path": work},
                                              "agent_type": "researcher"}))
        self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {
            "command": "python .probandia/pb.py known --agent researcher | head -20"}, "agent_type": "researcher"}))

    @writes
    def test_g6_the_main_agent_reading_the_index_in_a_pass(self):
        # T257: the session agent and the orchestrator read the index through known or status in an open pass
        index = os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")
        read = {"tool_name": "Read", "tool_input": {"file_path": index}}
        cat = {"tool_name": "Bash", "tool_input": {"command": "cat families/hugo/index/persons.yaml"}}
        self.assertIsNone(self.hook("guard", read))                     # no open pass: nothing to say
        self.open_pass()
        for payload in (read, cat, dict(read, agent_type="orchestrator")):
            reason = self.deny_reason(self.hook("guard", payload))
            self.assertTrue(reason and reason.startswith("G-6: "), (payload, reason))
            self.assertIn("known <research>", reason)
        # from the family folder, as in t82-resume
        d = self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": "cat index/sources.yaml"},
                                "cwd": os.path.join(self.dir, "families", "hugo")})
        self.assertTrue((self.deny_reason(d) or "").startswith("G-6: "), d)
        for command in ("python .probandia/pb.py known", "python .probandia/pb.py status"):
            self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": command}}))
        # events.jsonl and the report stay open to it, and so does the index outside Claude Code
        events = os.path.join(self.research.folder, "events.jsonl")
        self.assertIsNone(self.hook("guard", {"tool_name": "Read", "tool_input": {"file_path": events}}))
        self.assertIsNone(self.hook("guard", read, harness="codex"))

    @writes
    def test_g7_reading_again_a_proposal_just_summarised(self):
        from probandia.util.ids import ulid

        pid = ulid()
        folder = os.path.join(self.research.work, "proposals")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{pid}.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("schema: 1\n")
        read = {"tool_name": "Read", "tool_input": {"file_path": path}, "agent_type": "orchestrator"}
        reason = self.deny_reason(self.hook("guard", read))
        self.assertTrue(reason.startswith("G-7: "), reason)
        self.assertIn("printed its summary", reason)
        self.assertIsNone(self.hook("guard", read))          # once only: then the file can be read
        old = ulid()
        stale = os.path.join(folder, f"{old}.yaml")
        with open(stale, "w", encoding="utf-8") as fh:
            fh.write("schema: 1\n")
        os.utime(stale, (0, 0))                               # stored long ago: no warning
        self.assertIsNone(self.hook("guard", dict(read, tool_input={"file_path": stale})))

    @writes
    def test_g13_the_main_agent_reading_a_view(self):
        # token-economy A7: refused at the first image of the pass, then allowed with a notice that counts them
        view = os.path.join(self.research.work, "images", "ad50-607643-0090.jpg")
        read = {"tool_name": "Read", "tool_input": {"file_path": view}}
        self.assertIsNone(self.hook("guard", read))                     # no open pass: nothing to say
        self.open_pass()
        # the view a reader transcribed opens freely, to check its doubts, and counts for nothing
        folder = os.path.join(self.research.family_folder, "evidence", "transcriptions")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "src-01J9ZM0000000000000000000D.md"), "w", encoding="utf-8") as fh:
            fh.write("# Transcription\n\n| Field | Value |\n|---|---|\n| Source | src-01J9ZM0000000000000000000D |\n"
                     "| Image | families/hugo/research/x/work/images/ad50-607650-0020-crop.jpg (crop of view 20) |\n")
        crop = os.path.join(self.research.work, "images", "ad50-607650-0020-crop.jpg")
        self.assertIsNone(self.hook("guard", dict(read, tool_input={"file_path": crop})))
        reason = self.deny_reason(self.hook("guard", read))
        self.assertTrue(reason.startswith("G-13: "), reason)
        self.assertIn("reader subagent", reason)
        d = self.hook("guard", read)                                    # a doubt to check: allowed, counted
        self.assertNotIn("permissionDecision", d["hookSpecificOutput"])
        self.assertTrue(d["hookSpecificOutput"]["additionalContext"].startswith("G-13: 1 image(s) read by you"))
        d = self.hook("guard", dict(read, tool_input={"file_path": view.replace("\\", "/")}))
        self.assertIn("2 image(s)", d["hookSpecificOutput"]["additionalContext"])
        # the reader reads them; so does the main agent elsewhere, outside Claude Code, or a file that is no image
        for payload, harness in ((dict(read, agent_type="probandia:reader"), "claude-code"),
                                 (dict(read, tool_input={"file_path": os.path.join(self.tmp.name, "user.jpg")}),
                                  "claude-code"),
                                 (read, "codex"),
                                 (dict(read, tool_input={"file_path": view[:-4] + ".md"}), "claude-code")):
            self.assertIsNone(self.hook("guard", payload, harness=harness), (payload, harness))

    @writes
    def test_r3_a_probandia_agent_starts_with_the_settings_of_its_role(self):
        # agent-models R3: the guard rewrites the launch (checked in Claude Code on 12 Oct. 2026, R1)
        launch = {"tool_name": "Agent", "tool_input": {"description": "x", "prompt": "p",
                                                       "subagent_type": "probandia:reader", "run_in_background": False}}
        self.assertIsNone(self.hook("guard", launch))   # nothing chosen: the agent's header decides
        for key, value in (("roles.reader.model", "opus"), ("roles.reader.effort", "high")):
            self.assertEqual(self.call("config", "set", key, value)[0], 0)
        out = self.hook("guard", launch)["hookSpecificOutput"]
        self.assertEqual(out["updatedInput"], dict(launch["tool_input"], model="opus", effort="high"))
        self.assertNotIn("permissionDecision", out)   # the user's permissions stay as they are
        with open(os.path.join(self.dir, ".probandia", "logs", "agents.jsonl"), encoding="utf-8") as fh:
            self.assertEqual(json.loads(fh.readline())["from"], {"model": "project", "effort": "project"})
        # the user's choice wins over a model the agent passed itself
        mine = dict(launch, tool_input=dict(launch["tool_input"], model="haiku"))
        self.assertEqual(self.hook("guard", mine)["hookSpecificOutput"]["updatedInput"]["model"], "opus")
        # another agent, another harness: nothing to rewrite
        explore = dict(launch, tool_input=dict(launch["tool_input"], subagent_type="Explore"))
        self.assertIsNone(self.hook("guard", explore))
        self.assertIsNone(self.hook("guard", launch, harness="codex"))
        # a model the Agent tool takes no alias for is left to the header; the effort still goes
        self.call("config", "set", "roles.reader.model", "claude-opus-5-5")
        out = self.hook("guard", launch)["hookSpecificOutput"]
        self.assertEqual(out["updatedInput"], dict(launch["tool_input"], effort="high"))
        # the orchestrator: the research's own --model and --effort come first
        code, text = self.call("resume", RID, "--mode", "subagent", "--model", "haiku", "--effort", "low")
        self.assertEqual(code, 0, text)
        self.call("config", "set", "roles.orchestrator.model", "opus")
        orchestrator = dict(launch, tool_input=dict(launch["tool_input"], subagent_type="probandia:orchestrator"))
        out = self.hook("guard", orchestrator)["hookSpecificOutput"]
        self.assertEqual((out["updatedInput"]["model"], out["updatedInput"]["effort"]), ("haiku", "low"))

    @writes
    def test_g14_the_reader_reading_a_whole_view(self):
        # token-economy J8: a sheet shows a view, a crop reads the act; a whole view is never read
        import struct

        folder = os.path.join(self.research.work, "images")
        os.makedirs(folder, exist_ok=True)

        def jpeg(name, width, height):   # a frame header is all the guard reads
            path = os.path.join(folder, name)
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8\xff\xc0\x00\x11\x08" + struct.pack(">HH", height, width) + b"\x03" + bytes(9))
            return path

        view = jpeg("ad50-607643-0090.jpg", 2800, 1900)
        read = {"tool_name": "Read", "tool_input": {"file_path": view}, "agent_type": "probandia:reader"}
        with mock.patch("probandia.guard._pillow", return_value=True):
            reason = self.deny_reason(self.hook("guard", read))
            self.assertTrue(reason.startswith("G-14: ad50-607643-0090.jpg is a whole view, 7093 tokens"), reason)
            for words in ('"size": 900', '"region": "x,y,w,h"', "image sheet"):   # T73c: the view small, the act cut
                self.assertIn(words, reason)
            self.assertTrue(self.deny_reason(self.hook("guard", read)).startswith("G-14"))   # every time
            for payload in (dict(read, tool_input={"file_path": jpeg("ad50-607643-0090-crop.jpg", 2800, 1900)}),
                            dict(read, tool_input={"file_path": jpeg("ad50-607643-0091.jpg", 900, 600)}),
                            dict(read, tool_input={"file_path": view[:-4] + "-missing.jpg"}),
                            dict(read, agent_type="probandia:researcher")):
                self.assertIsNone(self.hook("guard", payload), payload)
        with mock.patch("probandia.guard._pillow", return_value=False):   # no sheet, no crop: the view is read
            self.assertIsNone(self.hook("guard", read))

    def test_g3_third_party_reader_on_a_forbidden_host(self):
        d = self.hook("guard", {"tool_name": "mcp__jina__read_url",
                                "tool_input": {"url": "https://francearchives.gouv.fr/fr/search?q=x"}})
        self.assertTrue(self.deny_reason(d).startswith("G-3"))
        self.assertIsNone(self.hook("guard", {"tool_name": "mcp__jina__read_url",
                                              "tool_input": {"url": "https://example.org/"}}))
        # token-economy A8: every departmental archive of the catalogue refuses them
        scrape = {"tool_name": "mcp__firecrawl__firecrawl_scrape",
                  "tool_input": {"url": "https://www.archives-manche.fr/ark:/57115/x"}}
        self.assertTrue(self.deny_reason(self.hook("guard", scrape)).startswith("G-3"))
        # a host that only looks like an archive portal runs, with a word for the agent
        scrape["tool_input"]["url"] = "https://www.archives-xyz.fr/etat-civil"
        d = self.hook("guard", scrape)
        self.assertEqual(set(d["hookSpecificOutput"]), {"hookEventName", "additionalContext"})
        self.assertTrue(d["hookSpecificOutput"]["additionalContext"].startswith("G-3: www.archives-xyz.fr "))
        self.assertIn("(read) or the browser", d["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.hook("guard", scrape, harness="codex"))
        self.assertEqual(self.hook("guard", scrape, harness="antigravity"), {"allowTool": True})
        # a refusal elsewhere in the same call still wins
        scrape["tool_input"]["urls"] = ["https://www.archives-manche.fr/"]
        self.assertTrue(self.deny_reason(self.hook("guard", scrape)).startswith("G-3"))

    def test_droid_its_tool_names(self):
        # T259: Factory Droid's Create wrote a skill the guard let through (21 Oct. 2026); its ApplyPatch and Execute
        skill = os.path.join(self.dir, ".claude", "skills", "mine", "SKILL.md")
        for tool, tool_input in (("Create", {"file_path": skill, "content": "x"}),
                                 ("ApplyPatch", {"input": f"*** Begin Patch\n*** Add File: {skill}\n+x\n*** End Patch"})):
            d = self.hook("guard", {"tool_name": tool, "tool_input": tool_input}, harness="droid")
            self.assertTrue(self.deny_reason(d).startswith("G-8: "), (tool, d))
        d = self.hook("guard", {"tool_name": "Execute",
                                "tool_input": {"command": "curl -A 'Mozilla/5.0' https://www.archives-manche.fr/"}},
                      harness="droid")
        self.assertTrue(self.deny_reason(d).startswith("G-12: "), d)

    def test_grok_its_own_keys_tool_names_and_answer(self):
        # Grok Build sends toolName and toolInput, names its tools its own way and denies on {"decision": "deny"}:
        # the guard refused nothing there (found on 12 Oct. 2026); GROK_SESSION_ID names the harness
        def grok(tool, tool_input):
            payload = {"hookEventName": "PreToolUse", "sessionId": "s1", "cwd": self.dir, "workspaceRoot": self.dir,
                       "toolName": tool, "toolInput": tool_input}
            text = hooks.run("guard", io.StringIO(json.dumps(payload)), dict(self.env, GROK_SESSION_ID="s1"))
            return json.loads(text) if text.strip() else None

        skill = os.path.join(self.dir, ".claude", "skills", "mine", "SKILL.md")
        for tool in ("write", "search_replace", "delete_file"):   # Grok's Write, Edit, and its deletion
            d = grok(tool, {"path": skill, "content": "x", "old_string": "a", "new_string": "b"})
            self.assertEqual(d["decision"], "deny", tool)
            self.assertTrue(d["reason"].startswith("G-8: "), d)
        for tool in ("run_terminal_command", "run_terminal_cmd"):   # its shell, under two names
            d = grok(tool, {"command": "curl -A 'Mozilla/5.0' https://www.archives-manche.fr/"})
            self.assertTrue(d["reason"].startswith("G-12: "), (tool, d))
        self.assertIsNone(grok("run_terminal_command", {"command": "ls"}))
        self.assertIsNone(grok("write", {"path": os.path.join(self.dir, "notes.md"), "content": "x"}))

    @writes
    def test_g12_a_script_posing_as_a_browser_toward_an_archive(self):
        script = os.path.join(self.research.work, "scripts", "ad50.py")
        body = ('BASE = "https://www.archives-manche.fr"\n'
                'op.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0) Chrome/120")]\n')
        honest = body.replace("Mozilla/5.0 (Windows NT 10.0) Chrome/120", "Probandia/0.9.1")

        def write(path, content):
            return self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}})

        def edit(old, new):
            return self.hook("guard", {"tool_name": "Edit", "tool_input": {"file_path": script, "old_string": old,
                                                                            "new_string": new}})

        def shell(command):
            return self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": command}})

        self.assertTrue(self.deny_reason(write(script, body)).startswith("G-12"))
        self.assertIsNone(write(script, honest))
        self.assertIsNone(write(script, body.replace("www.archives-manche.fr", "example.org")))
        self.assertIsNone(write(script[:-3] + ".md", body))                     # a note, not a script
        os.makedirs(os.path.dirname(script), exist_ok=True)
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(honest)
        self.assertTrue(self.deny_reason(edit("Probandia/0.9.1", "Mozilla/5.0")).startswith("G-12"))
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(body)
        self.assertIsNone(edit("Mozilla/5.0 (Windows NT 10.0) Chrome/120", "Probandia/0.9.1"))  # undoing it
        rel = os.path.relpath(script, self.dir).replace("\\", "/")
        self.assertTrue(self.deny_reason(shell(f"python {rel} /recherche")).startswith("G-12"))
        self.assertTrue(self.deny_reason(shell("curl -A 'Mozilla/5.0' https://www.archives-manche.fr/"))
                        .startswith("G-12"))
        self.assertIsNone(shell("curl https://www.archives-manche.fr/"))

    def test_g4_unattended_run_outside_work(self):
        env = {"PROBANDIA_WORKER": "1"}
        d = self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.dir, "notes.md")}},
                      env=env)
        self.assertTrue(self.deny_reason(d).startswith("G-4"))
        inside = os.path.join(self.research.work, "notes.md")
        self.assertIsNone(self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": inside}}, env=env))

    @writes
    def test_g5_draft_script(self):
        self.open_pass()
        lib = os.path.join(self.dir, "library")
        os.makedirs(os.path.join(lib, "connectors"))
        script = {"id": "ad56", "kind": "connector", "path": "connectors/ad56.py", "purpose": "p",
                  "status": "draft", "version": 1, "sha256": "abc"}
        yamlio.dump(os.path.join(lib, "manifest.yaml"), {"schema": 1, "scripts": [script]})
        payload = {"tool_name": "Bash", "tool_input": {"command": "python library/connectors/ad56.py Hugo"}}
        self.assertTrue(self.deny_reason(self.hook("guard", payload)).startswith("G-5"))
        with open(os.path.join(self.dir, ".probandia", "approved-scripts.json"), "w", encoding="utf-8") as fh:
            json.dump([{"id": "ad56", "sha256": "abc"}], fh)
        self.assertIsNone(self.hook("guard", payload))

    def test_refusal_formats(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "report/x.md"}, "agent_type": "researcher"}
        cursor = self.hook("guard", payload, harness="cursor")
        self.assertEqual(cursor["permission"], "deny")
        self.assertTrue(cursor["agentMessage"].startswith("G-1"))
        agy = self.hook("guard", payload, harness="antigravity")
        self.assertEqual(agy["allowTool"], False)
        self.assertTrue(agy["denyReason"].startswith("G-1"))
        self.assertEqual(self.hook("guard", {"tool_name": "Read"}, harness="antigravity"), {"allowTool": True})
        oc = self.hook("guard", dict(payload, harness="opencode"), harness=None)
        self.assertEqual(oc["permission"], "deny")
        codex = self.hook("guard", payload, harness="codex")
        self.assertEqual(codex["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_never_blocks_on_its_own_failure(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "report/x.md"}, "agent_type": "researcher"}
        with mock.patch("probandia.guard.check", side_effect=RuntimeError("boom")):
            self.assertIsNone(self.hook("guard", payload))
            self.assertEqual(self.hook("guard", payload, harness="antigravity"), {"allowTool": True})
        self.assertEqual(hooks.run("guard", io.StringIO("{not json"), self.env, "claude-code"), "")

    def test_silent_outside_a_project(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "report/x.md"}, "agent_type": "researcher",
                   "cwd": self.tmp.name}
        text = hooks.run("guard", io.StringIO(json.dumps(payload)), self.env, "claude-code")
        self.assertEqual(text, "")

    def test_cli_entry_point(self):
        payload = json.dumps({"cwd": self.dir, "tool_name": "Write", "agent_type": "researcher",
                              "tool_input": {"file_path": "research.yaml"}})
        printed = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", printed):
            code, _out = self.call("hook", "guard", "--harness", "claude-code")
        self.assertEqual(code, 0)
        self.assertIn('"permissionDecision": "deny"', printed.getvalue())

    @writes
    def test_g18_personnes_yaml_of_a_linked_workshop(self):
        # WS4-T5: only workshop push writes the workshop's personnes.yaml, for every agent; reading is open
        people = os.path.join(self.dir, "commun", "personnes.yaml")
        os.makedirs(os.path.dirname(people))
        with open(people, "w", encoding="utf-8") as fh:
            fh.write("personnes: []\n")
        edit = {"tool_name": "Edit", "tool_input": {"file_path": people, "old_string": "[]", "new_string": "[x]"}}
        write = {"tool_name": "Write", "tool_input": {"file_path": "commun/personnes.yaml", "content": "x"}}
        shell = {"tool_name": "Bash", "tool_input": {"command": "echo '- id: x' >> commun/personnes.yaml"}}
        read = {"tool_name": "Read", "tool_input": {"file_path": people}}
        for payload in (edit, write, shell):   # a project without workshop.yaml: nothing changes
            self.assertIsNone(self.deny_reason(self.hook("guard", payload)), payload)
        yamlio.dump(os.path.join(self.dir, "workshop.yaml"), {"schema": 1, "adapter": "prototype", "root": "."})
        for payload in (edit, write, shell, dict(edit, agent_type="probandia:researcher")):
            reason = self.deny_reason(self.hook("guard", payload))
            self.assertTrue(reason and reason.startswith("G-18: "), (payload, reason))
            self.assertIn("workshop push", reason)
        self.assertIsNone(self.deny_reason(self.hook("guard", read)))
        other = {"tool_name": "Write", "tool_input": {"file_path": "commun/lieux.yaml", "content": "x"}}
        self.assertIsNone(self.deny_reason(self.hook("guard", other)))


TRANSCRIPTS =os.path.join(os.path.dirname(FIXTURE), "transcripts")


class Tokens(Base):
    """The stop hooks record the tokens of the transcript, by pass and role."""

    def copy(self, name):
        dest = os.path.join(self.tmp.name, "transcripts")
        if not os.path.isdir(dest):
            shutil.copytree(TRANSCRIPTS, dest)
        return os.path.join(dest, name)

    def rows(self):
        path = os.path.join(self.dir, ".probandia", "tokens.jsonl")
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    def test_claude_code_transcripts_by_pass_and_role(self):
        from probandia import tokens
        self.assertEqual(tokens.parse(os.path.join(TRANSCRIPTS, "claude-session.jsonl")),
                         {"input": 5, "output": 200, "cache_read": 62000, "cache_write": 2500,
                          "cache_write_5m": 0, "model": "claude-opus-5-5"})   # msg_1 counted once, at its last line
        self.open_pass()
        main = self.copy("claude-session.jsonl")
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})
        self.hook("verify", {"hook_event_name": "SubagentStop", "transcript_path": main, "agent_id": "a1"})
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})   # nothing new
        self.assertEqual([(r["role"], r["pass"], r["output"], r["research"]) for r in self.rows()],
                         [("session", 2, 200, RID), ("researcher", 2, 400, RID)])
        code, out = self.call("status", RID)
        self.assertIn("TOKENS_PASS=2", out)
        self.assertIn("- tokens=researcher input=5 output=400 cache_read=8000 cache_write=6000 weighted=14805", out)
        self.assertIn("- tokens=session input=5 output=200 cache_read=62000 cache_write=2500 weighted=12205", out)

    def test_a_heavy_base_context_is_told_by_doctor_and_pass_end(self):
        # a real session of 6 Oct. 2026: 85 426 tokens before any work, read again at each call
        from probandia import tokens

        self.open_pass()
        main = os.path.join(self.tmp.name, "heavy.jsonl")
        with open(main, "w", encoding="utf-8") as fh:
            for i, ctx in enumerate((85426, 90000)):
                fh.write(json.dumps({"type": "assistant", "timestamp": f"2026-10-06T09:3{i}:00Z", "message": {
                    "id": f"msg_{i}", "usage": {"input_tokens": 6, "output_tokens": 10,
                                                "cache_read_input_tokens": ctx - 6,
                                                "cache_creation_input_tokens": 0}}}) + "\n")
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})
        self.assertEqual(tokens.base_context(self.dir)[0], 85426)
        code, out = self.call("doctor", env={"PWD": self.dir})
        self.assertEqual((self.value(out, "CONTEXT_BASE"), self.value(out, "STATUS")), ("85426", "WARN"))
        self.assertIn("enabledPlugins", out)
        code, out = self.call("pass", "end", RID, "--summary", "nothing found; next: the census")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.value(out, "CONTEXT_BASE"), "85426")

    def test_a_light_base_context_stays_silent(self):
        self.open_pass()
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": self.copy("claude-session.jsonl")})
        code, out = self.call("pass", "end", RID, "--summary", "nothing found; next: the census")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.value(out, "CONTEXT_BASE"))

    def test_only_what_is_new_is_recorded(self):
        self.open_pass()
        main = self.copy("claude-session.jsonl")
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})
        with open(main, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"id": "msg_3", "usage": {
                "input_tokens": 1, "output_tokens": 50, "cache_read_input_tokens": 33000,
                "cache_creation_input_tokens": 0}}}) + "\n")
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})
        self.assertEqual([(r["output"], r["cache_read"]) for r in self.rows()], [(200, 62000), (50, 33000)])

    def test_a_subagent_without_its_transcript_is_never_the_session(self):
        self.open_pass()
        main = self.copy("claude-session.jsonl")
        self.hook("verify", {"hook_event_name": "SubagentStop", "transcript_path": main, "agent_id": "zz",
                             "agent_type": "probandia:searcher"})
        self.assertEqual(self.rows(), [])

    def test_codex_rollouts_and_workers(self):
        from probandia import tokens
        self.assertEqual(tokens.parse(os.path.join(TRANSCRIPTS, "codex-rollout.jsonl")),
                         {"input": 43395 - 27776, "output": 441, "cache_read": 27776, "cache_write": 0,
                          "cache_write_5m": 0, "model": "gpt-5.5-codex"})   # the last cumulative count
        self.open_pass()
        rollout = self.copy("codex-rollout.jsonl")
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": rollout}, harness="codex",
                  env={"PROBANDIA_WORKER": "1"})      # a headless worker is measured too
        self.assertEqual([(r["harness"], r["cache_read"]) for r in self.rows()], [("codex", 27776)])

    def write(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def assistant(self, mid, ts, output, **extra):
        return dict({"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": "claude-opus-5-5",
                     "usage": {"input_tokens": 1, "output_tokens": output, "cache_read_input_tokens": 0,
                               "cache_creation_input_tokens": 0}}}, **extra)

    def test_each_message_goes_to_the_pass_of_its_time(self):
        # live, 2 October 2026: the session's last stop came after `pass end`, and the
        # whole pass was recorded without a pass
        from probandia import events
        self.open_pass()
        self.assertEqual(self.call("pass", "end", RID, "--summary", "fin")[0], 0)
        log = events.read(self.research.events_path)
        start = next(e["ts"] for e in log if e["type"] == "pass.started" and e["pass"] == 2)
        end = next(e["ts"] for e in log if e["type"] == "pass.ended" and e["pass"] == 2)
        main = os.path.join(self.tmp.name, "t", "s2.jsonl")
        self.write(main, [self.assistant("m0", "2020-01-01T00:00:00Z", 7),       # before the pass
                          self.assistant("m1", start, 100), self.assistant("m2", end, 20),
                          self.assistant("m3", "2999-01-01T00:00:00Z", 3)])       # the closing summary
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})
        self.assertEqual(sorted((r["pass"] or 0, r["output"]) for r in self.rows()), [(0, 7), (2, 123)])

    def test_a_teammate_gets_its_type_from_the_call_that_named_it(self):
        self.open_pass()
        main = os.path.join(self.tmp.name, "t", "team.jsonl")
        self.write(main, [{"type": "assistant", "message": {"id": "lead", "content": [
            {"type": "tool_use", "name": "Agent", "input": {"name": "r1-perrin",
                                                            "subagent_type": "probandia:researcher"}}]}}])
        sub = os.path.join(self.tmp.name, "t", "team", "subagents", "agent-ar1-perrin-42.jsonl")
        self.write(sub, [self.assistant("s1", None, 50)])
        with open(sub[:-6] + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"agentType": "r1-perrin", "name": "r1-perrin", "taskKind": "in_process_teammate"}, fh)
        self.hook("verify", {"hook_event_name": "SubagentStop", "transcript_path": main,
                             "agent_transcript_path": sub})
        self.assertEqual([(r["role"], r["agent"], r["output"]) for r in self.rows()],
                         [("researcher", "r1-perrin", 50)])

    def test_outside_a_pass_the_tokens_carry_no_pass(self):
        main = self.copy("claude-session.jsonl")
        self.hook("verify", {"hook_event_name": "Stop", "transcript_path": main})
        self.assertEqual([r["pass"] for r in self.rows()], [None])


class NativeBudget(Base):
    def native(self, n, session="test"):
        for i in range(n):
            self.hook("log", {"tool_name": "WebSearch", "tool_input": {"query": f"Hugo {i}"},
                              "tool_response": {"results": []}}, env={"PROBANDIA_SESSION": session})

    def test_an_accented_query_survives_a_windows_console(self):
        # the harness writes UTF-8; Python on Windows reads its stdin as cp1252
        self.open_pass()
        payload = {"cwd": self.dir, "tool_name": "WebSearch", "tool_input": {"query": "général Hugo Besançon"},
                   "tool_response": {"results": []}}
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                                 encoding="cp1252")
        with mock.patch("sys.stdin", stdin):
            hooks.run("log", None, self.env, "claude-code")
        logged = yamlio.load(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"))["searches"]
        self.assertEqual(logged[-1]["query"], "général Hugo Besançon")

    def test_four_in_one_turn_then_providers(self):
        self.call("config", "set", "search.max_parallel", "4")
        self.call("config", "set", "search.native_max_per_pass", "6")
        self.open_pass()
        code, out = self.call("plan", RID)
        self.assertEqual((self.value(out, "NATIVE_PARALLEL"), self.value(out, "NATIVE_LEFT")), ("4", "6"))
        self.native(4)  # four parallel searches, logged by the hook
        logged = [s for s in yamlio.load(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"))
                  ["searches"] if s["kind"] == "native" and s["pass"] == 2]
        self.assertEqual(len(logged), 4)
        self.assertEqual({s["filters"]["session"] for s in logged}, {"test"})
        self.assertIsNone(self.hook("guard", {"tool_name": "WebSearch", "tool_input": {"query": "x"}}))
        self.native(2)
        d = self.hook("guard", {"tool_name": "WebSearch", "tool_input": {"query": "x"}})
        self.assertTrue(d["hookSpecificOutput"]["permissionDecisionReason"].startswith("W-3"))
        # an MCP server's search_web is not paid from the native budget (FL-D5): the engine makes it (G-15, T54)
        d = self.hook("guard", {"tool_name": "mcp__jina__search_web", "tool_input": {"query": "x"}})
        self.assertTrue(d["hookSpecificOutput"]["permissionDecisionReason"].startswith("G-15"))
        code, out = self.call("search", "--log-native", "--query", "late", "--results", "0")
        self.assertIn("REASON=native-budget", out)
        self.assertEqual(self.value(out, "NATIVE_LEFT"), "0")
        # logged by hand where no hook does it, an MCP search is a provider call (FL1-T3)
        code, out = self.call("search", "--log-native", "--engine", "mcp:jina", "--query", "mcp", "--results", "3")
        self.assertEqual((code, self.value(out, "NATIVE_LEFT")), (0, "0"))
        logged = yamlio.load(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"))["searches"]
        self.assertEqual((logged[-1]["kind"], logged[-1]["engine"]), ("provider", "mcp:jina"))

    QUERY = "Victor Hugo Besançon 1802"

    def searches(self):
        return yamlio.load(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"))["searches"]

    def hook_then_left(self):
        """The native searches left before a WebSearch the hook logs."""
        self.open_pass()
        left = int(self.value(self.call("plan", RID)[1], "NATIVE_LEFT"))
        self.hook("log", {"tool_name": "WebSearch", "tool_input": {"query": self.QUERY},
                          "tool_response": {"results": [{"url": "https://example.org/hugo"}]}})
        return left

    def test_native_search_logged_once(self):
        # T51: in Claude Code the hook logs each WebSearch; the agent logging it again adds nothing
        left = self.hook_then_left()
        code, out = self.call("search", "--log-native", "--query", "victor hugo  Besançon 1802", "--results", "1")
        self.assertEqual(code, 0, out)
        natives = [s for s in self.searches() if s["kind"] == "native" and s["pass"] == 2]
        self.assertEqual(len(natives), 1)
        self.assertEqual(self.value(out, "SEARCH"), natives[0]["id"])
        self.assertEqual(int(self.value(out, "NATIVE_LEFT")), left - 1)
        self.assertIn("already logged", out)
        logged = [e for e in events.read(self.research.events_path) if e["type"] == "search.logged"
                  and e["pass"] == 2]
        self.assertEqual(len(logged), 1)
        # another query, or the same in another session, is a search of its own
        self.call("search", "--log-native", "--query", self.QUERY + " acte", "--results", "0")
        self.call("search", "--log-native", "--query", self.QUERY, "--results", "0", env={"PROBANDIA_SESSION": "other"})
        self.assertEqual(len([s for s in self.searches() if s["kind"] == "native" and s["pass"] == 2]), 3)

    def test_grok_native_search_logged_from_its_camel_case(self):
        # T126: Grok's web_search arrives as toolName and toolInput
        self.open_pass()
        self.hook("log", {"toolName": "web_search", "toolInput": {"query": self.QUERY}}, harness="grok")
        natives = [s for s in self.searches() if s["kind"] == "native" and s["pass"] == 2]
        self.assertEqual([s["engine"] for s in natives], ["native:grok"])

    def test_native_search_logged_once_from_proposal(self):
        # T51: measured at the bench (i1, run 2): one WebSearch, two native entries, the hook's and the proposal's
        from probandia.util.fs import iso, utc_now
        from probandia.util.ids import ulid

        left = self.hook_then_left()
        doc = {"schema": 1, "id": ulid(), "research": RID, "pass": 2,
               "author": {"harness": "claude-code", "agent": "session"},
               "searches": [{"id": f"s-{ulid()}", "ts": iso(utc_now()), "kind": "native",
                             "engine": "native:claude-code", "query": self.QUERY, "result": "positive",
                             "results": 1}]}
        path = os.path.join(self.tmp.name, f"{doc['id']}.yaml")
        yamlio.dump(path, doc)
        code, out = self.call("propose", RID, path, "--apply")
        self.assertEqual((code, self.value(out, "APPLIED")), (0, "true"), out)
        natives = [s for s in self.searches() if s["kind"] == "native" and s["pass"] == 2]
        self.assertEqual([s["query"] for s in natives], [self.QUERY])
        self.assertNotEqual(natives[0]["id"], doc["searches"][0]["id"])   # the hook's entry stays
        self.assertEqual(int(self.value(self.call("plan", RID)[1], "NATIVE_LEFT")), left - 1)

    def test_session_cap(self):
        from probandia.budget import native_budget, split
        from probandia.config import load

        self.call("config", "set", "search.native_max_per_pass", "200")
        self.open_pass()
        from probandia.providers import searchlog

        path = os.path.join(self.dir, "families", "hugo", "index", "searches.yaml")
        doc = yamlio.load(path)
        doc["searches"] += [searchlog.entry(f"q{i}", "native", "native:claude-code", "opaque", "negative", RID, 2, 0,
                                            filters={"session": "other"}) for i in range(180)]
        yamlio.dump(path, doc)
        cfg = load(self.dir, self.env)
        self.assertEqual(native_budget(self.dir, self.research, cfg, {"PROBANDIA_SESSION": "other"},
                                       "claude-code")["left"], 0)
        self.assertEqual(native_budget(self.dir, self.research, cfg, {"PROBANDIA_SESSION": "other"},
                                       "codex")["left"], 20)
        self.assertEqual(split(10, 3), [4, 3, 3])


class NativeRepeat(Base):
    """T55: the same native search, for the same family within cache.days, is refused once."""
    QUERY = "Victor Hugo Besançon 1802"

    def deny(self, payload):
        return ((self.hook("guard", payload) or {}).get("hookSpecificOutput") or {}).get("permissionDecisionReason")

    def search(self, query, **extra):
        return {"tool_name": "WebSearch", "tool_input": dict({"query": query}, **extra)}

    def run_search(self, query, urls=(), **extra):
        self.hook("log", dict(self.search(query, **extra), tool_response={"results": [{"url": u} for u in urls]}))

    def test_a_native_search_run_again_is_refused_once(self):
        from probandia.util.fs import iso, utc_now

        self.open_pass()
        first = self.search(self.QUERY, allowed_domains=["example.org"])
        self.assertIsNone(self.hook("guard", first))   # never run
        self.run_search(self.QUERY, ("https://example.org/a", "https://example.org/b"), allowed_domains=["example.org"])
        again = self.search("victor  HUGO Besançon 1802", allowed_domains=["Example.org"])   # normalised
        reason = self.deny(again)
        self.assertTrue(reason.startswith("G-16: "), reason)
        self.assertIn(f"on {iso(utc_now())[:10]} (pass 2, 2 results)", reason)
        path = reason.split("its URLs are in ", 1)[1].split(": use them", 1)[0]
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["payload"]["urls"], ["https://example.org/a", "https://example.org/b"])
        self.assertIsNone(self.hook("guard", again))   # once: then allowed
        stats = self.call("cache", "stats", "--provider", "native")[1]   # T64: the refusal served its URLs
        self.assertIn("- provider=native entries=1 ", stats)
        self.assertIn(" served=1 saved=0", stats)
        # another variant, or other domains, is another search
        self.assertIsNone(self.hook("guard", self.search("Victor Hugo Besançon 1803", allowed_domains=["example.org"])))
        self.assertIsNone(self.hook("guard", self.search(self.QUERY)))
        # whatever the pass: a zero of the pass before is refused too
        self.run_search("Léopold Hugo Nancy")
        self.assertEqual(self.call("pass", "end", RID, "--summary", "nothing yet")[0], 0)
        self.open_pass()
        reason = self.deny(self.search("Léopold Hugo Nancy"))
        self.assertIn("(pass 2, 0 results)", reason)
        # beyond cache.days, it runs
        self.run_search("Sophie Trébuchet Nantes")
        stale = self.deny(self.search("Sophie Trébuchet Nantes")).split("its URLs are in ", 1)[1].split(": use", 1)[0]
        self.run_search("Sophie Trébuchet Nantes")   # allowed, run again: kept anew, then 8 days old
        with open(stale, encoding="utf-8") as fh:
            entry = json.load(fh)
        entry["created"] -= 8 * 86400
        with open(stale, "w", encoding="utf-8") as fh:
            json.dump(entry, fh)
        os.remove(os.path.join(self.dir, ".probandia", "guard-repeats.json"))
        self.assertIsNone(self.hook("guard", self.search("Sophie Trébuchet Nantes")))

    def test_an_engine_search_run_again_is_served_by_its_cache(self):
        from probandia.cli import search_cmd
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        def transport(method, url, headers, body, timeout):
            fx = fixture("tavily", "search-ok.json")
            return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        self.open_pass()
        command = 'python .probandia/pb.py search "Hugo Besançon 1802" --engine tavily'
        units = []
        with mock.patch.object(search_cmd, "_client", make_client):
            for _ in range(2):
                self.assertIsNone(self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": command}}))
                code, out = self.call("search", "Hugo Besançon 1802", "--engine", "tavily",
                                      env={**REUSE, "TAVILY_API_KEY": "k"})
                self.assertEqual(code, 0, out)
                units.append(self.value(out, "UNITS"))
        self.assertNotEqual(units[0], "0")
        self.assertEqual(units[1], "0")


class WebFetchFirst(Base):
    """T57: a page goes through read first."""
    PROMPT = "When was Victor Hugo born?"

    def fetch(self, url, harness="claude-code"):
        return self.hook("guard", {"tool_name": "WebFetch", "tool_input": {"url": url, "prompt": self.PROMPT}},
                         harness=harness)

    def deny(self, d):
        return ((d or {}).get("hookSpecificOutput") or {}).get("permissionDecisionReason")

    def test_an_archive_of_the_catalogue_is_read_by_the_engine(self):
        url = "https://gallica.bnf.fr/ark:/12148/bpt6k5356122w/f2.texteBrut"
        for _ in range(2):   # two close together: refused both, Gallica's 5 a minute is the engine's to keep
            reason = self.deny(self.fetch(url))
            self.assertTrue(reason.startswith("G-17: gallica.bnf.fr is an archive of the catalogue"), reason)
            self.assertIn(f'read {url} --question "{self.PROMPT}"', reason)
        self.assertTrue(self.deny(self.fetch(url, harness="codex")).startswith("G-17"))

    def test_a_page_read_never_gets_a_notice_once(self):
        url = "https://example.org/hugo/naissance"
        d = self.fetch(url)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", d)   # it runs, with a word for the agent
        self.assertTrue(d["additionalContext"].startswith("G-17: read the page with the engine first"), d)
        self.assertIn(f'read {url} --question "{self.PROMPT}"', d["additionalContext"])
        self.assertIsNone(self.fetch(url))   # once per URL
        self.assertIn("additionalContext", self.fetch(url + "-2")["hookSpecificOutput"])

    def test_a_page_read_already_points_to_its_cache(self):
        from probandia.cli import reading_cmd
        from tests.unit.test_reading import Transport

        url = "https://fr.wikipedia.org/wiki/Octeville"
        with open(os.path.join(ROOT, "tests", "fixtures", "pages", "wikipedia-octeville.html"), encoding="utf-8") as fh:
            page = fh.read()
        transport = Transport({url: (200, {"Content-Type": "text/html; charset=utf-8"}, page)})
        build = reading_cmd.build_reader
        with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work=None, t=None: build(ctx, work, transport)):
            code, out = self.call("read", url, "--question", "mairie")
        self.assertEqual((code, self.value(out, "TRIED")), (0, "http:ok"), out)
        reason = self.deny(self.fetch(url))
        self.assertTrue(reason.startswith("G-17: read has this page already, for free"), reason)
        path = reason.split(" or its text in ", 1)[1].split(" (payload.text)", 1)[0]
        with open(path, encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["payload"]["text"])
        self.assertIsNone(self.fetch(url))   # once: then allowed

    def read_fails(self, url, robots, readers=True):
        from probandia.cli import reading_cmd
        from tests.unit.test_reading import Transport

        host = url.split("/")[2]
        transport = Transport({f"https://{host}/robots.txt": (200, {}, robots)})
        build = reading_cmd.build_reader
        with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work=None, t=None: build(ctx, work, transport)), \
                mock.patch("probandia.reading.browser.available", return_value=False):   # no real browser here
            code, out = self.call("read", url, "--question", "naissance")
        self.assertEqual((code, self.value(out, "REASON")), (1, "robots"), out)
        self.assertFalse([u for _m, u, _h in transport.calls if u == url])   # T66: never fetched by the engine
        tried = self.value(out, "TRIED")
        self.assertEqual("reader:jina" in tried, readers, tried)            # handed to the readers, if allowed

    def test_a_page_read_could_not_read_is_fetched(self):   # T66: no loop between read and WebFetch
        url = "https://gallica.bnf.fr/services/engine/search/sru?query=Hugo%20Besancon"
        self.read_fails(url, "User-agent: *\nDisallow: /services/engine/search/\n")
        d = self.fetch(url + "#resultats")["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", d)   # it runs, though the host is an archive of the catalogue
        self.assertTrue(d["additionalContext"].startswith("G-17: read could not read this page (robots, "), d)
        self.assertIsNone(self.fetch(url))   # the notice once, then nothing
        other = "https://gallica.bnf.fr/ark:/12148/bpt6k5356122w/f2.texteBrut"
        self.assertTrue(self.deny(self.fetch(other)).startswith("G-17: gallica.bnf.fr is an archive"))

    def test_a_page_read_failed_is_forgotten_once_read(self):
        from probandia.reading.cache import failure_of, forget_failure, note_failure

        url = "https://example.org/hugo/besancon"
        note_failure(self.dir, url, "blocked", 60, clock=lambda: 1000.0)
        self.assertEqual(failure_of(self.dir, url, clock=lambda: 1059.0)["status"], "blocked")
        self.assertIsNone(failure_of(self.dir, url, clock=lambda: 1060.0))   # the cache's lifetime only
        note_failure(self.dir, url, "blocked", 60)
        forget_failure(self.dir, url)
        self.assertIsNone(failure_of(self.dir, url))

    def test_a_host_forbidden_to_third_parties_stays_refused(self):
        url = "https://archives.aisne.fr/recherche/etat-civil"   # third_party: forbidden in archives-fr-ad.yaml
        self.read_fails(url, "User-agent: *\nDisallow: /recherche/\n", readers=False)
        reason = self.deny(self.fetch(url))
        self.assertTrue(reason.startswith("G-17: read could not read this page (robots, "), reason)
        self.assertIn(f"read {url} --interactive", reason)


class Questions(Base):
    Q = "Who were the parents of Victor Hugo?"

    def test_who_runs_then_the_team_in_one_call(self):
        code, out = self.call("new", self.Q, "--family", "hugo", "--harness", "claude-code")
        self.assertEqual(code, 3)
        self.assertEqual((self.value(out, "QUESTION"), self.value(out, "TOOL")), ("run_mode", "AskUserQuestion"))
        code, out = self.call("new", self.Q, "--family", "hugo", "--mode", "team", "--harness", "claude-code")
        self.assertEqual(self.value(out, "QUESTIONS"), "team_agents|team_effort|team_passes")
        self.assertEqual(self.value(out, "CHOICES_TEAM_EFFORT"), "low|medium|high|xhigh|max")
        self.assertEqual(self.value(out, "OPTION_TEAM_PASSES"), "--passes")

    def test_subagent_choices_follow_the_harness(self):
        code, out = self.call("new", self.Q, "--family", "hugo", "--mode", "subagent", "--harness", "claude-code")
        self.assertEqual(self.value(out, "QUESTIONS"), "run_model|run_effort")
        self.assertEqual(self.value(out, "CHOICES_RUN_MODEL"), "sonnet|opus|haiku|fable")
        code, out = self.call("new", self.Q, "--family", "hugo", "--mode", "subagent", "--harness", "grok")
        self.assertEqual(self.value(out, "QUESTION"), "run_effort")
        self.assertEqual(self.value(out, "CHOICES"), "low|medium|high|xhigh")
        code, out = self.call("new", self.Q, "--family", "hugo", "--mode", "subagent", "--harness", "cursor")
        self.assertEqual(code, 0, out)  # Cursor: the harness's own model and effort, nothing to ask

    def test_numbered_choices_where_there_is_no_tool(self):
        code, out = self.call("new", self.Q, "--family", "hugo")
        self.assertEqual(self.value(out, "TOOL"), "none")
        with open(os.path.join(ROOT, "skills", "ask", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertIn("numbered choices", skill)
        self.assertIn("AskUserQuestion", skill)

    def test_headless_takes_the_defaults(self):
        code, out = self.call("new", self.Q, "--family", "hugo", env={"PROBANDIA_HEADLESS": "1"})
        self.assertEqual(code, 0, out)
        self.assertEqual((self.value(out, "RUN_MODE"), self.value(out, "ASSUMED")), ("session", "true"))
        rid = self.value(out, "RESEARCH")
        started = events.read(Research(self.dir, "hugo", rid).events_path)[0]
        self.assertTrue(started["payload"]["assumed"])
        code, out = self.call("new", "Where did Léopold Hugo die?", "--family", "hugo", "--mode", "team",
                              "--harness", "claude-code", env={"PROBANDIA_WORKER": "1"})
        run = Research(self.dir, "hugo", self.value(out, "RESEARCH")).meta()["run"]
        self.assertEqual((run["max_agents"], run["effort"], run["max_passes"]), (3, "medium", 2))


class Team(Base):
    def setUp(self):
        super().setUp()
        self.open_pass("--mode", "team", "--agents", "3", "--effort", "high", "--passes", "2")

    def test_waves_capped(self):
        code, out = self.call("team", "wave", RID, "--agents", "5")
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=team-agents", out)
        code, out = self.call("team", "wave", RID, "--agents", "3")
        self.assertEqual((code, self.value(out, "WAVE")), (0, "1"))
        self.assertIn("- native=14,13,13", out)
        code, out = self.call("team", "wave", RID, "--agents", "2")
        self.assertEqual(self.value(out, "WAVE"), "2")

    def test_passes_capped(self):
        self.call("pass", "end", RID, "--summary", "x")
        code, out = self.call("resume", RID)
        self.assertEqual(code, 4, out)
        self.assertIn("REASON=team-passes", out)

    def test_relay(self):
        code, out = self.call("team", "send", RID, "--from", "researcher-1", "--to", "orchestrator",
                              "--type", "finding", "--body", "acte 112 found", "--refs", "s-01J9")
        self.assertEqual(code, 0, out)
        code, out = self.call("team", "inbox", RID, "--to", "orchestrator")
        self.assertEqual(self.value(out, "MESSAGES"), "1")
        self.assertIn('"from": "researcher-1"', out)
        code, out = self.call("team", "inbox", RID, "--to", "orchestrator")
        self.assertEqual(self.value(out, "MESSAGES"), "0")
        code, out = self.call("team", "send", RID, "--to", "../x", "--body", "y")
        self.assertEqual(code, 2)


    def test_send_message_copied_to_the_relay(self):
        msg = {"type": "finding", "from": "r2-archives", "to": "r1-bases", "body": "born at Nancy",
               "refs": ["https://example.org/acte"]}
        self.hook("log", {"tool_name": "SendMessage", "agent_type": "probandia:researcher",
                          "tool_input": {"to": "r1-bases", "message": json.dumps(msg)}})
        self.hook("log", {"tool_name": "SendMessage", "agent_type": "probandia:researcher",
                          "tool_input": {"to": "team-lead", "message": "plain text"}})
        code, out = self.call("team", "inbox", RID, "--to", "r1-bases")
        self.assertEqual(self.value(out, "MESSAGES"), "1", out)
        self.assertIn('"from": "r2-archives"', out)
        team = os.path.join(self.research.work, "team")
        with open(os.path.join(team, "r1-bases.inbox.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh]
        self.assertEqual((rows[0]["via"], rows[0]["pass"]), ("SendMessage", 2))
        with open(os.path.join(team, "orchestrator.inbox.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh]
        self.assertEqual((rows[0]["type"], rows[0]["from"], rows[0]["body"]), ("finding", "researcher", "plain text"))

    def test_the_team_skill_sends_the_json_as_text(self):
        # Claude Code's SendMessage takes a string: an object was refused in the run of 3 October 2026
        from tests import ROOT

        with open(os.path.join(ROOT, "skills", "team", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("in `message` as one line of text", text)
        self.assertIn("If it refuses", text)

    def test_send_message_outside_a_team_is_not_copied(self):
        meta_path = os.path.join(self.dir, "families", "hugo", "research", RID, "research.yaml")
        meta = yamlio.load(meta_path)
        meta["run"]["mode"] = "session"
        yamlio.dump(meta_path, meta)
        self.hook("log", {"tool_name": "SendMessage", "tool_input": {"to": "r1", "message": "x"}})
        self.assertFalse(os.path.exists(os.path.join(self.research.work, "team", "r1.inbox.jsonl")))

class OtherHooks(Base):
    def test_the_log_hook_runs_only_after_the_tools_it_records(self):
        # token-economy G1: Bash and WebFetch left the matchers, since the log does nothing for them
        import re

        from probandia.install import manifests, opencode

        def snapshot():
            out = {}
            for root, _dirs, files in os.walk(self.dir):
                for f in files:
                    p = os.path.join(root, f)
                    out[p] = (os.path.getsize(p), os.path.getmtime(p))
            return out

        self.open_pass()
        before = snapshot()
        for payload in ({"tool_name": "Bash", "tool_input": {"command": "python .probandia/pb.py search x"},
                         "tool_response": {"stdout": "https://example.org/a"}},
                        {"tool_name": "WebFetch", "tool_input": {"url": "https://example.org/", "prompt": "x"},
                         "tool_response": "https://example.org/b"},
                        {"command": "ls", "output": "x"}):   # Cursor's afterShellExecution
            self.assertIsNone(self.hook("log", payload))
        self.assertEqual(snapshot(), before)
        recorded = (set(hooks.WEB_SEARCH_TOOLS) | set(hooks.MESSAGE_TOOLS) | set(hooks.LEARNED_TOOLS)
                    | {"mcp__tavily__tavily_search"})
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as fh:
            matcher = json.load(fh)["hooks"]["PostToolUse"][0]["matcher"]
        claude = {t for t in recorded if t[:1].isupper() or t.startswith(("mcp__", "send_"))}
        self.assertEqual([t for t in claude if not re.fullmatch(matcher, t)], [])
        self.assertIsNone(re.fullmatch(matcher, "Bash"))
        self.assertTrue(re.fullmatch(matcher, "WebFetch"))   # T59: back, to tell a page not consulted
        self.assertNotIn("afterShellExecution", manifests.cursor_hooks({"hooks": {"PostToolUse": [
            {"hooks": [{"command": "x"}]}]}})["hooks"])
        silent = set(re.search(r"UNLOGGED = new Set\(\[(.*?)\]\)", opencode.PLUGIN_JS, re.S).group(1)
                     .replace('"', "").replace(" ", "").replace("\n", "").split(","))
        self.assertEqual(silent & {t.lower() for t in recorded}, set())

    def test_unconsulted_page_notice(self):
        # T59: a page WebFetch returned is judged by the detector; the Anubis answer is a real one (14 Oct. 2026)
        from probandia import i18n

        with open(os.path.join(ROOT, "tests", "fixtures", "pages", "webfetch-responses.json"), encoding="utf-8") as fh:
            cases = json.load(fh)["cases"]
        self.assertEqual([c["expect"] for c in cases], ["challenge", "template", "blocked", "ok"])
        for case in cases:
            d = self.hook("log", {"tool_name": "WebFetch", "tool_input": case["tool_input"],
                                  "tool_response": case["tool_response"]})
            url = case["tool_input"]["url"]
            if case["expect"] == "ok":
                self.assertIsNone(d, case["name"])
                continue
            self.assertEqual(d["hookSpecificOutput"]["additionalContext"],
                             f"Probandia: page NOT CONSULTED ({case['expect']}): no negative from it; read {url}",
                             case["name"])
        self.addCleanup(i18n.activate, "en")
        i18n.activate("fr")
        d = self.hook("log", {"tool_name": "WebFetch", "tool_input": cases[0]["tool_input"],
                              "tool_response": cases[0]["tool_response"]})
        self.assertIn("page NON CONSULTÉE (challenge) : aucun négatif ; read https://gov.genealogy.net/",
                      d["hookSpecificOutput"]["additionalContext"])
        outside = dict(cases[0], tool_input=dict(cases[0]["tool_input"]))
        self.assertEqual(hooks.run("log", io.StringIO(json.dumps(
            {"cwd": self.tmp.name, "tool_name": "WebFetch", "tool_input": outside["tool_input"],
             "tool_response": outside["tool_response"]})), self.env, "claude-code"), "")   # outside a project

    def test_the_digest_is_given_once(self):
        # E6: the hook gives the digest, then resume in the same session gives only what changed
        self.assertIn("Probandia state digest:", self.hook("digest", {"prompt": "/probandia:resume"})[
            "hookSpecificOutput"]["additionalContext"])
        code, out = self.call("resume", RID, "--mode", "session")
        self.assertEqual((code, self.value(out, "DIGEST")), (0, "changes"), out)
        self.assertLess(len([x for x in out.splitlines() if x.startswith("- ")]), 6, out)

    def test_digest_on_resume(self):
        d = self.hook("digest", {"prompt": "/probandia:resume --instructions 'Doubs'"})
        self.assertIn("NEGATIVES_DUE:", d["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.hook("digest", {"prompt": "what time is it?"}))
        self.assertIsNone(self.hook("digest", {"prompt": "/probandia:resume"}, env={"PROBANDIA_WORKER": "1"}))

    def test_a_prefix_sets_the_run_mode_in_any_message(self):
        # FL-D6, as in the author's workshop: not only after /probandia:new or /probandia:resume
        d = self.hook("digest", {"prompt": "agents : cherche Victor HUGO"})
        self.assertIn("--mode team", d["hookSpecificOutput"]["additionalContext"])
        d = self.hook("digest", {"prompt": "Seul: que sait-on de Victor ?"})
        self.assertIn("--mode session", d["hookSpecificOutput"]["additionalContext"])
        d = self.hook("digest", {"prompt": "/probandia:resume agents : la suite"})
        text = d["hookSpecificOutput"]["additionalContext"]
        self.assertIn("--mode team", text)
        self.assertIn("NEGATIVES_DUE:", text)
        self.assertIsNone(self.hook("digest", {"prompt": "les agents : qui sont-ils ?"}))

    def test_verify_at_the_end_of_a_turn(self):
        self.assertIsNone(self.hook("verify", {}, harness="cli"))
        self.open_pass()
        d = self.hook("verify", {}, harness="cli")
        self.assertIsNone(d)  # the cli harness has no stop hook
        d = self.hook("verify", {}, env={"PROBANDIA_SESSION": "someone-else"})
        self.assertIsNone(d)  # another session's turn says nothing
        d = self.hook("verify", {})   # no web search yet (FL-D1): it speaks, with the tools of the pass
        self.assertEqual(d["systemMessage"], "Probandia: no web search and no MCP call yet in this pass; "
                                             "tools of pass 2: web 0, MCP 0, archives 0, engine 0")
        self.assertIsNone(self.hook("verify", {}, env={"PROBANDIA_WORKER": "1"}))
        self.hook("log", {"tool_name": "WebSearch", "tool_input": {"query": "Hugo Nancy"},
                          "tool_response": {"results": []}})
        self.assertIsNone(self.hook("verify", {}))   # G4: a check that passes says nothing
        doc = yamlio.load(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"))
        doc["searches"].append(dict(doc["searches"][1], id="s-01J9ZK5A000000000000000092", witness=None,
                                    **{"pass": 2}))
        yamlio.dump(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"), doc)
        self.assertTrue(self.hook("verify", {})["systemMessage"].startswith("Probandia: V-3 "))
        doc["searches"][-1]["pass"] = 1   # an earlier pass's error: pass end tells it, not every turn
        yamlio.dump(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"), doc)
        self.assertIsNone(self.hook("verify", {}))

    def test_the_tools_of_a_pass(self):
        # FL-D7: the Stop message and pass end count web searches, MCP calls, archive runs, engine searches
        self.open_pass()
        self.hook("log", {"tool_name": "WebSearch", "tool_input": {"query": "Hugo Nancy"},
                          "tool_response": {"results": []}})
        self.hook("log", {"tool_name": "mcp__tavily__tavily_search", "tool_input": {"query": "Hugo"}})
        self.hook("log", {"tool_name": "mcp__someweb__web_search", "tool_input": {"query": "Hugo"}})
        self.assertIsNone(self.hook("verify", {}))   # G4: nothing to say; pass end counts them
        code, out = self.call("pass", "end", RID, "--summary", "x")
        self.assertEqual([self.value(out, k) for k in ("STATUS", "TOOLS_WEB", "TOOLS_MCP", "TOOLS_ARCHIVE")],
                         ["OK", "1", "2", "0"])

    def test_a_pass_without_web_or_mcp_is_incomplete(self):
        self.open_pass()
        code, out = self.call("pass", "end", RID, "--summary", "x")
        self.assertEqual((code, self.value(out, "STATUS"), self.value(out, "TOOLS_WEB")), (0, "WARN", "0"))

    def test_provider_mcp_calls_reach_the_ledger(self):
        self.open_pass()
        self.hook("log", {"tool_name": "mcp__tavily__tavily_search", "tool_input": {"query": "x"}})
        self.hook("log", {"tool_name": "mcp__firecrawl__firecrawl_scrape", "tool_input": {"url": "https://x.org"}})
        with open(os.path.join(self.dir, ".probandia", "ledger.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        self.assertEqual([(r["provider"], r["operation"], r["pass"]) for r in rows],
                         [("tavily", "search", 2), ("firecrawl", "read", 2)])

    def test_mcp_calls_are_counted_at_the_cost_they_report(self):
        self.open_pass()
        two = {"content": [{"type": "text", "text": json.dumps(
            {"success": True, "data": {"markdown": "x"}, "creditsUsed": 2})}]}
        self.hook("log", {"tool_name": "mcp__claude_ai_Firecrawl__firecrawl_scrape",
                          "tool_input": {"url": "https://x.org"}, "tool_response": two})
        self.hook("log", {"tool_name": "mcp__exa__web_search_exa", "tool_input": {"query": "x"},
                          "tool_response": {"results": [], "costDollars": {"total": 0.007}}})
        self.hook("log", {"tool_name": "mcp__openwebninja__realtime_news_data", "tool_input": {"query": "x"}})
        self.hook("log", {"tool_name": "mcp__apify__rag_web_browser_scrape", "tool_input": {"query": "https://x.org"},
                          "tool_response": json.dumps({"usageTotalUsd": 0.000225})})
        self.hook("log", {"tool_name": "mcp__firecrawl__firecrawl_scrape", "tool_input": {"url": "https://y.org"},
                          "tool_response": "not JSON"})
        with open(os.path.join(self.dir, ".probandia", "ledger.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        self.assertEqual([(r["provider"], r["operation"], r["units"]) for r in rows],
                         [("firecrawl", "read", 2.0), ("exa", "search", 0.007),
                          ("openwebninja_news", "search", 1), ("apify_reader", "read", 0.000225),
                          ("firecrawl", "read", 1)])

    def test_long_mcp_pages_go_to_work(self):
        # token-economy D3: Claude Code only, an MCP reader, beyond 8,000 characters, in an open pass
        page = "# Registre des naissances\n" + "Acte de naissance de Victor Hugo, fils de Léopold.\n" * 300
        scrape = {"tool_name": "mcp__claude_ai_Firecrawl__firecrawl_scrape",
                  "tool_input": {"url": "https://example.org/registre"},
                  "tool_response": [{"type": "text", "text": page}]}
        self.assertIsNone(self.hook("log", scrape))   # no open pass
        self.open_pass()
        out = self.hook("log", scrape)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        text = out["updatedToolOutput"][0]["text"]
        self.assertTrue(text.startswith(page[:2000]))
        self.assertLess(len(text), 2400)
        path = text.split(" characters: ", 1)[1].split("; ", 1)[0]
        self.assertEqual(os.path.dirname(path), os.path.join(self.research.work, "reads"))
        self.assertTrue(os.path.basename(path).startswith("firecrawl_scrape-"))
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), page)
        # the shape the tool answered in
        d = self.hook("log", dict(scrape, tool_response={"content": [{"type": "text", "text": page}]}))
        self.assertEqual(len(d["hookSpecificOutput"]["updatedToolOutput"]["content"]), 1)
        self.assertIsInstance(self.hook("log", dict(scrape, tool_response=page))["hookSpecificOutput"][
            "updatedToolOutput"], str)
        # left as they are: a short page, a search, a browser's page, an image, another harness
        self.assertIsNone(self.hook("log", dict(scrape, tool_response=[{"type": "text", "text": page[:8000]}])))
        self.assertIsNone(self.hook("log", dict(scrape, tool_name="mcp__claude_ai_Firecrawl__firecrawl_search")))
        self.assertIsNone(self.hook("log", dict(scrape, tool_name="mcp__claude-in-chrome__read_page")))
        self.assertIsNone(self.hook("log", dict(scrape, tool_response=[{"type": "text", "text": page},
                                                                        {"type": "image", "data": "x"}])))
        self.assertIsNone(self.hook("log", scrape, harness="codex"))

    def test_mcp_web_searches_reach_the_search_log(self):
        self.open_pass()
        found = {"data": {"web": [{"url": "https://www.geneanet.org/a"}, {"url": "https://luxroots.com/b"}]}}
        self.hook("log", {"tool_name": "mcp__claude_ai_Firecrawl__firecrawl_search",
                          "tool_input": {"query": "Hugo Foucher Vianden"}, "tool_response": found})
        self.hook("log", {"tool_name": "mcp__scrapegraph__web_search", "tool_input": {"query": "Hugo Vianden"}})
        self.hook("log", {"tool_name": "mcp__claude_ai_Slack__slack_search_public", "tool_input": {"query": "x"}})
        self.hook("log", {"tool_name": "mcp__claude_ai_Firecrawl__firecrawl_scrape",
                          "tool_input": {"url": "https://eluxemburgensia.lu/search?query=Hugo"}})
        self.hook("log", {"tool_name": "mcp__probandia__search", "tool_input": {"query": "Hugo"}})
        doc = yamlio.load(os.path.join(self.dir, "families", "hugo", "index", "searches.yaml"))
        searches = [s for s in doc["searches"] if s.get("pass") == 2]
        self.assertEqual([(s["kind"], s["engine"], s["query"], s["result"], s["results"]) for s in searches],
                         [("provider", "firecrawl", "Hugo Foucher Vianden", "positive", 2)])
        # ScrapeGraph's tools all extract (T49): its search is counted, not logged as a search
        self.assertEqual(searches[0]["filters"]["tool"], "mcp__claude_ai_Firecrawl__firecrawl_search")
        logged = [e for e in events.read(self.research.events_path) if e["type"] == "search.logged"]
        self.assertEqual(len(logged), 1)
        with open(os.path.join(self.dir, ".probandia", "ledger.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        self.assertEqual([(r["provider"], r["operation"]) for r in rows],
                         [("firecrawl", "search"), ("scrapegraph", "extract"), ("firecrawl", "read")])

    def test_a_uuid_connector_is_counted_outside_a_pass(self):
        # T49: no pass open, a claude.ai connector named by a UUID is counted at its operation's cost
        self.hook("log", {"tool_name": f"mcp__{UUID_T}__tavily_map", "tool_input": {"url": "https://example.org"}})
        self.hook("log", {"tool_name": f"mcp__{UUID_F}__firecrawl_scrape", "tool_input": {"url": "https://x.org"}})
        self.hook("log", {"tool_name": f"mcp__{UUID_F}__firecrawl_check_crawl_status", "tool_input": {"id": "x"}})
        with open(os.path.join(self.dir, ".probandia", "ledger.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        self.assertEqual([(r["provider"], r["operation"], r["units"]) for r in rows],
                         [("tavily", "map", 0.1), ("firecrawl", "read", 1)])


UUID_T, UUID_F = "86864585-3f1e-4c2a-9b7d-5e0a1c2b3d4f", "485c4522-7a9b-4c3d-8e1f-2a3b4c5d6e7f"


class EngineFirst(Base):
    """T54, G-15: during a pass, an MCP tool of a provider goes to the engine's command that does the same."""

    def reason(self, tool, tool_input, harness="claude-code"):
        d = self.hook("guard", {"tool_name": tool, "tool_input": tool_input}, harness=harness)
        return (d or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason")

    def test_provider_tools_are_sent_to_the_engine_during_a_pass(self):
        query = {"query": "Victor Hugo Besançon 1802"}
        self.assertIsNone(self.reason("mcp__tavily__tavily_search", query))   # no pass open: allowed
        self.hook("log", {"tool_name": "mcp__tavily__tavily_search", "tool_input": query})
        with open(os.path.join(self.dir, ".probandia", "ledger.jsonl"), encoding="utf-8") as fh:
            self.assertEqual([json.loads(x)["provider"] for x in fh], ["tavily"])   # and counted (T49)
        self.open_pass()
        for tool in ("mcp__tavily__tavily_search", f"mcp__{UUID_T}__tavily_search"):
            reason = self.reason(tool, query)
            self.assertTrue(reason.startswith("G-15: "), tool)
            self.assertTrue(reason.endswith(': search "Victor Hugo Besançon 1802" --engine tavily'), reason)
        page = "https://www.example.org/registres/1802"
        self.assertTrue(self.reason("mcp__firecrawl__firecrawl_scrape", {"url": page}).endswith(f": read {page}"))
        self.assertTrue(self.reason(f"mcp__{UUID_F}__firecrawl_map", {"url": page}).endswith(f": read {page} --map"))
        self.assertTrue(self.reason("mcp__tavily__tavily_crawl", {"url": page, "limit": 50, "instructions": "baptêmes"})
                        .endswith(f': read {page} --crawl 20 --question "baptêmes"'))   # read.crawl_max_pages
        self.assertTrue(self.reason("mcp__scrapegraph__smartscraper", {"website_url": page, "user_prompt": "the acts"})
                        .endswith(f': read {page} --extract "the acts"'))
        self.assertTrue(self.reason("mcp__jina__read_url", {"url": page, "query": "Hugo"})
                        .endswith(f': read {page} --question "Hugo"'))
        self.assertTrue(self.reason("mcp__brightdata__scrape_as_markdown", {"url": page})   # a web service by name
                        .endswith(f": read {page}"))
        d = self.hook("guard", {"tool_name": "mcp__tavily__tavily_search", "tool_input": query}, harness="cursor")
        self.assertEqual(d["permission"], "deny")
        # Claude in Chrome, Probandia's server, a server off the web, a status check: allowed
        for tool, tool_input in (("mcp__claude-in-chrome__navigate", {"url": page}),
                                 ("mcp__claude-in-chrome__get_page_text", {"tabId": 1}),
                                 ("mcp__probandia__search", query), ("mcp__plugin_probandia_probandia__known", {}),
                                 ("mcp__claude_ai_Slack__slack_search_public", query), ("mcp__hexagon__lookup", query),
                                 ("mcp__firecrawl__firecrawl_check_crawl_status", {"id": "x"})):
            self.assertIsNone(self.reason(tool, tool_input), tool)
        self.call("pass", "end", RID, "--summary", "x")
        self.assertIsNone(self.reason(f"mcp__{UUID_F}__firecrawl_scrape", {"url": page}))   # the pass closed


class McpAttribution(unittest.TestCase):
    """T49: each MCP tool to its provider and its operation, whatever its server is named."""

    TABLE = (
        (f"mcp__{UUID_T}__tavily_search", ("tavily", "search")),
        (f"mcp__{UUID_F}__firecrawl_scrape", ("firecrawl", "read")),
        ("mcp__plugin_exa_exa__web_search_exa", ("exa", "search")),
        ("mcp__claude_ai_Exa__web_search_exa", ("exa", "search")),
        ("mcp__hexagon__lookup", (None, None)),
        ("mcp__firecrawl__firecrawl_map", ("firecrawl", "map")),
        ("mcp__tavily__tavily_crawl", ("tavily", "crawl")),
        ("mcp__claude_ai_Firecrawl__firecrawl_extract", ("firecrawl", "extract")),
        ("mcp__tavily__tavily_extract", ("tavily", "read")),
        ("mcp__tavily__tavily-search", ("tavily", "search")),
        ("mcp__claude_ai_Tavily__tavily_map", ("tavily", "map")),
        ("mcp__firecrawl__firecrawl_search", ("firecrawl", "search")),
        ("mcp__firecrawl__firecrawl_crawl", ("firecrawl", "crawl")),
        ("mcp__scrapegraph__smartscraper", ("scrapegraph", "extract")),
        ("mcp__scrapegraph__web_search", ("scrapegraph", "extract")),
        ("mcp__scrapegraph-mcp__crawl_start", ("scrapegraph", "extract")),
        ("mcp__brightdata__search_engine", (None, "search")),
        ("mcp__brightdata__scrape_as_markdown", (None, "read")),
        ("mcp__jina__read_url", ("jina", "read")),
        ("mcp__jina__search_web", ("jina", "search")),
        ("mcp__exa__web_fetch_exa", ("exa", "read")),
        ("mcp__plugin_parallel_parallel-search__web_search", ("parallel", "search")),
        ("mcp__plugin_parallel_parallel-search__web_fetch", ("parallel", "read")),
        ("mcp__openwebninja__realtime_news_data", ("openwebninja_news", "search")),
        ("mcp__apify__rag_web_browser_scrape", ("apify_reader", "read")),
        ("mcp__firecrawl__firecrawl_check_crawl_status", ("firecrawl", None)),   # a status costs nothing
        ("mcp__claude_ai_Slack__slack_search_public", (None, "search")),
    )

    def test_each_tool_to_its_provider_and_operation(self):
        from probandia.providers import catalogue

        for tool, expected in self.TABLE:
            self.assertEqual(catalogue.mcp_tool(tool), expected, tool)
        listed = {op for e in catalogue.load().values() for op in (e.get("mcp_tools") or {}).values()}
        self.assertLessEqual(listed, set(catalogue.MCP_OPERATIONS))
        for pid, e in catalogue.load().items():   # each listed operation is priced, or its answer gives its cost
            for t, op in (e.get("mcp_tools") or {}).items():
                self.assertTrue(op in (e.get("costs") or {}) or (e.get("introspection") or {}).get("method")
                                == "response", (pid, t))
