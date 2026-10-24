"""A fact written as the workshop writes it (WS2-T2).

A fact is a flow map, its keys in the workshop's order, wrapped before 110 columns
with the rest aligned under the brace; free text in double quotes, markers and
file names plain, ``annee`` an integer. A union is a block map, its values quoted
only when YAML would read them otherwise.
"""
from probandia.util import yamlio

WIDTH = 110
ORDER = ("date", "annee", "fait", "lieu", "statut", "volet", "chapitre", "volet_refute", "rapport", "source",
         "image", "note")
UNION_ORDER = ("epoux", "epouse", "annee", "date", "lieu", "statut", "volet", "chapitre", "volet_refute",
               "rapport", "source", "image", "note")
QUOTED = {"date", "lieu", "fait", "source", "note"}   # free text: always in double quotes in a flow map


def ordered(fact, order=ORDER):
    """The keys of a fact in the workshop's order; unknown ones after, as they come."""
    return [k for k in order if k in fact] + [k for k in fact if k not in order]


def quoted(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _plain_ok(text, flow):
    if not text or text != text.strip() or "\n" in text or (flow and any(c in text for c in ",{}[]")):
        return False
    try:
        return yamlio.loads(f"k: {text}\n") == {"k": text}
    except Exception:  # noqa: BLE001 — anything YAML would not read back as this string is quoted
        return False


def scalar(key, value, flow=True):
    if value is None:   # T175: the workshop writes "epoux: null" for a spouse it does not know
        return "null"
    if isinstance(value, bool):
        raise ValueError(f"{key}: no value of the workshop is {value!r}")
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if (flow and key in QUOTED) or key == "date" or not _plain_ok(text, flow):
        return quoted(text)
    return text


def flow(fact, prefix, width=WIDTH):
    """The lines of a fact as a flow map that starts after ``prefix`` (``"    deces: "``,
    ``"      - "``), without line endings."""
    pieces = [f"{k}: {scalar(k, fact[k])}" for k in ordered(fact)]
    if not pieces:
        return [prefix + "{}"]
    pad = " " * (len(prefix) + 1)
    lines, current = [], prefix + "{"
    for n, piece in enumerate(pieces):
        piece += "}" if n + 1 == len(pieces) else ","
        if current.endswith(("{",)):
            current += piece
        elif len(current) + 1 + len(piece) <= width:
            current += " " + piece
        else:
            lines.append(current)
            current = pad + piece
    return lines + [current]


def block(fact, indent=2, order=UNION_ORDER):
    """The lines of a union (or a new person's markers) as a block map, list item first."""
    keys = ordered(fact, order)
    lines = []
    for n, k in enumerate(keys):
        head = " " * indent + ("- " if n == 0 else "  ")
        lines.append(f"{head}{k}: {scalar(k, fact[k], flow=False)}")
    return lines
