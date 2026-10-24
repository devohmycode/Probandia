"""References inside prose, and the chapters the engine writes itself.

| Syntax | Rendered as |
|---|---|
| ``[[s:<ULID>]]`` | a link showing the section's path, « § I.2.1 » |
| ``[[f:<fact>]]`` | the fact, with a citation note ``[^n]`` |
| ``[[p:<person>]]`` | the person's name, masked if presumed living |

An unresolved reference is shown as ``[?…]`` and listed: it fails V-6.
"""
import re

from probandia import cite as citing
from probandia.cite import ensure as with_citation
from probandia.report import labels as L

REF = re.compile(r"\[\[(s|f|p):([^\]\s]+)\]\]")
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
           "octobre", "novembre", "décembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
           "Oktober", "November", "Dezember"],
}


def format_day(value, lang):
    """``1802-02-26`` -> 26 February 1802 / 26 février 1802; ISO for unknown languages."""
    if not value:
        return ""
    base = lang.split("-")[0]
    parts = value.split("-")
    if base not in MONTHS or len(parts) == 1:
        return value
    month = MONTHS[base][int(parts[1]) - 1]
    if len(parts) == 2:
        return f"{month} {parts[0]}"
    day = int(parts[2])
    if base == "fr" and day == 1:
        return f"1er {month} {parts[0]}"
    if base == "de":
        return f"{day}. {month} {parts[0]}"
    return f"{day} {month} {parts[0]}"


def format_date(date, lang, t):
    if not date or not date.get("value"):
        return ""
    q = date.get("qualifier") or "exact"
    text = t(L.QUALIFIERS.get(q, "{date}")).format(date=format_day(date["value"], lang),
                                                   end=format_day(date.get("end") or "", lang))
    if date.get("calendar") and date["calendar"] != "gregorian":
        text += f" ({t(L.CALENDARS[date['calendar']])})"
    return text


