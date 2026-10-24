"""The verification rules V-1 to V-20 of a research.

Each rule returns ``(status, message)``: ``PASS``, ``WARN`` or ``FAIL``.
``--light`` runs V-2, V-3, V-4 or V-5 (by mode), V-6 and V-12.
"""
import datetime
import json
import os
import re

from probandia import events
from probandia.i18n import N_
from probandia.indexes import FamilyIndexes
from probandia.report import labels as L
from probandia.util.fs import parse_iso

APPLY_EVENTS = ("fact.asserted", "fact.revised", "fact.retracted", "negative.recorded",
                "hypothesis.opened", "hypothesis.updated", "hypothesis.closed", "erratum.recorded",
                "section.added", "section.replaced", "section.moved", "section.merged", "branch.added",
                "analysis.recorded", "proof.recorded")
REWRITES = ("section.replaced", "section.moved", "section.merged")
# written outside the steps of a pass (GPS1, GPS3): a question settled, a source type said not to apply,
# the research closed; a fact a person checked (T248)
OUTSIDE_PASS = ("question.added", "question.updated", "matrix.justified", "research.closed", "volet.opened",
                "fact.checked", "workshop.pushed")
RULES = tuple(f"V-{n}" for n in range(1, 21))

# What each rule checks (PRD § 8), and what corrects a failure: the readable
# output of verify shows them; the contract keeps its one line per rule.
TITLES = {
    "V-1": N_("the steps of each pass happened in order"),
    "V-2": N_("every fact has a status, and every record or index fact a citation"),
    "V-3": N_("every negative has its window, variants, witness and source state"),
    "V-4": N_("journal mode: earlier text unchanged, every correction an erratum"),
    "V-5": N_("living mode: every change is in the revision history"),
    "V-6": N_("numbering continuous and unique, every anchor resolves"),
    "V-7": N_("every fact of the report is in the index, and in a section of its pass"),
    "V-8": N_("trees regenerated after a change of branch"),
    "V-9": N_("presumed-living persons masked in the shared outputs"),
    "V-10": N_("no provider used beyond its free tier"),
    "V-11": N_("every learned script used had a passing witness"),
    "V-12": N_("every search of the pass is in the search log"),
    "V-13": N_("the HTML report was rendered with a template that still exists, unchanged"),
    "V-14": N_("the dates of the research's facts are consistent (P-9)"),
    "V-15": N_("every conflict between pieces of evidence is analysed, and resolved before its question is answered"),
    "V-16": N_("every answered question that needs a proof argument has one, reviewed and accepted"),
    "V-17": N_("every typed source a conclusion cites has the fields its citation model requires"),
    "V-18": N_("every settled question has searched each source type it expects, or says why not"),
    "V-19": N_("every excerpt a fact cites is found, word for word, in its transcription or the page kept"),
    "V-20": N_("no answered question rests on a refuted fact"),
}
FIXES = {
    "V-1": N_("run the steps in order: plan before any apply, then close the pass with pass end"),
    "V-2": N_("give each fact its status, and cite a source of sources.yaml (cite); a fact an online tree "
              "gives is a hypothesis until a record confirms it"),
    "V-3": N_("complete the negative (variants, window, source state) and run its witness search again"),
    "V-4": N_("record the change as an erratum with its cause, instead of rewriting a section"),
    "V-5": N_("add each rewrite to the revisions, with its reason"),
    "V-6": N_("render the report again (render); an anchor that resolves to nothing points to a removed section"),
    "V-7": N_("add the missing facts to a section of their pass, or remove the reference"),
    "V-8": N_("regenerate the trees: probandia tree"),
    "V-9": N_("export again: presumed-living persons are masked (privacy.living_years)"),
    "V-10": N_("the quota is spent and nothing was paid; look at probandia -u before the next search"),
    "V-11": N_("test the script against its witness (library test), then run it again"),
    "V-12": N_("log each native search of the pass (search --log-native), and count them in pass end"),
    "V-13": N_("render the report again with its template (render, or render --all), or choose another one "
               "(template use)"),
    "V-14": N_("check the dates against the records, then revise the fact (apply), or explain the clash in "
               "the fact's note"),
    "V-15": N_("correlate open, give each piece of evidence its three axes, then correlate resolve and apply"),
    "V-16": N_("proof draft, submit, have the contradictor review it (proof review --by contradictor), answer, "
               "accept"),
    "V-17": N_("read the record again and propose the source with the missing fields (probandia cite --form "
               "--type <type> lists them), then apply"),
    "V-18": N_("probandia matrix shows what is left: search the types to do, give each gap its justification, "
               "or say why a type does not apply (matrix justify); for catalogue_<country>, name the source "
               "types searched there"),
    "V-19": N_("read the source again and quote it anew (transcribe quote, read --quote), then revise the fact; "
               "a record fact that answers a question cites its excerpt"),
    "V-20": N_("reopen the question (question reopen <Q>), or answer it with another fact (question answer <Q> "
               "--conclusion <fact>)"),
}
FACT_REF = re.compile(r"\[\[f:([^\]\s]+)\]\]")


