"""From the event log and the family indexes to ``report.json``, Markdown and HTML.

The same events and indexes always give the same bytes: sorted JSON keys, a
stable order, and one timestamp only, ``generated``, the time of the last event.
"""
import html
import json
import re
from dataclasses import dataclass

from probandia import SITE
from probandia.report import build, content, numbering
from probandia.report import labels as L
from probandia.report.living import living_set
from probandia.util.schema import Validator, load_schema

NOTE = re.compile(r"\[\^(\d+)\]")
CODE = re.compile(r"(^```.*?^```[ \t]*$|`[^`\n]+`)", re.S | re.M)


def escape_html(text):
    """Raw HTML in prose is shown, never rendered: ``<`` becomes ``&lt;`` outside code."""
    parts = CODE.split(text or "")
    return "".join(p if i % 2 else p.replace("<", "&lt;") for i, p in enumerate(parts))


@dataclass
class Report:
    model: build.Model
    ctx: content.Context
    title: str
    research: str
    numbering: str
    resolved: dict          # node id -> resolved Markdown of its body
    notes: list
    data: dict              # report.json
    unresolved: list
    tree_svg: dict = None   # pass -> SVG ancestor chart of the branch, for HTML
    tree_mermaid: dict = None  # pass -> Mermaid block, for trees/pass-<n>.md
    manual: list = None     # pages left unread for want of a session (optimize 3.10)
    timeline_svg: dict = None  # person id -> SVG timeline, for HTML (GPS7)
    guide_svg: dict = None  # place id -> SVG of its jurisdictions over time, for HTML (GPS2)
    fingerprints: dict = None  # journal mode: pass -> sha256 of its rendered text (PRD criterion 6, T226)


MARK = re.compile(r" †E\d+")


def as_of(persons, events, research_id, p):
    """The family's persons as pass ``p`` of the research saw them (journal mode, PRD criterion 6, T226): its own
    facts of later passes left out, and a fact refuted later back to the status it had."""
    before = {}
    for e in events:
        payload = e.get("payload") or {}
        if e["type"] == "fact.revised" and payload.get("after") == "refuted" and e.get("pass", 0) > p \
                and payload.get("fact") not in before:   # a refutation's "before" is the status it had
            before[payload.get("fact")] = payload.get("before")
    out = []
    for person in persons:
        facts = []
        for f in person.get("facts") or []:
            if f.get("research") == research_id and (f.get("pass") or 0) > p:
                continue
            if f["id"] in before:
                f = {k: v for k, v in f.items() if k != "refuted_in"}
                f["status"] = before[f["id"]] if before[f["id"]] in ("record", "index", "hypothesis") else "record"
            facts.append(f)
        out.append(dict(person, facts=facts))
    return out


def fingerprints(model, resolved, notes, tree_md):
    """{pass: sha256} of the text each pass shows: its sections, their notes and its tree, without the marks
    that send to an erratum (``†E1``), which are added after it; note numbers left out, the notes kept in order."""
    import hashlib

    texts = {}
    by_number = dict(notes)
    for node in model.walk():
        p = node.pass_no
        if not p:
            continue
        body = MARK.sub("", resolved.get(node.id) or "")
        cited = [by_number.get(int(n), "") for n in NOTE.findall(body)]
        texts.setdefault(p, []).append("\n".join([node.title or "", NOTE.sub("[^]", body)] + cited))
    for p, tree in tree_md.items():
        texts.setdefault(p, []).append(tree)
    return {p: hashlib.sha256("\n\n".join(parts).encode("utf-8")).hexdigest() for p, parts in sorted(texts.items())}


def _used_sources(persons, research_id, events):
    cited = set()
    for e in events:
        payload = e.get("payload") or {}
        if e["type"] == "section.added":
            s = payload.get("section") or {}
            cited.update(s.get("facts") or [])
            cited.update(m.group(2) for m in content.REF.finditer(s.get("body_md") or "") if m.group(1) == "f")
        elif e["type"] == "section.replaced":
            cited.update(m.group(2) for m in content.REF.finditer(payload.get("body_md") or "")
                         if m.group(1) == "f")
    used = set()
    for p in persons:
        for f in p.get("facts", []):
            if f.get("source") and (f.get("research") == research_id or f["id"] in cited):
                used.add(f["source"])
    return used


