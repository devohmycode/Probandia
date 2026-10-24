"""The state digest of a research: what ``resume`` reads instead of the report.

At most ``digest.max_lines`` lines, in a fixed order::

    RESEARCH=… FAMILY=… PASS=… MODE=… LANG=…
    QUESTION=…
    INSTRUCTION=…
    TOKENS=…          input-equivalent tokens recorded for the pass so far, when any
    UNCHECKED=…       the concluding facts no person checked (T248), when any: their number, then
                      up to 5 of them
    STANDARDS:        up to 5 open questions, with what will count as their answer (T249)
    LEADS:            up to 10 open leads
    HYPOTHESES:       open hypotheses with their marks
    ERRATA_PENDING:   facts flagged for revision
    NEGATIVES_DUE:    up to 5 negatives whose recheck is due
    NEW_FACTS:        facts added to the family since this research's last pass
    QUOTAS:           up to 5 providers with the most free quota left; those under 20 %;
                      a drift the last reading of a balance showed
    WORKSHOP: …       a project linked to its workshop: the new and divergent facts of the
                      research, and whether the workshop changed since the last sync
    LOCKS:            other holders on the family
    NEXT=…

A section with nothing under it is left out (token-economy E6).

It reads ``research.yaml``, the events, the family indexes, the archive catalogue,
the ledger and the locks; never a report.

A negative's ``recheck_if`` is one condition on the archive catalogue:
``<archive> covers <place code>`` (the place is in its coverage and not in
``absent``), ``<archive> covers <year>``, ``<archive> has <record type>``, or
``<archive> exists``. It is met when the catalogue says so now.
"""
import datetime
import os
import re

from probandia import events
from probandia.indexes import FamilyIndexes
from probandia.lifecycle import pass_state
from probandia.util.fs import parse_iso
from probandia.util.ids import is_ulid, ulid_time_ms

RECHECK = re.compile(r"^\s*([a-z0-9_-]+)\s+(covers|has|exists)\s*(\S*)\s*$", re.I)
SECTION = re.compile(r"^[A-Z_]+:$")


def recheck_met(text, catalogue):
    """True when the condition holds in the archive catalogue now; None when it
    cannot be read."""
    m = RECHECK.match(text or "")
    if not m:
        return None
    archive, verb, arg = m.group(1).lower(), m.group(2).lower(), m.group(3)
    entry = catalogue.get(archive)
    if verb == "exists":
        return entry is not None
    if entry is None:
        return False
    cov = entry.get("coverage") or {}
    if verb == "has":
        return arg in (cov.get("types") or [])
    if arg.isdigit():
        years = cov.get("years") or []
        return len(years) == 2 and years[0] <= int(arg) <= years[1]
    from probandia.archives.coverage import covers

    code = arg.upper()
    if any(code == a or code.startswith(a + "-") for a in cov.get("absent") or []):
        return False
    return covers(cov.get("places") or [], [code])


def negatives_due(searches, catalogue, today, recheck_days=365):
    due = []
    for s in searches:
        if s.get("result") != "negative" or s.get("family") == "opaque":
            continue
        why = None
        if s.get("recheck_if") and recheck_met(s["recheck_if"], catalogue):
            why = f"recheck_if met: {s['recheck_if']}"
        elif s.get("recheck_after") and datetime.date.fromisoformat(s["recheck_after"]) <= today:
            why = f"recheck_after {s['recheck_after']}"
        elif not s.get("recheck_if") and not s.get("recheck_after") and s.get("ts") and \
                (today - parse_iso(s["ts"]).date()).days >= recheck_days:
            why = f"older than {recheck_days} days"
        if why:
            due.append((s, why))
    # a condition met on the catalogue first: it is news; then the dates
    return sorted(due, key=lambda x: 0 if x[1].startswith("recheck_if") else 1)


def _date(fact):
    d = fact.get("date") or {}
    value = d.get("value") or "?"
    q = d.get("qualifier")
    return f"{q}:{value}" if q and q != "exact" else value


