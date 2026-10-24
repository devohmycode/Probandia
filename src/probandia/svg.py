"""SVG charts in pure Python (SPECS § 11.2).

**Ancestor chart.** The root is Sosa 1; person ``n`` sits in generation
``g = floor(log2 n)``, at slot ``s = n - 2**g``; its vertical centre is
``(s + 0.5) * H / 2**g``, ``H`` being the chart's height. Boxes are 180 × 48
px, with 40 px between generations.

**Descendant chart.** A tidy tree laid out by the Buchheim–Walker algorithm
(linear time); boxes are 180 × 48 px, 16 px between siblings, 64 px between
generations.

A name is cut at 26 characters with an ellipsis; the second line holds the
years. Each box has a ``<title>`` with the full text. Colours come from CSS
variables, one per status; a person presumed living is masked.
"""
import math
from xml.sax.saxutils import escape as _escape


def escape(text):
    """Text for an element or a double-quoted attribute: ``&``, ``<``, ``>`` and ``"`` escaped."""
    return _escape(text, {'"': "&quot;"})

BOX_W, BOX_H = 180, 48
ANC_GAP, ANC_VGAP = 40, 8
DESC_SIB, DESC_GEN = 16, 64
NAME_MAX = 26

STYLE = """
  :root { --record: #1d6b3a; --index: #2a5d9f; --hypothesis: #8a6100; --living: #666666;
    --ink: #1b1b1b; --paper: #ffffff; --line: #555555; }
  .box rect { fill: var(--paper); stroke-width: 1.5; }
  .record rect { stroke: var(--record); stroke-width: 2.5; }
  .index rect { stroke: var(--index); }
  .hypothesis rect { stroke: var(--hypothesis); stroke-dasharray: 5 4; }
  .living rect { stroke: var(--living); fill: #eeeeee; }
  text { font: 13px system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink); }
  .years { font-size: 11px; fill: #444444; }
  .link { fill: none; stroke: var(--line); stroke-width: 1.2; }
  .link.hypothesis { stroke-dasharray: 4 4; }
"""


def cut(text, n=NAME_MAX):
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _box(tree, pid, x, y, living_label):
    name = tree.name(pid, living_label)
    years = tree.years(pid)
    title = name + (f", {years}" if years else "")
    status = tree.status(pid)
    return (f'<g class="box {status}" transform="translate({x:g},{y:g})">'
            f"<title>{escape(title)}</title>"
            f'<rect width="{BOX_W}" height="{BOX_H}" rx="6"/>'
            f'<text x="8" y="20">{escape(cut(name))}</text>'
            + (f'<text class="years" x="8" y="38">{escape(years)}</text>' if years else "")
            + "</g>")


def _svg(width, height, body, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" '
            f'width="{width:g}" height="{height:g}" role="img" aria-label="{escape(label)}">\n'
            f"<style>{STYLE}</style>\n" + "\n".join(body) + "\n</svg>\n")


def ancestors(tree, root, generations=4, living_label="Living person", title="Ancestors of {name}"):
    """The ancestor chart of ``root``, ``generations`` generations up; ``title``, translated, names it
    to a screen reader (T123)."""
    sosa = tree.ancestors(root, generations - 1)
    top = max(int(math.log2(n)) for n in sosa)
    height = (2 ** top) * (BOX_H + ANC_VGAP)
    width = (top + 1) * (BOX_W + ANC_GAP) - ANC_GAP
    pos = {}
    for n in sorted(sosa):
        g = int(math.log2(n))
        s = n - 2 ** g
        cy = (s + 0.5) * height / 2 ** g
        pos[n] = (g * (BOX_W + ANC_GAP), cy - BOX_H / 2)
    body = []
    for n in sorted(sosa):
        if n == 1:
            continue
        child = n // 2
        cx, cy = pos[child][0] + BOX_W, pos[child][1] + BOX_H / 2
        px, py = pos[n][0], pos[n][1] + BOX_H / 2
        mid = cx + ANC_GAP / 2
        dotted = " hypothesis" if tree.dotted(sosa[child]) else ""   # T250: a deduced link too
        body.append(f'<path class="link{dotted}" d="M{cx:g},{cy:g} H{mid:g} V{py:g} H{px:g}"/>')
    for n in sorted(sosa):
        body.append(_box(tree, sosa[n], pos[n][0], pos[n][1], living_label))
    return _svg(width, height, body, title.format(name=tree.name(root, living_label)))


