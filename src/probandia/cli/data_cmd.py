"""Engine commands of the data layer: event, propose, apply, cite, known."""
import os

from probandia.cli.output import Result
from probandia.errors import EXIT_FAIL, UsageError
from probandia.i18n import _
from probandia.lifecycle import current_pass
from probandia.proposals import EXAMPLE_PARTS as PROPOSAL_PARTS
from probandia.util import yamlio


def actor(ctx):
    from probandia.harness import detect
    from probandia.util.locks import session_id

    harness, _how = detect(ctx.args.harness, ctx.environ)
    return {"harness": harness, "agent": ctx.args.agent or "session", "session": session_id(ctx.environ)}


def propose_parts(ctx, research, prefix, **parts):
    """Stores a proposal carrying ``parts`` (analyses=…, places=…), as propose would; returns its id."""
    from probandia.proposals import propose as store
    from probandia.util.ids import ulid

    me = actor(ctx)
    doc = {"schema": 1, "id": ulid(), "research": research.id, "pass": max(1, current_pass(research)),
           "author": {"harness": me["harness"], "agent": me["agent"]}}
    doc.update(parts)
    os.makedirs(research.work, exist_ok=True)
    draft = os.path.join(research.work, f"{prefix}-{doc['id']}.yaml")
    yamlio.dump(draft, doc)
    try:
        store(ctx.project, research, draft)
    finally:
        os.unlink(draft)
    return doc["id"]


def apply_own(ctx, research, pid):
    """A proposal the engine made for the agent who applies (a place's guide): applied at once when its
    dry run finds nothing to refuse, rejected otherwise, so that it never waits (token-economy J9: left
    unapplied, it stopped ``pass end`` at the bench of J8, 12 Oct. 2026). Returns (applied, reasons);
    (False, []) for an agent who may not apply, or a user who declines."""
    from probandia import proposals
    from probandia.cli import asking

    if actor(ctx)["agent"] not in proposals.APPLY_ROLES:
        return False, []
    path = os.path.join(proposals.proposals_folder(research), f"{pid}.yaml")
    _docs, _touched, reasons, _warnings = proposals.check(ctx.project, research, yamlio.load(path), ctx.config)
    if reasons:
        proposals.reject_own(path, reasons)
        return False, reasons
    if not asking.confirm(ctx, _("Apply the proposal {proposal} to the family? Once applied, it is corrected "
                                 "only by an erratum.").format(proposal=pid)):
        return False, []
    proposals.apply(ctx.project, pid, actor(ctx), ctx.config)
    return True, []


# event


def event_args(p, common):
    p.add_argument("action", choices=("append", "check"))
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--type", dest="event_type", help=_("event type, such as section.added"))
    p.add_argument("--payload-file", help=_("JSON or YAML file holding the payload"))
    p.add_argument("--refs", default="", help=_("comma-separated references"))
    p.add_argument("--pass", dest="pass_no", type=int, help=_("pass number (default: the last pass)"))


def event(ctx):
    from probandia import events
    from probandia.indexes import locked
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    if ctx.args.action == "check":
        broken = events.check_chain(research.events_path)
        count = len(events.read_lines(research.events_path))
        if broken:
            return Result("FAIL", {"REASON": "chain-broken", "RESEARCH": research.id,
                                   "LINE": broken[0], "EVENTS": count},
                          [_("events.jsonl is broken at line {n}: {what}").format(
                              n=broken[0], what=broken[1])])
        return Result("OK", {"RESEARCH": research.id, "EVENTS": count})
    if not ctx.args.event_type or not ctx.args.payload_file:
        raise UsageError(_("event append needs --type and --payload-file"))
    if ctx.args.event_type == "fact.checked":   # T248: only fact check, at a person's keyboard, writes it
        raise UsageError(_("fact.checked is written by fact check, which a person runs at the terminal"),
                         values={"REASON": "needs-person"})
    payload = yamlio.load(ctx.args.payload_file)
    if not isinstance(payload, dict):
        raise UsageError(_("the payload must be an object"))
    pass_no = ctx.args.pass_no
    if pass_no is None:
        pass_no = current_pass(research)
    refs = [r for r in ctx.args.refs.split(",") if r]
    section_id = None
    if ctx.args.event_type == "section.added" and isinstance(payload.get("section"), dict):
        from probandia.util.ids import ulid

        payload["section"].setdefault("id", ulid())  # the agent needs it as a parent or a reference
        section_id = payload["section"]["id"]
        refs = refs or [section_id]
    e = events.make(ctx.args.event_type, payload, actor(ctx), pass_no, refs)
    with locked(ctx.project, f"research:{research.id}", actor(ctx),
                ctx.config.get("locks.expiry_minutes")):
        written = events.append(research.events_path, [e])
    r = Result("OK", {"RESEARCH": research.id, "EVENT": written[0]["id"], "TYPE": written[0]["type"]})
    if section_id:
        r.set("SECTION", section_id)
    return r


