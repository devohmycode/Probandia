"""Report templates (optimize.md § 4, decision 4.1).

A template is one self-contained ``.html`` file, template and preview at once:

- its style in a ``<style>`` element, colours and fonts in CSS variables;
- its identity in ``<meta name="probandia:…">`` elements: ``id``, ``name``,
  ``version``, ``contract`` (the version of this contract), and optionally
  ``description`` and ``notes`` (``end``: all the notes after the report;
  ``chapter``: each chapter's notes after it);
- slots marked by comments, ``<!-- probandia:slot <name> -->…<!-- /probandia:slot -->``:
  their sample content is the preview, the engine replaces the whole slot,
  markers included; a slot left empty that fills its own lines is removed with
  them;
- fixed texts marked ``<!-- probandia:label <message id> -->…<!-- /probandia:label -->``,
  replaced by the label translated into the report's language (``labels.py``).

The engine also sets the ``lang`` attribute of ``<html>`` and drops the
``probandia:`` meta elements, which describe the template, not the report.
Everything else is copied byte for byte. The classes the engine emits are part
of the contract: ``erratum``, ``notes``, ``manual``, ``tree``, ``chapter-notes``,
``standard`` (the box of a question's conformity to the GPS, framed by an inline
style from ``--note`` and ``--note-rule``: a template may style it further), and ``status-record``, ``status-index``, ``status-hypothesis``, ``status-refuted``
on the note of a fact and its call.
"""
import hashlib
import html
import os
import re
from dataclasses import dataclass, field

CONTRACT = 1
REQUIRED_SLOTS = ("head", "title", "body", "notes", "manual")
OPTIONAL_SLOTS = ("toc", "generated", "research")
SLOTS = REQUIRED_SLOTS + OPTIONAL_SLOTS
REQUIRED_META = ("id", "name", "version", "contract")
BUILTIN = "default"
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SLOT = re.compile(r"<!-- probandia:slot ([a-z-]+) -->(.*?)<!-- /probandia:slot -->", re.S)
LABEL = re.compile(r"<!-- probandia:label (.+?) -->(.*?)<!-- /probandia:label -->", re.S)
META = re.compile(r'<meta name="probandia:([a-z-]+)" content="([^"]*)">')
META_LINE = re.compile(r'^[ \t]*<meta name="probandia:[a-z-]+" content="[^"]*">[ \t]*\n', re.M)
HTML_TAG = re.compile(r"<html\b[^>]*>", re.I)
LANG_ATTR = re.compile(r'\slang="[^"]*"')


@dataclass
class Template:
    path: str
    text: str
    meta: dict = field(default_factory=dict)
    scope: str = "builtin"

    @property
    def id(self):
        return self.meta.get("id") or os.path.splitext(os.path.basename(self.path))[0]

    @property
    def name(self):
        return self.meta.get("name") or self.id

    @property
    def version(self):
        return self.meta.get("version") or "1"

    @property
    def sha256(self):
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def notes(self):
        return "chapter" if self.meta.get("notes") == "chapter" else "end"

    def slots(self):
        return [m.group(1) for m in SLOT.finditer(self.text)]

    def fingerprint(self):
        return {"id": self.id, "version": str(self.version), "sha256": self.sha256}


def parse(text, path="", scope="builtin"):
    meta = {}
    for m in META.finditer(text):
        meta.setdefault(m.group(1), html.unescape(m.group(2)))
    return Template(path=path, text=text, meta=meta, scope=scope)


def load(path, scope="builtin"):
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    return parse(text.replace("\r\n", "\n"), path, scope)


def builtin_dir():
    from probandia.paths import data

    return data("report-templates")


def builtin(template_id=BUILTIN):
    return load(os.path.join(builtin_dir(), f"{template_id}.html"))


def _set_lang(text, lang):
    m = HTML_TAG.search(text)
    if not m:
        return text
    tag = m.group(0)
    value = f' lang="{html.escape(lang)}"'
    new = LANG_ATTR.sub(value, tag, count=1) if LANG_ATTR.search(tag) else tag[:-1] + value + ">"
    return text[:m.start()] + new + text[m.end():]


