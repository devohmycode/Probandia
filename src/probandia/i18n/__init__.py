"""Messages shown to the user, through gettext catalogues.

- The domain is ``probandia``; message ids are English.
- Catalogues are ``.po`` files, read directly (no compiled ``.mo``):
  ``locales/<lang>/LC_MESSAGES/probandia.po`` in the package's repository, then
  in the folders given to ``activate`` (the project's ``locales/``, ``locales.dir``).
- A regional tag falls back to its base language, then to English:
  ``fr-CA`` -> ``fr`` -> ``en``.
- The pseudo-locale ``xx`` wraps every message in ``⟦…⟧``. Tests render outputs
  in ``xx``: a line that is not wrapped was not passed through ``_()``.

Usage::

    from probandia.i18n import _, N_, ngettext
    HELP = N_("Formats of the report")      # marked here, translated where shown
    r.line(_("wrote {path}").format(path=p))
"""
import os
import re

DOMAIN = "probandia"
PSEUDO = "xx"
PSEUDO_OPEN, PSEUDO_CLOSE = "⟦", "⟧"

_state = {"lang": "en", "catalog": {}, "plural": None}


def N_(message):
    """Marks a message for extraction, without translating it (yet)."""
    return message


def _(message):
    """Translates a message into the active language."""
    if _state["lang"] == PSEUDO:
        return f"{PSEUDO_OPEN}{message}{PSEUDO_CLOSE}"
    return _state["catalog"].get(message) or message


def ngettext(singular, plural, n):
    """Translates a message that depends on a number."""
    if _state["lang"] == PSEUDO:
        return f"{PSEUDO_OPEN}{singular if n == 1 else plural}{PSEUDO_CLOSE}"
    forms = _state["catalog"].get((singular, plural))
    index = _plural_index(_state["lang"], n)
    if forms and index < len(forms) and forms[index]:
        return forms[index]
    return singular if n == 1 else plural


def _plural_index(lang, n):
    base = lang.split("-")[0]
    if base in ("fr", "pt"):
        return 0 if n in (0, 1) else 1
    if base in ("ja", "zh", "ko"):
        return 0
    return 0 if n == 1 else 1


def current():
    return _state["lang"]


def repo_locales_dir():
    """``locales/``: in the package of a wheel, else at the root of the repository."""
    from probandia.paths import data

    return data("locales")


def fallbacks(lang):
    """fr-CA -> [fr-CA, fr, en]."""
    out = []
    parts = (lang or "en").split("-")
    for i in range(len(parts), 0, -1):
        tag = "-".join(parts[:i])
        if tag not in out:
            out.append(tag)
    if "en" not in out:
        out.append("en")
    return out


def activate(lang, extra_dirs=()):
    """Makes ``lang`` the language of messages. Unknown languages fall back to English."""
    lang = (lang or "en").strip()
    if lang == "auto" or not lang:
        lang = "en"
    catalog = {}   # filled, then put in place at once: another thread never sees it half read (T107)
    if lang != PSEUDO:
        dirs = [repo_locales_dir()] + [d for d in extra_dirs if d]
        # Lowest priority first: English, then the base language, then the regional tag;
        # within one language, the repository first, then the user's folders.
        for tag in reversed(fallbacks(lang)):
            for d in dirs:
                if tag == "en" and d == dirs[0]:   # the messages themselves (test_english_translates_nothing):
                    continue                       # 2,000 entries not read at each launch (T145)
                path = os.path.join(d, tag, "LC_MESSAGES", DOMAIN + ".po")
                if os.path.isfile(path):
                    for k, v in read_po(path).items():
                        if v:
                            catalog[k] = v
    _state["lang"], _state["catalog"] = lang, catalog
    return lang


class Translator:
    """Messages in one language, without changing the language of the engine's
    own messages: a report is written in its research's language."""

    def __init__(self, lang, extra_dirs=()):
        self.lang = (lang or "en").strip() or "en"
        self.catalog = {}
        self.missing = False
        if self.lang == PSEUDO:
            return
        found = False
        dirs = [repo_locales_dir()] + [d for d in extra_dirs if d]
        for tag in reversed(fallbacks(self.lang)):
            for d in dirs:
                if tag == "en" and d == dirs[0]:   # the messages themselves (test_english_translates_nothing):
                    continue                       # 2,000 entries not read at each launch (T145)
                path = os.path.join(d, tag, "LC_MESSAGES", DOMAIN + ".po")
                if os.path.isfile(path):
                    if tag == self.lang or tag == self.lang.split("-")[0]:
                        found = True
                    for k, v in read_po(path).items():
                        if v:
                            self.catalog[k] = v
        base = self.lang.split("-")[0]
        self.missing = base != "en" and not found

    def __call__(self, message):
        if self.lang == PSEUDO:
            return f"{PSEUDO_OPEN}{message}{PSEUDO_CLOSE}"
        return self.catalog.get(message) or message

    def plural(self, singular, plural, n):
        if self.lang == PSEUDO:
            return f"{PSEUDO_OPEN}{singular if n == 1 else plural}{PSEUDO_CLOSE}"
        forms = self.catalog.get((singular, plural))
        index = _plural_index(self.lang, n)
        if forms and index < len(forms) and forms[index]:
            return forms[index]
        return singular if n == 1 else plural


# .po files

_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}


def _unquote(s):
    s = s.strip()
    if not (s.startswith('"') and s.endswith('"')):
        raise ValueError(f"not a quoted string: {s!r}")
    return re.sub(r'\\(.)', lambda m: _ESCAPES.get(m.group(1), m.group(1)), s[1:-1])


def read_po(path):
    """Reads a .po file: {msgid: msgstr} and {(msgid, msgid_plural): [msgstr...]}.
    Fuzzy entries and the header are skipped."""
    with open(path, encoding="utf-8-sig") as fh:
        lines = fh.read().splitlines()
    entries, entry, field, fuzzy = {}, {}, None, False

    def flush():
        nonlocal entry, fuzzy
        if "msgid" in entry and entry["msgid"] and not fuzzy:
            if "msgid_plural" in entry:
                forms = [entry.get(f"msgstr[{i}]", "") for i in range(10) if f"msgstr[{i}]" in entry]
                entries[(entry["msgid"], entry["msgid_plural"])] = forms
            else:
                entries[entry["msgid"]] = entry.get("msgstr", "")
        entry, fuzzy = {}, False

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            field = None
        elif s.startswith("#"):
            if s.startswith("#,") and "fuzzy" in s:
                if "msgid" in entry:
                    flush()
                fuzzy = True
        elif s.startswith('"'):
            if field:
                entry[field] += _unquote(s)
        else:
            m = re.match(r"^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(.*)$", s)
            if not m:
                raise ValueError(f"{path}: cannot read line {line!r}")
            field = m.group(1)
            if field == "msgid" and "msgid" in entry:
                flush()
            entry[field] = _unquote(m.group(2))
    flush()
    return entries


def quote_po(text):
    """A .po string literal; long or multi-line messages are split per line."""
    esc = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    if "\n" not in text:
        return '"' + esc.replace("\n", "\\n") + '"'
    parts = esc.split("\n")
    pieces = [p + "\\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    return '""\n' + "\n".join(f'"{p}"' for p in pieces)