class Context:
    """What reference resolution needs to know, for one rendering."""

    def __init__(self, nodes, persons, sources, living, lang, t, errata, mode, checks=None):
        self.checks = checks or {}   # T248: {fact: [{by, looked, ts}]}, what a person looked at
        self.nodes = {}
        for n in nodes:
            self.nodes[n.id] = n
            for alias in n.aliases:
                self.nodes[alias] = n
        self.persons = {p["id"]: p for p in persons}
        self.facts = {f["id"]: (p, f) for p in persons for f in p.get("facts", [])}
        self.sources = {s["id"]: with_citation(s) if s.get("repository") else s for s in sources}
        self.living = living
        self.lang = lang
        self.t = t
        self.mode = mode
        self.notes = []          # (n, text)
        self.note_of = {}        # key -> n
        self.note_status = {}    # n -> the status of the fact it cites (the HTML's status-* classes)
        self.cited = set()       # typed sources already given their first note (GPS6-T5)
        self.unresolved = []
        self.marks = {}          # fact -> [(erratum id, pass)]
        self.at = None           # journal mode: pass -> {fact: (person, fact)} as the pass wrote them (T226)
        for e in errata:
            fact = (e.get("target") or {}).get("fact")
            if fact:
                self.marks.setdefault(fact, []).append((e["id"], e["pass"]))

    def name(self, pid):
        if pid in self.living:
            return self.t(L.LIVING_PERSON)
        p = self.persons.get(pid)
        if not p:
            return None
        names = p.get("names") or {}
        return " ".join(x for x in (names.get("given"), names.get("surname")) if x)

    def note(self, key, text):
        if key not in self.note_of:
            self.notes.append((len(self.notes) + 1, text))
            self.note_of[key] = len(self.notes)
        return self.note_of[key]

    def fact_text(self, fid, pair=None):
        pid, fact = (pair or self.facts[fid])[0]["id"], (pair or self.facts[fid])[1]
        kind = self.t(L.FACT_TYPES.get(fact["type"], L.FACT_TYPES["other"]))
        if pid in self.living:
            return f"{self.t(L.LIVING_PERSON)}, {kind}", None
        bits = [f"{self.name(pid)}, {kind}"]
        date = format_date(fact.get("date"), self.lang, self.t)
        if date:
            bits.append(date)
        place = (fact.get("place") or {}).get("as_written") or (fact.get("place") or {}).get("id")
        if place:
            bits.append(place)
        status = self.t(L.STATUSES.get(fact["status"], fact["status"]))
        where = fact.get("refuted_in") or {}
        if fact["status"] == "refuted" and where:   # FL-D10: when it was refuted, never deleted
            status = (self.t(L.REFUTED_IN_VOLET).format(volet=where["volet"], n=where["pass"]) if where.get("volet")
                      else self.t(L.REFUTED_IN_PASS).format(n=where["pass"]))
        src = self.sources.get(fact.get("source") or "")
        note = f"{status}. {self.citation(src)}".strip()
        quoted = self.excerpt(fact.get("excerpt"))
        note = f"{note} {quoted}" if quoted else note
        for c in self.checks.get(fid) or []:   # T248: who looked at the record, when, and at what
            note += " " + self.t(L.FACT_CHECKED).format(who=self.masked(c["by"]), looked=self.masked(c["looked"]),
                                                        date=format_day(c["ts"][:10], self.lang))
        return ", ".join(bits), note

    def masked(self, text):
        """A text of a person's, in a note: the name of a person presumed living masked, as in an excerpt."""
        text = " ".join(str(text or "").split())
        for name in self.living_names():
            text = re.sub(r"(?i)\b" + r"\s+".join(map(re.escape, name.split())) + r"\b", self.t(L.LIVING_PERSON), text)
        return re.sub(r"([*_`\\])", r"\\\1", text)

    def excerpt(self, found):
        """TRUST2-T2: the passage a fact cites, quoted, with where it is; the name of a person presumed
        living, should the passage hold one, is masked."""
        if not found:
            return ""
        text = " ".join(found["text"].split())
        for name in self.living_names():
            text = re.sub(r"(?i)\b" + r"\s+".join(map(re.escape, name.split())) + r"\b", self.t(L.LIVING_PERSON), text)
        text = re.sub(r"([*_`\\])", r"\\\1", text)
        if found["kind"] == "transcription":
            a, b = found["lines"]
            where = (self.t(L.EXCERPT_LINE).format(a=a) if a == b else self.t(L.EXCERPT_LINES).format(a=a, b=b))
        else:
            where = self.t(L.EXCERPT_PAGE).format(date=format_day(found.get("captured") or "", self.lang))
        return self.t(L.EXCERPT).format(text=text, where=where)

    def living_names(self):
        if not hasattr(self, "_living_names"):
            from probandia.report.living import full_names

            names = {n for pid in self.living if pid in self.persons for n in full_names(self.persons[pid]) if n}
            names |= {" ".join(n.split()[1:] + n.split()[:1]) for n in names}   # an act writes the surname first
            self._living_names = sorted(names, key=len, reverse=True)
        return self._living_names

    def citation(self, src):
        """A typed source's first note at its first mention, its short note after; the
        citation of a source without a type, every time."""
        if not src:
            return ""
        if not src.get("type"):
            return src.get("citation") or ""
        form = "short" if src["id"] in self.cited else "first"
        self.cited.add(src["id"])
        return citing.format(src, form, self.lang)

    def resolve(self, text, node_pass=None):
        text = text or ""

        def inline(m):
            """True when the agent's own words come before the reference in its sentence: the reference
            then cites what they say, and only its note is rendered (the fact's text would say it twice)."""
            before = re.split(r"\n|[.!?:;|](?=\s)", text[:m.start()])[-1]
            before = LIST_MARK.sub("", REF.sub("", before))
            return bool(re.search(r"\w", before))

        def sub(m):
            kind, ref = m.group(1), m.group(2)
            if kind == "s":
                node = self.nodes.get(ref) or self.nodes.get(ref.upper())
                if node is None:
                    self.unresolved.append(m.group(0))
                    return f"[?{ref}]"
                return f"[§ {node.path}](#{node.anchor})"
            if kind == "p":
                name = self.name(ref)
                if name is None:
                    self.unresolved.append(m.group(0))
                    return f"[?{ref}]"
                return name
            if ref not in self.facts:
                self.unresolved.append(m.group(0))
                return f"[?{ref}]"
            # journal mode (PRD criterion 6, T226): an earlier pass shows the fact as it wrote it, its erratum after
            pair = (self.at(node_pass) or {}).get(ref) if self.at and node_pass is not None else None
            text_, cite = self.fact_text(ref, pair)
            cites_words = inline(m) and cite
            out = "" if cites_words else text_
            if cite:
                n = self.note(f"f:{ref}:{cite}", cite)   # one note per state of the fact
                self.note_status.setdefault(n, (pair or self.facts[ref])[1].get("status"))
                out += f"[^{n}]"
            if self.mode == "journal" and node_pass is not None:
                for eid, epass in self.marks.get(ref, []):
                    if node_pass < epass:
                        out += f" †{eid}"
            return out

        out, at = [], 0
        for m in REF.finditer(text):
            piece = sub(m)
            head = text[at:m.start()]
            if piece.startswith("[^"):   # a note after the agent's words sits against them
                head = head.rstrip(" ")
            out += [head, piece]
            at = m.end()
        return "".join(out) + text[at:]


