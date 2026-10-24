"""Readable layouts of the commands a person reads often (cli.md § 5, CLI5).

Each layout takes the ``Result`` its command returns, the same one the contract
prints, and lays it out for the eye: it reads the tables and ``Result.extra``,
never the files. A command without a layout here falls back on the generic one
of ``cli.human``.
"""
import datetime
import textwrap

from probandia.cli import human as h
from probandia.i18n import N_, _


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _when(ts):
    """``2026-09-01T10:00:00Z`` -> ``31 d ago``; ``—`` when there is no date."""
    from probandia.i18n import formats

    if not ts:
        return "—"
    try:
        when = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return formats.relative(when, _now())


def _head(result, style, text):
    """The first line: the status symbol, then what the screen is about."""
    return h.mark(result.status, style) + " " + style.bold(text)


def _messages(result):
    """The lines that are messages, not ``key=value`` data."""
    return [line for line in result.lines if not h.DATA_LINE.match(line)]


def _plural(n, one, many):
    return (one if n == 1 else many).format(n=n)


# status (5.6.1)

RESEARCH_STATUSES = {"open": N_("open"), "paused": N_("paused"), "closed": N_("closed")}


def render_status(result, style):
    v, t = result.values, result.tables
    fams, ress, locks = (t.get(n, {}).get("rows", []) for n in ("families", "researches", "locks"))
    head = " · ".join([_plural(v["FAMILIES"], _("{n} family"), _("{n} families")),
                       _plural(v["RESEARCHES"], _("{n} research"), _("{n} researches")),
                       _plural(v["LOCKS"], _("{n} lock held"), _("{n} locks held")) if v["LOCKS"]
                       else _("no lock held")])
    out = [_head(result, style, head)]
    if fams:
        out += h.section(_("Families"), style)
        out += h.table(["family", "researches"], fams, style,
                       {"family": _("family"), "researches": _("researches")})
    if ress:
        rows = [{"research": x["research"], "status": _(RESEARCH_STATUSES.get(x["status"], x["status"])),
                 "passes": (_("pass {n} open").format(n=x["open_pass"]) if x["open_pass"]
                            else _plural(x["passes"] or 0, _("{n} pass"), _("{n} passes"))),
                 "mode": x["mode"], "language": x["language"], "last": _when(x["last_activity"]),
                 "standard": (_("{conform}/{n} conform").format(conform=x["standard"]["conform"],
                                                               n=sum(x["standard"].values()))
                              if x.get("standard") else "")}
                for x in ress]
        columns = ["research", "status", "passes", "mode", "language", "last"]
        if any(x.get("standard") for x in ress):   # GPS8: the questions that conform to the GPS
            columns.append("standard")
        out += h.section(_("Researches"), style)
        out += h.table(columns, rows, style,
                       {"research": _("research"), "status": _("status"), "passes": _("passes"),
                        "mode": _("mode"), "language": _("language"), "last": _("last activity"),
                        "standard": _("GPS")})
    opened = [x for x in ress if x["open_pass"]]
    if opened:
        out += h.section(_("Open passes"), style)
        out += [f"  {h.mark('WARN', style)} " + _("{research}: pass {n}, opened {when}").format(
            research=x["research"], n=x["open_pass"], when=_when(x["open_since"])) for x in opened]
    if locks:
        out += h.section(_("Locks"), style)
        locks = [dict(x, expires=_when(x["expires"])) for x in locks]
        out += h.table(["scope", "holder", "expires"], locks, style,
                       {"scope": _("scope"), "holder": _("holder"), "expires": _("until")})
    tokens = t.get("tokens", {}).get("rows", [])
    if "TOKENS_PASS" in v:
        out += h.section(_("Tokens of pass {n}, by role").format(n=v["TOKENS_PASS"]), style)
        out += (h.table(["role", "input", "output", "cache_read", "cache_write", "weighted"], tokens, style)
                if tokens else ["  " + _("no tokens measured")])
    low = t.get("lowest_accounts", {}).get("rows", [])
    if low:
        out += h.section(_("Lowest accounts"), style)
        out += h.table(["account", "left", "pays for"], low, style,
                       {"account": _("account"), "left": _("left"), "pays for": _("pays for")})
        out += ["", h.next_step("probandia -u", style) + style.dim("  " + _("every free quota"))]
    out += h.bullets(_messages(result), style)
    return "\n".join(out) + "\n"


# doctor (5.13.1)


def _check(status, text, style):
    return f"  {h.mark(status, style)} {text}"


# the support levels of harness.CAPABILITIES, as a person reads them (T114)
SUPPORT = {"first-class": N_("first-class"), "beta": N_("beta"), "reduced": N_("reduced"), "none": N_("none")}


def render_doctor(result, style):
    v, x = result.values, result.extra
    worst = result.status
    head = {"OK": _("Probandia is ready"), "WARN": _("Probandia works; a few things to look at"),
            "FAIL": _("Probandia cannot run here")}.get(worst, _("Probandia"))
    out = [_head(result, style, head)]
    ok_python = not any(line == _("Python 3.11 or later is required") for line in result.lines)
    out += h.section(_("Python"), style)
    out.append(_check("OK" if ok_python else "FAIL", "Python " + v["PYTHON"] + (
        "" if ok_python else " · " + _("Python 3.11 or later is required")), style))
    if v.get("PYTHON_PATH"):
        out.append("    " + style.dim(v["PYTHON_PATH"] + " · " + _("agents may run another Python: "
                                                                "run doctor from your agent to see theirs")))
    out += h.section(_("Harness"), style)
    caps = x["caps"]
    if v["HARNESS"] == "cli":
        out.append(_check("WARN", _("no harness detected: pass --harness, or run doctor from your agent"), style))
    else:
        out.append(_check("OK", _("{harness} (found by {how}), support: {support}").format(
            harness=v["HARNESS"], how=v["DETECTED_BY"], support=_(SUPPORT.get(v["SUPPORT"], v["SUPPORT"]))), style))
        yes, no = _("yes"), _("no")
        out += h.pairs([(_("web search"), caps["web_search"] or no),
                        (_("subagents"), yes if caps["subagents"] else no),
                        (_("question tool"), caps["question"] or no),
                        (_("messages between agents"), caps["messaging"] or no),
                        (_("hooks"), yes if caps["hooks"] else no),
                        (_("MCP server"), yes if caps["mcp"] else no),
                        (_("effort levels"), ", ".join(caps["efforts"]) or no)], style, indent=4)
        out += [_check("WARN", m, style) for m in x["degraded"]]
    out += h.section(_("Keys"), style)
    if x["keys"]:
        text = _("{n} set: {names}").format(n=len(x["keys"]), names=", ".join(x["keys"]))
        lines = textwrap.wrap(text, style.width - 4, break_long_words=False, break_on_hyphens=False)
        out.append(_check("OK", lines[0], style))
        out += ["    " + line for line in lines[1:]]
    else:
        out.append(_check("WARN", _("no key set: only the providers without a key can be used"), style))
    if v["KEYS_MISSING"]:
        out.append("    " + style.dim(_("{n} other keys not set; probandia -u shows what each one adds").format(
            n=v["KEYS_MISSING"])))
    for env, (ids, present) in x["shared"].items():
        out.append("    " + style.dim(_("{key}: one key for {count} entries ({names}), {state}").format(
            key=env, count=len(ids), names=", ".join(ids), state=_("present") if present else _("missing"))))
    for path in x["env_files"]:
        out.append("    " + style.dim(_("keys read from {path}").format(path=path)))
    if x["user_env"]:
        out.append("    " + style.dim(_("no .env file: keys can go in {path}, or in .env at the root of a project")
                                      .format(path=x["user_env"])))
    out += h.section(_("Optional tools"), style)
    tools = result.tables["tools"]["rows"]
    w = max(len(t["tool"]) for t in tools)
    for t in tools:
        out.append(_check("OK" if t["installed"] else "WARN", f"{t['tool']:{w}}  " + style.dim(t["purpose"]), style))
        for n, way in enumerate(t["install"]):
            for k, command in enumerate(way.split(" && ")):
                label = _("then:") if k else _("install:") if n == 0 else _("or:")
                out.append(" " * (w + 6) + style.dim(label) + " " + command)
    out += h.section(_("Free-tier catalogue"), style)
    if v["CATALOGUE"] == "absent":
        out.append(_check("FAIL", _("the free-tier catalogue is not installed"), style))
    else:
        out.append(_check("WARN" if x["old"] else "OK", _("{n} entries, the oldest checked {days} days ago").format(
            n=v["CATALOGUE"], days=v["CATALOGUE_OLDEST_DAYS"]), style))
        if x["old"]:
            out.append("    " + _("older than {days} days: {names}").format(days=x.get("days", 90),
                                                                             names=", ".join(x["old"])))
    return "\n".join(out) + "\n"


