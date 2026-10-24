"""Prose that promises more than the data (version-1.0.0 T252).

``render`` reads the text the agent wrote in each section (``body_md``), never the parts the engine
writes, and warns on:

- a source or a piece of evidence called primary or secondary (« source primaire », « preuve
  primaire », "primary source"…): a source is original or derivative, its information primary or
  secondary, the evidence direct or indirect; those axes are the facts' ``evidence``, not words of
  the prose. One warning per section;
- a sentence that carries a year or a date and cites no fact (``[[f:…]]``), nor a section that
  does (``[[s:…]]``). One warning per sentence. As V-7 counts the facts a section lists
  (``facts``) as cited, a sentence whose years are all years of a fact the section lists or cites
  elsewhere is not counted either.

Not counted as a year or a date: a reference's id, a code span or block, a link's address, an
italic or quoted title, and a number a word marks as something else (a page, a view, a folio,
inhabitants…).
"""
import re

from probandia.lang.dates import fold
from probandia.report.build import collect

CLASSED = re.compile(r"\b(?:sources?\s+(?:primaires?|secondaires?)|preuves?\s+primaires?"
                     r"|primary\s+(?:sources?|evidence)|secondary\s+sources?)\b", re.I)
FACT_OR_SECTION = re.compile(r"\[\[(?:f|s):[^\]\s]+\]\]")
FACT_REF = re.compile(r"\[\[f:([^\]\s]+)\]\]")

YEAR = re.compile(r"(?<![\w./,°#-])(1\d{3}|20\d{2})(?![\w°]|[.,]\d)")
NUMERIC_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/(\d{4}|\d{2})\b|\b\d{1,2}[.-]\d{1,2}[.-](1\d{3}|20\d{2})\b")
REPUBLICAN_YEAR = re.compile(r"\b[Aa]n\s+(?:I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XIV)\b")
_MONTHS = ("janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre "
           "january february march april may june july august september october november december "
           "januar februar marz maerz juni juli oktober dezember "
           "vendemiaire brumaire frimaire nivose pluviose ventose germinal floreal prairial messidor "
           "thermidor fructidor").split()
_MONTH = "(?:" + "|".join(sorted(set(_MONTHS), key=len, reverse=True)) + ")"
DAY_MONTH = re.compile(r"\b(?:[12]?\d|3[01])(?:er|st|nd|rd|th|\.)?\s+(?:de\s+)?" + _MONTH + r"\b")
MONTH_DAY = re.compile(r"\b" + _MONTH + r"\s+(?:[12]?\d|3[01])(?:st|nd|rd|th)?\b")
# a word before or after the number that makes it something other than a year (folded text)
NOT_A_YEAR_BEFORE = re.compile(r"(?:\b(?:no|n°|numero|number|p|pp|pages?|f°|fo|fol|folio|vues?|views?|cote"
                               r"|lignes?|lines?|lot|art|article|vol|volume|tome|images?)\.?|#)\s*$")
NOT_A_YEAR_AFTER = re.compile(r"^\s*(?:habitants?|inhabitants?|people|personnes?|ames|souls|feux|actes?|acts"
                              r"|records?|entries|entrees?|pages?|vues?|views?|km|m|kg|ha|hectares?|francs?"
                              r"|livres?|euros?|resultats?|results?|octets?|bytes?|tokens?|lignes?|lines?"
                              r"|mots?|words?|metres?|meters?)(?!\w)|^\s*[€$%]")

# what is not the agent's claim: removed before a year or a date is looked for
CODE_SPAN = re.compile(r"`[^`]*`")
REFERENCE = re.compile(r"\[\[[^\]]*\]\]|\[\^[^\]]*\]")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
URL = re.compile(r"\bhttps?://\S+")
ITALIC = re.compile(r"(?<![*\w])\*(?!\*)[^*\n]+?\*(?![*\w])|(?<!\w)_(?!_)[^_\n]+?_(?!\w)")
QUOTED = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")

ABBREVIATIONS = {"st", "ste", "mr", "mrs", "dr", "mme", "mlle", "me", "vve", "cf", "p", "pp", "vol", "no",
                 "art", "env", "ca", "c", "fol", "fo", "etc", "ibid", "id", "op", "cit", "vs", "sr", "jr"}
_BREAK = re.compile(r"[.!?…][\"»”)\]]*\s+")
_STARTS = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|\||#|>)")
EXCERPT = 90


