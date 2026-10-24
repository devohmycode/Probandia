"""Reading the work of the agents without an agent (cli.md § 5.6 to 5.8, CLI8).

``research list|show|log|pause|close|reopen``. Every listing reads the files of
the project only; every change goes through the engine, under its locks.
"""
import datetime
import json
import re
import time

from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import N_, _

RESEARCH_ACTIONS = ("list", "show", "log", "pause", "close", "reopen")
RESEARCH_STATUSES = ("open", "paused", "closed")


def _since(text):
    """``YYYY-MM-DD`` -> the same text, checked; None stays None."""
    if text is None:
        return None
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        raise UsageError(_("--since takes a date such as 2026-09-01, not {value}").format(value=text))


def _n(n, one, many, **values):
    return (one if n == 1 else many).format(n=n, **values)


def _listing(r, title):
    """The readable layout of the listings (cli.views.render_listing)."""
    r.view, r.extra = "listing", {"title": title}
    return r


# research


def research_args(p, common):
    p.add_argument("action", nargs="?", default="list", choices=RESEARCH_ACTIONS)
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--family", help=_("family slug"))
    p.add_argument("--status", choices=RESEARCH_STATUSES, help=_("only the researches in this status"))
    p.add_argument("--since", metavar="<date>", help=_("only what happened since this date (YYYY-MM-DD)"))
    p.add_argument("-f", "--follow", action="store_true", help=_("log: keep showing the events as they come"))
    p.add_argument("--jsonl", action="store_true", help=_("log: the events as they are, one JSON object per line"))


def research(ctx):
    return {"list": research_list, "show": research_show, "log": research_log,
            "pause": research_status, "reopen": research_status, "close": research_close}[ctx.args.action](ctx)


def research_list(ctx):
    """research list (cli.md 5.6.2): every research, newest activity first, filtered."""
    from probandia import board

    since = _since(ctx.args.since)
    rows = [x for x in board.researches(ctx.project)
            if (not ctx.args.family or x["family"] == ctx.args.family)
            and (not ctx.args.status or x["status"] == ctx.args.status)
            and (not since or str(x["last_activity"])[:10] >= since)]
    r = Result("OK", {"RESEARCHES": len(rows)})
    for x in rows:
        state = f"pass {x['open_pass']} open" if x["open_pass"] else f"{x['passes']} passes"
        r.data("research", f"{x['research']} [{x['status']}] {state} {x['family']} {x['last_activity']}")
    r.table("researches", [{"research": x["research"], "family": x["family"], "status": x["status"],
                            "passes": x["passes"], "open_pass": x["open_pass"], "pending": x["pending"],
                            "last_activity": x["last_activity"]} for x in rows])
    return _listing(r, _n(len(rows), _("{n} research"), _("{n} researches")))


def _units(units):
    return " ".join(f"{k}:{v:g}" for k, v in sorted((units or {}).items())) or "—"


