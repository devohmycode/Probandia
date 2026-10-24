"""Replays the jobs of ``.github/workflows/ci.yml`` on this machine: under Windows, and under
Ubuntu through WSL. Until the 1.0.0 nothing is pushed (version-1.0.0 T2): this is the CI.

    python tools/ci_local.py                                  # every job, every combination
    python tools/ci_local.py --jobs test --os windows --python 3.14
    python tools/ci_local.py --rev HEAD~1                     # a commit instead of the working tree
    python tools/ci_local.py --quick                          # what a sprint needs before its merge
    python tools/ci_local.py --parallel 1                     # one combination at a time (default 8)
    python tools/ci_local.py --dry-run                        # the combinations and their commands only
    python tools/ci_local.py --bilan <run folder>             # the bilan of a past run, again

The steps are read from ``ci.yml`` itself, with the matrix GitHub would build for ``master``:
``actions/checkout`` becomes a fresh copy of the source, ``actions/setup-python`` a virtual
environment made by ``uv venv --seed --python <version>``, ``actions/setup-node`` the Node of
this machine, and each ``run`` goes to the shell GitHub would use (``bash -e``, ``bash
--noprofile --norc -eo pipefail`` for ``shell: bash``, PowerShell on a Windows runner). A step
or a key it does not know stops it before anything runs.

- Source: the working tree as it is on disk (the files git tracks, and the new ones it does
  not ignore), or the commit given by ``--rev``. Each combination gets its own copy, a git
  repository of one commit, so that ``git status --porcelain`` works there; never the
  worktree itself.
- Windows: the copy sits in ``<work dir>/<run>/<combination>``, the commands run directly
  (Git Bash for bash, ``pwsh`` for PowerShell).
- Ubuntu: ``wsl.exe -d Ubuntu-24.04 --exec bash -lc ...``, the copy in the Linux file system
  (``~/probandia-ci/<run>/<combination>``), the Windows folders taken off ``PATH``. ``--exec``
  rather than ``--``: ``--`` hands the line to the default shell, which would expand it once more.
- The ``gedcom`` job runs under Windows, where Node is installed (WSL has none); its steps
  keep the shell of their runner, bash.
- macOS cannot run here: its combinations are listed, not run (checked at the first push).

``--quick`` runs ``test (windows-latest, 3.14)`` and ``test (ubuntu-latest, 3.12)``, plus
``tui (windows-latest, 3.14)`` when the revision changes a file of the TUI or of its tests, and
``gedcom`` when it changes a file of the GEDCOM export (the files counted between the revision,
or the working tree, and its merge base with ``master``). When it changes the CI itself, the
package or the version (``FULL_FILES``: ``ci.yml``, ``ci_local.py``, ``run_tests.py``,
``check_wheel.py``, ``pyproject.toml``, ``run_probandia.py``, ``src/probandia/__init__.py``),
``--quick`` runs the whole CI instead and says why: a quick check cannot vouch for the CI that
makes it. The bilan names what was left out, and why.

Each combination writes ``<combination>.log`` (every output, the duration of each step) in
the run folder (``~/probandia-ci/<run>`` unless ``--work-dir``); the bilan gives one line per
combination (``bilan.txt``, ``bilan.json``). The copy of a green combination is removed
unless ``--keep``. Eight combinations run at a time (``--parallel``), each with its tests shared
out between processes by ``tools/run_tests.py``; ``--verbose`` echoes the steps with
``--parallel 1`` only. Exit code: 0 when every combination is green, 1 otherwise, 2 for a usage
error or a missing tool, 130 when interrupted.
"""
import argparse
import concurrent.futures
import dataclasses
import fnmatch
import io
import itertools
import json
import ntpath
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from probandia.util import yamlio  # noqa: E402

WORKFLOW = ".github/workflows/ci.yml"
DISTRO = "Ubuntu-24.04"
PLACES = ("windows", "ubuntu")
LOCAL_PLACE_OF_JOB = {"gedcom": "windows"}   # js-gedcom needs Node, which WSL does not have
REF = "refs/heads/master"                    # the local CI stands for the CI of master
STEP_KEYS = {"name", "uses", "with", "run", "shell", "if", "env", "id", "timeout-minutes"}
JOB_KEYS = {"strategy", "runs-on", "steps", "name", "env", "timeout-minutes"}
STATUS_FUNCTIONS = ("success", "failure", "always", "cancelled")
# what a runner does not have: the settings of Probandia and of the harnesses, a Python of the user's
STRIPPED_PREFIXES = ("PROBANDIA_", "CLAUDE", "CODEX_", "CURSOR_", "FACTORY_", "DROID_", "GROK_", "ANTIGRAVITY_",
                     "OPENCODE", "PYTHON", "VIRTUAL_ENV", "CONDA_")
# the times of tests/unit/test_tui_speed.py hold on a calm machine, not under the load of this replay (some
# 34 processes on 16 cores): its assertions of time are skipped here, the rest of it runs (version-1.0.0 T91)
LOCAL_ENV = {"CI_LOCAL_NO_TIMING": "1"}
SNAPSHOT_AUTHOR = ["-c", "user.name=ci-local", "-c", "user.email=ci-local@localhost"]
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
# combinations at a time: each one runs its tests in several processes (tools/run_tests.py), so
# eight of them keep the sixteen cores busy: the whole CI took 6 min 16 s with 6, 5 min 44 s with 8,
# 5 min 46 s with all 11 at once (14 October 2026)
PARALLEL = 8


class Unsupported(Exception):
    """ci.yml uses something this replay does not know: teach it before trusting it."""


# GitHub expressions: the small part ci.yml uses


TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>\d+(?:\.\d+)?)"
                   r"|(?P<op>==|!=|&&|\|\||!|\(|\)|,)|(?P<name>[A-Za-z_][A-Za-z0-9_.-]*))")


def tokenize(text):
    tokens, pos, text = [], 0, text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise Unsupported(f"expression not understood: {text!r}")
        pos = m.end()
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
    return tokens


