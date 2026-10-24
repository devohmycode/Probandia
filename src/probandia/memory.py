"""The managed section of ``AGENTS.md`` (optimize.md § 5.2, decision 5.2.1).

One section, between ``<!-- probandia:begin -->`` and ``<!-- probandia:end -->``,
keeps the project's working decisions: conventions, the report template chosen,
the providers kept, the archives that need a sign-in, the user's preferences,
the known pitfalls of a source. Every harness that reads ``AGENTS.md`` loads it
at each session, so it stays short (``MAX_LINES``, ``MAX_BYTES``); the oldest
entries go to ``memory-archive.md``, which no harness loads.

Never in it: genealogical facts (they live in the family indexes), presumed-
living persons, keys and secrets. The engine never touches the text outside the
markers. Claude Code reads ``AGENTS.md`` by itself when the project has no
``CLAUDE.md``; when it has one, ``CLAUDE.md`` gets a single ``@AGENTS.md`` line,
never the section itself (it would be loaded twice).

Each entry is one line: ``- [M7] 2026-10-03 (provider) Serper for old newspapers.``
The fingerprint of the last section written is kept in ``memory.json`` (the
project's ``.probandia/`` or the user's folder), so ``doctor`` sees a section
edited by hand.
"""
import hashlib
import json
import os
import re

from probandia.errors import UsageError
from probandia.i18n import N_, _
from probandia.util.fs import atomic_write_text, iso, utc_now

BEGIN = "<!-- probandia:begin -->"
END = "<!-- probandia:end -->"
IMPORT = "@AGENTS.md"
MAX_LINES = 40          # the whole section, markers included
MAX_BYTES = 2048
MAX_ENTRY = 300         # characters of one entry
ARCHIVE = "memory-archive.md"
KINDS = ("decision", "convention", "template", "provider", "login", "preference", "pitfall")
ENTRY = re.compile(r"^- \[(M\d+)\] (\d{4}-\d{2}-\d{2})(?: \(([a-z]+)\))? (.+)$")
IMPORT_LINE = re.compile(r"^\s*@\.?/?AGENTS\.md\s*$", re.M)

# what a secret looks like, beyond the values of the known key variables
SECRET_PATTERNS = (
    re.compile(r"\b[A-Z][A-Z0-9_]*(API_KEY|TOKEN|SECRET|PASSWORD|USERNAME)\s*[=:]\s*\S+"),
    re.compile(r"\b(api[ _-]?key|token|secret|password|mot de passe|passwd)\b\s*[=:]\s*\S{4,}", re.I),
    re.compile(r"\b(sk|pk|rk|ghp|gho|xox[bp]|AIza)[-_][A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}\b"),
)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def home(environ=None):
    from probandia.learning import home as learning_home

    return learning_home(environ)


# where the section lives (5.2.1, 5.2.6)


def target(scope, project, harness=None, environ=None):
    """(the file holding the section, the CLAUDE.md that must import it or None).
    Raises UsageError where no verified file exists."""
    environ = os.environ if environ is None else environ
    if scope == "project":
        if not project:
            raise UsageError(_("the project's memory needs a project"))
        claude = os.path.join(project, "CLAUDE.md")
        return os.path.join(project, "AGENTS.md"), claude if os.path.isfile(claude) else None
    if harness == "claude-code":
        return os.path.join(home(environ), ".claude", "CLAUDE.md"), None
    if harness == "codex":
        base = environ.get("CODEX_HOME") or os.path.join(home(environ), ".codex")
        return os.path.join(base, "AGENTS.md"), None
    raise UsageError(_("no verified user file of instructions for {harness}: keep it in the project's memory")
                     .format(harness=harness or "?"))


def _state_path(scope, project, environ):
    if scope == "project":
        return os.path.join(project, ".probandia", "memory.json")
    from probandia.config import user_config_path

    return os.path.join(os.path.dirname(user_config_path(environ)), "memory.json")


def _archive_path(path, scope):
    folder = os.path.dirname(path)
    return os.path.join(folder, ARCHIVE if scope == "project" else "probandia-" + ARCHIVE)


def title(scope):
    return _("Project memory (Probandia)") if scope == "project" else _("Memory (Probandia)")


# reading


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


def spans(text):
    """[(start, end)] of each managed section, markers included; an unbalanced
    marker raises ValueError."""
    out, pos = [], 0
    while True:
        b = text.find(BEGIN, pos)
        e = text.find(END, pos)
        if b < 0 and e < 0:
            return out
        if b < 0 or (0 <= e < b):
            raise ValueError("end")
        e = text.find(END, b)
        nb = text.find(BEGIN, b + len(BEGIN))
        if e < 0 or (0 <= nb < e):
            raise ValueError("begin")
        out.append((b, e + len(END)))
        pos = e + len(END)