# propose and apply


EXAMPLE_PARTS = ("all", *PROPOSAL_PARTS)


def propose_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("file", nargs="?", help=_("the proposal file"))
    p.add_argument("--example", type=_example_parts, metavar="<part,…>",
                   help=_("print a valid sample of parts of a proposal, and nothing else: {parts}").format(
                       parts=", ".join(EXAMPLE_PARTS)))
    p.add_argument("--apply", action="store_true",
                   help=_("then apply it, when the dry run finds no refusal (session or orchestrator)"))
    p.add_argument("--draft", action="store_true",
                   help=_("write the pass's proposal as far as the engine knows it (sources, searches, subject), "
                          "for the facts to be added"))


def _example_parts(text):
    """``facts,sources``: the parts of the example, in the order asked (token-economy J1: a pass
    with records needs four of them, not the whole example)."""
    import argparse

    parts = [p.strip() for p in text.split(",") if p.strip()]
    unknown = [p for p in parts if p not in EXAMPLE_PARTS]
    if not parts or unknown:
        raise argparse.ArgumentTypeError(_("unknown part {parts}: choose among {known}").format(
            parts=", ".join(unknown) or "''", known=", ".join(EXAMPLE_PARTS)))
    return ",".join(dict.fromkeys(parts))


def proposal_example(part="all"):
    """The text of ``schemas/examples/proposal-1.yaml``, whole or some top-level parts
    (``facts,sources``), comments kept: what an agent copies instead of reading the schema."""
    import re

    from probandia.paths import data

    with open(data("schemas", "examples", "proposal-1.yaml"), encoding="utf-8") as fh:
        text = fh.read()
    parts = part.split(",")
    if "all" in parts:
        return text
    return "".join(re.search(rf"^{p}:\n(?:(?:[ #].*)?\n)*", text, re.M).group(0) for p in parts)


SUMMARY_REASONS = 5   # reason lines shown; the summary stays within 10 lines (optimize 2.9)


def propose(ctx):
    """Stores the proposal and answers a summary of 10 lines at most, from a dry run
    of apply: the facts by status, what it adds, what would make apply refuse it.
    The orchestrator reads this summary, not the YAML."""
    from probandia import proposals
    from probandia.research import find_research

    if ctx.args.example:
        r = Result("OK", {"EXAMPLE": ctx.args.example})
        r.raw = proposal_example(ctx.args.example)
        return r
    if ctx.args.draft:
        return _draft(ctx)
    if ctx.args.research and not ctx.args.file:   # propose <file>: the research is the default one
        ctx.args.research, ctx.args.file = None, ctx.args.research
    if not ctx.args.file:
        raise UsageError(_("give the research and the proposal file, or --example <part>"))
    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    if ctx.args.apply and actor(ctx)["agent"] not in proposals.APPLY_ROLES:
        raise UsageError(_("only the orchestrator or the session agent may apply a proposal"),
                         values={"REASON": "not-allowed"})
    normalized = []
    me = actor(ctx)
    doc, path = proposals.propose(ctx.project, research, ctx.args.file, normalized,
                                  author={"harness": me["harness"], "agent": me["agent"]})
    counts = {k.upper(): len(doc.get(k, [])) for k in ("facts", "sources", "searches", "persons")}
    r = Result("OK", dict({"PROPOSAL": doc["id"], "RESEARCH": research.id}, **counts),
               details=os.path.relpath(path, ctx.project).replace(os.sep, "/"))
    for line in normalized:   # H3: a short form put in the schema's form, stored so
        r.data("normalized", line)
    reasons = []
    for line in summary(ctx, research, doc, reasons):
        r.lines.append(line)
    if any(line.startswith("verdict=would-reject") for line in r.lines):
        r.status = "WARN"
        if me["agent"] in proposals.APPLY_ROLES:   # J8: its author reads why and proposes it again
            proposals.reject_own(path, reasons)
    if ctx.args.apply:
        return _apply_proposed(ctx, r, doc["id"]) or r
    return r


