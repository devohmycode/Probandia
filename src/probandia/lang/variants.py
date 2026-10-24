"""Name variants, before any search: attested forms first, then the particle
forms, then scribal forms, then reading confusions; at most 12 surname forms.

- **Attested forms** come from the family's ``variants.yaml``.
- **Particle forms**: LAFONTAINE, LA FONTAINE and FONTAINE are one name.
- **Scribal forms**: one change among the rules below. A form is kept only when
  it keeps the Soundex2 or the Kölner Phonetik code of the original; at most two
  doubled or dropped consonants and two final letters.
- **Given names**: the French, German and Latin forms, and the Latin genitive,
  from a table of more than 300 names.
- **Reading confusions** (``--paleo``): letters a reader can mistake.
"""
import os
import re

from probandia.lang.phonetic import fold, koelner, soundex2

MAX_FORMS = 12

# Groups of interchangeable spellings. One change: one occurrence of one member
# replaced by another member of its group.
SCRIBAL = [
    ("clusters", ("ckh", "ck", "kk", "kh", "k")),
    ("vowels", ("ei", "ey", "ai", "ay")),
    ("aspirated-t", ("th", "t")),
    ("aspirated-p", ("ph", "f")),
    ("c-k", ("c", "k")),
    ("w-v", ("w", "v")),
    ("z-s", ("tz", "z", "s")),
    ("y-i", ("y", "i")),
    ("umlaut-a", ("ä", "ae", "a")),
    ("umlaut-o", ("ö", "oe", "o")),
    ("umlaut-u", ("ü", "ue", "u")),
]
PALEO = [("u", "n"), ("n", "u"), ("c", "e"), ("e", "c"), ("b", "d"), ("d", "b"), ("ſ", "f"),
         ("s", "f"), ("f", "s"), ("rn", "m"), ("m", "rn"), ("cl", "d"), ("d", "cl")]
CONSONANTS = "bcdfgjklmnpqrstvwxz"  # not h: a doubled h is no spelling
FINALS = "estd"
PER_RULE = {"double": 2, "final": 2}
PARTICLES = ("des", "du", "de", "le", "la")  # glued or apart; d' only with its apostrophe
VOWELS = "aeiouy"


def _case_like(model, form):
    if model.isupper():
        return form.upper()
    if model[:1].isupper():
        return form[:1].upper() + form[1:]
    return form


# Members that only replace, never get replaced: a plain "a" is not an umlaut.
TARGET_ONLY = {"umlaut-a": {"a"}, "umlaut-o": {"o"}, "umlaut-u": {"u"}}


def _replacements(name, groups):
    """Every form with one member of a group replaced by another one."""
    low = name.lower()
    out = []
    for rule, members in groups:
        sources = [m for m in members if m not in TARGET_ONLY.get(rule, ())]
        pattern = "|".join(re.escape(m) for m in sorted(sources, key=len, reverse=True))
        for m in re.finditer(pattern, low):
            if rule == "z-s" and low[m.end():m.end() + 1] == "c":
                continue  # the s of "sch" is not a z
            for other in members:
                if other != m.group(0):
                    out.append((low[: m.start()] + other + low[m.end():], rule))
    return out


def scribal_forms(name):
    """(form, rule) of every scribal form that keeps a phonetic code of ``name``."""
    low = name.lower()
    candidates = _replacements(name, SCRIBAL)
    for i, c in enumerate(low):  # double letters, inside the name only
        if c in CONSONANTS and 0 < i < len(low) - 1:
            if i + 1 < len(low) and low[i + 1] == c:
                candidates.append((low[:i] + low[i + 1:], "double"))
            elif (i == 0 or low[i - 1] != c) and (i + 1 >= len(low) or low[i + 1] != c):
                candidates.append((low[: i + 1] + c + low[i + 1:], "double"))
    if low and low[-1] in FINALS:  # final letters
        candidates.append((low[:-1], "final"))
    for f in FINALS:
        if not low.endswith(f):
            candidates.append((low + f, "final"))
    codes = (soundex2(name), koelner(name))
    out, seen, count = [], {fold(name)}, dict.fromkeys(PER_RULE, 0)
    for form, rule in candidates:
        key = fold(form)
        if key in seen or not key or count.get(rule, -1) >= PER_RULE.get(rule, 1):
            continue
        if soundex2(form) == codes[0] or koelner(form) == codes[1]:
            seen.add(key)
            if rule in count:
                count[rule] += 1
            out.append((_case_like(name, form), rule))
    return out