# verify (5.6.5)

RULE_MARKS = {"PASS": "OK", "WARN": "WARN", "FAIL": "FAIL"}


def render_verify(result, style):
    from probandia.verify import FIXES, TITLES

    v = result.values
    rules = result.tables["rules"]["rows"]
    head = (_("{failed} of {n} rules failed").format(failed=v["FAILED"], n=v["RULES"]) if v["FAILED"]
            else _("{n} rules passed").format(n=v["RULES"]))
    out = [_head(result, style, head + " · " + v["RESEARCH"]), ""]
    w = max(len(x["rule"]) for x in rules) if rules else 4
    for x in rules:
        detail = x["detail"] if x["status"] == "PASS" and x["detail"] else ""
        line = f"  {h.mark(RULE_MARKS.get(x['status'], 'WARN'), style)} {x['rule']:{w}}  {_(TITLES[x['rule']])}"
        out.append(line + (style.dim(" · " + detail) if detail else ""))
    for x in rules:
        if x["status"] == "PASS":
            continue
        out += h.section(f"{x['rule']} · {_(TITLES[x['rule']])}", style)
        if x["detail"]:
            out += _wrapped(_("concerned: {what}").format(what=x["detail"]), style)
        out += _wrapped(_("to correct: {fix}").format(fix=_(FIXES[x["rule"]])), style)
    ids = tuple(x["rule"] + "=" for x in rules)
    out += h.bullets([m for m in _messages(result) if not m.startswith(ids)], style)
    return "\n".join(out) + "\n"


def _wrapped(text, style, indent=4):
    return [" " * indent + line for line in textwrap.wrap(text, style.width - indent, break_long_words=False,
                                                          break_on_hyphens=False)]


# config (5.12.1 to 5.12.3)

# One colour per layer, lowest first; the name is always written beside it.
LAYER_COLORS = {"default": "2", "harness": "35", "user": "36", "project": "32", "local": "33", "env": "34",
                "arg": "1"}
LAYER_LABELS = {"default": N_("default"), "harness": N_("harness"), "user": N_("user"),
                "project": N_("project"), "local": N_("local"), "env": N_("environment"), "arg": N_("argument")}


def _layer(name, style):
    return style.paint(_(LAYER_LABELS.get(name, name)), LAYER_COLORS.get(name, "0"))


def render_config_show(result, style):
    v = result.values
    rows = result.tables["settings"]["rows"]
    head = _("{n} settings · grade {grade}").format(n=v["COUNT"], grade=v["GRADE"])
    if v["SHOWN"] != v["GRADE"]:
        head += " · " + _("shown: {shown}").format(shown=v["SHOWN"])
    out = [_head(result, style, head)]
    out += h.bullets(_messages(result), style, symbol="WARN") if result.status == "WARN" else []
    if rows:
        wk = min(34, max(len(x["key"]) for x in rows))
        wv = min(24, max(len(x["value"]) for x in rows))
        wl = max(len(_(LAYER_LABELS.get(x["layer"], x["layer"]))) for x in rows)
        out += ["", style.dim(f"  {_('setting'):{wk}}  {_('value'):{wv}}  {_('from'):{wl}}  {_('what it does')}")]
        for x in rows:
            label = _(LAYER_LABELS.get(x["layer"], x["layer"]))
            mark = " " + style.paint("↑", "33") if x["above_grade"] and not style.plain else (
                " ^" if x["above_grade"] else "")
            text = (f"  {h.cut(x['key'], wk, style):{wk}}  {h.cut(x['value'], wv, style):{wv}}  "
                    + _layer(x["layer"], style) + " " * (wl - len(label) + 2))
            room = style.width - (wk + wv + wl + 8)
            out.append(text + style.dim(h.cut(x["help"], max(10, room), style)) + mark)
        out += ["", style.dim(_("from:")) + " " + " < ".join(_layer(layer, style) for layer in LAYER_COLORS)
                + style.dim("  · " + _("a higher layer wins"))]
        if any(x["above_grade"] for x in rows):
            out.append(style.dim(_("^ set above your grade: it takes effect anyway") if style.plain
                                 else _("↑ set above your grade: it takes effect anyway")))
    else:
        out += ["", "  " + _("nothing set here")]
    out += ["", h.next_step("probandia config explain <setting>", style)]
    return "\n".join(out) + "\n"


def render_config_diff(result, style):
    rows = result.tables["diff"]["rows"]
    if not rows:
        return _head(result, style, _("Every setting has its default value")) + "\n"
    out = [_head(result, style, _plural(len(rows), _("{n} setting differs from its default"),
                                        _("{n} settings differ from their default")))]
    wk = max(len(x["key"]) for x in rows)
    wv = min(28, max(len(x["value"]) for x in rows))
    last = None
    for x in rows:
        if x["layer"] != last:
            out += ["", "  " + _layer(x["layer"], style) + style.dim(f"  {x['source']}")]
            last = x["layer"]
        out.append(f"    {x['key']:{wk}}  {h.cut(x['value'], wv, style):{wv}}  "
                   + style.dim(_("default: {value}").format(value=x["default"])))
    return "\n".join(out) + "\n"


def render_config_explain(result, style):
    v = result.values
    out = [_head(result, style, v["KEY"])]
    out += _wrapped(_messages(result)[0] if _messages(result) else "", style, indent=2)
    origin = v["ORIGIN"].split(" ", 1)
    out += [""] + h.pairs([(_("value"), v["VALUE"]), (_("from"), " ".join([_(LAYER_LABELS.get(
        origin[0], origin[0]))] + origin[1:])), (_("default"), v["DEFAULT"]), (_("allowed"), v["VALUES"]),
        (_("type"), v["TYPE"]), (_("grade"), v["GRADE"]), (_("variable"), v["ENV"]),
        (_("option"), v["FLAG"] or "—"), (_("in the harness"), v["HARNESS"] or "—")], style)
    out += h.bullets(_messages(result)[1:], style)
    return "\n".join(out) + "\n"


def render_config_path(result, style):
    rows = result.tables["layers"]["rows"]
    out = [_head(result, style, _("Where the settings come from, lowest layer first"))]
    w = max(len(_(LAYER_LABELS[x["layer"]])) for x in rows)
    out.append("")
    for n, x in enumerate(rows, start=1):
        label = _(LAYER_LABELS[x["layer"]])
        sym = h.mark("OK", style) if x["present"] else style.dim("·")
        out.append(f"  {n}. {sym} " + _layer(x["layer"], style) + " " * (w - len(label) + 2)
                   + (x["where"] if x["present"] else style.dim(x["where"])))
    out += ["", style.dim(_("a higher layer wins; ✓ marks a layer that sets something here") if not style.plain
                          else _("a higher layer wins; [ok] marks a layer that sets something here"))]
    return "\n".join(out) + "\n"