def _notices(model, ctx, t):
    """Each erratum's notice goes after the section it names, else after the first
    section of an earlier pass that cites the fact."""
    for e in model.errata:
        target = e.get("target") or {}
        node = ctx.nodes.get(target.get("section") or "")
        if node is None and target.get("fact"):
            ref = f"[[f:{target['fact']}]]"
            for n in model.walk():
                if n.generated and n.kind != "chapter":
                    continue
                if (target["fact"] in n.facts or ref in n.body_md) and (n.pass_no or 0) < e["pass"]:
                    node = n
                    break
        if node is not None:
            node.notices.append(content.notice(e, t))


def _timelines(meta, persons, living, t, setting, today=None):
    """(sections, SVG charts) of the timelines the setting asks for (GPS7-T5): each section is
    (person id, title, Markdown table)."""
    from probandia import svg as charts
    from probandia.report import timeline

    def event_label(e):
        return t(L.FACT_TYPES.get(e["type"], L.FACT_TYPES["other"])) + ("?" if e["status"] == "hypothesis" else "")

    def kin_label(r):
        return f"{t(L.TIMELINE_ROLES[r['role']])}: {t(L.FACT_TYPES.get(r['type'], L.FACT_TYPES['other']))}"

    sections, svgs = [], {}
    for pid in timeline.chosen(meta, persons, setting or "main"):
        tl = timeline.model(pid, persons, living, today)
        if tl is None or len(tl["events"]) < timeline.MIN_EVENTS:
            continue
        title = t(L.TIMELINE).format(name=tl["name"])
        sections.append((pid, title, timeline.markdown(tl, t)))
        svgs[pid] = charts.timeline(tl, title, event_label, kin_label)
    return sections, svgs


def _proofs(meta, docs, t):
    """GPS5-T7: (id, title, Markdown) of the research's accepted proof arguments, in the order of its questions;
    an argument not accepted never enters the report."""
    order = {q.get("id"): n for n, q in enumerate(meta.get("questions") or [])}
    found = [p for p in (docs.get("proofs") or {}).get("proofs", [])
             if p["research"] == meta["id"] and p["review"]["state"] == "accepted"]
    found.sort(key=lambda p: (order.get(p["question"], len(order)), p["question"]))
    return [(p["id"], t(L.PROOF).format(question=p["question"]), content.proof_md(p, t)) for p in found]


def _analyses(meta, docs, persons, sources, living, t):
    """GPS4-T6: (id, title, Markdown table) of the analyses of this research, or about its persons; an
    analysis about a person presumed living stays out."""
    rid = meta["id"]
    mine = {p["id"] for p in persons if any(f.get("research") == rid for f in p.get("facts") or [])}
    names = {p["id"]: " ".join(x for x in ((p.get("names") or {}).get("given"), (p.get("names") or {}).get("surname"))
                               if x) for p in persons}
    out = []
    for a in (docs.get("analyses") or {}).get("analyses", []):
        if a["person"] in living or not (a.get("research") == rid or a["person"] in mine):
            continue
        kind = t(L.FACT_TYPES.get(a["fact_kind"], L.FACT_TYPES["other"]))
        out.append((a["id"], t(L.ANALYSIS).format(name=names.get(a["person"]) or a["person"], kind=kind),
                    content.analysis_md(a, sources, t)))
    return out


def research_places(meta, docs, persons, living):
    """The places of a research that have a locality guide: those its questions name, then those of its
    facts (by id, or by a name as written), a fact of a person presumed living left out."""
    from probandia.lang.places import key

    places = (docs.get("places") or {}).get("places", [])
    by_id = {p["id"]: p for p in places}
    by_name = {}
    for p in places:
        for name in [p.get("current_name")] + list(p.get("names_as_written") or []):
            if name:
                by_name.setdefault(key(name), p["id"])
    wanted = [pid for q in meta.get("questions") or [] for pid in q.get("places") or []]
    for person in persons:
        if person["id"] in living:
            continue
        for f in person.get("facts") or []:
            if f.get("research") != meta["id"]:
                continue
            where = f.get("place") or {}
            pid = where.get("id") or by_name.get(key(where.get("as_written") or ""))
            if pid:
                wanted.append(pid)
    out = []
    for pid in dict.fromkeys(wanted):
        p = by_id.get(pid)
        if p and (p.get("jurisdictions") or p.get("repositories")):
            out.append(p)
    return out


