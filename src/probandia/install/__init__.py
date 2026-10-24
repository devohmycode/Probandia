"""Installing Probandia into a harness.

- ``install --harness codex``: a project marketplace, plugin activation and agents.
- ``install --harness codex-agents``: Codex plugins cannot hold subagents, so
  the roles are written as custom agents in ``.codex/agents/<role>.toml``.
- ``install --harness opencode``: OpenCode has no package format; the
  installer copies skills, agents and commands, merges the MCP server into
  ``opencode.json`` and adds a small JS plugin for the hooks.

Every install records what it wrote in a manifest, so ``--uninstall`` removes
exactly that and restores the files it changed from their ``.bak`` copies. A
shared settings file (``.codex/config.toml``, ``opencode.json``) gets back its
``.bak`` only while no one else changed it; otherwise only Probandia's keys are
taken out of it (decision T11).
"""
import hashlib
import json
import os
import shutil

from probandia.errors import UsageError
from probandia.i18n import _
from probandia.install import convert
from probandia.util.fs import atomic_write_text

RECORD = ".probandia-install.json"


def _engine_root():
    """The package root, written as an absolute path with forward slashes:
    files installed outside a plugin cannot rely on a plugin root variable."""
    return convert.package_root().replace("\\", "/")


class Installer:
    def __init__(self, record_dir):
        self.record_path = os.path.join(record_dir, RECORD)
        self.written = []   # files created
        self.backups = []   # (file, backup) changed in place
        self.folders = []   # folders created
        self.notes = []     # what the install did not write, one line each (T125)
        self.previous = load_record(self.record_path)  # an earlier install, if any
        self.merged = dict(self.previous.get("merged", {}))  # shared file: {keys, sha256, edited}

    def write(self, path, text):
        ours = path in self.previous.get("written", []) or any(
            p == path for p, _b in self.previous.get("backups", []))
        if os.path.exists(path) and not ours:
            if path not in self.written and not any(p == path for p, _ in self.backups):
                bak = path + ".bak"
                shutil.copy2(path, bak)
                self.backups.append((path, bak))
        elif not os.path.exists(path) and path not in self.written:
            self.written.append(path)
        self._note_folders(os.path.dirname(path))
        atomic_write_text(path, text)

    def merge(self, path, text, keys):
        """Writes a settings file shared with the user, where Probandia owns only
        ``keys`` (paths of keys, such as ``["mcp", "probandia"]``)."""
        entry = self.merged.get(path)
        known = entry is not None or path in self.previous.get("written", []) or any(
            p == path for p, _b in self.previous.get("backups", []))
        # changed by someone since our last write (or by an install recorded before T11)
        edited = known and (entry is None or entry.get("edited") or _sha(path) != entry.get("sha256"))
        own = [list(k) for k in (entry or {}).get("keys", [])]
        own += [list(k) for k in keys if list(k) not in own]
        self.write(path, text)
        self.merged[path] = {"keys": own, "sha256": _sha(path), "edited": bool(edited)}

    def _note_folders(self, folder):
        missing = []
        while folder and not os.path.isdir(folder):
            missing.append(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        for f in missing:
            if f not in self.folders:
                self.folders.append(f)

    def save(self):
        previous = self.previous
        record = {
            "written": sorted(set(previous.get("written", []) + self.written)),
            "backups": previous.get("backups", []) + [list(b) for b in self.backups
                                                       if list(b) not in previous.get("backups", [])],
            "folders": sorted(set(previous.get("folders", []) + self.folders)),
        }
        if self.merged:
            record["merged"] = self.merged
        os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
        atomic_write_text(self.record_path, json.dumps(record, indent=2) + "\n")


def load_record(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def _sha(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return None


def _remove_keys(path, keys):
    """Takes ``keys`` out of a TOML or JSON file, and the tables they leave empty;
    returns whether anything is left in it (the file is rewritten only then)."""
    if path.endswith(".toml"):
        import tomlkit

        doc = tomlkit.parse(convert.read(path))
    else:
        doc = json.loads(convert.read(path))
    for key in keys:
        trail = [doc]
        for part in key[:-1]:
            nxt = trail[-1].get(part) if hasattr(trail[-1], "get") else None
            if nxt is None:
                break
            trail.append(nxt)
        else:
            if hasattr(trail[-1], "pop"):
                trail[-1].pop(key[-1], None)
            for i in range(len(trail) - 1, 0, -1):   # the parents we emptied
                if len(trail[i]) == 0:
                    trail[i - 1].pop(key[i - 1], None)
    if not doc:
        return False
    text = tomlkit.dumps(doc) if path.endswith(".toml") else json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text)
    return True


def uninstall(record_dir):
    """Removes what an install wrote, and restores what it changed. Returns
    (files removed, files restored)."""
    path = os.path.join(record_dir, RECORD)
    record = load_record(path)
    if not record:
        raise UsageError(_("nothing to uninstall: no install record in {folder}").format(folder=record_dir))
    removed = restored = 0
    # A shared file changed since the install keeps those changes: only our keys leave it.
    # One left untouched gets back its .bak, or is removed when the install created it.
    changed = {file: entry for file, entry in record.get("merged", {}).items()
               if os.path.exists(file) and (entry.get("edited") or _sha(file) != entry.get("sha256"))}
    for file, entry in changed.items():
        if not _remove_keys(file, entry.get("keys", [])) and file in record.get("written", []):
            os.unlink(file)   # the install created it, and nothing else is left in it
            removed += 1
        else:
            restored += 1
    for file, bak in record.get("backups", []):
        if file in changed:
            if os.path.exists(bak):
                os.unlink(bak)   # older than what the file now holds
        elif os.path.exists(bak):
            from probandia.util.fs import _replace

            _replace(bak, file)   # retried while Windows lets a reader hold the file (WinError 5, 18 Oct. 2026)
            restored += 1
    for file in record.get("written", []):
        if file not in changed and os.path.exists(file):
            os.unlink(file)
            removed += 1
    os.unlink(path)
    # The folders the install created, deepest first, if nothing else lives there.
    for folder in sorted(record.get("folders", []), key=len, reverse=True):
        try:
            os.rmdir(folder)
        except OSError:
            pass
    return removed, restored


# Codex custom agents


def install_codex_agents(project):
    """Writes ``<project>/.codex/agents/probandia-<role>.toml`` for the seven roles."""
    import tomlkit

    from probandia import roles

    inst = Installer(os.path.join(project, ".codex"))
    root = _engine_root()
    # agent-models R5: the model and the effort chosen for each role; Codex's agent file wins over any
    # value given at spawn (its docs, 12 Oct. 2026), so no hook is needed
    dropped = []
    chosen = roles.for_install(project, os.environ, "codex", dropped)
    inst.notes += roles.dropped_lines("codex", dropped)
    for role, (fm, body) in convert.agents().items():
        mine = chosen.get(role, {})
        text = convert.codex_agent(role, dict(fm, effort=mine.get("effort", fm.get("effort", "medium"))), body)
        if mine.get("model"):
            doc = tomlkit.parse(text)
            doc["model"] = mine["model"]
            text = tomlkit.dumps(doc)
        inst.write(os.path.join(project, ".codex", "agents", f"probandia-{role}.toml"),
                   text.replace("${PLUGIN_ROOT}", root))
    inst.save()
    return inst


def install_codex(project):
    """Prepare the local plugin and seven agents for a trusted Codex project."""
    import tomlkit
    from tomlkit.exceptions import TOMLKitError

    config_path = os.path.join(project, ".codex", "config.toml")
    # Validate the configuration before writing any agents or settings.
    try:
        config = (tomlkit.parse(convert.read(config_path)) if os.path.exists(config_path)
                  else tomlkit.document())
        # T222: Codex 0.161 reads no marketplace from a project's config.toml; `codex plugin marketplace add`
        # registers it in the user's, which is the user's to change: the install says the command
        plugins = config.setdefault("plugins", tomlkit.table())
        plugins.setdefault("probandia@probandia", tomlkit.table())["enabled"] = True
        config_text = tomlkit.dumps(config)
    except (ValueError, TypeError, AttributeError, TOMLKitError) as exc:
        raise UsageError(str(exc)) from exc
    inst = install_codex_agents(project)
    # ["marketplaces", "probandia"] stays among Probandia's keys: --uninstall takes it out of an older install
    inst.merge(config_path, config_text, [["marketplaces", "probandia"], ["plugins", "probandia@probandia"]])
    inst.notes.append(_("the marketplace goes in your Codex settings, which the install does not write: run "
                        "codex plugin marketplace add {root}, then codex plugin add probandia@probandia")
                      .format(root=_engine_root()))
    inst.save()
    return inst
