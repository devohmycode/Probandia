"""The language of a report, in the order of the sources:

1. ``--lang``;
2. the ``language`` of ``research.yaml``;
3. ``PROBANDIA_LANGUAGE``, or its alias ``PROBANDIA_LANG``;
4. the ``language`` setting, unless it is ``auto``;
5. the harness's language: the ``language`` key of Claude Code's settings;
6. the language of the prompt: ``--prompt-lang``, else ``.probandia/session-lang``;
7. the operating system;
8. ``en``.

``language.detection_order`` reorders or drops sources. Nothing is guessed: a
source that gives no clear tag is skipped.
"""
import json
import os
import re
import subprocess
import sys

from probandia.config.registry import LANGUAGE_SOURCES

TAG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
SESSION_FILE = os.path.join(".probandia", "session-lang")

# free text of Claude Code's ``language`` setting -> tag
HARNESS_NAMES = {
    "english": "en", "anglais": "en",
    "french": "fr", "français": "fr", "francais": "fr",
    "german": "de", "deutsch": "de", "allemand": "de",
    "spanish": "es", "español": "es", "espanol": "es",
    "italian": "it", "italiano": "it",
    "portuguese": "pt", "português": "pt",
    "dutch": "nl", "nederlands": "nl",
    "japanese": "ja", "日本語": "ja",
    "chinese": "zh", "中文": "zh",
}


def normalize(tag):
    """``fr_FR.UTF-8`` -> ``fr-FR``; None when it is not a language tag."""
    if not tag:
        return None
    tag = str(tag).strip().split(".")[0].split("@")[0].replace("_", "-")
    if tag in ("C", "POSIX", "auto", "") or not TAG.match(tag):
        return None
    parts = tag.split("-")
    out = [parts[0].lower()]
    for p in parts[1:]:
        out.append(p.upper() if len(p) == 2 else p.capitalize() if len(p) == 4 else p)
    return "-".join(out)


def base(tag):
    return (tag or "en").split("-")[0].lower()


def harness_value(text):
    """Claude Code's free-text ``language`` -> a tag, or None."""
    if not text:
        return None
    key = str(text).strip().lower()
    first = key.split()[0] if key.split() else ""
    tag = HARNESS_NAMES.get(key) or HARNESS_NAMES.get(first)
    if tag:
        return tag
    return normalize(key) if len(key) <= 8 else None


def claude_settings_language(project=None, environ=None):
    """The ``language`` key of ``.claude/settings.json`` (project first), then of
    ``~/.claude/settings.json``; read only."""
    environ = os.environ if environ is None else environ
    home = environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        environ.get("USERPROFILE") or environ.get("HOME") or os.path.expanduser("~"), ".claude")
    paths = []
    if project:
        paths += [os.path.join(project, ".claude", "settings.local.json"),
                  os.path.join(project, ".claude", "settings.json")]
    paths.append(os.path.join(home, "settings.json"))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                value = (json.load(fh) or {}).get("language")
        except (OSError, ValueError, AttributeError):
            continue
        tag = harness_value(value)
        if tag:
            return tag
    return None


def session_language(project):
    if not project:
        return None
    try:
        with open(os.path.join(project, SESSION_FILE), encoding="utf-8") as fh:
            return normalize(fh.read().strip())
    except OSError:
        return None


def remember_session_language(project, tag):
    tag = normalize(tag)
    if project and tag:
        path = os.path.join(project, SESSION_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(tag + "\n")
    return tag


def _windows_language():
    import ctypes
    import locale

    lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    return normalize(locale.windows_locale.get(lcid))


def _macos_language():
    out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                         text=True, timeout=5).stdout
    m = re.search(r'"?([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*)"?', out.replace("(", " "))
    return normalize(m.group(1)) if m else None


def os_language(environ=None, platform=None):
    environ = os.environ if environ is None else environ
    platform = platform or sys.platform
    if platform == "win32":
        try:
            tag = _windows_language()
            if tag:
                return tag
        except (AttributeError, OSError, ValueError):
            pass
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(var)
        if value:
            tag = normalize(value.split(":")[0])
            if tag:
                return tag
    if platform == "darwin":
        try:
            return _macos_language()
        except (OSError, subprocess.SubprocessError):
            return None
    return None


def detect(arg=None, research=None, environ=None, setting=None, project=None, prompt=None,
           order=None, os_lookup=None):
    """(tag, source). ``setting``: the value of the ``language`` setting from the
    files and harness options (not from ``--lang`` nor the environment)."""
    environ = os.environ if environ is None else environ
    lookups = {
        "arg": lambda: normalize(arg),
        "research": lambda: normalize(research),
        "env": lambda: normalize(environ.get("PROBANDIA_LANGUAGE") or environ.get("PROBANDIA_LANG")),
        "setting": lambda: normalize(setting),
        "harness": lambda: claude_settings_language(project, environ),
        "prompt": lambda: normalize(prompt) or session_language(project),
        "os": os_lookup or (lambda: os_language(environ)),
        "default": lambda: "en",
    }
    for source in order or LANGUAGE_SOURCES:
        if source not in lookups:
            continue
        tag = lookups[source]()
        if tag:
            return tag, source
    return "en", "default"


def setting_value(config):
    """The ``language`` setting, unless it came from ``--lang`` or the environment
    (those are sources of their own) or is ``auto``."""
    if config is None:
        return None
    origin = config.origin("language").layer
    value = config.get("language")
    if origin in ("arg", "env", "default") or value == "auto":
        return None
    return value