# Buchheim–Walker


class _Node:
    def __init__(self, pid, kids, parent=None, depth=0, number=1):
        self.pid, self.x, self.y = pid, -1.0, depth
        self.children = [_Node(k, sub, self, depth + 1, i + 1) for i, (k, sub) in enumerate(kids)]
        self.parent, self.thread, self.mod = parent, None, 0.0
        self.ancestor, self.change, self.shift = self, 0.0, 0.0
        self._lmost, self.number = None, number

    def left(self):
        return self.thread or (self.children[0] if self.children else None)

    def right(self):
        return self.thread or (self.children[-1] if self.children else None)

    def lbrother(self):
        n = None
        if self.parent:
            for node in self.parent.children:
                if node is self:
                    return n
                n = node
        return n

    @property
    def lmost_sibling(self):
        if not self._lmost and self.parent and self is not self.parent.children[0]:
            self._lmost = self.parent.children[0]
        return self._lmost


def _firstwalk(v, distance=1.0):
    if not v.children:
        v.x = v.lbrother().x + distance if v.lmost_sibling else 0.0
    else:
        default = v.children[0]
        for w in v.children:
            _firstwalk(w, distance)
            default = _apportion(w, default, distance)
        _execute_shifts(v)
        midpoint = (v.children[0].x + v.children[-1].x) / 2
        w = v.lbrother()
        if w:
            v.x = w.x + distance
            v.mod = v.x - midpoint
        else:
            v.x = midpoint
    return v


def _apportion(v, default, distance):
    w = v.lbrother()
    if w is not None:
        vir = vor = v
        vil, vol = w, v.lmost_sibling
        sir = sor = v.mod
        sil, sol = vil.mod, vol.mod
        while vil.right() and vir.left():
            vil, vir = vil.right(), vir.left()
            vol, vor = vol.left(), vor.right()
            vor.ancestor = v
            shift = (vil.x + sil) - (vir.x + sir) + distance
            if shift > 0:
                _move_subtree(_ancestor(vil, v, default), v, shift)
                sir += shift
                sor += shift
            sil += vil.mod
            sir += vir.mod
            sol += vol.mod
            sor += vor.mod
        if vil.right() and not vor.right():
            vor.thread = vil.right()
            vor.mod += sil - sor
        else:
            if vir.left() and not vol.left():
                vol.thread = vir.left()
                vol.mod += sir - sol
            default = v
    return default


def _move_subtree(wl, wr, shift):
    subtrees = wr.number - wl.number
    wr.change -= shift / subtrees
    wr.shift += shift
    wl.change += shift / subtrees
    wr.x += shift
    wr.mod += shift


def _execute_shifts(v):
    shift = change = 0.0
    for w in v.children[::-1]:
        w.x += shift
        w.mod += shift
        change += w.change
        shift += w.shift + change


def _ancestor(vil, v, default):
    return vil.ancestor if vil.ancestor in v.parent.children else default


def _second_walk(v, m=0.0, depth=0, lowest=None):
    v.x += m
    v.y = depth
    if lowest is None or v.x < lowest:
        lowest = v.x
    for w in v.children:
        lowest = _second_walk(w, m + v.mod, depth + 1, lowest)
    return lowest


def layout(nested):
    """Buchheim–Walker on ``(id, [children…])``: {id: (x, depth)}, x from 0 in sibling units."""
    root = _firstwalk(_Node(nested[0], nested[1]))
    lowest = _second_walk(root)
    out = {}

    def collect(v):
        out[v.pid] = (v.x - lowest, v.y)
        for c in v.children:
            collect(c)
    collect(root)
    return out


