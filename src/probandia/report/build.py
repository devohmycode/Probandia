"""The report model, built from the event log and the family indexes.

- **Journal mode**: one chapter per pass, holding the sections written in that
  pass, as they were written; then Errata, Method and Sources. Erratum notices
  and ``†E<n>`` marks are added at rendering: the stored text never changes.
- **Living mode**: the default chapters, each section at its latest text
  (``section.replaced``), moved or merged where the events say; then the
  revision history.

Every node of the model is plain Markdown (``body_md``); the renderers turn it
into Markdown, HTML and JSON.
"""
from dataclasses import dataclass, field

from probandia.lang.places import key as fold
from probandia.report import labels as L

KINDS = ("chapter", "section", "subsection")


@dataclass
class Node:
    id: str
    kind: str
    title: str
    body_md: str = ""
    facts: list = field(default_factory=list)
    pass_no: int | None = None
    children: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    notices: list = field(default_factory=list)   # erratum notices, Markdown
    position: float | None = None
    generated: bool = False                       # written by the engine, not by the model
    number: str = ""
    path: str = ""
    anchor: str = ""

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class Model:
    mode: str
    lang: str
    chapters: list
    errata: list
    revisions: list
    method: list
    log: list
    trees: list
    through_pass: int
    generated: str
    facts_cited: dict = field(default_factory=dict)

    def walk(self):
        for c in self.chapters:
            yield from c.walk()


def _kind(level):
    return KINDS[min(level, len(KINDS) - 1)]


def collect(events):
    """Sections, errata, revisions and the rest, from the events in order."""
    sections, order = {}, []
    errata, revisions, method, log, trees = [], {}, [], [], []
    passes = set()
    n_errata = 0
    for e in events:
        p = e.get("pass", 0)
        passes.add(p)
        log.append({"id": e["id"], "type": e["type"], "pass": p})
        payload = e.get("payload") or {}
        t = e["type"]
        if t == "section.added":
            s = payload["section"]
            sections[s["id"]] = {"id": s["id"], "parent": s.get("parent"), "kind": s.get("kind", "section"),
                                 "title": s.get("title", ""), "body_md": s.get("body_md", ""),
                                 "facts": list(s.get("facts") or []), "pass": p,
                                 "position": s.get("position"), "aliases": [], "history": []}
            order.append(s["id"])
        elif t == "section.replaced" and payload.get("section") in sections:
            s = sections[payload["section"]]
            s["history"].append({"pass": p, "title": s["title"], "body_md": s["body_md"]})
            s["title"] = payload.get("title", s["title"])
            s["body_md"] = payload.get("body_md", s["body_md"])
            revisions.setdefault(p, []).append({"section": s["id"], "what": "rewritten",
                                                "why": payload.get("reason", "")})
        elif t == "section.moved" and payload.get("section") in sections:
            s = sections[payload["section"]]
            s["parent"] = payload.get("parent")
            s["position"] = payload.get("position", s["position"])
            revisions.setdefault(p, []).append({"section": s["id"], "what": "moved",
                                                "why": payload.get("reason", "")})
        elif t == "section.merged":
            into = sections.get(payload.get("into"))
            for sid in payload.get("sections", []):
                s = sections.pop(sid, None)
                if s is None or into is None or sid == into["id"]:
                    continue
                into["body_md"] = (into["body_md"].rstrip() + "\n\n" + s["body_md"].strip()).strip()
                into["facts"] += [f for f in s["facts"] if f not in into["facts"]]
                into["aliases"] += [sid] + s["aliases"]
                for other in sections.values():
                    if other["parent"] == sid:
                        other["parent"] = into["id"]
            if into is not None:
                revisions.setdefault(p, []).append({"section": into["id"], "what": "merged",
                                                    "why": payload.get("reason", "")})
        elif t == "erratum.recorded":
            n_errata += 1
            errata.append({"id": payload.get("erratum") or f"E{n_errata}", "target": payload.get("target") or {},
                           "wrong": payload.get("wrong", ""), "correction": payload.get("correction", ""),
                           "cause": payload.get("cause", "other"), "detection": payload.get("detection") or "",
                           "pass": p})
        elif t == "fact.revised":
            n_errata += 1
            fact = payload.get("fact")
            errata.append({"id": f"E{n_errata}", "target": {"section": None, "fact": fact},
                           "wrong": str(payload.get("wrong") or payload.get("before") or ""),
                           "correction": str(payload.get("after") or ""), "cause": payload.get("cause", "other"),
                           "detection": payload.get("reason") or "", "pass": p,
                           "refuted": payload.get("after") == "refuted", "volet": payload.get("volet")})
            revisions.setdefault(p, []).append({"section": None, "fact": fact, "what": "fact revised",
                                                "why": payload.get("reason", "")})
        elif t == "fact.retracted":
            revisions.setdefault(p, []).append({"section": None, "fact": payload.get("fact"),
                                                "what": "fact retracted", "why": payload.get("reason", "")})
        elif t == "branch.added":
            trees.append({"pass": p, "root": payload.get("root"), "persons": payload.get("persons", [])})
        elif t in ("pass.started", "pass.ended"):
            actor = e.get("actor") or {}
            if t == "pass.started":
                method.append({"pass": p, "harness": actor.get("harness"), "agent": actor.get("agent"),
                               "model": actor.get("model"), "run": payload.get("run")})
            elif payload.get("tools"):   # FL-D7: the tools the pass used
                for m in method:
                    if m["pass"] == p:
                        m["tools"] = payload["tools"]
    for s in sections.values():  # merged sections that were someone's alias target
        s["aliases"] = sorted(set(s["aliases"]))
    return sections, order, errata, revisions, method, log, trees, passes