# chapters written by the engine


def table(header, rows):
    if not rows:
        return ""
    def cell(v):
        return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def _change(e, t):
    """What an erratum changed; a refutation (FL-D10) as the status it had, then where it was refuted."""
    if not e.get("refuted"):
        return e["wrong"], e["correction"]
    where = (t(L.REFUTED_IN_VOLET).format(volet=e["volet"], n=e["pass"]) if e.get("volet")
             else t(L.REFUTED_IN_PASS).format(n=e["pass"]))
    return t(L.STATUSES.get(e["wrong"], e["wrong"])), where


def errata_md(errata, t):
    return "\n".join(f"- **{t(L.ERRATUM).format(id=e['id'])}** — {t(L.PASS).format(n=e['pass'])}: "
                     f"{' → '.join(_change(e, t))}. {t(L.CAUSE)}: "
                     f"{t(L.CAUSES.get(e['cause'], e['cause']))}."
                     + (f" {t(L.DETECTED_BY)}: {e['detection']}." if e.get("detection") else "")
                     for e in errata)


def notice(e, t):
    detection = (e.get("detection") or "").strip()
    if detection and not detection.endswith("."):
        detection += "."
    wrong, correction = _change(e, t)
    return t(L.ERRATUM_NOTICE).format(id=e["id"], n=e["pass"], wrong=wrong, correction=correction,
                                      cause=t(L.CAUSES.get(e["cause"], e["cause"])),
                                      detection=detection).strip()


def questions_md(questions, t, confidence=None):
    """The research's questions (GPS1): each with its status, and the facts that answer it or why it
    stays unresolved; ``confidence``: {question id: level name} (TRUST3), a column when one is known."""
    confidence = confidence or {}
    standards = any(q.get("standard") for q in questions)   # T249: a column when a question says what will answer it
    rows = []
    for q in questions:
        status = q.get("status", "open")
        if status == "answered":
            answer = ", ".join(f"`{c}`" for c in q.get("conclusion") or [])
        else:
            answer = q.get("reason") or ""
        row = (q["id"], q["text"]) + ((q.get("standard") or "",) if standards else ()) + (
            t(L.QUESTION_STATUSES.get(status, status)), answer)
        if confidence:
            row += (t(L.CONFIDENCE_LEVELS[confidence[q["id"]]]) if q["id"] in confidence else "",)
        rows.append(row)
    head = [t(L.QUESTION_NO), t(L.QUESTION)] + ([t(L.QUESTION_STANDARD)] if standards else []) + [
        t(L.TABLE["status"]), t(L.QUESTION_ANSWER)]
    return table(head + ([t(L.CONFIDENCE)] if confidence else []), rows)


def standard_md(found, living, t):
    """GPS8-T2: one question against the Genealogical Proof Standard: how many of its elements the data
    establish, never a claim of conformity (T239), then each of the five elements, its state and what it lacks.
    An id that names a person presumed living is not shown."""
    from probandia.proof import confidence as C
    from probandia.proof import standard as S

    def hide(lack):
        ids = [t(L.LIVING_PERSON) if any(x == p or x.startswith(p + ".") or f"-{p}-" in f"-{x}-" for p in living)
               else x for x in lack["ids"]]
        return dict(lack, ids=list(dict.fromkeys(ids)))

    rows = [(t(L.STANDARD_ELEMENTS[k]), t(L.STANDARD_STATES[e["state"]]),
             "; ".join(S.describe(hide(x), t) for x in e["lacks"])) for k, e in found["elements"].items()]
    applicable = [e for e in found["elements"].values() if e["state"] != "not_applicable"]
    n = sum(1 for e in applicable if e["state"] == "established")
    head = "**" + t(L.STANDARD_COUNT).format(n=n, m=len(applicable)) + "**\n\n*" + t(L.STANDARD_CAVEAT) + "*"
    conf = found.get("confidence")
    if conf:   # TRUST3-T3: the confidence of the conclusion, and what holds it down
        head += "\n\n" + t(L.CONFIDENCE_OF).format(level=t(L.CONFIDENCE_LEVELS[conf["name"]]))
        head += "".join(f"\n- {C.describe(hide(x), t)}" for x in conf["reasons"])
    return head + "\n\n" + table([t(L.STANDARD_HEAD[k]) for k in ("element", "state", "lacks")], rows)


