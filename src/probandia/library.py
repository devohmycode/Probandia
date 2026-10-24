"""The self-learning library: ``library/manifest.yaml`` (SPECS § 5.6, § 9.12).

Two scopes, searched in this order (decision 5.1.1): the project's
``library/``, then the user's, next to ``config.toml``. ``promote`` copies an
element to the user's scope and runs its witness again there; ``demote`` brings
it back to the project. The library keeps the original of each element; the
harnesses only ever receive copies.

A learned script is a Python file with an entry point ``run(args, http)``,
where ``http`` is the engine's HTTP client restricted to the script's declared
hosts, and returns rows (a list, or a dict with ``rows``). It may define
``WITNESS = {"args": {…}, "expect": {"min_results": 1}}``.

| Status | Means |
|---|---|
| ``draft`` | saved, or changed since its last test: runs inside a pass only with the user's approval |
| ``tested`` | its witness passed |
| ``trusted`` | the user accepted it (or, in grade Expert, ``library.auto_trust_after`` successful runs) |

A changed file changes its ``sha256``, and the script goes back to ``draft``.
A recipe (``kind: recipe``) is a stored query: no file, a ``query_template``,
a ``question_type``, an ``archive`` and its ``hits``.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

from probandia.errors import ProbandiaError, UsageError
from probandia.i18n import _
from probandia.util import yamlio
from probandia.util.fs import iso, parse_iso, utc_now
from probandia.util.ids import is_slug, slugify
from probandia.util.schema import validate_document

KINDS = ("connector", "helper", "recipe", "skill", "agent")
SCHEMA = 2   # the manifest's version; a version 1 manifest is read as it is and written as 2
SCOPES = ("project", "user")
FOLDERS = {"connector": "connectors", "helper": "helpers"}
TIMEOUT = 120
# What a confined run keeps of the environment, besides the declared variables.
BASE_ENV = ("SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "HOME",
            "USERPROFILE")
STOP = {"the", "a", "an", "of", "for", "and", "to", "in", "on", "de", "la", "le", "les", "des", "du", "et"}
# What would step out of the confinement (library_run.py): another process, a raw socket,
# native code, or an import the analysis cannot see.
ESCAPE_MODULES = {"subprocess", "_posixsubprocess", "multiprocessing", "socket", "_socket", "ssl", "ctypes",
                  "_ctypes", "cffi", "pty", "importlib"}
ESCAPE_OS = {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp", "startfile"}
ESCAPE_OS_PREFIXES = ("exec", "spawn")
ESCAPE_BUILTINS = {"__import__", "exec", "eval", "compile"}


class Escapes(ProbandiaError):
    """A learned script that would get round its confinement: refused before it is kept or run."""

    reason = "confinement"


def escapes(path):
    """The names in the script at ``path`` that step out of its confinement, sorted."""
    import ast

    with open(path, encoding="utf-8-sig") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as err:
        raise UsageError(_("the script is not valid Python: {error}").format(error=err)) from None
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [(a.name, None) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [(node.module or "", a.name) for a in node.names]
        else:
            mods = []
        for mod, name in mods:
            top = mod.split(".")[0]
            if top in ESCAPE_MODULES:
                found.add(mod)
            elif top == "os" and name and _os_escape(name):
                found.add(f"os.{name}")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os" \
                and _os_escape(node.attr):
            found.add(f"os.{node.attr}")
        if isinstance(node, ast.Name) and node.id in ESCAPE_BUILTINS:
            found.add(node.id)
    return sorted(found)


def _os_escape(name):
    return name in ESCAPE_OS or name.startswith(ESCAPE_OS_PREFIXES)


def refuse_escapes(path):
    names = escapes(path)
    if names:
        raise Escapes(_("the script gets round its confinement: {names}").format(names=", ".join(names)),
                      values={"IMPORTS": ",".join(names)})


def user_folder(environ=None):
    """The user's library: ``library/`` next to ``config.toml``."""
    from probandia.config import user_config_path

    return os.path.join(os.path.dirname(user_config_path(environ)), "library")