def research_show(ctx):
    """research show (cli.md 5.6.3): the question and instructions, the passes as
    pass.ended tells them, what the research found, the last verify and the tokens."""
    from probandia import events, known, tokens
    from probandia.indexes import FamilyIndexes
    from probandia.research import find_research

    res = find_research(ctx.project, ctx.args.research, ctx.environ)
    meta, log = res.meta() or {}, events.read(res.events_path)
    idx = FamilyIndexes(ctx.project, res.family)
    facts = [f for p in idx.items("persons") for f in p.get("facts", []) if f.get("research") == res.id]
    found = known.known(ctx.project, res.family, config=ctx.config)
    negatives = [s for s in found["negatives"] if s.get("research") == res.id]
    ended = [e["payload"] for e in log if e["type"] == "pass.ended"]
    runs = [e for e in log if e["type"] == "verify.run"]
    results = runs[-1]["payload"].get("results") or {} if runs else {}
    failed = [rule for rule, status in results.items() if status == "FAIL"]
    r = Result("OK", {"RESEARCH": res.id, "FAMILY": res.family, "RESEARCH_STATUS": meta.get("status", "open"),
                      "QUESTION": meta.get("question", ""), "PASSES": len(ended), "FACTS": len(facts),
                      "NEGATIVES": len(negatives), "HYPOTHESES": len(found["hypotheses"]),
                      "GAPS": len(found["gaps"]),
                      "VERIFY": ("never" if not runs else "failed " + ",".join(failed) if failed else "passed")})
    for p in ended:
        r.data("pass", f"{p['n']} {p.get('duration_s', 0)}s units={_units(p.get('units'))} "
                       f"native={p.get('native_searches', 0)} {p.get('summary', '')}".rstrip())
    r.table("instructions", [{"pass": i.get("pass"), "instruction": i.get("text")}
                             for i in meta.get("instructions") or []])
    r.table("passes", [{"pass": p["n"], "duration": _("{n} min").format(n=round((p.get("duration_s") or 0) / 60)),
                        "units": _units(p.get("units")), "native": p.get("native_searches", 0),
                        "summary": p.get("summary", "")} for p in ended])
    r.table("facts", [{"fact": f["id"], "date": known.date_text(f), "place": known.place_text(f),
                       "status": f["status"], "source": f.get("source")} for f in facts])
    r.table("negatives", [{"search": s["id"], "state": s["state"], "query": s["query"]} for s in negatives])
    r.table("hypotheses", [{"hypothesis": h["id"], "question": h["question"]} for h in found["hypotheses"]])
    r.table("gaps", [{"archive": g["archive"], "reference": g.get("reference"),
                      "window": f"{g['window']['from']}-{g['window']['to']}", "kind": g["kind"]}
                     for g in found["gaps"]])
    r.table("verify", [{"rule": rule, "status": status} for rule, status in results.items() if status != "PASS"])
    pass_no, roles = tokens.by_role(ctx.project, res.id)
    r.table("tokens", [{"role": role, "pass": pass_no, "input": t["input"], "output": t["output"],
                        "weighted": tokens.weighted(t)} for role, t in sorted(roles.items())])
    title = f"{res.id} · {meta.get('question', '')}"
    if runs:
        r.line(_("verify failed on {rules}").format(rules=", ".join(failed)) if failed else _("verify passed"))
    else:
        r.line(_("verify was never run on this research"))
    return _listing(r, title)


# research log (cli.md 5.6.4, § 7.3)

_sleep = time.sleep   # tests replace it


def tail(path, offset):
    """(the complete lines written after byte ``offset``, the offset after them):
    an append-only file is never read twice, and a line half written waits."""
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except FileNotFoundError:
        return [], offset
    end = chunk.rfind(b"\n") + 1
    return chunk[:end].decode("utf-8").splitlines(), offset + end


def event_what(e):
    """What an event says, in a few words."""
    p = e.get("payload") or {}
    if isinstance(p.get("fact"), dict):
        return f"{p['fact'].get('id')} [{p['fact'].get('status')}]"
    if isinstance(p.get("section"), dict):
        return p["section"].get("title") or ""
    if e["type"] == "verify.run":
        return " ".join(k for k, v in (p.get("results") or {}).items() if v == "FAIL") or "PASS"
    for key in ("summary", "search", "proposal", "plan", "root", "text"):
        if p.get(key):
            return str(p[key])
    return " ".join(f"{k}={v}" for k, v in p.items() if isinstance(v, (str, int, float)))[:80]


def event_row(e):
    return {"time": e["ts"][:16].replace("T", " "), "pass": e["pass"], "type": e["type"], "what": event_what(e)}


def _event_line(e):
    x = event_row(e)
    return f"{x['time']}  p{x['pass']}  {x['type']:<20} {x['what']}".rstrip()


def research_log(ctx):
    """The events of a research in clear; ``--follow`` reads on from the last byte
    read, once a second, until Ctrl+C; ``--jsonl`` keeps them as they are."""
    from probandia.research import find_research

    res = find_research(ctx.project, ctx.args.research, ctx.environ)
    since = _since(ctx.args.since)
    lines, offset = tail(res.events_path, 0)
    shown = [x for x in lines if not since or json.loads(x)["ts"][:10] >= since]
    if ctx.args.follow:
        write = ctx.stdout.write
        try:
            while True:
                for line in shown:
                    write((line if ctx.args.jsonl else _event_line(json.loads(line))) + "\n")
                ctx.stdout.flush()
                _sleep(1)
                shown, offset = tail(res.events_path, offset)
        except KeyboardInterrupt:
            return None
    found = [json.loads(x) for x in shown]
    r = Result("OK", {"RESEARCH": res.id, "EVENTS": len(found)})
    if ctx.args.jsonl:
        r.raw = "".join(x + "\n" for x in shown)
        return r
    for e in found:
        r.data("event", _event_line(e))
    r.table("events", [event_row(e) for e in found])
    return _listing(r, _n(len(found), _("{n} event"), _("{n} events")) + f" · {res.id}")