def method_md(method, t):
    """The passes, who ran them and with what; first, that AI agents wrote the report (T239)."""
    head = [t(L.TABLE["pass"]), t(L.TABLE["harness"]), t(L.TABLE["agent"]), t(L.TABLE["model"])]
    rows = [(m["pass"], m.get("harness") or "", m.get("agent") or "", m.get("model") or "")
            for m in method]
    if any(m.get("tools") for m in method):   # FL-D7: web, MCP, archives, engine, as pass end counted them
        head.append(t(L.TABLE["tools"]))
        rows = [row + (t(L.TOOLS).format(**m["tools"]) if m.get("tools") else "",)
                for row, m in zip(rows, method)]
    return t(L.AI_ASSISTED) + "\n\n" + table(head, rows)


def coverage_md(question, names, places, searches, gaps, lang, t):
    """GPS3-T8: one question's source coverage: a row per expected source type, then the gaps it
    rests on with how they are known. ``names``: the source types' names by language; ``places``,
    ``searches``, ``gaps``: the family's, by id."""
    out = [f"*{t(L.COVERAGE_UNKNOWN[u])}*" for u in question.get("unknown") or [] if u in L.COVERAGE_UNKNOWN]
    out += [t(L.COVERAGE_COUNTRY).format(country=c) for c in question.get("notes") or []]
    base = (lang or "en").split("-")[0]
    rows, used = [], []
    for r in question.get("rows") or []:
        name = (names.get(r["type"]) or {}).get(base) or (names.get(r["type"]) or {}).get("en") or r["type"]
        where = ", ".join((places[p].get("names_as_written") or [places[p].get("current_name") or p])[0]
                          if p in places else p for p in r["places"])
        years = str(r["years"][0]) if r["years"][0] == r["years"][1] else f"{r['years'][0]}–{r['years'][1]}"
        if r["state"] == "consulted":
            found = [searches[s] for s in r["searches"] if s in searches]
            how = "; ".join(f"{s.get('engine') or ''}: “{s['query']}”" for s in found[:3])
            how += f" (+{len(found) - 3})" if len(found) > 3 else ""
        elif r["state"] in ("gap", "unjustified_gap"):
            how = ", ".join(r["gaps"])
            used += [g for g in r["gaps"] if g not in used]
        else:
            how = r.get("reason") or ""
        rows.append((name, where, years, t(L.COVERAGE_STATES[r["state"]]), how))
    if rows:
        out.append(table([t(L.COVERAGE_HEAD[k]) for k in ("type", "places", "years", "state", "how")], rows))
    lines = []
    for gid in used:
        g = gaps.get(gid)
        if not g:
            continue
        said = g.get("justification") or (f"`{g['source']}`" if g.get("source")
                                          else f"*{t(L.COVERAGE_STATES['unjustified_gap'])}*")
        ref = f", {g['reference']}" if g.get("reference") else ""
        lines.append(f"- **{gid}** — {g['archive']}{ref}, {g['window']['from']}–{g['window']['to']}, "
                     f"{t(L.GAP_KINDS.get(g['kind'], g['kind']))}: {said}")
    if lines:
        out += [f"**{t(L.COVERAGE_GAPS)}**", "\n".join(lines)]
    return "\n\n".join(out)


