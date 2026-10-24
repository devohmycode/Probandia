"""tools/hook_cost.py: the payloads drawn from a made-up stream, and their replay through the real hooks."""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

from tests import ROOT


def load_tool():
    spec = importlib.util.spec_from_file_location("hook_cost", os.path.join(ROOT, "tools", "hook_cost.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hc = load_tool()
PLAYED = "C:\\runs\\hugo\\projet"          # the folder the made-up session ran in
PLUGIN = "C:\\runs\\depots\\probandia"


def call(tool_id, name, data, parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"id": "m-" + tool_id, "content": [{"type": "tool_use", "id": tool_id, "name": name,
                                                            "input": data}]}}


def answer(tool_id, text, parent=None):
    return {"type": "user", "parent_tool_use_id": parent, "tool_use_result": {"text": text},
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}


STREAM = [
    {"type": "system", "subtype": "init", "cwd": PLAYED, "plugins": [{"name": "probandia", "path": PLUGIN}]},
    {"type": "system", "subtype": "hook_started", "hook_event": "SessionStart"},
    call("t1", "Bash", {"command": "python C:/runs/depots/probandia/run_probandia.py status"}),
    answer("t1", "STATUS=OK"),
    call("t2", "WebSearch", {"query": "Victor Hugo 1802 Besançon"}),
    answer("t2", "Links: []"),
    call("t3", "Agent", {"subagent_type": "probandia:reader", "description": "Read the act", "prompt": "Read it."}),
    call("t4", "Read", {"file_path": "C:/runs/hugo/projet/families/hugo/views/p1.jpg"}, parent="t3"),
    answer("t4", "an image", parent="t3"),
    answer("t3", "Birth act read."),
    call("t5", "Write", {"file_path": PLAYED + "\\work\\notes.md", "content": "Victor, born 1802."}),
    answer("t5", "written"),
]


class HookCost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stream = os.path.join(self.tmp.name, "session.jsonl")
        with open(self.stream, "w", encoding="utf-8") as fh:
            for row in STREAM:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.project = os.path.join(self.tmp.name, "sample")
        shutil.copytree(hc.SAMPLE, self.project)

    def test_payloads_follow_the_matchers_of_hooks_json(self):
        runs = hc.payloads(self.stream, self.project)
        self.assertEqual([(event, argv[2:], p["tool_name"]) for event, argv, p in runs], [
            ("PreToolUse", ["hook", "guard"], "Bash"),
            ("PreToolUse", ["hook", "guard"], "WebSearch"), ("PostToolUse", ["hook", "log"], "WebSearch"),
            ("PreToolUse", ["hook", "guard"], "Agent"), ("PostToolUse", ["hook", "log"], "Agent"),
            ("PreToolUse", ["hook", "guard"], "Read"),
            ("PreToolUse", ["hook", "guard"], "Write")])
        first, read, write = runs[0][2], runs[5][2], runs[6][2]
        self.assertEqual((first["cwd"], first["hook_event_name"]), (self.project, "PreToolUse"))
        self.assertEqual(first["tool_input"]["command"], f"python {hc.ROOT}/run_probandia.py status")
        self.assertEqual((read["agent_type"], read["agent_id"]), ("probandia:reader", "t3"))
        self.assertTrue(read["tool_input"]["file_path"].startswith(self.project))
        self.assertTrue(write["tool_input"]["file_path"].startswith(self.project))
        self.assertEqual(runs[2][2]["tool_response"], {"text": "Links: []"})
        self.assertNotIn("agent_type", first)

    def test_the_guard_accepts_every_payload(self):
        env = hc.clean_environment(self.tmp.name, self.project)
        results = hc.replay(hc.payloads(self.stream, self.project), self.project, env)
        self.assertEqual([(event, label, code) for event, label, _, code, _ in results if label == "hook guard"],
                         [("PreToolUse", "hook guard", 0)] * 5)
        self.assertEqual({code for _, _, _, code, _ in results}, {0})
        report = hc.summary(results)
        self.assertEqual([(g["event"], g["command"], g["runs"], g["failed"]) for g in report["events"]],
                         [("PreToolUse", "hook guard", 5, 0), ("PostToolUse", "hook log", 2, 0)])
        self.assertEqual(report["runs"], 7)
        self.assertGreater(report["total_ms"], 0)

    def test_the_table(self):
        report = {"system": "Linux", "python": "3.12.3", "runs": 3, "total_ms": 1500,
                  "events": [{"event": "PreToolUse", "command": "hook guard", "runs": 2, "median_ms": 600,
                              "total_ms": 1200, "refused": 0, "failed": 0, "answered": 0},
                             {"event": "PostToolUse", "command": "hook log", "runs": 1, "median_ms": 300,
                              "total_ms": 300, "refused": 0, "failed": 0, "answered": 0}]}
        out = io.StringIO()
        hc.render(report, out)
        self.assertIn("| PreToolUse | `hook guard` | 2 | 600 ms | 1200 ms | 0 | 0 |", out.getvalue())
        self.assertIn("| **pass** | | 3 | | 1500 ms | | |", out.getvalue())

    def test_matchers(self):
        self.assertTrue(hc.matches("*", "Bash"))
        self.assertTrue(hc.matches("WebSearch|Agent|mcp__.*", "mcp__tavily__tavily_search"))
        self.assertFalse(hc.matches("WebSearch|Agent|mcp__.*", "Read"))
