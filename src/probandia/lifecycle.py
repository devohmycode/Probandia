"""The life of a research: its family, its passes, an interrupted pass.

A pass opens with ``pass.started`` under the research lock, held by the session
for the whole pass (``new``, ``resume``), and closes with ``pass.ended``; then
``research.yaml`` counts it in ``passes`` and the lock is released. The steps in
between (plan, searches, evidence, proposals, apply, render) are commands of their
own, run by the ``research`` skill.
"""
import os
import re

from probandia import events
from probandia.errors import UsageError
from probandia.i18n import _
from probandia.util.fs import iso, utc_now
from probandia.util.ids import slugify
from probandia.util.locks import Locks
from probandia.util.schema import validate_document

RUN_KEYS = ("mode", "max_agents", "max_passes", "model", "effort")


def locked(*args, **kwargs):
    """``indexes.locked``, imported when a lock is taken: a hook that reads the pass state loads no
    YAML (T145)."""
    from probandia.indexes import locked

    return locked(*args, **kwargs)


# families


def families(project):
    from probandia.util import yamlio

    root = os.path.join(project, "families")
    out = {}
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name, "family.yaml")
            if os.path.isfile(path):
                out[name] = yamlio.load(path) or {}
    return out


def _fold(text):
    from probandia.lang.places import key

    return key(text)


def infer_family(project, question):
    """(family id or None, candidate slugs for the question when none is known).

    A family is inferred when the question names one of its surnames (or its
    name), or when it is the project's only family and the question names no
    surname of another."""
    known = families(project)
    words = set(_fold(question).split())
    hits = []
    for fid, doc in known.items():
        names = [fid, doc.get("name") or ""] + list(doc.get("surnames") or [])
        if any(_fold(n) and set(_fold(n).split()) <= words for n in names if n):
            hits.append(fid)
    if len(hits) == 1:
        return hits[0], []
    if not hits and len(known) == 1 and not _surname_candidates(question):
        return next(iter(known)), []
    candidates = list(dict.fromkeys(hits or [slugify(w) for w in _surname_candidates(question)]))
    caps = re.findall(r"\b[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'\-]{2,}\b", question)
    if not known and len(candidates) == 1 and caps:
        return candidates[0], []  # a new project, and one surname written in capitals
    return None, candidates[:3]


def _surname_candidates(question):
    """Words written in capitals (HUGO), else capitalised words that do not
    start the sentence (Hugo): the likely surnames of a question."""
    caps = re.findall(r"\b[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'\-]{2,}\b", question)
    if caps:
        return caps
    words = re.findall(r"(?<![.?!]\s)(?<!^)\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+\b", question.strip())
    common = {"Who", "What", "When", "Where", "Qui", "Quand", "Quel", "Quelle", "Quels", "Quelles",
              "Wer", "Wann", "Wo", "Quién", "Dónde"}
    return [w for w in words if w not in common]


