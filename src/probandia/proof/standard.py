"""Conformity to the Genealogical Proof Standard, question by question (GPS8-T1).

The five elements of the GPS, each ``established``, ``partial`` or ``missing``
for one question (the citations and the argument may be ``not_applicable``), from the same
data as the rules of verify:

1. ``exhaustive``: a reasonably exhaustive search (V-18): no hole left in the
   question's matrix; ``missing`` while the question has no window or place, or
   no expected source type is settled yet;
2. ``citations``: complete and accurate citations (V-2, V-17): every fact of the
   question has its status, every record or index fact a source, and every
   source a type whose required fields are given; an untyped source cannot be
   checked: ``partial``; ``not_applicable`` for a question set aside without any
   fact;
3. ``analysis``: analysis and correlation (V-15, V-14): every conflict among
   the question's facts is analysed, each piece of evidence with its three
   axes, each fact that concludes an answered question too (T243), and no
   clash of dates is left unexplained;
4. ``conflicts``: conflicting evidence resolved (V-15): every analysis of the
   question is resolved;
5. ``argument``: a soundly reasoned conclusion (V-16): an accepted proof
   argument, reviewed by the contradictor, when one is required (GPS-D8);
   ``not_applicable`` when none is; ``missing`` for a question still open.

The facts of a question are those of its conclusion (an analysis named there
stands for the fact it retained); for a question not answered, the facts the
research established about its persons.

A question is ``conform`` when no element is partial or missing, ``partial``
when none is missing, else ``not_conform``. The indicator helps to show a proof:
it does not replace the genealogist's judgement, and it does not block ``close``,
which follows the rules of verify, except with ``proof.standard`` strict, where a
question that does not conform keeps the research open (GPS-D13).
"""
ELEMENTS = ("exhaustive", "citations", "analysis", "conflicts", "argument")
STATES = ("established", "partial", "missing", "not_applicable")
LEVELS = ("conform", "partial", "not_conform")
PROVEN = ("record", "index")


def _element(missing=(), partial=()):
    """An element's state, and what it lacks: [{why, ids}], the missing first."""
    lacks = [x for x in list(missing) + list(partial) if x]
    state = "missing" if any(missing) else "partial" if any(partial) else "established"
    return {"state": state, "lacks": lacks}


def _lack(why, ids=()):
    return {"why": why, "ids": list(ids)}


def question_facts(question, facts, analyses, research_id):
    """The ids of the facts a question rests on."""
    out = []
    by_id = {a["id"]: a for a in analyses}
    for c in question.get("conclusion") or []:
        fid = ((by_id.get(c) or {}).get("resolution") or {}).get("fact") if c in by_id else c
        if fid in facts and fid not in out:
            out.append(fid)
    if question.get("status") == "answered":
        return out
    persons = set(question.get("persons") or [])
    return out + [fid for fid, f in facts.items() if f["_person"] in persons and f.get("research") == research_id
                  and fid not in out]


def exhaustive(question, matrix_q, questions):
    """Element 1 (V-18), from the question's entry in the matrix."""
    from probandia.proof import matrix

    if matrix_q is None:
        return _element([_lack("unknown", ["window", "places"])])
    holes = matrix.holes(matrix_q)
    unknown = [h.split(":", 1)[1] for h in holes if h.startswith("unknown:")]
    types = [h for h in holes if not h.startswith("unknown:")]
    if question.get("type") == "general":
        unknown = []
    alone = question.get("type") == "general" and question.get("status") == "answered" \
        and question.get("conclusion") \
        and not any(q.get("type") != "general" and q.get("status") == "answered" for q in questions)
    settled = [r for r in matrix_q.get("rows") or [] if r["type"] not in types]
    missing = [_lack("unknown", unknown) if unknown else None, _lack("general-alone") if alone else None]
    if types and not settled:
        missing.append(_lack("holes", types))
        return _element(missing)
    return _element(missing, [_lack("holes", types) if types else None])