def entries(section):
    """The entries of a section's text, in order."""
    out = []
    for line in section.splitlines():
        m = ENTRY.match(line.strip())
        if m:
            out.append({"id": m.group(1), "date": m.group(2), "kind": m.group(3) or "decision",
                        "text": m.group(4).strip()})
    return out


def load(path):
    """(text of the file, entries of all its sections)."""
    text = read(path)
    try:
        found = spans(text)
    except ValueError:
        found = []
    out = []
    for s, e in found:
        for x in entries(text[s:e]):
            if x["id"] not in {y["id"] for y in out}:
                out.append(x)
    return text, out


def line(x):
    kind = f" ({x['kind']})" if x.get("kind") and x["kind"] != "decision" else ""
    return f"- [{x['id']}] {x['date']}{kind} {x['text']}"


def render(items, scope):
    body = [BEGIN, f"## {title(scope)}", ""]
    body += [line(x) for x in items] or [_("(no entry yet)")]
    body.append(END)
    return "\n".join(body)


def size(section):
    return len(section.splitlines()), len(section.encode("utf-8"))


def fits(section):
    lines, nbytes = size(section)
    return lines <= MAX_LINES and nbytes <= MAX_BYTES


# checks (5.2.3)


def _norm(text):
    from probandia.lang.places import key

    return " ".join(key(text).split())


def check(text, project=None, environ=None, living_years=100):
    """The reasons an entry is refused; [] when it may be written."""
    environ = os.environ if environ is None else environ
    reasons = []
    if not text.strip():
        reasons.append(_("an empty entry"))
    if "\n" in text.strip() or "\r" in text:
        reasons.append(_("an entry is a single line"))
    if len(text) > MAX_ENTRY:
        reasons.append(_("{n} characters, more than the {max} of an entry").format(n=len(text), max=MAX_ENTRY))
    if BEGIN in text or END in text:
        reasons.append(_("it holds a marker of the section"))
    if _secret(text, project, environ):
        reasons.append(_("it holds a key or a secret: keys stay in .env, never in AGENTS.md"))
    names = living_names(text, project, living_years)
    if names:
        reasons.append(_("it names a person presumed living: {names}").format(names=", ".join(names)))
    return reasons


def _secret(text, project, environ):
    from probandia.doctor import SECRET_VARIABLES
    from probandia.util.envfile import merged

    values = merged(environ, project)
    for name in SECRET_VARIABLES:
        value = str(values.get(name) or "")
        if len(value) >= 6 and value in text:
            return True
    return any(rx.search(text) for rx in SECRET_PATTERNS)


def living_names(text, project, living_years=100):
    """The presumed-living persons of every family of the project the text names."""
    if not project:
        return []
    from probandia.indexes import FamilyIndexes
    from probandia.lifecycle import families
    from probandia.report.living import names_in_query

    found = []
    for family in families(project):
        try:
            persons = FamilyIndexes(project, family).items("persons")
        except Exception:   # noqa: BLE001 — an unreadable index names nobody
            continue
        for name in names_in_query(text, persons, living_years) or []:
            if name not in found:
                found.append(name)
    return found


# writing (5.2.2)


def _next_id(items, path, scope):
    numbers = [int(x["id"][1:]) for x in items]
    numbers += [int(n) for n in re.findall(r"\[M(\d+)\]", read(_archive_path(path, scope)))]
    return f"M{max(numbers, default=0) + 1}"


def find_same(items, text):
    key = _norm(text)
    return next((x for x in items if _norm(x["text"]) == key), None)


def plan_add(path, scope, text, kind="decision", supersedes=(), now=None):
    """(new entries, the entry added, entries it replaces, unchanged). Writes nothing."""
    _text, items = load(path)
    same = find_same(items, text)
    gone = [x for x in items if x["id"] in set(supersedes)]
    missing = sorted(set(supersedes) - {x["id"] for x in items})
    if missing:
        raise UsageError(_("no entry {ids} in the memory").format(ids=", ".join(missing)))
    if same and not gone:
        return items, same, [], True
    entry = {"id": _next_id(items, path, scope), "date": iso(now or utc_now())[:10],
             "kind": kind or "decision", "text": " ".join(text.split())}
    keep = [x for x in items if x not in gone and (not same or x["id"] != same["id"])]
    return keep + [entry], entry, gone + ([same] if same and same not in gone else []), False


def compose(text, items, scope):
    """The file's new text: the first section replaced, the others removed, the
    text outside the markers untouched; a missing section goes at the end."""
    section = render(items, scope)
    try:
        found = spans(text)
    except ValueError as exc:
        raise UsageError(_("the managed section of AGENTS.md has an unmatched marker: fix it by hand, "
                           "then memory sync"), values={"REASON": f"unmatched-{exc}"})
    if not found:
        if not text.strip():
            return section + "\n"
        return text.rstrip("\n") + "\n\n" + section + "\n"
    out, pos = [], 0
    for i, (s, e) in enumerate(found):
        out.append(text[pos:s])
        if i == 0:
            out.append(section)
        else:
            # a duplicate section: removed with the blank line before it
            if out[-1].endswith("\n\n"):
                out[-1] = out[-1][:-1]
            if text[e:e + 1] == "\n":
                e += 1
        pos = e
    out.append(text[pos:])
    return "".join(out)