class Context:
    def __init__(self, project, research, config=None, today=None, report=None, pass_no=None):
        self.project = project
        self.research = research
        self.config = config
        self.pass_no = pass_no   # set: V-1, V-2, V-3, V-4, V-5 and V-12 look at that pass only (B7)
        self.today = today or datetime.date.today()
        self.meta = research.meta() or {}
        self.log = events.read(research.events_path)
        self.idx = FamilyIndexes(project, research.family)
        self._report = report

    def get(self, key, default=None):
        value = self.config.get(key) if self.config is not None else None
        return default if value is None else value

    @property
    def mode(self):
        return self.meta.get("mode") or "journal"

    def items(self, name):
        return self.idx.items(name)

    def in_scope(self, item):
        """An index record or an event of the pass in scope; every one when none is."""
        return self.pass_no is None or item.get("pass") == self.pass_no

    def report(self):
        """The report model, built in memory as ``render`` would build it."""
        if self._report is None:
            from probandia.i18n import Translator
            from probandia.proof import matrix
            from probandia.report.render import build_report

            lang = self.meta.get("language") or "en"
            t = Translator(lang, [os.path.join(self.project, "locales")])
            docs = self.idx.load_all()
            self._report = build_report(self.meta, self.log, docs, lang, t,
                                        numbering_style=self.meta.get("numbering") or "arabic",
                                        living_years=self.get("privacy.living_years", 100),
                                        timelines=self.get("report.timeline", "main"),
                                        matrix=matrix.build(self.research, self.meta))
        return self._report

    def by_pass(self):
        out = {}
        for i, e in enumerate(self.log):
            out.setdefault(e["pass"], []).append((i, e))
        return out


def _ids(items, n=5):
    items = list(items)
    more = f" (+{len(items) - n})" if len(items) > n else ""
    return ", ".join(str(x) for x in items[:n]) + more


def v1(c):
    """Each pass: pass.started, plan.made, its search.logged events, pass.ended; no
    apply event before plan.made."""
    bad = []
    for p, evs in sorted(c.by_pass().items()):
        if p == 0 or c.pass_no not in (None, p):
            continue
        types = [e["type"] for _i, e in evs if e["type"] not in OUTSIDE_PASS]
        if not types:
            continue
        if types[0] != "pass.started":
            bad.append(f"pass {p}: does not start with pass.started")
            continue
        if "plan.made" not in types:
            bad.append(f"pass {p}: no plan.made")
            continue
        plan = types.index("plan.made")
        early = [t for t in types[:plan] if t in APPLY_EVENTS or t == "search.logged"]
        if early:
            bad.append(f"pass {p}: {early[0]} before plan.made")
        if "pass.ended" in types and types.index("pass.ended") != len(types) - 1:
            bad.append(f"pass {p}: events after pass.ended")
    if bad:
        return "FAIL", "; ".join(bad[:4])
    return "PASS", ""