def citations(fids, facts, sources, status="answered", excerpt_state=None, strict=False):
    """Element 2 (V-2, V-17, V-19). A question set aside without any fact has nothing to cite. A record fact
    that answers the question cites its excerpt (TRUST-D3): without one the element is partial, missing with
    proof.standard strict; an excerpt not found as quoted makes it missing. ``excerpt_state``: a fact's
    excerpt, ``ok``, ``unseen`` or ``broken`` (``excerpt.verdict``); None does not look for it."""
    from probandia import cite

    if not fids and status == "unresolved":
        return {"state": "not_applicable", "lacks": []}
    if not fids:
        return _element([_lack("no-facts")])
    no_status = [fid for fid in fids if not facts[fid].get("status")]
    uncited = [fid for fid in fids if facts[fid].get("status") in PROVEN and facts[fid].get("source") not in sources]
    cited = list(dict.fromkeys(facts[fid]["source"] for fid in fids
                               if facts[fid].get("status") in PROVEN and facts[fid].get("source") in sources))
    untyped = [sid for sid in cited if not sources[sid].get("type")]
    incomplete = [sid for sid in cited if sources[sid].get("type") and cite.missing(sources[sid])]
    unquoted = [fid for fid in fids if status == "answered" and facts[fid].get("status") == "record"
                and not facts[fid].get("excerpt")] if excerpt_state is not None else []
    broken = [fid for fid in fids if facts[fid].get("excerpt") and excerpt_state is not None
              and excerpt_state(facts[fid]) == "broken"]
    lack = _lack("no-excerpt", unquoted) if unquoted else None
    return _element([_lack("no-status", no_status) if no_status else None,
                     _lack("no-citation", uncited) if uncited else None,
                     _lack("excerpt-broken", broken) if broken else None] + ([lack] if strict else []),
                    [_lack("required", incomplete) if incomplete else None,
                     _lack("untyped", untyped) if untyped else None] + ([] if strict else [lack]))


def _conflicts(fids, persons, places, analyses):
    """(conflicts among the question's facts that no analysis covers, the analyses that cover the others)."""
    from probandia.proof import conflicts as C

    mine = {f["_person"] for f in fids.values()}
    found = [c for c in C.find(persons, places, mine) if set(c["facts"]) & set(fids)]
    bare, covering = [], []
    for c in found:
        a = C.covered(c, analyses)
        if a is None:
            bare.append(c)
        elif a not in covering:
            covering.append(a)
    return bare, covering


def unclassified(question, fids, facts):
    """T243: the concluding facts of an answered question that do not give their three axes (``evidence``: source,
    information, evidence). Only those that conclude are asked for them, to keep the cost low."""
    from probandia.proof.conflicts import AXES

    if question.get("status") != "answered":
        return []
    return [fid for fid in fids if any(not (facts[fid].get("evidence") or {}).get(k) for k in AXES)]


def analysis(bare, relied, findings, bare_facts=()):
    """Element 3 (V-15, V-14); ``bare_facts``: the concluding facts without their three axes (T243)."""
    from probandia.proof.conflicts import missing_axes

    unanalysed = sorted({f"{c['person']}.{c['fact_kind']}" for c in bare})
    axes = [a["id"] for a in relied if missing_axes(a)]
    clashes = sorted({x for f in findings for x in f["facts"]})
    return _element([_lack("unanalysed", unanalysed) if unanalysed else None],
                    [_lack("axes", axes) if axes else None, _lack("chronology", clashes) if clashes else None,
                     _lack("unclassified", list(bare_facts)) if bare_facts else None])


def resolution(question, bare, relied):
    """Element 4 (V-15)."""
    unanalysed = sorted({f"{c['person']}.{c['fact_kind']}" for c in bare})
    still = [a["id"] for a in relied if a["status"] == "open"]
    lack = _lack("open-analysis", still) if still else None
    if question.get("status") == "answered":
        # FL-D9: answering a question means the divergence was settled
        divergent = [a["id"] for a in relied if a["status"] == "divergent"]
        return _element([_lack("unanalysed", unanalysed) if unanalysed else None, lack,
                         _lack("divergent-analysis", divergent) if divergent else None])
    return _element([_lack("unanalysed", unanalysed) if unanalysed else None], [lack])


def argument(question, persons, analyses, proofs, research_id):
    """Element 5 (V-16)."""
    from probandia.proof import arguments as A

    status = question.get("status", "open")
    if status == "unresolved":
        return {"state": "not_applicable", "lacks": []}
    if status != "answered":
        return _element([_lack("no-conclusion")])
    why = A.required(question, persons, analyses)
    if not why:
        return {"state": "not_applicable", "lacks": []}
    p = A.accepted(proofs, research_id, question["id"])
    if p is None:
        drafted = [x["id"] for x in proofs if x["research"] == research_id and x["question"] == question["id"]]
        if drafted:
            return _element(partial=[_lack("argument-pending", drafted)])
        return _element([_lack("no-argument", why)])
    if not any(r["reviewer"] == "contradictor" for r in p["review"]["rounds"]):
        return _element(partial=[_lack("not-independent", [p["id"]])])
    return _element()