def revisions_md(revisions, t):
    """Sections are named by ``[[s:…]]``: their paths are known only once numbered."""
    rows = []
    for p in sorted(revisions):
        for c in revisions[p]:
            where = f"[[s:{c['section']}]]" if c.get("section") else f"`{c.get('fact') or ''}`"
            rows.append((p, where, t(L.CHANGES.get(c["what"], c["what"])), c.get("why") or ""))
    return table([t(L.TABLE["pass"]), t(L.TABLE["section"]), t(L.TABLE["what"]), t(L.TABLE["why"])], rows)


def persons_md(persons, ctx, research_id):
    t = ctx.t
    rows = []
    for p in persons:
        facts = p.get("facts", [])
        if not any(f.get("research") == research_id for f in facts) and research_id:
            continue
        if p["id"] in ctx.living:
            rows.append((t(L.LIVING_PERSON), "", "", ""))
            continue
        born = next((f for f in facts if f["type"] in ("birth", "baptism")), None)
        died = next((f for f in facts if f["type"] in ("death", "burial")), None)
        status = t(L.STATUSES.get(born["status"], "")) if born else ""
        rows.append((ctx.name(p["id"]), format_date((born or {}).get("date"), ctx.lang, t),
                     format_date((died or {}).get("date"), ctx.lang, t), status))
    return table([t(L.TABLE["name"]), t(L.TABLE["born"]), t(L.TABLE["died"]), t(L.TABLE["status"])], rows)


def proof_md(p, t):
    """GPS5-T7: an accepted proof argument: its six parts, who reviewed it, and the objections raised with
    their answers, set apart as a quotation."""
    out = []
    for key, label in L.PROOF_PARTS:
        text = (p["parts"].get(key) or "").strip()
        if text:
            out.append(f"**{t(label)}.** {text}" if "\n" not in text else f"**{t(label)}.**\n\n{text}")
    if p.get("analyses"):
        out.append(" ".join(f"[[s:analysis-{aid}]]" for aid in p["analyses"]))
    who = sorted({r["reviewer"] for r in p["review"]["rounds"]})
    if who:
        out.append("*" + t(L.REVIEWED_BY).format(who="; ".join(t(L.REVIEWERS[w]) for w in who)) + "*")
    quoted = []
    for r in p["review"]["rounds"]:
        for o in r["objections"]:
            line = f"> **{t(L.OBJECTION).format(n=o['n'])}**" + (f" (`{o['fact']}`)" if o.get("fact") else "")
            line += f" — {o['text']}"
            if o["state"] == "answered":
                line += " " + t(L.OBJECTION_ANSWER).format(text=o.get("answer") or "")
            elif o["state"] == "dismissed":
                line += " " + t(L.OBJECTION_DISMISSED).format(text=o.get("reason") or "")
            quoted.append(line)
    if quoted:
        out.append("\n>\n".join(quoted))
    return "\n\n".join(out)


def analysis_md(a, sources, t):
    """GPS4-T6: one analysis as a correlation table, a row per piece of evidence and a column per axis
    (PRD P-10), with the resolution under it."""
    def axis(item, key):
        value = (item.get("axes") or {}).get(key)
        return t(L.AXES[key][value]) if value else "—"

    rows = []
    for i in a.get("items") or []:
        source = (sources.get(i.get("source") or "") or {}).get("citation") or "—"
        what = f"`{i['fact']}`" if i.get("fact") else ""
        rows.append((i["asserts"], i.get("informant") or "", source, axis(i, "source"), axis(i, "information"),
                     axis(i, "evidence"), " ".join(x for x in (what, i.get("note") or "") if x)))
    out = [table([t(L.ANALYSIS_HEAD["asserts"]), t(L.ANALYSIS_HEAD["informant"]), t(L.ANALYSIS_HEAD["source"]),
                  t(L.AXIS_NAMES["source"]), t(L.AXIS_NAMES["information"]), t(L.AXIS_NAMES["evidence"]),
                  t(L.ANALYSIS_HEAD["note"])], rows)]
    res = a.get("resolution")
    if res:
        kept = res["value"] + (f" (`{res['fact']}`)" if res.get("fact") else "")
        out.append(t(L.RESOLUTION).format(kept=kept, reasoning=res["reasoning"]))
    elif a.get("status") == "divergent":   # FL-D9: both versions stay side by side, unchosen
        out.append(f"**{t(L.DIVERGENT_ANALYSIS).format(reason=a.get('reason') or '')}**")
    else:
        out.append(f"*{t(L.UNRESOLVED_ANALYSIS)}*")
    return "\n\n".join(out)