def _guides(meta, docs, persons, living, lang, t):
    """GPS2-T6: (sections, SVG charts) of the research's locality guides; each section is
    (place id, title, Markdown)."""
    from probandia import svg as charts

    gaps = (docs.get("gaps") or {}).get("gaps", [])
    sections, svgs = [], {}
    for p in research_places(meta, docs, persons, living):
        archives = {r.get("archive") for r in p.get("repositories") or [] if r.get("archive")}
        title = content.guide_title(p, t)
        sections.append((p["id"], title, content.guide_md(p, [g for g in gaps if g["archive"] in archives], lang, t)))
        if p.get("jurisdictions"):
            svgs[p["id"]] = charts.jurisdictions(
                p["jurisdictions"], t(L.GUIDE_JURISDICTIONS) + " — " + title,
                lambda j: t(L.LEVELS.get(j["level"], j["level"])) + " " + j["name"],
                lambda value: content.format_day(value, lang), t(L.GUIDE_OPEN), t(L.GUIDE_UNKNOWN))
    return sections, svgs


def _coverage(matrix, docs, lang, t):
    """GPS3-T8: (question id, title, Markdown) of each question of the matrix that expects sources
    or does not know them yet."""
    if not matrix:
        return []
    from probandia.proof import source_types

    names = {x["id"]: x["names"] for x in source_types.load()["types"]}
    places = {p["id"]: p for p in (docs.get("places") or {}).get("places", [])}
    searches = {s["id"]: s for s in (docs.get("searches") or {}).get("searches", [])}
    gaps = {g["id"]: g for g in (docs.get("gaps") or {}).get("gaps", []) if g.get("id")}
    return [(q["id"], t(L.COVERAGE).format(question=q["id"]),
             content.coverage_md(q, names, places, searches, gaps, lang, t))
            for q in matrix["questions"] if q["rows"] or q["unknown"] or q["notes"]]


def _standard(found, living, t):
    """GPS8-T2: (question id, title, Markdown) of each question's conformity to the GPS; the ids of a person
    presumed living are not named."""
    return [(q["question"], t(L.STANDARD_OF).format(question=q["question"]), content.standard_md(q, living, t))
            for q in found or []]