def level(elements):
    states = {e["state"] for e in elements.values()}
    return "not_conform" if "missing" in states else "partial" if "partial" in states else "conform"


def assess(meta, docs, matrix_doc=None, today=None, excerpt_state=None, strict=False):
    """[{question, text, status, elements: {element: {state, lacks}}, level, confidence}] for each question of a
    research; ``confidence`` is None for a question not answered (``proof.confidence``).
    ``docs``: the family's indexes, as ``FamilyIndexes.load_all`` gives them; ``matrix_doc``: the research's
    matrix (``proof.matrix.build``)."""
    from probandia import chronology
    from probandia.proof import arguments as A
    from probandia.proof import confidence
    from probandia.proof import questions as Q

    def items(name):
        return (docs.get(name) or {}).get(name) or []

    persons, places, analyses, proofs = items("persons"), items("places"), items("analyses"), items("proofs")
    sources = {s["id"]: s for s in items("sources")}
    facts = {f["id"]: dict(f, _person=p["id"]) for p in persons for f in p.get("facts") or []}
    matrix_qs = {q["id"]: q for q in (matrix_doc or {}).get("questions") or []}
    questions = Q.of(meta)
    rid = meta.get("id")
    out = []
    for q in questions:
        fids = question_facts(q, facts, analyses, rid)
        mine = {fid: facts[fid] for fid in fids}
        bare, covering = _conflicts(mine, persons, places, analyses)
        relied = covering + [a for a in A.relied_on(q, analyses) if a not in covering]
        touched = {f["_person"] for f in mine.values()}
        findings = [f for f in chronology.all_findings(persons, touched, today, sources=sources)
                    if set(f["facts"]) & set(fids) and not any((facts.get(x) or {}).get("note") for x in f["facts"])]
        elements = {"exhaustive": exhaustive(q, matrix_qs.get(q["id"]), questions),
                    "citations": citations(fids, facts, sources, q.get("status", "open"), excerpt_state, strict),
                    "analysis": analysis(bare, relied, findings, unclassified(q, fids, facts)),
                    "conflicts": resolution(q, bare, relied),
                    "argument": argument(q, persons, analyses, proofs, rid)}
        gps = level(elements)
        out.append({"question": q["id"], "text": q.get("text", ""), "status": q.get("status", "open"),
                    "elements": elements, "level": gps,
                    # TRUST3: the confidence of the conclusion, from the same facts
                    "confidence": confidence.assess(q, fids, facts, relied, findings, proofs, gps, rid,
                                                    excerpt_state, sources)})
    return out


def excerpts(project, research, docs):
    """The state of a fact's excerpt, for ``assess`` (TRUST2-T3)."""
    from probandia import excerpt

    sources = {s["id"]: s for s in (docs.get("sources") or {}).get("sources") or []}
    return lambda fact: excerpt.verdict(project, research.family, fact, sources, research)[0]


def of_research(project, research, meta=None, today=None, strict=False, docs=None, matrix_doc=None):
    """``assess`` for a research, from its family's indexes and its matrix; ``strict``: proof.standard."""
    from probandia.indexes import FamilyIndexes
    from probandia.proof import matrix

    meta = meta if meta is not None else (research.meta() or {})
    docs = docs if docs is not None else FamilyIndexes(project, research.family).load_all()
    matrix_doc = matrix_doc if matrix_doc is not None else matrix.build(research, meta=meta)
    return assess(dict(meta, id=meta.get("id") or research.id), docs, matrix_doc, today,
                  excerpts(project, research, docs), strict)


def counts(found):
    """{level: n} over the questions assessed."""
    return {lv: sum(1 for q in found if q["level"] == lv) for lv in LEVELS}


def describe(lack, t):
    """What an element lacks, as a person reads it, in the language of ``t``."""
    from probandia.report import labels as L

    ids = [t(L.STANDARD_REASONS[x]) if x in L.STANDARD_REASONS else x for x in lack["ids"]]
    return t(L.STANDARD_LACKS[lack["why"]]).format(ids=", ".join(ids))


def short(lack):
    """What an element lacks, for the contract: ``why`` and its ids."""
    return lack["why"] + (":" + ",".join(lack["ids"]) if lack["ids"] else "")
