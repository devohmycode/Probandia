"""Proposals: what field agents propose, and ``apply``, which accepts or rejects them whole.

Field agents never write the indexes. They write ``work/proposals/<ULID>.yaml``
and run ``propose``. The orchestrator, or the session agent, runs ``apply``:

1. check the proof rules on the proposal and the family as it would become:
   P-1 a citation for every ``record`` and ``index`` fact; P-2 ``record`` only with
   an image or a transcription, and neither ``record`` nor ``index`` on an online
   tree, a lead and never a proof (T238); P-3 every negative has a witness passed within
   ``witness.max_age_hours``, a detector status of ok, variants and a window, and one that
   serves as proof (``proves: proof``) says why the record should exist (``expected``, T249);
   P-9 chronology; no person their own ancestor (T250); every non-link respected; a gap
   names known places and source types; presumed-living persons flagged;
2. take the family lock; 3. write the indexes; 4. append the events;
5. write ``<proposal>.result``; 6. release the lock.

A rejection changes nothing but the ``.result`` file and ends with exit code 1.
``apply --drop "<reason>"`` sets a proposal aside: only its ``.result`` is written.
A pass does not end while one of its proposals is still pending. The proposal of the agent who
applies, when ``propose`` finds it would be refused, is rejected at once; the pass still does not end
until a later proposal of the same author is applied, or it is dropped.
"""
import filecmp
import json
import os
import re
import shutil

from probandia import cite, events, images
from probandia.errors import EXIT_FAIL, ProbandiaError, UsageError
from probandia.i18n import _
from probandia.indexes import FamilyIndexes, locked
from probandia.research import all_researches
from probandia.util import yamlio
from probandia.util.fs import iso, parse_iso, utc_now
from probandia.util.ids import ulid
from probandia.util.schema import validate_document

APPLY_ROLES = ("orchestrator", "session")
BIRTH = ("birth", "baptism")
END = ("death", "burial")


class Rejected(ProbandiaError):
    exit_code = EXIT_FAIL
    reason = "rejected"


def proposals_folder(research):
    return os.path.join(research.work, "proposals")


# propose


EXAMPLE_PARTS = ("persons", "facts", "sources", "searches", "hypotheses", "errata", "refutations", "sections")


def normalize(doc):
    """The short forms that cannot be misread, put in the schema's own form (token-economy H3):
    ``spouses: [<id>]`` becomes ``[{person: <id>}]``; a person's ``facts: [<id>]`` naming facts of
    ``facts`` is emptied of them; a search's ``support: record``, the fact's
    level written for the search's, becomes ``image`` (refused on every pass at the bench, I1 of
    11 Oct. 2026); a search with no ``id``, or a made-up one, gets one, as the proposal does, and one
    with no ``ts`` the time of the proposal (refused at the bench, A7 and J2-J3 of 11 Oct. 2026: no
    part of a proposal names a search by its id). Returns what changed, one line each."""
    done = []
    listed = {f.get("id") for f in doc.get("facts") or [] if isinstance(f, dict)}
    for i, person in enumerate(doc.get("persons") or []):
        spouses = person.get("spouses") if isinstance(person, dict) else None
        for j, spouse in enumerate(spouses if isinstance(spouses, list) else []):
            if isinstance(spouse, str):
                spouses[j] = {"person": spouse}
                done.append(f"persons[{i}].spouses[{j}] {spouse} -> {{person: {spouse}}}")
        # J8: a person's facts named by their id, when ``facts`` holds them (refused in each session of the
        # bench of J7, 12 Oct. 2026): the id already ties a fact to its person
        facts = person.get("facts") if isinstance(person, dict) else None
        named = [f for f in facts if isinstance(f, str) and f in listed] if isinstance(facts, list) else []
        if named:
            person["facts"] = [f for f in facts if f not in named]
            done.append(f"persons[{i}].facts {', '.join(named)} -> facts")
    for i, search in enumerate(doc.get("searches") or []):
        if not isinstance(search, dict):
            continue
        if search.get("support") == "record":
            search["support"] = "image"
            done.append(f"searches[{i}].support record -> image")
        if not SEARCH_ID.match(str(search.get("id") or "")):
            was = search.get("id") or "(none)"
            search["id"] = f"s-{ulid()}"
            done.append(f"searches[{i}].id {was} -> {search['id']}")
        if not search.get("ts"):
            search["ts"] = iso(utc_now())
            done.append(f"searches[{i}].ts (none) -> {search['ts']}")
    for i, source in enumerate(doc.get("sources") or []):   # T247: the first of the views is the image
        views = source.get("images") if isinstance(source, dict) else None
        if isinstance(views, list) and views and isinstance(views[0], str) and not source.get("image"):
            source["image"] = views[0]
            done.append(f"sources[{i}].image (none) -> images[0]")
    return done