# research pause, close, reopen (cli.md 5.6.6)


def research_status(ctx):
    """pause (open -> paused) and reopen (paused or closed -> open), under the lock
    of the research: a research an agent is writing is refused at once (exit 5)."""
    from probandia import lifecycle
    from probandia.cli.data_cmd import actor
    from probandia.indexes import locked
    from probandia.research import find_research

    res = find_research(ctx.project, ctx.args.research, ctx.environ)
    target = "paused" if ctx.args.action == "pause" else "open"
    with locked(ctx.project, f"research:{res.id}", actor(ctx), ctx.config.get("locks.expiry_minutes") or 30,
                wait_seconds=0):
        before = (res.meta() or {}).get("status", "open")
        if ctx.args.action == "pause" and before == "closed":
            raise UsageError(_("the research is closed; reopen it first"),
                             values={"REASON": "closed", "RESEARCH": res.id})
        if before != target:
            lifecycle.update_meta(res, status=target)
    return Result("OK", {"RESEARCH": res.id, "RESEARCH_STATUS": target, "WAS": before})


def research_close(ctx):
    """close, as the ``close`` command does it (its checks, its verify), after a confirmation."""
    from probandia.cli import asking
    from probandia.cli.lifecycle_cmd import close_cmd
    from probandia.research import find_research

    res = find_research(ctx.project, ctx.args.research, ctx.environ)
    if not asking.confirm(ctx, _("Close the research {research}?").format(research=res.id)):
        return asking.declined({"RESEARCH": res.id})
    ctx.args.research = res.id
    return close_cmd(ctx)


# family (cli.md 5.6.7)

BIRTH, END = ("birth", "baptism"), ("death", "burial")


def _first_date(person, types):
    from probandia.known import date_text

    for f in person.get("facts", []):
        if f["type"] in types and f.get("status") != "refuted":
            return date_text(f)
    return None


def _name(person):
    names = person.get("names") or {}
    return " ".join(x for x in (names.get("given"), names.get("surname")) if x)


def family_args(p, common):
    p.add_argument("action", nargs="?", default="list", choices=("list", "show"))
    p.add_argument("family", nargs="?", help=_("family slug"))


def family(ctx):
    from probandia import lifecycle
    from probandia.indexes import FamilyIndexes
    from probandia.research import all_researches, default_family, family_folder

    fams, researches = lifecycle.families(ctx.project), all_researches(ctx.project)
    if ctx.args.action == "list":
        rows = [{"family": fid, "name": d.get("name"), "language": d.get("language"),
                 "persons": len(FamilyIndexes(ctx.project, fid).items("persons")),
                 "researches": sum(1 for x in researches if x.family == fid),
                 "places": ", ".join(d.get("places") or [])} for fid, d in fams.items()]
        r = Result("OK", {"FAMILIES": len(rows)})
        for x in rows:
            r.data("family", f"{x['family']} persons={x['persons']} researches={x['researches']}")
        r.table("families", rows)
        return _listing(r, _n(len(rows), _("{n} family"), _("{n} families")))
    fid = ctx.args.family or default_family(ctx.project)
    family_folder(ctx.project, fid)   # an unknown family is a usage error, with suggestions
    d, persons = fams[fid], FamilyIndexes(ctx.project, fid).items("persons")
    mine = [x for x in researches if x.family == fid]
    period = "-".join(str(y) for y in d.get("period") or [])
    r = Result("OK", {"FAMILY": fid, "NAME": d.get("name", ""), "LANGUAGE": d.get("language", ""),
                      "PERIOD": period, "PERSONS": len(persons), "RESEARCHES": len(mine)})
    r.table("persons", [{"person": p["id"], "name": _name(p), "born": _first_date(p, BIRTH),
                         "died": _first_date(p, END)} for p in persons])
    r.table("researches", [{"research": x.id, "status": (x.meta() or {}).get("status", "open"),
                            "question": (x.meta() or {}).get("question")} for x in mine])
    r.line(_("surnames: {names}").format(names=", ".join(d.get("surnames") or []) or "—"))
    r.line(_("places: {places}").format(places=", ".join(d.get("places") or []) or "—"))
    return _listing(r, _("Family {family}").format(family=d.get("name") or fid) + (f" · {period}" if period else ""))


