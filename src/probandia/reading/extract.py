"""Visible text of a page, and its densest text block.

trafilatura is used when it is installed; otherwise the built-in extractor
drops ``script``, ``style``, ``nav``, ``header``, ``footer`` and similar parts,
and keeps the block with the most text and the fewest links.
"""
import html
import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "template", "svg", "head"}
CHROME = {"nav", "header", "footer", "aside", "form", "menu"}
BLOCKS = {"article", "main", "section", "div", "td", "body"}
# Elements that end a paragraph: their text is kept apart from the next one.
PARAGRAPHS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre",
              "section", "article", "dd", "dt", "table", "ul", "ol"}
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source",
        "track", "wbr", "param"}


def visible_text(page):
    """All the text a reader would see, scripts and styles left out."""
    text = re.sub(r"(?is)<(script|style|noscript|template|svg)\b[^>]*>.*?</\1\s*>", " ", page)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def main_text(page):
    """The text without the page's chrome: navigation, header, footer, scripts."""
    text = re.sub(r"(?is)<(script|style|noscript|template|svg|nav|header|footer|aside)\b[^>]*>.*?</\1\s*>",
                  " ", page)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def title(page):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""


class _Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # [tag, text parts, link chars]
        self.skip = 0
        self.blocks = []     # (score, text)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        if tag in SKIP or tag in CHROME:
            self.skip += 1
        self.stack.append([tag, [], 0])

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            t, parts, links = self.stack.pop()
            if t in SKIP or t in CHROME:
                self.skip = max(0, self.skip - 1)
            text = re.sub(r"[^\S\n]+", " ", " ".join(parts))
            text = re.sub(r"\s*\n\s*\n\s*", "\n\n", text).strip()
            if self.stack:
                self.stack[-1][1].append(f"\n\n{text}\n\n" if t in PARAGRAPHS else text)
                self.stack[-1][2] += links
            if t in BLOCKS and text:
                density = links / max(1, len(text))
                self.blocks.append((len(text) * (1 - min(density, 1)), text))
            if t == tag:
                break

    def handle_data(self, data):
        if self.skip or not self.stack:
            return
        self.stack[-1][1].append(data)
        if any(t == "a" for t, _p, _l in self.stack):
            self.stack[-1][2] += len(data.strip())


def densest_block(page):
    parser = _Blocks()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        return main_text(page)
    while parser.stack:
        parser.handle_endtag(parser.stack[-1][0])
    if not parser.blocks:
        return main_text(page)
    best = max(parser.blocks, key=lambda b: b[0])[1]
    return best


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.href, self.parts = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.parts = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((re.sub(r"\s+", " ", "".join(self.parts)).strip(), self.href))
            self.href = None

    def handle_data(self, data):
        if self.href:
            self.parts.append(data)


def links(page, pattern, base=None):
    """token-economy D1: [(text, address)] of the links whose text or address holds
    ``pattern`` (any case), from HTML or from a reader's markdown, without duplicates."""
    from urllib.parse import urljoin

    parser = _Links()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        pass
    found = parser.links + [(t.strip(), h) for t, h in re.findall(r"\[([^\]]*)\]\((\S+?)\)", page)]
    want, out = pattern.casefold(), []
    for text, href in found:
        href = urljoin(base, href) if base else href
        if (want in text.casefold() or want in href.casefold()) and (text, href) not in out:
            out.append((text, href))
    return out


def grep(text, pattern):
    """token-economy D1: the lines of ``text`` that hold ``pattern`` (any case), with one
    line of context each side; ``…`` between groups that are not next to each other."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    want = pattern.casefold()
    keep = sorted({j for i, ln in enumerate(lines) if want in ln.casefold()
                   for j in (i - 1, i, i + 1) if 0 <= j < len(lines)})
    out = []
    for n, j in enumerate(keep):
        if n and j != keep[n - 1] + 1:
            out.append("…")
        out.append(lines[j])
    return out


class _Select(HTMLParser):
    def __init__(self, tag, kind, name):
        super().__init__(convert_charrefs=True)
        self.want, self.depth, self.parts, self.done = (tag, kind, name), 0, [], False

    def _matches(self, tag, attrs):
        want_tag, kind, name = self.want
        a = dict(attrs)
        return ((not want_tag or tag == want_tag)
                and (kind is None or (kind == "#" and a.get("id") == name)
                     or (kind == "." and name in (a.get("class") or "").split())))

    def handle_starttag(self, tag, attrs):
        if self.done or tag in VOID:
            return
        if self.depth:
            self.depth += 1
        elif self._matches(tag, attrs):
            self.depth = 1
        if self.depth and tag in PARAGRAPHS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.depth and tag not in VOID:
            self.depth -= 1
            self.parts.append("\n" if tag in PARAGRAPHS else "")
            self.done = self.done or not self.depth

    def handle_data(self, data):
        if self.depth and not self.done:
            self.parts.append(data)


def select(page, selector):
    """token-economy D1: the text of the first block that ``selector`` names: a tag,
    ``.class``, ``#id``, or a tag with either (``div.results``); ``""`` when none."""
    m = re.fullmatch(r"([a-zA-Z][\w-]*)?(?:([.#])([\w-]+))?", selector.strip())
    if not m or not (m.group(1) or m.group(2)):
        raise ValueError(selector)
    parser = _Select((m.group(1) or "").lower(), m.group(2), m.group(3))
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        pass
    text = re.sub(r"[^\S\n]+", " ", "".join(parser.parts))
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def extract(page):
    """(text, extractor name)."""
    try:
        import trafilatura  # optional
        text = trafilatura.extract(page)
        if text:
            return text, "trafilatura"
    except ImportError:
        pass
    return densest_block(page), "built-in"