def v2(c):
    """Every fact of the research has a status; record and index facts cite a known source, and not an online
    tree (P-2, T238)."""
    sources = {s["id"]: s for s in c.items("sources")}
    bad = []
    for p in c.items("persons"):
        for f in p.get("facts", []):
            if f.get("research") != c.research.id or not c.in_scope(f):
                continue
            if not f.get("status"):
                bad.append(f"{f['id']} (no status)")
            elif f["status"] in ("record", "index") and f.get("source") not in sources:
                bad.append(f"{f['id']} (no citation)")
            elif f["status"] in ("record", "index") and sources[f["source"]].get("type") == "online-tree":
                bad.append(f"{f['id']} ({f['status']} on an online tree)")
    if bad:
        return "FAIL", f"{len(bad)} facts without a proper citation: {_ids(bad)}"
    return "PASS", ""


def v3(c):
    """Every negative has variants, a window, a source state, no failure, and a
    witness passed within witness.max_age_hours of the search."""
    hours = c.get("witness.max_age_hours", 24)
    bad = []
    for s in c.items("searches"):
        if s.get("research") != c.research.id or s.get("result") != "negative" or s.get("family") == "opaque" \
                or not c.in_scope(s):
            continue
        w = s.get("witness") or {}
        missing = [k for k in ("variants", "window", "source_state") if not s.get(k)]
        if s.get("failure"):
            missing.append("failure")
        if not w.get("passed"):
            missing.append("witness")
        elif s.get("ts") and w.get("ts") and \
                abs((parse_iso(s["ts"]) - parse_iso(w["ts"])).total_seconds()) > hours * 3600:
            missing.append("witness too old")
        if missing:
            bad.append(f"{s['id']} ({', '.join(missing)})")
    if bad:
        return "FAIL", f"{len(bad)} negatives without a witness or their proof: {_ids(bad)}"
    return "PASS", ""


def v4(c):
    """Journal mode: no rewrite events; an intact chain; every erratum has a known cause."""
    if c.mode != "journal":
        return "PASS", "living mode"
    bad = []
    broken = events.check_chain(c.research.events_path)
    if broken:
        bad.append(f"chain broken at line {broken[0]}")
    rewrites = [e["id"] for e in c.log if e["type"] in REWRITES and c.in_scope(e)]
    if rewrites:
        bad.append(f"{len(rewrites)} rewrite events in journal mode: {_ids(rewrites)}")
    causes = [e["id"] for e in c.log if e["type"] in ("erratum.recorded", "fact.revised") and c.in_scope(e)
              and (e.get("payload") or {}).get("cause") not in L.CAUSES]
    if causes:
        bad.append(f"errata without a known cause: {_ids(causes)}")
    return ("FAIL", "; ".join(bad)) if bad else ("PASS", "")


def v5(c):
    """Living mode: every rewrite event gives its reason (its revision entry)."""
    if c.mode != "living":
        return "PASS", "journal mode"
    bad = [e["id"] for e in c.log if e["type"] in REWRITES and c.in_scope(e)
           and not (e.get("payload") or {}).get("reason")]
    broken = events.check_chain(c.research.events_path)
    if broken:
        return "FAIL", f"chain broken at line {broken[0]}"
    if bad:
        return "FAIL", f"{len(bad)} rewrites without a reason: {_ids(bad)}"
    return "PASS", ""