def _whole_lines(text, start, end):
    """(start, end) widened to whole lines when the slot is alone on its lines."""
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].strip() or not text.startswith("\n", end):
        return None
    return line_start, end + 1


def fill(template, values, t, lang):
    """The report: the template with its slots, labels and language filled."""
    text = META_LINE.sub("", template.text)
    text = _set_lang(text, lang)
    text = LABEL.sub(lambda m: html.escape(t(m.group(1).strip())), text)
    out, pos = [], 0
    for m in SLOT.finditer(text):
        value = values.get(m.group(1), "")
        start, end = m.start(), m.end()
        if not value:
            widened = _whole_lines(text, start, end)
            if widened:
                start, end = widened
        out.append(text[pos:start])
        out.append(value)
        pos = end
    out.append(text[pos:])
    return "".join(out)


# where templates are, and which one a research uses (4.3)

SCOPES = ("project", "user", "builtin")


def user_dir(config=None, environ=None):
    """``templates.dir``, else ``templates/`` next to the user's ``config.toml``."""
    from probandia.config import user_config_path

    chosen = (config.get("templates.dir") if config is not None else "") or ""
    if chosen:
        return os.path.abspath(os.path.expanduser(chosen))
    return os.path.join(os.path.dirname(user_config_path(environ)), "templates")


def folders(project=None, config=None, environ=None):
    """[(scope, folder)], the most precise first."""
    out = []
    if project:
        out.append(("project", os.path.join(project, "templates")))
    out.append(("user", user_dir(config, environ)))
    out.append(("builtin", builtin_dir()))
    return out


def available(project=None, config=None, environ=None):
    """Every template, the first of each id only (the project's hides the user's,
    which hides the built-in one)."""
    seen, out = set(), []
    for scope, folder in folders(project, config, environ):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".html"):
                continue
            try:
                tpl = load(os.path.join(folder, name), scope)
            except (OSError, UnicodeDecodeError):
                continue
            if tpl.id in seen or not tpl.meta.get("id") or tpl.id != name[:-5]:
                continue
            seen.add(tpl.id)
            out.append(tpl)
    return out


def find(template_id, project=None, config=None, environ=None):
    """The template ``template_id``, or None."""
    for scope, folder in folders(project, config, environ):
        path = os.path.join(folder, f"{template_id}.html")
        if os.path.isfile(path):
            return load(path, scope)
    return None


def choose(explicit=None, research_meta=None, family_meta=None, config=None):
    """(template id, where it was chosen), from the most precise level to the most
    general: ``--template``, the research, the family, the setting ``report.template``
    (its own layers: local, project, user), then ``default``."""
    if explicit:
        return explicit, "--template"
    for level, meta in (("research", research_meta), ("family", family_meta)):
        value = (meta or {}).get("template")
        if value:
            return str(value), level
    if config is not None:
        value = config.get("report.template")
        if value:
            return str(value), str(config.origin("report.template"))
    return BUILTIN, "default built-in"


# checks (4.4)

MAX_BYTES = 1024 * 1024   # images and fonts embedded as data: included
FORBIDDEN = (
    (re.compile(r"<\s*script\b", re.I), "a script"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "an event handler attribute"),
    (re.compile(r"javascript\s*:", re.I), "a javascript: link"),
    (re.compile(r"<\s*(iframe|frame|object|embed|applet|link|base|form|input|button|portal|svg:script)\b", re.I),
     "an element that loads or runs something"),
    (re.compile(r"<\s*meta\b[^>]*http-equiv", re.I), "a meta http-equiv"),
    (re.compile(r"@import\b", re.I), "an @import"),
    (re.compile(r"url\(\s*(?![\"']?\s*(data:|#))", re.I), "a url() that is not data:"),
    (re.compile(r"\s(src|srcset|poster|action|formaction|xlink:href)\s*=\s*(?![\"']?\s*data:)", re.I),
     "a source that is not data:"),
    (re.compile(r"\shref\s*=\s*(?![\"']?\s*#)", re.I), "a link outside the report"),
    (re.compile(r"expression\s*\(|behavior\s*:|-moz-binding", re.I), "a CSS expression or binding"),
)


