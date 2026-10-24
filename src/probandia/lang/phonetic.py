"""Phonetic keys of surnames: Soundex2 (French) and Kölner Phonetik (German).

Two spellings of one name usually share at least one key: ``Hugo``,
``Hugot`` and ``Hugues`` all give ``AK`` in Soundex2.
"""
import re
import unicodedata


def fold(text):
    """Upper case letters A-Z only: accents dropped, ß -> SS, other signs removed."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ß", "ss").replace("æ", "ae").replace("œ", "oe")
    text = text.replace("Æ", "AE").replace("Œ", "OE")
    return re.sub(r"[^A-Z]", "", text.upper())


def soundex2(name):
    """French Soundex2 (after F. Brouard): at most 4 characters, no padding."""
    s = fold(name)
    if not s:
        return ""
    for a, b in (("GUI", "KI"), ("GUE", "KE"), ("GA", "KA"), ("GO", "KO"), ("GU", "K"),
                 ("CA", "KA"), ("CO", "KO"), ("CU", "KU"), ("Q", "K"), ("CC", "K"), ("CK", "K")):
        s = s.replace(a, b)
    s = s[0] + re.sub(r"[EIOU]", "A", s[1:])
    for a, b in (("ASA", "AZA"), ("KN", "NN"), ("PF", "FF"), ("PH", "FF"), ("SCH", "SSS")):
        if s.startswith(a):
            s = b + s[len(a):]
    s = re.sub(r"(?<![CS])H", "", s)
    s = re.sub(r"(?<!A)Y", "", s)
    s = re.sub(r"[ADTS]$", "", s) if len(s) > 1 else s
    s = s[0] + s[1:].replace("A", "") if s else s
    s = re.sub(r"(.)\1+", r"\1", s)
    return s[:4]


def koelner(name):
    """Kölner Phonetik: a string of digits."""
    s = fold(name)
    codes = []
    for i, c in enumerate(s):
        prev = s[i - 1] if i else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if c in "AEIJOUY":
            code = "0"
        elif c == "H":
            code = ""
        elif c == "B":
            code = "1"
        elif c == "P":
            code = "3" if nxt == "H" else "1"
        elif c in "DT":
            code = "8" if nxt in ("C", "S", "Z") else "2"
        elif c in "FVW":
            code = "3"
        elif c in "GKQ":
            code = "4"
        elif c == "C":
            if i == 0:
                code = "4" if nxt in "AHKLOQRUX" else "8"
            elif prev in "SZ":
                code = "8"
            else:
                code = "4" if nxt in "AHKOQUX" else "8"
        elif c == "X":
            code = "8" if prev in "CKQ" else "48"
        elif c == "L":
            code = "5"
        elif c in "MN":
            code = "6"
        elif c == "R":
            code = "7"
        elif c in "SZ":
            code = "8"
        else:
            code = ""
        codes.append(code)
    out = ""
    for code in codes:
        for d in code:
            if not out or out[-1] != d:
                out += d
    return out[0] + out[1:].replace("0", "") if out else ""


def keys(name):
    """Every key of a name, for matching."""
    return {k for k in (soundex2(name), "K:" + koelner(name)) if k and k != "K:"}


def same_name(a, b):
    """True when two surnames share a phonetic key, or fold to the same letters."""
    return fold(a) == fold(b) or bool(keys(a) & keys(b))
