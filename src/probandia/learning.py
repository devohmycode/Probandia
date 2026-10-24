"""Learned skills and sub-agents: drafted, checked, approved, installed (optimize.md 5.1).

The loop: the end of a pass spots the **candidates** (``candidates``); the agent
**drafts** a ``SKILL.md`` or an agent file into the library (``draft``), which
the engine **checks** (format, size, no instruction against the rules); the user
**approves**; ``install`` puts **copies** where each harness reads them, and
records them so that ``uninstall`` removes exactly those (decision 5.1.1). The
library keeps the original. Names start with ``probandia-``, so a learned
element never overwrites the user's own.

| Kind | Scope | Harness | Where the copy goes |
|---|---|---|---|
| skill | project | claude-code | ``.claude/skills/<name>/`` |
| skill | project | the others | ``.agents/skills/<name>/`` |
| skill | user | claude-code | ``~/.claude/skills/<name>/`` |
| skill | user | codex, opencode | ``~/.agents/skills/<name>/`` |
| agent | project | claude-code, cursor, droid, codex | ``.claude/agents/``, ``.cursor/agents/``, ``.factory/droids/``, ``.codex/agents/`` |
| agent | user | the same | ``~/.claude/agents/``, ``~/.cursor/agents/``, ``~/.factory/droids/``, ``~/.codex/agents/`` |

A project skill goes to both folders: Claude Code does not read ``.agents/``.
A user skill and an agent go to the harness that runs the command only. The
other user folders are not verified yet: install those at project scope.
"""
import hashlib
import json
import os
import re
import zipfile

from probandia.errors import UsageError
from probandia.i18n import N_, _
from probandia.util.fs import iso, utc_now

PREFIX = "probandia-"
MAX_BYTES = {"skill": 4096, "agent": 4096}
HARNESSES = ("claude-code", "codex", "cursor", "droid", "grok", "antigravity", "opencode")

# (pattern, reason): what a learned skill or agent may never tell an agent to do.
FORBIDDEN = (
    (re.compile(r"\b(pay|paid|purchase|buy|credit card|carte bancaire|payer|upgrade to (a )?paid)\b", re.I),
     N_("it would pay for something: Probandia never pays (PRD § 3)")),
    (re.compile(r"(PROBANDIA_HOOKS_GUARD|hooks\.guard|\b(bypass|disable|turn off|skip|avoid|contourne\w*|d[eé]sactive\w*)"
                r"\b[^.\n]{0,30}\b(guard|garde-fou|hook)s?\b)", re.I),
     N_("it would bypass the guard")),
    (re.compile(r"--no-verify|\bcaptcha\b|anti-?bot|stealth|residential prox", re.I),
     N_("it would use an anti-bot option or skip a check (decision 1.1)")),
    (re.compile(r"\b(conclude|assert|record|promote|mark|state)\w*\b[^.\n]{0,60}\bwithout (a |any )?"
                r"(source|proof|citation|witness|record)\b", re.I),
     N_("it would conclude without proof")),
    (re.compile(r"\b(write|edit|modify|append|change|overwrite|delete)\w*\b[^.\n]{0,50}"
                r"(families/\S*index|events\.jsonl|research\.yaml|report/)", re.I),
     N_("it would write the indexes, the events or the report itself, not through the engine")),
)


def home(environ=None):
    environ = os.environ if environ is None else environ
    return (environ.get("USERPROFILE") if os.name == "nt" else environ.get("HOME")) or \
        environ.get("HOME") or environ.get("USERPROFILE") or os.path.expanduser("~")


# checks (5.1.5, 5.1.6)


def _front_matter(text):
    from probandia.install.convert import split_front_matter

    try:
        return split_front_matter(text)
    except (ValueError, Exception):   # a broken header is a reason, not a crash
        return None, text


