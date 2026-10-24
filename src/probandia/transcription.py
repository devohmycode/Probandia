"""Transcriptions of records (SPECS § 9.13).

A transcription is ``evidence/transcriptions/<source>.md`` in the family folder:

- a header table: source, image, language, script, and the image's state
  (``good``, or what is wrong with it: then the register's other copy is sought);
- ``## Diplomatic transcription``: numbered lines, as written;
- ``## Normalised transcription``: modern spelling, dates checked by ``dates``;
- ``## Persons``: role, as written, normalised form, age, residence or
  occupation, relation, signature;
- ``## Uncertain readings``: one line per doubt;
- ``## Not understood``: the passages read but not understood (T246).

Notation: ``[…]`` a gap, ``word[?]`` a doubtful reading, ``{struck: …}``
struck-out text, ``{margin: …}`` a note in the margin; T246: ``{blank}`` a space
the writer left empty (a clue, not a gap), ``{above: …}`` added between the
lines, ``{over: a > b}`` ``a`` written over as ``b``, ``{hand: …}`` in another,
later hand, ``{restored: …}`` supposed, not read. A doubtful reading or a mark
behind a fact sets that fact's ``uncertain_reading``; nothing restored or not
understood goes into the normalised transcription.

A second reading of the same act, made without the first (T245), is
``<source>.2.md`` next to it; ``compare`` lists where the two differ.
"""
import difflib
import os
import re
import shutil
import subprocess

from probandia.errors import ProbandiaError
from probandia.i18n import _

SECTIONS = ("Diplomatic transcription", "Normalised transcription", "Persons", "Uncertain readings")
PERSON_COLUMNS = ("Role", "As written", "Normalised", "Age", "Residence or occupation", "Relation", "Signature")
HEADER_KEYS = ("Source", "Image", "Language", "Script")
DOUBT = re.compile(r"(\S+?)\[\?\]")
# T246: the marks a fact may rest on, each a doubt; ``{struck: …}`` and ``{margin: …}`` are not
MARK = re.compile(r"\{blank\}|\{(above|over|hand|restored):\s*([^}]*)\}")
UNCLEAR = "Not understood"
GOOD = "good"
GAP = "[…]"
REGION_MAX = 2576
OVERVIEW = 1500


def path_for(family_folder, source):
    return os.path.join(family_folder, "evidence", "transcriptions", f"{source}.md")


def second_path(family_folder, source):
    """T245: the second reading of a source, made blind, next to the first."""
    return path_for(family_folder, f"{source}.2")


def template(source, image, language="fr", script="cursive", lines=None):
    """The empty skeleton of a transcription; ``lines`` fills the diplomatic part."""
    out = [f"# Transcription — {source}", "", "| Field | Value |", "|---|---|",
           f"| Source | {source} |", f"| Image | {image} |", f"| Language | {language} |",
           f"| Script | {script} |", f"| Image state | {GOOD} |", "", "## Diplomatic transcription", ""]
    body = lines or ["…"]
    out += [f"{i}. {line}" for i, line in enumerate(body, 1)]
    out += ["", "## Normalised transcription", "", "…", "", "## Persons", "",
            "| " + " | ".join(PERSON_COLUMNS) + " |", "|" + "---|" * len(PERSON_COLUMNS), "",
            "## Uncertain readings", "", "- none", "", f"## {UNCLEAR}", "", "- none", ""]
    return "\n".join(out)


def sections(text):
    """{title: body} of the ``##`` sections."""
    out, title, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if title:
                out[title] = "\n".join(buf).strip()
            title, buf = m.group(1), []
        elif title:
            buf.append(line)
    if title:
        out[title] = "\n".join(buf).strip()
    return out