# known (5.7.3)

FACT_STATUSES = {"record": N_("record"), "index": N_("index"), "hypothesis": N_("hypothesis"),
                 "proven": N_("proven"), "probable": N_("probable"), "possible": N_("possible")}


def render_known(result, style):
    v, t = result.values, result.tables
    head = " · ".join([_plural(v["FACTS"], _("{n} fact"), _("{n} facts")),
                       _plural(v["NEGATIVES"], _("{n} negative"), _("{n} negatives")),
                       _plural(v["HYPOTHESES"], _("{n} open hypothesis"), _("{n} open hypotheses")),
                       _plural(v["GAPS"], _("{n} gap"), _("{n} gaps"))])
    out = [_head(result, style, _("Family {family}").format(family=v["FAMILY"]) + " · " + head)]
    facts = t["facts"]["rows"]
    if facts:
        rows, last = [], None
        for f in facts:   # the person once, at the first of their facts
            rows.append(dict(f, person=f["person"] if f["person"] != last else " ",
                             status=_(FACT_STATUSES.get(f["status"], f["status"]))))
            last = f["person"]
        out += h.section(_("Facts"), style)
        out += h.table(["person", "fact", "date", "place", "status", "source"], rows, style,
                       {"person": _("person"), "fact": _("fact"), "date": _("date"), "place": _("place"),
                        "status": _("status"), "source": _("source")})
    negs = t["negatives"]["rows"]
    if negs:
        out += h.section(_("Negatives"), style)
        rows = [dict(x, state=_("to check again") if x["state"] == "due" else _("valid")) for x in negs]
        out += h.table(["search", "state", "query", "engine", "window"], rows, style,
                       {"search": _("search"), "state": _("state"), "query": _("query"), "engine": _("engine"),
                        "window": _("window")})
        if v["NEGATIVES_DUE"]:
            out.append(f"  {h.mark('WARN', style)} " + _plural(
                v["NEGATIVES_DUE"], _("{n} negative to check again before relying on it"),
                _("{n} negatives to check again before relying on them")))
    if t["hypotheses"]["rows"]:
        out += h.section(_("Open hypotheses"), style)
        out += h.table(["hypothesis", "question"], t["hypotheses"]["rows"], style,
                       {"hypothesis": _("hypothesis"), "question": _("question")})
    if t["gaps"]["rows"]:
        out += h.section(_("Gaps in the archives"), style)
        out += h.table(["archive", "reference", "window", "kind"], t["gaps"]["rows"], style,
                       {"archive": _("archive"), "reference": _("reference"), "window": _("window"),
                        "kind": _("kind")})
    return "\n".join(out) + "\n"


# export (5.9.7) and import-gedcom (5.9.8)


def render_export(result, style):
    v, x = result.values, result.extra
    path = next((line.split("=", 1)[1] for line in result.lines if line.startswith("FILE=")), "")
    out = [_head(result, style, _("Exported to {path}").format(path=path))]
    out += [""] + h.pairs([(_("format"), v["FORMAT"]), (_("family"), v["FAMILY"]), (_("persons"), v["PERSONS"]),
                           (_("families"), v["FAMILIES"]), (_("sources"), v["SOURCES"]), (_("media"), v["MEDIA"])],
                          style)
    if x["living"]:
        text = (_plural(x["living"], _("{n} presumed-living person masked: name and dates left out"),
                        _("{n} presumed-living persons masked: names and dates left out"))
                if v["LIVING"] == "mask" else
                _plural(x["living"], _("{n} presumed-living person left out of the file"),
                        _("{n} presumed-living persons left out of the file")))
        out += ["", f"  {h.mark('OK', style)} " + text]
    out += ["", h.next_step("probandia export {format} --open-folder".format(format=v["FORMAT"]), style)
            + style.dim("  " + _("opens {folder}").format(folder=x["folder"]))]
    return "\n".join(out) + "\n"


def render_import_gedcom(result, style):
    v = result.values
    out = [_head(result, style, _("{n} persons read from the file ({version}), {m} matching the family").format(
        n=v["PERSONS"], version=v["VERSION"], m=v["MATCHED"]))]
    out += ["", "  " + _("staged in {path}").format(path=result.details)]
    rows = result.tables["proposals"]["rows"]
    rows = [dict(x, proposal=x["proposal"] if n == 0 or rows[n - 1]["proposal"] != x["proposal"] else " ")
            for n, x in enumerate(rows)]
    if rows:
        out += h.section(_plural(v["PROPOSALS"], _("To review: {n} proposal"), _("To review: {n} proposals")), style)
        out += h.table(["proposal", "person", "why"], rows, style,
                       {"proposal": _("proposal"), "person": _("person"), "why": _("why")})
    out += [""] + h.bullets([m for m in _messages(result)], style, symbol="WARN" if result.status == "WARN" else None)
    if rows:
        out += ["", h.next_step("probandia apply <proposal>", style)]
    return "\n".join(out) + "\n"


# library (5.14.1)

LEVELS = {"draft": N_("draft"), "tested": N_("tested"), "trusted": N_("trusted"), "recipe": N_("recipe")}


def render_library(result, style):
    rows = result.tables["scripts"]["rows"]
    out = [_head(result, style, _plural(len(rows), _("{n} learned script"), _("{n} learned scripts")))]
    if not rows:
        out += ["", "  " + _("nothing in the library yet: agents save the scripts they write, with a witness")]
        return "\n".join(out) + "\n"
    shown = [dict(x, level=_(LEVELS.get(x["level"], x["level"])), witness=x["witness"],
                  last_run=_when(x["last_run"]) if x["last_run"] else _("never")) for x in rows]
    out.append("")
    out += h.table(["script", "level", "kind", "version", "witness", "runs", "last_run", "purpose"], shown, style,
                   {"script": _("script"), "level": _("level"), "kind": _("kind"), "version": _("version"),
                    "witness": _("witness"), "runs": _("runs ok"), "last_run": _("last run"),
                    "purpose": _("what it does")})
    if any(x["level"] == "draft" for x in rows):
        out += ["", f"  {h.mark('WARN', style)} " + _("a draft runs only after the user agrees; "
                                                      "library test checks it against its witness")]
    return "\n".join(out) + "\n"


# The genealogist's tools (5.10.1 to 5.10.7)

CALENDARS = {"gregorian": N_("Gregorian calendar"), "julian": N_("Julian calendar"),
             "republican": N_("French Republican calendar")}
QUALIFIERS = {"exact": N_("exact"), "about": N_("about"), "before": N_("before"), "after": N_("after"),
              "between": N_("between"), "estimated": N_("estimated"), "calculated": N_("calculated")}


def render_dates(result, style):
    from probandia.i18n import formats

    v = result.values
    if "END" in v:
        when = _("between {start} and {end}").format(start=formats.long_date(v["ISO"]),
                                                    end=formats.long_date(v["END"]))
    else:
        when = formats.long_date(v["ISO"])
        if v["QUALIFIER"] not in ("exact", "between"):
            when = _(QUALIFIERS.get(v["QUALIFIER"], v["QUALIFIER"])) + " " + when
    out = [_head(result, style, f"{v['ORIGINAL']}  →  {when}" if not style.plain
                 else f"{v['ORIGINAL']}  ->  {when}")]
    out += [""] + h.pairs([(_("ISO date"), v["ISO"] + (" / " + v["END"] if "END" in v else "")),
                           (_("qualifier"), _(QUALIFIERS.get(v["QUALIFIER"], v["QUALIFIER"]))),
                           (_("read in"), _(CALENDARS.get(v["CALENDAR"], v["CALENDAR"])))], style)
    return "\n".join(out) + "\n"