def sources_md(sources, used, lang=None):
    """The list of sources: one entry per source (the full form of a typed source; sources
    of one register share their entry), sorted by repository, then type."""
    entries = {}
    for sid in used:
        s = sources.get(sid)
        if not s:
            continue
        text = citing.format(s, "full", lang) if s.get("type") else s.get("citation") or sid
        key = ((s.get("repository") or "").casefold(), s.get("type") or "", text.casefold())
        entries.setdefault(text, key)
    return "\n".join(f"- {text}" for text, _key in sorted(entries.items(), key=lambda e: e[1]))


def hypotheses_md(hypotheses, t):
    out = []
    for h in hypotheses:
        out.append(f"- **{h['question']}**")
        for alt in h.get("hypotheses", []):
            status = alt.get("status", "open")
            out.append(f"  - {alt['statement']} ({t(L.HYPOTHESIS_STATUSES.get(status, status))})")
    return "\n".join(out)


def guide_title(place, t):
    name = (place.get("names_as_written") or [place.get("current_name") or place["id"]])[0]
    current = place.get("current_name")
    return t(L.GUIDE_TODAY).format(name=name, current=current) if current and current != name else name


def guide_md(place, gaps, lang, t):
    """GPS2-T6: a place's locality guide: its jurisdictions in the order of their dates, its
    repositories and the known gaps of their holdings."""
    def day(value):
        return format_day(value, lang) if value else "…"

    out, derived = [], False
    rows = []
    for j in place.get("jurisdictions") or []:
        derived = derived or bool(j.get("derived"))
        source = (j.get("source") or "—") + (f" ({j['note']})" if j.get("note") else "")
        rows.append((t(L.LEVELS.get(j["level"], j["level"])) + ("\\*" if j.get("derived") else ""), j["name"],
                     day(j.get("from")), day(j.get("to")), source))
    if rows:
        out += [f"**{t(L.GUIDE_JURISDICTIONS)}**",
                table([t(L.GUIDE_HEAD[k]) for k in ("level", "name", "from", "to", "source")], rows)]
        if derived:
            out.append(f"\\* *{t(L.GUIDE_DERIVED)}*")
    rows = []
    for r in place.get("repositories") or []:
        held = []
        for h in r.get("holdings") or []:
            text = t(L.SOURCE_TYPES.get(h["type"], h["type"]))
            if h.get("years"):
                text += f" {h['years'][0]}–{h['years'][1]}"
            if h.get("reference"):
                text += f" ({h['reference']})"
            held.append(text)
        rows.append((r["name"] + (f" (`{r['archive']}`)" if r.get("archive") else ""), ", ".join(held),
                     r.get("note") or ""))
    if rows:
        out += [f"**{t(L.GUIDE_REPOSITORIES)}**",
                table([t(L.GUIDE_HEAD[k]) for k in ("repository", "holdings", "note")], rows)]
    rows = [(g["archive"], f"{g['window']['from']}–{g['window']['to']}", t(L.GAP_KINDS.get(g["kind"], g["kind"])),
             g.get("reference") or "") for g in gaps]
    if rows:
        out += [f"**{t(L.GUIDE_GAPS)}**",
                table([t(L.GUIDE_HEAD[k]) for k in ("archive", "years", "kind", "reference")], rows)]
    guide = place.get("guide") or {}
    said = []
    if guide.get("built"):
        said.append(t(L.GUIDE_BUILT).format(date=format_day(guide["built"], lang),
                                            sources=", ".join(guide.get("sources") or []) or "—"))
    if guide.get("copied_from"):
        said.append(t(L.GUIDE_COPIED).format(family=guide["copied_from"]))
    if said:
        out.append(" ".join(said))
    return "\n\n".join(out)


def negatives_md(searches, research_id, t):
    rows = []
    for s in searches:
        if s.get("result") != "negative" or s.get("family") == "opaque":
            continue
        if research_id and s.get("research") != research_id:
            continue
        w = s.get("window") or {}
        rows.append((s["query"], s.get("engine") or "", f"{w.get('from', '')}–{w.get('to', '')}",
                     ", ".join(s.get("variants") or [])))
    return table([t(L.TABLE[k]) for k in ("query", "engine", "window", "variants")], rows)
