"""Replays the last pass of the sample project, line by line, for a manual check of the TUI (version-1.0.0 T110).

    python tools/replay_pass.py <folder> [--delay 2]

Copies ``tests/sample-project`` into ``<folder>`` (which must not exist), cuts its research's ``events.jsonl``
before the last ``pass.started``, then writes the cut lines back one by one, ``--delay`` seconds apart. Open
the TUI on ``<folder>`` meanwhile (``python run_probandia.py tui``, from that folder): the home screen and the
journal follow the pass as it happens. No session is run and nothing is paid. At the end the log is the
sample's own again, byte for byte.
"""
import argparse
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "tests", "sample-project")
LOG = os.path.join("families", "marchand", "research", "2026-09-01-ancestors-of-louis-marchand", "events.jsonl")


def replay(folder, delay, out=sys.stdout):
    shutil.copytree(SAMPLE, folder)
    path = os.path.join(folder, LOG)
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.readlines()
    start = max(i for i, line in enumerate(lines) if '"pass.started"' in line)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.writelines(lines[:start])
    print(f"{folder}: {start} events kept, {len(lines) - start} to replay", file=out, flush=True)
    for n, line in enumerate(lines[start:], 1):
        time.sleep(delay)
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write(line)
        print(f"  {n}/{len(lines) - start}", file=out, flush=True)
    return len(lines) - start


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="where to copy the sample project (must not exist)")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between two events (default 2)")
    args = ap.parse_args(argv)
    if os.path.exists(args.folder):
        ap.error(f"{args.folder} exists: give a new folder")
    replay(args.folder, args.delay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