def create_family(project, fid, question="", language="en"):
    """``families/<fid>/family.yaml`` and its folders. Returns the path written."""
    from probandia.util import yamlio

    folder = os.path.join(project, "families", fid)
    path = os.path.join(folder, "family.yaml")
    if os.path.isfile(path):
        return None
    name = fid.replace("-", " ").upper()
    doc = {"schema": 1, "id": fid, "name": name, "surnames": [fid.replace("-", " ").title()],
           "places": [], "language": language}
    validate_document("family", doc, "family.yaml")
    for sub in ("index", "research", "evidence", "trees"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    yamlio.dump(path, doc)
    return path


# passes


def pass_state(log):
    """(last pass number, whether it is open): open when its ``pass.started`` has
    no ``pass.ended``."""
    started, ended = set(), set()
    for e in log:
        if e["type"] == "pass.started":
            started.add(e["pass"])
        elif e["type"] == "pass.ended":
            ended.add(e["pass"])
    last = max(started | ended, default=0)
    return last, last in started and last not in ended


def volets(log):
    """The volets of a research (FL-D8), oldest first: the payloads of ``volet.opened``."""
    return [e["payload"] for e in log if e["type"] == "volet.opened"]


def current_volet(log):
    """The number of the last volet opened, or None."""
    found = volets(log)
    return found[-1]["n"] if found else None


def open_volet(project, research, actor, expiry, title, established=(), corrections=(), openings=()):
    """Opens the next volet: it starts at the open pass, else at the next one. Returns its payload and,
    when the volet before it holds fewer than four passes, (that volet, its passes)."""
    log = events.read(research.events_path)
    last, open_ = pass_state(log)
    before = volets(log)
    clean = lambda xs: [x.strip() for x in xs or () if x and x.strip()]   # noqa: E731
    payload = {"n": len(before) + 1, "title": title.strip(), "from_pass": last if open_ else last + 1,
               "established": clean(established), "corrections": clean(corrections), "openings": clean(openings)}
    short = None
    if before and payload["from_pass"] - before[-1]["from_pass"] < 4:
        short = (before[-1]["n"], payload["from_pass"] - before[-1]["from_pass"])
    with locked(project, f"research:{research.id}", actor, expiry):
        events.append(research.events_path, [events.make("volet.opened", payload, actor, last)])
    return payload, short


def current_pass(research):
    """The open pass, else the last completed one: the pass that searches, events
    and evidence belong to."""
    last, open_ = pass_state(events.read(research.events_path))
    if open_:
        return last
    return max(last, int((research.meta() or {}).get("passes") or 0))


def _meta_path(research):
    return os.path.join(research.folder, "research.yaml")


def update_meta(research, **changes):
    from probandia.util import yamlio

    meta = research.meta() or {}
    meta.update(changes)
    validate_document("research", meta, "research.yaml")
    yamlio.dump(_meta_path(research), meta)
    return meta


def add_instructions(research, pass_no, texts, now=None):
    texts = [t.strip() for t in texts or [] if t and t.strip()]
    if not texts:
        return research.meta()
    meta = research.meta() or {}
    ts = iso(now or utc_now())
    history = list(meta.get("instructions") or [])
    history += [{"pass": pass_no, "ts": ts, "text": t} for t in texts]
    return update_meta(research, instructions=history)


def _pass_owner(owner):
    return {k: owner[k] for k in ("harness", "session", "agent") if owner.get(k)}


def take_research_lock(project, research, owner, expiry):
    """The research lock for the whole pass. A lock of the same session (another of
    its agents) is renewed as it is."""
    from probandia.util.locks import same_session

    locks = Locks(project, expiry_minutes=expiry)
    scope = f"research:{research.id}"
    info, expired = locks.status(scope)
    if info is not None and not expired and same_session(info.get("owner"), owner):
        return locks.renew(scope, info["owner"])
    return locks.take(scope, _pass_owner(owner))


def release_research_lock(project, research, owner, expiry):
    from probandia.util.locks import same_session

    locks = Locks(project, expiry_minutes=expiry)
    scope = f"research:{research.id}"
    info, _expired = locks.status(scope)
    if info is None:
        return False
    holder = info.get("owner") or {}
    if same_session(holder, owner):
        return locks.release(scope, holder)
    try:
        return locks.release(scope, _pass_owner(owner))
    except Exception:  # noqa: BLE001 — a lock held by another session is not ours to release
        return False


def start_pass(project, research, actor, expiry, run=None, instructions=(), assumed=False):
    """Steps 1 and 2: the research lock, then ``pass.started``. Returns the pass number."""
    take_research_lock(project, research, actor, expiry)
    log = events.read(research.events_path)
    last, open_ = pass_state(log)
    if open_:
        raise UsageError(_("pass {n} is still open").format(n=last))
    n = last + 1
    payload = {"n": n, "run": run or (research.meta() or {}).get("run") or {"mode": "session"},
               "instructions": list(instructions)}
    if assumed:
        payload["assumed"] = True
    if current_volet(log):   # FL-D8: the pass belongs to the volet open when it starts
        payload["volet"] = current_volet(log)
    with locked(project, f"research:{research.id}", actor, expiry):
        events.append(research.events_path, [events.make("pass.started", payload, actor, n)])
    return n


def native_count(project, research, pass_no):
    from probandia.indexes import FamilyIndexes

    return sum(1 for s in FamilyIndexes(project, research.family).items("searches")
               if s.get("research") == research.id and s.get("pass") == pass_no and s.get("kind") == "native")


def end_pass(project, research, actor, expiry, summary="", native=None, duration=None, extra=None):
    """Steps 12 and 13: ``pass.ended``, ``passes`` in research.yaml, then the lock. ``extra``: more of
    the payload (``workshop_deferred``)."""
    log = events.read(research.events_path)
    last, open_ = pass_state(log)
    if not open_:
        raise UsageError(_("no pass is open in {id}").format(id=research.id))
    counted = native_count(project, research, last)
    started = next(e for e in reversed(log) if e["type"] == "pass.started" and e["pass"] == last)
    if duration is None:
        from probandia.util.fs import parse_iso

        duration = int((utc_now() - parse_iso(started["ts"])).total_seconds())
    payload = {"n": last, "summary": summary or "", "units": _units(project, research, last),
               "native_searches": counted if native is None else native, "duration_s": max(0, duration),
               "tools": tool_counts(project, research, last)}
    payload.update(extra or {})
    with locked(project, f"research:{research.id}", actor, expiry):
        events.append(research.events_path, [events.make("pass.ended", payload, actor, last)])
        update_meta(research, passes=last)
    release_research_lock(project, research, actor, expiry)
    return last, payload


def _ledger_entries(project, research, pass_no):
    path = os.path.join(project, ".probandia", "ledger.jsonl")
    if not os.path.isfile(path):
        return []
    import json

    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("research") == research.id and e.get("pass") == pass_no:
                out.append(e)
    return out


def _units(project, research, pass_no):
    out = {}
    for e in _ledger_entries(project, research, pass_no):
        out[e["provider"]] = out.get(e["provider"], 0) + (e.get("units") or 0)
    return out


CALLS = os.path.join(".probandia", "calls.jsonl")


def note_call(project, command):
    """token-economy H2: one line per engine command an agent ran (from a shell or through the MCP
    server, both go through ``cli.main``) while a research lock is held, that is while a pass is open.
    shortcut: the call goes to every research whose lock is held; one session opens one pass at a time."""
    import json

    try:
        held = sorted(n[len("research-"):-len(".json")] for n in os.listdir(os.path.join(project, ".probandia", "locks"))
                      if n.startswith("research-") and n.endswith(".json"))
        if held:
            with open(os.path.join(project, CALLS), "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({"ts": iso(utc_now()), "command": command, "research": held}) + "\n")
    except OSError:   # counting never stops a command
        pass


def engine_calls(project, research, since):
    """The commands noted for the research from ``since`` (the ISO time its pass started) on."""
    import json

    try:
        with open(os.path.join(project, CALLS), encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return []
    return [r.get("command") for r in rows if research.id in (r.get("research") or []) and str(r.get("ts")) >= since]


def tool_counts(project, research, pass_no):
    """The pass's tools (FL-D7): native web searches, MCP calls, archive commands, engine commands.
    An MCP call of a catalogued provider is in the ledger (``source=hook``); one of another
    server only in the search log, under ``mcp:<server>``. token-economy H2: ``engine`` counts every
    engine command of the pass and ``archive`` its ``archive`` commands, not only the searches they logged."""
    from probandia.indexes import FamilyIndexes

    counts = {"web": 0, "mcp": sum(1 for e in _ledger_entries(project, research, pass_no)
                                   if e.get("source") == "hook"), "archive": 0, "engine": 0}
    for s in FamilyIndexes(project, research.family).items("searches"):
        if s.get("research") != research.id or s.get("pass") != pass_no:
            continue
        if s.get("kind") == "native":
            counts["web"] += 1
        elif str(s.get("engine") or "").startswith("mcp:"):
            counts["mcp"] += 1
    started = [e["ts"] for e in events.read(research.events_path) if e["type"] == "pass.started" and e["pass"] == pass_no]
    calls = engine_calls(project, research, started[-1]) if started else []
    counts["engine"], counts["archive"] = len(calls), calls.count("archive")
    return counts


def run_options(args, config, meta_run=None, harness="cli"):
    """The run block of research.yaml, and the launch questions still open.

    The run mode comes from ``--mode``, else from the research, else from
    ``run.mode`` (``ask`` there means E-1's question). The model and effort come
    from the options, the research or the settings; a team takes its size, effort
    and passes from the options or the ``team.*`` settings."""
    from probandia.questions import missing_run

    run = dict(meta_run or {})
    if getattr(args, "mode", None):
        run["mode"] = args.mode
    elif not run.get("mode") and config.get("run.mode") != "ask":
        run["mode"] = config.get("run.mode")
    for key, opt, setting in (("model", "model", "run.model"), ("effort", "effort", "run.effort")):
        value = getattr(args, opt, None) or run.get(key) or config.get(setting)
        if value:
            run[key] = value
    if getattr(args, "agents", None):
        run["max_agents"] = args.agents
    if getattr(args, "passes", None):
        run["max_passes"] = args.passes
    if run.get("mode") == "team":
        for key, setting in (("max_agents", "team.max_agents"), ("effort", "team.effort"),
                             ("max_passes", "team.max_passes")):
            if not run.get(key) and config.get(setting) is not None:
                run[key] = config.get(setting)
    missing = missing_run(run, config, harness)
    return {k: run[k] for k in RUN_KEYS if run.get(k) not in (None, "")}, missing
