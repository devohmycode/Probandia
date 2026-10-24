"""Times of the terminal application, without a screen, on a copy of ``tests/sample-project``.

    python tools/tui_timing.py               # medians of 5 runs
    python tools/tui_timing.py --runs 9 --idle 0 --json

Each run starts a new application (``App.run_test``, 140 x 45, its own configuration and data
folders, no harness variable), then measures, in milliseconds, from a key sent as the terminal
sends it (the pilot's own waits for an idle process are not counted: they would wait for the
reads of other threads too):

- ``pause``: one idle turn of the pilot, for reference;
- ``start``: until the home screen shows its data;
- ``shown <screen>``: its key, until the application has handled the switch: the screen is drawn
  next, with its data or with the indicator of a read under way;
- ``first <screen>``: the same key, until the screen shows its data (its first read);
- ``back <screen>``: its key again once every screen was seen, nothing changed meanwhile;
  ``back reads`` counts the engine commands these returns ran;
- ``filter``: four letters typed at once in the filter of Quotas, until the table shows them;
  ``filter reads`` counts the engine commands they ran;
- ``refresh``: ``r`` on Quotas, the cursor on its fourth line; ``cursor after`` says where the
  cursor is then (3 when the place is kept);
- ``tick``: an event added to the log of the research, then the look at the watched files, until
  Researches shows it;
- ``idle cpu``: the share of one processor the application takes at rest, in %, over ``--idle``
  seconds (10 by default; 0 leaves it out).

The handlers it times exist in every version of the application since CLI15, so that the same
tool measures before and after a change.

The machine and its load come first: other programs slow every figure down, hence the medians.
Measures only (version-1.0.0 T88, T90): exits 0, or 2 when Textual is not installed.
"""
import argparse
import asyncio
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "tests", "sample-project")
RID = "2026-09-01-ancestors-of-louis-marchand"
SIZE = (140, 45)
SCREENS = ("quotas", "researches", "family", "proposals", "config")   # by their keys, 2 to 6
HARNESS_PREFIXES = ("PROBANDIA_", "CLAUDE", "CODEX_", "CURSOR_", "FACTORY_", "DROID_", "GROK_",
                    "ANTIGRAVITY_", "OPENCODE")

if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))


def machine():
    """The processor, the system, the versions and the load, as one line."""
    cpu = platform.processor() or platform.machine()
    if sys.platform == "win32":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_Processor).Name; (Get-CimInstance Win32_Processor).LoadPercentage"],
                                 capture_output=True, text=True, timeout=20).stdout.split("\n")
            cpu, load = out[0].strip() or cpu, f"processor load {out[1].strip()} %"
        except (OSError, subprocess.SubprocessError, IndexError):
            load = "load unknown"
    else:
        try:
            load = "load average " + " ".join(f"{x:.2f}" for x in os.getloadavg())
        except (AttributeError, OSError):
            load = "load unknown"
    try:
        import textual

        version = textual.__version__
    except (ImportError, AttributeError):
        version = "?"
    return (f"{cpu}, {os.cpu_count()} logical processors, {platform.system()} {platform.release()}, "
            f"Python {platform.python_version()}, Textual {version}; {load}")