VARIANT_KINDS = {"attested": N_("Attested in the family"), "particle": N_("With or without the particle"),
                 "scribal": N_("Spellings of the scribes"),
                 "paleo": N_("Misreadings of the handwriting"), "phonetic": N_("Same sound")}


def render_variants(result, style):
    v, t = result.values, result.tables
    out = [_head(result, style, _("{n} forms of {surname}").format(n=v["FORMS"], surname=v["SURNAME"]))]
    kinds = list(dict.fromkeys(x["kind"] for x in t["forms"]["rows"]))
    for kind in kinds:
        forms = [x["form"] for x in t["forms"]["rows"] if x["kind"] == kind]
        out += h.section(_(VARIANT_KINDS.get(kind, kind)), style)
        out += _wrapped(", ".join(forms), style, indent=2)
    if "given" in t:
        out += h.section(_("Forms of the given name"), style)
        langs = list(dict.fromkeys(x["language"] for x in t["given"]["rows"]))
        out += h.pairs([(lang, ", ".join(x["form"] for x in t["given"]["rows"] if x["language"] == lang))
                        for lang in langs], style)
    return "\n".join(out) + "\n"


def render_places(result, style):
    v = result.values
    rows = result.tables.get("places", {}).get("rows", [])
    if result.status == "ASK":
        head = _("{n} places answer to {name}: which one?").format(n=len(rows), name=v["NAME"])
    elif rows:
        head = (v["AS_OF"] if v["AS_OF"] == v["NAME"] else f"{v['NAME']}  →  {v['AS_OF']}") + (
            " · " + _("today {name}").format(name=v["CURRENT"]) if v["CURRENT"] != v["AS_OF"] else "")
    else:
        head = _("no place found under {name}").format(name=v["NAME"])
    out = [_head(result, style, head)]
    if rows:
        out.append("")
        out += h.table(["place", "name", "current", "codes"], rows, style,
                       {"place": _("id"), "name": _("name then"), "current": _("name today"), "codes": _("codes")})
    notes = [m for m in _messages(result) if m != _("no place found under this name")]
    if notes:
        out.append("")
        out += h.bullets(notes, style)
    if result.status == "ASK":
        out += ["", h.next_step(f"probandia places \"{v['NAME']}\" --choice <id>", style)]
    return "\n".join(out) + "\n"


def render_place_guide(result, style):
    v, t = result.values, result.tables
    head = _("Locality guide of {place}").format(place=v["PLACE"])
    if v.get("COPIED_FROM"):
        head += " · " + _("copied from {family}").format(family=v["COPIED_FROM"])
    out = [_head(result, style, head)]
    rows = t.get("jurisdictions", {}).get("rows", [])
    if rows:
        out += h.section(_("Jurisdictions"), style)
        shown = [dict(x, period=f"{x['from'] or '…'} – {x['to'] or '…'}",
                      source=x["source"] + (" (" + _("derived") + ")" if x["derived"] else "")) for x in rows]
        out += h.table(["level", "name", "period", "source"], shown, style,
                       {"level": _("level"), "name": _("name"), "period": _("period"), "source": _("source")})
    rows = t.get("repositories", {}).get("rows", [])
    if rows:   # T67: those of the window only, when one is given or planned
        out += h.section(_("Repositories") + (f" ({v['WINDOW']})" if v.get("WINDOW") else ""), style)
        out += h.table(["name", "holdings", "note"], rows, style,
                       {"name": _("repository"), "holdings": _("holdings"), "note": _("note")})
    notes = [m for m in _messages(result) if not m.startswith(_("next: apply {id}").split("{")[0])]
    if notes:
        out.append("")
        out += h.bullets(notes, style)
    if v.get("PROPOSAL"):
        out += ["", h.next_step(f"probandia apply {v['PROPOSAL']}", style)]
    return "\n".join(out) + "\n"


def render_cite(result, style):
    v = result.values
    out = [_head(result, style, _("Citation of {source}").format(source=v["SOURCE"]) if "SOURCE" in v
                 else _("Citation"))]
    if "FULL" in v:
        for label, key in ((_("List of sources"), "FULL"), (_("First note"), "CITATION"),
                           (_("Short note"), "SHORT")):
            out += h.section(label, style) + _wrapped(v[key], style, indent=2)
    else:
        out += [""] + _wrapped(v["CITATION"], style, indent=2)
    copied = (result.extra or {}).get("copied")
    if copied:
        out += ["", f"  {h.mark('OK', style)} " + _("copied to the clipboard ({tool})").format(tool=copied)]
    out += h.bullets(_messages(result), style, symbol="WARN") if _messages(result) else []
    return "\n".join(out) + "\n"


def _cost(units, unit):
    from probandia.i18n import formats

    if not units:
        return _("free")
    if unit == "dollar":
        return formats.money(units)
    return (_("{n} unit") if units == 1 else _("{n} units")).format(n=formats.number(units))


def render_search(result, style):
    v, t = result.values, result.tables
    out = [_head(result, style, _plural(v["RESULTS"], _("{n} result"), _("{n} results")) + " · " + _(
        "cost: {cost}").format(cost=_cost(float(v["UNITS"]), None)))]
    out += h.section(_("Engines"), style)
    for e in t["engines"]["rows"]:
        if e["failure"]:
            text = f"{e['name']}: " + _("not used ({why})").format(why=e["failure"])
            out.append(f"  {h.mark('WARN', style)} " + text)
        else:
            out.append(f"  {h.mark('OK', style)} " + _("{name}: {n} results, {cost}").format(
                name=e["name"], n=e["results"], cost=_cost(e["units"], e["unit"])))
    rows = t["results"]["rows"]
    if rows:
        out += h.section(_("Results"), style)
        for n, x in enumerate(rows, start=1):
            out.append(f"  {n:>2}. " + style.bold(h.cut(x["title"] or x["url"], style.width - 6, style)))
            out.append("      " + style.dim(h.cut(x["url"], style.width - 6, style) + "  · " + x["engines"]))
            if x.get("snippet") and x["snippet"] != x["title"]:   # T66: what the provider quoted of the page
                out.append("      " + h.cut(x["snippet"], style.width - 6, style))
    if "SEARCH" in v:
        out += ["", style.dim(_("written to the search log: {id}").format(id=v["SEARCH"]))]
    return "\n".join(out) + "\n"


STEP_LABELS = {"cache": N_("the cache"), "api": N_("an archive API"), "http": N_("a plain download"),
               "extract": N_("the text of the page"), "reader": N_("a reading service"),
               "browser": N_("the headless browser"), "user-browser": N_("your browser"),
               "archive": N_("a web archive")}


def render_read(result, style):
    from probandia.reading.ladder import STEPS

    v, x = result.values, result.extra
    step = x["step_name"]
    rank = STEPS.index(step) + 1 if step in STEPS else v["STEP"]
    how = _(STEP_LABELS.get(step, str(step)))
    if x["extractor"] and step == "reader":
        how += f" ({x['extractor']})"
    cost = " + ".join(f"{s['reader']} " + _cost(s["units"], None) for s in x["spent"] if s["units"]) or _("free")
    out = [_head(result, style, _("Read at step {n}: {how} · {cost}").format(n=rank, how=how, cost=cost))]
    out += [""] + h.pairs([(_("page"), v.get("FINAL_URL") or v["URL"]), (_("characters"), v["CHARS"]),
                           (_("cache"), v["CACHE"])], style)
    if x["passages"]:
        out += h.section(_plural(len(x["passages"]), _("{n} useful passage"), _("{n} useful passages")), style)
        for p in x["passages"]:
            out += _wrapped(p, style, indent=4)
            out.append("")
        out.pop()
    out += h.bullets(_messages(result), style, symbol="WARN") if _messages(result) else []
    out += ["", style.dim(_("full text: {path}").format(path=result.details))]
    return "\n".join(out) + "\n"