def descendants(tree, root, generations=3, living_label="Living person", title="Descendants of {name}"):
    """The descendant chart of ``root``; ``title`` as for ``ancestors``."""
    seen = set()

    def nest(pid, depth):
        seen.add(pid)
        kids = []
        if depth < generations:
            for c, _d in tree.descendants(pid, 1)[1:]:  # the children, by year of birth
                if c not in seen:
                    kids.append(nest(c, depth + 1))
        return (pid, kids)
    nested = nest(root, 0)
    pos = layout(nested)
    step_x, step_y = BOX_W + DESC_SIB, BOX_H + DESC_GEN
    width = (max(x for x, _d in pos.values()) + 1) * step_x - DESC_SIB
    height = (max(d for _x, d in pos.values()) + 1) * step_y - DESC_GEN
    body = []

    def links(node):
        pid, kids = node
        px, pd = pos[pid]
        for kid in kids:
            cx, cd = pos[kid[0]]
            x1, y1 = px * step_x + BOX_W / 2, pd * step_y + BOX_H
            x2, y2 = cx * step_x + BOX_W / 2, cd * step_y
            ym = y1 + DESC_GEN / 2
            dotted = " hypothesis" if tree.dotted(kid[0]) else ""   # T250: a deduced link too
            body.append(f'<path class="link{dotted}" d="M{x1:g},{y1:g} V{ym:g} H{x2:g} V{y2:g}"/>')
            links(kid)
    links(nested)
    for pid in sorted(pos, key=lambda p: (pos[p][1], pos[p][0])):
        x, d = pos[pid]
        body.append(_box(tree, pid, x * step_x, d * step_y, living_label))
    return _svg(width, height, body, title.format(name=tree.name(root, living_label)))


# Timeline of a person (GPS7-T4): one horizontal axis of years. The person's
# facts sit above it, their kin's landmarks below. A clash is a diamond with a
# "!" (error) or a "?" (warning), not only a colour: it reads in black and white
# and in the high-contrast template. A hypothesis has a dashed outline.

TL_W, TL_MARGIN, TL_ROW = 760, 48, 16
TL_STYLE = """
  .tl { --record: #1d6b3a; --index: #2a5d9f; --hypothesis: #8a6100; --clash: #b00020; --ink: #1b1b1b;
    --paper: #ffffff; --line: #555555; }
  .tl text { font: 12px system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink); }
  .tl .axis { stroke: var(--line); stroke-width: 1.5; }
  .tl .tick { stroke: var(--line); stroke-width: 1; }
  .tl .tick-label, .tl .kin { font-size: 11px; fill: #444444; }
  .tl .stem { stroke: #999999; stroke-width: 1; }
  .tl .mark { stroke-width: 2; }
  .tl .record .mark { fill: var(--record); stroke: var(--record); }
  .tl .index .mark { fill: var(--paper); stroke: var(--index); }
  .tl .hypothesis .mark { fill: var(--paper); stroke: var(--hypothesis); stroke-dasharray: 3 2; }
  .tl .clash .mark { fill: var(--paper); stroke: var(--clash); stroke-width: 3; stroke-dasharray: none; }
  .tl .clash text.sign { font-weight: bold; fill: var(--clash); }
  .tl .clash text.label { fill: var(--clash); font-weight: 600; }
  .tl .landmark { fill: #777777; }
"""


def _rows(items, x_of, char_w=6.6):
    """Each item's row, so that labels on one row never overlap: the first row with room."""
    ends, rows = [], []
    for text, x in ((i[0], x_of(i[1])) for i in items):
        width = len(text) * char_w
        left = x - width / 2
        for r, end in enumerate(ends):
            if left > end + 6:
                ends[r] = left + width
                rows.append(r)
                break
        else:
            ends.append(left + width)
            rows.append(len(ends) - 1)
    return rows