def v6(c):
    """Numbers unique and continuous; every [[s:…]] resolves, aliases included."""
    report = c.report()
    paths = [n.path for n in report.model.walk()]
    dupes = sorted({p for p in paths if paths.count(p) > 1})
    sections = [r for r in report.unresolved if r.startswith("[[s:") or r.startswith("[[p:")]
    bad = []
    if dupes:
        bad.append(f"numbers used twice: {_ids(dupes)}")
    if sections:
        bad.append(f"{len(sections)} references that resolve to nothing: {_ids(sorted(set(sections)))}")
    return ("FAIL", "; ".join(bad)) if bad else ("PASS", "")


def v7(c):
    """Every [[f:…]] exists; every fact asserted in a pass appears in a section of that pass."""
    report = c.report()
    missing = sorted({r for r in report.unresolved if r.startswith("[[f:")})
    cited = {}
    for e in c.log:
        if e["type"] in ("section.added", "section.replaced"):
            payload = e.get("payload") or {}
            s = payload.get("section") if isinstance(payload.get("section"), dict) else {}
            refs = set(s.get("facts") or []) | set(FACT_REF.findall(s.get("body_md") or payload.get("body_md") or ""))
            cited.setdefault(e["pass"], set()).update(refs)
    absent = []
    for e in c.log:
        if e["type"] == "fact.asserted":
            fid = ((e.get("payload") or {}).get("fact") or {}).get("id")
            if fid and fid not in cited.get(e["pass"], set()):
                absent.append(f"{fid} (pass {e['pass']})")
    bad = []
    if missing:
        bad.append(f"{len(missing)} fact references not in the index: {_ids(missing)}")
    if absent:
        bad.append(f"{len(absent)} facts in no section of their pass: {_ids(absent)}")
    return ("FAIL", "; ".join(bad)) if bad else ("PASS", "")


def v8(c):
    """A pass with branch.added has its trees in trees/, newer than the event."""
    folder = os.path.join(c.research.folder, "trees")
    newest = 0.0
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            newest = max(newest, os.path.getmtime(os.path.join(folder, name)))
    late = [e["pass"] for e in c.log if e["type"] == "branch.added"
            and parse_iso(e["ts"]).timestamp() > newest]
    if late:
        return "FAIL", f"trees missing or older than branch.added in passes {_ids(sorted(set(late)))}"
    return "PASS", ""


def _shared_texts(c):
    """(file name, text) of each shared output of the research: its report and trees, and the GEDCOM exports of
    its family (T241), a GEDZIP read inside."""
    import zipfile

    out = []
    for sub in ("report", "trees"):
        folder = os.path.join(c.research.folder, sub)
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.endswith((".md", ".html", ".svg", ".ged", ".json")):
                    with open(os.path.join(folder, f), encoding="utf-8", errors="replace") as fh:
                        out.append((f, fh.read()))
    folder = os.path.join(c.project, "exports")
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            path = os.path.join(folder, f)
            if not f.startswith(f"{c.research.family}-"):
                continue
            if f.endswith(".ged"):
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    out.append((f, fh.read()))
            elif f.endswith(".gdz"):
                try:
                    with zipfile.ZipFile(path) as z:
                        out.append((f, z.read("gedcom.ged").decode("utf-8-sig", errors="replace")))
                except (zipfile.BadZipFile, KeyError, OSError):
                    continue
    return out


def v9(c):
    """The shared outputs hold no name or date of a presumed-living person: the report, the trees and the
    GEDCOM exports of the family (T241)."""
    from probandia.gedcom import date_value
    from probandia.lang.places import key
    from probandia.report.living import full_names, living_set

    persons = c.items("persons")
    living = living_set(persons, c.get("privacy.living_years", 100), c.today)
    needles = []
    for p in persons:
        if p["id"] not in living:
            continue
        needles += [("name", key(n)) for n in full_names(p)]
        for f in p.get("facts", []):
            value = (f.get("date") or {}).get("value")
            if value and len(value) == 10:
                needles += [("date", value), ("date", date_value({"value": value}))]
    leaks = []
    for name, text in _shared_texts(c):
        folded = f" {key(text)} "
        for kind, needle in needles:
            if (kind == "name" and f" {needle} " in folded) or (kind == "date" and needle in text):
                leaks.append(f"{name} ({kind})")
    if leaks:
        return "FAIL", f"presumed-living persons shown in: {_ids(sorted(set(leaks)))}"
    return "PASS", ""