def check(kind, text, name):
    """The reasons a learned skill or agent is refused; [] when it passes."""
    reasons = []
    if not name.startswith(PREFIX) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        reasons.append(_("its name must start with {prefix} and be a slug: {name}").format(prefix=PREFIX, name=name))
    size = len(text.encode("utf-8"))
    if size > MAX_BYTES[kind]:
        reasons.append(_("{size} bytes, more than the {max} allowed").format(size=size, max=MAX_BYTES[kind]))
    fm, body = _front_matter(text)
    if not fm:
        reasons.append(_("no YAML header (--- name, description ---)"))
    else:
        if fm.get("name") != name:
            reasons.append(_("the header's name is {got}, not {name}").format(got=fm.get("name"), name=name))
        if not str(fm.get("description") or "").strip():
            reasons.append(_("no description: it says when to use it"))
        if kind == "agent" and fm.get("effort") and fm["effort"] not in ("low", "medium", "high", "xhigh", "max"):
            reasons.append(_("unknown effort {effort}").format(effort=fm["effort"]))
    if not (body or "").strip():
        reasons.append(_("an empty body"))
    for rx, why in FORBIDDEN:
        m = rx.search(text)
        if m:
            reasons.append(f"{_(why)}: \"{m.group(0).strip()}\"")
    return reasons


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def draft(lib, kind, source, name, purpose, trigger="", harnesses=(), author=None, now=None):
    """Checks a skill or agent file and stores it in the library as a draft.
    Raises UsageError with the reasons when the check refuses it."""
    if kind not in ("skill", "agent"):
        raise UsageError(_("a learned element is a skill or an agent"))
    if not os.path.isfile(source):
        raise UsageError(_("no file {path}").format(path=source))
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    reasons = check(kind, text, name)
    if reasons:
        raise UsageError(_("the {kind} {name} is refused").format(kind=kind, name=name), lines=reasons,
                         values={"REASON": "refused"})
    fm, _body = _front_matter(text)
    rel = f"skills/{name}/SKILL.md" if kind == "skill" else f"agents/{name}.md"
    dest = os.path.join(lib.folder, *rel.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    stamp = iso(now or utc_now())
    doc = lib.load()
    old = next((s for s in doc["scripts"] if s["id"] == name), None)
    digest = _sha(text)
    entry = {"id": name, "kind": kind, "path": rel, "purpose": purpose or str(fm.get("description") or ""),
             "trigger": trigger or str(fm.get("description") or ""), "scope": lib.scope,
             "harnesses": list(harnesses) or list(HARNESSES), "tools": _tools(fm), "author": author or {},
             "created": (old or {}).get("created", stamp), "updated": stamp,
             "version": 1 if not old else int(old.get("version") or 1) + (0 if old.get("sha256") == digest else 1),
             "sha256": digest, "status": "draft", "installed": list((old or {}).get("installed") or []),
             "used": int((old or {}).get("used") or 0), "last_used": (old or {}).get("last_used"),
             "runs": dict((old or {}).get("runs") or {"ok": 0, "failed": 0, "last_ok": None})}
    if kind == "agent":
        entry["model"] = fm.get("model")
        entry["effort"] = fm.get("effort")
    doc["scripts"] = [s for s in doc["scripts"] if s["id"] != name] + [entry]
    lib.save_doc(doc)
    return entry


def _tools(fm):
    from probandia.install.convert import tools_list

    value = fm.get("tools")
    return value if isinstance(value, list) else tools_list(value)


# formats of a learned agent (5.1.6)


def agent_formats(text):
    """{harness: (file name suffix, text)}: the Claude Code original, converted
    for Cursor, Factory Droid and Codex by the plugin's own converters."""
    from probandia.install import convert, manifests

    fm, body = convert.split_front_matter(text)
    role = str(fm.get("name", "")).removeprefix(PREFIX)
    out = {"claude-code": (".md", text),
           "cursor": (".md", manifests.cursor_agent(role, fm, body)),
           "droid": (".md", manifests.droid_agent(role, fm, body))}
    try:
        out["codex"] = (".toml", convert.codex_agent(role, fm, body))
    except ImportError:   # tomlkit missing: no Codex format
        pass
    return out


# where copies go (5.1.8)

SKILL_DIRS = {"project": {"claude-code": ".claude/skills", "*": ".agents/skills"},
              "user": {"claude-code": ".claude/skills", "codex": ".agents/skills", "opencode": ".agents/skills"}}
AGENT_DIRS = {"claude-code": ".claude/agents", "cursor": ".cursor/agents", "droid": ".factory/droids",
              "codex": ".codex/agents"}
GUARDED = (".claude/skills", ".claude/agents", ".agents/skills", ".cursor/agents", ".factory/droids",
           ".codex/agents", ".opencode/agents")


def targets(entry, scope, harness, project, environ=None):
    """[(absolute path, text)] of the copies to write. Raises UsageError where no
    verified location exists."""
    base = project if scope == "project" else home(environ)
    if scope == "project" and not project:
        raise UsageError(_("a project install needs a project"))
    lib_file = entry["_file"]
    with open(lib_file, encoding="utf-8") as fh:
        text = fh.read()
    name = entry["id"]
    if entry["kind"] == "skill":
        if scope == "project":
            folders = [SKILL_DIRS["project"]["claude-code"], SKILL_DIRS["project"]["*"]]
        else:
            folder = SKILL_DIRS["user"].get(harness)
            if folder is None:
                raise UsageError(_("no verified user folder for skills in {harness}: install it at project scope")
                                 .format(harness=harness))
            folders = [folder]
        return [(os.path.join(base, *f.split("/"), name, "SKILL.md"), text) for f in folders]
    folder = AGENT_DIRS.get(harness)
    if folder is None:
        raise UsageError(_("no verified folder for agents in {harness}").format(harness=harness))
    formats = agent_formats(text)
    if harness not in formats:
        raise UsageError(_("no agent format for {harness}").format(harness=harness))
    suffix, converted = formats[harness]
    return [(os.path.join(base, *folder.split("/"), name + suffix), converted)]


def install(lib, sid, scope, harness, project, environ=None, now=None):
    """Writes the copies and records them. Refuses to overwrite a file it did not write."""
    from probandia.util.fs import atomic_write_text

    entry = dict(lib.get(sid))
    if entry["kind"] not in ("skill", "agent"):
        raise UsageError(_("only a skill or an agent is installed; a script runs from the library"))
    entry["_file"] = lib.file(entry)
    planned = targets(entry, scope, harness, project, environ)
    recorded = {p for i in entry.get("installed") or [] for p in i.get("paths") or []}
    for path, _text in planned:
        if os.path.exists(path) and path not in recorded:
            raise UsageError(_("{path} exists and was not written by Probandia: nothing installed").format(path=path))
    for path, text in planned:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_text(path, text)
    installed = [i for i in entry.get("installed") or [] if not (i["harness"] == harness and i["scope"] == scope)]
    installed.append({"harness": harness, "scope": scope, "paths": [p for p, _t in planned],
                      "sha256": entry.get("sha256") or "", "ts": iso(now or utc_now())})
    lib.update(sid, installed=installed)
    return [p for p, _t in planned]


def uninstall(lib, sid, harness=None, scope=None):
    """Removes exactly the recorded copies (and the folders it made empty)."""
    entry = lib.get(sid)
    removed, kept = [], []
    for i in entry.get("installed") or []:
        if (harness and i["harness"] != harness) or (scope and i["scope"] != scope):
            kept.append(i)
            continue
        for path in i.get("paths") or []:
            if os.path.isfile(path):
                os.remove(path)
                removed.append(path)
            folder = os.path.dirname(path)
            if entry["kind"] == "skill" and os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)
    lib.update(sid, installed=kept)
    return removed