# find (cli.md 5.7.1)

MATCHES = ("exact", "variant", "phonetic", "given name")


def find_args(p, common):
    p.add_argument("name", help=_("a surname, a given name, or both"))
    p.add_argument("--family", help=_("family slug"))


def variant_groups(variants):
    """The spellings of the variants index, folded: one set per name."""
    from probandia.lang.phonetic import fold

    return [{fold(name)} | {fold(a["form"]) for a in attested} for name, attested in variants.items()]


def _match(words, person, groups):
    """(the index in MATCHES of the best way ``words`` name ``person``, whether a word
    is also their given name), or None."""
    from probandia.lang.phonetic import fold, same_name

    names = person.get("names") or {}
    surname, given = fold(names.get("surname") or ""), fold(names.get("given") or "")
    given_too = bool(given) and any(fold(w) == given for w in words)
    kinds = []
    for w in map(fold, words):
        if not surname or not w:
            continue
        if w == surname:
            kinds.append(0)
        elif any(w in g and surname in g for g in groups):
            kinds.append(1)
        elif same_name(w, surname):
            kinds.append(2)
    if kinds:
        return min(kinds), given_too
    return (3, True) if given_too else None


def find(ctx):
    """Every person of every family whose name matches, through the spelling variants
    of the family and the phonetic keys; the closest first."""
    import re

    from probandia import lifecycle
    from probandia.indexes import FamilyIndexes

    words = re.findall(r"[^\W\d_]+", ctx.args.name)
    if not words:
        raise UsageError(_("give a name to find"))
    found = []
    for fid in lifecycle.families(ctx.project):
        if ctx.args.family and fid != ctx.args.family:
            continue
        idx = FamilyIndexes(ctx.project, fid)
        groups = variant_groups(idx.load("variants").get("surnames", {}))
        for p in idx.items("persons"):
            m = _match(words, p, groups)
            if m:
                found.append(((m[0], not m[1], fid, p["id"]), fid, p, MATCHES[m[0]]))
    found.sort(key=lambda x: x[0])
    r = Result("OK", {"QUERY": ctx.args.name, "FOUND": len(found)})
    for _key, fid, p, how in found:
        r.data("person", f"{p['id']} {fid} {how}")
    r.table("persons", [{"person": p["id"], "family": fid, "name": _name(p), "born": _first_date(p, BIRTH),
                         "died": _first_date(p, END), "match": how} for _key, fid, p, how in found])
    if not found:
        r.line(_("nobody of that name in the families of this project"))
    return _listing(r, _n(len(found), _("{n} person found for {name}"), _("{n} persons found for {name}"),
                          name=ctx.args.name))


# person (cli.md 5.7.2)


def person_args(p, common):
    p.add_argument("person", help=_("a person id of a family index, or a unique prefix"))
    p.add_argument("--family", help=_("family slug"))