def units(body):
    """The paragraphs, list items, table rows and headings of a Markdown text, fenced code left out."""
    out, current, fenced = [], [], False
    for line in (body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            if current:
                out.append(" ".join(current))
                current = []
            continue
        if fenced:
            continue
        if not stripped:
            if current:
                out.append(" ".join(current))
                current = []
            continue
        if _STARTS.match(stripped) or (current and current[0].startswith(("|", "#"))):
            if current:
                out.append(" ".join(current))
            current = [stripped]
        else:
            current.append(stripped)
    if current:
        out.append(" ".join(current))
    return out


def sentences(unit):
    """A unit cut into sentences: after . ! ? before a capital, a quote, a bracket, never after an
    abbreviation or an initial."""
    out, start = [], 0
    for m in _BREAK.finditer(unit):
        after = unit[m.end():m.end() + 1]
        if not after or not (after.isupper() or after in "«\"“[("):
            continue
        word = re.search(r"([^\s(\[«\"“]*)[.!?…][\"»”)\]]*\s+$", unit[start:m.end()])
        token = fold(word.group(1)) if word else ""
        if unit[m.start()] == "." and (token in ABBREVIATIONS or (len(token) == 1 and token.isalpha())):
            continue
        out.append(unit[start:m.end()].strip())
        start = m.end()
    if unit[start:].strip():
        out.append(unit[start:].strip())
    return out


def _claim_text(sentence):
    """The sentence without what is not the agent's claim (references, code, links, titles)."""
    text = CODE_SPAN.sub(" ", sentence)
    text = REFERENCE.sub(" ", text)
    text = LINK.sub(lambda m: m.group(1), text)
    text = URL.sub(" ", text)
    text = ITALIC.sub(" ", text)
    return QUOTED.sub(" ", text)


def dates(sentence):
    """(dated, years): whether the sentence carries a year or a date of its own, and its years."""
    text = _claim_text(sentence)
    folded = fold(text)
    years = set()
    for m in NUMERIC_DATE.finditer(text):
        year = m.group(1) or m.group(2)
        if len(year) == 4:
            years.add(int(year))
    for m in YEAR.finditer(folded):
        if not (NOT_A_YEAR_BEFORE.search(folded[:m.start()]) or NOT_A_YEAR_AFTER.search(folded[m.end():])):
            years.add(int(m.group(1)))
    dated = bool(years or NUMERIC_DATE.search(text) or REPUBLICAN_YEAR.search(text)
                 or DAY_MONTH.search(folded) or MONTH_DAY.search(folded))
    return dated, years


def excerpt(text):
    text = " ".join(text.split())
    if len(text) <= EXCERPT:
        return text
    cut = text[:EXCERPT].rsplit(" ", 1)[0]
    return cut + "…"


def fact_years(persons):
    """{fact id: the years of its date}, from the persons index."""
    out = {}
    for p in persons or []:
        for f in p.get("facts") or []:
            date = f.get("date") or {}
            out[f.get("id")] = {int(v[:4]) for v in (date.get("value"), date.get("end"))
                                if isinstance(v, str) and v[:4].isdigit()}
    return out


def check_section(sid, body, facts=(), years_of=None):
    """[(section id, kind, text)]: ``classed`` once with the words found, ``uncited`` per sentence.
    ``facts``: the facts the section lists; ``years_of``: {fact id: years}, from ``fact_years``."""
    found = []
    words = []
    for m in CLASSED.finditer(CODE_SPAN.sub(" ", body or "")):
        w = " ".join(m.group(0).split())
        if w.lower() not in (x.lower() for x in words):
            words.append(w)
    if words:
        found.append((sid, "classed", ", ".join(words)))
    years_of = years_of or {}
    backed = set()
    for fid in set(facts or ()) | set(FACT_REF.findall(body or "")):
        backed |= years_of.get(fid, set())
    for unit in units(body):
        for sentence in sentences(unit):
            if FACT_OR_SECTION.search(sentence):
                continue
            dated, years = dates(sentence)
            if not dated or (years and years <= backed and not _yearless_date(sentence)):
                continue
            found.append((sid, "uncited", excerpt(sentence)))
    return found


def _yearless_date(sentence):
    """True when the sentence holds a day and month with no year after them (« le 3 mai »)."""
    folded = fold(_claim_text(sentence))
    return any(not YEAR.match(folded[m.end():].lstrip(" ,"))
               for m in list(DAY_MONTH.finditer(folded)) + list(MONTH_DAY.finditer(folded)))


def imported(events):
    """The sections a workshop import wrote (``import`` agent) and no pass has rewritten since:
    the workshop's prose, which knows no ``[[f:…]]``."""
    out = set()
    for e in events:
        payload = e.get("payload") or {}
        by_import = (e.get("actor") or {}).get("agent") == "import"
        if e["type"] == "section.added" and by_import:
            out.add((payload.get("section") or {}).get("id"))
        elif e["type"] == "section.replaced" and not by_import:
            out.discard(payload.get("section"))
    return out


def check(events, persons=None):
    """The warnings of every section the agent wrote, in the order they were added; ``persons``,
    the family's persons index, tells the years of the facts a section lists."""
    sections, order = collect(events)[:2]
    years_of = fact_years(persons)
    skip = imported(events)
    found = []
    for sid in order:
        if sid in sections and sid not in skip:
            s = sections[sid]
            found += check_section(sid, s["body_md"], s["facts"], years_of)
    return found