def _ledger_entries(project):
    path = os.path.join(project, ".probandia", "ledger.jsonl")
    out = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def v10(c):
    """In the ledger, no provider used more than its free amount in the period."""
    from probandia.ledger import Ledger
    from probandia.providers import catalogue

    cat = catalogue.load()
    ledger = Ledger(c.project, cat)
    over = []
    for provider in sorted({e["provider"] for e in _ledger_entries(c.project) if e.get("provider") in cat}):
        amount = (cat[provider].get("free") or {}).get("amount")
        if amount is None:
            continue
        used = ledger.local_used(provider)
        if used > amount:
            over.append(f"{provider} {used:g}/{amount:g}")
    if over:
        return "FAIL", f"beyond the free amount: {_ids(over)}"
    return "PASS", ""


def v11(c):
    """Every learned script used was tested or trusted, with a witness passed
    within witness.max_age_hours before use."""
    from probandia.util import yamlio

    uses = [e for e in c.log if e["type"] == "library.used"]
    if not uses:
        return "PASS", ""
    path = os.path.join(c.project, "library", "manifest.yaml")
    scripts = {s["id"]: s for s in ((yamlio.load(path) or {}).get("scripts") or [])} if os.path.isfile(path) else {}
    hours = c.get("witness.max_age_hours", 24)
    bad = []
    for e in uses:
        sid = (e.get("payload") or {}).get("script")
        s = scripts.get(sid)
        if s is None or s.get("status") not in ("tested", "trusted"):
            bad.append(f"{sid} ({(s or {}).get('status', 'unknown')})")
            continue
        last = (s.get("runs") or {}).get("last_ok")
        used = parse_iso(e["ts"])
        if not last or not (0 <= (used - parse_iso(last)).total_seconds() <= hours * 3600):
            bad.append(f"{sid} (no recent witness)")
    if bad:
        return "FAIL", f"learned scripts used without proof: {_ids(bad)}"
    return "PASS", ""


def _pass_owner(research):
    """T262: the research that ran each pass, a fork's inherited passes being its origin's (followed up a chain
    of forks): a function of the pass number."""
    from probandia.research import Research

    chain, meta, seen = [], research.meta() or {}, {research.id}
    while (meta.get("forked_from") or {}).get("research") not in (None, *seen):
        origin = meta["forked_from"]
        chain.append((origin.get("pass") or 0, origin["research"]))
        seen.add(origin["research"])
        try:
            meta = Research(research.project, research.family, origin["research"]).meta() or {}
        except OSError:   # an origin in another family (fork --new-family): its own folder is not here
            break

    def owner(n):
        rid = research.id
        for upto, origin in chain:   # nearest first, each inheriting fewer passes
            if n is not None and n <= upto:
                rid = origin
        return rid
    return owner


def v12(c):
    """Native searches counted in pass.ended match the logged ones; every provider
    call of the ledger has its search.logged."""
    owner = _pass_owner(c.research)
    searches = [s for s in c.items("searches") if s.get("research") == owner(s.get("pass"))]
    logged = {(e.get("payload") or {}).get("search") for e in c.log if e["type"] == "search.logged"}
    bad = []
    for e in c.log:
        if e["type"] != "pass.ended" or not c.in_scope(e):
            continue
        counted = (e.get("payload") or {}).get("native_searches")
        found = sum(1 for s in searches if s.get("pass") == e["pass"] and s.get("kind") == "native")
        if counted is not None and counted != found:
            bad.append(f"pass {e['pass']}: {counted} native searches counted, {found} logged")
    calls = {}
    for entry in _ledger_entries(c.project):
        if entry.get("research") == owner(entry.get("pass")) and entry.get("operation") == "search" \
                and entry.get("source") == "response" and c.in_scope(entry):
            k = (entry.get("pass"), entry["provider"])
            calls[k] = calls.get(k, 0) + 1
    for (p, provider), n in sorted(calls.items(), key=lambda x: (x[0][0] or 0, x[0][1])):
        have = sum(1 for s in searches if s.get("pass") == p and s.get("engine") == provider
                   and s.get("kind") == "provider" and s["id"] in logged)
        if have < n:
            bad.append(f"pass {p}: {n - have} {provider} calls without search.logged")
    if bad:
        return "FAIL", "; ".join(bad[:4])
    return "PASS", ""


