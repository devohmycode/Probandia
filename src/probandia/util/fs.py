"""File helpers: atomic writes, UTF-8 without BOM, LF line endings."""
import json
import os
import time
from datetime import datetime, timezone


def utc_now():
    """The current time in UTC, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    """ISO 8601 in UTC with a Z suffix: 2026-09-30T18:34:12Z."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    """Reads a timestamp written by ``iso``."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def atomic_write_bytes(path, data, mode=None):
    """Writes a file atomically: a temporary file in the same folder, then a replace.

    A reader sees either the old content or the new one, never a partial file.
    ``mode``: the file's mode, set before a byte is written (keys: 0o600).
    """
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    import tempfile   # not at import: it costs a hook some 40 ms (T145)

    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        # mkstemp creates the file with mode 0600: give it the mode of the file it
        # replaces, or the usual mode of a new file.
        if mode is not None:
            os.chmod(tmp, mode)
        else:
            try:
                os.chmod(tmp, os.stat(path).st_mode & 0o7777)
            except FileNotFoundError:
                os.chmod(tmp, 0o666 & ~_umask())
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _replace(src, dst, attempts=50):
    """os.replace, retried while Windows reports the target as in use by a reader."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == attempts - 1:
                raise
            time.sleep(0.02)


def atomic_write_text(path, text, mode=None, newline="\n"):
    """Writes text atomically, in UTF-8 without BOM, with LF line endings; ``newline=None``
    keeps the text's own endings (a file of someone else's, such as a workshop's)."""
    if newline is not None:
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    atomic_write_bytes(path, text.encode("utf-8"), mode)


def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_text(path):
    """Reads a UTF-8 text file; a byte-order mark, if any, is dropped."""
    with open(path, encoding="utf-8-sig", newline=None) as fh:
        return fh.read()