def write(path, items, scope, project=None, environ=None):
    """Writes the section, atomically; nothing when it is already so. Returns True
    when the file changed."""
    text = read(path)
    new = compose(text, items, scope)
    record(scope, project, environ, path, new)
    if new == text:
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    atomic_write_text(path, new)
    return True


def section_of(text):
    try:
        found = spans(text)
    except ValueError:
        return None
    return text[found[0][0]:found[0][1]] if found else None


def record(scope, project, environ, path, text):
    """Keeps the fingerprint of the section just written."""
    state = _state_path(scope, project, environ)
    data = _load_state(state)
    section = section_of(text)
    data[os.path.normcase(os.path.abspath(path))] = _sha(section) if section else None
    os.makedirs(os.path.dirname(state), exist_ok=True)
    atomic_write_text(state, json.dumps(data, indent=1, sort_keys=True) + "\n")


def _load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def archive(path, scope, items, reason, now=None):
    """Appends entries to the archive file, which no harness loads."""
    if not items:
        return None
    dest = _archive_path(path, scope)
    old = read(dest)
    head = "" if old else "# " + _("Memory archive (Probandia)") + "\n\n" + \
        _("Entries moved out of AGENTS.md: no harness loads this file.") + "\n\n"
    stamp = iso(now or utc_now())[:10]
    lines = [f"{line(x)} — {reason} {stamp}" for x in items]
    atomic_write_text(dest, (old.rstrip("\n") + "\n" if old else head) + "\n".join(lines) + "\n")
    return dest


def overflow(items, scope):
    """The oldest entries to archive so that the section fits."""
    keep, gone = list(items), []
    while keep and not fits(render(keep, scope)):
        gone.append(keep.pop(0))
    return keep, gone


# CLAUDE.md (5.2.1)


def imports(claude_path):
    return bool(IMPORT_LINE.search(read(claude_path)))


def add_import(claude_path):
    """Adds the single ``@AGENTS.md`` line; nothing when it is there."""
    text = read(claude_path)
    if IMPORT_LINE.search(text):
        return False
    atomic_write_text(claude_path, text.rstrip("\n") + ("\n\n" if text.strip() else "") + IMPORT + "\n")
    return True


# checks of doctor (5.2.7)

PROBLEMS = {
    "unmatched": N_("an unmatched marker"),
    "duplicate": N_("more than one managed section"),
    "too-big": N_("the section is over {lines} lines or {bytes} bytes"),
    "edited": N_("the section was edited by hand: run memory sync"),
    "no-import": N_("CLAUDE.md does not import AGENTS.md: run memory sync"),
    "in-claude": N_("CLAUDE.md holds a managed section too: it would be loaded twice"),
}


def problems(project, environ=None):
    """[(file, code)] of what is wrong with the project's memory."""
    if not project:
        return []
    out = []
    path, claude = target("project", project, environ=environ)
    text = read(path)
    try:
        found = spans(text)
    except ValueError:
        return [(path, "unmatched")]
    if len(found) > 1:
        out.append((path, "duplicate"))
    if found:
        section = text[found[0][0]:found[0][1]]
        if not fits(section):
            out.append((path, "too-big"))
        known = _load_state(_state_path("project", project, environ)).get(os.path.normcase(os.path.abspath(path)))
        if known and known != _sha(section):
            out.append((path, "edited"))
        if claude and not imports(claude):
            out.append((claude, "no-import"))
    if claude:
        try:
            if spans(read(claude)):
                out.append((claude, "in-claude"))
        except ValueError:
            out.append((claude, "unmatched"))
    return out


def describe(code):
    return _(PROBLEMS[code]).format(lines=MAX_LINES, bytes=MAX_BYTES)


# end of a pass (5.2.8)


def candidates(project, research_id):
    """What the engine saw in the pass that the memory could keep: archives that
    asked for a sign-in, not yet written down."""
    from probandia import logins

    path, _claude = target("project", project)
    _text, items = load(path)
    known = " ".join(_norm(x["text"]) for x in items)
    out = []
    for archive_id, rec in sorted(logins.load(project).items()):
        if rec.get("research") != research_id or rec.get("state") not in ("confirmed", "skipped", "expired"):
            continue
        if _norm(archive_id) not in known:
            out.append(("login", _("{archive} asks for a sign-in in the browser").format(archive=archive_id)))
    return out