def build(project, research, config=None, today=None, ledger=None, catalogue=None, usable=None):
    """The digest lines, at most ``digest.max_lines``."""
    from probandia.archives.finder import load_catalogue
    from probandia.util.locks import Locks

    get = (lambda k, d=None: config.get(k)) if config is not None else (lambda k, d=None: d)
    max_lines = get("digest.max_lines", 60) or 60
    today = today or datetime.date.today()
    meta = research.meta() or {}
    log = events.read(research.events_path)
    last, open_ = pass_state(log)
    current = last if open_ else last + 1
    idx = FamilyIndexes(project, research.family)
    persons = idx.items("persons")
    hypotheses = [h for h in idx.items("hypotheses") if not h.get("closed")]
    catalogue = catalogue if catalogue is not None else load_catalogue(project)

    out = [f"RESEARCH={research.id} FAMILY={research.family} PASS={current} "
           f"MODE={meta.get('mode', 'journal')} LANG={meta.get('language', 'en')}",
           f"QUESTION={meta.get('question', '')}"]
    instructions = meta.get("instructions") or []
    out.append(f"INSTRUCTION={instructions[-1]['text'] if instructions else ''}")
    from probandia import tokens

    spent = tokens.pass_weighted(project, research.id, current)
    if spent is not None:   # token-economy I2: what the pass has cost so far, as the stop hooks recorded it
        out.append(f"TOKENS={spent}")
    from probandia import factcheck

    left = factcheck.unchecked(meta, factcheck.of_family(project, research.family))
    if left:   # T248: the concluding facts that no person checked (fact check, at the user's terminal)
        out.append(f"UNCHECKED={len(left)} ({', '.join(left[:5])}{', …' if len(left) > 5 else ''})")
    from probandia.proof import questions as Q

    out.append("STANDARDS:")   # T249: what will count as the answer of each open question that says it
    out += [f"  {q['id']}: {q['standard']}" for q in Q.unsettled(meta) if q.get("standard")][:5]

    ended = [e for e in log if e["type"] == "pass.ended"]
    leads = []
    if ended:
        summary = (ended[-1].get("payload") or {}).get("summary") or ""
        leads += [x.strip() for x in re.split(r"[;\n]", summary) if x.strip()]
    leads += [f"{h['id']}: {h['discriminating']}" for h in hypotheses if h.get("discriminating")]
    out.append("LEADS:")
    out += [f"  {x}" for x in leads[:10]]

    out.append("HYPOTHESES:")
    for h in hypotheses[:8]:
        marks = {}
        for ev in h.get("evidence") or []:
            for alt, mark in (ev.get("marks") or {}).items():
                marks.setdefault(alt, []).append(mark)
        alts = "; ".join(f"{a['id']}: {a['statement']} ({a.get('status', 'open')}"
                         + (", " + ", ".join(marks[a["id"]]) if a["id"] in marks else "") + ")"
                         for a in h.get("hypotheses") or [])
        out.append(f"  {h['id']} {h['question']} — {alts}")

    out.append("ERRATA_PENDING:")
    revised = {(e.get("payload") or {}).get("fact") for e in log if e["type"] == "fact.revised"}
    pending = [(p, f) for p in persons for f in p.get("facts", [])
               if f.get("uncertain_reading") and f["id"] not in revised]
    out += [f"  {f['id']} {f['type']} {_date(f)}: {f['uncertain_reading']}" for _p, f in pending[:5]]

    out.append("NEGATIVES_DUE:")
    due = negatives_due(idx.items("searches"), catalogue, today, get("negatives.recheck_days", 365) or 365)
    out += [f"  {s['id']} \"{s['query']}\" {s.get('engine') or s.get('kind')} — {why}" for s, why in due[:5]]

    out.append("NEW_FACTS:")
    since = parse_iso(ended[-1]["ts"]) if ended else None
    new = []
    for p in persons:
        for f in p.get("facts", []):
            if f.get("research") == research.id or not is_ulid(f.get("event") or ""):
                continue
            when = datetime.datetime.fromtimestamp(ulid_time_ms(f["event"]) / 1000, datetime.timezone.utc)
            if since is None or when > since:
                new.append(f)
    out += [f"  {f['id']} {f['type']} {_date(f)} [{f['status']}] ({f.get('research') or '-'})" for f in new[:5]]

    from probandia import logins

    manual = logins.manual_tasks(project, research.id)
    if manual:   # optimize 3.10: pages no one could sign in for, to read by hand
        out.append("MANUAL_TASKS:")
        out += [f"  {m['archive']} {m['url']} (login required)" for m in manual[:5]]

    out.append("QUOTAS:")
    if ledger is not None:
        reserve = get("budget.reserve_percent", 10) or 0
        lefts = []
        for provider in usable or []:
            left = ledger.left(provider, reserve)
            if left is not None:
                lefts.append((left, provider))
        out += [f"  {p} {left:,.0f} left" for left, p in sorted(lefts, key=lambda x: (-x[0], x[1]))[:5]]
        out += [f"  low: {p} {n}% left" for p, n in ledger.low(usable or [], reserve)]   # T62
        pools = list(dict.fromkeys(ledger.pool(p) for p in usable or []))
        for pool in pools:   # T52: what the provider counted and the ledger did not see
            d = ledger.drift(pool)
            if d:
                out.append(f"  {pool} drift {d['percent']}%: provider {d['provider']:g}, ledger {d['counted']:g} "
                           f"since {str(d['since'])[:10]}")

    line = workshop_line(project, research)
    if line:
        out.append(line)
    out.append("LOCKS:")
    locks = Locks(project, expiry_minutes=get("locks.expiry_minutes", 30) or 30)
    for scope in [f"family:{research.family}"] + [f"research:{r}" for r in _family_researches(research)]:
        info, expired = locks.status(scope)
        if info is not None and not expired:
            d = locks.describe(scope, info)
            out.append(f"  {scope} {d['HOLDER']} until {d['EXPIRES']}")

    planned = open_ and any(e["type"] == "plan.made" and e["pass"] == last for e in log)
    if due:
        hint = f"recheck the negative {due[0][0]['id']}"
    elif leads:
        hint = f"follow the lead: {leads[0]}"
    else:
        hint = ""
    if planned:
        nxt = "continue the pass: searches, evidence, proposals, apply"
    else:
        nxt = "known, then plan" + (f"; {hint}" if hint else "")
    tail = f"NEXT={nxt}"
    # E6: a section with nothing under it is left out (QUOTAS: with no quota to show…)
    out = [x for i, x in enumerate(out)
           if not (SECTION.match(x) and (i + 1 == len(out) or SECTION.match(out[i + 1])))]
    if len(out) + 1 > max_lines:
        out = out[: max_lines - 1]
    return out + [tail]


