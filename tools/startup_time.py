"""Startup time of the engine and of the guard, in a copy of ``tests/sample-project``.

    python tools/startup_time.py [--runs 9]

Launches ``run_probandia.py --version`` and ``run_probandia.py hook guard`` (a
simulated PreToolUse call of Claude Code, the hook every tool call goes through)
nine times each, and prints their medians, with ``python -c pass`` for reference.
When ``$GITHUB_STEP_SUMMARY`` is set (a CI job), the same table goes to the job
summary. The launches never see the user's settings: their own configuration and
data folders, no Probandia or harness variable.

It measures only, so that no regression goes unnoticed (version-1.0.0 T28): exits 0,
or 1 when a launch fails. The threshold that blocks comes with the fix of the
startup itself.
"""
import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "tests", "sample-project")
LAUNCHER = os.path.join(ROOT, "run_probandia.py")
HARNESS_PREFIXES = ("PROBANDIA_", "CLAUDE", "CODEX_", "CURSOR_", "FACTORY_", "DROID_", "GROK_",
                    "ANTIGRAVITY_", "OPENCODE")


def clean_environment(tmp, project, environ=None):
    """The current environment without any Probandia or harness variable, plus what Claude Code
    gives a hook: the harness is Claude Code, the project is the copy."""
    environ = os.environ if environ is None else environ
    env = {k: v for k, v in environ.items() if not k.upper().startswith(HARNESS_PREFIXES)}
    env.update(PROBANDIA_CONFIG_DIR=os.path.join(tmp, "config"), PROBANDIA_DATA_DIR=os.path.join(tmp, "data"),
               PYTHONIOENCODING="utf-8", CLAUDECODE="1", CLAUDE_PROJECT_DIR=project, CLAUDE_PLUGIN_ROOT=ROOT)
    return env


def pre_tool_use(project):
    """What Claude Code sends the guard before an ordinary call of the engine."""
    return {"session_id": "startup-time", "transcript_path": "", "cwd": project, "permission_mode": "default",
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python .probandia/pb.py status", "description": "Show the research"}}


def measures(project):
    """(label, command, stdin) of each measure."""
    payload = json.dumps(pre_tool_use(project))
    return [("python -c pass", [sys.executable, "-c", "pass"], None),
            ("run_probandia.py --version", [sys.executable, LAUNCHER, "--version"], None),
            ("run_probandia.py hook guard", [sys.executable, LAUNCHER, "hook", "guard"], payload)]


def time_launches(command, stdin, runs, cwd, env):
    """The wall time of each launch, in seconds; raises RuntimeError when one fails."""
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        r = subprocess.run(command, input=stdin, capture_output=True, text=True, encoding="utf-8",
                           cwd=cwd, env=env)
        times.append(time.perf_counter() - start)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(command[1:])} exited with {r.returncode}: {(r.stderr or r.stdout)[-500:]}")
    return times


def ms(seconds):
    return f"{seconds * 1000:.0f} ms"


def report(results, runs):
    """The lines printed at the terminal."""
    head = f"startup time, median of {runs} launches (Python {platform.python_version()}, {platform.system()})"
    width = max(len(label) for label, _ in results)
    lines = [head]
    for label, times in results:
        lines.append(f"  {label.ljust(width)}  {ms(statistics.median(times)):>7}"
                     f"   (min {ms(min(times))}, max {ms(max(times))})")
    return "\n".join(lines) + "\n"


def summary(results, runs):
    """The same, as Markdown for the job summary."""
    lines = [f"### Startup time, median of {runs} launches", "",
             f"Python {platform.python_version()} on {platform.system()}, in a copy of `tests/sample-project`; "
             "`hook guard` reads a simulated PreToolUse call of Claude Code.", "",
             "| Command | Median | Min | Max |", "|---|---:|---:|---:|"]
    for label, times in results:
        lines.append(f"| `{label}` | {ms(statistics.median(times))} | {ms(min(times))} | {ms(max(times))} |")
    return "\n".join(lines) + "\n\n"


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=9, help="launches of each command (default 9)")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="probandia-startup-") as tmp:
        project = os.path.join(tmp, "sample")
        shutil.copytree(SAMPLE, project)
        env = clean_environment(tmp, project)
        results = []
        try:
            for label, command, stdin in measures(project):
                results.append((label, time_launches(command, stdin, args.runs, project, env)))
        except RuntimeError as err:
            print(f"FAIL  {err}")
            return 1
    sys.stdout.write(report(results, args.runs))
    target = environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(summary(results, args.runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
