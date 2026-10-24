"""Builds the wheel and the sdist, checks what they carry, installs the wheel in a throwaway
environment, and checks that the installed ``probandia`` command finds its data.

    python tools/check_wheel.py                    # every check
    python tools/check_wheel.py --update           # rewrites tools/package-contents.txt first
    python tools/check_wheel.py --compare <folder> # the built packages against those of <folder>
    python tools/check_wheel.py --dist <folder>    # keeps the checked packages there (release.yml)

- The wheel is built by ``pip wheel``; the sdist by the build backend ``pyproject.toml`` names
  (hatchling), installed apart as pip does for the wheel.
- The files of both are compared with the frozen list ``tools/package-contents.txt``
  (version-1.0.0 T253), ``{version}`` standing for the version: a file more or less fails, by
  name. After adding, moving or removing a file a package carries, ``--update`` rewrites the
  list; read its diff before committing it.
- The names of the author's family research (``tests/unit/test_no_private_names.py``: its
  hashes, and its local list when there is one) are looked for in the content of both packages.
- ``--compare <folder>``: the SHA-256 of the built wheel and sdist against the files of the same
  name in ``<folder>``, for instance those downloaded from PyPI once published (T227). Nothing
  is ever published from here.
- The sdist (T210) holds nothing of ``docs/``, ``.remember/``, ``private/``, ``.claude/`` nor any
  ``.env``, and installs on its own in a second environment, where ``--version`` answers.
- ``--dist <folder>``: the wheel and the sdist checked are copied there when every check passes;
  ``.github/workflows/release.yml`` publishes them.

It stays out of the test suite: building downloads the build backend (hatchling). The installed
command never sees the user's keys or settings: it runs with its own configuration and data
folders, and as a plain ``cli``. Exits 0 when every check passes, 1 otherwise.
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENTS = os.path.join(ROOT, "tools", "package-contents.txt")
KINDS = ("wheel", "sdist")
SHOWN = 20   # differences printed per package and direction
REQUIRED = (
    "probandia/_data/catalogues/providers.toml",
    "probandia/_data/catalogues/archives.yaml",
    "probandia/_data/locales/en/LC_MESSAGES/probandia.po",
    "probandia/_data/locales/fr/LC_MESSAGES/probandia.po",
    "probandia/_data/schemas/research-1.json",
    "probandia/_data/vendor-js/family-chart/family-chart.min.js",
    "probandia/_data/report-templates/default.html",
    "probandia/_data/designer/designer.js",
    "probandia/_data/designer/sample.json",
    "probandia/lang/data/given_names.tsv",
    "probandia/_vendor/vendor.txt",
)
# T204: the status (T227), the topic, the Pythons and the systems of the CI
REQUIRED_CLASSIFIERS = (
    "Development Status :: 5 - Production/Stable", "Topic :: Sociology :: Genealogy",
    *(f"Programming Language :: Python :: 3.{n}" for n in range(11, 15)),
    "Operating System :: Microsoft :: Windows", "Operating System :: POSIX :: Linux", "Operating System :: MacOS",
)
# T203: the OFL of each font report-templates/habillage.html embeds
FONT_LICENSES = tuple(f"report-templates/licenses/{name}-OFL.txt"
                      for name in ("BodoniModa", "GrenzeGotisch", "IBMPlexMono", "Spectral"))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", **kw)


def clean_environment(tmp):
    """The current environment without any Probandia setting or harness variable."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PROBANDIA_", "CLAUDE", "CODEX_", "CURSOR_", "FACTORY_", "DROID_",
                                "GROK_", "ANTIGRAVITY_", "OPENCODE"))}
    env.update(PROBANDIA_CONFIG_DIR=os.path.join(tmp, "config"),
               PROBANDIA_DATA_DIR=os.path.join(tmp, "data"),
               PROBANDIA_HARNESS="cli", PYTHONIOENCODING="utf-8")
    return env


# what a package carries


def members(path):
    """(name, bytes) of each file of a wheel (zip) or an sdist (tar.gz)."""
    if path.endswith(".whl"):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.endswith("/"):
                    yield name, z.read(name)
    else:
        with tarfile.open(path) as t:
            for m in t.getmembers():
                if m.isfile():
                    yield m.name, t.extractfile(m).read()


def contents(path, version):
    """The sorted names of a package's files, its version written ``{version}``."""
    return sorted(name.replace(f"probandia-{version}", "probandia-{version}") for name, _ in members(path))


def read_list(path=CONTENTS):
    """{kind: set of names} of the frozen list; empty sets when it is missing."""
    found, kind = {k: set() for k in KINDS}, None
    if not os.path.isfile(path):
        return found
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                kind = line[1:-1]
            elif kind in found:
                found[kind].add(line)
    return found


def write_list(lists, path=CONTENTS):
    lines = ["# The files of the built packages, checked by tools/check_wheel.py (version-1.0.0 T253).",
             "# {version} stands for the version. Rewritten by: python tools/check_wheel.py --update"]
    for kind in KINDS:
        lines += ["", f"[{kind}]"] + sorted(lists[kind])
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def differences(expected, actual):
    """(the names more than the list, the names it lists that are missing), sorted."""
    return sorted(set(actual) - set(expected)), sorted(set(expected) - set(actual))