def truthy(value):
    return value not in (None, False, 0, "") and value == value


def equal(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    return a == b


class Expression:
    """``||``, ``&&``, ``!``, ``==``, ``!=``, parentheses, strings, numbers, true/false/null,
    the contexts github, matrix, runner, env, and the status functions."""

    def __init__(self, text, context, failed):
        self.tokens, self.i, self.context, self.failed = tokenize(text), 0, context, failed

    def value(self):
        v = self.either()
        if self.i != len(self.tokens):
            raise Unsupported(f"expression not understood after {self.tokens[self.i][1]!r}")
        return v

    def peek(self, op):
        return self.i < len(self.tokens) and self.tokens[self.i] == ("op", op)

    def either(self):
        v = self.both()
        while self.peek("||"):
            self.i += 1
            right = self.both()
            v = v if truthy(v) else right
        return v

    def both(self):
        v = self.compare()
        while self.peek("&&"):
            self.i += 1
            right = self.compare()
            v = right if truthy(v) else v
        return v

    def compare(self):
        v = self.unary()
        for op in ("==", "!="):
            if self.peek(op):
                self.i += 1
                same = equal(v, self.unary())
                return same if op == "==" else not same
        return v

    def unary(self):
        if self.peek("!"):
            self.i += 1
            return not truthy(self.unary())
        return self.primary()

    def primary(self):
        if self.i >= len(self.tokens):
            raise Unsupported("expression ends too early")
        kind, text = self.tokens[self.i]
        self.i += 1
        if kind == "str":
            return text[1:-1].replace("''", "'")
        if kind == "num":
            return float(text)
        if (kind, text) == ("op", "("):
            v = self.either()
            if not self.peek(")"):
                raise Unsupported("missing )")
            self.i += 1
            return v
        if kind != "name":
            raise Unsupported(f"unexpected {text!r}")
        if self.peek("("):
            self.i += 1
            if not self.peek(")") or text not in STATUS_FUNCTIONS:
                raise Unsupported(f"function {text}() is not known here")
            self.i += 1
            return {"success": not self.failed, "failure": self.failed, "always": True, "cancelled": False}[text]
        if text in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[text]
        head, *rest = text.split(".")
        if head not in self.context:
            raise Unsupported(f"context {head} is not known here")
        v = self.context[head]
        for part in rest:
            v = v.get(part) if isinstance(v, dict) else None
        return v


def strip_braces(text):
    text = text.strip()
    if text.startswith("${{") and text.endswith("}}"):
        return text[3:-2]
    return text


def evaluate(text, context, failed=False):
    return Expression(strip_braces(text), context, failed).value()


def condition(text, context, failed):
    """Whether a step runs: ``success()`` unless the condition names a status function."""
    if text is None or isinstance(text, bool):
        return text is not False and not failed
    text = str(text)
    value = truthy(evaluate(text, context, failed))
    if not any(re.search(rf"\b{f}\s*\(", text) for f in STATUS_FUNCTIONS):
        value = value and not failed
    return value


def as_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def interpolate(text, context):
    if not isinstance(text, str):
        return as_text(text)
    return re.sub(r"\$\{\{(.*?)\}\}", lambda m: as_text(evaluate(m.group(1), context)), text)


# the plan: combinations and steps


@dataclasses.dataclass
class Step:
    number: int
    name: str
    kind: str                 # checkout, python, node, run
    condition: object = None
    script: str = ""
    shell: str = ""           # bash (-eo pipefail), bash-e, pwsh
    version: str = ""
    env: dict = dataclasses.field(default_factory=dict)
    timeout: float = None     # minutes


@dataclasses.dataclass
class Combination:
    job: str
    name: str                 # as GitHub names it: test (windows-latest, 3.14)
    runs_on: str
    place: str                # windows, ubuntu, or None: not on this machine
    python: str
    matrix: dict
    steps: list
    varies_python: bool = False

    @property
    def id(self):
        return f"{self.job}-{self.place or self.runs_on}-{self.python or 'none'}"


def expand_matrix(job, context):
    """The combinations GitHub builds from ``strategy.matrix`` (include and exclude included)."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if not matrix:
        return [{}], []
    if not isinstance(matrix, dict):
        raise Unsupported("a matrix given by an expression")
    keys = [k for k in matrix if k not in ("include", "exclude")]

    def values(entry):
        return {k: interpolate(v, context) for k, v in entry.items()}

    lists = [[interpolate(v, context) for v in matrix[k]] for k in keys]
    combos = [dict(zip(keys, product)) for product in itertools.product(*lists)]
    for entry in matrix.get("exclude") or []:
        entry = values(entry)
        combos = [c for c in combos if not all(c.get(k) == v for k, v in entry.items())]
    originals = list(combos)
    for entry in matrix.get("include") or []:
        entry = values(entry)
        matched = False
        for combo in originals:
            if all(combo[k] == v for k, v in entry.items() if k in keys):
                combo.update({k: v for k, v in entry.items() if k not in keys})
                matched = True
        if not matched:
            combos.append(entry)
    return combos, keys


def place_of(runs_on):
    for place in PLACES:
        if runs_on.startswith(place):
            return place
    return None


def runner_context(runs_on):
    family = runs_on.split("-")[0]
    return {"os": {"windows": "Windows", "ubuntu": "Linux", "macos": "macOS"}.get(family, family),
            "runs-on": runs_on}


def shell_of(shell, runs_on):
    if shell == "bash":
        return "bash"
    if shell == "pwsh":
        return "pwsh"
    if shell is None:
        return "pwsh" if runs_on.startswith("windows") else "bash-e"
    raise Unsupported(f"shell {shell!r}")


def plan_steps(job_id, job, context, env):
    steps = []
    for number, raw in enumerate(job.get("steps") or [], 1):
        unknown = set(raw) - STEP_KEYS
        if unknown:
            raise Unsupported(f"job {job_id}, step {number}: key {', '.join(sorted(unknown))}")
        with_ = {k: interpolate(v, context) for k, v in (raw.get("with") or {}).items()}
        step_env = dict(env, **{k: interpolate(v, context) for k, v in (raw.get("env") or {}).items()})
        common = dict(number=number, condition=raw.get("if"), env=step_env, timeout=raw.get("timeout-minutes"))
        uses = raw.get("uses")
        if uses:
            action = uses.split("@")[0]
            if action == "actions/checkout":
                steps.append(Step(name=raw.get("name") or "Check out (a fresh copy of the source)", kind="checkout",
                                  **common))
            elif action == "actions/setup-python":
                version = with_.get("python-version", "")
                steps.append(Step(name=raw.get("name") or f"Set up Python {version} (uv venv)", kind="python",
                                  version=version, **common))
            elif action == "actions/setup-node":
                version = with_.get("node-version", "")
                steps.append(Step(name=raw.get("name") or f"Set up Node {version} (the Node of this machine)",
                                  kind="node", version=version, **common))
            else:
                raise Unsupported(f"job {job_id}, step {number}: action {action}")
        elif "run" in raw:
            script = interpolate(raw["run"], context)
            if not script.endswith("\n"):
                script += "\n"
            first = script.strip().splitlines()[0]
            steps.append(Step(name=raw.get("name") or f"Run {first}", kind="run", script=script,
                              shell=shell_of(raw.get("shell"), context["runner"]["runs-on"]), **common))
        else:
            raise Unsupported(f"job {job_id}, step {number}: neither uses nor run")
    return steps


def plan(workflow, ref=REF):
    """Every combination of the workflow, as GitHub would run it for ``ref``."""
    github = {"ref": ref, "event_name": "push", "ref_name": ref.rsplit("/", 1)[-1]}
    top_env = workflow.get("env") or {}
    combinations = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        unknown = set(job) - JOB_KEYS
        if unknown:
            raise Unsupported(f"job {job_id}: key {', '.join(sorted(unknown))}")
        combos, keys = expand_matrix(job, {"github": github})
        for matrix in combos:
            context = {"github": github, "matrix": matrix, "env": {}}
            runs_on = interpolate(job.get("runs-on", ""), context)
            context["runner"] = runner_context(runs_on)
            env = {k: interpolate(v, context) for k, v in dict(top_env, **(job.get("env") or {})).items()}
            context["env"] = env
            steps = plan_steps(job_id, job, context, env)
            python = next((s.version for s in steps if s.kind == "python"), "")
            name = f"{job_id} ({', '.join(as_text(v) for v in matrix.values())})" if matrix else job_id
            place = LOCAL_PLACE_OF_JOB.get(job_id) or place_of(runs_on)
            combinations.append(Combination(job_id, name, runs_on, place, python, matrix, steps,
                                             varies_python="python" in keys))
    return combinations


# --quick: the combinations a sprint needs, from the files it changes


QUICK_TEST = {("test", "windows", "3.14"), ("test", "ubuntu", "3.12")}
QUICK_TUI = ("tui", "windows", "3.14")
QUICK_BASE = "master"
# fnmatch patterns on the paths git gives ("*" crosses "/")
TUI_FILES = ("src/probandia/cli/tui_*", "tests/unit/test_tui*")
GEDCOM_FILES = ("src/probandia/gedcom*", "src/probandia/cli/export_cmd.py", "tools/check_gedcom7.py",
                "tools/validate_gedcom7.mjs", "tests/unit/test_trees_exports.py", "tests/fixtures/gedcom/*",
                "tests/fixtures/project/*", "tests/fixtures/tree/*")
# the CI itself, the package and the version: a change there is checked by every combination
FULL_FILES = (WORKFLOW, "tools/ci_local.py", "tools/run_tests.py", "pyproject.toml", "run_probandia.py",
              "src/probandia/__init__.py", "tools/check_wheel.py")


def matching(paths, patterns):
    return [p for p in paths if any(fnmatch.fnmatchcase(p, pattern) for pattern in patterns)]


def changed_files(rev, root=ROOT, base=QUICK_BASE):
    """The files the revision changes since its merge base with ``base``; for the working tree,
    its changes and its new files too."""
    sha = git("rev-parse", "--verify", f"{rev or 'HEAD'}^{{commit}}", cwd=root).strip()
    merge_base = git("merge-base", base, sha, cwd=root).strip()
    names = git("diff", "--name-only", "-z", merge_base, *([sha] if rev else []), cwd=root).split("\0")
    if not rev:
        names += git("ls-files", "-z", "--others", "--exclude-standard", cwd=root).split("\0")
    return sorted({n for n in names if n})


def quick_select(combinations, changed):
    """(the combinations of --quick, those left out with why, the files that call for the whole CI)."""
    full = matching(changed, FULL_FILES)
    if full:
        return None, [], full
    tui, gedcom = matching(changed, TUI_FILES), matching(changed, GEDCOM_FILES)
    chosen, left = [], []
    for combo in combinations:
        if combo.place is None:
            continue      # macOS: listed as not run here, like the whole CI does
        key = (combo.job, combo.place, combo.python)
        if combo.job == "test":
            keep, why = key in QUICK_TEST, "quick: the test job on Windows 3.14 and Ubuntu 3.12 only"
        elif combo.job == "tui":
            keep = bool(tui) and key == QUICK_TUI
            why = "quick: one tui combination, Windows 3.14" if tui else "quick: no file of the TUI changed"
        elif combo.job == "gedcom":
            keep, why = bool(gedcom), "quick: no file of the GEDCOM export changed"
        else:
            keep, why = True, ""
        if keep:
            chosen.append(combo)
        else:
            left.append({"name": combo.name, "why": why})
    return chosen, left, []


def select(combinations, jobs=None, places=None, pythons=None):
    """(the combinations to run, those that match but cannot run here)."""
    chosen, absent = [], []
    for combo in combinations:
        if jobs and combo.job not in jobs:
            continue
        if pythons and combo.varies_python and combo.python not in pythons:
            continue
        if combo.place is None:
            absent.append(combo)
        elif not places or combo.place in places:
            chosen.append(combo)
    return chosen, absent


# commands


def wsl_path(path):
    """C:\\Users\\x -> /mnt/c/Users/x (the default mount of WSL)."""
    drive, rest = ntpath.splitdrive(ntpath.normpath(path))
    if len(drive) != 2 or drive[1] != ":":
        raise ValueError(f"not a path on a Windows drive: {path}")
    return f"/mnt/{drive[0].lower()}" + rest.replace("\\", "/")


def forward(path):
    return path.replace("\\", "/")


def wsl_argv(script, distro=DISTRO):
    return ["wsl.exe", "-d", distro, "--exec", "bash", "-lc", script]


def linux_dir(run_id, combo_id):
    for part in (run_id, combo_id):
        if not SAFE_ID.match(part):
            raise ValueError(f"unsafe name {part!r}")
    return f'"$HOME/probandia-ci/{run_id}/{combo_id}"'


def shell_flags(shell):
    return {"bash": ["--noprofile", "--norc", "-eo", "pipefail"], "bash-e": ["-e"]}[shell]


def script_text(step):
    """The file a run step executes, as GitHub writes it."""
    if step.shell == "pwsh":
        return ("$ErrorActionPreference = 'stop'\n" + step.script
                + "if ((Test-Path -LiteralPath variable:\\LASTEXITCODE)) { exit $LASTEXITCODE }\n")
    return step.script


def script_name(step):
    return f"{step.number:02d}.{'ps1' if step.shell == 'pwsh' else 'sh'}"


def windows_run_argv(step, script, git_bash, pwsh):
    if step.shell == "pwsh":
        return [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", f". '{script}'"]
    return [git_bash, *shell_flags(step.shell), forward(script)]


def windows_env(base, layout, venv, step_env):
    env = {k: v for k, v in base.items() if not k.upper().startswith(STRIPPED_PREFIXES)}
    env.update(CI="true", RUNNER_OS="Windows", RUNNER_TEMP=forward(layout["tmp"]),
               GITHUB_WORKSPACE=forward(layout["src"]), GITHUB_STEP_SUMMARY=layout["summary"], **LOCAL_ENV)
    if venv:
        env["VIRTUAL_ENV"] = layout["venv"]
        env["PATH"] = os.path.join(layout["venv"], "Scripts") + ";" + env.get("PATH", "")
    env.update(step_env)
    return env


def wsl_prelude(run_id, combo_id, summary, venv, step_env):
    """The lines that give a WSL step the environment of a runner."""
    d = linux_dir(run_id, combo_id)
    exports = {"CI": "true", "RUNNER_OS": "Linux", "GITHUB_STEP_SUMMARY": wsl_path(summary), **LOCAL_ENV}
    lines = ["set -e", f"D={d}",
             # a Linux runner has no Windows folders on PATH (WSL appends them)
             'set -f; P=; IFS=:; for p in $PATH; do case $p in /mnt/*) ;; *) P="${P:+$P:}$p" ;; esac; done',
             'unset IFS; set +f; PATH="$P"',
             'export RUNNER_TEMP="$D/tmp" GITHUB_WORKSPACE="$D/src" LANG=C.UTF-8',
             "export " + " ".join(f"{k}={shlex.quote(v)}" for k, v in exports.items())]
    if venv:
        lines.append('export VIRTUAL_ENV="$D/venv" PATH="$D/venv/bin:$PATH"')
    if step_env:
        lines.append("export " + " ".join(f"{k}={shlex.quote(str(v))}" for k, v in step_env.items()))
    lines.append('mkdir -p "$RUNNER_TEMP"')
    return lines


def wsl_run_script(step, run_id, combo_id, summary, venv, script):
    lines = wsl_prelude(run_id, combo_id, summary, venv, step.env)
    lines += ['cd "$D/src"', f"exec bash {' '.join(shell_flags(step.shell))} {shlex.quote(wsl_path(script))}"]
    return "\n".join(lines) + "\n"


def wsl_checkout_script(run_id, combo_id, tar):
    d = linux_dir(run_id, combo_id)
    author = " ".join(SNAPSHOT_AUTHOR)
    return "\n".join([
        "set -e", f"D={d}", 'rm -rf "$D"', 'mkdir -p "$D/src" "$D/tmp"',
        f'tar -xf {shlex.quote(wsl_path(tar))} -C "$D/src"', 'cd "$D/src"',
        # --force: the local list private/forbidden-names.txt matches .gitignore; the tar holds nothing else
        "git -c init.defaultBranch=master init -q", "git add -A --force",
        f'git {author} commit -q -m "ci-local snapshot"',
        'echo "copy: $D/src at $(git rev-parse --short HEAD), $(git ls-files | wc -l) files"']) + "\n"


def wsl_python_script(run_id, combo_id, version):
    """A Python of uv's own: Ubuntu's lacks ensurepip without python3-venv, where setup-python's has it."""
    return "\n".join(["set -e", f"D={linux_dir(run_id, combo_id)}", 'cd "$D"',
                      f"uv venv --seed --python-preference only-managed --python {shlex.quote(version)} venv",
                      "venv/bin/python --version"]) + "\n"


def wsl_cleanup_script(run_id, combo_id):
    d = linux_dir(run_id, combo_id)
    return f'rm -rf {d}; rmdir "$HOME/probandia-ci/{run_id}" 2>/dev/null || true\n'


# the source


def parse_ls_files(text):
    """{path: mode} from ``git ls-files -s -z``."""
    entries = {}
    for record in text.split("\0"):
        if record:
            meta, path = record.split("\t", 1)
            entries[path] = meta.split()[0]
    return entries


def git(*args, cwd=ROOT):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout.decode("utf-8")


def working_tree_files(root=ROOT):
    """(path, mode): the tracked files, then the new ones git does not ignore."""
    entries = parse_ls_files(git("ls-files", "-s", "-z", cwd=root))
    new = [p for p in git("ls-files", "-z", "--others", "--exclude-standard", cwd=root).split("\0") if p]
    for path in new:
        entries.setdefault(path, "100644")
    return sorted(entries.items()), new


def write_working_tree(root, files, tar_path):
    """The files as they are on disk, in a tar; returns how many went in."""
    count = 0
    with tarfile.open(tar_path, "w") as tar:
        for path, mode in files:
            full = os.path.join(root, path)
            if mode == "160000":
                continue
            info = tarfile.TarInfo(path)
            info.mtime = int(time.time())
            if mode == "120000":
                if not os.path.lexists(full):
                    continue
                info.type = tarfile.SYMTYPE
                if os.path.islink(full):
                    info.linkname = os.readlink(full)
                else:
                    with open(full, encoding="utf-8") as fh:
                        info.linkname = fh.read()
                tar.addfile(info)
                count += 1
                continue
            if not os.path.isfile(full):
                continue   # deleted in the working tree
            with open(full, "rb") as fh:
                data = fh.read()
            info.size = len(data)
            info.mode = 0o755 if mode == "100755" else 0o644
            tar.addfile(info, io.BytesIO(data))
            count += 1
    return count


PRIVATE_NAMES = "private/forbidden-names.txt"   # read by tests/unit/test_no_private_names.py when present


def add_private_names(tar_path, root=ROOT):
    """Adds the local list of forbidden names (never tracked) to the copied source, so that the guard test
    runs with it here as in the working tree; a name it lists, slipped into a tracked file, fails the CI."""
    path = os.path.join(root, *PRIVATE_NAMES.split("/"))
    if not os.path.isfile(path):
        return False
    with tarfile.open(tar_path, "a") as tar:
        tar.add(path, arcname=PRIVATE_NAMES)
    return True


def snapshot(rev, tar_path, root=ROOT):
    """Writes the source in a tar, with the local list of forbidden names; returns (its description,
    the text of ci.yml)."""
    description, text = _snapshot(rev, tar_path, root)
    if add_private_names(tar_path, root):
        description += ", with the local list of forbidden names"
    return description, text


def _snapshot(rev, tar_path, root=ROOT):
    if rev:
        sha = git("rev-parse", "--verify", f"{rev}^{{commit}}", cwd=root).strip()
        git("archive", "--format=tar", "-o", tar_path, sha, cwd=root)
        subject = git("log", "-1", "--format=%s", sha, cwd=root).strip()
        return f"commit {sha[:12]} ({subject[:70]})", git("show", f"{sha}:{WORKFLOW}", cwd=root)
    files, new = working_tree_files(root)
    count = write_working_tree(root, files, tar_path)
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
    head = git("rev-parse", "--short", "HEAD", cwd=root).strip()
    changed = [line for line in git("status", "--porcelain", cwd=root).splitlines() if not line.startswith("??")]
    with open(os.path.join(root, WORKFLOW), encoding="utf-8") as fh:
        text = fh.read()
    return (f"working tree of {branch} at {head}: {count} files, {len(changed)} changed and {len(new)} new "
            "since the commit"), text


# running


def duration(seconds):
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes} min {rest:02d} s"


