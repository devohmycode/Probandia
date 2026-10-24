"""tools/startup_time.py: the medians, the job summary, and one real launch of each measure."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

from tests import ROOT


def load_tool():
    spec = importlib.util.spec_from_file_location("startup_time", os.path.join(ROOT, "tools", "startup_time.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


st = load_tool()
RESULTS = [("run_probandia.py --version", [0.5, 0.45, 0.61]), ("run_probandia.py hook guard", [0.55, 0.6, 0.58])]


class Reports(unittest.TestCase):
    def test_terminal(self):
        text = st.report(RESULTS, 3)
        self.assertIn("median of 3 launches", text)
        self.assertIn("run_probandia.py --version    500 ms   (min 450 ms, max 610 ms)", text)
        self.assertIn("run_probandia.py hook guard   580 ms", text)

    def test_job_summary(self):
        text = st.summary(RESULTS, 3)
        self.assertIn("| `run_probandia.py --version` | 500 ms | 450 ms | 610 ms |", text)
        self.assertIn("| `run_probandia.py hook guard` | 580 ms | 550 ms | 600 ms |", text)

    def test_the_guard_reads_a_pre_tool_use_call_in_the_copy(self):
        payload = st.pre_tool_use("/tmp/sample")
        self.assertEqual((payload["hook_event_name"], payload["cwd"], payload["tool_name"]),
                         ("PreToolUse", "/tmp/sample", "Bash"))
        label, command, stdin = st.measures("/tmp/sample")[2]
        self.assertEqual(command[-2:], ["hook", "guard"])
        self.assertEqual(json.loads(stdin), payload)

    def test_the_user_settings_stay_out(self):
        env = st.clean_environment("/t", "/t/sample", {"PROBANDIA_LANGUAGE": "fr", "CODEX_THREAD_ID": "x",
                                                       "PATH": "/bin"})
        self.assertNotIn("PROBANDIA_LANGUAGE", env)
        self.assertNotIn("CODEX_THREAD_ID", env)
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual((env["CLAUDECODE"], env["CLAUDE_PROJECT_DIR"]), ("1", "/t/sample"))
        self.assertEqual(env["PROBANDIA_CONFIG_DIR"], os.path.join("/t", "config"))


class OneLaunch(unittest.TestCase):
    def test_measures_and_writes_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "summary.md")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = st.main(["--runs", "1"], environ={"GITHUB_STEP_SUMMARY": target})
            self.assertEqual(code, 0, out.getvalue())
            self.assertIn("run_probandia.py hook guard", out.getvalue())
            with open(target, encoding="utf-8") as fh:
                self.assertIn("### Startup time, median of 1 launches", fh.read())

    def test_no_summary_outside_a_ci_job(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(st.main(["--runs", "1"], environ={}), 0)


if __name__ == "__main__":
    unittest.main()
