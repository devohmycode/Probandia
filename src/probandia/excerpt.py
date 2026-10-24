"""Excerpts: the passage of its source a fact reads (TRUST1, TRUST-D1 to TRUST-D3).

A fact may carry ``excerpt``, the exact passage it rests on:

- ``kind: transcription``: lines ``[a, b]`` of the diplomatic transcription of its
  source (``evidence/transcriptions/<source>.md``);
- ``kind: page``: ``offset`` and ``length`` in the text of a page read (``read``),
  its whitespace normalised, with the ``url`` read and the day it was ``captured``.

``text`` is the passage itself, 500 characters at most, and ``sha256`` the digest
of that text, whitespace normalised: a passage cut or rewritten no longer matches.
``region`` (T247) keeps where the act is on its view, as the reader cropped it.

The text of a page read is kept where its rights allow it (TRUST-D2): the
family's ``evidence/pages/<source>.md`` when the source is free to reuse and its
site is an archive of the catalogue whose images are free, else the research's
``work/pages/<source>.md``, which stays on this computer. A short excerpt is always kept in the fact.
"""
import datetime
import difflib
import hashlib
import os
from urllib.parse import urlparse

from probandia.i18n import _

MAX_CHARS = 500
KINDS = ("transcription", "page")


def normalise(text):
    """The text on one line, its whitespace runs made single spaces."""
    return " ".join(str(text or "").split())


def digest(text):
    """The sha256 of a text, whitespace normalised."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def from_lines(lines, first, last):
    """The excerpt of lines ``first`` to ``last`` (from 1) of a diplomatic transcription."""
    if not 1 <= first <= last <= len(lines):
        raise ValueError(_("lines {a}-{b} are not in the transcription, which has {n}").format(
            a=first, b=last, n=len(lines)))
    text = normalise(" ".join(lines[first - 1:last]))
    _check_size(text)
    return {"kind": "transcription", "lines": [first, last], "text": text, "sha256": digest(text)}


def from_page(text, offset, length, url=None, captured=None):
    """The excerpt of a page's text, ``offset`` and ``length`` counted in its normalised text."""
    whole = normalise(text)
    part = whole[offset:offset + length]
    if not part or offset < 0:
        raise ValueError(_("no text at offset {offset} of the page").format(offset=offset))
    _check_size(part)
    return {"kind": "page", "offset": offset, "length": len(part), "text": part, "sha256": digest(part),
            "url": url, "captured": captured or datetime.date.today().isoformat()}


def _check_size(text):
    if len(text) > MAX_CHARS:
        raise ValueError(_("an excerpt holds {n} characters at most: cite fewer lines").format(n=MAX_CHARS))


def offset_of(whole, part):
    """Where a passage starts in a page's normalised text; -1 when it is not there."""
    return normalise(whole).find(normalise(part))


# where the cited text is


def transcription_path(project, family, source):
    """The transcription of a source: its ``transcription`` field (from the family folder, then the
    project), else the conventional path."""
    from probandia.transcription import path_for

    folder = os.path.join(project, "families", family)
    given = (source or {}).get("transcription")
    for base in ((folder, project) if given else ()):
        path = os.path.join(base, given)
        if os.path.isfile(path):
            return path
    return path_for(folder, (source or {}).get("id") or "")


def transcription_lines(project, family, source, problems=None):
    """The numbered lines of a source's diplomatic transcription, or None when there is no file.
    ``problems``, a list, receives what ``transcribe check`` finds wrong in it."""
    from probandia.transcription import check

    path = transcription_path(project, family, source)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        found, parsed = check(fh.read())
    if problems is not None:
        problems.extend(found)
    return parsed["lines"]


def resolve(project, family, doc):
    """token-economy B4: each excerpt of a proposal given by reference, ``{source, lines: a-b}``, put in
    its long form from the source's transcription, as ``transcribe quote`` gives it. The source is the
    fact's when the excerpt names none. Raises ValueError."""
    import re

    from probandia.indexes import FamilyIndexes

    facts = list(doc.get("facts") or []) + [f for p in doc.get("persons") or [] for f in p.get("facts") or []]
    short = [f for f in facts if isinstance(f.get("excerpt"), dict) and "kind" not in f["excerpt"]]
    if not short:
        return
    sources = {s["id"]: s for s in FamilyIndexes(project, family).items("sources")}
    sources.update({s["id"]: s for s in doc.get("sources") or [] if s.get("id")})   # the proposal's own first
    for f in short:
        ref = f["excerpt"]
        sid = ref.get("source") or f.get("source")
        if not sid or (f.get("source") and f["source"] != sid):
            raise ValueError(_("the excerpt of fact {fact} cites {cited}, the fact {source}").format(
                fact=f["id"], cited=sid or "-", source=f.get("source") or "-"))
        source, problems = sources.get(sid) or {"id": sid}, []
        lines = transcription_lines(project, family, source, problems)
        if lines is None:
            raise ValueError(_("the excerpt of fact {fact}: no transcription of {source}").format(fact=f["id"],
                                                                                              source=sid))
        if not lines:   # a file not in the engine's form: say so, rather than "which has 0" (I1, 11 Oct. 2026)
            path = os.path.relpath(transcription_path(project, family, source), project).replace(os.sep, "/")
            why = next((p for p in problems if "iplomatic" in p), problems[0] if problems else "-")
            raise ValueError(_("the transcription of {source} has no numbered line ({why}): "
                               "`transcribe check {path}` lists what to fix").format(source=sid, why=why, path=path))
        a, b = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", str(ref["lines"])).groups()
        f["excerpt"] = from_lines(lines, int(a), int(b or a))
        if ref.get("region"):   # T247: where the act is on its view
            f["excerpt"]["region"] = ref["region"]
        f["source"] = sid