def decode(line):
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return line.decode("cp1252", "replace")


RUNNING = set()
STOP = threading.Event()


def kill(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def stream(argv, log, cwd=None, env=None, timeout=None, echo=None):
    """Runs a command, its output into the log; returns its exit code (124 on timeout)."""
    log.write(f"$ {subprocess.list2cmdline(argv) if os.name == 'nt' else shlex.join(argv)}\n")
    log.flush()
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
    except OSError as err:
        log.write(f"cannot start: {err}\n")
        return 127
    RUNNING.add(proc)
    timer = None
    expired = threading.Event()
    if timeout:
        def expire():
            expired.set()
            kill(proc)
        timer = threading.Timer(timeout, expire)
        timer.start()
    try:
        for raw in proc.stdout:
            text = decode(raw).rstrip("\r\n")
            log.write(text + "\n")
            log.flush()
            if echo:
                echo(text)
        proc.wait()
    finally:
        if timer:
            timer.cancel()
        RUNNING.discard(proc)
    log.flush()
    if expired.is_set():
        log.write(f"stopped after {timeout / 60:.0f} minutes\n")
        return 124
    return proc.returncode


def remove_tree(path):
    def retry(func, target, *_):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if os.path.isdir(path):
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=retry)
        else:
            shutil.rmtree(path, onerror=retry)