def build_report(meta, events, docs, lang, t, numbering_style="arabic", pattern="", today=None,
                 living_years=100, trees=True, timelines="main", matrix=None, standard=None, checks=None):
    """The whole report. ``docs``: the family indexes, as loaded; ``matrix``: the research's
    exhaustiveness matrix (``proof.matrix.build``), for the source coverage of its questions;
    ``standard``: its questions' conformity to the GPS (``proof.standard.assess``); ``checks``: what
    persons looked at, by fact (``factcheck.of_family``), else those of ``events``."""
    research_id = meta["id"]
    mode = meta.get("mode") or "journal"
    persons = docs["persons"].get("persons", [])
    sources = {s["id"]: content.with_citation(s, lang) for s in docs["sources"].get("sources", [])}
    living = living_set(persons, living_years, today)
    used = _used_sources(persons, research_id, events)
    timeline_sections, timeline_svg = _timelines(meta, persons, living, t, timelines, today)
    guide_sections, guide_svg = _guides(meta, docs, persons, living, lang, t)
    # TRUST3: the confidence of each answered question, a column of the questions' table
    trust = {q["question"]: q["confidence"]["name"] for q in standard or [] if q.get("confidence")}

    from probandia import svg as charts
    from probandia import trees as family

    label = t(L.LIVING_PERSON)
    graph = family.Tree(persons, living=living)
    tree_data, tree_md, tree_svg, tree_mermaid = [], {}, {}, {}
    for e in events:
        root = (e.get("payload") or {}).get("root") if e["type"] == "branch.added" else None
        p = e.get("pass", 0)
        if root and mode == "journal":   # the tree of a pass as the pass saw the family (T226)
            graph = family.Tree(as_of(persons, events, research_id, p), living=living)
        if root not in graph.persons:
            continue
        ids = graph.simplified(root)  # the root, two generations up and one down, 40 at most
        d = family.data(graph, ids, label)
        tree_data.append({"pass": p, "root": root, "nodes": d["nodes"], "edges": d["edges"]})
        tree_mermaid[p] = family.mermaid_block(graph, ids, label)
        tree_svg[p] = charts.ancestors(graph, root, 3, label)
        if trees:
            tree_md[p] = "```mermaid\n" + tree_mermaid[p] + "\n```"

    extra = {
        "tree_md": tree_md,
        "errata_md": lambda errata: content.errata_md(errata, t),
        "method_md": lambda method: content.method_md(method, t),
        "sources_md": lambda: content.sources_md(sources, used, lang),
        "revisions_md": lambda revisions: content.revisions_md(revisions, t),
        # with structured questions (GPS1), their table stands for the free-text question
        "question_md": lambda: "\n\n".join(x for x in [
            content.questions_md(meta["questions"], t, trust) if meta.get("questions") else meta.get("question") or ""] + [
            f"- {i['text']}" for i in meta.get("instructions") or [] if i.get("text")] if x),
        "questions_md": lambda: content.questions_md(meta.get("questions") or [], t, trust),
        "timelines": timeline_sections,
        "guides": guide_sections,
        # a free-text question, read as Q1, has neither window nor places to expect sources from
        "coverage": _coverage(matrix if meta.get("questions") else None, docs, lang, t),
        "analyses": _analyses(meta, docs, persons, sources, living, t),
        "proofs": _proofs(meta, docs, t),
        # GPS8: a box at the head of each structured question
        "standard": _standard(standard if meta.get("questions") else None, living, t),
        "hypotheses_md": lambda: content.hypotheses_md(docs["hypotheses"].get("hypotheses", []), t),
        "negatives_md": lambda: content.negatives_md(docs["searches"].get("searches", []), research_id, t),
    }
    project = build.living if mode == "living" else build.journal
    if mode == "living":
        # the persons table needs no numbering: it is built before the context
        tmp = content.Context([], persons, [], living, lang, t, [], mode)
        extra["persons_md"] = lambda: content.persons_md(persons, tmp, research_id)
    chapters, errata, revisions, method, log, _trees, through = project(events, t, extra)
    numbering.apply(chapters, numbering_style, pattern)
    generated = events[-1]["ts"] if events else "1970-01-01T00:00:00Z"
    model = build.Model(mode=mode, lang=lang, chapters=chapters, errata=errata,
                        revisions=revisions, method=method, log=log, trees=tree_data,
                        through_pass=through, generated=generated)
    from probandia import factcheck

    ctx = content.Context(list(model.walk()), persons, list(sources.values()), living, lang, t,
                          errata, mode, checks if checks is not None else factcheck.of_log(events))
    if mode == "journal":
        _notices(model, ctx, t)
        seen = {}

        def at(p):
            if p not in seen:
                seen[p] = {f["id"]: (x, f) for x in as_of(persons, events, research_id, p) for f in x["facts"]}
            return seen[p]
        ctx.at = at
    resolved = {}
    for node in model.walk():  # document order: notes are numbered as they appear
        resolved[node.id] = ctx.resolve(escape_html(node.body_md), node.pass_no)
    title = meta.get("question") or research_id
    data = to_data(model, research_id, numbering_style)
    return Report(model=model, ctx=ctx, title=title, research=research_id, numbering=numbering_style,
                  resolved=resolved, notes=list(ctx.notes), data=data, unresolved=list(ctx.unresolved),
                  tree_svg=tree_svg, tree_mermaid=tree_mermaid, timeline_svg=timeline_svg, guide_svg=guide_svg,
                  fingerprints=fingerprints(model, resolved, ctx.notes, tree_md) if mode == "journal" else None)


# JSON