def render_ocr(result, style):
    v = result.values
    out = [_head(result, style, _("{n} lines read by OCR from {image}").format(n=v["LINES"], image=v["IMAGE"])), ""]
    lines = result.extra["lines"]
    w = len(str(len(lines)))
    out += [style.dim(f"  {n:>{w}}") + "  " + text for n, text in enumerate(lines, start=1)]
    out += ["", style.dim(_("OCR is a draft: check each line against the image"))]
    return "\n".join(out) + "\n"


# new at a terminal (5.11.1)


def render_new(result, style):
    v = result.values
    family = (_("family {family}, created") if v["FAMILY_CREATED"] else _("family {family}")).format(
        family=v["FAMILY"])
    out = [_head(result, style, _("Research {id} created ({family})").format(id=v["RESEARCH"], family=family))]
    out += [""] + h.pairs([(_("run by"), v["RUN_MODE"]), (_("report"), f"{v['MODE']} · {v['FORMATS']}"),
                           (_("language"), v["LANG"])], style)
    out += ["", h.next_step(_("In your agent: {command}").format(command=v["NEXT"]), style)]
    return "\n".join(out) + "\n"


# probandia alone: the welcome screen (§ 6.6)

ALERTS = {"quota-low": N_("{what}: {left} % of the free quota left"),
          "quota-exhausted": N_("{what}: the free quota is used up"),
          "quota-expired": N_("{what}: the free tier has expired"),
          "catalogue-old": N_("catalogue entries older than {days} days: {what}"),
          "lock-expired": N_("lock {what} expired {since}")}


def _account_line(a):
    from probandia.cli.usage_cmd import _pays

    return f"{a['name']} {_pays(a)}"


def render_board(result, style):
    v, b = result.values, result.extra
    bullet = ">" if style.plain else "▸"
    if b["project"]:
        head = " · ".join([f"Probandia {v['VERSION']}", _("project {path}").format(path=b["project"]),
                           _plural(len(b["families"]), _("{n} family"), _("{n} families")),
                           _plural(len(b["researches"]), _("{n} research"), _("{n} researches"))])
    else:
        head = f"Probandia {v['VERSION']} · " + _("no project here")
    out = [style.bold(head)]
    if b["project"] and b["researches"]:
        live = [r for r in b["researches"] if r["status"] != "closed"][:6]
        if live:
            out += h.section(_("In progress"), style)
            wf = max(len(r["family"]) for r in live)
            wr = max(len(r["research"]) for r in live)
            for r in live:
                if r["open_pass"]:
                    sym = style.paint("●" if not style.plain else "*", h.COLORS["OK"])
                    state = _("pass {n} open").format(n=r["open_pass"])
                    if r["run_mode"] == "team" and r["agents"]:
                        state += " · " + _("team of {n}").format(n=r["agents"])
                    if r["open_since"]:
                        state += " · " + _("opened {when}").format(when=_when(r["open_since"]))
                else:
                    sym = style.dim("⏸" if not style.plain else "=") if r["status"] == "paused" else style.dim("·")
                    state = (_("paused after {n} passes") if r["status"] == "paused"
                             else _plural(r["passes"], _("{n} pass done"), _("{n} passes done"))).format(n=r["passes"])
                if r["failed_rules"]:
                    state += " · " + style.paint(style.symbol("FAIL") + " " + ", ".join(r["failed_rules"]),
                                                 h.COLORS["FAIL"])
                out.append(f" {sym} {r['family']:{wf}}  {r['research']:{wr}}  {state}")
        waiting = [r for r in b["researches"] if r["pending"]]
        if waiting:
            out += h.section(_("To review"), style)
            for r in waiting:
                out.append(f" {bullet} " + _plural(r["pending"], _("{n} proposal waiting"), _("{n} proposals waiting"))
                           + f" ({r['family']}, {r['research']})")
    elif b["project"]:
        out += ["", "  " + _("no research yet")]
    if b["accounts"]:
        out += h.section(_("Lowest quotas"), style)
        out.append(f" {bullet} " + " · ".join(_account_line(a) for a in b["accounts"]) + "   "
                   + style.dim("probandia -u"))
    if b["alerts"]:
        out += h.section(_("Alerts"), style)
        for a in b["alerts"]:
            text = _(ALERTS[a["kind"]]).format(what=a["what"], left=a.get("left"), since=_when(a.get("since")),
                                               days=a.get("days"))
            out.append(f" {h.mark('WARN', style)} {text}")
    out += h.section(_("Next"), style)
    if b["project"]:
        steps = b["next"] or [{"command": 'probandia new "<question>"', "why": N_("start a research")}]
    else:
        steps = [{"command": 'probandia new "<question>"', "why": N_("create a project here, with its first research")},
                 {"command": "probandia -p <folder>", "why": N_("work in a project elsewhere")},
                 {"command": "probandia -u", "why": N_("every free quota")}]
        if b.get("counted_projects"):
            out.insert(1, style.dim(_plural(b["counted_projects"], _("{n} project counted in your quotas"),
                                            _("{n} projects counted in your quotas"))))
    w = max(len(s["command"]) for s in steps)
    out += [" " + h.next_step(f"{s['command']:{w}}", style) + "  " + style.dim(_(s["why"])) for s in steps]
    return "\n".join(out) + "\n"


# errors that say what to do (§ 6.5)


def render_no_project(result, style):
    out = [_head(result, style, _("No project here."))]
    steps = [('probandia new "<question>"', _("create one here, with its first research")),
             ("probandia config init", _("create an empty one here")),
             ("probandia -p <folder>", _("name a project elsewhere")),
             ("probandia -u", _("the free quotas show anywhere"))]
    w = max(len(c) for c, _w in steps)
    out += [""] + [" " + h.next_step(f"{c:{w}}", style) + "  " + style.dim(why) for c, why in steps]
    return "\n".join(out) + "\n"


# keys (5.3.1 to 5.3.3)

KEY_SOURCES = {"user": N_("user .env"), "project": N_("project .env"), "environment": N_("environment")}
KEY_OUTCOMES = {"valid": N_("valid"), "refused": N_("refused"), "not-subscribed": N_("not subscribed"),
                "failed": N_("not checked"), "no-free-check": N_("no free check"), "missing": N_("not set")}


def render_keys(result, style):
    v = result.values
    rows = result.tables["keys"]["rows"]
    out = [_head(result, style, _("{n} of {total} keys set · never shown, told apart by their fingerprint").format(
        n=v["PRESENT"], total=v["KEYS"]))]
    shown = [{"variable": x["variable"], "state": (h.mark("OK", style) if x["present"] else style.dim("·")),
              "source": _(KEY_SOURCES[x["source"]]) if x["source"] else "",
              "fingerprint": x["fingerprint"] or "", "unlocks": ", ".join(x["unlocks"])} for x in rows]
    wv = max(len(x["variable"]) for x in shown)
    ws = max([len(x["source"]) for x in shown] + [len(_("from"))])
    out += ["", style.dim(f"    {_('variable'):{wv}}  {_('from'):{ws}}  {_('fingerprint'):11}  {_('unlocks')}")]
    for x in shown:
        line = f"  {x['state']} {x['variable']:{wv}}  {x['source']:{ws}}  {x['fingerprint']:11}  {x['unlocks']}"
        out.append(h.cut(line, style.width + (len(x["state"]) - 1), style) if not style.color else line.rstrip())
    out += ["", h.next_step("probandia keys check", style) + style.dim("  " + _("a free reading of each account")),
            h.next_step("probandia keys set <VARIABLE>", style) + style.dim("  " + _("typed unseen, into your .env"))]
    return "\n".join(out) + "\n"