def _draft(ctx):
    """T76: ``propose --draft [<research>]`` writes ``work/proposals/draft-<pass>.yaml``, which the agent completes
    with its facts instead of writing the whole proposal; never over a draft it may be filling. Named after no id,
    the draft is not a pending proposal."""
    from probandia import proposals
    from probandia.research import find_research
    from probandia.util.fs import atomic_write_text

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    path = os.path.join(proposals.proposals_folder(research), f"draft-{max(1, current_pass(research))}.yaml")
    rel = os.path.relpath(path, ctx.project).replace(os.sep, "/")
    if os.path.exists(path):
        return Result("WARN", {"DRAFT": rel}, [_("the draft exists: complete it")])
    me = actor(ctx)
    text, subject, sources, searches = proposals.draft(ctx.project, research,
                                                       {"harness": me["harness"], "agent": me["agent"]})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, text)
    r = Result("OK", {"DRAFT": rel, "SOURCES": sources, "SEARCHES": searches})
    if subject:
        r.set("SUBJECT", subject)
    r.line(_("add at its end your facts, under facts:, then the new persons and the sections; propose it with --apply"))
    return r


def _apply_proposed(ctx, r, pid):
    """token-economy B2: ``propose --apply`` applies at once when the dry run announces no refusal;
    otherwise the summary stands alone, as without --apply (``APPLIED=false``)."""
    from probandia import proposals
    from probandia.cli import asking

    r.set("APPLIED", False)
    if not any(line.startswith("verdict=would-apply") for line in r.lines):
        return
    if not asking.confirm(ctx, _("Apply the proposal {proposal} to the family? Once applied, it is corrected "
                                 "only by an erratum.").format(proposal=pid)):
        return
    _status, info = proposals.apply(ctx.project, pid, actor(ctx), ctx.config)
    r.set("APPLIED", True)
    r.set("EVENTS", info.get("events", 0))
    if info.get("warnings"):
        r.status = "WARN"
        r.lines += info["warnings"]
    from probandia.cli.workshop_cmd import after_apply

    return after_apply(ctx, info["research"], r)


def summary(ctx, research, doc, all_reasons=None):
    """At most 10 data lines: facts by status, additions, verdict, reasons, warnings. ``all_reasons``,
    a list, receives every reason of refusal, beyond the five shown."""
    import collections

    from probandia import proposals

    facts = list(doc.get("facts", [])) + [f for p in doc.get("persons", []) for f in p.get("facts", [])]
    by_status = collections.Counter(f.get("status", "?") for f in facts)
    negatives = [s for s in doc.get("searches", []) if s.get("result") == "negative"]
    out = ["facts=" + (" ".join(f"{k}:{v}" for k, v in sorted(by_status.items())) or "0"),
           f"adds=persons:{len(doc.get('persons', []))} sources:{len(doc.get('sources', []))} "
           f"searches:{len(doc.get('searches', []))} negatives:{len(negatives)} "
           f"hypotheses:{len(doc.get('hypotheses', []))} errata:{len(doc.get('errata', []))} "
           f"sections:{len(doc.get('sections', []))}"]
    records = [str(f.get("id", "?")) for f in facts if f.get("status") == "record"]
    if records and not doc.get("searches"):   # token-economy H1: the search a next pass would otherwise redo
        out.append("missing_search=" + ",".join(records[:5]) + " " + _(
            "record facts without the search that found them: add it to searches (the archive, the call number, "
            "the views read, the result, and the negative it proves for the rest of the views)"))
    try:
        _docs, touched, reasons, warnings = proposals.check(ctx.project, research, doc, ctx.config)
    except Exception as err:   # a dry run that fails says so; apply will tell the rest
        return out + [f"verdict=unknown {type(err).__name__}"]
    if all_reasons is not None:
        all_reasons.extend(reasons)
    conflicts = [x for x in reasons if not x.startswith(("P-1", "P-2", "P-3"))]
    citations = [x for x in reasons if x.startswith(("P-1", "P-2"))]
    out.append(f"verdict={'would-reject' if reasons else 'would-apply'} reasons={len(reasons)} "
               f"conflicts={len(conflicts)} citations={len(citations)} "
               f"negatives={len(reasons) - len(conflicts) - len(citations)} persons_touched={len(touched)}")
    shown = reasons[:SUMMARY_REASONS]
    out += [f"reason={x}" for x in shown]
    if len(reasons) > len(shown):
        out.append(f"reason=… {len(reasons) - len(shown)} more: apply lists them all")
    if warnings:
        out.append("warning=" + "; ".join(warnings)[:300])
    return out[:10]


def apply_args(p, common):
    p.add_argument("proposal", help=_("the proposal id, or its file"))
    p.add_argument("--drop", metavar="REASON", help=_("set the proposal aside without applying it, and say why"))


