"""The confidence of a conclusion (TRUST3, TRUST-D4 to TRUST-D6).

Four levels, those of GEDCOM's QUAY: 3 *proved*, 2 *probable*, 1 *possible*,
0 *unsupported*. The level is computed, never declared, and only for an
answered question; ``reasons`` says what holds it down, each one what would
raise it once dealt with.

The rule (TRUST-D5):

- start from the weakest concluding fact: ``record`` 3, ``index`` 2,
  ``hypothesis`` 1, ``refuted`` 0;
- one step down for each of: indirect or negative evidence, unless an
  argument the contradictor reviewed was accepted (the GPS lets argued indirect
  evidence establish a conclusion); secondary information that no second, independent
  source confirms (two pieces from the same informant, or from a source and
  what it copies, are not independent); an objection of the contradictor still
  open; a clash of dates (``warning``) left unexplained; a question only partly
  conform to the GPS. The steps add up, but no lower than *possible*:
  *unsupported* is for a conclusion on a refuted fact;
- at most *possible* for a question that does not conform to the GPS, or whose
  clash of dates is an ``error`` left unexplained;
- *proved* needs, besides, the excerpt of each concluding ``record`` fact,
  found as quoted (TRUST2), and no concluding fact whose reading is marked
  uncertain (``uncertain_reading``, T236): at most *probable* until a revision
  clears it.

It informs and blocks nothing (TRUST-D6): GPS-D13 already keeps a research open
when a question does not conform under ``proof.standard`` strict.
"""
LEVELS = ("unsupported", "possible", "probable", "proved")
STATUS_LEVEL = {"record": 3, "index": 2, "hypothesis": 1, "refuted": 0}


def _reason(why, ids=(), effect="down"):
    return {"why": why, "ids": sorted(set(ids)), "effect": effect}


def _key(text):
    """A text compared without case, accents or spacing."""
    import unicodedata

    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text or "")) if not unicodedata.combining(c))
    return " ".join(plain.lower().split())


def _original(sid, sources):
    """What a source stands for: the end of its ``derived_from`` chain, or the act it names (jurisdiction,
    register and act number); the source itself when it names neither."""
    seen = set()
    while sid not in seen and (sources.get(sid) or {}).get("derived_from"):
        seen.add(sid)
        sid = sources[sid]["derived_from"]
    s = sources.get(sid) or {}
    if s.get("register") and s.get("act_no"):
        return ("act", _key(s.get("jurisdiction")), _key(s["register"]), _key(s["act_no"]))
    return sid


def _apart(a, b, sources):
    """None when two pieces of evidence are independent; else why not: ``same-original`` or ``same-informant``.
    An informant not given is taken as another one."""
    if _original(a["source"], sources) == _original(b["source"], sources):
        return "same-original"
    if _key(a.get("informant")) and _key(a.get("informant")) == _key(b.get("informant")):
        return "same-informant"
    return None


def corroboration(fid, relied, sources=None):
    """None when an analysis the question relies on has two independent pieces of evidence, from two sources,
    that assert what the fact concludes; else why not: ``secondary`` (no second source), ``same-original`` (one
    source copies the other, or both are the same act) or ``same-informant`` (TRUST-D5)."""
    sources = sources or {}
    why = "secondary"
    for a in relied:
        items = a.get("items") or []
        kept = next((i for i in items if i.get("fact") == fid), None)
        if kept is None:
            continue
        said = " ".join((kept.get("asserts") or "").lower().split())
        agree = [i for i in items if i.get("source") and " ".join((i.get("asserts") or "").lower().split()) == said]
        for n, x in enumerate(agree):
            for y in agree[n + 1:]:
                if x["source"] == y["source"]:
                    continue
                apart = _apart(x, y, sources)
                if apart is None:
                    return None
                why = apart if why == "secondary" else why
    return why


def assess(question, fids, facts, relied, findings, proofs, gps_level, research_id, excerpt_state=None,
           sources=None):
    """{level, name, reasons} for an answered question; None for one that is open or unresolved.
    ``fids``: its concluding facts; ``facts``: the family's, by id; ``relied``: the analyses it relies on;
    ``findings``: its clashes of dates left unexplained; ``gps_level``: ``proof.standard.level``;
    ``sources``: the family's, by id."""
    if question.get("status") != "answered" or not fids:
        return None
    weakest = min(fids, key=lambda fid: STATUS_LEVEL.get(facts[fid].get("status"), 0))
    level = start = STATUS_LEVEL.get(facts[weakest].get("status"), 0)
    reasons = []
    if level < 3:
        reasons.append(_reason(facts[weakest].get("status") or "no-status", [weakest], "start"))
    axes = {fid: facts[fid].get("evidence") or {} for fid in fids}
    argued = any(p["research"] == research_id and p["question"] == question["id"]
                 and p["review"]["state"] == "accepted"
                 and any(r["reviewer"] == "contradictor" for r in p["review"]["rounds"]) for p in proofs)
    # an argument the contradictor reviewed and that was accepted establishes indirect or negative evidence, as the
    # GPS allows; an absence (T237) is not indirect evidence, and says so
    indirect = [] if argued else [fid for fid, e in axes.items() if e.get("evidence") == "indirect"]
    negative = [] if argued else [fid for fid, e in axes.items() if e.get("evidence") == "negative"]
    secondary = {}   # one step for secondary information not confirmed, whatever says why
    for fid, e in axes.items():
        why = corroboration(fid, relied, sources) if e.get("information") == "secondary" else None
        if why:
            secondary.setdefault(why, []).append(fid)
    objections = [p["id"] for p in proofs if p["research"] == research_id and p["question"] == question["id"]
                  and any(o["state"] == "open" for r in p["review"]["rounds"] for o in r["objections"])]
    warnings = [x for f in findings if f.get("severity") != "error" for x in f["facts"]]
    errors = [x for f in findings if f.get("severity") == "error" for x in f["facts"]]
    steps = [[("indirect", indirect), ("negative", negative)], sorted(secondary.items()), [("objection", objections)],
             [("chronology", warnings)]]
    for step in steps:
        step = [(why, ids) for why, ids in step if ids]
        if step:
            level -= 1
            reasons += [_reason(why, ids) for why, ids in step]
    if gps_level == "partial":
        level -= 1
        reasons.append(_reason("gps-partial", [question["id"]]))
    level = max(level, min(start, 1))   # the steps add up, but no lower than possible: unsupported is for a refuted fact
    cap = []
    if gps_level == "not_conform":
        cap.append(_reason("gps-not-conform", [question["id"]], "cap"))
    if errors:
        cap.append(_reason("chronology-error", errors, "cap"))
    if cap and level > 1:
        level = 1
    reasons += cap
    if level == 3 and excerpt_state is not None:
        unquoted = [fid for fid in fids if facts[fid].get("status") == "record"
                    and (not facts[fid].get("excerpt") or excerpt_state(facts[fid]) == "broken")]
        if unquoted:
            level = 2
            reasons.append(_reason("no-excerpt", unquoted, "cap"))
    # T236: a reading the transcription marked doubtful, not yet revised
    doubtful = [fid for fid in fids if str(facts[fid].get("uncertain_reading") or "").strip()]
    if doubtful:
        level = min(level, 2)
        reasons.append(_reason("uncertain-reading", doubtful, "cap"))
    level = max(level, 0)
    return {"level": level, "name": LEVELS[level], "reasons": reasons}


def describe(reason, t):
    """A reason, as a person reads it, in the language of ``t``."""
    from probandia.report import labels as L

    return t(L.CONFIDENCE_REASONS[reason["why"]]).format(ids=", ".join(reason["ids"]))