def preview(lib, sid, scope, harness):
    """What the user approves: the element, where it goes, and what changed since
    the copy installed there (``new``, ``same``, or ``changed``)."""
    entry = lib.get(sid)
    before = next((i for i in entry.get("installed") or [] if i["harness"] == harness and i["scope"] == scope), None)
    if before is None:
        change = "new"
    elif before.get("sha256") == entry.get("sha256"):
        change = "same"
    else:
        change = "changed"
    return {"KIND": entry["kind"], "PURPOSE": entry.get("purpose", ""), "TRIGGER": entry.get("trigger", ""),
            "SCOPE": scope, "HARNESS": harness, "STATE": entry["status"], "VERSION": entry.get("version", 1),
            "CHANGE": change}


# candidates at the end of a pass (5.1.4)

REPEATS = 3   # the same archive operation, or the same host in the browser, this many times


def candidates(project, research, pass_no, environ=None):
    """[(kind, detail)]: what the pass did that the library could keep."""
    from collections import Counter
    from urllib.parse import urlparse

    from probandia.indexes import FamilyIndexes
    from probandia.library import Library, libraries

    out = []
    known = {s.get("sha256") for lib in libraries(project, environ) for s in lib.load()["scripts"]}
    for folder, _dirs, files in os.walk(research.work):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(folder, f)
                with open(path, "rb") as fh:
                    if hashlib.sha256(fh.read()).hexdigest() not in known:
                        out.append(("script", os.path.relpath(path, project).replace(os.sep, "/")))
    ops = Counter()
    for s in FamilyIndexes(project, research.family).items("searches"):
        if s.get("research") == research.id and s.get("pass") == pass_no and s.get("kind") == "archive":
            ops[f"{s.get('engine')}.{str(s.get('query', '')).split(' ', 1)[0]}"] += 1
    out += [("helper", f"{op} x{n}") for op, n in sorted(ops.items()) if n >= REPEATS]
    hosts = Counter()
    for root in (os.path.join(project, ".probandia", "cache"), os.path.join(research.work, "cache")):
        for folder, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(folder, f), encoding="utf-8") as fh:
                            entry = json.load(fh)
                    except (OSError, ValueError):
                        continue
                    # not every file of the cache is a response: small-images.json is a list (J10; it
                    # stopped pass end at the bench of I3, 12 Oct. 2026)
                    payload = (entry.get("payload") or {}) if isinstance(entry, dict) else {}
                    if isinstance(payload, dict) and payload.get("step") == "browser":
                        hosts[urlparse(str(payload.get("final_url") or "")).hostname or "?"] += 1
    out += [("skill", f"{h} read {n} times in the browser") for h, n in sorted(hosts.items()) if n >= REPEATS]
    user = {s["id"] for s in Library(project, scope="user", environ=environ).load()["scripts"]}
    for s in Library(project).load()["scripts"]:
        if s.get("kind") == "recipe" and int(s.get("hits") or 0) >= REPEATS and s["id"] not in user:
            out.append(("promote", f"{s['id']} ({s.get('hits')} hits)"))
    return out