def apply(ctx):
    from probandia import proposals

    if ctx.args.drop is not None:
        research, pid = proposals.drop(ctx.project, ctx.args.proposal, actor(ctx), ctx.args.drop)
        return Result("OK", {"PROPOSAL": pid, "RESEARCH": research.id, "STATE": "dropped"})
    from probandia.cli import asking

    if not asking.confirm(ctx, _("Apply the proposal {proposal} to the family? Once applied, it is corrected "
                                 "only by an erratum.").format(proposal=ctx.args.proposal)):
        return asking.declined({"PROPOSAL": ctx.args.proposal})
    status, info = proposals.apply(ctx.project, ctx.args.proposal, actor(ctx), ctx.config)
    if status == "already":
        return Result("WARN", {"PROPOSAL": info["proposal"], "RESEARCH": info["research"]},
                      [_("this proposal was already applied; nothing changed")])
    r = Result("WARN" if info["warnings"] else "OK",
               {"PROPOSAL": info["proposal"], "RESEARCH": info["research"],
                "EVENTS": info["events"], "PERSONS": len(info["touched"])}, info["warnings"])
    from probandia.cli.workshop_cmd import after_apply

    return after_apply(ctx, info["research"], r)


# cite


def cite_args(p, common):
    from probandia import cite as citing

    p.add_argument("source", nargs="?", help=_("a source id (src-…) of the family"))
    p.add_argument("--form", action="store_true", help=_("build a citation from the fields below"))
    p.add_argument("--type", type=citing.type_name, choices=citing.types(),
                   help=_("the type of the source: its model asks for its own fields"))
    p.add_argument("--as", dest="as_form", choices=citing.FORMS,
                   help=_("one form only: full (list of sources), first (first note) or short"))
    p.add_argument("--family", help=_("the family (default: the only one)"))
    for field in ("repository", "collection", "reference", "item", "page", "image", "url",
                  "accessed"):
        p.add_argument(f"--{field}")
    for field in TYPED_FIELDS:
        p.add_argument("--" + field.replace("_", "-"), dest=f"f_{field}")
    p.add_argument("--layer", choices=LAYER_FORMS, help=_("the reproduction consulted (one layer)"))
    for field in ("by", "url", "image", "accessed"):
        p.add_argument(f"--layer-{field}", dest=f"layer_{field}")
    p.add_argument("--copy", action="store_true", help=_("also put the citation in the clipboard"))


TYPED_FIELDS = ("jurisdiction", "act", "register", "folio", "act_no", "act_date", "names", "notary",
                "class", "matricule", "title", "author", "publisher", "published", "issue_date")
LAYER_FORMS = ("online-image", "microfilm", "database", "index", "transcription", "abstract", "publication")


def cite(ctx):
    r = _cite(ctx)
    if r.status in ("OK", "WARN"):
        r.view = "cite"
        if ctx.args.copy:
            from probandia.util.clipboard import copy

            tool = copy(r.values["CITATION"], ctx.environ)
            r.extra = {"copied": tool}
            if tool is None:
                r.status = "WARN"
                r.line(_("no clipboard tool found: install clip, pbcopy, wl-copy or xclip"))
    return r


def _form_fields(ctx):
    fields = {k: getattr(ctx.args, k) for k in ("repository", "collection", "reference", "item",
                                                "page", "url", "accessed")}
    fields["image_no"] = ctx.args.image
    if not ctx.args.type:
        return fields
    fields["type"] = ctx.args.type
    for field in TYPED_FIELDS:
        value = getattr(ctx.args, f"f_{field}")
        if value:
            fields[field] = [n.strip() for n in value.split(";") if n.strip()] if field == "names" else value
    if ctx.args.layer:
        layer = {"form": ctx.args.layer, "by": ctx.args.layer_by, "url": ctx.args.layer_url,
                 "image_no": ctx.args.layer_image, "accessed": ctx.args.layer_accessed}
        fields["layers"] = [{k: v for k, v in layer.items() if v}]
    return {k: v for k, v in fields.items() if v not in (None, "")}


def _citation(source, ctx, values):
    """The values of a citation: CITATION (the form asked, else the first note), and the
    three forms of a typed source when no form is asked."""
    from probandia import cite as citing

    lang = None   # the language of messages: --lang, else the project's
    if not source.get("type"):
        if ctx.args.form:
            values["CITATION"] = citing.sentence(source)
        else:
            values["CITATION"] = citing.ensure(source)["citation"]
        return Result("OK", values)
    if ctx.args.as_form:
        values["FORM"] = ctx.args.as_form
        values["CITATION"] = citing.format(source, ctx.args.as_form, lang)
    else:
        forms = citing.forms(source, lang)
        values.update(FULL=forms["full"], CITATION=forms["first"], SHORT=forms["short"])
    values["TYPE"] = source["type"]
    if citing.lacking(source):
        values["LACKING"] = ",".join(citing.lacking(source))
    holes = citing.missing(source)
    if not holes:
        return Result("OK", values)
    values["MISSING"] = ",".join(holes)
    flag = "--" if ctx.args.form else ""
    return Result("WARN", values, [_("required by the model of {type}, missing: {fields}").format(
        type=source["type"], fields=", ".join(flag + f.replace("_", "-") if flag else f for f in holes))])