@dataclasses.dataclass
class Tools:
    git_bash: str = None
    pwsh: str = None
    uv: str = None
    node: str = None


class Place:
    """Where a combination runs; ``execute`` returns an exit code."""

    def __init__(self, run, combo):
        self.run, self.combo, self.venv = run, combo, False
        base = os.path.join(run.folder, combo.id)
        self.layout = {"base": base, "src": os.path.join(base, "src"), "venv": os.path.join(base, "venv"),
                       "tmp": os.path.join(base, "tmp"), "steps": os.path.join(run.folder, combo.id + ".steps"),
                       "summary": os.path.join(run.folder, combo.id + ".summary.md")}

    def write_script(self, step):
        os.makedirs(self.layout["steps"], exist_ok=True)
        path = os.path.join(self.layout["steps"], script_name(step))
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(script_text(step))
        return path


class WindowsPlace(Place):
    def env(self, step):
        return windows_env(os.environ, self.layout, self.venv, step.env)

    def execute(self, step, log, timeout, echo):
        tools, layout = self.run.tools, self.layout
        if step.kind == "checkout":
            remove_tree(layout["base"])
            os.makedirs(layout["src"])
            os.makedirs(layout["tmp"])
            with tarfile.open(self.run.tar) as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(layout["src"], filter="data")
                else:
                    tar.extractall(layout["src"])
            src = layout["src"]
            for argv in (["git", "-c", "init.defaultBranch=master", "init", "-q"], ["git", "add", "-A", "--force"],
                         ["git", *SNAPSHOT_AUTHOR, "commit", "-q", "-m", "ci-local snapshot"]):
                code = stream(argv, log, cwd=src, timeout=timeout)
                if code:
                    return code
            log.write(f"copy: {src}\n")
            return 0
        if step.kind == "python":
            code = stream([tools.uv, "venv", "--seed", "--python", step.version, layout["venv"]], log,
                          cwd=layout["base"], env=windows_env(os.environ, layout, False, {}), timeout=timeout)
            if code == 0:
                self.venv = True
                code = stream([os.path.join(layout["venv"], "Scripts", "python.exe"), "--version"], log)
            return code
        if step.kind == "node":
            if not tools.node:
                log.write("no node on this machine\n")
                return 1
            out = subprocess.run([tools.node, "--version"], capture_output=True, text=True).stdout.strip()
            log.write(f"node {out} ({tools.node})\n")
            if out.lstrip("v").split(".")[0] != step.version.split(".")[0]:
                log.write(f"warning: the CI installs Node {step.version}, this machine has {out}\n")
            return 0
        script = self.write_script(step)
        argv = windows_run_argv(step, script, tools.git_bash, tools.pwsh)
        return stream(argv, log, cwd=layout["src"], env=self.env(step), timeout=timeout, echo=echo)

    def cleanup(self, log):
        remove_tree(self.layout["base"])
        remove_tree(self.layout["steps"])