# sharing (5.1.10)


def export(project, ids, path, environ=None):
    """A portable lot: ``manifest.yaml`` with the elements, their files, and their fingerprints."""
    from probandia.library import locate
    from probandia.util import yamlio

    entries = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for sid in ids:
            lib, entry = locate(project, sid, environ)
            entry = {k: v for k, v in entry.items() if k != "installed"}
            if entry.get("path"):
                source = lib.file(entry)
                with open(source, "rb") as fh:
                    data = fh.read()
                z.writestr(entry["path"], data)
                entry["sha256"] = hashlib.sha256(data).hexdigest()
            entries.append(entry)
        z.writestr("manifest.yaml", yamlio.dumps({"schema": 2, "scripts": entries}))
    return entries


def import_lot(lib, path, origin="", now=None):
    """Imports a lot into ``lib``: each element back to ``draft``, its file checked
    against its fingerprint. Returns the entries imported."""
    from probandia.util import yamlio
    from probandia.util.schema import validate_document

    with zipfile.ZipFile(path) as z:
        doc = yamlio.loads(z.read("manifest.yaml").decode("utf-8"))
        validate_document("library", doc, os.path.basename(path))
        current = lib.load()
        imported = []
        for entry in doc["scripts"]:
            if entry.get("path"):
                rel = entry["path"]
                if rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
                    raise UsageError(_("{path}: a path outside the library: {rel}").format(path=path, rel=rel))
                data = z.read(rel)
                if entry.get("sha256") and hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise UsageError(_("{rel} does not match its fingerprint: nothing imported").format(rel=rel))
                if entry["kind"] in ("skill", "agent"):
                    reasons = check(entry["kind"], data.decode("utf-8"), entry["id"])
                    if reasons:
                        raise UsageError(_("the {kind} {name} is refused").format(kind=entry["kind"],
                                                                                   name=entry["id"]), lines=reasons)
                target = os.path.join(lib.folder, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as fh:
                    fh.write(data)
            entry = dict(entry, status="draft" if entry["kind"] != "recipe" else entry.get("status", "tested"),
                         scope=lib.scope, installed=[], imported={"from": origin or os.path.basename(path),
                                                                 "ts": iso(now or utc_now())})
            current["scripts"] = [s for s in current["scripts"] if s["id"] != entry["id"]] + [entry]
            imported.append(entry)
        lib.save_doc(current)
    return imported
