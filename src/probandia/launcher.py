"""The short way to call the engine from a project, and the harness options it
remembers, so that agents no longer write either at every call.

- ``.probandia/pb.py`` runs the plugin's ``run_probandia.py``: an agent calls
  ``python .probandia/pb.py <command>`` from the project root instead of the
  plugin's absolute path. Each plugin's engine that runs in the project adds
  itself, with its version; the newest one that still exists runs (T260: a project
  passed from one harness to another kept the first harness's older engine, under
  the newer skills of the next one).
- ``.probandia/harness-options.json`` keeps the plugin options of the harness,
  per session: Claude Code exports them to its hooks (``CLAUDE_PLUGIN_OPTION_<KEY>``),
  and a command that still passes ``--harness-options`` updates them. A command
  without ``--harness-options`` takes those of its session, else the latest ones:
  they stay the second layer of the settings.
"""
import json
import os

from probandia.config import registry
from probandia.util.fs import atomic_write_json, iso, utc_now

LAUNCHER = "pb.py"
OPTIONS_FILE = "harness-options.json"
TEMPLATE = '''"""Probandia: the short way to call the engine from this project.

    python .probandia/pb.py <command> [arguments]

Written by the engine: each plugin's engine that runs here adds itself, and the
newest one that still exists runs. Do not edit."""
import os
import runpy
import sys

ENGINES = {engines!r}
ENGINE = next((path for _version, path in ENGINES if os.path.isfile(path)), ENGINES[0][1])
sys.argv[0] = ENGINE
runpy.run_path(ENGINE, run_name="__main__")
'''


def engine_path():
    from probandia.install.convert import package_root

    return os.path.join(package_root(), "run_probandia.py")


def _version_key(version):
    return tuple(int(part) if part.isdigit() else 0 for part in str(version or "0").split("."))


def known_engines(path):
    """The ``[version, path]`` pairs a ``pb.py`` lists; one of version "0" for an older launcher's ``ENGINE``."""
    import ast

    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    for line in text.splitlines():
        name, sep, value = line.partition(" = ")
        if sep and name in ("ENGINES", "ENGINE"):
            try:
                found = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return []
            return [["0", found]] if name == "ENGINE" else [list(pair) for pair in found]
    return []


def write_launcher(project, engine=None, version=None):
    """Adds this engine to ``.probandia/pb.py``, keeping the others that still exist, the newest first.
    Returns its path, or None when there is no ``run_probandia.py`` to point at (an installed wheel)."""
    from probandia import __version__

    engine = engine or engine_path()
    if not os.path.isfile(engine):
        return None
    path = os.path.join(project, ".probandia", LAUNCHER)
    others = [[v, p] for v, p in known_engines(path)
              if os.path.normcase(p) != os.path.normcase(engine) and os.path.isfile(p)]
    engines = sorted(others + [[version or __version__, engine]], key=lambda pair: _version_key(pair[0]),
                     reverse=True)
    text = TEMPLATE.format(engines=engines)
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return path
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def from_environment(environ):
    """The ``k=v;…`` text of the plugin options a harness exported to a hook
    (``CLAUDE_PLUGIN_OPTION_<KEY>``), or None when it exported none."""
    pairs = []
    for s in registry.harness_settings():
        value = environ.get("CLAUDE_PLUGIN_OPTION_" + s.harness_key.upper())
        if value is not None:
            pairs.append(f"{s.harness_key}={value}")
    return ";".join(pairs) if pairs else None


def has_values(text):
    """True when at least one option was substituted by the harness."""
    from probandia.config import parse_harness_options

    try:
        return bool(parse_harness_options(text))
    except Exception:  # noqa: BLE001 — a malformed text is reported where it is used
        return False


def _file(project):
    return os.path.join(project, ".probandia", OPTIONS_FILE)


def remember(project, text, session, clock=utc_now):
    """Keeps the options of a session (only when the harness filled some)."""
    if not text or not has_values(text):
        return False
    try:
        with open(_file(project), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    sessions = data.get("sessions") or {}
    if sessions.get(session, {}).get("options") == text and data.get("latest") == session:
        return False
    sessions[session] = {"options": text, "ts": iso(clock())}
    # keep the twenty most recent sessions
    keep = sorted(sessions.items(), key=lambda kv: kv[1].get("ts") or "")[-20:]
    atomic_write_json(_file(project), {"latest": session, "sessions": dict(keep)})
    return True


def recall(project, session):
    """The options of the session, else the latest ones, or None."""
    try:
        with open(_file(project), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    sessions = data.get("sessions") or {}
    found = sessions.get(session) or sessions.get(data.get("latest") or "")
    return (found or {}).get("options")