def _tree(sections, order, roots, level_of_root):
    """Nodes for the sections whose parent is in ``roots`` (None for the top)."""
    by_parent = {}
    for sid in order:
        if sid in sections:
            by_parent.setdefault(sections[sid]["parent"], []).append(sections[sid])
    def make(s, level):
        node = Node(id=s["id"], kind=_kind(level), title=s["title"], body_md=s["body_md"],
                    facts=s["facts"], pass_no=s["pass"], aliases=s["aliases"], position=s["position"])
        kids = sorted(by_parent.get(s["id"], []), key=lambda c: (c["position"] is None, c["position"] or 0))
        node.children = [make(c, level + 1) for c in kids]
        return node
    return [make(s, level_of_root) for s in sorted(by_parent.get(roots, []),
                                                    key=lambda c: (c["position"] is None, c["position"] or 0))]


def timeline_nodes(extra):
    """One generated section per timeline (GPS7): its table; HTML puts the chart above it."""
    return [Node(id=f"timeline-{pid}", kind="section", title=title, body_md=body, generated=True)
            for pid, title, body in extra.get("timelines") or []]


def proof_nodes(extra):
    """One generated section per accepted proof argument (GPS5)."""
    return [Node(id=f"proof-{pid}", kind="section", title=title, body_md=body, generated=True)
            for pid, title, body in extra.get("proofs") or []]


def standard_nodes(extra):
    """One generated section per structured question: its conformity to the GPS (GPS8)."""
    return [Node(id=f"standard-{qid.lower()}", kind="section", title=title, body_md=body, generated=True)
            for qid, title, body in extra.get("standard") or []]


def coverage_nodes(extra):
    """One generated section per question with a matrix (GPS3), under the method chapter."""
    return [Node(id=f"coverage-{qid.lower()}", kind="section", title=title, body_md=body, generated=True)
            for qid, title, body in extra.get("coverage") or []]


def guide_nodes(extra):
    """One generated section per place of the research with a locality guide (GPS2)."""
    return [Node(id=f"guide-{pid}", kind="section", title=title, body_md=body, generated=True)
            for pid, title, body in extra.get("guides") or []]


def analysis_nodes(extra):
    """One generated section per analysis (GPS4): its correlation table and resolution."""
    return [Node(id=f"analysis-{aid}", kind="section", title=title, body_md=body, generated=True)
            for aid, title, body in extra.get("analyses") or []]


def volet_node(v, t):
    """FL-D8: the chapter that opens a volet, before its first pass: what the volets before established,
    the corrections, and what this one takes on."""
    body = []
    for key in ("established", "corrections", "openings"):
        if v.get(key):
            body.append(f"**{t(L.VOLET_PARTS[key])}**\n\n" + "\n".join(f"- {x}" for x in v[key]))
    return Node(id=f"volet-{v['n']}", kind="chapter", title=t(L.VOLET).format(n=v["n"], title=v["title"]),
                body_md="\n\n".join(body), pass_no=v["from_pass"], generated=True)


