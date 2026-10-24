"""Runs the test suite in several processes: ``python -m unittest discover -s tests``, shared out.

    python tools/run_tests.py                  # every test module, one process per core (at most 8)
    python tools/run_tests.py -v               # the verbose output of each process, one after the other
    python tools/run_tests.py -j 1             # one process, the modules in the order of discover
    python tools/run_tests.py --measure        # one process per module; rewrites tools/test_durations.json

The modules are found as ``unittest discover`` finds them (``test*.py`` in ``tests`` and in its
sub-packages), then shared out between ``-j`` processes, each ``python -m unittest <modules>``
started from the root of the repository. The shares are balanced by the duration of each
module as ``tools/test_durations.json`` keeps it (``--measure`` writes it again); a module it
does not know weighs its size. Each process writes into a file of its own; its output is
printed whole when it ends (never two processes mixed), as it came, ResourceWarning included,
under a line that names its modules. Then the total, in the words of unittest: ``Ran N
tests``, then ``OK`` or ``FAILED (failures=…, errors=…, skipped=…)``.

Exit code: 0 when every process is green, 1 otherwise, 2 for a usage error, 130 when
interrupted. The environment of the processes is this one, unchanged.
"""
import argparse
import fnmatch
import json
import os
import platform
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DURATIONS = os.path.join(ROOT, "tools", "test_durations.json")
MAX_JOBS = 8          # past eight, the longest module sets the pace anyway
RAN = re.compile(rb"^Ran (\d+) tests? in ", re.M)
VERDICT = re.compile(rb"^(OK|FAILED)(?: \((.*)\))?\s*$", re.M)
COUNTS = ("failures", "errors", "skipped", "expected failures", "unexpected successes")


def default_jobs():
    count = os.process_cpu_count() if hasattr(os, "process_cpu_count") else os.cpu_count()
    return max(1, min(count or 1, MAX_JOBS))


def discover(start="tests", top=ROOT, pattern="test*.py"):
    """The dotted names of the test modules, in the order of ``unittest discover``: the files of
    a folder that match, then its sub-folders that are packages (an ``__init__.py``)."""
    names = []

    def walk(folder):
        for entry in sorted(os.listdir(folder)):
            path = os.path.join(folder, entry)
            if os.path.isfile(path):
                stem, ext = os.path.splitext(entry)
                if ext == ".py" and stem.isidentifier() and fnmatch.fnmatch(entry, pattern):
                    rel = os.path.relpath(os.path.join(folder, stem), top)
                    names.append(rel.replace(os.sep, "."))
            elif os.path.isfile(os.path.join(path, "__init__.py")):
                walk(path)

    walk(os.path.join(top, start))
    return names


def module_file(name, top=ROOT):
    return os.path.join(top, *name.split(".")) + ".py"


def read_durations(path=DURATIONS):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("modules") or {}
    except (OSError, ValueError):
        return {}


def weights(modules, durations, top=ROOT):
    """Seconds for each module: the known duration, or its size at the pace of the known ones."""
    sizes = {}
    for name in modules:
        try:
            sizes[name] = os.path.getsize(module_file(name, top))
        except OSError:
            sizes[name] = 1
    known = [n for n in modules if n in durations]
    pace = (sum(durations[n] for n in known) / max(1, sum(sizes[n] for n in known))) if known else 1.0
    return {n: float(durations[n]) if n in durations else sizes[n] * pace for n in modules}


def share(modules, weight, jobs):
    """The modules in at most ``jobs`` shares of close weight: the heaviest first, each to the
    lightest share (each share then in discover order)."""
    count = max(1, min(jobs, len(modules)))
    shares = [[] for _ in range(count)]
    loads = [0.0] * count
    order = {name: i for i, name in enumerate(modules)}
    for name in sorted(modules, key=lambda n: (-weight[n], order[n])):
        i = loads.index(min(loads))
        shares[i].append(name)
        loads[i] += weight[name]
    return [sorted(s, key=order.get) for s in shares if s]


def counts_of(output):
    """(tests run, {failures, errors, skipped, …}, whether unittest gave its verdict)."""
    ran = RAN.findall(output)
    verdict = VERDICT.findall(output)
    found = {k: 0 for k in COUNTS}
    if verdict:
        for part in verdict[-1][1].decode("ascii", "replace").split(","):
            key, _, value = part.strip().partition("=")
            if key in found and value.isdigit():
                found[key] = int(value)
    return int(ran[-1]) if ran else 0, found, bool(ran and verdict)


def summary_line(found):
    shown = [f"{k}={found[k]}" for k in COUNTS if found[k]]
    bad = found["failures"] or found["errors"] or found["unexpected successes"]
    return ("FAILED" if bad else "OK") + (f" ({', '.join(shown)})" if shown else "")


class Batch:
    def __init__(self, number, modules):
        self.number, self.modules = number, modules
        self.code, self.seconds, self.output = None, 0.0, b""


