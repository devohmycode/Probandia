"""Citations of sources.

A typed source (GPS6) is cited after the models of ``catalogues/citations/<lang>.yaml``,
in three forms: ``full`` (the entry of the list of sources), ``first`` (the first
reference note) and ``short`` (the notes after it). Its layers (the reproductions
consulted) follow the source in the first two forms. A required field that is missing
shows as ``[field?]`` in the text and is listed by ``missing()``: it is never invented.
A recommended field (GPS-D10) sits in an optional group: ``lacking()`` lists it.

A source without a type keeps the sentence of earlier versions, in every form:
repository, collection, reference, item, page, image, URL (consulted on <date>).
Missing parts are left out; the repository is required.
"""
import os
import re

from probandia import paths
from probandia.errors import UsageError
from probandia.i18n import _

FIELDS = ("repository", "collection", "reference", "item", "page", "image_no", "url", "accessed")
FORMS = ("full", "first", "short")
DATES = ("act_date", "issue_date", "accessed")

_catalogues = {}


def sentence(fields):
    """The citation sentence of a source without a type (a dict with the fields of sources.yaml)."""
    def get(key):
        value = fields.get(key)
        return str(value).strip() if value not in (None, "") else ""

    if not get("repository"):
        raise UsageError(_("a citation needs at least the repository"))
    parts = [get("repository")]
    for key in ("collection", "reference", "item"):
        if get(key):
            parts.append(get(key))
    if get("page"):
        parts.append(_("page {page}").format(page=get("page")))
    if get("image_no"):
        parts.append(_("image {image}").format(image=get("image_no")))
    text = ", ".join(parts)
    if get("url"):
        text += ", " + get("url")
    if get("accessed"):
        text += " " + _("(consulted on {date})").format(date=get("accessed"))
    return text + "."


def catalogue(lang=None):
    """The models of ``lang`` (a tag such as ``fr-CA``), else of its base language, else English."""
    from probandia.i18n import current, fallbacks

    for tag in fallbacks(lang or current()):
        if tag not in _catalogues:
            path = paths.data("catalogues", "citations", tag + ".yaml")
            if not os.path.exists(path):
                _catalogues[tag] = None
                continue
            from probandia.util import yamlio

            _catalogues[tag] = yamlio.load(path)
        if _catalogues[tag]:
            return _catalogues[tag]
    raise UsageError(_("no citation models found in catalogues/citations"))


def types():
    """The source types that have a model."""
    return list(catalogue("en")["types"])


TYPE_ALIASES = {"civil-record": "civil-registration", "civil-register": "civil-registration",
                "civil-status": "civil-registration", "parish-record": "parish-register",
                "decennial-tables": "decennial-table"}


def type_name(text):
    """A source type as an agent writes it (``civil_record``, ``civil_register``) in its model's own name
    (token-economy J9: guessed so, and refused, in each session of the bench of J8, 12 Oct. 2026)."""
    name = str(text).strip().lower().replace("_", "-").replace(" ", "-")
    return TYPE_ALIASES.get(name, name)


def required(source_type):
    """The fields a citation of this type cannot do without."""
    model = catalogue("en")["types"].get(source_type)
    return list(model["required"]) if model else []


def recommended(source_type):
    """The fields a complete citation of this type gives: their absence only warns (GPS-D10)."""
    model = catalogue("en")["types"].get(source_type)
    return list(model.get("recommended", [])) if model else []


def series(source_type):
    """The series of ``catalogues/source-types.yaml`` (GPS3) a record of this type belongs to, such as
    ``parish_registers`` for ``parish-register``; None for what is not an archive series (GPS-D12)."""
    model = catalogue("en")["types"].get(source_type)
    return model.get("series") if model else None


def _text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def missing(source):
    """The required fields of a typed source that are empty (none for a source without a type)."""
    return [f for f in required(source.get("type")) if not _text(source.get(f))]