def v13(c):
    """The template recorded in report.json (optimize 4.6) still exists, with the same fingerprint."""
    import json

    from probandia.report import template as T

    path = os.path.join(c.research.folder, "report", "report.json")
    try:
        with open(path, encoding="utf-8") as fh:
            used = json.load(fh).get("template")
    except (OSError, ValueError):
        return "PASS", ""
    if not used:
        return "PASS", ""
    tpl = T.find(used["id"], c.project, c.config, None)
    if tpl is None:
        return "FAIL", f"the template {used['id']} of the report no longer exists"
    if tpl.sha256 != used.get("sha256"):
        return "FAIL", f"the template {used['id']} changed since the report was rendered"
    return "PASS", ""


def v14(c):
    """P-9 on the persons whose facts the research established, or that answer its questions (GPS7-T2).
    A finding none of whose facts has a note is a warning; with proof.standard strict, one that touches
    a question's conclusion fails."""
    from probandia import chronology
    from probandia.proof import questions as Q

    persons = c.items("persons")
    facts = {f["id"]: f for p in persons for f in p.get("facts") or []}
    conclusions = {x for q in Q.of(c.meta) for x in q.get("conclusion") or []}
    mine = {fid for fid, f in facts.items() if f.get("research") == c.research.id} | conclusions
    touched = {p["id"] for p in persons if any(f["id"] in mine for f in p.get("facts") or [])}
    sources = {s["id"]: s for s in c.items("sources")}   # T244: each fact against the date of its act
    found = [f for f in chronology.all_findings(persons, touched, c.today, sources=sources)
             if any(x in mine for x in f["facts"]) and not any((facts.get(x) or {}).get("note") for x in f["facts"])]
    if not found:
        return "PASS", ""
    message = "; ".join(f["message"] for f in found[:4])
    if c.get("proof.standard", "off") == "strict" and any(x in conclusions for f in found for x in f["facts"]):
        return "FAIL", message
    return "WARN", message


def v15(c):
    """GPS4-T5: the conflicts among the facts of the research's persons each have an analysis; an analysis
    serving an answered question is resolved; with proof.standard on, every piece of evidence has its axes.
    A warning; with proof.standard strict, a failure."""
    from probandia.proof import conflicts
    from probandia.proof.conflicts import missing_axes
    from probandia.proof import questions as Q

    persons = c.items("persons")
    analyses = c.items("analyses")
    qs = Q.of(c.meta)
    conclusions = {x for q in qs for x in q.get("conclusion") or []}
    mine = {p["id"] for p in persons
            if any(f.get("research") == c.research.id or f["id"] in conclusions for f in p.get("facts") or [])}
    bad = [f"{pid} {kind}: {len(cs)} conflict(s) without an analysis"
           for (pid, kind), cs in sorted(conflicts.unanalysed(persons, c.items("places"), analyses, mine).items())]
    answered = {q["id"] for q in qs if q.get("status") == "answered"}
    bad += [f"{a['id']}: {a['status']}, but question {a['question']} is answered" for a in analyses
            if a["status"] in ("open", "divergent") and a.get("question") in answered]   # FL-D9
    standard = c.get("proof.standard", "off")
    if standard != "off":
        bad += [f"{a['id']}: {missing_axes(a)} piece(s) of evidence without their three axes" for a in analyses
                if a["person"] in mine and missing_axes(a)]
    if not bad:
        return "PASS", ""
    return ("FAIL" if standard == "strict" else "WARN"), "; ".join(bad[:4])