def _cite(ctx):
    from probandia.indexes import FamilyIndexes
    from probandia.research import default_family

    if ctx.args.form:
        return _citation(_form_fields(ctx), ctx, {})
    if not ctx.args.source:
        raise UsageError(_("give a source id, or --form with its fields"))
    family = ctx.args.family or default_family(ctx.project)
    for s in FamilyIndexes(ctx.project, family).items("sources"):
        if s["id"] == ctx.args.source:
            return _citation(s, ctx, {"SOURCE": s["id"]})
    return Result("FAIL", {"REASON": "unknown-source", "SOURCE": ctx.args.source},
                  [_("no source {source} in family {family}").format(source=ctx.args.source,
                                                                     family=family)],
                  exit_code=EXIT_FAIL)


# known


def known_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--names", help=_("surnames, comma-separated"))
    p.add_argument("--places", help=_("places, comma-separated"))
    p.add_argument("--window", help=_("years: 1840-1860, 1851 or 1851+-5"))
    p.add_argument("--family", help=_("the family, instead of a research"))


def known(ctx):
    from probandia import known as k
    from probandia.research import find_research

    family = ctx.args.family or find_research(ctx.project, ctx.args.research, ctx.environ).family
    return known_result(ctx, family, k.split_list(ctx.args.names), k.split_list(ctx.args.places),
                        k.parse_window(ctx.args.window))


def known_result(ctx, family, names, places, window):
    """The Result of ``known``; ``new`` runs it too, on the plan's names, places and window (token-economy B1)."""
    from probandia import known as k

    found = k.known(ctx.project, family, names, places, window, ctx.config)
    r = Result("OK", {"FAMILY": family, "FACTS": len(found["facts"]),
                      "NEGATIVES": len(found["negatives"]),
                      "NEGATIVES_DUE": sum(1 for n in found["negatives"] if n["state"] == "due"),
                      "HYPOTHESES": len(found["hypotheses"]), "GAPS": len(found["gaps"])},
               k.lines(found))
    if found["facts"] and not (names or places or window):
        # F1: unfiltered, the facts are counted here and listed in the details file only
        from probandia.util.fs import atomic_write_text
        from probandia.util.ids import ulid

        path = os.path.join(ctx.project, ".probandia", "details", f"known-{ulid()}.txt")
        try:
            atomic_write_text(path, "\n".join(r.lines) + "\n")
            r.details = os.path.relpath(path, ctx.project).replace(os.sep, "/")
        except OSError:   # a read-only sandbox (Codex's contradictor, T129): the counts still go out
            r.lines.insert(0, _("the details could not be written: only the first lines follow"))
        by_status = {}
        for f in found["facts"]:
            by_status[f["status"]] = by_status.get(f["status"], 0) + 1
        r.set("PERSONS", len({f["id"].rsplit(".", 1)[0] for f in found["facts"]}))
        r.set("BY_STATUS", ",".join(f"{s}:{n}" for s, n in by_status.items()))
        r.lines = [line for line in r.lines if not line.startswith("fact=")]
        if r.details:
            r.line(_("each fact is in DETAILS; give --names, --places or --window to list them here"))
    r.table("facts", [{"person": f["id"].rsplit(".", 1)[0], "fact": f["type"], "date": k.date_text(f),
                       "place": k.place_text(f), "status": f["status"], "source": f.get("source")}
                      for f in found["facts"]])
    r.table("negatives", [{"search": s["id"], "state": s["state"], "query": s["query"],
                           "engine": s.get("engine") or s["kind"],
                           "window": f"{(s.get('window') or {}).get('from', '?')}-{(s.get('window') or {}).get('to', '?')}"}
                          for s in found["negatives"]])
    r.table("hypotheses", [{"hypothesis": x["id"], "question": x["question"]} for x in found["hypotheses"]])
    r.table("gaps", [{"archive": g["archive"], "reference": g.get("reference"),
                      "window": f"{g['window']['from']}-{g['window']['to']}", "kind": g["kind"]}
                     for g in found["gaps"]])
    r.view = "known"
    return r