def timeline(tl, title, event_label, kin_label):
    """The SVG timeline of ``tl`` (report.timeline.model). ``event_label(e)`` and ``kin_label(r)`` give the
    words of a mark, in the report's language; ``title`` names the chart."""
    y0, y1 = tl["span"][0] - 2, tl["span"][1] + 2
    span = max(1, y1 - y0)

    def x_of(year):
        return TL_MARGIN + (year - y0) * (TL_W - 2 * TL_MARGIN) / span

    events = [(f"{event_label(e)} {e['year']}", e["year"], e) for e in tl["events"]]
    kin = [(f"{kin_label(r)} {r['year']}", r["year"], r) for r in tl["relatives"]]
    up = _rows(events, x_of)
    down = _rows(kin, x_of)
    top_rows = max(up, default=0) + 1
    axis = 24 + top_rows * TL_ROW + 16
    height = axis + 44 + (max(down, default=-1) + 1) * 14 + 8
    body = [f"<title>{escape(title)}</title>",
            "<desc>" + escape("; ".join(t for t, _y, _e in events + kin)) + "</desc>",
            f'<line class="axis" x1="{TL_MARGIN - 12}" y1="{axis}" x2="{TL_W - TL_MARGIN + 12}" y2="{axis}"/>']
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500) if span / s <= 12)
    for year in range((y0 // step + 1) * step, y1 + 1, step):
        x = x_of(year)
        body.append(f'<line class="tick" x1="{x:.1f}" y1="{axis - 4}" x2="{x:.1f}" y2="{axis + 4}"/>'
                    f'<text class="tick-label" x="{x:.1f}" y="{axis + 17}" text-anchor="middle">{year}</text>')
    for (text, year, e), row in zip(events, up):
        x, ly = x_of(year), axis - 18 - row * TL_ROW
        css = e["status"] + (f" clash {e['severity']}" if e["severity"] else "")
        tip = text + ("" if not e["findings"] else " — " + "; ".join(e["findings"]))
        if e["severity"]:
            mark = (f'<polygon class="mark" points="{x:.1f},{axis - 8} {x + 8:.1f},{axis} {x:.1f},{axis + 8} '
                    f'{x - 8:.1f},{axis}"/><text class="sign" x="{x:.1f}" y="{axis + 4}" text-anchor="middle">'
                    + ("!" if e["severity"] == "error" else "?") + "</text>")
        else:
            mark = f'<circle class="mark" cx="{x:.1f}" cy="{axis}" r="6"/>'
        body.append(f'<g class="{css}"><title>{escape(tip)}</title>'
                    f'<line class="stem" x1="{x:.1f}" y1="{ly + 3}" x2="{x:.1f}" y2="{axis - 8}"/>{mark}'
                    f'<text class="label" x="{x:.1f}" y="{ly}" text-anchor="middle">{escape(text)}</text></g>')
    for (text, year, r), row in zip(kin, down):
        x, ly = x_of(year), axis + 46 + row * 14
        body.append(f'<g><title>{escape(text + " — " + r["name"])}</title>'
                    f'<polygon class="landmark" points="{x:.1f},{axis + 24} {x + 4:.1f},{axis + 31} '
                    f'{x - 4:.1f},{axis + 31}"/>'
                    f'<text class="kin" x="{x:.1f}" y="{ly}" text-anchor="middle">{escape(text)}</text></g>')
    # as wide as the page allows, up to its own width: a template's column never cuts it
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="tl" viewBox="0 0 {TL_W} {height}" width="100%" '
            f'style="max-width:{TL_W}px;height:auto" role="img" aria-label="{escape(title)}">\n'
            f'<style>{TL_STYLE}</style>\n'
            + "\n".join(body) + "\n</svg>\n")


# Jurisdictions of a place over time (GPS2-T6): one row per jurisdiction, a bar from its
# start to its end on a shared axis of years. An unknown start or end is not a date: the
# bar runs to the edge and ends there with an open arrow, so it reads without colour. A
# jurisdiction derived from a rule has a dashed outline.

JU_W, JU_LABEL, JU_ROW = 760, 250, 22
JU_STYLE = """
  .ju { --bar: #2a5d9f; --derived: #8a6100; --ink: #1b1b1b; --paper: #ffffff; --line: #555555; }
  .ju text { font: 12px system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink); }
  .ju .axis { stroke: var(--line); stroke-width: 1.5; }
  .ju .tick { stroke: var(--line); stroke-width: 1; }
  .ju .grid { stroke: #dddddd; stroke-width: 1; }
  .ju .tick-label { font-size: 11px; fill: #444444; }
  .ju .bar { fill: var(--bar); fill-opacity: 0.25; stroke: var(--bar); stroke-width: 1.5; }
  .ju .derived .bar { fill: var(--derived); stroke: var(--derived); stroke-dasharray: 5 3; }
  .ju .open { fill: none; stroke: var(--line); stroke-width: 1.5; }
"""


def _year(value):
    try:
        return int(str(value)[:4]) if value else None
    except ValueError:
        return None


def jurisdictions(items, title, label, day, open_word="open", unknown_word="unknown"):
    """The SVG chart of a place's jurisdictions (``places.yaml``), or None when none has a date.
    ``label(j)`` names a row and ``day(value)`` writes a date, in the report's language."""
    known = [y for j in items for y in (_year(j.get("from")), _year(j.get("to"))) if y is not None]
    if not known:
        return None
    lo, hi = min(known), max(known)
    pad = max(10, (hi - lo) // 10)
    y0, y1 = (lo - pad) // 10 * 10, (hi + pad + 9) // 10 * 10
    span = max(1, y1 - y0)
    left, right = JU_LABEL, JU_W - 16

    def x_of(year):
        return left + (year - y0) * (right - left) / span

    axis = 12 + len(items) * JU_ROW + 6
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500) if span / s <= 10)
    body = [f"<title>{escape(title)}</title>"]
    words = []
    for year in range((y0 // step + 1) * step, y1 + 1, step):
        x = x_of(year)
        body.append(f'<line class="grid" x1="{x:.1f}" y1="8" x2="{x:.1f}" y2="{axis}"/>'
                    f'<line class="tick" x1="{x:.1f}" y1="{axis}" x2="{x:.1f}" y2="{axis + 5}"/>'
                    f'<text class="tick-label" x="{x:.1f}" y="{axis + 18}" text-anchor="middle">{year}</text>')
    body.append(f'<line class="axis" x1="{left}" y1="{axis}" x2="{right}" y2="{axis}"/>')
    for n, j in enumerate(items):
        top = 12 + n * JU_ROW
        start, end = _year(j.get("from")), _year(j.get("to"))
        a = x_of(start) if start is not None else left
        b = x_of(end) if end is not None else right
        b = max(b, a + 3)
        name = label(j)
        said = f"{name}: {day(j.get('from')) if j.get('from') else unknown_word} – " \
               f"{day(j.get('to')) if j.get('to') else open_word}" + (f" ({j['source']})" if j.get("source") else "")
        words.append(said)
        marks = ""
        mid = top + 8
        if start is None:
            marks += f'<polyline class="open" points="{a + 7:.1f},{mid - 6} {a + 1:.1f},{mid} {a + 7:.1f},{mid + 6}"/>'
        if end is None:
            marks += f'<polyline class="open" points="{b - 7:.1f},{mid - 6} {b - 1:.1f},{mid} {b - 7:.1f},{mid + 6}"/>'
        css = "row derived" if j.get("derived") else "row"
        body.append(f'<g class="{css}"><title>{escape(said)}</title>'
                    f'<text x="{left - 8}" y="{top + 12}" text-anchor="end">{escape(cut(name, 34))}</text>'
                    f'<rect class="bar" x="{a:.1f}" y="{top + 2}" width="{b - a:.1f}" height="12" rx="3"/>{marks}</g>')
    body.insert(1, "<desc>" + escape("; ".join(words)) + "</desc>")
    height = axis + 28
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="ju" viewBox="0 0 {JU_W} {height}" width="100%" '
            f'style="max-width:{JU_W}px;height:auto" role="img" aria-label="{escape(title)}">\n'
            f'<style>{JU_STYLE}</style>\n'
            + "\n".join(body) + "\n</svg>\n")