def page_paths(project, family, source_id, research=None):
    """Where a page's text is kept: the family's evidence, then the research's work folder."""
    out = [os.path.join(project, "families", family, "evidence", "pages", f"{source_id}.md")]
    if research is not None:
        out.append(os.path.join(research.work, "pages", f"{source_id}.md"))
    return out


def read_page(path):
    """The text of a page kept by ``freeze``: the file without its first comment line."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if text.startswith("<!--"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    return text.strip("\n")


def page_text(project, family, source_id, excerpt, research=None):
    """(text, where) of the page an excerpt cites: a kept page, then the read cache, even expired;
    (None, None) when it is nowhere on this computer."""
    for path in page_paths(project, family, source_id, research):
        if os.path.isfile(path):
            return read_page(path), os.path.relpath(path, project).replace(os.sep, "/")
    url = (excerpt or {}).get("url")
    if url:
        from probandia.reading.cache import Cache, make_key

        entry = Cache(project, research.work if research is not None else None).entry("http", make_key("http", url))
        if entry and entry.get("status") == "ok":
            return (entry.get("payload") or {}).get("text") or "", "cache"
    return None, None


def locate(excerpt, lines=None, text=None):
    """Why an excerpt does not hold against its transcription ``lines`` or page ``text``: a list of
    reasons, empty when it holds."""
    if digest(excerpt["text"]) != excerpt["sha256"]:
        return [_("its text does not match its sha256")]
    if excerpt["kind"] == "transcription":
        if lines is None:
            return [_("no transcription")]
        a, b = (excerpt.get("lines") or [0, 0])[:2]
        if not 1 <= a <= b <= len(lines):
            return [_("lines {a}-{b} are not in the transcription, which has {n}").format(a=a, b=b, n=len(lines))]
        if normalise(" ".join(lines[a - 1:b])) != normalise(excerpt["text"]):
            near = nearest(excerpt["text"], lines)
            return [_("lines {a}-{b} do not read so").format(a=a, b=b)
                    + (_("; the closest is line {n}: {line}").format(n=near[0], line=near[1]) if near else "")]
        return []
    if text is None:
        return [_("the page is not kept on this computer")]
    if normalise(excerpt["text"]) not in normalise(text):
        return [_("the page does not contain it")]
    return []


def nearest(text, lines):
    """(line number, line) of the transcription line closest to ``text``, or None."""
    best = max(((difflib.SequenceMatcher(None, normalise(text), normalise(line)).ratio(), i, line)
                for i, line in enumerate(lines, 1)), default=None)
    return (best[1], best[2]) if best and best[0] > 0.3 else None


def check(project, family, fact, sources, research=None):
    """Why a fact's excerpt does not hold: reasons, empty when it holds or when there is none."""
    return verdict(project, family, fact, sources, research)[1]


def verdict(project, family, fact, sources, research=None):
    """(state, reasons) of a fact's excerpt: ``ok`` (or no excerpt), ``unseen`` (a page this computer
    does not keep: it cannot be checked here) or ``broken`` (the text is not found, or not as quoted)."""
    excerpt = fact.get("excerpt")
    if not excerpt:
        return "ok", []
    source = sources.get(fact.get("source") or "")
    if source is None:
        return "broken", [_("its source is not known")]
    if excerpt["kind"] == "transcription":
        found = locate(excerpt, lines=transcription_lines(project, family, source))
        return ("broken" if found else "ok"), found
    text, _where = page_text(project, family, source["id"], excerpt, research)
    if text is None and digest(excerpt["text"]) == excerpt["sha256"]:
        return "unseen", locate(excerpt, text=None)
    found = locate(excerpt, text=text)
    return ("broken" if found else "ok"), found


# keeping the page (TRUST-D2)


def may_keep(source, archives=None):
    """True when a page of this source may be copied into the family's evidence: the source is
    free to reuse, and its URL belongs to an archive of the catalogue whose images are free. A site
    the catalogue does not know stays in ``work/``: the source's rights are only what an agent wrote
    (TRUST-D2, made precise on 5 October 2026)."""
    if (source or {}).get("rights") != "free":
        return False
    host = urlparse((source or {}).get("url") or "").hostname or ""
    for entry in (archives or {}).values():
        hosts = ((entry.get("access") or {}).get("hosts") or [])
        if host and any(host == h or host.endswith("." + h) for h in hosts):
            return entry.get("image_rights") == "free"
    return False


def freeze(project, family, research, facts, sources, archives=None):
    """Keeps the text of each page an excerpt of ``facts`` cites, where its rights allow, and returns
    {source id: sha256 of the page}. A page already kept is left as it is."""
    from probandia.util.fs import atomic_write_text

    out = {}
    for f in facts:
        excerpt = f.get("excerpt") or {}
        source = sources.get(f.get("source") or "")
        if excerpt.get("kind") != "page" or source is None:
            continue
        evidence, work = page_paths(project, family, source["id"], research)
        text, where = page_text(project, family, source["id"], excerpt, research)
        if text is None:
            continue
        if where == "cache":
            target = evidence if may_keep(source, archives) else work
            atomic_write_text(target, f"<!-- {excerpt.get('url') or ''} -->\n{text}\n")
        out[source["id"]] = digest(text)
    return out