SEARCH_ID = re.compile(r"^s-[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def header(doc, research, author):
    """The head of a proposal, which the engine knows: its research, the pass open, its author (the
    agent's ``--agent``), when left out or written short (``author: main``); the four-part example of
    J1 shows none of them (refused twice in each session of the bench, 11 Oct. 2026). Returns one
    line, or none."""
    from probandia.lifecycle import current_pass

    filled = []
    if not doc.get("research"):
        doc["research"] = research.id
        filled.append("research")
    if not doc.get("pass"):
        doc["pass"] = max(1, current_pass(research))
        filled.append("pass")
    if not isinstance(doc.get("author"), dict) and author:
        doc["author"] = dict(author)
        filled.append("author")
    shown = {"research": doc["research"], "pass": doc["pass"],
             "author": (doc.get("author") or {}).get("agent") if isinstance(doc.get("author"), dict) else None}
    return [f"{', '.join(filled)} (none) -> {', '.join(str(shown[k]) for k in filled)}"] if filled else []


def propose(project, research, path, normalized=None, author=None):
    """Validates a proposal file and stores it in the research's work/proposals/.
    ``normalized``, a list, receives what ``header`` filled and ``normalize`` changed; ``author``
    is ``{harness, agent}`` of the agent who proposes."""
    from probandia.errors import SchemaError

    doc = yamlio.load_input(path)
    if not isinstance(doc, dict):
        raise UsageError(_("{path} is not a proposal").format(path=path))
    doc.setdefault("schema", 1)
    for part in [p for p in EXAMPLE_PARTS if p in doc and doc[p] is None]:   # T76: a draft's facts: left empty
        del doc[part]
    if not doc.get("id"):
        doc["id"] = ulid()
    changed = header(doc, research, author) + normalize(doc)
    if normalized is not None:
        normalized.extend(changed)
    try:
        validate_document("proposal", doc, os.path.basename(path))
    except SchemaError as err:   # H3: the sample of the part at fault, rather than the schema
        part = next((p for p in EXAMPLE_PARTS for e in err.errors[:1] if str(e.path).startswith(f"$.{p}")), None)
        if part:
            err.lines.append(f"example=propose --example {part}")
        raise
    if doc["research"] != research.id:
        raise UsageError(_("the proposal is for research {other}, not {research}").format(
            other=doc["research"], research=research.id))
    from probandia import excerpt

    try:   # token-economy B4: an excerpt by reference is stored in its long form, said nowhere (a form, not a fault)
        excerpt.resolve(project, research.family, doc)
    except ValueError as err:
        raise UsageError(str(err), values={"REASON": "excerpt"}) from None
    folder = proposals_folder(research)
    target = os.path.join(folder, f"{doc['id']}.yaml")
    yamlio.dump(target, doc)
    return doc, target


def find_proposal(project, ref):
    """(research, path) of a proposal given by its path or its id. A file given by its
    path stands for its stored copy (``work/proposals/<id>.yaml``), stored first when
    ``propose`` was skipped: the ``.result`` always lands next to the stored copy."""
    if os.path.isfile(ref):
        doc = yamlio.load_input(ref) or {}
        for r in all_researches(project):
            if r.id == doc.get("research"):
                if os.path.dirname(os.path.abspath(ref)) == os.path.abspath(proposals_folder(r)) and \
                        os.path.basename(ref) == f"{doc.get('id')}.yaml":
                    return r, os.path.abspath(ref)  # the stored copy itself
                stored_doc, stored = propose(project, r, ref)  # the draft as it is now
                if not doc.get("id"):  # keep the id, so that the same draft is never applied twice
                    yamlio.dump(ref, dict(doc, id=stored_doc["id"]))
                return r, stored
        raise UsageError(_("the research of {path} is not in this project").format(path=ref))
    for r in all_researches(project):
        path = os.path.join(proposals_folder(r), f"{ref}.yaml")
        if os.path.isfile(path):
            return r, path
    raise UsageError(_("no proposal {ref}").format(ref=ref))


# the rules


def person_of(fact_id):
    return fact_id.split(".", 1)[0]


def year(fact, last=False):
    date = fact.get("date") or {}
    value = (date.get("end") if last and date.get("end") else date.get("value")) or ""
    try:
        return int(value[:5] if value.startswith("-") else value[:4])
    except ValueError:
        return None


def _now():
    return utc_now()


def check_sources(facts, sources):
    reasons = []
    for f in facts:
        if f["status"] not in ("record", "index"):
            continue
        src = sources.get(f.get("source") or "")
        if not f.get("source"):
            reasons.append(_("P-1: fact {fact} ({status}) has no source").format(
                fact=f["id"], status=f["status"]))
            continue
        if src is None:
            reasons.append(_("P-1: fact {fact} cites {source}, which is not known").format(
                fact=f["id"], source=f["source"]))
            continue
        if not src.get("citation") and not src.get("repository"):
            reasons.append(_("P-1: source {source} has no citation and no repository").format(
                source=src["id"]))
        if f["status"] == "record" and not (src.get("image") or src.get("transcription")):
            reasons.append(_("P-2: fact {fact} is a record, but source {source} has no image "
                             "and no transcription").format(fact=f["id"], source=src["id"]))
        if src.get("type") == "online-tree":   # T238: a tree found online is a lead, as an imported one
            reasons.append(_("P-2: fact {fact} is {status}, but source {source} is an online tree: a hypothesis at "
                             "most").format(fact=f["id"], status=f["status"], source=src["id"]))
    return reasons


def check_views(sources):
    """T247: a source's ``images`` are its views in order, and its ``image`` the first of them."""
    return [_("P-2: source {source}: its image {image} is not the first of its images").format(
        source=s["id"], image=s.get("image") or "-")
        for s in sources if s.get("images") and s.get("image") != s["images"][0]]


IMAGE_FILE = re.compile(r"\.(?:jpe?g|png|tiff?|gif|webp|jp2|pdf)\b", re.I)


def _outside(project, path):
    try:
        return os.path.relpath(os.path.abspath(path), os.path.abspath(project)).startswith(os.pardir)
    except ValueError:   # another drive
        return True


def _image_path(research, view):
    """Where a source's view is on this computer: as written when absolute, else from the family's folder."""
    return os.path.expanduser(view) if os.path.isabs(os.path.expanduser(view)) else \
        os.path.join(research.family_folder, view)


def check_images(project, research, sources):
    """T264: a view of a proposed source is a path, or a URL, and nothing after it; a file outside the
    project must exist, for ``apply`` copies it under the family's evidence."""
    reasons = []
    for s in sources:
        for view in images.views(s):
            if "://" in view:
                continue
            m = IMAGE_FILE.search(view)
            if m and view[m.end():].strip():
                reasons.append(_("P-2: source {source}: its image holds more than a path ({image}); say the "
                                 "rest in its note").format(source=s["id"], image=view))
                continue
            path = _image_path(research, view)
            if _outside(project, path) and not os.path.isfile(path):
                reasons.append(_("P-2: source {source}: its image {image} is outside the project and is not "
                                 "found").format(source=s["id"], image=view))
    return reasons


def keep_images(project, research, doc):
    """T264: a view of a proposed source kept outside the project (a temporary folder) is copied under the
    family's ``evidence/images/``, and the source names the copy: the proof outlives the folder."""
    folder = os.path.join(research.family_folder, "evidence", "images")
    for s in doc.get("sources", []):
        moved = {}
        for view in images.views(s):
            path = _image_path(research, view)
            if "://" in view or not _outside(project, path) or not os.path.isfile(path):
                continue
            os.makedirs(folder, exist_ok=True)
            stem, ext = os.path.splitext(os.path.basename(path))
            name, n = f"{s['id']}-{stem}{ext}", 1
            while os.path.exists(os.path.join(folder, name)) and not filecmp.cmp(path, os.path.join(folder, name),
                                                                                 shallow=False):
                n += 1
                name = f"{s['id']}-{stem}-{n}{ext}"
            shutil.copyfile(path, os.path.join(folder, name))
            moved[view] = f"evidence/images/{name}"
        if moved:
            if s.get("image") in moved:
                s["image"] = moved[s["image"]]
            if s.get("images"):
                s["images"] = [moved.get(v, v) for v in s["images"]]


def check_transcriptions(project, research, before, after, persons):
    """T265: a proposal that gives a known source another transcription keeps every excerpt the facts
    cite from it: one that read in the old transcription and no longer reads in the new refuses it."""
    from probandia import excerpt

    reasons = []
    for sid, new in after.items():
        old = before.get(sid)
        if not old or old.get("transcription") == new.get("transcription"):
            continue
        for p in persons:
            for f in p.get("facts") or []:
                if f.get("source") != sid or (f.get("excerpt") or {}).get("kind") != "transcription":
                    continue
                if excerpt.check(project, research.family, f, before, research):
                    continue
                why = excerpt.check(project, research.family, f, after, research)
                if why:
                    reasons.append(_("P-2: source {source}: its transcription would become {new}, where the "
                                     "excerpt of fact {fact} no longer reads ({why}); a second reading stays "
                                     "the second (transcribe compare)").format(
                        source=sid, new=new.get("transcription") or "-", fact=f["id"], why="; ".join(why)))
    return reasons


def check_excerpts(project, research, facts, sources):
    """TRUST1-T5: the excerpt of a fact is found, word for word, in its transcription or in the page read."""
    from probandia import excerpt

    return [_("excerpt of fact {fact}: {why}").format(fact=f["id"], why=why)
            for f in facts for why in excerpt.check(project, research.family, f, sources, research)]


def check_negatives(searches, max_age_hours, now):
    reasons = []
    for s in searches:
        if s["result"] != "negative":
            continue
        w = s.get("witness")
        if not w or not w.get("passed"):
            reasons.append(_("P-3: negative {search} has no passed witness").format(search=s["id"]))
        elif (now - parse_iso(w["ts"])).total_seconds() > max_age_hours * 3600:
            reasons.append(_("P-3: the witness of negative {search} is older than {hours} hours")
                           .format(search=s["id"], hours=max_age_hours))
        if s.get("failure"):
            reasons.append(_("P-3: negative {search} comes from a failed access ({failure})")
                           .format(search=s["id"], failure=s["failure"]))
        if not s.get("variants"):
            reasons.append(_("P-3: negative {search} records no variants").format(search=s["id"]))
        window = s.get("window") or {}
        if window.get("from") is None or window.get("to") is None:
            reasons.append(_("P-3: negative {search} records no window").format(search=s["id"]))
        if s.get("proves") == "proof" and not str(s.get("expected") or "").strip():
            # T249: an absence proves something only if the record should have been there
            reasons.append(_("P-3: negative {search} serves as proof, but does not say why the record should "
                             "exist there (expected)").format(search=s["id"]))
    return reasons


def _first(facts, types, last=False):
    years = [year(f, last) for f in facts if f["type"] in types and f["status"] in ("record", "index")]
    years = [y for y in years if y is not None]
    if not years:
        return None
    return max(years) if last else min(years)


def check_chronology(persons, touched, sources=None):
    """P-9 on the persons a proposal touches, and on their parents and children; with ``sources``, by id, each
    fact against the date of its act (T244)."""
    from probandia import chronology

    return chronology.check(persons, touched, sources=sources)


def check_analyses(analyses, persons):
    """GPS4: an analysis is about a known person, cites known facts, and a resolved one says what it kept."""
    people = {p["id"]: p for p in persons}
    facts = {f["id"] for p in persons for f in p.get("facts", [])}
    reasons = []
    for a in analyses:
        if a["person"] not in people:
            reasons.append(_("analysis {id}: no person {person} in the family").format(id=a["id"], person=a["person"]))
        cited = [i["fact"] for i in a["items"] if i.get("fact")] + [(a.get("resolution") or {}).get("fact")]
        for fid in [x for x in cited if x and x not in facts]:
            reasons.append(_("analysis {id}: no fact {fact} in the family").format(id=a["id"], fact=fid))
        if a["status"] == "resolved" and not a.get("resolution"):
            reasons.append(_("analysis {id}: resolved, but without its resolution").format(id=a["id"]))
        if a["status"] == "divergent" and not (a.get("reason") or "").strip():
            reasons.append(_("analysis {id}: divergent, but without the reason it is left unresolved")
                           .format(id=a["id"]))
    return reasons


def check_proofs(proofs, persons, analyses):
    """GPS5: a proof argument cites known facts and analyses, and an accepted one leaves no objection open."""
    facts = {f["id"] for p in persons for f in p.get("facts", [])}
    known = {a["id"] for a in analyses}
    reasons = []
    for pf in proofs:
        for fid in [x for x in pf.get("conclusion") or [] if x not in facts]:
            reasons.append(_("proof {id}: no fact {fact} in the family").format(id=pf["id"], fact=fid))
        for aid in [x for x in pf.get("analyses") or [] if x not in known]:
            reasons.append(_("proof {id}: no analysis {analysis} in the family").format(id=pf["id"], analysis=aid))
        still = [o["n"] for r in pf["review"]["rounds"] for o in r["objections"] if o["state"] == "open"]
        if pf["review"]["state"] == "accepted" and still:
            reasons.append(_("proof {id}: accepted with objection(s) still open: {n}").format(
                id=pf["id"], n=", ".join(str(n) for n in still)))
    return reasons


def check_ancestry(persons, touched):
    """T250: no person is their own ancestor. From each person a proposal touches, the parents are followed up;
    a way back to that person is refused, with the persons it goes through."""
    parents = {p["id"]: [x for x in ((p.get("parents") or {}).get("father"), (p.get("parents") or {}).get("mother"))
                         if x] for p in persons}
    reasons, found = [], set()
    for start in sorted(touched):
        stack, seen = [(x, [start, x]) for x in parents.get(start, [])], set()
        while stack:
            pid, path = stack.pop()
            if pid == start:
                if frozenset(path) not in found:
                    found.add(frozenset(path))
                    reasons.append(_("{person} would be their own ancestor: {path}").format(
                        person=start, path=" → ".join(path)))
                break
            if pid in seen:
                continue
            seen.add(pid)
            stack += [(x, path + [x]) for x in parents.get(pid, [])]
    return reasons


def check_non_links(persons, touched, non_links):
    reasons = []
    excluded = {frozenset((n["a"], n["b"])): n for n in non_links}
    for p in persons:
        if p["id"] not in touched:
            continue
        parents = p.get("parents") or {}
        links = [parents.get("father"), parents.get("mother")]
        links += [s.get("person") for s in p.get("spouses", [])]
        for other in links:
            if other and frozenset((p["id"], other)) in excluded:
                n = excluded[frozenset((p["id"], other))]
                reasons.append(_("non-link: {a} and {b} were shown to be unrelated ({reason})")
                               .format(a=p["id"], b=other, reason=n["reason"]))
    return reasons


def presumed_living(persons, touched, living_years, today):
    """The touched persons that shared outputs will mask: the rule of ``report.living`` (T240)."""
    from probandia.report import living

    by_id = {p["id"]: p for p in persons}
    return [p["id"] for p in persons
            if p["id"] in touched and living.presumed_living(p, by_id, living_years or 100, today)]


# apply


def _merge_by_id(existing, new):
    out = {item["id"]: item for item in existing}
    for item in new:
        out[item["id"]] = item
    return list(out.values())


def _gap_number(gap):
    gid = gap.get("id") or ""
    return int(gid[1:]) if gid[1:].isdigit() else 0


def merge_gaps(existing, new):
    """GPS3-T2: a gap with an id replaces the one of that id; one without an id
    is added once, under the next free ``G<n>``."""
    out = list(existing)
    n = max((_gap_number(g) for g in out + list(new)), default=0)
    for gap in new:
        if gap.get("id"):
            at = next((i for i, g in enumerate(out) if g.get("id") == gap["id"]), None)
            if at is None:
                out.append(gap)
            else:
                out[at] = gap
        elif not any({k: v for k, v in g.items() if k != "id"} == gap for g in out):
            n += 1
            out.append({"id": f"G{n}", **gap})
    return out


def check_gaps(gaps, places):
    """A gap names a known place and known source types."""
    from probandia.proof import source_types

    known = {t["id"] for t in source_types.load()["types"]} if gaps else set()
    ids = {p["id"] for p in places}
    reasons = []
    for gap in gaps:
        label = gap.get("id") or gap["archive"]
        if gap.get("place") and gap["place"] not in ids:
            reasons.append(_("gap {gap}: no place {place} in the family").format(gap=label, place=gap["place"]))
        for t in [t for t in gap.get("types") or [] if t not in known]:
            reasons.append(_("gap {gap}: unknown source type {type}").format(gap=label, type=t))
    return reasons


def merged_state(indexes, doc, volet=None, docs=None):
    """The family indexes as they would be once the proposal is applied, and
    the persons it touches. Raises Rejected for facts it cannot place. ``docs``:
    the indexes already loaded, changed in place; else they are loaded."""
    docs = indexes.load_all() if docs is None else docs
    reasons = []
    persons = {p["id"]: p for p in docs["persons"]["persons"]}
    touched = set()
    for p in doc.get("persons", []):
        old = persons.get(p["id"])
        new = dict(p)
        new["facts"] = list((old or {}).get("facts", [])) + list(p.get("facts", []))
        persons[p["id"]] = new
        touched.add(p["id"])
    known_facts = {f["id"] for p in persons.values() for f in p.get("facts", [])}
    for f in doc.get("facts", []):
        pid = person_of(f["id"])
        if pid not in persons:
            reasons.append(_("fact {fact}: no person {person} in the family or the proposal")
                           .format(fact=f["id"], person=pid))
            continue
        if f["id"] in known_facts:
            reasons.append(_("fact {fact} already exists: record a revision instead").format(fact=f["id"]))
            continue
        persons[pid].setdefault("facts", []).append(f)
        known_facts.add(f["id"])
        touched.add(pid)
    by_id = {f["id"]: (pid, f) for pid, p in persons.items() for f in p.get("facts", [])}
    for r in doc.get("refutations", []):   # FL-D10: refuted, never deleted
        if r["fact"] not in by_id:
            reasons.append(_("refutation of {fact}: no such fact in the family").format(fact=r["fact"]))
            continue
        pid, f = by_id[r["fact"]]
        r["before"] = f.get("status")
        if f.get("status") == "refuted":
            reasons.append(_("fact {fact} is already refuted").format(fact=r["fact"]))
            continue
        changed = dict(f, status="refuted", refuted_in={k: v for k, v in (
            ("pass", doc["pass"]), ("volet", volet), ("event", r.get("event"))) if v is not None})
        persons[pid]["facts"] = [changed if x["id"] == f["id"] else x for x in persons[pid]["facts"]]
        touched.add(pid)
    docs["persons"]["persons"] = list(persons.values())
    for name in ("places", "sources", "searches", "hypotheses", "analyses", "proofs"):
        docs[name][name] = _merge_by_id(docs[name][name], doc.get(name, []))
    docs["non-links"]["non_links"] += [x for x in doc.get("non_links", []) if x not in docs["non-links"]["non_links"]]
    docs["gaps"]["gaps"] = merge_gaps(docs["gaps"]["gaps"], doc.get("gaps", []))
    variants = docs["variants"]
    for v in doc.get("variants", []):
        table = variants.setdefault("surnames" if v["kind"] == "surname" else "given", {})
        forms = table.setdefault(v["name"], [])
        if not any(f["form"] == v["form"] for f in forms):
            forms.append({"form": v["form"], "source": v.get("source")})
    return docs, touched, reasons


def check(project, research, doc, config, now=None, docs=None):
    """(the family as it would be, touched persons, reasons, warnings). ``docs``: the family's indexes
    already loaded, which become the family as it would be."""
    now = now or _now()
    indexes = FamilyIndexes(project, research.family)
    docs = indexes.load_all() if docs is None else docs
    before = {s["id"]: s for s in docs["sources"]["sources"]}
    docs, touched, reasons = merged_state(indexes, doc, _volet(research), docs)
    sources = {s["id"]: s for s in docs["sources"]["sources"]}
    new_facts = doc.get("facts", []) + [f for p in doc.get("persons", []) for f in p.get("facts", [])]
    reasons += check_sources(new_facts, sources)
    reasons += check_views(doc.get("sources", []))
    reasons += check_images(project, research, doc.get("sources", []))
    reasons += check_transcriptions(project, research, before, sources, docs["persons"]["persons"])
    reasons += check_excerpts(project, research, new_facts, sources)
    reasons += check_negatives(doc.get("searches", []), config.get("witness.max_age_hours"), now)
    reasons += check_chronology(docs["persons"]["persons"], touched, sources)
    reasons += check_ancestry(docs["persons"]["persons"], touched)
    reasons += check_non_links(docs["persons"]["persons"], touched, docs["non-links"]["non_links"])
    reasons += check_analyses(doc.get("analyses", []), docs["persons"]["persons"])
    reasons += check_proofs(doc.get("proofs", []), docs["persons"]["persons"], docs["analyses"]["analyses"])
    reasons += check_gaps(doc.get("gaps", []), docs["places"]["places"])
    living = presumed_living(docs["persons"]["persons"], touched,
                             config.get("privacy.living_years"), now.date())
    warnings = [_("presumed living: {person}; their name and dates stay out of shared outputs")
                .format(person=p) for p in living]
    warnings += refuted_reach(project, research, doc.get("refutations", []), docs)
    return docs, touched, reasons, warnings


def changes(before, after):
    """version-1.0.0 T102: [{"index", "entry", "change"}], what applying a proposal adds to the family's indexes
    (``added``) or changes in them (``modified``): ``before`` the indexes as they are, ``after`` as ``check``
    merged them; the facts apart from their persons. The variants, forms of names, are left out."""
    from probandia.indexes import FILES

    def key(x):
        return x.get("id") or f"{x.get('a')} / {x.get('b')}"   # a non-link has no id: its two persons

    def compare(index, old, new, apart=()):
        was = {key(x): x for x in old}
        for x in new:
            k = key(x)
            if k not in was:
                out.append({"index": index, "entry": k, "change": "added"})
            elif {a: v for a, v in x.items() if a not in apart} != {a: v for a, v in was[k].items() if a not in apart}:
                out.append({"index": index, "entry": k, "change": "modified"})

    out = []
    for name, (_schema, field) in FILES.items():
        if field:
            compare(name, before[name][field], after[name][field], ("facts",) if name == "persons" else ())
    compare("facts", [f for p in before["persons"]["persons"] for f in p.get("facts", [])],
            [f for p in after["persons"]["persons"] for f in p.get("facts", [])])
    return out


def refuted_reach(project, research, refutations, docs):
    """T242: what each fact a proposal refutes held up, one line each: the answered questions of the family's
    researches that conclude on it (or on an analysis that retained it), the analyses that cite it, the proof
    arguments that conclude on it or rely on such an analysis. Each is to be looked at again; V-20 fails on
    the question until it is reopened or answered with another fact."""
    from probandia.proof import questions as Q

    if not refutations:
        return []
    analyses, proofs = docs["analyses"]["analyses"], docs["proofs"]["proofs"]

    def cites(a, fid):
        return fid in {i.get("fact") for i in a.get("items") or []} | {(a.get("resolution") or {}).get("fact")}

    retained = {a["id"]: (a.get("resolution") or {}).get("fact") for a in analyses}
    by_id = {a["id"]: a for a in analyses}
    researches = [r for r in all_researches(project) if r.family == research.family]
    out = []
    for fid in dict.fromkeys(r["fact"] for r in refutations):
        for r in researches:
            for q in Q.of(r.meta() or {}):
                named = q.get("conclusion") or []
                if q.get("status") == "answered" and (fid in named or any(retained.get(c) == fid for c in named)):
                    out.append(_("refuted fact {fact}: question {question} of {research} rests on it; reopen it, or "
                                 "answer it with another fact (V-20)").format(fact=fid, question=q["id"],
                                                                              research=r.id))
        out += [_("refuted fact {fact}: analysis {analysis} cites it; record it again without it, or resolve it "
                  "anew").format(fact=fid, analysis=a["id"]) for a in analyses if cites(a, fid)]
        out += [_("refuted fact {fact}: proof argument {proof} ({question}) rests on it; draft it again").format(
                    fact=fid, proof=pf["id"], question=pf.get("question"))
                for pf in proofs if fid in (pf.get("conclusion") or [])
                or any(cites(by_id[x], fid) for x in pf.get("analyses") or [] if x in by_id)]
    return out


def _result_path(path):
    return path[: -len(".yaml")] + ".result"


def _write_result(path, status, reasons=(), warnings=(), event_ids=(), stage=None):
    result = {"status": status, "ts": iso(_now()), "reasons": list(reasons), "warnings": list(warnings),
              "events": list(event_ids)}
    if stage:   # J10: "propose", a rejection by the dry run of propose, not by apply
        result["stage"] = stage
    yamlio.dump(_result_path(path), result)


def _volet(research):
    from probandia.lifecycle import current_volet

    # only the volets opened are decoded: a long log costs its reading, not its decoding (version-1.0.0 T102)
    return current_volet([json.loads(x) for x in events.read_lines(research.events_path) if '"volet.opened"' in x])


def _events_for(doc, docs, research, actor, start_errata):
    """The events of an accepted proposal; facts receive their event id, and the
    volet open (FL-D8)."""
    out = []
    p = doc["pass"]
    volet = _volet(research)
    for s in doc.get("sources", []):
        if s.get("image") or s.get("transcription"):
            out.append(events.make("evidence.recorded", {"source": s["id"], "image": s.get("image"),
                                   "transcription": s.get("transcription")}, actor, p, [s["id"]]))
    for s in doc.get("searches", []):
        out.append(events.make("search.logged", {"search": s["id"]}, actor, p, [s["id"]]))
        if s["result"] == "negative":
            out.append(events.make("negative.recorded", {"search": s["id"],
                                   "recheck_if": s.get("recheck_if"),
                                   "recheck_after": s.get("recheck_after")}, actor, p, [s["id"]]))
    new_persons = [x["id"] for x in doc.get("persons", [])]
    if new_persons:
        out.append(events.make("branch.added", {"persons": new_persons, "root": new_persons[0]},
                               actor, p, new_persons))
    facts = list(doc.get("facts", [])) + [f for x in doc.get("persons", []) for f in x.get("facts", [])]
    for f in facts:
        e = events.make("fact.asserted", {"fact": f["id"]}, actor, p, [f["id"]])
        f["research"], f["pass"], f["event"] = research.id, p, e["id"]
        if volet:
            f["volet"] = volet
        e["payload"]["fact"] = dict(f)
        out.append(e)
    for r in doc.get("refutations", []):   # r["before"]: the status merged_state found
        e = events.make("fact.revised", {"fact": r["fact"], "before": r.get("before"), "after": "refuted",
                                         "cause": r["cause"], "reason": r["reason"], "volet": volet},
                        actor, p, [r["fact"]])
        r["event"] = e["id"]
        out.append(e)
    for h in doc.get("hypotheses", []):
        out.append(events.make("hypothesis.opened", {"hypothesis": h}, actor, p, [h["id"]]))
    for a in doc.get("analyses", []):
        out.append(events.make("analysis.recorded", {"analysis": a["id"], "status": a["status"],
                                                     "resolution": a.get("resolution")}, actor, p, [a["id"]]))
    for pf in doc.get("proofs", []):
        out.append(events.make("proof.recorded", {"proof": pf["id"], "question": pf["question"],
                                                  "state": pf["review"]["state"]}, actor, p, [pf["id"]]))
    for n, err in enumerate(doc.get("errata", []), start=start_errata):
        err = dict(err, id=err.get("id") or f"E{n}", **{"pass": err.get("pass") or p})
        out.append(events.make("erratum.recorded", {"erratum": err["id"], "target": err["target"],
                               "wrong": err["wrong"], "correction": err["correction"],
                               "cause": err["cause"], "detection": err.get("detection")},
                               actor, p, [err["id"]]))
    for sec in doc.get("sections", []):
        section = dict(sec, id=ulid())
        out.append(events.make("section.added", {"section": section}, actor, p, [section["id"]]))
    return out


def _keep_pages(project, research, doc, docs):
    """TRUST1-T4: the text of each page a new fact quotes is kept where its rights allow (TRUST-D2), and its
    source records the page's digest."""
    from probandia import excerpt
    from probandia.archives.finder import load_catalogue

    facts = doc.get("facts", []) + [f for p in doc.get("persons", []) for f in p.get("facts", [])]
    if not any((f.get("excerpt") or {}).get("kind") == "page" for f in facts):
        return
    sources = {s["id"]: s for s in docs["sources"]["sources"]}
    for sid, digest in excerpt.freeze(project, research.family, research, facts, sources,
                                      load_catalogue(project)).items():
        sources[sid]["sha256"] = digest


def _fill_searches(doc, research):
    for s in doc.get("searches", []):
        s.setdefault("research", research.id)
        if s.get("pass") is None:
            s["pass"] = doc["pass"]


def _drop_logged_natives(project, research, doc):
    """T51: a native search the hook (or ``search --log-native``) logged in the pass is not logged a second
    time by the proposal that reports it: the budget would count it twice."""
    from probandia.providers.searchlog import logged_native

    if not any(s.get("kind") == "native" for s in doc.get("searches", [])):
        return
    logged = FamilyIndexes(project, research.family).items("searches")
    doc["searches"] = [s for s in doc["searches"] if logged_native(logged, s) is None]


def apply(project, ref, actor, config):
    """Applies a proposal as a whole, or rejects it. Returns (status, details)."""
    if actor.get("agent") not in APPLY_ROLES:
        raise UsageError(_("only the orchestrator or the session agent may apply a proposal"),
                         values={"REASON": "not-allowed"})
    research, path = find_proposal(project, ref)
    doc = yamlio.load(path)
    validate_document("proposal", doc, os.path.basename(path))
    if os.path.exists(_result_path(path)):
        previous = yamlio.load(_result_path(path)) or {}
        if previous.get("status") == "accepted":
            return "already", {"proposal": doc["id"], "research": research.id}
    _fill_searches(doc, research)
    _drop_logged_natives(project, research, doc)
    for s in doc.get("sources", []):
        if not s.get("citation") and (s.get("repository") or s.get("type")):
            s["citation"] = cite.ensure(s)["citation"]
    docs, touched, reasons, warnings = check(project, research, doc, config)
    if reasons:
        _write_result(path, "rejected", reasons, warnings)
        raise Rejected(_("proposal {id} rejected: {n} reason(s)").format(id=doc["id"], n=len(reasons)),
                       values={"PROPOSAL": doc["id"]}, lines=reasons)
    broken = events.check_chain(research.events_path)
    if broken:
        raise events.ChainError(_("events.jsonl is broken at line {n}: {what}").format(
            n=broken[0], what=broken[1]), values={"LINE": broken[0]})

    expiry = config.get("locks.expiry_minutes")
    indexes = FamilyIndexes(project, research.family)
    with locked(project, f"family:{research.family}", actor, expiry):
        with locked(project, f"research:{research.id}", actor, expiry):
            # The family may have changed while waiting for the lock: check again.
            docs, touched, reasons, warnings = check(project, research, doc, config)
            if reasons:
                _write_result(path, "rejected", reasons, warnings)
                raise Rejected(_("proposal {id} rejected: {n} reason(s)").format(
                    id=doc["id"], n=len(reasons)), values={"PROPOSAL": doc["id"]}, lines=reasons)
            keep_images(project, research, doc)
            errata_before = sum(1 for e in events.read(research.events_path)
                                if e["type"] == "erratum.recorded")
            new_events = _events_for(doc, docs, research, actor, errata_before + 1)
            # The facts now carry their event id: rebuild the family with them.
            docs, touched, _r = merged_state(indexes, doc, _volet(research))
            _keep_pages(project, research, doc, docs)
            backups = _backup(indexes)
            try:
                indexes.write(docs, actor, f"apply {doc['id']}")
                written = events.append(research.events_path, new_events)
            except BaseException:
                _restore(indexes, backups)
                raise
            drop_backups(indexes)
            _write_result(path, "accepted", [], warnings, [e["id"] for e in written])
    learned = _remember_queries(project, research, doc, actor)
    return "accepted", {"proposal": doc["id"], "research": research.id, "events": len(written),
                        "warnings": warnings, "touched": sorted(touched), "recipes": learned}


def drop(project, ref, actor, reason):
    """Sets a proposal aside without applying it: its ``.result`` says so, and why."""
    if actor.get("agent") not in APPLY_ROLES:
        raise UsageError(_("only the orchestrator or the session agent may drop a proposal"),
                         values={"REASON": "not-allowed"})
    if not (reason or "").strip():
        raise UsageError(_("say why the proposal is dropped"), values={"REASON": "no-reason"})
    research, path = find_proposal(project, ref)
    doc = yamlio.load(path) or {}
    if os.path.exists(_result_path(path)) and (yamlio.load(_result_path(path)) or {}).get("status") == "accepted":
        raise UsageError(_("proposal {id} was applied: correct it with an erratum").format(id=doc.get("id")),
                         values={"REASON": "applied"})
    _write_result(path, "dropped", [reason.strip()])
    return research, doc.get("id")


def reject_own(path, reasons):
    """The proposal of the agent who applies, which its dry run refuses: rejected at once, since its
    author proposes a corrected one under a new id (token-economy J8: left waiting, it stopped ``pass end``
    in each session of the bench of J7, 12 Oct. 2026, until dropped by hand). ``apply`` may still take it."""
    _write_result(path, "rejected", reasons, stage="propose")


def unsettled(research):
    """The proposals ``reject_own`` rejected that no proposal of the same author, applied since, replaced:
    left so, their findings would never be recorded, and ``pass end`` says so as for a pending one
    (token-economy J10: the safety net J8 took away when its author gives up instead of proposing again)."""
    folder = proposals_folder(research)
    if not os.path.isdir(folder):
        return []
    rejected, accepted = [], {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".result"):
            continue
        pid = name[: -len(".result")]
        result = yamlio.load(os.path.join(folder, name)) or {}
        stored = os.path.join(folder, f"{pid}.yaml")
        author = (yamlio.load(stored) or {}).get("author") if os.path.isfile(stored) else None
        who = (author.get("harness"), author.get("agent")) if isinstance(author, dict) else None
        if result.get("status") == "rejected" and result.get("stage") == "propose":
            rejected.append((pid, who, str(result.get("ts") or "")))
        elif result.get("status") == "accepted":
            accepted.setdefault(who, []).append(str(result.get("ts") or ""))
    return [pid for pid, who, ts in rejected if not any(t >= ts for t in accepted.get(who, []))]


def applied_in_pass(research):
    """Whether a proposal was applied since the pass opened: a fact, a negative or a hypothesis recorded."""
    started = [e for e in events.read(research.events_path) if e.get("type") == "pass.started"]
    folder = proposals_folder(research)
    if not started or not os.path.isdir(folder):
        return False
    since = str(started[-1].get("ts") or "")
    for name in os.listdir(folder):
        if name.endswith(".result"):
            result = yamlio.load(os.path.join(folder, name)) or {}
            if result.get("status") == "accepted" and str(result.get("ts") or "") >= since:
                return True
    return False


def unrecorded(project, research):
    """The transcriptions ``transcribe new`` made in the pass open (their source id, ``src-<ULID>``, says
    when) whose source no applied proposal brought into the family: what they prove was never proposed
    (token-economy J12: a pass closed so at the bench of I3, 12 Oct. 2026, two acts read, no fact)."""
    from probandia.indexes import FamilyIndexes
    from probandia.util.ids import is_ulid, ulid_time_ms

    started = [e for e in events.read(research.events_path) if e.get("type") == "pass.started"]
    if not started:
        return []
    opened = started[-1]
    since = ulid_time_ms(opened["id"]) if is_ulid(opened.get("id")) else parse_iso(opened["ts"]).timestamp() * 1000
    folder = os.path.join(project, "families", research.family, "evidence", "transcriptions")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    known = {s.get("id") for s in FamilyIndexes(project, research.family).items("sources")}
    out = []
    for name in names:
        sid = name[: -len(".md")] if name.endswith(".md") else ""
        if sid.startswith("src-") and is_ulid(sid[4:]) and sid not in known and ulid_time_ms(sid[4:]) >= since:
            out.append(sid)
    return out


def _spans(numbers):
    """``3-5, 9``: sorted numbers as ranges."""
    out = []
    for n in sorted(set(numbers)):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in out)