def v16(c):
    """GPS5-T6: an answered question that needs a proof argument (identity, indirect evidence, conflict) has an
    accepted one. A review by the same session only is not independent: a warning, a failure in strict mode,
    as a missing argument is."""
    from probandia.proof import arguments as A
    from probandia.proof import questions as Q

    persons, analyses, proofs = c.items("persons"), c.items("analyses"), c.items("proofs")
    bad = []
    for q in Q.of(c.meta):
        if q.get("status") != "answered":
            continue
        why = A.required(q, persons, analyses)
        if not why:
            continue
        p = A.accepted(proofs, c.research.id, q["id"])
        if p is None:
            bad.append(f"{q['id']} needs a proof argument ({', '.join(why)}): none accepted")
        elif not any(r["reviewer"] == "contradictor" for r in p["review"]["rounds"]):
            bad.append(f"{q['id']}: {p['id']} was reviewed by the same session only, not independently")
    if not bad:
        return "PASS", ""
    return ("FAIL" if c.get("proof.standard", "off") == "strict" else "WARN"), "; ".join(bad[:4])


def v17(c):
    """GPS6-T7: a typed source cited by a fact of the research or by a conclusion has the fields its model
    requires (GPS-D10): a warning, a failure with proof.standard strict. A recommended field missing is a
    warning only, and only with proof.standard on. V-2 keeps its role: a citation exists."""
    from probandia import cite
    from probandia.proof import questions as Q

    persons, sources = c.items("persons"), {s["id"]: s for s in c.items("sources")}
    conclusions = {x for q in Q.of(c.meta) for x in q.get("conclusion") or []}
    cited = sorted({f["source"] for p in persons for f in p.get("facts") or []
                    if f.get("source") and (f.get("research") == c.research.id or f["id"] in conclusions)})
    required, recommended = [], []
    for sid in cited:
        src = sources.get(sid) or {}
        if not src.get("type"):
            continue
        if cite.missing(src):
            required.append(f"{sid} ({src['type']}): missing {', '.join(cite.missing(src))}")
        if cite.lacking(src):
            recommended.append(f"{sid} ({src['type']}): no {', '.join(cite.lacking(src))}")
    standard = c.get("proof.standard", "off")
    if required:
        return ("FAIL" if standard == "strict" else "WARN"), "; ".join((required + recommended)[:4])
    if recommended and standard != "off":
        return "WARN", "; ".join(recommended[:4])
    return "PASS", ""


def v18(c):
    """GPS3-T6: a question answered or unresolved leaves no hole in its matrix: no source type to do, no gap
    without its justification, no type said not to apply without the reason, no window or place unknown.
    A general question may stay without window or place: a broad question, such as the research's own, has
    no single span to search; but it is answered with a conclusion only once a specific question of the
    research is answered. A warning; with proof.standard strict, a failure."""
    from probandia.proof import matrix
    from probandia.proof import questions as Q

    def left(q):
        found = matrix.holes(q)
        return [h for h in found if not h.startswith("unknown:")] if q["type"] == "general" else found

    doc = matrix.build(c.research, meta=c.meta)
    bad = [f"{q['id']} ({q['status']}): {', '.join(left(q))}" for q in doc["questions"]
           if q["status"] != "open" and left(q)]
    # a general question does not carry a conclusion alone: specific questions, searched in full, do
    questions = Q.of(c.meta)
    if not any(q.get("type") != "general" and q.get("status") == "answered" for q in questions):
        bad += [f"{q['id']} (general): answered with a conclusion, but no specific question of the research is"
                for q in questions
                if q.get("type") == "general" and q.get("status") == "answered" and q.get("conclusion")]
    if not bad:
        return "PASS", ""
    return ("FAIL" if c.get("proof.standard", "off") == "strict" else "WARN"), "; ".join(bad[:4])