def private_names(paths, local=None):
    """The lines ``<package>:<file>: <names>`` of the files that hold a name of the author's family
    research, read as tests/unit/test_no_private_names.py reads the tracked files; ``local``: the
    plain names, its local list by default."""
    spec = importlib.util.spec_from_file_location(
        "no_private_names", os.path.join(ROOT, "tests", "unit", "test_no_private_names.py"))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    items = []
    for path in paths:
        for name, data in members(path):
            text = name
            if os.path.splitext(name)[1].lower() not in check.BINARY:
                text += "\n" + data.decode("utf-8", errors="ignore")
            items.append((f"{os.path.basename(path)}:{name}", text))
    return check.scan(items, check.local_names() if local is None else local)


def relative_links(text):
    """The targets of the Markdown links of ``text`` that are neither a URL nor an anchor."""
    return [t for t in re.findall(r"\]\(([^)\s]+)\)", text) if not re.match(r"[a-z][a-z0-9+.-]*:|#", t)]


def metadata_lines():
    """The lines the wheel's METADATA must hold: the licence of pyproject.toml (version-1.0.0 T202), the
    third-party notices (T203), the classifiers T204 requires and every address of [project.urls]."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        project = tomllib.load(fh)["project"]
    return ([f"License-Expression: {project['license']}", "License-File: LICENSE",
             "License-File: THIRD-PARTY-NOTICES"] + [f"License-File: {f}" for f in FONT_LICENSES]
            + [f"Classifier: {c}" for c in REQUIRED_CLASSIFIERS]
            + [f"Project-URL: {name}, {url}" for name, url in project["urls"].items()])


def installed_files(python):
    """The files of the probandia distribution installed for ``python``, as importlib.metadata lists them."""
    code = ("import importlib.metadata as m; d = m.distribution('probandia'); "
            "print('\\n'.join(str(f).replace(chr(92), '/') for f in d.files if d.locate_file(f).is_file()))")
    return set(run([python, "-c", code]).stdout.split("\n"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# building


def build_wheel(dist):
    r = run([sys.executable, "-m", "pip", "wheel", ROOT, "--no-deps", "-w", dist])
    found = glob.glob(os.path.join(dist, "probandia-*.whl"))
    return (found[0] if not r.returncode and found else None), r


def build_sdist(tmp, dist):
    """The sdist, by the build backend of pyproject.toml installed in a folder of its own."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        system = tomllib.load(fh)["build-system"]
    backend = os.path.join(tmp, "backend")
    r = run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-warn-conflicts",
             "--ignore-installed", "--target", backend, *system["requires"]])
    if r.returncode:
        return None, r
    code = "import importlib, sys; print(importlib.import_module(sys.argv[1]).build_sdist(sys.argv[2]))"
    r = run([sys.executable, "-c", code, system["build-backend"], dist], cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=backend))
    found = glob.glob(os.path.join(dist, "probandia-*.tar.gz"))
    return (found[0] if not r.returncode and found else None), r