def _section(node):
    return {"id": node.id, "aliases": list(node.aliases), "kind": node.kind, "number": node.number,
            "path": node.path, "title": node.title, "body_md": node.body_md, "facts": list(node.facts),
            "pass": node.pass_no, "children": [_section(c) for c in node.children]}


def to_data(model, research_id, numbering_style):
    return {
        "$schema": f"{SITE}/schemas/report-1.json",
        "schema": 1, "research": research_id, "lang": model.lang, "mode": model.mode,
        "numbering": numbering_style if numbering_style in numbering.STYLES else "arabic",
        "generated": model.generated, "through_pass": model.through_pass,
        "sections": [_section(c) for c in model.chapters],
        "errata": model.errata,
        "revisions": [{"pass": p, "changes": model.revisions[p]} for p in sorted(model.revisions)],
        "trees": model.trees, "method": model.method, "log": model.log,
    }


_validator = None


def validate(data):
    global _validator
    if _validator is None:
        _validator = Validator(load_schema("report", 1))
    return _validator.errors(data)


def to_json(report):
    return json.dumps(report.data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


# Markdown


def _heading_level(depth):
    return min(depth + 2, 4)


def to_markdown(report, t):
    out = [f"# {report.title}", ""]
    out.append(f"## {t(L.CONTENTS)}")
    out.append("")

    def toc(nodes, depth):
        for n in nodes:
            out.append("  " * depth + f"- [{n.number} {n.title}](#{n.anchor})")
            toc(n.children, depth + 1)
    toc(report.model.chapters, 0)
    out.append("")

    def section(node, depth):
        out.append(f'<a id="{node.anchor}"></a>')
        for alias in node.aliases:
            out.append(f'<a id="s-{alias.lower()}"></a>')
        out.append("")
        out.append(f"{'#' * _heading_level(depth)} {node.number} {node.title}")
        out.append("")
        body = report.resolved.get(node.id, "").strip()
        if body:
            out.append(body)
            out.append("")
        for child in node.children:
            section(child, depth + 1)
        for text in node.notices:
            out.append(f"> **†** {text}")
            out.append("")
    for chapter in report.model.chapters:
        section(chapter, 0)
    for n, text in report.notes:
        out.append(f"[^{n}]: {text}")
    if report.manual:
        out += ["", f"## {t(L.MANUAL_TASKS)}", ""]
        out += [f"- {t(L.MANUAL_TASK).format(archive=m['archive'], url=m['url'])}" for m in report.manual]
    return "\n".join(out).rstrip() + "\n"


# HTML: the engine writes the slots, the template (template.py) the rest

def _markdown():
    from markdown_it import MarkdownIt

    return MarkdownIt("commonmark", {"html": False}).enable("table")


def _tree_svg(report, node):
    """The SVG chart of a tree section: ``tree-<pass>`` in journal mode, ``tree`` in living mode."""
    if not node.generated or not report.tree_svg:
        return None
    if node.id.startswith("tree-"):
        return report.tree_svg.get(int(node.id[5:]))
    if node.id == "tree":
        return report.tree_svg[max(report.tree_svg)]
    return None


# The box of the conformity to the GPS takes the colours of the template's notes: the shipped templates keep
# their fingerprint (V-13), and a template without these variables still shows a frame.
STANDARD_BOX = ("border: 1px solid var(--note-rule, currentColor); background: var(--note, transparent); "
                "padding: .5rem 1rem; margin: 1rem 0")


def to_html(report, t, template=None):
    """The HTML report, in ``template`` (the built-in ``default`` when None)."""
    from probandia.report import template as T

    template = template or T.builtin()
    return T.fill(template, html_slots(report, t, template.notes), t, report.model.lang)


def html_slots(report, t, notes="end"):
    """What the engine writes into each slot of a template: ``notes`` is ``end`` (all
    the notes after the report) or ``chapter`` (each chapter's notes after it)."""
    md = _markdown()
    esc = html.escape
    status = report.ctx.note_status if report.ctx is not None else {}

    def calls(text):
        return NOTE.sub(lambda m: _call(m.group(1), status.get(int(m.group(1)))), text)

    slots = {"head": "\n".join(['<meta name="generator" content="Probandia">',
                                f'<meta name="dcterms.modified" content="{esc(report.model.generated)}">',
                                f"<title>{esc(report.title)}</title>"]),
             "title": f"<h1>{esc(report.title)}</h1>", "research": esc(report.research or ""),
             "generated": esc(_long_date(report.model.generated, report.model.lang))}
    out = [f'<nav aria-labelledby="toc-title"><h2 id="toc-title">{esc(t(L.CONTENTS))}</h2>']

    def toc(nodes):
        out.append("<ol>")
        for n in nodes:
            out.append(f'<li><a href="#{n.anchor}">{esc(n.number)} {esc(n.title)}</a>')
            if n.children:
                toc(n.children)
            out.append("</li>")
        out.append("</ol>")
    toc(report.model.chapters)
    out.append("</nav>")
    slots["toc"] = "\n".join(out)

    def section(node, depth):
        level = _heading_level(depth)
        out.append(f'<section id="{node.anchor}">')
        for alias in node.aliases:
            out.append(f'<span id="s-{alias.lower()}"></span>')
        out.append(f"<h{level}>{esc(node.number)} {esc(node.title)}</h{level}>")
        body = report.resolved.get(node.id, "").strip()
        chart = _tree_svg(report, node)
        line = (report.timeline_svg or {}).get(node.id[9:]) if node.generated and node.id.startswith("timeline-") \
            else None
        css = "timeline"
        if node.generated and node.id.startswith("guide-"):
            line, css = (report.guide_svg or {}).get(node.id[6:]), "timeline guide"
        if line:   # the chart, then its table: the dates and clashes in words (GPS7-T5)
            out.append(f'<figure class="{css}">{line}</figure>')
        if chart:
            out.append(f'<figure class="tree">{chart}</figure>')
        elif body and node.generated and node.id.startswith("standard-"):   # GPS8: a box, in any template
            out.append(f'<aside class="standard" role="note" style="{STANDARD_BOX}">'
                       f'{calls(md.render(body)).rstrip()}</aside>')
        elif body:
            out.append(calls(md.render(body)).rstrip())
        for child in node.children:
            section(child, depth + 1)
        for text in node.notices:
            out.append(f'<aside class="erratum" role="note">{calls(md.renderInline(text))}</aside>')
        out.append("</section>")

    def note_items(numbers):
        return [f'<li id="fn-{n}"{_status_class(status.get(n))}>{md.renderInline(text)}</li>'
                for n, text in report.notes if n in numbers]

    out = []
    done = set()
    for chapter in report.model.chapters:
        start = len(out)
        section(chapter, 0)
        if notes == "chapter":
            cited = {int(n) for n in re.findall(r'href="#fn-(\d+)"', "\n".join(out[start:]))} - done
            if cited:
                out.append(f'<section class="notes chapter-notes" aria-label="{esc(t(L.NOTES))}"><ol>')
                out += note_items(cited)
                out.append("</ol></section>")
                done |= cited
    slots["body"] = "\n".join(out)
    rest = {n for n, _text in report.notes} - done
    if rest:
        slots["notes"] = "\n".join([f'<section class="notes" aria-label="{esc(t(L.NOTES))}"><ol>']
                                   + note_items(rest) + ["</ol></section>"])
    if report.manual:
        slots["manual"] = "\n".join(
            [f"<section class=\"manual\"><h2>{esc(t(L.MANUAL_TASKS))}</h2><ul>"]
            + [f"<li>{esc(t(L.MANUAL_TASK).format(archive=m['archive'], url=m['url']))}</li>" for m in report.manual]
            + ["</ul></section>"])
    return slots


def _status_class(status):
    return f' class="status-{status}"' if status in L.STATUSES else ""


def _call(n, status):
    return f'<sup{_status_class(status)}><a href="#fn-{n}">{n}</a></sup>'


def _long_date(iso, lang):
    """The day of ``generated``, in the report's language (the ``generated`` slot)."""
    return content.format_day((iso or "")[:10], lang)


def rule_v6(report):
    """Rule V-6: every reference of the prose resolves. ("PASS" or "FAIL", the
    unresolved references)."""
    missing = sorted(set(report.unresolved))
    return ("FAIL" if missing else "PASS"), missing