def environment(tmp):
    """The current environment without any Probandia or harness variable, with folders of its own."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(HARNESS_PREFIXES)}
    env.update(PROBANDIA_CONFIG_DIR=os.path.join(tmp, "config"), PROBANDIA_DATA_DIR=os.path.join(tmp, "data"),
               PROBANDIA_PAGER="none")
    return env


def make(project, env):
    """The application of ``probandia tui`` in ``project``."""
    from probandia import cli
    from probandia.cli.tui_app import make_app

    args = cli.build_parser().parse_args(["tui"])
    for k, v in cli.GLOBAL_DEFAULTS.items():
        if not hasattr(args, k):
            setattr(args, k, v)
    return make_app(cli.Context(args, env, project))


class Reads:
    """Counts the engine commands run, from any thread."""

    def __init__(self):
        from probandia.cli import commands

        self.count, self.lock, self.commands = 0, threading.Lock(), commands
        self.original = commands.Command.run
        reads = self

        def counted(spec, ctx):
            with reads.lock:
                reads.count += 1
            return reads.original(spec, ctx)
        commands.Command.run = counted

    def close(self):
        self.commands.Command.run = self.original


def busy(app):
    """A read under way, or read and not shown yet (an application that reads in its own
    thread is never busy between two of its handlers)."""
    from textual.worker import WorkerState

    if any(w.state in (WorkerState.PENDING, WorkerState.RUNNING) for w in app.workers):
        return True
    return any(getattr(state, "busy", False) for pane in app.screen.query("Pane")
               for state in getattr(pane, "reads", {}).values())


def active(app):
    from textual.widgets import TabbedContent

    return app.screen.query_one("#screens", TabbedContent).active


def owner(cls, name):
    """The class of ``cls``'s MRO that defines ``name``: Textual calls the handler of each one."""
    return next(c for c in cls.__mro__ if name in c.__dict__)


class Handled:
    """The times the application finished handling a screen switch, a letter of the filter
    of Quotas and ``r``: the same handlers whether it reads in its own thread or in others."""

    def __init__(self):
        from probandia.cli import tui_app

        self.times = {"switch": [], "filter": [], "refresh": []}
        self.patched = [(tui_app.Main, "on_tabbed_content_tab_activated", "switch"),
                        (owner(tui_app.QuotasPane, "on_input_changed"), "on_input_changed", "filter"),
                        (tui_app.ProbandiaApp, "action_refresh", "refresh")]
        self.originals = [getattr(cls, name) for cls, name, _k in self.patched]
        for (cls, name, kind), original in zip(self.patched, self.originals):
            setattr(cls, name, self.timed(original, self.times[kind]))

    @staticmethod
    def timed(original, times):
        def handler(*args, **kwargs):
            out = original(*args, **kwargs)
            times.append(time.perf_counter())
            return out
        return handler

    def count(self, kind):
        return len(self.times[kind])

    def close(self):
        for (cls, name, _k), original in zip(self.patched, self.originals):
            setattr(cls, name, original)


async def send(app, *keys, typed=False):
    """Keys as the terminal sends them, outside any field unless ``typed``, without the
    pilot's waits for an idle process (they would count the reads of other threads)."""
    from textual import events

    if not typed:
        app.set_focus(None)
    for key in keys:
        char = {"slash": "/"}.get(key, key if len(key) == 1 else None)
        app._driver.send_message(events.Key(key, char))
        await asyncio.sleep(0)


async def until(condition, limit=60.0):
    end = time.perf_counter() + limit
    while not condition():
        if time.perf_counter() > end:
            raise TimeoutError("the application did not settle")
        await asyncio.sleep(0.002)


def key_of(name):
    from probandia.cli.tui_app import SCREENS as ALL

    return str([n for n, _t in ALL].index(name) + 1)


async def switch(app, hooks, name, out, first):
    """The key of screen ``name``: until the switch is handled (shown), then until its data
    is there (first, or back)."""
    n, t0 = hooks.count("switch"), time.perf_counter()
    await send(app, key_of(name))
    await until(lambda: hooks.count("switch") > n and active(app) == name)
    if first:
        out[f"shown {name}"] = (hooks.times["switch"][-1] - t0) * 1000
    await until(lambda: not busy(app))
    out[f"{'first' if first else 'back'} {name}"] = (time.perf_counter() - t0) * 1000


