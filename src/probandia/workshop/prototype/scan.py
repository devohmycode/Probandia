"""Finding one's way in ``commun/personnes.yaml``, line by line (WS2-T1).

The workshop's file is written by hand: comments, order, flow maps over several
lines. Nothing here parses YAML; the scan finds where each person, each of its
keys, each item of a list and each union starts and ends, so that the writer can
insert lines without rewriting any (WS-D2). Spans are ``(start, end)`` line
indices, ``end`` excluded; they are found again at each scan, never kept.
"""
import re

PERSON = re.compile(r"^  - id:\s*(\S+)\s*$")
KEY = re.compile(r"^    ([^\s#:{}\[\],][^:]*?):(?:\s|$)")
ITEM = re.compile(r"^      - ")
TOP = re.compile(r"^([^\s#][^:]*):")
UNION = re.compile(r"^  - ")


def split_lines(text):
    """The lines of a text with their endings: ``\\n`` only splits (not the other
    line breaks ``str.splitlines`` knows)."""
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def _content(line):
    return line.rstrip("\r\n")


def _indent(line):
    s = _content(line)
    return len(s) - len(s.lstrip(" ")) if s.strip() else None


def _is_comment(line):
    return _content(line).lstrip().startswith("#")


SPECIAL = re.compile(r"[\"'{}\[\]#\\]")


def braces(line, depth=0):
    """The depth of ``{``/``[`` after a line, quotes and comments skipped. It goes from one character that
    matters to the next (T266: char by char, it took two seconds on a workshop of 14,000 lines)."""
    quote = None
    s = _content(line)
    skip = -1   # the character an escape in double quotes takes
    for m in SPECIAL.finditer(s):
        i, c = m.start(), m.group()
        if i == skip:
            continue
        if quote:
            if c == "\\" and quote == '"':
                skip = i + 1
            elif c == quote:
                quote = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " {[,:"):
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] == " "):
            break
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
    return depth


def _block_end(lines, start, stop, deeper_than):
    """The end of the block that starts at ``start``: the lines after it that are
    indented more than ``deeper_than``, or inside an open flow map; trailing blank
    lines and comments left out."""
    depth = braces(lines[start])
    last = start
    i = start + 1
    while i < stop:
        ind = _indent(lines[i])
        if depth > 0:
            depth = braces(lines[i], depth)
            last = i
        elif ind is None or _is_comment(lines[i]) and ind <= deeper_than:
            pass
        elif ind > deeper_than:
            depth = braces(lines[i], depth)
            if not _is_comment(lines[i]):
                last = i
        else:
            break
        i += 1
    return last + 1


class Person:
    def __init__(self, wid, start, end):
        self.id, self.start, self.end = wid, start, end
        self.keys = {}    # key -> (start, end)
        self.items = {}   # key -> [(start, end)] of a list's items

    def __repr__(self):
        return f"Person({self.id!r}, {self.start}, {self.end})"


class Layout:
    """Where things are in the file. ``persons``: [Person], in file order;
    ``unions``: [(start, end)] of each union; ``top``: column-0 key -> (start, end);
    ``updated``: the line of ``meta.mis_a_jour``; ``banners``: [(line, text)] of the
    comment lines; ``persons_end``: the end of the last person."""

    def __init__(self, text):
        self.text = text
        self.newline = newline_of(text)
        self.lines = split_lines(text)
        self.persons, self.unions, self.banners = [], [], []
        self.top, self.updated, self.persons_end = {}, None, None
        self._scan()

    def person(self, wid):
        return next((p for p in self.persons if p.id == wid), None)

    def _scan(self):
        lines = self.lines
        tops = [(i, TOP.match(_content(x)).group(1)) for i, x in enumerate(lines) if TOP.match(_content(x))]
        for n, (i, key) in enumerate(tops):
            stop = tops[n + 1][0] if n + 1 < len(tops) else len(lines)
            self.top[key] = (i, _block_end(lines, i, stop, 0))
        self.banners = [(i, _content(x)) for i, x in enumerate(lines) if _is_comment(x)]
        if "meta" in self.top:
            a, b = self.top["meta"]
            self.updated = next((i for i in range(a, b) if re.match(r"^  mis_a_jour:", lines[i])), None)
        if "personnes" in self.top:
            self._persons(*self.top["personnes"])
        if "unions" in self.top:
            a, b = self.top["unions"]
            starts = [i for i in range(a + 1, b) if UNION.match(lines[i])]
            self.unions = [(i, _block_end(lines, i, b, 2)) for i in starts]

    def _persons(self, a, b):
        lines = self.lines
        starts = [i for i in range(a + 1, b) if PERSON.match(_content(lines[i]))]
        for i in starts:
            end = _block_end(lines, i, b, 2)
            p = Person(PERSON.match(_content(lines[i])).group(1).strip("\"'"), i, end)
            keys = [j for j in range(i + 1, end) if KEY.match(lines[j])]
            for j in keys:
                key = KEY.match(lines[j]).group(1)
                p.keys[key] = (j, _block_end(lines, j, end, 4))
                k_end = p.keys[key][1]
                items = [x for x in range(j + 1, k_end) if ITEM.match(lines[x])]
                if items:
                    p.items[key] = [(x, _block_end(lines, x, k_end, 6)) for x in items]
            p.keys = {"id": (i, i + 1), **p.keys}
            self.persons.append(p)
        self.persons_end = self.persons[-1].end if self.persons else a + 1