def install(venv, package, *options):
    """(python, the probandia command) of a new virtual environment where ``package`` is installed;
    (None, None) when it does not install. An sdist is built by pip, with the backend of its pyproject.toml."""
    run([sys.executable, "-m", "venv", venv], check=True)
    bindir = os.path.join(venv, "Scripts" if os.name == "nt" else "bin")
    python = os.path.join(bindir, "python")
    r = run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", *options, package])
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
        return None, None
    return python, shutil.which("probandia", path=bindir)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true", help="rewrite tools/package-contents.txt from the built packages")
    ap.add_argument("--compare", metavar="<folder>",
                    help="compare the SHA-256 of the built packages with the files of the same name in <folder>")
    ap.add_argument("--dist", metavar="<folder>",
                    help="copy the built wheel and sdist into <folder> when every check passes (release.yml)")
    args = ap.parse_args(argv)
    failures = []

    def check(ok, what):
        print(("ok    " if ok else "FAIL  ") + what)
        if not ok:
            failures.append(what)

    with tempfile.TemporaryDirectory() as tmp:
        dist = os.path.join(tmp, "dist")
        wheel, build = build_wheel(dist)
        if wheel is None:
            print(build.stdout[-2000:], build.stderr[-2000:])
            print("FAIL  the wheel was not built")
            return 1
        sdist, build = build_sdist(tmp, dist)
        if sdist is None:
            print(build.stdout[-2000:], build.stderr[-2000:])
            print("FAIL  the sdist was not built")
            return 1
        version = os.path.basename(wheel).split("-")[1]
        names = set(zipfile.ZipFile(wheel).namelist())
        for member in REQUIRED:
            check(member in names, f"wheel carries {member}")

        # T253: exactly the frozen list, and no private name inside
        built = {"wheel": contents(wheel, version), "sdist": contents(sdist, version)}
        if args.update:
            write_list(built)
            print(f"wrote {os.path.relpath(CONTENTS, ROOT)}: {len(built['wheel'])} files in the wheel, "
                  f"{len(built['sdist'])} in the sdist")
        frozen = read_list()
        stale = False
        for kind in KINDS:
            more, missing = differences(frozen[kind], built[kind])
            stale = stale or bool(more or missing)
            for name in more[:SHOWN]:
                check(False, f"{kind} carries {name}, which tools/package-contents.txt does not list")
            for name in missing[:SHOWN]:
                check(False, f"{kind} lacks {name}, which tools/package-contents.txt lists")
            for n, what in ((len(more) - SHOWN, "more"), (len(missing) - SHOWN, "missing")):
                if n > 0:
                    check(False, f"{kind}: {n} other files {what}")
            if not (more or missing):
                check(True, f"{kind} carries the {len(built[kind])} files of tools/package-contents.txt")
        if stale:
            print("      a file added, moved or removed on purpose: python tools/check_wheel.py --update, "
                  "then read git diff tools/package-contents.txt")
        # T190: PyPI shows the README from METADATA, where a relative link leads nowhere
        with zipfile.ZipFile(wheel) as zf:
            metadata = zf.read(f"probandia-{version}.dist-info/METADATA").decode("utf-8")
        headers = metadata.split("\n\n", 1)[0].splitlines()
        for line in metadata_lines():
            check(line in headers, f"the wheel's METADATA has {line}")
        relative = relative_links(metadata)
        check(not relative, "the wheel's description has no relative link"
              + (f": {', '.join(relative[:SHOWN])}" if relative else ""))
        found = private_names([wheel, sdist])
        for line in found[:SHOWN]:
            check(False, f"a name of the author's family research in {line}")
        if not found:
            check(True, "no name of the author's family research in the wheel nor in the sdist")
        for path in (wheel, sdist):
            print(f"      sha256 {sha256(path)}  {os.path.basename(path)}")
        if args.compare:
            for path in (wheel, sdist):
                other = os.path.join(args.compare, os.path.basename(path))
                if not os.path.isfile(other):
                    check(False, f"{os.path.basename(path)} is not in {args.compare}")
                else:
                    check(sha256(other) == sha256(path), f"{os.path.basename(path)}: the same SHA-256 as {other}")

        # T210: the sdist holds no local note, installs on its own and runs
        local = [n for n in built["sdist"] if n.endswith("/.env") or n.startswith(
            tuple("probandia-{version}/" + d for d in ("docs/", ".remember/", "private/", ".claude/")))]
        check(not local, "the sdist has nothing of docs/, .remember/, private/, .claude/ nor any .env"
              + (f": {', '.join(local[:SHOWN])}" if local else ""))
        python, exe = install(os.path.join(tmp, "venv-sdist"), sdist)
        r = run([exe, "--version"], cwd=tmp, env=clean_environment(tmp)) if exe else None
        check(r is not None and r.stdout.strip() == f"probandia {version}", f"the sdist installs and says {version}")

        python, exe = install(os.path.join(tmp, "venv"), wheel, "--no-index")
        check(python is not None, "the wheel installs")
        check(exe is not None, "the probandia command is installed")
        if exe is None:
            return 1
        files = installed_files(python)
        for name in (f"probandia-{version}.dist-info/licenses/THIRD-PARTY-NOTICES",
                     *(f"probandia/_data/{f}" for f in FONT_LICENSES)):
            check(name in files, f"the installed wheel has {name}")

        env = clean_environment(tmp)
        sample = os.path.join(tmp, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), sample)

        def engine(*args, cwd=tmp):
            r = run([exe, *args, "--json"], cwd=cwd, env=env)
            try:
                return json.loads(r.stdout)
            except ValueError:
                return {"status": "FAIL", "values": {}, "lines": [r.stdout[-500:], r.stderr[-500:]]}

        r = run([exe, "--version"], cwd=tmp, env=env)
        check(r.stdout.strip() == f"probandia {version}", f"--version says {version}")
        doctor = engine("doctor")
        check(doctor["values"].get("CATALOGUE") not in (None, "absent"),
              f"doctor reads the provider catalogue (CATALOGUE={doctor['values'].get('CATALOGUE')})")
        check(engine("variants", "Hugo")["status"] == "OK", "variants Hugo")
        dates = engine("dates", "3 nivôse an XII")
        check(dates["values"].get("ISO") == "1803-12-25", "dates reads the French Republican calendar")
        quota = engine("quota", "show", cwd=sample)
        check(quota["status"] in ("OK", "WARN"), f"quota show in the sample project ({quota['status']})")
        tree = engine("tree", cwd=sample)
        check(tree["status"] in ("OK", "WARN"), f"tree in the sample project ({tree['status']})")
        example = run([exe, "propose", "--example", "facts"], cwd=sample, env=env)
        check(example.stdout.startswith("facts:\n"), "propose --example reads schemas/examples/")
        if args.dist and not failures:   # release.yml publishes exactly the packages checked here
            os.makedirs(args.dist, exist_ok=True)
            for path in (wheel, sdist):
                shutil.copy2(path, args.dist)
            print(f"      copied {os.path.basename(wheel)} and {os.path.basename(sdist)} to {args.dist}")

    print(f"\n{len(failures)} failure(s)" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
