"""The first commit the new repository receives: the 1.0.0, alone, without the history (version-1.0.0 T212).

    python tools/release_snapshot.py --dry-run                 # HEAD's tree, checked in a local bare test repository
    python tools/release_snapshot.py --rev v1.0.0 --dry-run
    python tools/release_snapshot.py --rev v1.0.0              # the same, then a local branch `release` on the commit

It makes an orphan commit (``git commit-tree`` with no parent) from the tree of ``--rev``, pushes it into a
bare repository made in a temporary folder, and checks there:

- the commit has no parent, and the bare repository holds that commit alone: no message of the local history,
  where earlier commits name places of the author's family research, goes with it;
- its message, author and address hold no name of that research (``tests/unit/test_no_private_names.py``,
  local list included) and no agent attribution;
- its files hold none either, and nothing ignored: ``docs/``, ``private/``, ``.remember/``, ``.claude/``, ``.env``;
- ``gitleaks dir`` finds nothing in its files (``--gitleaks``, else ``GITLEAKS``, ``PATH`` or ``~/tools/gitleaks-*``).

It never pushes to a remote: the push is the user's, with the command it prints.
"""
import argparse
import glob
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORED = ("docs/", "private/", ".remember/", ".claude/")
ATTRIBUTION = re.compile(r"co-authored-by|claude|anthropic|generated with|made with|codex|copilot|cursor", re.I)


def git(*args, cwd=ROOT, env=None, data=None):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, input=data,
                          env=dict(os.environ, **(env or {})))
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:2])}: {done.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return done.stdout


def names_check():
    spec = importlib.util.spec_from_file_location(
        "no_private_names", os.path.join(ROOT, "tests", "unit", "test_no_private_names.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    return check


def version():
    with open(os.path.join(ROOT, "src", "probandia", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)


def orphan(tree, message, author, email, cwd=ROOT):
    """The SHA of a commit of ``tree`` with no parent."""
    who = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": email}
    return git("commit-tree", tree, "-m", message, cwd=cwd, env=who).decode().strip()


def alone(bare, sha):
    """None when ``sha`` has no parent and is the only commit of ``bare``; else what is wrong."""
    parents = git("rev-list", "--parents", "-n", "1", sha, cwd=bare).decode().split()[1:]
    if parents:
        return f"the commit has {len(parents)} parent(s)"
    count = int(git("rev-list", "--all", "--count", cwd=bare).decode())
    return None if count == 1 else f"the test repository holds {count} commits"


def ignored(paths):
    return [p for p in paths if p.startswith(IGNORED) or os.path.basename(p) == ".env"]


def find_gitleaks(given=None):
    for path in (given, os.environ.get("GITLEAKS"), shutil.which("gitleaks"),
                 *sorted(glob.glob(os.path.expanduser("~/tools/gitleaks-*/gitleaks*")), reverse=True)):
        if path and os.path.isfile(path) and os.path.splitext(path)[1] in ("", ".exe"):
            return path
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rev", default="HEAD", help="the commit whose tree is published (HEAD)")
    ap.add_argument("--message", help="the commit message (Version <the version of src/probandia/__init__.py>)")
    ap.add_argument("--author", help="the author's name (git config user.name)")
    ap.add_argument("--email", help="the author's address (git config user.email)")
    ap.add_argument("--gitleaks", help="the gitleaks executable")
    ap.add_argument("--dry-run", action="store_true", help="check only: no branch is made")
    a = ap.parse_args(argv)
    message = a.message or f"Version {version()}"
    author = a.author or git("config", "user.name").decode().strip()
    email = a.email or git("config", "user.email").decode().strip()
    failures = []

    def check(ok, what):
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            failures.append(what)

    names = names_check()
    local = names.local_names()
    tree = git("rev-parse", f"{a.rev}^{{tree}}").decode().strip()
    sha = orphan(tree, message, author, email)
    with tempfile.TemporaryDirectory() as tmp:
        bare = os.path.join(tmp, "test.git")
        git("init", "--bare", "-q", bare)
        git("push", "-q", bare, f"{sha}:refs/heads/master")
        wrong = alone(bare, sha)
        check(wrong is None, "one commit, no parent: nothing of the local history goes with it"
              + (f" ({wrong})" if wrong else ""))
        said = git("log", "-1", "--format=%an%n%ae%n%B", sha, cwd=bare).decode()
        found = names.scan([("commit", said)], local)
        check(not found, f"message, author and address name nothing of the family research ({message!r}, "
                         f"{author} <{email}>)" + (f": {found}" if found else ""))
        check(not ATTRIBUTION.search(said), "no agent attribution in the commit")
        paths = [p for p in git("ls-tree", "-r", "--name-only", "-z", sha, cwd=bare).decode().split("\0") if p]
        bad = ignored(paths)
        check(not bad, f"{len(paths)} files, nothing of docs/, private/, .remember/, .claude/ nor any .env"
              + (f": {bad[:5]}" if bad else ""))
        files = os.path.join(tmp, "files")
        os.makedirs(files)
        archive = os.path.join(tmp, "tree.tar")
        with open(archive, "wb") as fh:
            fh.write(git("archive", "--format=tar", sha, cwd=bare))
        with tarfile.open(archive) as tar:
            tar.extractall(files, filter="data")
        items = []
        for rel in paths:
            text = rel
            if os.path.splitext(rel)[1].lower() not in names.BINARY and os.path.isfile(os.path.join(files, rel)):
                with open(os.path.join(files, rel), "rb") as fh:
                    text += "\n" + fh.read().decode("utf-8", errors="ignore")
            items.append((rel, text))
        found = names.scan(items, local)
        check(not found, "no file names the family research" + (f": {found[:5]}" if found else "")
              + ("" if local else " (no local list: hashed names only)"))
        leaks = find_gitleaks(a.gitleaks)
        if leaks is None:
            check(False, "gitleaks: not found (--gitleaks, GITLEAKS or PATH)")
        else:
            # from the files' folder: the fingerprints of its .gitleaksignore are relative paths
            run = subprocess.run([leaks, "dir", ".", "--no-banner", "--redact", "--no-color"], cwd=files,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            check(run.returncode == 0, "gitleaks dir finds nothing"
                  + ("" if run.returncode == 0 else f": {(run.stdout + run.stderr).strip()[-500:]}"))
    if failures:
        print(f"{len(failures)} check(s) failed: nothing to push")
        return 1
    if a.dry_run:
        print(f"all checks passed on {sha[:12]} (dry run: no branch made)")
        return 0
    git("branch", "-f", "release", sha)
    print(f"all checks passed: branch `release` on {sha[:12]}; the push is yours:")
    print("    git push <the new repository> release:master")
    return 0


if __name__ == "__main__":
    sys.exit(main())