def v19(c):
    """TRUST2-T1: an excerpt cited by a fact of the research, or by a conclusion, is found word for word in
    its transcription, or in the page kept (evidence/pages, work/pages, the read cache): a failure when it is
    not. A page this computer does not keep cannot be checked here: a warning. A record fact that answers a
    question cites its excerpt (TRUST-D3): a warning, a failure with proof.standard strict."""
    from probandia import excerpt
    from probandia.proof import questions as Q

    sources = {s["id"]: s for s in c.items("sources")}
    conclusions = {x for q in Q.of(c.meta) if q.get("status") == "answered" for x in q.get("conclusion") or []}
    broken, unseen, lacking = [], [], []
    for p in c.items("persons"):
        for f in p.get("facts") or []:
            if f.get("research") != c.research.id and f["id"] not in conclusions:
                continue
            if f.get("excerpt"):
                state, why = excerpt.verdict(c.project, c.research.family, f, sources, c.research)
                if state == "broken":
                    broken.append(f"{f['id']}: {'; '.join(why)}")
                elif state == "unseen":
                    unseen.append(f"{f['id']}: the page is not kept on this computer")
            elif f["id"] in conclusions and f.get("status") == "record":
                lacking.append(f"{f['id']}: no excerpt")
    standard = c.get("proof.standard", "off")
    if broken or (lacking and standard == "strict"):
        return "FAIL", "; ".join((broken + lacking)[:4])
    found = unseen + (lacking if standard == "warn" else [])
    return ("WARN", "; ".join(found[:4])) if found else ("PASS", "")


def v20(c):
    """T242: an answered question whose conclusion rests on a refuted fact (an analysis named there stands for
    the fact it retained) fails, whatever proof.standard says: the question is reopened, or answered with
    another fact."""
    from probandia.proof import questions as Q
    from probandia.proof.standard import question_facts

    facts = {f["id"]: dict(f, _person=p["id"]) for p in c.items("persons") for f in p.get("facts") or []}
    analyses = c.items("analyses")
    bad = []
    for q in Q.of(c.meta):
        if q.get("status") != "answered":
            continue
        refuted = [fid for fid in question_facts(q, facts, analyses, c.research.id)
                   if facts[fid].get("status") == "refuted"]
        if refuted:
            bad.append(f"{q['id']} is answered on refuted facts: {_ids(refuted)}")
    return ("FAIL", "; ".join(bad[:4])) if bad else ("PASS", "")


CHECKS = {"V-1": v1, "V-2": v2, "V-3": v3, "V-4": v4, "V-5": v5, "V-6": v6, "V-7": v7, "V-8": v8,
          "V-9": v9, "V-10": v10, "V-11": v11, "V-12": v12, "V-13": v13,
          "V-14": v14, "V-15": v15, "V-16": v16, "V-17": v17, "V-18": v18, "V-19": v19, "V-20": v20}


def light_rules(mode):
    return ["V-2", "V-3", "V-4" if mode == "journal" else "V-5", "V-6", "V-12"]


def run(project, research, config=None, rules=None, light=False, today=None, pass_no=None):
    """[(rule, status, message)] in rule order. ``pass_no``: what that pass brought only,
    where a rule can tell; a broken chain and the report's numbers stay the research's."""
    c = Context(project, research, config, today, pass_no=pass_no)
    chosen = rules or (light_rules(c.mode) if light else list(RULES))
    out = []
    for rule in RULES:
        if rule in chosen:
            status, message = CHECKS[rule](c)
            out.append((rule, status, message))
    return out