def workshop_line(project, research):
    """WS5-T4: ``WORKSHOP: <n> new, <n> divergent, workshop changed since the last sync: yes|no``, or None
    in a project without workshop; the digest never fails on it."""
    from probandia import workshop as ws

    try:
        link = ws.load(project)
        if link is None:
            return None
        state = ws.State(project, link, research.id)
    except Exception:  # noqa: BLE001 — a workshop that cannot be read leaves the digest as it is
        return None
    c = state.counts
    return (f"WORKSHOP: {c['new']} new, {c['divergent']} divergent, workshop changed since the last sync: "
            f"{'yes' if state.changed else 'no'}")


def lines_for(project, research, config, environ):
    """The digest as resume gives it: with the quotas left of the usable providers.
    The hook that injects it builds it the same way, so that resume sees it as given."""
    from probandia.ledger import Ledger
    from probandia.providers import catalogue

    return build(project, research, config, ledger=Ledger(project, catalogue.load(), environ=environ),
                 usable=catalogue.usable(config, environ))


def _family_researches(research):
    import os

    folder = os.path.dirname(research.folder)
    return sorted(r for r in os.listdir(folder) if r != research.id) if os.path.isdir(folder) else []


# Differential digest (optimize 2.13): a second resume in the same session gets
# only what changed since the digest that session last received.

SEEN = "digest-seen.json"   # in <project>/.probandia: {"<session> <research>": [lines]}
DIFF_MAX_LINES = 15


def _sections(lines):
    """{section header: [its lines]}; the lines before the first header go under ""."""
    out, current = {"": []}, ""
    for line in lines:
        if re.match(r"^[A-Z_]+:$", line):
            current = line
            out.setdefault(current, [])
        elif not line.startswith("NEXT="):
            out[current].append(line)
    return out


def differential(previous, lines, max_lines=DIFF_MAX_LINES):
    """The lines of ``lines`` that ``previous`` did not have, each under its section,
    with what went away, the first line and NEXT=: ``max_lines`` lines at most."""
    before, now = _sections(previous[1:]), _sections(lines[1:])   # the first line is always shown
    head = [lines[0]] if lines else []
    body = []
    for section in dict.fromkeys([*now, *before]):   # a section emptied since is left out of ``now``
        items = now.get(section, [])
        added = [x for x in items if x not in before.get(section, []) and x not in head]
        gone = [x for x in before.get(section, []) if x not in items]
        if added or gone:
            if section:
                body.append(section)
            body += added
            body += [f"  gone: {x.strip()}" for x in gone]
    if not body:
        body = ["UNCHANGED: nothing new since your last digest"]
    tail = [x for x in lines if x.startswith("NEXT=")]
    room = max_lines - len(head) - len(tail)
    if len(body) > room:
        body = body[: room - 1] + [f"MORE: {len(body) - room + 1} more lines in DETAILS"]
    return head + body + tail


def seen(project, session, research_id, lines=None):
    """The digest lines this session last received for the research; with
    ``lines``, records them instead."""
    import json

    path = os.path.join(project, ".probandia", SEEN)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    key = f"{session} {research_id}"
    if lines is None:
        return data.get(key)
    data[key] = list(lines)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except OSError:
        pass
    return lines
