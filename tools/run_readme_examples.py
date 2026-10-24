"""Replays the README's examples under bash and under PowerShell (version-1.0.0 T191).

    python tools/run_readme_examples.py [--out bench/readme-1.0.0.md] [--shell bash|powershell]

Each line that starts with ``probandia`` in a ``sh`` or ``powershell`` block, and each table cell
that does, runs in a copy of ``tests/sample-project``, in the order of the README, with
``probandia`` standing for ``python run_probandia.py``. A line with a pipe runs only in the shell of
its block; any other runs in both. Nothing is spent: the settings folder is an empty one (no key),
the providers' key variables are removed from the environment, and every HTTP request goes to a
proxy that does not answer. What opens a window or waits at the keyboard is not run, and says why.

The exit code of each example goes to the report, next to the one expected, 0; exit code 0 when
every example gave it.
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FENCE = re.compile(r"^[ \t]*```([\w-]*)\n(.*?)^[ \t]*```", re.S | re.M)
SHELLS = {"sh": "bash", "bash": "bash", "powershell": "powershell"}
# by the PATH: on Windows, a bare "bash" would start the one of WSL from System32
BASH = shutil.which("bash") or "bash"
# Not run, by the start of the line: what opens a window or waits for a person.
SKIP = {
    "probandia": "the welcome screen needs a terminal (elsewhere: a usage error, 2)",
    "probandia tui": "needs an interactive terminal",
    "probandia browser": "opens a browser for a sign-in",
    "probandia report open": "opens the report in the browser",
    "probandia -r": "opens the report in the browser",
    "probandia template designer": "opens the designer in the browser",
    "probandia config wizard": "asks the settings at the keyboard",
    "probandia config edit": "opens an editor",
    "probandia keys set": "asks the key at the keyboard",
    "probandia fact check": "records what a person looked at: at a terminal only",
    "probandia close": "the research has a pass open (opened by resume above): close wants every pass ended",
}


def examples(text):
    """[(line, shells)] in the order of the README, each once."""
    out, seen = [], set()

    def add(line, shells):
        if line not in seen:
            seen.add(line)
            out.append((line, shells))

    found = [(m.start(), m.group(1), m.group(2)) for m in FENCE.finditer(text)]
    rest = FENCE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)   # the same offsets, blocks blanked
    found += [(m.start(), "table", m.group(0)) for m in re.finditer(r"^\|.*$", rest, re.M)]
    for _at, lang, body in sorted(found):
        if lang == "table":
            for cell in re.findall(r"`(probandia [^`]+)`", body):
                add(cell, ("bash", "powershell"))
            continue
        shell = SHELLS.get(lang)
        if shell is None:
            continue
        for line in body.splitlines():
            line = re.sub(r"\s+#\s.*$", "", line.strip())
            if line.split(" ")[0] == "probandia":
                add(line, (shell,) if "|" in line else ("bash", "powershell"))
    return out


def expected(line):
    for prefix, reason in SKIP.items():
        if line == prefix or (prefix != "probandia" and line.startswith(prefix + " ")):
            return None, reason
    return (0,), ""


def environment(config_dir):
    """The environment of a run: no key, no harness, no network."""
    with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as fh:
        keys = set(re.findall(r"^([A-Z0-9_]+)=", fh.read(), re.M))
    harness = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_", "CURSOR_", "DROID_", "FACTORY_", "GROK_",
               "ANTIGRAVITY_", "OPENCODE")
    env = {k: v for k, v in os.environ.items()
           if k not in keys and not k.startswith("PROBANDIA_") and not k.startswith(harness)}
    dead = "http://127.0.0.1:9"
    env.update({"PROBANDIA_CONFIG_DIR": config_dir, "PROBANDIA_SESSION": "readme-examples",
                "PROBANDIA_PAGER": "none", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8",
                "HTTP_PROXY": dead, "HTTPS_PROXY": dead, "http_proxy": dead, "https_proxy": dead,
                "NO_PROXY": "", "no_proxy": ""})
    return env


def prepare(folder):
    """A copy of the sample project, with the files its examples read: a GEDCOM file and a workshop."""
    project = os.path.join(folder, "project")
    shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), project)
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "gedcom", "tree-7.ged"), os.path.join(project, "family.ged"))
    shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "workshop"), os.path.join(folder, "my-workshop"))
    os.makedirs(os.path.join(folder, "config"))
    os.makedirs(os.path.join(folder, "out"))
    # the report rendered, as after a pass: verify's rule V-8 wants it
    subprocess.run([sys.executable, os.path.join(ROOT, "run_probandia.py"), "report", "render", "--yes"],
                   cwd=project, env=environment(os.path.join(folder, "config")), stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=300, check=True)
    return project


def script(shell, folder, project, lines):
    """The script that runs ``lines`` (index, line) and writes each exit code to out/<index>.code."""
    engine = os.path.join(ROOT, "run_probandia.py")
    out = os.path.join(folder, "out")
    if shell == "bash":
        def q(path):
            return "'" + path.replace("\\", "/") + "'"
        text = [f'probandia() {{ python {q(engine)} "$@"; }}', f"cd {q(project)}"]
        for i, line in lines:
            text += [f"{{ {line} ; }} > {q(os.path.join(out, f'{i}.txt'))} 2>&1 < /dev/null",
                     f"echo $? > {q(os.path.join(out, f'{i}.code'))}"]
        return "\n".join(text) + "\n", ".sh"

    def q(path):
        return "'" + path.replace("'", "''") + "'"
    text = [f"function probandia {{ & python {q(engine)} @args }}", f"Set-Location {q(project)}"]
    for i, line in lines:
        text += ["$global:LASTEXITCODE = 0",
                 f"& {{ {line} }} *> {q(os.path.join(out, f'{i}.txt'))}",
                 f"\"$LASTEXITCODE\" | Set-Content {q(os.path.join(out, f'{i}.code'))}"]
    return "\n".join(text) + "\n", ".ps1"


def run_shell(shell, items):
    """{index: exit code} of the examples run in ``shell``."""
    folder = tempfile.mkdtemp(prefix=f"readme-{shell}-")
    try:
        project = prepare(folder)
        lines = [(i, line) for i, (line, shells, codes, _why) in enumerate(items) if shell in shells and codes]
        text, suffix = script(shell, folder, project, lines)
        path = os.path.join(folder, "examples" + suffix)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        argv = ([BASH, path] if shell == "bash"
                else ["pwsh", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path])
        subprocess.run(argv, env=environment(os.path.join(folder, "config")), stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=1800)
        codes = {}
        for i, _line in lines:
            try:
                with open(os.path.join(folder, "out", f"{i}.code"), encoding="utf-8-sig") as fh:
                    codes[i] = int(fh.read().strip() or 0)
            except (OSError, ValueError):
                codes[i] = None
        return codes
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def version(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
    except (OSError, IndexError, subprocess.SubprocessError):
        return "not found"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "bench", "readme-1.0.0.md"))
    parser.add_argument("--shell", choices=("bash", "powershell"), action="append")
    args = parser.parse_args(argv)
    shells = args.shell or ["bash", "powershell"]
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        items = [(line, sh, *expected(line)) for line, sh in examples(fh.read())]
    results = {shell: run_shell(shell, items) for shell in shells}
    failed = 0
    rows = []
    for i, (line, sh, codes, why) in enumerate(items):
        cells = []
        for shell in ("bash", "powershell"):
            if shell not in sh:
                cells.append("not in this shell")
            elif codes is None:
                cells.append("not run")
            elif shell not in results:
                cells.append("not asked")
            else:
                got = results[shell].get(i)
                ok = got in codes
                failed += not ok
                cells.append(f"{got}" + ("" if ok else " **unexpected**"))
        want = "-" if codes is None else " or ".join(map(str, codes))
        rows.append(f"| {i + 1} | `{line}` | {cells[0]} | {cells[1]} | {want} | {why} |")
    commit = version(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"])
    head = [
        "# The README's examples, replayed (version-1.0.0 T191)",
        "",
        f"Written by `python tools/run_readme_examples.py` on {datetime.date.today().isoformat()}, at `{commit}`"
        f" (the README of the working tree), on {sys.platform}, Python {sys.version.split()[0]};"
        f" bash: {version([BASH, '--version'])}; PowerShell: {version(['pwsh', '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'])}.",
        "",
        "Each example ran in a copy of `tests/sample-project`, in the order of the README, without a key or a"
        " network (an empty settings folder, the key variables removed, a proxy that does not answer).",
        "",
        f"Result: {len(items)} examples, {failed} exit code(s) not the one expected.",
        "",
        "| # | Example | bash | PowerShell | Expected | Note |",
        "|---|---|---|---|---|---|",
    ]
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(head + rows) + "\n")
    print(f"{len(items)} examples, {failed} unexpected; written to {os.path.relpath(args.out, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