def run_batch(batch, verbose, python, top, stop):
    argv = [python, "-m", "unittest", *(["-v"] if verbose else []), *batch.modules]
    with tempfile.TemporaryFile() as out:
        t0 = time.monotonic()
        proc = subprocess.Popen(argv, cwd=top, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            if stop.wait(0.2):
                proc.kill()
                proc.wait()
                break
        batch.seconds = time.monotonic() - t0
        batch.code = proc.returncode
        out.seek(0)
        batch.output = out.read()
    return batch


def header(batch, total):
    shown = ", ".join(m.rsplit(".", 1)[-1] for m in batch.modules)
    return (f"===== process {batch.number}/{total}: {len(batch.modules)} module(s), {batch.seconds:.1f} s, "
            f"exit {batch.code}: {shown}\n")


def execute(batches, jobs, verbose=False, python=sys.executable, top=ROOT, out=None):
    """Runs the batches, ``jobs`` at a time; prints each output whole as it ends. Returns them."""
    out = out or sys.stdout.buffer
    todo, done, stop = queue.Queue(), queue.Queue(), threading.Event()
    for batch in batches:
        todo.put(batch)

    def worker():
        while not stop.is_set():
            try:
                batch = todo.get_nowait()
            except queue.Empty:
                return
            done.put(run_batch(batch, verbose, python, top, stop))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(jobs, len(batches))))]
    for t in threads:
        t.start()
    try:
        for _ in batches:
            batch = done.get()
            out.write(header(batch, len(batches)).encode("utf-8"))
            out.write(batch.output.replace(b"\r\n", b"\n"))
            if not batch.output.endswith(b"\n"):
                out.write(b"\n")
            out.flush()
    except KeyboardInterrupt:
        stop.set()
        for t in threads:
            t.join()
        raise
    return batches


def total(batches, seconds, out):
    ran, found, broken = 0, {k: 0 for k in COUNTS}, []
    for batch in batches:
        n, counts, complete = counts_of(batch.output)
        ran += n
        for k in COUNTS:
            found[k] += counts[k]
        if batch.code != 0 and not (counts["failures"] or counts["errors"]):
            found["errors"] += 1      # a process that died before its verdict
        if batch.code != 0 or not complete:
            broken.append(batch)
    longest = max((b.seconds for b in batches), default=0.0)
    lines = ["", "=" * 70]
    for batch in broken:
        lines.append(f"process {batch.number} not green (exit {batch.code}): {' '.join(batch.modules)}")
    lines += [f"Ran {ran} tests in {seconds:.3f}s ({len(batches)} processes, the longest {longest:.1f} s)", "",
              summary_line(found)]
    out.write(("\n".join(lines) + "\n").encode("utf-8"))
    out.flush()
    return 1 if broken else 0


def write_durations(batches, path=DURATIONS):
    data = {"comment": "seconds per test module, one process each: python tools/run_tests.py --measure",
            "measured": time.strftime("%Y-%m-%d"),
            "python": platform.python_version(), "platform": platform.system(),
            "modules": {b.modules[0]: round(b.seconds, 1) for b in sorted(batches, key=lambda b: b.modules[0])}}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")


def parse_args(argv):
    p = argparse.ArgumentParser(description="Runs the test suite (python -m unittest discover -s tests) "
                                "in several processes.")
    p.add_argument("-j", "--jobs", type=int, default=default_jobs(),
                   help=f"processes at a time (default: the cores of this machine, at most {MAX_JOBS})")
    p.add_argument("-v", "--verbose", action="store_true", help="the verbose output of unittest")
    p.add_argument("-s", "--start-directory", default="tests", help="where discovery starts (default: tests)")
    p.add_argument("-p", "--pattern", default="test*.py", help="the test files (default: test*.py)")
    p.add_argument("--measure", action="store_true",
                   help="one process per module, and the durations written to tools/test_durations.json")
    p.add_argument("--durations", default=DURATIONS, help="the file of module durations (default: %(default)s)")
    p.add_argument("--top", default=ROOT, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if args.jobs < 1:
        p.error("-j takes 1 or more")
    return args


def main(argv=None):
    args = parse_args(argv)
    modules = discover(args.start_directory, args.top, args.pattern)
    if not modules:
        print(f"no test module in {args.start_directory}")
        return 2
    weight = weights(modules, read_durations(args.durations), args.top)
    if args.measure:
        groups = [[m] for m in sorted(modules, key=lambda n: -weight[n])]
    elif args.jobs == 1:
        groups = [modules]
    else:
        groups = share(modules, weight, args.jobs)
    batches = [Batch(i, g) for i, g in enumerate(groups, 1)]
    print(f"{len(modules)} test modules in {len(batches)} process(es), {min(args.jobs, len(batches))} at a time",
          flush=True)
    start = time.monotonic()
    try:
        execute(batches, args.jobs, args.verbose, top=args.top)
    except KeyboardInterrupt:
        print("\ninterrupted", flush=True)
        return 130
    code = total(batches, time.monotonic() - start, sys.stdout.buffer)
    if args.measure:
        write_durations(batches, args.durations)
        print(f"durations written: {args.durations}")
    return code


if __name__ == "__main__":
    sys.exit(main())
