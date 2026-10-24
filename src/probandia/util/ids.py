"""Identifiers: ULIDs and slugs.

- A ULID has 26 characters in Crockford base 32: 48 bits of milliseconds since
  the epoch, then 80 random bits. ULIDs sort by time. Within one millisecond the
  generator increments the random part, so ULIDs made by one process stay ordered.
- A slug matches ``[a-z0-9]+(-[a-z0-9]+)*`` and has at most 64 characters.
"""
import os
import re
import threading
import time
import unicodedata

from probandia.limits import SLUG_MAX_LENGTH

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(CROCKFORD)}
ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_lock = threading.Lock()
_last = [0, 0]  # last millisecond, last random part


def _encode(value, length):
    out = []
    for _ in range(length):
        out.append(CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


def ulid(now_ms=None):
    """Returns a new ULID. ``now_ms`` fixes the time part (for tests)."""
    ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not 0 <= ms < 1 << 48:
        raise ValueError("ULID time out of range")
    with _lock:
        if ms == _last[0]:
            rand = (_last[1] + 1) & ((1 << 80) - 1)
            if rand == 0:  # overflow of the random part: move to the next millisecond
                ms += 1
                rand = int.from_bytes(os.urandom(10), "big")
        else:
            rand = int.from_bytes(os.urandom(10), "big")
        _last[0], _last[1] = ms, rand
    return _encode(ms, 10) + _encode(rand, 16)


def is_ulid(value):
    return isinstance(value, str) and bool(ULID_RE.match(value))


def ulid_time_ms(value):
    """Returns the milliseconds encoded in a ULID."""
    if not is_ulid(value):
        raise ValueError(f"not a ULID: {value!r}")
    ms = 0
    for c in value[:10]:
        ms = (ms << 5) | _DECODE[c]
    return ms


def slugify(text, max_length=SLUG_MAX_LENGTH):
    """Turns any text into a slug: accents dropped, lower case, words joined by '-'.

    Raises ValueError when nothing is left.
    """
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ß", "ss").replace("æ", "ae").replace("œ", "oe")
    text = text.replace("Æ", "ae").replace("Œ", "oe").replace("ø", "o").replace("Ø", "o")
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > max_length:
        text = text[:max_length]
        if "-" in text and not text.endswith("-"):
            cut = text.rfind("-")
            # cut at a word boundary, unless that would lose more than half
            if cut >= max_length // 2:
                text = text[:cut]
        text = text.strip("-")
    if not text:
        raise ValueError("nothing left to make a slug from")
    return text


def is_slug(value, max_length=SLUG_MAX_LENGTH):
    return isinstance(value, str) and len(value) <= max_length and bool(SLUG_RE.match(value))