def label_ids():
    """Every message id of the report labels (labels.py)."""
    from probandia.report import labels as L

    out = set()
    for name, value in vars(L).items():
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            out.add(value)
        elif isinstance(value, dict):
            out.update(v for v in value.values() if isinstance(v, str))
        elif isinstance(value, list):
            out.update(v for item in value if isinstance(item, tuple) for v in item[1:] if isinstance(v, str))
    return out


def check(tpl):
    """The reasons a template is refused; [] when it may be used."""
    reasons = []
    text = tpl.text
    size = len(text.encode("utf-8"))
    if size > MAX_BYTES:
        reasons.append(f"{size} bytes, more than the {MAX_BYTES} allowed")
    if not text.lstrip().lower().startswith("<!doctype html>"):
        reasons.append("it does not start with <!DOCTYPE html>")
    if not re.search(r'<meta charset="utf-8">', text, re.I):
        reasons.append('no <meta charset="utf-8">')
    if not HTML_TAG.search(text):
        reasons.append("no <html> element")
    for rx, what in FORBIDDEN:
        m = rx.search(text)
        if m:
            reasons.append(f"{what}: {text[m.start():m.start() + 40].strip()!r}")
    for key in REQUIRED_META:
        if not tpl.meta.get(key):
            reasons.append(f'no <meta name="probandia:{key}">')
    if tpl.meta.get("id") and not ID.match(tpl.meta["id"]):
        reasons.append(f"the id {tpl.meta['id']} is not a slug")
    if tpl.path and tpl.meta.get("id") and os.path.basename(tpl.path) != f"{tpl.meta['id']}.html":
        reasons.append(f"the file must be named {tpl.meta['id']}.html")
    if tpl.meta.get("contract") and tpl.meta["contract"] != str(CONTRACT):
        reasons.append(f"contract {tpl.meta['contract']}: this engine knows contract {CONTRACT}")
    if tpl.meta.get("notes") and tpl.meta["notes"] not in ("end", "chapter"):
        reasons.append(f"notes is {tpl.meta['notes']}: end or chapter")
    opens, closes = text.count("<!-- probandia:slot "), text.count("<!-- /probandia:slot -->")
    if opens != closes or opens != len(tpl.slots()):
        reasons.append("unbalanced slot markers")
    names = tpl.slots()
    for name in REQUIRED_SLOTS:
        if names.count(name) != 1:
            reasons.append(f"the slot {name} must appear once" if names.count(name) else f"no slot {name}")
    for name in sorted(set(names) - set(SLOTS)):
        reasons.append(f"unknown slot {name}")
    for name in sorted(set(n for n in names if n in OPTIONAL_SLOTS and names.count(n) > 1)):
        reasons.append(f"the slot {name} must appear once")
    known = label_ids()
    for m in LABEL.finditer(text):
        if m.group(1).strip() not in known:
            reasons.append(f"unknown label {m.group(1).strip()!r}")
    if text.count("<!-- probandia:label ") != len(LABEL.findall(text)):
        reasons.append("unbalanced label markers")
    ink, paper = (re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})\b", text) for name in ("ink", "paper"))
    if ink and paper and contrast(ink.group(1), paper.group(1)) < 4.5:
        reasons.append(f"the text contrast is {contrast(ink.group(1), paper.group(1)):.2f}:1, "
                       "under the 4.5:1 of WCAG AA")
    return reasons


def _luminance(hexa):
    n = int(hexa.lstrip("#"), 16)
    channels = [((n >> s) & 255) / 255 for s in (16, 8, 0)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """The WCAG contrast ratio of two ``#rrggbb`` colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