class WslPlace(Place):
    def execute(self, step, log, timeout, echo):
        run, combo = self.run, self.combo
        if step.kind == "checkout":
            script = wsl_checkout_script(run.id, combo.id, run.tar)
        elif step.kind == "python":
            script = wsl_python_script(run.id, combo.id, step.version)
        elif step.kind == "node":
            script = "node --version\n"
        else:
            script = wsl_run_script(step, run.id, combo.id, self.layout["summary"], self.venv,
                                    self.write_script(step))
        code = stream(wsl_argv(script), log, timeout=timeout, echo=echo if step.kind == "run" else None)
        if step.kind == "python" and code == 0:
            self.venv = True
        return code

    def cleanup(self, log):
        stream(wsl_argv(wsl_cleanup_script(self.run.id, self.combo.id)), log)
        remove_tree(self.layout["steps"])


class Run:
    def __init__(self, folder, run_id, tar, tools, source="", keep=False, verbose=False, step_timeout=60,
                 parallel=1):
        self.folder, self.id, self.tar, self.tools, self.source = folder, run_id, tar, tools, source
        self.keep, self.verbose, self.step_timeout, self.parallel = keep, verbose, step_timeout, parallel
        self.lock = threading.Lock()

    def say(self, text):
        with self.lock:
            print(text, flush=True)

    def combination(self, combo, index, total):
        place = (WindowsPlace if combo.place == "windows" else WslPlace)(self, combo)
        log_path = os.path.join(self.folder, combo.id + ".log")
        result = {"id": combo.id, "name": combo.name, "job": combo.job, "place": combo.place,
                  "python": combo.python, "log": log_path, "status": "ok", "seconds": 0.0, "steps": []}
        where = "Windows" if combo.place == "windows" else f"Ubuntu (WSL {DISTRO})"
        self.say(f"[{index}/{total}] {combo.name} on {where}")
        start = time.monotonic()
        failed = False
        context = {"github": {"ref": REF}, "matrix": combo.matrix, "env": {}, "runner": runner_context(combo.runs_on)}
        with open(log_path, "w", encoding="utf-8", newline="\n") as log:
            log.write(f"{combo.name}, run {self.id} on {where}\nsource: {self.source}\n\n")
            for step in combo.steps:
                entry = {"number": step.number, "name": step.name, "status": "skipped", "seconds": None,
                         "exit": None}
                result["steps"].append(entry)
                if STOP.is_set():
                    entry["status"] = "interrupted"
                    continue
                if not condition(step.condition, context, failed):
                    log.write(f"==> {step.number} {step.name}: skipped\n\n")
                    continue
                log.write(f"==> {step.number} {step.name}\n")
                log.flush()
                timeout = (step.timeout or self.step_timeout) * 60 if (step.timeout or self.step_timeout) else None
                echo = (lambda text: self.say("      " + text)) if self.verbose and self.parallel == 1 else None
                t0 = time.monotonic()
                code = place.execute(step, log, timeout, echo)
                entry.update(seconds=time.monotonic() - t0, exit=code)
                entry["status"] = "ok" if code == 0 else ("interrupted" if STOP.is_set() else "fail")
                failed = failed or code != 0
                log.write(f"<== {step.number} {entry['status']} (exit {code}) in {duration(entry['seconds'])}\n\n")
                if self.parallel == 1:
                    self.say(f"  {entry['status']:<5} {duration(entry['seconds']):>12}  {step.number} {step.name}")
            result["seconds"] = time.monotonic() - start
            statuses = {s["status"] for s in result["steps"]}
            result["status"] = ("interrupted" if "interrupted" in statuses
                                else "fail" if "fail" in statuses else "ok")
            if os.path.exists(place.layout["summary"]):
                with open(place.layout["summary"], encoding="utf-8") as fh:
                    log.write("job summary ($GITHUB_STEP_SUMMARY)\n" + fh.read() + "\n")
            log.write("step durations\n")
            for s in result["steps"]:
                log.write(f"  {s['number']:>2} {s['status']:<11} {duration(s['seconds']):>12}  {s['name']}\n")
            log.write(f"\n{combo.name}: {result['status']} in {duration(result['seconds'])}\n")
            if result["status"] == "ok" and not self.keep:
                place.cleanup(log)
        self.say(f"  -> {result['status']} in {duration(result['seconds'])}: {combo.name}, log {log_path}")
        return result


