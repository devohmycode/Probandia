"""Keys in ``.env`` files.

Two files are read, when they exist:
- ``<user config folder>/.env``, next to the user's ``config.toml``: keys for every project;
- ``<project>/.env``: keys of one project. ``config init`` lists it in ``.gitignore``
  and writes ``.env.example`` (``TEMPLATE``), to copy to ``.env``.

A variable already set in the environment always wins; then the project's file,
then the user's. Their values are never printed: only the names of the variables
they set. They are written only by ``keys set`` and ``keys unset`` (decision
D-7), which keep the other lines and the comments.

Syntax: ``NAME=value`` per line; ``export NAME=value`` is accepted; blank lines
and lines starting with ``#`` are skipped; a value may be quoted with ``"`` or
``'``; an unquoted value ends at `` #``.
"""
import os
import re

LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
FILES_VARIABLE = "PROBANDIA_ENV_FILES"
FILE_NAME = ".env"
ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}

TEMPLATE = r"""# Keys read by Probandia. Copy this file to .env and fill in the keys you have;
# an empty value is ignored. Never commit .env (it is in .gitignore).
#
# Probandia reads two .env files, when they exist:
#   - the user's: next to config.toml (Windows: %APPDATA%\probandia\.env;
#     Linux and macOS: ~/.config/probandia/.env; or $PROBANDIA_CONFIG_DIR/.env);
#   - the project's: at the root of the project, next to probandia.toml.
# A variable set in the environment wins, then the project's file, then the user's.
# Check with: doctor

# Search providers
TAVILY_API_KEY=
BRAVE_API_KEY=
LINKUP_API_KEY=
EXA_API_KEY=
SERPER_API_KEY=
SEARCHAPI_API_KEY=
SERPAPI_API_KEY=
# one key for every OpenWeb Ninja API (web search, news, books)
OPENWEBNINJA_API_KEY=
PARALLEL_API_KEY=
STAAN_API_KEY=
MARGINALIA_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=

# Reading
FIRECRAWL_API_KEY=
JINA_API_KEY=
# structured extraction (read --extract); its free plan may reuse the pages sent
SGAI_API_KEY=
# unblocking readers, without their anti-bot options
ZENROWS_API_KEY=
SCRAPERAPI_API_KEY=
# Apify: search and reading by a few allowed actors
APIFY_TOKEN=

# Archives
EUROPEANA_API_KEY=
GEONAMES_USERNAME=
IA_ACCESS_KEY=
IA_SECRET_KEY=

# Gramps Web export
PROBANDIA_GRAMPS_PASSWORD=
"""


def _value(raw):
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), "\\" + m.group(1)), raw[1:-1])
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def parse(text):
    """{name: value} of a ``.env`` text."""
    out = {}
    for line in text.lstrip("﻿").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = LINE.match(line)
        if m:
            out[m.group(1)] = _value(m.group(2))
    return out


def user_file(environ):
    from probandia.config import user_config_path

    return os.path.join(os.path.dirname(user_config_path(environ)), FILE_NAME)


def files(environ, project=None):
    """The ``.env`` files to read, the weakest first."""
    out = [user_file(environ)]
    if project:
        out.append(os.path.join(project, FILE_NAME))
    return out


def merged(environ, project=None):
    """A copy of ``environ`` completed by the ``.env`` files. ``PROBANDIA_ENV_FILES``
    names the files that were read."""
    values, read = {}, []
    for path in files(environ, project):
        try:
            with open(path, encoding="utf-8") as fh:
                values.update(parse(fh.read()))
        except (OSError, UnicodeDecodeError):
            continue
        read.append(path)
    out = dict(environ)
    for name, value in values.items():
        if value and not environ.get(name):
            out[name] = value
    if read:
        out[FILES_VARIABLE] = os.pathsep.join(read)
    return out


def _quote(value):
    """A value as ``parse`` reads it back: bare when it can be, otherwise quoted."""
    if value and not re.search(r"[\s#\"'\\]", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return '"' + escaped + '"'


def _write(path, lines):
    from probandia.util.fs import atomic_write_text

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # keys: readable by their owner only, from the first byte (on Windows, chmod sets read-only only)
    atomic_write_text(path, "".join(line + "\n" for line in lines), mode=0o600)


def _lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().lstrip("\ufeff").splitlines()
    except FileNotFoundError:
        return []


def set_value(path, name, value):
    """Writes ``NAME=value`` in ``path``: in place of its line when it has one (the
    first; later ones go), at the end otherwise. Other lines and comments stay."""
    out, done = [], False
    for line in _lines(path):
        m = LINE.match(line)
        if m and m.group(1) == name and not line.lstrip().startswith("#"):
            if not done:
                out.append(f"{name}={_quote(value)}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={_quote(value)}")
    _write(path, out)


def unset_value(path, name):
    """Removes ``NAME``'s lines from ``path``; True when there was one."""
    lines = _lines(path)
    kept = [line for line in lines if not ((m := LINE.match(line)) and m.group(1) == name
                                           and not line.lstrip().startswith("#"))]
    if len(kept) == len(lines):
        return False
    _write(path, kept)
    return True