def find_person(project, ref, family=None):
    """(family, person, persons of that family) for an id or a unique prefix."""
    from probandia import lifecycle
    from probandia.indexes import FamilyIndexes

    every = []
    for fid in lifecycle.families(project):
        if not family or fid == family:
            persons = FamilyIndexes(project, fid).items("persons")
            every += [(fid, p, persons) for p in persons]
    matches = [x for x in every if x[1]["id"] == ref] or [x for x in every if x[1]["id"].startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise UsageError(_("{ref} names several persons: {ids}").format(
            ref=ref, ids=", ".join(x[1]["id"] for x in matches[:5])))
    from probandia.suggest import lines

    raise UsageError(_("no person {ref} in this project; find looks a name up").format(ref=ref),
                     lines=lines(ref, [x[1]["id"] for x in every]))


def _years(person):
    from probandia.proposals import year

    born = [year(f) for f in person.get("facts", []) if f["type"] in BIRTH and year(f) is not None]
    died = [year(f, last=True) for f in person.get("facts", []) if f["type"] in END and year(f) is not None]
    return (min(born) if born else None), (max(died) if died else None)


def person(ctx):
    """A person's file: facts with their sources and their level of proof, relatives,
    and what the family knows around them; a person presumed living is flagged."""
    from probandia import cite, known
    from probandia.indexes import FamilyIndexes
    from probandia.lang.phonetic import fold
    from probandia.report.living import presumed_living

    fid, p, persons = find_person(ctx.project, ctx.args.person, ctx.args.family)
    by_id = {x["id"]: x for x in persons}
    living = presumed_living(p, by_id, ctx.config.get("privacy.living_years") or 100)
    sources = {s["id"]: s for s in FamilyIndexes(ctx.project, fid).items("sources")}
    r = Result("OK", {"PERSON": p["id"], "FAMILY": fid, "NAME": _name(p), "SEX": p.get("sex") or "",
                      "LIVING": living, "FACTS": len(p.get("facts", []))})
    rows = []
    for f in p.get("facts", []):
        s = sources.get(f.get("source"))
        rows.append({"fact": f["type"], "date": known.date_text(f), "place": known.place_text(f),
                     "status": f["status"], "source": f.get("source"),
                     "citation": cite.ensure(dict(s))["citation"] if s else None})
        r.data("fact", f"{f['id']} {f['status']} {f.get('source') or '-'}")
    r.table("facts", rows)
    parents = p.get("parents") or {}
    relatives = [("father", parents.get("father")), ("mother", parents.get("mother"))]
    relatives += [("spouse", s.get("person")) for s in p.get("spouses") or []]
    relatives += [("child", x["id"]) for x in persons
                  if p["id"] in ((x.get("parents") or {}).get("father"), (x.get("parents") or {}).get("mother"))]
    r.table("relatives", [{"relation": rel, "person": pid, "name": _name(by_id[pid]) if pid in by_id else None}
                          for rel, pid in relatives if pid])
    born, died = _years(p)
    window = (born, died if died is not None else born + 100) if born is not None else None
    surname = (p.get("names") or {}).get("surname")
    found = known.known(ctx.project, fid, [surname] if surname else [], (), window, ctx.config)
    full = fold(_name(p))
    r.table("hypotheses", [{"hypothesis": h["id"], "question": h["question"]} for h in found["hypotheses"]
                           if full and full in fold(json.dumps(h, ensure_ascii=False))])
    r.table("negatives", [{"search": s["id"], "state": s["state"], "query": s["query"]} for s in found["negatives"]])
    r.table("gaps", [{"archive": g["archive"], "reference": g.get("reference"),
                      "window": f"{g['window']['from']}-{g['window']['to']}", "kind": g["kind"]}
                     for g in found["gaps"]])
    if living:
        r.line(_("presumed living: {person}; their name and dates stay out of shared outputs").format(person=p["id"]))
    title = _name(p) + (f" ({born or '?'}-{died or '?'})" if born or died else "") + f" · {fid}"
    return _listing(r, title)


# searches, sources, negatives, hypotheses, gaps (cli.md 5.7.4, 5.7.5)

INDEX_LISTS = ("searches", "sources", "negatives", "hypotheses", "gaps")


def index_args(name):
    def configure(p, common):
        p.add_argument("--family", help=_("family slug"))
        p.add_argument("--person", help=_("only what concerns this person (an id or a unique prefix)"))
        if name == "searches":
            p.add_argument("--engine", help=_("only the searches of this engine or archive"))
            p.add_argument("--since", metavar="<date>", help=_("only what happened since this date (YYYY-MM-DD)"))
        p.set_defaults(listing=name)
    return configure


def _overlaps(window, span):
    return not span or not window or (window[0] <= span[1] and span[0] <= window[1])


def _rows(ctx, name, fid, who):
    """The rows of one family for the listing ``name``; ``who`` is (person, persons) or None."""
    from probandia import cite, known
    from probandia.indexes import FamilyIndexes
    from probandia.lang.phonetic import fold, same_name

    idx = FamilyIndexes(ctx.project, fid)
    span = None
    if who:
        born, died = _years(who)
        span = (born, died if died is not None else born + 100) if born is not None else None
    surname = ((who or {}).get("names") or {}).get("surname") or ""

    def about(search):
        if not who:
            return True
        words = re.findall(r"[^\W\d_]+", search.get("query") or "") + list(search.get("variants") or [])
        w = search.get("window") or {}
        return any(same_name(x, surname) for x in words) and \
            _overlaps((w.get("from"), w.get("to")) if w.get("from") is not None else None, span)

    if name == "searches":
        since = _since(ctx.args.since)
        return [{"search": s["id"], "family": fid, "date": s["ts"][:10], "engine": s.get("engine") or s["kind"],
                 "query": s.get("query"), "result": s.get("result"), "results": s.get("results")}
                for s in idx.items("searches") if about(s)
                and (not ctx.args.engine or ctx.args.engine in (s.get("engine"), s.get("kind")))
                and (not since or s["ts"][:10] >= since)]
    if name == "negatives":
        return [{"search": s["id"], "family": fid, "state": s["state"], "query": s["query"],
                 "engine": s.get("engine") or s["kind"],
                 "window": f"{(s.get('window') or {}).get('from', '?')}-{(s.get('window') or {}).get('to', '?')}"}
                for s in known.known(ctx.project, fid, config=ctx.config)["negatives"] if about(s)]
    if name == "sources":
        cited = {f.get("source") for f in who.get("facts", [])} if who else None
        return [{"source": s["id"], "family": fid, "citation": cite.ensure(dict(s))["citation"],
                 "accessed": s.get("accessed"), "rights": s.get("rights")}
                for s in idx.items("sources") if cited is None or s["id"] in cited]
    if name == "hypotheses":
        full = fold(_name(who)) if who else ""
        return [{"hypothesis": h["id"], "family": fid, "question": h["question"],
                 "state": "closed" if h.get("closed") else "open", "opened": h.get("opened")}
                for h in idx.items("hypotheses") if not full or full in fold(json.dumps(h, ensure_ascii=False))]
    return [{"archive": g["archive"], "family": fid, "reference": g.get("reference"),
             "window": f"{g['window']['from']}-{g['window']['to']}", "kind": g["kind"], "cause": g.get("source")}
            for g in idx.items("gaps") if _overlaps((g["window"]["from"], g["window"]["to"]), span)]


INDEX_TITLES = {"searches": (N_("{n} search"), N_("{n} searches")),
                "sources": (N_("{n} source"), N_("{n} sources")),
                "negatives": (N_("{n} negative"), N_("{n} negatives")),
                "hypotheses": (N_("{n} hypothesis"), N_("{n} hypotheses")),
                "gaps": (N_("{n} gap"), N_("{n} gaps"))}


def index_list(ctx):
    """What the families already know, one index at a time, filtered."""
    from probandia import lifecycle

    name, who, family = ctx.args.listing, None, ctx.args.family
    if ctx.args.person:
        family, who, _persons = find_person(ctx.project, ctx.args.person, family)
    rows = []
    for fid in lifecycle.families(ctx.project):
        if not family or fid == family:
            rows += _rows(ctx, name, fid, who)
    r = Result("OK", {name.upper(): len(rows)})
    item = {"searches": "search", "sources": "source", "negatives": "negative", "hypotheses": "hypothesis",
            "gaps": "gap"}[name]
    for x in rows:
        r.data(item, " ".join(str(v) for k, v in x.items() if v not in (None, "") and k != "family"))
    r.table(name, rows)
    one, many = INDEX_TITLES[name]
    title = _n(len(rows), _(one), _(many))
    if who:
        title += " · " + _name(who)
    return _listing(r, title)


# proposals (cli.md 5.8.1 to 5.8.3)


def proposals_args(p, common):
    p.add_argument("action", nargs="?", default="list", choices=("list", "show", "apply", "drop"))
    p.add_argument("proposal", nargs="?", help=_("the proposal id"))
    p.add_argument("--research", help=_("research id or unique prefix"))
    p.add_argument("--reason", help=_("drop: why the proposal is set aside"))


def proposals(ctx):
    """The proposals waiting, one at a time, then accepted or set aside with a reason,
    by the engine's own apply, under the role of the session (PRD M-4)."""
    from probandia.cli import asking, data_cmd

    action = ctx.args.action
    if action == "list":
        return proposals_list(ctx)
    if not ctx.args.proposal:
        raise UsageError(_("proposals {action} needs a proposal id").format(action=action))
    if action == "show":
        return proposal_show(ctx)
    ctx.args.drop = None
    if action == "drop":
        if not (ctx.args.reason or "").strip():
            raise UsageError(_("say why the proposal is dropped"), values={"REASON": "no-reason"})
        if not asking.confirm(ctx, _("Set the proposal {proposal} aside?").format(proposal=ctx.args.proposal)):
            return asking.declined({"PROPOSAL": ctx.args.proposal})
        ctx.args.drop = ctx.args.reason
    return data_cmd.apply(ctx)


def _verdict(lines):
    return next((x.split()[0].split("=")[1] for x in lines if x.startswith("verdict=")), "unknown")


def proposals_list(ctx):
    from probandia.cli.data_cmd import summary
    from probandia.proposals import pending, proposals_folder
    from probandia.research import all_researches, find_research
    from probandia.util import yamlio
    import os

    chosen = [find_research(ctx.project, ctx.args.research, ctx.environ)] if ctx.args.research else all_researches(ctx.project)
    rows = []
    r = Result("OK")
    for res in chosen:
        for pid in pending(res):
            doc = yamlio.load(os.path.join(proposals_folder(res), f"{pid}.yaml"))
            lines = summary(ctx, res, doc)
            for line in lines:
                r.data("proposal", f"{pid} {line}")
            facts = list(doc.get("facts", [])) + [f for p in doc.get("persons", []) for f in p.get("facts", [])]
            rows.append({"proposal": pid, "research": res.id, "pass": doc.get("pass"),
                         "author": (doc.get("author") or {}).get("agent"), "facts": len(facts),
                         "persons": len(doc.get("persons", [])), "sources": len(doc.get("sources", [])),
                         "verdict": _verdict(lines)})
    r.set("PROPOSALS", len(rows))
    r.table("proposals", rows)
    if rows:
        r.line(_("read one with: probandia proposals show <proposal>"))
    return _listing(r, _n(len(rows), _("{n} proposal waiting"), _("{n} proposals waiting")))


def proposal_show(ctx):
    """A proposal in clear: its facts, sources and searches, and the rules of apply."""
    import copy

    from probandia import known, proposals
    from probandia.indexes import FamilyIndexes
    from probandia.util import yamlio

    res, path = proposals.find_proposal(ctx.project, ctx.args.proposal)
    doc = yamlio.load(path)
    try:
        before = FamilyIndexes(ctx.project, res.family).load_all()   # read once: a copy becomes the family after
        docs, _touched, reasons, warnings = proposals.check(ctx.project, res, doc, ctx.config,
                                                            docs=copy.deepcopy(before))
    except Exception as err:   # noqa: BLE001 — the reading still shows the content
        docs, reasons, warnings = None, [f"{type(err).__name__}: {err}"], []
    facts = list(doc.get("facts", [])) + [f for p in doc.get("persons", []) for f in p.get("facts", [])]
    r = Result("WARN" if reasons else "OK",
               {"PROPOSAL": doc["id"], "RESEARCH": res.id, "PASS": doc.get("pass"),
                "AUTHOR": (doc.get("author") or {}).get("agent", ""), "VERDICT": "would-reject" if reasons
                else "would-apply", "REASONS": len(reasons)})
    for x in reasons:
        r.data("reason", x)
    r.table("persons", [{"person": p["id"], "name": _name(p)} for p in doc.get("persons", [])])
    r.table("facts", [{"fact": f["id"], "date": known.date_text(f), "place": known.place_text(f),
                       "status": f.get("status"), "source": f.get("source")} for f in facts])
    r.table("sources", [{"source": s["id"], "citation": s.get("citation") or s.get("repository")}
                        for s in doc.get("sources", [])])
    r.table("searches", [{"search": s.get("id"), "engine": s.get("engine") or s.get("kind"),
                          "query": s.get("query"), "result": s.get("result")} for s in doc.get("searches", [])])
    r.table("rules", [{"rule": x.split(":", 1)[0] if x[:2] == "P-" else "", "reason": x} for x in reasons])
    r.table("changes", proposals.changes(before, docs) if docs else [])
    r.lines += warnings
    r.line(_("apply would refuse it: {n} reason(s)").format(n=len(reasons)) if reasons
           else _("every rule of apply passes; accept it with: probandia proposals apply {proposal}").format(
               proposal=doc["id"]))
    return _listing(r, _("Proposal {proposal} · {research}, pass {n}").format(
        proposal=doc["id"], research=res.id, n=doc.get("pass")))
