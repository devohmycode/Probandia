"""Reading genealogical dates. Nothing is ever guessed: a form that is not
understood raises ``Unrecognized``.

Forms read:
- ISO dates and numeric day/month/year (``1802-02-26``, ``26/02/1802``, ``26.2.1802``);
- month names in French, English, German and Latin, with their abbreviations,
  including ``7bre``, ``8bris``, ``9bre`` (November) and ``Xbris`` (December);
- day and year numbers written in words, in French and in Latin;
- the French Republican calendar, with its complementary days;
- fixed feast days, and movable feasts counted from Easter (Gregorian or Julian);
- qualifiers: about, before, after, between … and ….

A result is a dict: ``iso`` (the Gregorian date, ``YYYY``, ``YYYY-MM`` or
``YYYY-MM-DD``), ``end`` (for a range), ``qualifier``, ``calendar`` (the calendar
the text was written in) and ``original``.
"""
import re
import unicodedata

from probandia.lang import calendars as cal


class Unrecognized(ValueError):
    """The text is not a date this module can read with certainty."""


def fold(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower().replace("ſ", "s")


def _tokens(text):
    return re.findall(r"\d+[a-z]*|[a-z]+", fold(text))


# months

MONTHS = {}
for n, names in enumerate([
    "janvier janv jan january januar janner jaenner januarii ianuarii januarius ianuarius",
    "fevrier fevr fev feb february februar feber februarii februarius",
    "mars mar march marz maerz martii martius",
    "avril avr apr april aprilis",
    "mai may maii maius",
    "juin jun june juni junii iunii junius iunius",
    "juillet juil jul july juli julii iulii julius iulius",
    "aout aug august augusti augustus",
    "septembre sept sep september septembris 7bre 7bris 7ber 7embre",
    "octobre oct october oktober octobris 8bre 8bris 8ber",
    "novembre nov november novembris 9bre 9bris 9ber",
    "decembre dec december dezember decembris xbre xbris xber 10bre 10bris",
], start=1):
    for name in names.split():
        MONTHS[name] = n

REPUBLICAN_MONTHS = {
    "vendemiaire": 1, "brumaire": 2, "frimaire": 3, "nivose": 4, "pluviose": 5, "ventose": 6,
    "germinal": 7, "floreal": 8, "prairial": 9, "messidor": 10, "thermidor": 11, "fructidor": 12,
}
COMPLEMENTARY = {"vertu": 1, "genie": 2, "travail": 3, "opinion": 4, "recompenses": 5,
                 "recompense": 5, "revolution": 6}

# numbers in words

FR_UNITS = {"zero": 0, "un": 1, "une": 1, "premier": 1, "deux": 2, "trois": 3, "quatre": 4,
            "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
            "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20,
            "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}
FR_MULT = {"cent": 100, "cents": 100, "mil": 1000, "mille": 1000}

LA_ORDINAL = {"prim": 1, "secund": 2, "terti": 3, "quart": 4, "quint": 5, "sext": 6,
              "septim": 7, "octav": 8, "non": 9, "decim": 10, "undecim": 11, "duodecim": 12,
              "vigesim": 20, "vicesim": 20, "trigesim": 30, "tricesim": 30,
              "quadragesim": 40, "quinquagesim": 50, "sexagesim": 60, "septuagesim": 70,
              "octogesim": 80, "nonagesim": 90, "centesim": 100, "ducentesim": 200,
              "trecentesim": 300, "quadringentesim": 400, "quingentesim": 500,
              "sexcentesim": 600, "septingentesim": 700, "octingentesim": 800,
              "nongentesim": 900, "millesim": 1000}
LA_CARDINAL = {"unus": 1, "una": 1, "uno": 1, "duo": 2, "duobus": 2, "tres": 3, "tribus": 3,
               "quatuor": 4, "quattuor": 4, "quinque": 5, "sex": 6, "septem": 7, "octo": 8,
               "novem": 9, "decem": 10, "undecim": 11, "duodecim": 12, "viginti": 20,
               "triginta": 30, "quadraginta": 40, "quinquaginta": 50, "sexaginta": 60,
               "septuaginta": 70, "octoginta": 80, "nonaginta": 90, "centum": 100,
               "ducenti": 200, "ducentesimo": 200, "trecenti": 300, "quadringenti": 400,
               "quingenti": 500, "sexcenti": 600, "septingenti": 700, "octingenti": 800,
               "nongenti": 900, "mille": 1000}
LA_ENDINGS = ("us", "a", "o", "um", "ae", "am", "i", "e")
LA_FILLER = {"die", "dies", "diei", "mensis", "anno", "annus", "domini", "dni", "et", "ac",
             "salutis", "currentis", "eiusdem", "ejusdem", "hora"}
FR_FILLER = {"le", "l", "la", "du", "de", "an", "et", "l", "en", "annee", "jour", "mois", "dit"}


def la_ordinal(token):
    for stem, value in sorted(LA_ORDINAL.items(), key=lambda kv: -len(kv[0])):
        if token.startswith(stem) and token[len(stem):] in LA_ENDINGS:
            return value
    return LA_CARDINAL.get(token)


def la_number(tokens):
    """The sum of consecutive Latin number words, or None."""
    total, seen = 0, False
    for t in tokens:
        v = la_ordinal(t)
        if v is None:
            return None
        if v == 1000 and total:
            total *= 1000  # bis millesimo…
        else:
            total += v
        seen = True
    return total if seen else None


def fr_number(tokens):
    """French number words (un … mil huit cent cinquante et un), or None."""
    total, current, seen = 0, 0, False
    for t in tokens:
        if t == "et":
            continue
        if t in FR_UNITS:
            v = FR_UNITS[t]
            if t in ("vingt", "vingts") and current in (4,):
                current *= 20  # quatre-vingt(s)
            else:
                current += v
        elif t in FR_MULT:
            m = FR_MULT[t]
            if m == 1000:
                total += (current or 1) * 1000
                current = 0
            else:
                current = (current or 1) * m
        else:
            return None
        seen = True
    return total + current if seen else None


def _roman(text):
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    text = text.lower()
    if not text or any(c not in values for c in text):
        return None
    total = 0
    for i, c in enumerate(text):
        v = values[c]
        if i + 1 < len(text) and values[text[i + 1]] > v:
            total -= v
        else:
            total += v
    return total


# feasts

FIXED_FEASTS = {  # folded names -> (month, day)
    "noel": (12, 25), "nativite": (12, 25), "weihnachten": (12, 25), "christmas": (12, 25),
    "nativitatis": (12, 25),
    "toussaint": (11, 1), "allerheiligen": (11, 1), "all saints": (11, 1), "omnium sanctorum": (11, 1),
    "saint martin": (11, 11), "st martin": (11, 11), "martini": (11, 11), "martinmas": (11, 11),
    "sancti martini": (11, 11),
    "saint jean baptiste": (6, 24), "saint jean": (6, 24), "johannistag": (6, 24),
    "johanni": (6, 24), "midsummer": (6, 24), "sancti joannis baptistae": (6, 24),
    "assomption": (8, 15), "mariae himmelfahrt": (8, 15), "assumption": (8, 15),
    "assumptionis": (8, 15),
    "saint michel": (9, 29), "michaelis": (9, 29), "michaelmas": (9, 29), "sancti michaelis": (9, 29),
    "chandeleur": (2, 2), "lichtmess": (2, 2), "candlemas": (2, 2), "purificationis": (2, 2),
    "annonciation": (3, 25), "mariae verkundigung": (3, 25), "lady day": (3, 25),
    "annuntiationis": (3, 25),
    "epiphanie": (1, 6), "les rois": (1, 6), "dreikonigstag": (1, 6), "epiphany": (1, 6),
    "epiphaniae": (1, 6),
    "saint etienne": (12, 26), "stephanstag": (12, 26),
    "saint nicolas": (12, 6), "nikolaus": (12, 6), "sancti nicolai": (12, 6),
    "saint barthelemy": (8, 24), "bartholomai": (8, 24),
    "saint remi": (10, 1), "saint andre": (11, 30), "andreas": (11, 30),
    "saint thomas": (12, 21), "saint pierre et saint paul": (6, 29), "saint pierre": (6, 29),
    "peter und paul": (6, 29), "saint laurent": (8, 10), "laurentius": (8, 10),
    "sainte madeleine": (7, 22), "saint georges": (4, 23), "georgi": (4, 23),
    "saint jacques": (7, 25), "jakobi": (7, 25), "saint luc": (10, 18),
    "saint sylvestre": (12, 31), "silvester": (12, 31),
}
MOVABLE_FEASTS = {  # folded names -> days from Easter Sunday
    "paques": 0, "ostern": 0, "easter": 0, "pascha": 0, "paschae": 0,
    "lundi de paques": 1, "ostermontag": 1, "easter monday": 1,
    "rameaux": -7, "palmsonntag": -7, "palm sunday": -7,
    "vendredi saint": -2, "karfreitag": -2, "good friday": -2,
    "mardi gras": -47, "cendres": -46, "aschermittwoch": -46, "ash wednesday": -46,
    "quasimodo": 7, "ascension": 39, "christi himmelfahrt": 39, "ascensionis": 39,
    "pentecote": 49, "pfingsten": 49, "pentecost": 49, "whitsun": 49, "pentecostes": 49,
    "lundi de pentecote": 50, "pfingstmontag": 50,
    "trinite": 56, "trinitatis": 56, "trinity sunday": 56,
    "fete dieu": 60, "fronleichnam": 60, "corpus christi": 60,
}

QUALIFIERS = [
    ("about", r"^(?:vers|environ|env\.?|ca\.?|circa|c\.|um|gegen|about|abt\.?|around|approx\.?|"
              r"approximately|circiter)\s+"),
    ("before", r"^(?:avant|av\.|before|bef\.?|vor)\s+(?:le\s+)?"),
    ("after", r"^(?:apres|after|aft\.?|nach)\s+(?:le\s+)?"),
]
BETWEEN = [r"^(?:entre|between|zwischen)\s+(.+?)\s+(?:et|and|und)\s+(.+)$",
           r"^(?:de|du|from|von)\s+(.+?)\s+(?:a|au|to|bis)\s+(.+)$",
           r"^(\d{4})\s*-\s*(\d{4})$"]
# the hour a workshop writes after a day (« 9 oct. 1930 à 5 h 30 »): kept in the original only
HOUR = re.compile(r"\s+(?:a|at|um)\s+\d{1,2}\s*h(?:\s*\d{1,2})?$")


def _result(iso, calendar="gregorian", qualifier="exact", end=None):
    return {"iso": iso, "end": end, "qualifier": qualifier, "calendar": calendar}


def _check(y, m, d, julian=False):
    ok = cal.valid_julian(y, m, d) if julian else cal.valid_gregorian(y, m, d)
    if not ok:
        raise Unrecognized(f"{y}-{m}-{d} does not exist")


def _year(tokens):
    """A year: digits, French words or Latin words."""
    if len(tokens) == 1 and tokens[0].isdigit() and 1 <= len(tokens[0]) <= 4:
        if len(tokens[0]) < 3:
            return None  # a two-digit year would be a guess
        return int(tokens[0])
    words = [t for t in tokens if t not in ("anno", "domini", "dni", "salutis", "an", "en", "l")]
    for reader in (fr_number, la_number):
        v = reader(words)
        if v and v >= 100:
            return v
    return None


def _day(tokens):
    if len(tokens) == 1 and re.fullmatch(r"\d{1,2}", tokens[0]):
        return int(tokens[0])
    if len(tokens) == 1 and re.fullmatch(r"\d{1,2}(?:er|e|eme|st|nd|rd|th)", tokens[0]):
        return int(re.match(r"\d+", tokens[0]).group())
    words = [t for t in tokens if t not in ("le", "die", "diei", "the", "am", "den")]
    for reader in (fr_number, la_number):
        v = reader(words)
        if v and 1 <= v <= 31:
            return v
    return None


# the readers


def _read_iso(text):
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", text)
    if not m:
        return None
    y = int(m.group(1))
    if m.group(3):
        mo, d = int(m.group(2)), int(m.group(3))
        _check(y, mo, d)
        return _result(cal.iso(y, mo, d))
    if m.group(2):
        mo = int(m.group(2))
        if not 1 <= mo <= 12:
            raise Unrecognized("month")
        return _result(cal.iso(y, mo))
    return _result(cal.iso(y))


def _read_numeric(text):
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    _check(y, mo, d)
    return _result(cal.iso(y, mo, d))


def _read_republican(text):
    f = fold(text)
    if " an " not in f" {f} " and not re.search(r"\ban\b", f):
        return None
    m = re.search(r"\ban\s+([ivxlc]+|\d{1,2})\b(.*)$", f)
    if not m:
        return None
    year = _roman(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
    if m.group(2).strip(" .,;"):
        return None
    before = f[: m.start()]
    tokens = [t for t in _tokens(before) if t not in ("le", "l", "du", "de", "la", "jour", "des")]
    if not tokens:
        span = cal.republican_year_span(year)
        if not span:
            raise Unrecognized("republican year")
        return _result(cal.iso(*span[0]), "republican", "between", cal.iso(*span[1]))
    month = next((REPUBLICAN_MONTHS[t] for t in tokens if t in REPUBLICAN_MONTHS), None)
    comp = next((COMPLEMENTARY[t] for t in tokens if t in COMPLEMENTARY), None)
    if month:
        day_tokens = tokens[: tokens.index(next(t for t in tokens if t in REPUBLICAN_MONTHS))]
        if not day_tokens:
            span = cal.republican_to_gregorian(year, month, 1)
            last = cal.republican_to_gregorian(year, month, 30)
            if not span:
                raise Unrecognized("republican month")
            return _result(cal.iso(*span), "republican", "between", cal.iso(*last))
        day = _day(day_tokens)
        if day is None:
            return None
        g = cal.republican_to_gregorian(year, month, day)
    elif comp or "complementaire" in tokens or "sansculottide" in tokens or "sanculottide" in tokens:
        if comp is None:
            num = [t for t in tokens if t not in ("complementaire", "sansculottide", "sanculottide",
                                                  "sans", "culottide")]
            comp = _day(num) if num else None
        if comp is None:
            return None
        g = cal.republican_to_gregorian(year, 13, comp)
    else:
        return None
    if not g:
        raise Unrecognized("this republican date did not exist")
    return _result(cal.iso(*g), "republican")


def _read_month_text(text, julian):
    """Day, month name and year, in any order the languages use."""
    tokens = _tokens(text)
    idx = [i for i, t in enumerate(tokens) if t in MONTHS]
    if len(idx) != 1:
        return None
    i = idx[0]
    month = MONTHS[tokens[i]]
    before = [t for t in tokens[:i] if t not in ("le", "die", "mensis", "the", "of", "am", "den",
                                                 "de", "du", "l")]
    after = [t for t in tokens[i + 1:] if t not in ("de", "of", "mensis", "l", "an")]
    if "anno" in tokens and tokens.index("anno") < i:
        return None
    if after and after[0] in ("anno",):
        after = after[1:]
    day = None
    if before:
        day = _day(before)
        if day is None:
            return None
    elif after and re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?", after[0]) and len(after) >= 2:
        day = int(re.match(r"\d+", after[0]).group())
        after = after[1:]
    if not after:
        return None
    year = _year(after)
    if year is None:
        return None
    calendar = "julian" if julian else "gregorian"
    if day is None:
        return _result(cal.iso(year, month), calendar)
    _check(year, month, day, julian)
    if julian:
        return _result(cal.iso(*cal.julian_to_gregorian(year, month, day)), "julian")
    return _result(cal.iso(year, month, day))


def _read_feast(text, julian):
    f = " ".join(_tokens(re.sub(r"[-'’]", " ", text)))
    m = re.fullmatch(r"(?:(?:le|la|jour de la|fete de|am|in festo|festo|on|feast of)\s+)*(.+?)\s+(\d{4})", f)
    if not m:
        return None
    name, year = m.group(1), int(m.group(2))
    name = re.sub(r"^(?:la|le|st|ste|sainte)\s+", lambda x: "saint " if x.group(0).startswith("st") else "", name)
    name = name.replace("ste ", "sainte ")
    if name in FIXED_FEASTS:
        mo, d = FIXED_FEASTS[name]
        if julian:
            return _result(cal.iso(*cal.julian_to_gregorian(year, mo, d)), "julian")
        return _result(cal.iso(year, mo, d))
    if name in MOVABLE_FEASTS:
        easter = cal.easter_julian(year) if julian else cal.easter_gregorian(year)
        day = cal.add_days(easter, MOVABLE_FEASTS[name], julian=julian)
        if julian:
            return _result(cal.iso(*cal.julian_to_gregorian(*day)), "julian")
        return _result(cal.iso(*day))
    return None


def _read_one(text, julian=False):
    text = text.strip().strip(".,;")
    f = fold(text)
    for reader in (_read_iso, _read_numeric):
        r = reader(f)
        if r:
            if julian and r["iso"].count("-") == 2:
                y, m, d = (int(x) for x in r["iso"].split("-"))
                if not cal.valid_julian(y, m, d):
                    raise Unrecognized("julian")
                return _result(cal.iso(*cal.julian_to_gregorian(y, m, d)), "julian")
            return r
    for reader in (_read_republican,):
        r = reader(text)
        if r:
            return r
    for reader in (_read_month_text, _read_feast):
        r = reader(text, julian)
        if r:
            return r
    tokens = _tokens(text)
    year = _year([t for t in tokens if t not in ("anno", "domini", "an", "en", "l")])
    if year is not None and len(tokens) <= 8 and not any(t in MONTHS for t in tokens):
        if all(t.isdigit() or fr_number([t]) is not None or la_ordinal(t) is not None
               or t in ("anno", "domini", "en", "an", "et", "l") for t in tokens):
            return _result(cal.iso(year))
    raise Unrecognized(text)


def read(text, calendar="gregorian"):
    """Reads a date. ``calendar``: the calendar of dates written without one
    (``julian`` for regions that had not yet adopted the Gregorian reform)."""
    original = text
    julian = calendar == "julian"
    f = fold(text).strip()
    f = HOUR.sub("", re.sub(r"\s+", " ", f))
    for pattern in BETWEEN:
        m = re.match(pattern, f)
        if m:
            a = _read_one(m.group(1), julian)
            b = _read_one(m.group(2), julian)
            out = _result(a["iso"], a["calendar"], "between", b["end"] or b["iso"])
            out["original"] = original
            return out
    qualifier = "exact"
    for name, pattern in QUALIFIERS:
        m = re.match(pattern, f)
        if m:
            qualifier = name
            f = f[m.end():]
            break
    r = _read_one(f, julian)
    if qualifier != "exact":
        if r["qualifier"] == "between":
            raise Unrecognized("a qualifier on a range")
        r["qualifier"] = qualifier
    r["original"] = original
    return r


FR_MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
FR_QUALIFIERS = {"about": "vers ", "before": "avant ", "after": "après "}


def _french_one(iso):
    y, *rest = iso.split("-")
    out = [str(int(y))]
    if rest:
        out.insert(0, FR_MONTHS[int(rest[0]) - 1])
    if len(rest) > 1:
        out.insert(0, "1er" if int(rest[1]) == 1 else str(int(rest[1])))
    return " ".join(out)


def french(iso, qualifier="exact", end=None):
    """A date as a French workshop writes it, read back by ``read``: « 29 juil. 1984 »,
    « sept. 1929 », « vers 1850 », « avant 1890 », « entre 1839 et 1849 »."""
    if qualifier == "between" and end:
        return f"entre {_french_one(iso)} et {_french_one(end)}"
    return FR_QUALIFIERS.get(qualifier, "") + _french_one(iso)


def from_julian(text):
    """A Julian calendar date, converted to the Gregorian calendar."""
    return read(text, calendar="julian")


def age_range(age, on):
    """Born between ``on - age - 1 year + 1 day`` and ``on - age years``."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", on.strip())
    if not m:
        raise Unrecognized(on)
    y, mo, d = (int(x) for x in m.groups())
    _check(y, mo, d)
    latest = _minus_years(y, mo, d, age)
    earliest = cal.add_days(_minus_years(y, mo, d, age + 1), 1)
    return {"iso": cal.iso(*earliest), "end": cal.iso(*latest), "qualifier": "between",
            "calendar": "gregorian", "original": f"{age} on {on}"}


def _minus_years(y, m, d, n):
    y -= n
    if m == 2 and d == 29 and not cal.valid_gregorian(y, 2, 29):
        d = 28
    return y, m, d