def registers_read(project, research, pass_no):
    """{(archive, register): views} of the pass's archive runs that showed views: a ``view`` or a sheet's
    ``from``-``to``, of a register given by its ``detail`` (a departmental archive) or its manifest ``url``."""
    import json

    out = {}
    for s in FamilyIndexes(project, research.family).items("searches"):
        if s.get("research") != research.id or s.get("pass") != pass_no or s.get("kind") != "archive" \
                or s.get("result") == "failed":
            continue
        try:
            args = json.loads(str(s.get("query") or "").partition(" ")[2])
            views = [int(args["view"])] if "view" in args else range(int(args["from"]), int(args["to"]) + 1)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        key = args.get("detail") or args.get("url")
        if key:
            out.setdefault((s.get("engine"), str(key)), set()).update(views)
    return out


def _cotes(research):
    """{(archive, detail): cote} from the registers the pass's archive runs listed (``work/details/``)."""
    import json

    folder, out = os.path.join(research.work, "details"), {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not (name.startswith("archive-") and name.endswith(".json")):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                rows = json.load(fh).get("rows") or []
        except (OSError, ValueError, AttributeError):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("detail") is not None and row.get("cote"):
                out[(name.split("-")[1], str(row["detail"]))] = row["cote"]
    return out


def _subject(project, research):
    """(subject, its note in the draft): the id of the person the question names in the family's index; else
    their name, when a first name comes before a surname of the family, for the agent to add to persons (the
    draft holds no ``persons:``, which the agent adds at its end)."""
    from probandia.planner import find_indexed_person, find_person

    question = (research.meta() or {}).get("question", "")
    known = find_indexed_person(question, FamilyIndexes(project, research.family).items("persons"))
    if known:
        return known["id"], f"# subject: {known['id']}"
    given, surname = find_person(question, yamlio.load(os.path.join(research.family_folder, "family.yaml")) or {})
    if not given:   # find_person falls back on the family's surname: no subject rather than a wrong one
        return "", ""
    return f"{given} {surname}", f"# subject: {given} {surname}, not in the family: add them to persons"


def draft(project, research, author):
    """``propose --draft`` (T76): the pass's proposal as far as the engine knows it, as text, ``facts:`` last,
    so that the agent adds its facts, new persons and sections at the end instead of writing it all: the header;
    a source for each transcription of the pass no proposal brought in (``unrecorded``), its repository and call
    number those of the register its image was saved from, else of the only register read; a search for each
    register whose views were read; the subject. Returns (text, subject, sources, searches)."""
    from probandia import transcription
    from probandia.archives.finder import load_catalogue
    from probandia.lifecycle import current_pass

    pass_no = max(1, current_pass(research))
    read, cotes, catalogue = registers_read(project, research, pass_no), _cotes(research), load_catalogue(project)
    searches = [{"kind": "archive", "engine": archive, "query": cotes.get((archive, key), key),
                 "filters": {"register": cotes.get((archive, key), key), "views": _spans(views)},
                 "result": "positive", "support": "image"} for (archive, key), views in sorted(read.items())]
    sources = []
    for sid in unrecorded(project, research):
        path = transcription.path_for(research.family_folder, sid)
        with open(path, encoding="utf-8") as fh:
            image = transcription.header(fh.read()).get("Image") or None
        source = {"id": sid, "image": image,
                  "transcription": os.path.relpath(path, research.family_folder).replace(os.sep, "/")}
        stem = os.path.basename(image or "")   # a view a connector saved: <archive>-<detail>-<view>.jpg
        found = [k for k in read if stem.startswith(f"{k[0]}-{k[1]}-")] or (list(read) if len(read) == 1 else [])
        if found:
            archive, key = found[0]
            source.update(repository=(catalogue.get(archive) or {}).get("name") or archive,
                          reference=cotes.get((archive, key), key))
        sources.append(source)
    subject, note = _subject(project, research)
    doc = {"schema": 1, "research": research.id, "pass": pass_no, "author": dict(author)}
    for part, items in (("sources", sources), ("searches", searches)):
        if items:
            doc[part] = items
    notes = ([note] if note else []) + (
        ["# a register read without the act: result negative, with its witness (negatives.md)"] if searches else [])
    text = yamlio.dumps(doc) + "".join(n + "\n" for n in notes) + \
        "facts:\n  # one per fact (propose --example facts); its excerpt {source, lines} as the reader returned them\n"
    return text, subject, len(sources), len(searches)


def pending(research):
    """The stored proposals of a research that were neither applied, rejected nor
    dropped. Drafts in the same folder (a file not named after its id) do not count."""
    folder = proposals_folder(research)
    if not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not name.endswith(".yaml") or os.path.exists(_result_path(path)):
            continue
        doc = yamlio.load(path)
        if isinstance(doc, dict) and doc.get("id") == name[: -len(".yaml")]:
            out.append(doc["id"])
    return out


def _remember_queries(project, research, doc, actor):
    """PRD S-8: when a proposal brings facts proven by a record or an index, the
    positive queries of its pass are stored as recipes, per source and per type of
    question. A failure here never undoes the apply."""
    try:
        if not any(f.get("status") in ("record", "index") for f in doc.get("facts", [])):
            return []
        from probandia.indexes import FamilyIndexes
        from probandia.library import Library
        from probandia.planner import detect_type

        plan_path = os.path.join(research.work, f"plan-{doc['pass']}.yaml")
        plan = yamlio.load(plan_path) if os.path.isfile(plan_path) else {}
        qtype = (plan or {}).get("question_type") or detect_type((research.meta() or {}).get("question", ""))
        axes = (plan or {}).get("axes") or {}
        searches = [x for x in FamilyIndexes(project, research.family).items("searches")
                    if x.get("research") == research.id and x.get("pass") == doc["pass"]]
        searches += doc.get("searches", [])
        lib, out, seen = Library(project), [], set()
        for x in searches:
            if x.get("result") not in ("positive", "partial") or x.get("kind") == "native" or not x.get("engine"):
                continue
            if x["engine"].startswith("mcp:"):  # the engine cannot replay another server's search
                continue
            if (x["engine"], x["query"]) in seen:
                continue
            seen.add((x["engine"], x["query"]))
            entry = lib.remember_query(x["query"], qtype, x["engine"], x.get("results") or 1, axes,
                                       {"harness": actor.get("harness"), "agent": actor.get("agent")})
            out.append(entry["id"])
        return out
    except Exception:  # noqa: BLE001 — a recipe is a help, never a condition
        return []


def _backup(indexes):
    out = {}
    for name in ("persons", "places", "sources", "searches", "hypotheses", "variants", "non-links",
                 "gaps", "analyses", "proofs"):
        path = indexes.path(name)
        if os.path.exists(path):
            tmp = path + ".apply-bak"
            shutil.copy2(path, tmp)
            out[path] = tmp
        else:
            out[path] = None
    return out


def _restore(indexes, backups):
    for path, tmp in backups.items():
        if tmp:
            from probandia.util.fs import _replace

            _replace(tmp, path)   # retried while Windows lets a reader hold the index
        elif os.path.exists(path):
            os.unlink(path)


def drop_backups(indexes):
    for name in ("persons", "places", "sources", "searches", "hypotheses", "variants", "non-links",
                 "gaps", "analyses", "proofs"):
        tmp = indexes.path(name) + ".apply-bak"
        if os.path.exists(tmp):
            os.unlink(tmp)