def lacking(source):
    """The recommended fields of a typed source that are empty."""
    return [f for f in recommended(source.get("type")) if not _text(source.get(f))]


def write_date(value, cat):
    """``1785-03-14`` -> ``14 March 1785`` in the language of the models; partial dates too."""
    m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value or "")
    if not m:
        return value or ""
    year, month, day = m.groups()
    dates = cat["dates"]
    if not month:
        return year
    name = dates["months"][int(month) - 1]
    if not day:
        return dates["month"].format(month=name, y=year)
    d = dates.get("first_day", "1") if int(day) == 1 else str(int(day))
    return dates["day"].format(d=d, month=name, y=year)


def _values(fields, cat):
    out = {k: _text(v) for k, v in fields.items() if k != "layers"}
    names = fields.get("names") or []
    out["name"] = _text(names[0]) if names else ""
    if out.get("act"):
        out["act"] = cat["terms"].get(out["act"], out["act"])
    for key in DATES:
        if out.get(key):
            out[key] = write_date(out[key], cat)
    return out


def _parse(template):
    """A template as nested lists: text, ("field", name) and sub-lists for [ ... ] groups."""
    root = []
    stack = [root]
    for token in re.findall(r"\{\w+\}|\[|\]|[^\[\]{]+|\{", template):
        if token == "[":
            group = []
            stack[-1].append(group)
            stack.append(group)
        elif token == "]":
            stack.pop()
        elif token.startswith("{") and token.endswith("}"):
            stack[-1].append(("field", token[1:-1]))
        else:
            stack[-1].append(token)
    return root


def _render(nodes, values, holes, top):
    out = []
    for node in nodes:
        if isinstance(node, list):
            out.append(_render(node, values, holes, False))
        elif isinstance(node, tuple):
            value = values.get(node[1], "")
            if not value:
                if not top:
                    return ""
                holes.append(node[1])
                value = f"[{node[1]}?]"
            out.append(value)
        else:
            out.append(node)
    return "".join(out)


def _tidy(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r" ,", ",", text).lstrip(", ")
    return re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)


def apply(template, fields, cat, holes=None):
    """The text of one template for these fields."""
    return _tidy(_render(_parse(template), _values(fields, cat), [] if holes is None else holes, True))


def format(source, form="full", lang=None):
    """The citation of a source in one of the three forms, in ``lang`` (default: the current one)."""
    if form not in FORMS:
        raise UsageError(_("unknown citation form {form}: full, first or short").format(form=form))
    cat = catalogue(lang)
    model = cat["types"].get(source.get("type") or "")
    if model is None:
        if source.get("citation"):
            return source["citation"]
        return sentence(source)
    text = apply(model[form], source, cat)
    layers = [layer for layer in source.get("layers") or [] if layer.get("form") in cat["layers"]]
    if form == "short" or not layers:
        return text
    parts = [apply(cat["layers"][layer["form"]][form], layer, cat) for layer in layers]
    if form == "full":
        return " ".join([text] + parts)
    joined = cat["layer_join"].join([text.rstrip(".")] + [p.rstrip(".") for p in parts])
    return joined + "."


def page(source, lang=None):
    """What is proper to the record (folio, number, act, person, date, image…): the PAGE of a
    GEDCOM citation. The image of the first layer stands in for the source's own."""
    cat = catalogue(lang)
    fields = dict(source)
    if not fields.get("image_no"):
        fields["image_no"] = next((layer.get("image_no") for layer in source.get("layers") or []
                                   if layer.get("image_no")), None)
    return apply(cat["page"], fields, cat).strip(", ")


def forms(source, lang=None):
    """The three forms of a source's citation."""
    return {form: format(source, form, lang) for form in FORMS}


def ensure(source, lang=None):
    """The source with its citation filled in when it has none: the first note of a typed
    source, the sentence of a source without a type."""
    if not source.get("citation"):
        source = dict(source)
        source["citation"] = format(source, "first", lang) if source.get("type") else sentence(source)
    return source