async def one_run(project, env, idle):
    """The figures of one application, in ms (idle cpu in %)."""
    from textual.widgets import DataTable

    out = {}
    hooks = Handled()
    try:
        app = make(project, env)
        t0 = time.perf_counter()
        async with app.run_test(size=SIZE) as pilot:
            await until(lambda: hooks.count("switch") and not busy(app))
            out["start"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            await pilot.pause()
            out["pause"] = (time.perf_counter() - t0) * 1000
            for name in SCREENS:
                await switch(app, hooks, name, out, True)
            await switch(app, hooks, "home", {}, False)
            reads = Reads()
            try:
                for name in SCREENS:
                    await switch(app, hooks, name, out, False)
                out["back reads"] = reads.count
            finally:
                reads.close()
            # the filter of Quotas: four letters typed at once
            await switch(app, hooks, "quotas", {}, False)
            await send(app, "slash")
            await until(lambda: app.focused is not None and app.focused.id == "filter")
            reads, n = Reads(), hooks.count("filter")
            try:
                t0 = time.perf_counter()
                await send(app, *"serp", typed=True)
                await until(lambda: hooks.count("filter") >= n + 4 and not busy(app))
                out["filter"] = (time.perf_counter() - t0) * 1000
                out["filter reads"] = reads.count
            finally:
                reads.close()
            app.pane("quotas").query_one("#filter").value = ""
            await until(lambda: hooks.count("filter") >= n + 5 and not busy(app))
            # r on Quotas, the cursor on the fourth line
            table = app.screen.query_one("#quotas-accounts", DataTable)
            table.move_cursor(row=3)
            await pilot.pause()
            n, t0 = hooks.count("refresh"), time.perf_counter()
            await send(app, "r")
            await until(lambda: hooks.count("refresh") > n and not busy(app))
            out["refresh"] = (time.perf_counter() - t0) * 1000
            out["cursor after"] = table.cursor_row
            # an event in the log of the research, then the look at the watched files
            from probandia import events

            await switch(app, hooks, "researches", {}, False)
            log = app.screen.query_one("#research-log", DataTable)
            rows = log.row_count
            path = os.path.join(project, "families", "marchand", "research", RID, "events.jsonl")
            events.append(path, [events.make("instruction.added", {"text": "look at the census first"},
                                             {"harness": "cli", "agent": "session"}, 2)])
            t0 = time.perf_counter()
            app.tick()
            await until(lambda: not busy(app) and log.row_count > rows)
            out["tick"] = (time.perf_counter() - t0) * 1000
            if idle:
                await switch(app, hooks, "home", {}, False)
                await asyncio.sleep(1.5)
                c0, w0 = time.process_time(), time.perf_counter()
                await asyncio.sleep(idle)
                out["idle cpu"] = 100 * (time.process_time() - c0) / (time.perf_counter() - w0)
    finally:
        hooks.close()
    return out


def run(runs, idle):
    results = []
    for _n in range(runs):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "sample")
            shutil.copytree(SAMPLE, project)
            results.append(asyncio.run(one_run(project, environment(tmp), idle)))
    keys = list(dict.fromkeys(k for r in results for k in r))
    return {k: statistics.median([r[k] for r in results if k in r]) for k in keys}, results


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--runs", type=int, default=5, help="runs, each in a new application (default 5)")
    p.add_argument("--idle", type=float, default=10.0, help="seconds at rest for the idle cpu (0: none)")
    p.add_argument("--json", action="store_true", help="one JSON object: the machine, the medians, every run")
    args = p.parse_args(argv)
    try:
        import textual  # noqa: F401
    except ImportError:
        print("tui_timing: Textual is not installed: python -m pip install --editable \".[tui]\"", file=sys.stderr)
        return 2
    where = machine()
    medians, results = run(max(1, args.runs), args.idle)
    if args.json:
        print(json.dumps({"machine": where, "runs": args.runs, "medians": medians, "results": results}, indent=1))
        return 0
    print(where)
    print(f"medians of {args.runs} runs, in ms (idle cpu in %, reads and cursor as counted)")
    for k, v in medians.items():
        print(f"  {k:<22} {v:>8.1f}" if isinstance(v, float) else f"  {k:<22} {v:>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