# the bilan


def bilan_exit_code(data):
    results = data.get("combinations") or []
    if any(r["status"] == "interrupted" for r in results):
        return 130
    if not results or any(r["status"] != "ok" for r in results):
        return 1
    return 0


def first_failure(result):
    for step in result.get("steps") or []:
        if step["status"] in ("fail", "interrupted"):
            return f'step {step["number"]} "{step["name"]}" (exit {step["exit"]})'
    return ""


def format_bilan(data):
    results = data.get("combinations") or []
    quick = data.get("quick") or {}
    left = quick.get("left_out") or []
    width = max([len(r["name"]) for r in results + data.get("absent", []) + left] + [10])
    mode = " (quick)" if quick and not quick.get("full_because") else ""
    lines = [f"ci-local {data['run']}{mode}: {data['source']}"]
    if quick.get("full_because"):
        lines.append("  --quick ran the whole CI: the revision changes " + ", ".join(quick["full_because"]))
    elif quick:
        lines.append(f"  --quick: {quick.get('changed', 0)} file(s) changed since the merge base with "
                     f"{quick.get('base', QUICK_BASE)}")
    for r in results:
        mark = {"ok": "ok", "fail": "FAIL", "interrupted": "STOP"}.get(r["status"], r["status"])
        line = f"  {mark:<5} {r['name'].ljust(width)}  {duration(r['seconds']):>12}"
        if r["status"] != "ok":
            line += f"  {first_failure(r)}"
        lines.append(line + f"  {r['log']}")
    for a in data.get("absent", []):
        lines.append(f"  {'--':<5} {a['name'].ljust(width)}  not run here: {a['why']}")
    for a in left:
        lines.append(f"  {'--':<5} {a['name'].ljust(width)}  left out: {a['why']}")
    bad = [r for r in results if r["status"] != "ok"]
    code = bilan_exit_code(data)
    verdict = {0: "every combination is green", 130: "interrupted"}.get(
        code, f"{len(bad)} of {len(results)} combinations not green" if results else "nothing ran")
    if mode:
        verdict = f"quick: {verdict}, {len(left)} left out"
    lines.append(f"RESULT={'OK' if code == 0 else 'FAIL'} {verdict} ({duration(data.get('seconds'))})")
    return "\n".join(lines) + "\n"