def render_keys_where(result, style):
    out = [_head(result, style, _("The .env files, the weakest first"))]
    out.append("")
    for x in result.tables["files"]["rows"]:
        sym = h.mark("OK", style) if x["present"] else style.dim("·")
        label = _(KEY_SOURCES[x["file"]])
        count = _plural(x["keys"], _("{n} variable"), _("{n} variables")) if x["present"] else _("absent")
        out.append(f"  {sym} {label:14}  {x['path']}  " + style.dim(count))
    out += [""] + h.bullets(_messages(result), style)
    return "\n".join(out) + "\n"


def render_keys_check(result, style):
    v = result.values
    out = [_head(result, style, _("{valid} valid of {n} checked · free readings, nothing spent").format(
        valid=v["VALID"], n=v["CHECKED"]))]
    out.append("")
    marks = {"valid": "OK", "refused": "FAIL", "not-subscribed": "WARN", "failed": "WARN"}
    rows = result.tables["checks"]["rows"]
    wv = max([len(x["variable"]) for x in rows] + [8])
    for x in rows:
        sym = h.mark(marks[x["outcome"]], style) if x["outcome"] in marks else style.dim("·")
        what = _(KEY_OUTCOMES.get(x["outcome"], x["outcome"]))
        detail = []
        if x["entry"]:
            detail.append(x["entry"])
        if x["detail"]:
            detail.append(_("{n} left").format(n=x["detail"]) if x["outcome"] == "valid" else x["detail"])
        out.append(f"  {sym} {x['variable']:{wv}}  {what}" + (style.dim("  " + " · ".join(detail)) if detail else ""))
    return "\n".join(out) + "\n"


# providers (5.4.1 to 5.4.4)

PROVIDER_STATES = {"ready": N_("ready"), "no-key": N_("no key"), "not-enabled": N_("disabled"),
                   "card-required": N_("card required"), "content-reuse": N_("reuses the content")}
KINDS = {"search": N_("search"), "read": N_("reading"), "extract": N_("extraction"), "answer": N_("answers"),
         "model": N_("model")}


def _period(x):
    return {"monthly": _("a month"), "daily": _("a day"), "once": _("once")}.get(x["period"], x["period"] or "")


def render_providers(result, style):
    v = result.values
    rows = []
    for x in result.tables["providers"]["rows"]:
        free = f"{x['amount']} {x['unit']} · {_period(x)}" if x["amount"] is not None else _("unlimited")
        rows.append({"provider": x["provider"], "role": _(KINDS.get(x["kind"], x["kind"] or "")),
                     "family": x["family"] or "—", "free": free,
                     "state": _(PROVIDER_STATES.get(x["state"], x["state"])),
                     "checked": _plural(x["age_days"], _("{n} day ago"), _("{n} days ago"))
                     if x["age_days"] is not None else _("never")})
    out = [_head(result, style, _("{n} providers in the catalogue · {ready} ready").format(
        n=v["PROVIDERS"], ready=v["READY"])), ""]
    out += h.table(["provider", "role", "family", "free", "state", "checked"], rows, style,
                   {"provider": _("provider"), "role": _("role"), "family": _("family"), "free": _("free tier"),
                    "state": _("state"), "checked": _("checked")})
    out += ["", h.next_step("probandia providers show <id>", style),
            h.next_step("probandia providers disable <id>", style)]
    return "\n".join(out) + "\n"


def render_provider(result, style):
    v, x = result.values, result.extra
    out = [_head(result, style, f"{v['NAME']} ({v['PROVIDER']}) · " + _(PROVIDER_STATES.get(v["STATE"], v["STATE"])))]
    pairs = [(_("role"), _(KINDS.get(v["KIND"], v["KIND"] or ""))), (_("index family"), v["FAMILY"]),
             (_("free tier"), f"{v['FREE']} · {_period({'period': v['PERIOD']})}"),
             (_("costs"), ", ".join(f"{op} {c}" for op, c in x["costs"].items()) or "—"),
             (_("key"), v["KEY"]), (_("card required"), v["CARD_REQUIRED"]),
             (_("reuses the content"), v["CONTENT_REUSE"]),
             (_("checked"), v["CHECKED"] + (f" ({_plural(v['AGE_DAYS'], _('{n} day ago'), _('{n} days ago'))})"
                                           if v["AGE_DAYS"] != "" else "")),
             (_("pricing"), x["source"] or "—"), (_("terms"), x["terms"] or "—")]
    out += [""] + h.pairs(pairs, style)
    notes = [m for m in _messages(result)]
    if notes:
        out += [""] + h.bullets(notes, style)
    return "\n".join(out) + "\n"


def render_providers_stale(result, style):
    v = result.values
    rows = result.tables["stale"]["rows"]
    if not rows:
        return _head(result, style, _("Every entry was checked in the last {days} days").format(days=v["DAYS"])) + "\n"
    text = (_("{n} entry checked more than {days} days ago") if len(rows) == 1
            else _("{n} entries checked more than {days} days ago")).format(n=len(rows), days=v["DAYS"])
    out = [_head(result, style, text), ""]
    out += h.table(["provider", "checked", "source"], [dict(x, checked=x["checked"] or _("never")) for x in rows],
                   style, {"provider": _("provider"), "checked": _("checked"), "source": _("where to read it again")})
    return "\n".join(out) + "\n"


def render_archive_stale(result, style):
    """``archive stale`` (TRUST4-T2): the archives of the catalogue checked too long ago."""
    v = result.values
    rows = result.tables["stale"]["rows"]
    if not rows:
        return _head(result, style, _("Every archive was checked in the last {days} days").format(days=v["DAYS"])) + "\n"
    text = (_("{n} archive checked more than {days} days ago") if len(rows) == 1
            else _("{n} archives checked more than {days} days ago")).format(n=len(rows), days=v["DAYS"])
    out = [_head(result, style, text), ""]
    out += h.table(["archive", "checked", "name"], [dict(x, checked=x["checked"] or _("never")) for x in rows],
                   style, {"archive": _("archive"), "checked": _("checked"), "name": _("name")})
    return "\n".join(out) + "\n"


# archive list and coverage (5.4.6, 5.4.7)

NATURES = {"image": N_("images"), "index": N_("index"), "press": N_("press"), "catalogue": N_("catalogue"),
           "tree": N_("shared tree")}


def _access(x):
    if x["connector"]:
        return _("connector") + ("" if x["enabled"] in (True, None) else " · " + _("disabled"))
    return _("browser") if x["mode"] == "browser" else (x["mode"] or "")


def render_archive_list(result, style):
    v = result.values
    rows = [{"archive": x["archive"], "nature": _(NATURES.get(x["nature"], x["nature"] or "")),
             "access": _access(x), "key": (x["key"] + (" ✓" if x["key_set"] and not style.plain else ""))
             if x["key"] else "—",
             "readers": _("forbidden") if not x["third_party"] else _("permitted"), "name": x["name"]}
            for x in result.tables["archives"]["rows"]]
    out = [_head(result, style, _("{n} archives · {c} connectors, {e} enabled").format(
        n=v["ARCHIVES"], c=v["CONNECTORS"], e=v["ENABLED"])), ""]
    out += h.table(["archive", "nature", "access", "key", "readers", "name"], rows, style,
                   {"archive": _("archive"), "nature": _("nature"), "access": _("access"), "key": _("key"),
                    "readers": _("third-party readers"), "name": _("name")})
    return "\n".join(out) + "\n"


def render_archive_coverage(result, style):
    v = result.values
    span = ""
    if v.get("FROM", "") != "" or v.get("TO", "") != "":
        span = f" · {v['FROM'] or '…'}–{v['TO'] or '…'}"
    out = [_head(result, style, _("{n} archives cover {place}").format(n=v["ARCHIVES"], place=v["PLACE"]) + span)]
    rows = [] if "archives" not in result.tables else [{"archive": x["archive"], "nature": _(NATURES.get(x["nature"], x["nature"] or "")),
             "years": f"{x['from']}–{x['to']}", "types": ", ".join(x["types"]),
             "access": _access(dict(x, enabled=True))} for x in result.tables["archives"]["rows"]]
    if rows:
        out.append("")
        out += h.table(["archive", "nature", "years", "access", "types"], rows, style,
                       {"archive": _("archive"), "nature": _("nature"), "years": _("years"), "access": _("access"),
                        "types": _("records")})
    out += h.bullets(_messages(result), style)
    return "\n".join(out) + "\n"