def _onset(rest):
    """A name can start so after a glued particle: no vowel (it would take l' or d'),
    nothing like the "mb" of LAMBERT or the "lc" of DELCOURT."""
    return len(rest) >= 3 and rest[0] in CONSONANTS and (rest[1] in VOWELS or rest[1] in "lrh")


def particle_forms(name):
    """(form, particle): the particle glued or apart, then dropped. LAFONTAINE gives
    LA FONTAINE and FONTAINE; La Fontaine gives Lafontaine and Fontaine."""
    low = name.lower().replace("’", "'")
    m = re.match(r"(des|du|de|le|la)\s+(\S.*)$", low) or re.match(r"(d)'\s*(\S.*)$", low)
    if m:
        particle, forms = m.group(1), [m.group(1) + m.group(2), m.group(2)]
    else:  # glued: the longest particle that starts the name, or none
        particle = next((p for p in PARTICLES if low.startswith(p)), "")
        rest = low[len(particle):]
        if not particle or not _onset(rest):
            return []
        forms = [particle + " " + rest, rest]
    if name.isupper():
        return [(f.upper(), particle) for f in forms]
    if name[:1].isupper():
        return [(" ".join(w[:1].upper() + w[1:] for w in f.split(" ")), particle) for f in forms]
    return [(f, particle) for f in forms]


def paleo_forms(name):
    low = name.lower()
    out, seen = [], {fold(name)}
    for a, b in PALEO:
        for m in re.finditer(re.escape(a), low):
            form = low[: m.start()] + b + low[m.end():]
            if fold(form) not in seen:
                seen.add(fold(form))
                out.append((_case_like(name, form), f"{a}>{b}"))
    return out


def surname_forms(name, attested=None, paleo=False, limit=MAX_FORMS):
    """[(form, kind, detail)], attested forms first; at most ``limit``."""
    candidates = []
    for key, forms in (attested or {}).items():
        if fold(key) == fold(name) or any(fold(f["form"]) == fold(name) for f in forms):
            candidates += [(f["form"], "attested", f.get("source") or "")
                           for f in [{"form": key, "source": None}] + list(forms)]
    candidates += [(form, "particle", particle) for form, particle in particle_forms(name)]
    candidates += [(form, "scribal", rule) for form, rule in scribal_forms(name)]
    if paleo:
        candidates += [(form, "paleo", rule) for form, rule in paleo_forms(name)]
    out, seen = [], {_words(name)}
    for form, kind, detail in candidates:
        if _words(form) not in seen:
            seen.add(_words(form))
            out.append((form, kind, detail))
    return out[:limit]


def _words(form):
    """The folded words: LA FONTAINE and LAFONTAINE are two searches, La Fontaine and LA FONTAINE one."""
    return " ".join(w for w in (fold(x) for x in re.split(r"[\s'’]+", form)) if w)


# given names

_TABLE = None


def given_table():
    global _TABLE
    if _TABLE is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "given_names.tsv")
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                fr, de, la = (c.split("/") for c in cols[:3])
                gen = cols[3].split("/") if len(cols) > 3 and cols[3] else [genitive(x) for x in la]
                rows.append({"fr": fr, "de": de, "la": la, "la_gen": gen})
        _TABLE = rows
    return _TABLE


def genitive(nominative):
    """The regular Latin genitive: Theodorus -> Theodori, Joannes -> Joannis, Maria -> Mariae."""
    parts = nominative.split(" ")
    out = []
    for p in parts:
        if p.endswith("us"):
            out.append(p[:-2] + "i")
        elif p.endswith("es"):
            out.append(p[:-2] + "is")
        elif p.endswith("a"):
            out.append(p + "e")
        elif p.endswith("as"):
            out.append(p[:-2] + "ae")
        else:
            out.append(p)
    return " ".join(out)


def given_forms(name):
    """[(form, language)] for every row of the table that holds ``name``."""
    key = fold(name)
    out, seen = [], {key}
    for row in given_table():
        everything = row["fr"] + row["de"] + row["la"] + row["la_gen"]
        if key not in {fold(x) for x in everything}:
            continue
        for lang in ("fr", "de", "la", "la_gen"):
            for form in row[lang]:
                if fold(form) not in seen:
                    seen.add(fold(form))
                    out.append((form, lang))
    return out
