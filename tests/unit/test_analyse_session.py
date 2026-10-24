import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

from tests import ROOT


def load_tool():
    spec = importlib.util.spec_from_file_location("analyse_session", os.path.join(ROOT, "tools", "analyse_session.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assistant(mid, context, output, tools=()):
    return {"type": "assistant", "timestamp": f"2026-10-06T09:{mid:02d}:00Z",
            "message": {"id": f"m{mid}", "model": "claude-opus-5-5",
                        "usage": {"input_tokens": 0, "cache_read_input_tokens": context,
                                  "cache_creation_input_tokens": 0, "output_tokens": output},
                        "content": [{"type": "tool_use", "id": f"t{mid}-{i}", "name": n, "input": d}
                                    for i, (n, d) in enumerate(tools)]}}


def result(tool_id, text, images=0):
    content = [{"type": "text", "text": text}] + [{"type": "image", "source": {}}] * images
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id,
                                                      "content": content}]}}


def prompt(text):
    return {"type": "user", "timestamp": "2026-10-06T09:00:00Z", "message": {"content": text}}


class AnalyseSession(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.join(self.tmp.name, "project")
        rows = [
            prompt("<command-name>/probandia:new</command-name> <command-args>Victor HUGO</command-args>"),
            assistant(1, 80000, 100, [("Bash", {"command": "python .probandia/pb.py propose R p.yaml"})]),
            result("t1-0", "STATUS=FAIL"),
            assistant(2, 81000, 100, [("Bash", {"command": "python .probandia/pb.py propose R p.yaml"}),
                                      ("Read", {"file_path": os.path.join(self.tmp.name, "plugin", "schema.json")})]),
            result("t2-0", "STATUS=OK"),
            result("t2-1", "x" * 5000),
            prompt("<command-name>/probandia:resume</command-name>"),
            assistant(3, 90000, 50, [("mcp__claude-in-chrome__computer", {"action": "screenshot"})]),
            result("t3-0", "shot", images=1),
            assistant(4, 95000, 70),
        ]
        self.path = os.path.join(self.tmp.name, "s.jsonl")
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_phases_tokens_tools_and_retries(self):
        report = self.tool.analyse(self.path, project=self.project)
        self.assertEqual([(p["prompt"].split()[0], p["calls"], p["input"], p["first_context"], p["max_context"])
                          for p in report["phases"]],
                         [("/probandia:new", 2, 161000, 80000, 81000), ("/probandia:resume", 2, 185000, 90000, 95000)])
        self.assertEqual(report["total"]["output"], 320)
        self.assertEqual((report["engine"], report["retried"], report["images"]), ({"propose": 2}, {"propose": 1}, 1))
        self.assertEqual(report["largest_results"][0]["chars"], 5000)
        self.assertEqual(list(report["outside_project"]), [os.path.join(self.tmp.name, "plugin", "schema.json")])
        self.assertEqual(report["largest_rises"][0]["tokens"], 9000)

    def test_since_and_the_readable_report(self):
        report = self.tool.analyse(self.path, since="/probandia:resume")
        self.assertEqual(len(report["phases"]), 1)
        out = io.StringIO()
        self.tool.render(report, out)
        self.assertIn("| /probandia:resume | 2 | 185 000 |", out.getvalue())

    def test_a_message_on_several_lines_counts_its_last_output(self):
        rows = [prompt("go"), assistant(1, 1000, 4), assistant(1, 1000, 150), assistant(2, 1200, 10)]
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        report = self.tool.analyse(self.path)
        self.assertEqual((report["total"]["calls"], report["total"]["output"]), (2, 160))

    def test_engine_command_names(self):
        self.assertEqual(self.tool.engine_command('python .probandia/pb.py -l fr archive run ad92.view'), "archive run")
        self.assertEqual(self.tool.engine_command('python "C:/x/run_probandia.py" new "Q" --mode session'), "new")
        self.assertIsNone(self.tool.engine_command("git status"))


class ByAgent(unittest.TestCase):
    """A made-up session: the main agent on Opus calls two readers on Sonnet."""

    SESSION = os.path.join(ROOT, "tests", "fixtures", "transcripts", "by-agent", "session.jsonl")

    def setUp(self):
        self.tool = load_tool()

    def test_one_line_per_agent_and_each_column(self):
        main, readers = self.tool.by_agent(self.SESSION)
        self.assertEqual(main, {
            "agent": "main", "count": 1, "returned_chars": None, "calls": 3,
            "first_context": [20000], "max_context": [22000], "images": 0, "image_tokens": 0,
            # "I ask a reader." + two Agent calls (name and input) + the answer
            "visible_chars": 340, "output": 290, "thinking": 40, "models": ["claude-opus-5-5"]})
        self.assertEqual(readers, {
            "agent": "probandia:reader", "count": 2,
            # "Birth act found: Besançon, 26 February 1802." (44) and "No baptism found." (17)
            "returned_chars": 61, "calls": 5, "first_context": [8000, 9000], "max_context": [10100, 10000],
            # a PNG of 1500 × 1000 (2000 tokens) and two JPEG of 750 × 300 (300 each)
            "images": 3, "image_tokens": 2600,
            # three Read calls of 33 characters, "Found." and "Not found."; the thinking is not shown
            "visible_chars": 115, "output": 540, "thinking": 250, "models": ["claude-sonnet-5-5"]})

    def test_the_command_line_table_and_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.tool.main([self.SESSION, "--by-agent"]), 0)
        table = out.getvalue()
        self.assertIn("| main | 3 | 20 000 | 22 000 | 0 (0) | – | 340 | 290 (40) | 1.2 |", table)
        self.assertIn("| probandia:reader ×2 | 5 | 8 000–9 000 | 10 000–10 100 | 3 (2 600) | 61 | 115 | 540 (250) | 0.2 |",
                      table)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.tool.main([self.SESSION, "--by-agent", "--json"])
        self.assertEqual([(r["agent"], r["count"]) for r in json.loads(out.getvalue())],
                         [("main", 1), ("probandia:reader", 2)])

    def test_image_sizes(self):
        self.assertIsNone(self.tool.image_size("bm90IGFuIGltYWdl"))
        self.assertEqual(self.tool.image_tokens({"source": {"data": ""}}), 0)