# question (GPS1)

QUESTION_MARKS = {"answered": "OK", "unresolved": "WARN", "open": "ASK"}
QUESTION_STATUSES = {"open": N_("open"), "answered": N_("answered"), "unresolved": N_("unresolved")}


def render_question(result, style):
    v = result.values
    rows = result.tables["questions"]["rows"]
    head = _plural(v["QUESTIONS"], _("{n} question"), _("{n} questions"))
    if v["OPEN"]:
        head += " · " + _plural(v["OPEN"], _("{n} open"), _("{n} open"))
    out = [_head(result, style, head + " · " + v["RESEARCH"])]
    for q in rows:
        out.append("")
        out.append(f"  {h.mark(QUESTION_MARKS.get(q['status'], 'ASK'), style)} {style.bold(q['id'])}  "
                   f"{_(QUESTION_STATUSES.get(q['status'], q['status']))} · {q['type']}")
        out += _wrapped(q["text"], style)
        about = [(_("persons"), q["persons"]), (_("window"), q["window"]), (_("places"), q["places"]),
                 (_("will count as an answer"), q.get("standard")),   # T249
                 (_("conclusion"), q["conclusion"]), (_("reason"), q["reason"])]
        out += h.pairs([(k, x) for k, x in about if x], style, indent=4)
    out += h.bullets(_messages(result), style)
    return "\n".join(out) + "\n"


# correlate (GPS4)

ANALYSIS_MARKS = {"open": "WARN", "resolved": "OK", "divergent": "WARN"}


def render_correlate(result, style):
    v = result.values
    head = " · ".join([_plural(v["CONFLICTS"], _("{n} conflict without an analysis"),
                               _("{n} conflicts without an analysis")),
                       _plural(v["OPEN"], _("{n} open analysis"), _("{n} open analyses")),
                       _plural(v["RESOLVED"], _("{n} resolved"), _("{n} resolved"))])
    out = [_head(result, style, head + " · " + v["RESEARCH"])]
    rows = result.tables["conflicts"]["rows"]
    if rows:
        out += h.section(_("Conflicts"), style)
        out += h.table(["person", "fact", "on", "values"], rows, style,
                       {"person": _("person"), "fact": _("fact"), "on": _("on"), "values": _("values")})
    for x in result.tables["analyses"]["rows"]:
        out.append("")
        out.append(f"  {h.mark(ANALYSIS_MARKS.get(x['status'], 'WARN'), style)} {style.bold(x['analysis'])}  "
                   f"{_(x['status'])} · {x['person']} · {x['fact']}")
        about = [(_("evidence"), x["evidence"]), (_("kept"), x["kept"]), (_("question"), x["question"]),
                 (_("without their three axes"), x["missing_axes"] or "")]
        out += h.pairs([(k, y) for k, y in about if y not in ("", None)], style, indent=4)
    out += h.bullets(_messages(result), style)
    return "\n".join(out) + "\n"


# proof (GPS5)

PROOF_PARTS = (("question", N_("Question")), ("sources", N_("Sources")), ("analysis", N_("Analysis")),
               ("correlation", N_("Correlation")), ("conflicts", N_("Conflicts resolved")),
               ("conclusion", N_("Conclusion")))
OBJECTION_MARKS = {"open": "WARN", "answered": "OK", "dismissed": "OK"}
REVIEWERS = {"contradictor": N_("the contradictor, independent"), "session": N_("the same session, not independent")}


def render_proof(result, style):
    v = result.values
    head = f"{v['PROOF']} · {_(v['STATE'])}"
    if v["OPEN"]:
        head += " · " + _plural(v["OPEN"], _("{n} objection open"), _("{n} objections open"))
    out = [_head(result, style, head)]
    if v.get("REVIEWED_BY"):
        out.append("  " + style.dim(_("reviewed by: {who}").format(
            who="; ".join(_(REVIEWERS.get(w, w)) for w in v["REVIEWED_BY"].split(",")))))
    for key, label in PROOF_PARTS:
        text = (result.extra.get("parts") or {}).get(key) or ""
        out += h.section(_(label), style)
        out += [line for para in text.splitlines() for line in (_wrapped(para, style, 2) or [""])] or \
            ["  " + style.dim(_("to write"))]
    rows = result.tables["objections"]["rows"]
    if rows:
        out += h.section(_("Objections"), style)
        for o in rows:
            out.append(f"  {h.mark(OBJECTION_MARKS.get(o['state'], 'WARN'), style)} {o['n']}. {o['text']}")
            about = [(_("fact"), o["fact"]), (_("would settle it"), o["settle"]),
                     (_(o["state"]), o["answer"])]
            out += h.pairs([(k, x) for k, x in about if x], style, indent=5)
    out += h.bullets([m for m in _messages(result) if not m.startswith("objection=")], style)
    return "\n".join(out) + "\n"


def render_proof_list(result, style):
    v = result.values
    head = _plural(v["PROOFS"], _("{n} proof argument"), _("{n} proof arguments"))
    if v["NEEDED"]:
        head += " · " + _plural(v["NEEDED"], _("{n} question still needs one"), _("{n} questions still need one"))
    out = [_head(result, style, head + " · " + v["RESEARCH"]), ""]
    out += h.table(["question", "needs", "proof", "state", "open"], result.tables["questions"]["rows"], style,
                   {"question": _("question"), "needs": _("needs an argument"), "proof": _("proof"),
                    "state": _("state"), "open": _("open objections")})
    out += h.bullets([m for m in _messages(result) if not m.startswith("question=")], style)
    return "\n".join(out) + "\n"


# matrix (GPS3)

MATRIX_MARKS = {"consulted": "OK", "gap": "WARN", "not_applicable": "WARN", "unjustified_gap": "FAIL",
                "todo": "FAIL"}
MATRIX_STATES = {"consulted": N_("consulted"), "gap": N_("gap"), "not_applicable": N_("not applicable"),
                 "unjustified_gap": N_("unjustified gap"), "todo": N_("to do")}


def render_matrix(result, style):
    v = result.values
    head = _plural(v["QUESTIONS"], _("{n} question"), _("{n} questions")) + " · " + (
        _plural(v["HOLES"], _("{n} hole"), _("{n} holes")) if v["HOLES"] else _("no hole"))
    out = [_head(result, style, head + " · " + v["RESEARCH"])]
    rows = result.tables["matrix"]["rows"]
    for q in result.tables["questions"]["rows"]:
        mine = [dict(r, mark=style.symbol("FAIL" if r["state"] == "not_applicable" and not r["settled_by"]
                                          else MATRIX_MARKS[r["state"]]),
                     state=_(MATRIX_STATES[r["state"]]), what=r["left"] or r["settled_by"])
                for r in rows if r["question"] == q["question"]]
        out.append("")
        about = " · ".join(x for x in (q["type"], q["window"]) if x)
        out.append(f"  {h.mark('WARN' if q['holes'] else 'OK', style)} {style.bold(q['question'])}  {about}")
        if mine:
            out += h.table(["mark", "name", "state", "years", "repositories", "what"], mine, style,
                           {"mark": "", "name": _("source type"), "state": _("state"), "years": _("years"),
                            "repositories": _("repositories"), "what": _("searches, gaps, or what is left")})
    out += h.bullets(_messages(result), style)
    return "\n".join(out) + "\n"