def write_bilan(folder, data):
    with open(os.path.join(folder, "bilan.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(folder, "bilan.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(format_bilan(data))


def read_bilan(folder):
    path = folder if folder.endswith(".json") else os.path.join(folder, "bilan.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# the command


def split(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def parse_args(argv):
    p = argparse.ArgumentParser(description="Replays the jobs of .github/workflows/ci.yml on this machine "
                                "(Windows, and Ubuntu through WSL).")
    p.add_argument("--jobs", help="jobs to run, e.g. test,tui,gedcom (default: all)")
    p.add_argument("--os", dest="places", help="windows,ubuntu (default: both)")
    p.add_argument("--python", help="Python versions of the matrix jobs, e.g. 3.11,3.14 (default: all)")
    p.add_argument("--rev", help="a commit to test instead of the working tree")
    p.add_argument("--work-dir", default=os.path.join(os.path.expanduser("~"), "probandia-ci"),
                   help="where run folders go (default: ~/probandia-ci)")
    p.add_argument("--parallel", type=int, default=PARALLEL,
                   help=f"combinations at a time (default {PARALLEL}; each shares its tests out between processes)")
    p.add_argument("--step-timeout", type=float, default=60, help="minutes before a step is stopped (default 60)")
    p.add_argument("--keep", action="store_true", help="keep the copies of green combinations too")
    p.add_argument("--verbose", action="store_true", help="print the output of the steps too")
    p.add_argument("--dry-run", action="store_true", help="print the combinations and their steps, run nothing")
    p.add_argument("--quick", action="store_true",
                   help="test on Windows 3.14 and Ubuntu 3.12 only, tui and gedcom when the revision changes their "
                        "files (since its merge base with master); the whole CI when it changes the CI itself, "
                        "the package or the version")
    p.add_argument("--bilan", metavar="RUN_FOLDER", help="print the bilan of a past run and exit with its code")
    args = p.parse_args(argv)
    args.jobs, args.places, args.python = split(args.jobs), split(args.places), split(args.python)
    if args.places and set(args.places) - set(PLACES):
        p.error(f"--os takes {', '.join(PLACES)}")
    if args.parallel < 1:
        p.error("--parallel takes 1 or more")
    if args.quick and (args.jobs or args.places or args.python):
        p.error("--quick chooses the combinations itself: not with --jobs, --os or --python")
    return args


def find_git_bash():
    """Git's bash, not the bash.exe of System32 (which starts WSL)."""
    git_exe = shutil.which("git")
    folder = os.path.dirname(git_exe) if git_exe else None
    for _ in range(3):
        if not folder:
            break
        candidate = os.path.join(folder, "bin", "bash.exe")
        if os.path.isfile(candidate):
            return candidate
        folder = os.path.dirname(folder)
    default = r"C:\Program Files\Git\bin\bash.exe"
    return default if os.path.isfile(default) else None


def preflight(chosen):
    """The tools the chosen combinations need; (tools, problems)."""
    problems = []
    if os.name != "nt":
        return Tools(), ["ci_local.py runs from Windows (WSL gives it Ubuntu)"]
    tools = Tools(git_bash=find_git_bash(), pwsh=shutil.which("pwsh"), uv=shutil.which("uv"),
                  node=shutil.which("node"))
    if not shutil.which("git"):
        problems.append("git is not on PATH")
    windows = [c for c in chosen if c.place == "windows"]
    if windows:
        if not tools.uv:
            problems.append("uv is not on PATH")
        if not tools.git_bash and any(s.kind == "run" and s.shell != "pwsh" for c in windows for s in c.steps):
            problems.append("Git Bash (bin/bash.exe next to git) is not found")
        if not tools.pwsh and any(s.shell == "pwsh" for c in windows for s in c.steps):
            problems.append("pwsh (PowerShell 7) is not on PATH")
        if not tools.node and any(s.kind == "node" for c in windows for s in c.steps):
            problems.append("node is not on PATH")
    if any(c.place == "ubuntu" for c in chosen):
        r = subprocess.run(wsl_argv("uv --version && git --version && tar --version | head -1"),
                           capture_output=True)
        if r.returncode:
            problems.append(f"WSL {DISTRO} with uv, git and tar does not answer: "
                            + decode(r.stdout + r.stderr).strip()[-300:])
    return tools, problems


def quick_choice(rev, combinations, root=ROOT):
    """(what --quick decided, for the bilan; the combinations to run, or None for the whole CI)."""
    try:
        changed = changed_files(rev, root)
    except RuntimeError as err:
        return {"base": QUICK_BASE, "full_because": [f"(files changed unknown: {err})"]}, None
    chosen, left, full = quick_select(combinations, changed)
    if full:
        return {"base": QUICK_BASE, "changed": len(changed), "full_because": full}, None
    return {"base": QUICK_BASE, "changed": len(changed), "left_out": left}, chosen


def quick_text(quick):
    if quick.get("full_because"):
        return "--quick: the whole CI, the revision changes " + ", ".join(quick["full_because"])
    lines = [f"--quick: {quick['changed']} file(s) changed since the merge base with {quick['base']}"]
    lines += [f"  left out: {a['name']}: {a['why']}" for a in quick["left_out"]]
    return "\n".join(lines)


def dry_run(chosen, absent, source, quick=None):
    print(f"source: {source}")
    if quick:
        print(quick_text(quick))
    for combo in chosen:
        print(f"\n{combo.name}  ->  {combo.id} on {combo.place}")
        for step in combo.steps:
            when = f"  [if: {step.condition}]" if step.condition else ""
            if step.kind == "run":
                first = step.script.strip().splitlines()[0]
                more = " ..." if len(step.script.strip().splitlines()) > 1 else ""
                print(f"  {step.number:>2} {step.name}{when}\n       {step.shell}: {first}{more}")
            else:
                print(f"  {step.number:>2} {step.name}{when}")
    for combo in absent:
        print(f"\n{combo.name}: not run here (no {combo.runs_on} on this machine)")


def main(argv=None):
    args = parse_args(argv)
    if args.bilan:
        data = read_bilan(args.bilan)
        sys.stdout.write(format_bilan(data))
        return bilan_exit_code(data)

    run_id = time.strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(os.path.abspath(args.work_dir), run_id)
    os.makedirs(folder)
    tar = os.path.join(folder, "source.tar")
    code = None   # set when nothing runs: the run folder goes away
    try:
        source, text = snapshot(args.rev, tar)
        combinations = plan(yamlio.loads(text))
        unknown = sorted(set(args.jobs or ()) - {c.job for c in combinations})
        chosen, absent = select(combinations, args.jobs, args.places, args.python)
        quick = None
        if args.quick:
            quick, quick_chosen = quick_choice(args.rev, combinations)
            chosen = quick_chosen if quick_chosen is not None else chosen
        if unknown:
            print(f"unknown job: {', '.join(unknown)}")
            code = 2
        elif args.dry_run:
            dry_run(chosen, absent, source, quick)
            code = 0
        elif not chosen:
            print("no combination matches")
            code = 2
        else:
            tools, problems = preflight(chosen)
            if problems:
                print("ci_local cannot run:\n  " + "\n  ".join(problems))
                code = 2
    except (Unsupported, RuntimeError) as err:
        print(f"ci_local: {err}")
        code = 2
    if code is not None:
        remove_tree(folder)
        return code

    run = Run(folder, run_id, tar, tools, source=source, keep=args.keep, verbose=args.verbose,
              step_timeout=args.step_timeout, parallel=args.parallel)
    print(f"ci-local {run_id}: {len(chosen)} combination(s); source: {source}\nrun folder: {folder}")
    if quick:
        print(quick_text(quick))
    data = {"run": run_id, "source": source, "folder": folder, "combinations": [], "seconds": None,
            "absent": [{"name": c.name, "why": f"no {c.runs_on} on this machine (checked at the first push)"}
                       for c in absent]}
    if quick:
        data["quick"] = quick
    start = time.monotonic()
    results = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel)
    futures = {pool.submit(run.combination, combo, i, len(chosen)): combo for i, combo in enumerate(chosen, 1)}
    try:
        for future in concurrent.futures.as_completed(futures):
            combo = futures[future]
            try:
                results[combo.id] = future.result()
            except Exception as err:   # noqa: BLE001 — a fault of this script: that combination is red
                results[combo.id] = {"id": combo.id, "name": combo.name, "status": "fail", "seconds": None,
                                     "log": os.path.join(folder, combo.id + ".log"),
                                     "steps": [{"number": 0, "name": f"ci_local.py: {type(err).__name__}: {err}",
                                                "status": "fail", "seconds": None, "exit": None}]}
            data["combinations"] = [results[c.id] for c in chosen if c.id in results]
            write_bilan(folder, data)
        pool.shutdown()
    except KeyboardInterrupt:
        STOP.set()
        for proc in list(RUNNING):
            kill(proc)
        print("\ninterrupted: stopping the running combinations")
        pool.shutdown(wait=True, cancel_futures=True)
        for future, combo in futures.items():
            if future.done() and not future.cancelled() and future.exception() is None:
                results.setdefault(combo.id, future.result())
            results.setdefault(combo.id, {"id": combo.id, "name": combo.name, "status": "interrupted",
                                          "seconds": None, "log": os.path.join(folder, combo.id + ".log"),
                                          "steps": []})
    data["combinations"] = [results[c.id] for c in chosen if c.id in results]
    data["seconds"] = time.monotonic() - start
    write_bilan(folder, data)
    if not args.keep and os.path.exists(tar):
        os.remove(tar)
    print()
    sys.stdout.write(format_bilan(data))
    return bilan_exit_code(data)


if __name__ == "__main__":
    sys.exit(main())