def header(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*(Source|Image state|Image|Language|Script)\s*\|\s*(.*?)\s*\|\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def persons(body):
    rows = []
    for line in body.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").strip()) <= {"-", ":", " "}:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[:2] == ["Role", "As written"]:
            continue
        rows.append(dict(zip(PERSON_COLUMNS, cells + [""] * (len(PERSON_COLUMNS) - len(cells)))))
    return rows


def check(text):
    """(problems, parsed): the parts that are missing or malformed, and what was read."""
    problems = []
    head = header(text)
    for k in HEADER_KEYS:
        if not head.get(k):
            problems.append(f"header: no {k}")
    parts = sections(text)
    for s in SECTIONS:
        if s not in parts:
            problems.append(f"no section {s}")
    diplomatic = parts.get("Diplomatic transcription", "")
    numbered = [line for line in diplomatic.splitlines() if line.strip()]
    lines = []
    for i, line in enumerate(numbered, 1):
        m = re.match(r"^(\d+)\.\s?(.*)$", line)
        if not m or int(m.group(1)) != i:
            problems.append(f"diplomatic line {i} is not numbered {i}.")
            continue
        lines.append(m.group(2))
    if lines == ["…"]:
        problems.append("the diplomatic transcription is empty")
    people = persons(parts.get("Persons", ""))
    if not people:
        problems.append("the table of persons is empty")
    doubts = []
    for i, line in enumerate(lines, 1):
        for m in DOUBT.finditer(line):
            doubts.append({"line": i, "word": m.group(1)})
    listed = _listed(parts.get("Uncertain readings", ""))
    if doubts and not listed:
        problems.append("doubtful readings marked [?] but none listed under Uncertain readings")
    # T246: the marks a fact may rest on, and the passages not understood; neither what was restored nor
    # what was not understood is asserted by the normalised transcription (its own marks aside)
    marks = [{"line": i, "text": m.group(0), "kind": m.group(1) or "blank", "value": (m.group(2) or "").strip()}
             for i, line in enumerate(lines, 1) for m in MARK.finditer(line)]
    unclear = _listed(parts.get(UNCLEAR, ""))
    normalised = parts.get("Normalised transcription", "")
    asserted = re.sub(r"\{[^}]*\}", " ", normalised)
    read = re.sub(r"\{restored:[^}]*\}", " ", " ".join(lines))
    for m in marks:
        if m["kind"] == "restored" and _count(asserted, m["value"]) > _count(read, m["value"]):
            problems.append(f"line {m['line']}: '{m['value']}' is restored, not read, but the normalised "
                            "transcription asserts it")
    for u in unclear:
        if _count(asserted, _passage(u)):
            problems.append(f"'{_passage(u)}' is not understood, but the normalised transcription asserts it")
    return problems, {"header": head, "lines": lines, "persons": people, "doubts": doubts,
                      "uncertain": listed, "normalised": normalised, "marks": marks, "unclear": unclear,
                      "image_state": head.get("Image state") or None}


def _listed(body):
    """The ``- `` lines of a section, but ``- none``."""
    return [line[2:].strip() for line in body.splitlines()
            if line.startswith("- ") and line[2:].strip().lower() != "none"]


def _passage(entry):
    """The passage of a ``Not understood`` line, ``line 5: 'dlle' (…)``: between its first and last
    quotes, else what follows the line number."""
    text = re.sub(r"^lines?\s+[\d\s-]+:\s*", "", entry)
    first, last = text.find("'"), text.rfind("'")
    return text[first + 1:last] if 0 <= first < last else text


def _line_of(entry):
    """The line number a ``Not understood`` line starts with, or None."""
    m = re.match(r"^lines?\s+(\d+)", entry)
    return int(m.group(1)) if m else None


def _count(text, part):
    """How many times ``part`` is in ``text``, as whole words, case and spacing aside."""
    t, p = " ".join(text.lower().split()), " ".join(str(part).lower().split())
    return len(re.findall(rf"(?<!\w){re.escape(p)}(?!\w)", t)) if p else 0


def doubts_of(parsed):
    """T246: the ``doubt=`` lines of a transcription: its ``[?]`` marks, its marks a fact may rest on
    (blank, above, over, hand, restored) and its passages not understood."""
    out = [f"line {d['line']}: {d['word']}[?]" for d in parsed["doubts"]]
    out += [f"line {m['line']}: {m['text']}" for m in parsed["marks"]]
    return out + [f"not understood: {u}" for u in parsed["unclear"]]


def check_dates(normalised):
    """Dates of the normalised text that ``dates`` cannot read: [(text, why)]."""
    from probandia.lang.dates import read

    found = re.findall(r"\b(\d{1,2}(?:er)?\s+[A-Za-zéûè]+\s+\d{4}|\b[1-9]\d{3}-\d{2}-\d{2})\b", normalised)
    bad = []
    for d in found:
        try:
            read(d)
        except Exception as err:  # noqa: BLE001 — every refusal of `dates` is reported
            bad.append((d, str(err) or type(err).__name__))
    return bad


def reading_for(parsed, name):
    """The ``uncertain_reading`` text of a fact about ``name``: the listed doubts
    that mention it, else the marked words of the lines that hold it; and the marks
    and passages not understood of those lines (T246)."""
    from probandia.lang.places import key

    k = key(name)

    def holds(text):
        return any(part and part in key(text) for part in k.split())

    def on_line(n):
        return n is not None and 1 <= n <= len(parsed["lines"]) and holds(parsed["lines"][n - 1])

    hits = [u for u in parsed["uncertain"] if holds(u)]
    if not hits:
        hits = [f"line {d['line']}, '{d['word']}'[?]" for d in parsed["doubts"] if on_line(d["line"])][:1]
    hits += [f"line {m['line']}, {m['text']}" for m in parsed.get("marks", ()) if on_line(m["line"])]
    hits += [f"not understood: {u}" for u in parsed.get("unclear", ()) if holds(u) or on_line(_line_of(u))]
    return "; ".join(hits) or None


def doubtful_names(persons, family_folder, research, pass_no):
    """T258: the names this pass's facts rest on that their transcription reads with a doubt ``[?]``:
    [(full name, "'word'[?] (source)")], the person of each fact, its parents and spouses checked against
    the doubtful words of its source's transcription; a near form counts (``Gréhault`` for ``gréhaut[?]``)."""
    from probandia.lang.places import key

    by_id = {p["id"]: p for p in persons}
    parsed, out = {}, {}
    for p in persons:
        for f in p.get("facts") or []:
            if f.get("research") != research or f.get("pass") != pass_no or not f.get("source"):
                continue
            src = f["source"]
            if src not in parsed:
                parsed[src] = _doubtful_words(family_folder, src)
            kin = [p, *(by_id.get(i) for i in (p.get("parents") or {}).values()),
                   *(by_id.get(s.get("person")) for s in p.get("spouses") or [])]
            for who in filter(None, kin):
                names = who.get("names") or {}
                parts = [key(v) for v in names.values() if isinstance(v, str) and v.strip()]
                for words, label in parsed[src]:
                    if any(difflib.SequenceMatcher(None, key(w), n).ratio() >= 0.8
                           for w in words if key(w) for part in parts for n in part.split()):
                        full = " ".join(v for v in (names.get("given"), names.get("surname")) if v)
                        out.setdefault((full, label), f"{full}: {label} ({src})")
    return list(out.values())


def _doubtful_words(family_folder, source):
    """[(words, label)] of a source's doubts: the words its reading marks ``[?]``; with a second reading
    (T245), only those the second marks too or reads otherwise, then the second's own doubts, and each place
    where the two differ, ``'gréhaut' or 'gréhant'``."""
    try:
        with open(path_for(family_folder, source), encoding="utf-8") as fh:
            first = check(fh.read())[1]
    except OSError:
        return []
    try:
        with open(second_path(family_folder, source), encoding="utf-8") as fh:
            second = check(fh.read())[1]
    except OSError:
        return [([d["word"]], f"'{d['word']}'[?]") for d in first["doubts"]]
    found = compare(first["lines"], second["lines"])
    differ = {_key(w) for d in found for w in f"{d['first']} {d['second']}".split()}
    marked = {_key(d["word"]) for d in second["doubts"]}
    words = [d["word"] for d in first["doubts"] if _key(d["word"]) in marked - differ]
    words += [d["word"] for d in second["doubts"] if _key(d["word"]) not in differ | {_key(w) for w in words}]
    return [([w], f"'{w}'[?]") for w in words] + [
        (f"{d['first']} {d['second']}".replace("[?]", "").split(), f"'{d['first']}' or '{d['second']}'")
        for d in found]


TOKEN =re.compile(r"\{[^}]*\}|\S+")
EDGES = ".,;:!?()«»\"“”"


def _key(token):
    """What two readings of a word must share: the word without its mark ``[?]``, its case or the
    punctuation around it."""
    return token.replace("[?]", "").strip(EDGES).lower()


def _tokens(lines):
    return [(i, t) for i, line in enumerate(lines, 1) for t in TOKEN.findall(line) if _key(t)]


def compare(first, second):
    """T245: where two readings of an act differ, aligned word by word whatever their line breaks:
    [{"lines", "first", "second", "text"}], ``lines`` those of the first reading, ``text`` the ``doubt=``
    form, ``line 4: 'Hugot' or 'Hugo'``."""
    a, b = _tokens(first), _tokens(second)
    matcher = difflib.SequenceMatcher(None, [_key(t) for _i, t in a], [_key(t) for _i, t in b], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        lines = sorted({i for i, _t in (a[i1:i2] or a[max(i1 - 1, 0):i1] or a[:1])}) or [1]
        one, two = (" ".join(t.strip(EDGES) for _i, t in side) for side in (a[i1:i2], b[j1:j2]))
        where = f"line {lines[0]}" if len(lines) == 1 else f"lines {lines[0]}-{lines[-1]}"
        out.append({"lines": lines, "first": one, "second": two, "text": f"{where}: '{one}' or '{two}'"})
    return out


def divergence_for(found, first, name):
    """The ``uncertain_reading`` text of a fact about ``name``: the divergences ``compare`` found that
    name it, or that sit on a line of the first reading that holds it."""
    from probandia.lang.places import key

    parts = [p for p in key(name).split() if p]

    def holds(text):
        return any(p in key(text) for p in parts)

    hits = [d["text"] for d in found
            if holds(f"{d['first']} {d['second']}") or any(holds(first[i - 1]) for i in d["lines"] if i <= len(first))]
    return "; ".join(hits) or None


class TesseractFailed(ProbandiaError):
    reason = "tesseract-failed"


def tesseract(image, languages="fra", binary=None, timeout=120):
    """The OCR of a printed page by local Tesseract, as lines; None when it is not installed.
    ``TesseractFailed`` when it fails or runs past ``timeout`` seconds."""
    exe = binary or shutil.which("tesseract")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, image, "stdout", "-l", languages], capture_output=True, text=True,
                             timeout=timeout, encoding="utf-8", errors="replace")
        error = None if out.returncode == 0 else (out.stderr.strip().splitlines() or ["exit %d" % out.returncode])[-1]
    except subprocess.TimeoutExpired:
        error = _("no answer after {n} s").format(n=timeout)
    except OSError as err:
        error = str(err)
    if error is not None:
        raise TesseractFailed(_("Tesseract could not read {image} ({error}); is its language pack {languages} "
                                "installed? tesseract --list-langs lists the packs").format(
                                    image=image, error=error[:200], languages=languages),
                              values={"IMAGE": image, "LANGUAGES": languages})
    return [line.rstrip() for line in out.stdout.splitlines() if line.strip()]


def region_size(region, width=None):
    """The IIIF size parameter: the overview at 1,500 px; a region at most 2,576 px
    on its long side."""
    if width:
        return f"{min(int(width), REGION_MAX)},"
    if region in (None, "", "full"):
        return f"{OVERVIEW},"
    return f"!{REGION_MAX},{REGION_MAX}"
