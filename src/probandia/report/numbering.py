"""Numbering of chapters and sections, computed at each rendering.

| Style | Level 1 | Level 2 | Level 3 | Level 4 |
|---|---|---|---|---|
| ``arabic`` | 1 | 1.1 | 1.1.1 | 1.1.1.1 |
| ``roman`` | I | I.1 | I.1.1 | I.1.1.1 |
| ``roman-outline`` | I | A | 1 | a — headings show their own level; references the path I.A.1.a |

``report.number_pattern`` builds other styles from ``{I}``, ``{i}``, ``{A}``, ``{a}``, ``{1}``.
"""
import re

ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
         (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def roman(n):
    if not 0 < n < 4000:
        raise ValueError(f"no Roman numeral for {n}")
    out = []
    for value, sym in ROMAN:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def letters(n):
    """1 -> A, 26 -> Z, 27 -> AA, 28 -> AB."""
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def token(kind, n):
    return {"I": roman(n), "i": roman(n).lower(), "A": letters(n), "a": letters(n).lower(),
            "1": str(n)}[kind]


STYLES = {"arabic": ["1", "1", "1", "1"], "roman": ["I", "1", "1", "1"],
          "roman-outline": ["I", "A", "1", "a"]}


def parse_pattern(pattern):
    kinds = re.findall(r"\{(I|i|A|a|1)\}", pattern or "")
    if not kinds:
        raise ValueError(f"no tokens in the pattern {pattern!r}")
    sep = re.sub(r"\{(I|i|A|a|1)\}", "", pattern)[:1] or "."
    return kinds, sep


def apply(chapters, style="arabic", pattern=""):
    """Sets ``number`` (shown in the heading) and ``path`` (shown in references)."""
    if pattern:
        kinds, sep = parse_pattern(pattern)
        outline = False
    else:
        kinds, sep = STYLES[style], "."
        outline = style == "roman-outline"

    def walk(nodes, prefix, level):
        for i, node in enumerate(nodes, start=1):
            kind = kinds[min(level, len(kinds) - 1)]
            tok = token(kind, i)
            node.path = f"{prefix}{sep}{tok}" if prefix else tok
            node.number = f"{tok}." if outline else node.path
            node.anchor = "s-" + node.id.lower()
            walk(node.children, node.path, level + 1)

    walk(chapters, "", 0)
    return chapters