class Library:
    def __init__(self, project, now=None, scope="project", environ=None):
        self.project = project
        self.scope = scope
        self.folder = os.path.join(project, "library") if scope == "project" else user_folder(environ)
        self.path = os.path.join(self.folder, "manifest.yaml")
        self.now = now

    def clock(self):
        return self.now or utc_now()

    # the manifest

    def load(self):
        if not os.path.isfile(self.path):
            return {"schema": SCHEMA, "scripts": []}
        doc = yamlio.load(self.path) or {"schema": SCHEMA, "scripts": []}
        doc.setdefault("scripts", [])
        return doc

    def save_doc(self, doc):
        doc["schema"] = SCHEMA   # version 1 entries are valid version 2 entries
        validate_document("library", doc, "library/manifest.yaml")
        os.makedirs(self.folder, exist_ok=True)
        yamlio.dump(self.path, doc)

    def scripts(self):
        """The scripts, with a changed file sent back to ``draft`` (and the manifest saved)."""
        doc = self.load()
        changed = False
        for s in doc["scripts"]:
            if s.get("path") and s["kind"] != "recipe":
                digest = self.digest(s)
                if digest and digest != s.get("sha256"):
                    s["sha256"] = digest
                    s["status"] = "draft"
                    s["version"] = int(s.get("version") or 1) + 1
                    s["updated"] = iso(self.clock())
                    changed = True
        if changed:
            self.save_doc(doc)
        return doc["scripts"]

    def get(self, sid):
        for s in self.scripts():
            if s["id"] == sid:
                return s
        raise UsageError(_("no script {id} in the library").format(id=sid))

    def update(self, sid, **changes):
        doc = self.load()
        for s in doc["scripts"]:
            if s["id"] == sid:
                s.update(changes)
                s["updated"] = iso(self.clock())
                self.save_doc(doc)
                return s
        raise UsageError(_("no script {id} in the library").format(id=sid))

    def file(self, script):
        return os.path.join(self.folder, script["path"]) if script.get("path") else None

    def digest(self, script):
        path = self.file(script)
        if not path or not os.path.isfile(path):
            return None
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    # save

    def save(self, source, sid, kind, purpose, witness=None, hosts=(), env=(), inputs=None, outputs="",
             author=None, formats=()):
        if kind not in ("connector", "helper"):
            raise UsageError(_("a script is a connector or a helper"))
        if not is_slug(sid):
            raise UsageError(_("invalid script id {id}").format(id=sid))
        if not os.path.isfile(source):
            raise UsageError(_("no file {path}").format(path=source))
        refuse_escapes(source)
        name = os.path.basename(source)
        rel = f"{FOLDERS[kind]}/{name}"
        dest = os.path.join(self.folder, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(source) != os.path.abspath(dest):
            shutil.copy2(source, dest)
        with open(dest, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        now = iso(self.clock())
        doc = self.load()
        old = next((s for s in doc["scripts"] if s["id"] == sid), None)
        entry = {"id": sid, "kind": kind, "path": rel, "purpose": purpose, "inputs": inputs or {},
                 "outputs": outputs or "", "target": {"hosts": list(hosts), "formats": list(formats)},
                 "env": list(env), "witness": witness, "author": author or {}, "created": now, "updated": now,
                 "version": 1, "sha256": digest, "status": "draft",
                 "runs": {"ok": 0, "failed": 0, "last_ok": None}}
        if old:
            entry["created"] = old.get("created", now)
            entry["version"] = int(old.get("version") or 1) + (0 if old.get("sha256") == digest else 1)
            if old.get("sha256") == digest:
                entry["status"], entry["runs"] = old.get("status", "draft"), old.get("runs", entry["runs"])
            doc["scripts"] = [entry if s["id"] == sid else s for s in doc["scripts"]]
        else:
            doc["scripts"].append(entry)
        self.save_doc(doc)
        return entry

    # find

    def find(self, need, limit=5):
        """[(score, script)], best first: the words of the need against the purpose,
        the target, the id and the operations of each script and recipe."""
        words = _words(need)
        scored = []
        for s in self.scripts():
            text = " ".join([s["id"].replace("-", " "), s.get("purpose") or "",
                             " ".join((s.get("target") or {}).get("hosts") or []),
                             s.get("query_template") or "", s.get("question_type") or "", s.get("archive") or ""])
            have = _words(text)
            score = len(words & have) * 2 + sum(1 for w in words for h in have if len(w) > 3 and w != h
                                                 and (w in h or h in w))
            if score:
                bonus = {"trusted": 2, "tested": 1}.get(s.get("status"), 0)
                scored.append((score + bonus, s))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        return scored[:limit]

    # running

    def run(self, script, args, environ=None, timeout=TIMEOUT):
        """Runs a script confined: the environment reduced to its declared variables,
        the network to its declared hosts, ``timeout`` seconds. Returns (ok, rows, error)."""
        environ = os.environ if environ is None else environ
        path = self.file(script)
        if not path or not os.path.isfile(path):
            return False, None, "the script file is missing"
        refuse_escapes(path)   # a file changed by hand after its save
        env ={k: environ[k] for k in BASE_ENV if k in environ}
        env.update({k: environ[k] for k in script.get("env") or [] if k in environ})
        src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = src
        env["PYTHONIOENCODING"] = "utf-8"
        state = os.path.join(self.project, ".probandia") if self.project else os.path.join(self.folder, ".state")
        hosts = ",".join((script.get("target") or {}).get("hosts") or [])
        cmd = [sys.executable, "-m", "probandia.library_run", "--script", path, "--hosts", hosts,
               "--state", state, "--args", json.dumps(args or {}, ensure_ascii=False)]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8",
                                 cwd=self.project or self.folder)
        except subprocess.TimeoutExpired:
            return False, None, f"timeout after {timeout} s"
        last = (out.stdout.strip().splitlines() or [""])[-1]
        try:
            answer = json.loads(last)
        except ValueError:
            return False, None, (out.stderr.strip().splitlines() or ["no answer"])[-1][:300]
        if not answer.get("ok"):
            return False, None, answer.get("error") or "failed"
        return True, answer.get("rows"), None

    def test(self, sid, environ=None, timeout=TIMEOUT, auto_trust_after=0):
        """Runs the witness: ``tested`` when it passes, ``draft`` when it fails."""
        s = self.get(sid)
        witness = s.get("witness") or {}
        if not witness:
            return False, _("the script has no witness")
        try:
            ok, rows, error = self.run(s, witness.get("args") or {}, environ, timeout)
        except Escapes:
            self.update(sid, status="draft")
            raise
        if ok:
            expect = witness.get("expect") or {}
            n = len(rows) if isinstance(rows, list) else (1 if rows else 0)
            if n < int(expect.get("min_results", 1)):
                ok, error = False, f"{n} results, {expect.get('min_results', 1)} expected"
        runs = dict(s.get("runs") or {"ok": 0, "failed": 0, "last_ok": None})
        if ok:
            runs["ok"] = int(runs.get("ok") or 0) + 1
            runs["last_ok"] = iso(self.clock())
            status = s["status"] if s["status"] == "trusted" else "tested"
            if status == "tested" and auto_trust_after and runs["ok"] >= auto_trust_after:
                status = "trusted"
        else:
            runs["failed"] = int(runs.get("failed") or 0) + 1
            status = "draft"  # a script never runs while its witness fails
        self.update(sid, runs=runs, status=status)
        return ok, error

    def record_use(self, sid, ok=True):
        """One more use (optimize 5.1.9): ``used``, ``last_used`` and, for a skill or
        an agent, its runs (a script counts its runs when it runs)."""
        doc = self.load()
        for s in doc["scripts"]:
            if s["id"] == sid:
                now = iso(self.clock())
                s["used"] = int(s.get("used") or 0) + 1
                s["last_used"] = now
                if s.get("kind") in ("skill", "agent"):
                    runs = dict(s.get("runs") or {"ok": 0, "failed": 0, "last_ok": None})
                    runs["ok" if ok else "failed"] = int(runs.get("ok" if ok else "failed") or 0) + 1
                    if ok:
                        runs["last_ok"] = now
                    s["runs"] = runs
                self.save_doc(doc)
                return s
        return None

    def trust(self, sid):
        s = self.get(sid)
        if s["status"] == "draft":
            raise UsageError(_("{id} is a draft: test it first").format(id=sid))
        return self.update(sid, status="trusted")

    def witness_fresh(self, script, max_age_hours):
        last = (script.get("runs") or {}).get("last_ok")
        if not last:
            return False
        return (self.clock() - parse_iso(last)).total_seconds() <= max_age_hours * 3600

    # approvals of draft scripts (rule G-5)

    def approvals_path(self):
        base = os.path.join(self.project, ".probandia") if self.project else self.folder
        return os.path.join(base, "approved-scripts.json")

    def approved(self, script):
        try:
            with open(self.approvals_path(), encoding="utf-8") as fh:
                return any(a.get("id") == script["id"] and a.get("sha256") == script.get("sha256")
                           for a in json.load(fh))
        except (OSError, ValueError):
            return False

    def approve(self, script, who):
        path = self.approvals_path()
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            rows = []
        rows.append({"id": script["id"], "sha256": script.get("sha256"), "version": script.get("version"),
                     "by": who, "ts": iso(self.clock())})
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        return rows[-1]

    # recipes (PRD S-8)

    def remember_query(self, query, question_type, archive, hits, axes, author=None):
        """Stores a query that produced facts as a recipe, its axes turned into
        placeholders; an existing recipe gets its hits counted."""
        template = to_template(query, axes)
        sid = slugify(f"q-{question_type}-{archive}-{template}")[:64].rstrip("-")
        doc = self.load()
        now = iso(self.clock())
        for s in doc["scripts"]:
            if s["kind"] == "recipe" and s.get("query_template") == template and s.get("archive") == archive \
                    and s.get("question_type") == question_type:
                s["hits"] = int(s.get("hits") or 0) + int(hits or 1)
                s["updated"] = now
                self.save_doc(doc)
                return s
        entry = {"id": sid, "kind": "recipe", "path": "", "purpose": f"{question_type} query on {archive}",
                 "query_template": template, "question_type": question_type, "archive": archive,
                 "hits": int(hits or 1), "author": author or {}, "created": now, "updated": now, "version": 1,
                 "status": "tested", "runs": {"ok": 1, "failed": 0, "last_ok": now}}
        doc["scripts"].append(entry)
        self.save_doc(doc)
        return entry

    def recipes(self, question_type):
        return sorted((s for s in self.scripts() if s["kind"] == "recipe" and s.get("question_type") == question_type),
                      key=lambda s: (-int(s.get("hits") or 0), s["id"]))


# both scopes


def libraries(project, environ=None, now=None):
    """The project's library, then the user's."""
    out = [Library(project, now)] if project else []
    return out + [Library(project, now, "user", environ)]


def find_all(project, need, environ=None, limit=5, now=None):
    """[(score, script, scope)], best first, across both scopes; the project's
    element wins over a user's element of the same id."""
    seen, out = set(), []
    for lib in libraries(project, environ, now):
        for score, s in lib.find(need, limit=100):
            if s["id"] not in seen:
                seen.add(s["id"])
                out.append((score, s, lib.scope))
    out.sort(key=lambda x: (-x[0], x[2] != "project", x[1]["id"]))
    return out[:limit]


def locate(project, sid, environ=None, now=None):
    """(library, element) of ``sid``, the project's first."""
    for lib in libraries(project, environ, now):
        if any(s["id"] == sid for s in lib.load()["scripts"]):
            return lib, lib.get(sid)
    raise UsageError(_("no script {id} in the library").format(id=sid))


def _copy_element(src, dst, sid):
    """Copies an element and its file (or folder) from one library to another."""
    entry = dict(src.get(sid))
    if entry.get("path"):
        source = src.file(entry)
        target = os.path.join(dst.folder, entry["path"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.isdir(source):
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif os.path.isfile(source):
            shutil.copy2(source, target)
    entry["scope"] = dst.scope
    entry["installed"] = []
    doc = dst.load()
    doc["scripts"] = [s for s in doc["scripts"] if s["id"] != sid] + [entry]
    dst.save_doc(doc)
    return entry


def promote(project, sid, environ=None, now=None, timeout=TIMEOUT):
    """Copies a project element to the user's library and runs its witness there.
    (element, witness ok or None when it has none, error)."""
    src = Library(project, now)
    dst = Library(project, now, "user", environ)
    entry = _copy_element(src, dst, sid)
    if entry.get("witness") and entry["kind"] in ("connector", "helper"):
        ok, error = dst.test(sid, environ, timeout)
        return dst.get(sid), ok, error
    return entry, None, None


def demote(project, sid, environ=None, now=None):
    """Brings a user element back to the project, and takes it out of the user's library."""
    src = Library(project, now, "user", environ)
    dst = Library(project, now)
    entry = _copy_element(src, dst, sid)
    doc = src.load()
    doc["scripts"] = [s for s in doc["scripts"] if s["id"] != sid]
    src.save_doc(doc)
    return entry


UNUSED_DAYS = 30


def health(project, environ=None, now=None):
    """[(scope, id, problem)]: elements never used for UNUSED_DAYS days, and elements
    that fail more often than they succeed (``doctor``)."""
    now = now or utc_now()
    out = []
    for lib in libraries(project, environ, now):
        for s in lib.load()["scripts"]:
            if s.get("kind") == "recipe":
                continue
            runs = s.get("runs") or {}
            ok, failed = int(runs.get("ok") or 0), int(runs.get("failed") or 0)
            if failed > ok:
                out.append((lib.scope, s["id"], f"failing {failed}/{ok + failed}"))
                continue
            last = s.get("last_used") or runs.get("last_ok") or s.get("created")
            try:
                idle = (now - parse_iso(last)).days if last else None
            except ValueError:
                idle = None
            if not int(s.get("used") or 0) and not ok and idle is not None and idle >= UNUSED_DAYS:
                out.append((lib.scope, s["id"], f"unused for {idle} days"))
    return out


def record_use(project, name, environ=None, ok=True):
    """Counts a use of a learned element by its id, wherever it lives; None when
    no library knows it."""
    for lib in libraries(project, environ):
        if any(s["id"] == name for s in lib.load()["scripts"]):
            return lib.record_use(name, ok)
    return None


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", _fold(text)) if len(w) > 2 and w not in STOP}


def _fold(text):
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


PLACEHOLDERS = ("surname", "given", "place", "from", "to")


def to_template(query, axes):
    """``"Hugo" Besançon 1802`` -> ``"{surname}" {place} {from}``, from the plan's axes."""
    out = query
    pairs = []
    for name in axes.get("names") or []:
        pairs.append((name, "{surname}"))
    for g in axes.get("given") or []:
        pairs.append((g, "{given}"))
    for p in axes.get("places") or []:
        pairs.append((p, "{place}"))
    w = axes.get("window") or {}
    for key in ("from", "to"):
        if w.get(key):
            pairs.append((str(w[key]), "{" + key + "}"))
    for value, token in sorted(pairs, key=lambda x: -len(x[0])):
        if value:
            out = re.sub(re.escape(value), token, out, flags=re.I)
    return out


def fill(template, axes):
    w = axes.get("window") or {}
    values = {"surname": (axes.get("names") or [""])[0], "given": (axes.get("given") or [""])[0],
              "place": (axes.get("places") or [""])[0], "from": w.get("from") or "", "to": w.get("to") or ""}
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return re.sub(r"\s+", " ", out).strip()