STANDARD_MARKS = {"established": "OK", "not_applicable": "OK", "partial": "WARN", "missing": "FAIL"}
LEVEL_MARKS = {"conform": "OK", "partial": "WARN", "not_conform": "FAIL"}


def render_standard(result, style):
    """``verify --standard`` (GPS8-T1): one block per question, its five elements, and what each lacks."""
    from probandia.proof.standard import ELEMENTS
    from probandia.report import labels as L

    v = result.values
    head = _("{conform} of {n} questions conform to the Genealogical Proof Standard").format(
        conform=v["CONFORM"], n=v["QUESTIONS"])
    out = [_head(result, style, head + " · " + v["RESEARCH"])]
    lacks = result.tables["lacks"]["rows"]
    for q in result.tables["questions"]["rows"]:
        out.append("")
        conf = (" · " + _(L.CONFIDENCE_OF).format(level=_(L.CONFIDENCE_LEVELS[q["confidence"]]))
                if q.get("confidence") else "")
        out.append(f"  {h.mark(LEVEL_MARKS[q['level']], style)} {style.bold(q['question'])}  "
                   f"{_(L.STANDARD_LEVELS[q['level']])} · {_(L.QUESTION_STATUSES.get(q['status'], q['status']))}"
                   + conf)
        rows = [{"mark": style.symbol(STANDARD_MARKS[q[k]]), "element": _(L.STANDARD_ELEMENTS[k]),
                 "state": _(L.STANDARD_STATES[q[k]]),
                 "lacks": "; ".join(x["lacks"] for x in lacks if x["question"] == q["question"] and x["element"] == k)}
                for k in ELEMENTS]
        out += h.table(["mark", "element", "state", "lacks"], rows, style,
                       {"mark": "", "element": _(L.STANDARD_HEAD["element"]), "state": _(L.STANDARD_HEAD["state"]),
                        "lacks": _(L.STANDARD_HEAD["lacks"])})
        out += _wrapped("; ".join(q.get("reasons") or []), style) if q.get("reasons") else []
    out += h.bullets([m for m in _messages(result) if "=" not in m.split(" ")[0]], style)
    return "\n".join(out) + "\n"


# listings (CLI8): a title, the messages, then each table under its own title

LABELS = {"research": N_("research"), "family": N_("family"), "status": N_("status"), "passes": N_("passes"),
          "open_pass": N_("open pass"), "pending": N_("proposals"), "last_activity": N_("last activity"),
          "pass": N_("pass"), "instruction": N_("instruction"), "duration": N_("duration"), "units": N_("units"),
          "native": N_("native searches"), "summary": N_("summary"), "fact": N_("fact"), "date": N_("date"),
          "place": N_("place"), "source": N_("source"), "search": N_("search"), "state": N_("state"),
          "query": N_("query"), "hypothesis": N_("hypothesis"), "question": N_("question"),
          "archive": N_("archive"), "reference": N_("reference"), "window": N_("window"), "kind": N_("kind"),
          "rule": N_("rule"), "role": N_("role"), "input": N_("input"), "output": N_("output"),
          "weighted": N_("weighted"), "time": N_("time"), "type": N_("type"), "what": N_("what"),
          "name": N_("name"), "language": N_("language"), "persons": N_("persons"), "researches": N_("researches"),
          "places": N_("places"), "person": N_("person"), "born": N_("born"), "died": N_("died"),
          "match": N_("match"), "citation": N_("citation"), "relation": N_("relation"),
          "engine": N_("engine"), "result": N_("result"), "results": N_("results"), "accessed": N_("accessed"),
          "rights": N_("rights"), "opened": N_("opened"), "cause": N_("cause"),
          "proposal": N_("proposal"), "author": N_("author"), "facts": N_("facts"), "sources": N_("sources"),
          "verdict": N_("verdict"), "reason": N_("reason"),
          "account": N_("account"), "left": N_("left"), "alert": N_("alert"), "command": N_("command"),
          "why": N_("why"), "of": N_("of"), "unit": N_("unit"), "gauge": N_("gauge"), "renews": N_("renews"),
          "remedy": N_("remedy"), "provider": N_("provider"), "amount": N_("amount"), "variable": N_("variable"),
          "present": N_("present"), "fingerprint": N_("fingerprint"), "unlocks": N_("unlocks"), "key": N_("key"),
          "value": N_("value"), "layer": N_("layer"), "grade": N_("grade"), "help": N_("help"), "tool": N_("tool"),
          "installed": N_("installed"), "purpose": N_("purpose"), "install": N_("install"), "scope": N_("scope"),
          "holder": N_("holder"), "expires": N_("expires"), "wave": N_("wave"), "agents": N_("agents"),
          "ts": N_("time"), "from": N_("from"), "to": N_("to"), "body": N_("message"),
          "index": N_("index"), "entry": N_("entry"), "change": N_("change"), "outcome": N_("check"),
          "model": N_("model"), "model_from": N_("model set by"), "effort": N_("effort"),
          "effort_from": N_("effort set by"), "script": N_("script"), "level": N_("level"), "version": N_("version"),
          "witness": N_("witness"), "runs": N_("runs ok"), "used": N_("used"), "last_run": N_("last run"),
          "entries": N_("entries"), "bytes": N_("bytes"), "expired_entries": N_("expired entries"),
          "served": N_("served"), "saved": N_("saved"), "file": N_("file"), "size": N_("size"),
          "written": N_("last written")}
TITLES = {"researches": N_("Researches"), "instructions": N_("Instructions"), "passes": N_("Passes"),
          "facts": N_("Facts"), "negatives": N_("Negatives"), "hypotheses": N_("Hypotheses"),
          "gaps": N_("Gaps in the archives"), "verify": N_("Rules that failed at the last verify"),
          "tokens": N_("Tokens of the last pass, by role"), "events": N_("Events"),
          "families": N_("Families"), "persons": N_("Persons"), "relatives": N_("Relatives"),
          "searches": N_("Searches"), "sources": N_("Sources"),
          "proposals": N_("Proposals"), "rules": N_("Rules of apply that fail"),
          "changes": N_("What applying it would change in the indexes")}


def _label(name, labels=LABELS):
    return _(labels[name]) if name in labels else h.humanize(name)


def render_listing(result, style):
    """The title of ``Result.extra``, then every table that has rows."""
    out = [_head(result, style, (result.extra or {}).get("title") or h.status_label(result.status))]
    messages = _messages(result)
    if messages:
        out += [""] + h.bullets(messages, style)
    for name, t in result.tables.items():
        if t["rows"] and not t.get("hidden"):
            out += h.section(_label(name, TITLES), style)
            out += h.table(t["columns"], t["rows"], style, {c: _label(c) for c in t["columns"]})
    return "\n".join(out) + "\n"


def register():
    h.VIEWS.update({"status": render_status, "doctor": render_doctor, "verify": render_verify,
                    "config-show": render_config_show, "config-explain": render_config_explain,
                    "config-path": render_config_path, "config-diff": render_config_diff, "known": render_known,
                    "export": render_export,
                    "import-gedcom": render_import_gedcom, "library": render_library, "dates": render_dates,
                    "variants": render_variants, "places": render_places, "place_guide": render_place_guide, "cite": render_cite,
                    "search": render_search, "read": render_read, "ocr": render_ocr, "new": render_new,
                    "board": render_board, "no-project": render_no_project, "keys": render_keys,
                    "keys-where": render_keys_where, "keys-check": render_keys_check,
                    "providers": render_providers, "provider": render_provider,
                    "providers-stale": render_providers_stale, "archive-list": render_archive_list,
                    "archive-stale": render_archive_stale,
                    "archive-coverage": render_archive_coverage,
                    "question": render_question, "correlate": render_correlate, "proof": render_proof,
                    "proof-list": render_proof_list, "matrix": render_matrix, "standard": render_standard,
                    "listing": render_listing})


register()