def journal(events, t, extra):
    sections, order, errata, revisions, method, log, trees, passes = collect(events)
    chapters = []
    volets = [e["payload"] for e in events if e["type"] == "volet.opened"]
    tops = [sections[i] for i in order if i in sections and sections[i]["parent"] is None]
    for p in sorted(x for x in passes if x):
        while volets and volets[0]["from_pass"] <= p:
            chapters.append(volet_node(volets.pop(0), t))
        mine = [s for s in tops if s["pass"] == p]
        model_chapters = [s for s in mine if s["kind"] == "chapter"]
        # one chapter written in the pass becomes the pass's chapter; several stay sections of it
        named = model_chapters[0]["title"] if len(model_chapters) == 1 else ""
        title = t(L.PASS).format(n=p) + (f" — {named}" if named else "")
        chapter = Node(id=f"pass-{p}", kind="chapter", title=title, pass_no=p, generated=True)
        for s in mine:
            node_list = _tree(sections, order, s["id"], 2)
            if s["kind"] == "chapter" and len(model_chapters) == 1:
                # the pass chapter takes the model's chapter: its text, then its sections
                chapter.body_md = (chapter.body_md + "\n\n" + s["body_md"]).strip()
                chapter.facts += s["facts"]
                chapter.aliases.append(s["id"])
                chapter.children += node_list
            else:
                node = Node(id=s["id"], kind="section", title=s["title"], body_md=s["body_md"],
                            facts=s["facts"], pass_no=s["pass"], aliases=s["aliases"])
                node.children = node_list
                chapter.children.append(node)
        tree_md = extra.get("tree_md", {}).get(p)
        if tree_md:
            chapter.children.append(Node(id=f"tree-{p}", kind="section", title=t(L.TREE),
                                         body_md=tree_md, pass_no=p, generated=True))
        chapters.append(chapter)
    chapters += [volet_node(v, t) for v in volets]   # opened for passes still to come
    if errata:
        chapters.append(Node(id="errata", kind="chapter", title=t(L.ERRATA), generated=True,
                             body_md=extra["errata_md"](errata)))
    chapter = Node(id="method", kind="chapter", title=t(L.METHOD), generated=True,
                   body_md=extra["method_md"](method))
    chapter.children = coverage_nodes(extra)
    chapters.append(chapter)
    questions = extra["questions_md"]() if "questions_md" in extra else ""
    if questions:   # after the passes: their numbers never move (GPS1)
        chapter = Node(id="questions", kind="chapter", title=t(L.QUESTIONS), generated=True, body_md=questions)
        chapter.children = standard_nodes(extra)   # GPS8: each question's conformity, after their table
        chapters.append(chapter)
    arguments = proof_nodes(extra)
    if arguments:   # GPS5: after the questions they argue
        chapter = Node(id="proofs", kind="chapter", title=t(L.PROOFS), generated=True)
        chapter.children = arguments
        chapters.append(chapter)
    tables = analysis_nodes(extra)
    if tables:   # GPS4: also after the passes
        chapter = Node(id="evidence", kind="chapter", title=t(L.EVIDENCE), generated=True)
        chapter.children = tables
        chapters.append(chapter)
    lines = timeline_nodes(extra)
    if lines:   # GPS7: also after the passes
        chapter = Node(id="timelines", kind="chapter", title=t(L.TIMELINES), generated=True)
        chapter.children = lines
        chapters.append(chapter)
    chapters.append(Node(id="sources", kind="chapter", title=t(L.SOURCES), generated=True,
                         body_md=extra["sources_md"]()))
    guides = guide_nodes(extra)
    if guides:   # GPS2: an annex, after the sources
        chapter = Node(id="guides", kind="chapter", title=t(L.GUIDES), generated=True)
        chapter.children = guides
        chapters.append(chapter)
    return chapters, errata, revisions, method, log, trees, max(passes or {0})


def living(events, t, extra):
    sections, order, errata, revisions, method, log, trees, passes = collect(events)
    names = {fold(t(label)): cid for cid, label in L.LIVING_CHAPTERS}
    names.update({fold(label): cid for cid, label in L.LIVING_CHAPTERS})
    default = {cid: Node(id=cid, kind="chapter", title=t(label), generated=True)
               for cid, label in L.LIVING_CHAPTERS}
    written = []
    for sid in order:
        if sid not in sections or sections[sid]["parent"] is not None:
            continue
        s = sections[sid]
        cid = names.get(fold(s["title"]))
        kids = _tree(sections, order, sid, 1)
        if cid:  # the model wrote a default chapter
            ch = default[cid]
            ch.body_md = (ch.body_md + "\n\n" + s["body_md"]).strip()
            ch.aliases.append(sid)
            ch.facts += s["facts"]
            ch.children += kids
            ch.generated = False
        else:
            node = Node(id=sid, kind="chapter", title=s["title"], body_md=s["body_md"], facts=s["facts"],
                        pass_no=s["pass"], aliases=s["aliases"], position=s["position"])
            node.children = kids
            written.append(node)
    for cid, fn in (("question", extra["question_md"]), ("persons", extra["persons_md"]),
                    ("hypotheses", extra["hypotheses_md"]), ("negatives", extra["negatives_md"]),
                    ("sources", extra["sources_md"]), ("method", lambda: extra["method_md"](method)),
                    ("revisions", lambda: extra["revisions_md"](revisions))):
        generated = fn()
        if generated:
            ch = default[cid]
            ch.body_md = (generated + ("\n\n" + ch.body_md if ch.body_md else "")).strip()
    default["persons"].children += timeline_nodes(extra)   # GPS7: each main person's timeline
    default["evidence"].children += analysis_nodes(extra)   # GPS4: the correlation tables
    default["question"].children += standard_nodes(extra)   # GPS8: each question's conformity to the GPS
    default["question"].children += proof_nodes(extra)   # GPS5: each question's accepted argument
    default["guides"].children += guide_nodes(extra)   # GPS2: the locality guides
    default["method"].children += coverage_nodes(extra)   # GPS3: each question's source coverage
    tree_md = extra.get("tree_md", {})
    if tree_md:
        last = max(tree_md)
        default["persons"].children.append(Node(id="tree", kind="section", title=t(L.TREE),
                                                body_md=tree_md[last], generated=True))
    written.sort(key=lambda n: (n.position is None, n.position or 0))
    chapters = []
    for cid, _label in L.LIVING_CHAPTERS:
        if cid == "sources":
            chapters += written
        ch = default[cid]
        if ch.body_md or ch.children:
            chapters.append(ch)
    return chapters, errata, revisions, method, log, trees, max(passes or {0})
