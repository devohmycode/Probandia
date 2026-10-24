"""Engine commands of the genealogical toolkit: dates, variants, places."""
import os

from probandia.cli.output import Result
from probandia.errors import EXIT_FAIL, NotInProject, UsageError
from probandia.i18n import _


def _project_or_none(ctx):
    try:
        return ctx.project
    except NotInProject:
        return None


# dates


def dates_args(p, common):
    p.add_argument("text", nargs="?", help=_("the date as written"))
    p.add_argument("--julian", metavar="<date>", help=_("a Julian date to convert"))
    p.add_argument("--age", type=int, help=_("an age, with --on"))
    p.add_argument("--on", metavar="<YYYY-MM-DD>", help=_("the date the age was given"))
    p.add_argument("--calendar", choices=("gregorian", "julian"), default="gregorian",
                   help=_("the calendar of a date written without one"))


def dates(ctx):
    from probandia.lang import dates as d

    a = ctx.args
    try:
        if a.age is not None or a.on:
            if a.age is None or not a.on:
                raise UsageError(_("--age and --on go together"))
            r = d.age_range(a.age, a.on)
        elif a.julian:
            r = d.from_julian(a.julian)
        elif a.text:
            r = d.read(a.text, a.calendar)
        else:
            raise UsageError(_("give a date, --julian <date>, or --age <n> --on <date>"))
    except d.Unrecognized:
        original = a.text or a.julian or a.on
        return Result("FAIL", {"REASON": "unrecognized", "ORIGINAL": original},
                      [_("this date cannot be read with certainty; nothing is guessed")],
                      exit_code=EXIT_FAIL)
    values = {"ISO": r["iso"], "QUALIFIER": r["qualifier"], "CALENDAR": r["calendar"]}
    if r.get("end"):
        values["END"] = r["end"]
    values["ORIGINAL"] = r["original"]
    r = Result("OK", values)
    r.view = "dates"
    return r


# variants


def variants_args(p, common):
    p.add_argument("surname")
    p.add_argument("--given", metavar="<name>", help=_("a given name, for its other forms"))
    p.add_argument("--paleo", action="store_true", help=_("add the reading confusions"))
    p.add_argument("--family", help=_("the family whose attested forms come first"))


def variants(ctx):
    from probandia.indexes import FamilyIndexes
    from probandia.lang import variants as v
    from probandia.research import default_family

    attested = {}
    project = _project_or_none(ctx)
    if project:
        family = ctx.args.family
        if not family:
            try:
                family = default_family(project)
            except UsageError:
                family = None
        if family:
            attested = FamilyIndexes(project, family).load("variants").get("surnames", {})
    forms = v.surname_forms(ctx.args.surname, attested, ctx.args.paleo)
    r = Result("OK", {"SURNAME": ctx.args.surname, "FORMS": len(forms),
                      "ATTESTED": sum(1 for f in forms if f[1] == "attested")})
    for form, kind, detail in forms:
        r.data("form", f"{form} {kind} {detail}".rstrip())
    if ctx.args.given:
        given = v.given_forms(ctx.args.given)
        r.set("GIVEN", len(given))
        for form, lang in given:
            r.data("given", f"{form} {lang}")
        r.table("given", [{"form": form, "language": lang} for form, lang in given])
    r.table("forms", [{"form": form, "kind": kind, "rule": detail} for form, kind, detail in forms])
    r.view = "variants"
    return r


# places


def places_args(p, common):
    p.add_argument("name", nargs="?", help=_("the place as written, or guide"))
    p.add_argument("place", nargs="?", help=_("guide: the place of the family, or a place name"))
    p.add_argument("--as-of", type=int, metavar="<year>", help=_("the year of the record"))
    p.add_argument("--family", help=_("the family whose places come first"))
    p.add_argument("--choice", metavar="<id>", help=_("the place the user chose among the candidates"))
    p.add_argument("--offline", action="store_true", help=_("local sources only"))
    p.add_argument("--update-cog", action="store_true", help=_("download the INSEE COG files"))
    p.add_argument("--research", help=_("guide: the research the proposal belongs to"))
    p.add_argument("--window", metavar="<from-to>", help=_(
        "guide: the years whose repositories are listed (default: the research's plan); places.yaml keeps them all"))
    p.add_argument("--refresh", action="store_true", help=_("guide: ask the gazetteers again, past the cache"))
    p.add_argument("--copy-from", metavar="<family>", help=_("guide: take the guide another family built"))


def places(ctx):
    from probandia.indexes import FamilyIndexes
    from probandia.lang import places as pl

    folder = os.path.join(pl.data_dir(ctx.environ), "insee")
    if ctx.args.update_cog:
        written = pl.update_cog(folder, _http(ctx))
        return Result("OK", {"COG": folder, "FILES": len(written)})
    if not ctx.args.name:
        raise UsageError(_("give a place name, or --update-cog"))
    if ctx.args.name == "guide":
        return guide(ctx, folder)
    if ctx.args.place:
        raise UsageError(_("give one place name, in quotes if it has spaces"))
    family_places = []
    project = _project_or_none(ctx)
    family = _family(ctx, project)
    if family:
        family_places = FamilyIndexes(project, family).items("places")
    http = None if ctx.args.offline else _http(ctx)
    found, notes = pl.lookup(ctx.args.name, ctx.args.as_of, family_places, pl.Cog.load(folder),
                             http, ctx.environ, ctx.args.offline)
    if ctx.args.choice:
        chosen = [c for c in found if c["id"] == ctx.args.choice]
        if not chosen:
            raise UsageError(_("{id} is not among the candidates for {name}").format(
                id=ctx.args.choice, name=ctx.args.name))
        found = chosen
    if pl.ambiguous(found):
        r = Result.ask("place_ambiguous", "Which place is meant?", [c["id"] for c in found],
                       found[0]["id"], allow_other=True, values={"NAME": ctx.args.name})
        r.line(_("answer with --choice <id>"))
    else:
        r = Result("OK" if found else "WARN", {"NAME": ctx.args.name, "COUNT": len(found)})
        if found:
            r.set("AS_OF", found[0]["name"])
            r.set("CURRENT", found[0]["current"])
    for c in found:
        codes = " ".join(f"{k}={v}" for k, v in sorted(c["codes"].items()) if v)
        coords = f" lat={c['lat']} lon={c['lon']}" if c["lat"] is not None else ""
        r.data("place", f"{c['id']} \"{c['name']}\" current=\"{c['current']}\" {codes}{coords}".rstrip())
    for note in notes:
        r.line(note)
    if not found:
        r.line(_("no place found under this name"))
    r.table("places", [{"place": c["id"], "name": c["name"], "current": c["current"],
                        "codes": " ".join(f"{k}={v}" for k, v in sorted(c["codes"].items()) if v)}
                       for c in found])
    r.view = "places"
    return r


def _family(ctx, project):
    from probandia.research import default_family

    if not project:
        return None
    if ctx.args.family:
        return ctx.args.family
    try:
        return default_family(project)
    except UsageError:
        return None


def _family_place(name, places):
    from probandia.lang.places import key

    for p in places:
        if p["id"] == name:
            return p
    wanted = key(name)
    for p in places:
        if wanted in {key(f) for f in [p.get("current_name") or ""] + list(p.get("names_as_written", [])) if f}:
            return p
    return None


def _bracketed(text):
    """("Coutances", "Manche") for "Coutances (Manche)"; (text, None) without brackets."""
    import re

    m = re.fullmatch(r"\s*(.+?)\s*\(([^)]+)\)\s*", text)
    return (m.group(1), m.group(2)) if m else (text, None)


def _new_place(ctx, name, cog, http, department=None):
    """(a place of places.yaml for ``name``, None, the gazetteer's full label) from the gazetteers,
    or (None, a question, None). The label (``…, Manche, Normandie, France``) gives the department
    when the COG files are not installed (token-economy A3); so does the department in brackets,
    which also chooses among communes of one name (C3)."""
    from probandia.archives.coverage import places_in
    from probandia.lang import places as pl
    from probandia.util.ids import slugify

    found, _notes = pl.lookup(name, ctx.args.as_of, (), cog, http, ctx.environ, http is None)
    deps = {c[3:] for c in places_in(department or "") if c.startswith("FR-")}
    if deps:
        found = [c for c in found if not c["codes"].get("insee") or pl.department_of(c["codes"]["insee"]) in deps]
    if ctx.args.choice:
        found = [c for c in found if c["id"] == ctx.args.choice]
        if not found:
            raise UsageError(_("{id} is not among the candidates for {name}").format(id=ctx.args.choice, name=name))
    if not found and deps:   # in no gazetteer, but its department names the archives
        return {"id": slugify(name), "names_as_written": [name]}, None, department
    if not found:
        raise UsageError(_("no place found under this name"), values={"REASON": "no-place", "NAME": name},
                         lines=[] if cog else [_("insee: the COG files are not installed (places --update-cog)")])
    if pl.ambiguous(found):
        r = Result.ask("place_ambiguous", "Which place is meant?", [c["id"] for c in found], found[0]["id"],
                       allow_other=True, values={"NAME": name})
        r.line(_("answer with --choice <id>"))
        return None, r, None
    c = found[0]
    if deps and not c.get("context"):
        c = dict(c, context=department)
    place = {"id": slugify(name), "names_as_written": [name], "current_name": c["current"]}
    if c["id"].startswith("insee:"):
        place["type"] = "commune"
        place["insee"] = {"code": c["id"].split(":", 1)[1]}
    for k in ("gov", "wikidata", "geonames"):
        if c["codes"].get(k):
            place[k] = c["codes"][k]
    if c.get("lat") is not None:
        place["lat"], place["lon"] = c["lat"], c["lon"]
    return place, None, c.get("context")


def _guide_research(project, family, ref):
    from probandia.research import all_researches, find_research

    if ref:
        research = find_research(project, ref)
        if research.family != family:
            raise UsageError(_("the research {id} belongs to the family {family}").format(
                id=research.id, family=research.family))
        return research
    open_ones = [(str((r.meta() or {}).get("created", "")), r) for r in all_researches(project)
                 if r.family == family and (r.meta() or {}).get("status", "open") == "open"]
    return max(open_ones, key=lambda x: x[0])[1] if open_ones else None


def _window(text):
    if not text:
        return None
    try:
        lo, hi = (int(x) if x else None for x in text.split("-", 1))
    except ValueError:
        raise UsageError(_("a window is written <from-to>, such as 1780-1850")) from None
    return lo, hi


def _plan_window(research):
    """(from, to) of the research's last plan (work/plan-<n>.yaml), else None."""
    import re

    from probandia.util import yamlio

    if research is None or not os.path.isdir(research.work):
        return None
    plans = [(int(m.group(1)), name) for name in os.listdir(research.work)
             for m in [re.fullmatch(r"plan-(\d+)\.yaml", name)] if m]
    if not plans:
        return None
    w = ((yamlio.load(os.path.join(research.work, max(plans)[1])) or {}).get("axes") or {}).get("window") or {}
    return (w.get("from"), w.get("to")) if w.get("from") or w.get("to") else None


def _crosses(repo, window):
    """A repository is listed when it holds something of the window: an undated holding, or none known."""
    held = repo.get("holdings") or []
    if not window or not held:
        return True
    lo, hi = window
    return any(not h.get("years") or ((lo is None or h["years"][1] >= lo) and (hi is None or h["years"][0] <= hi))
               for h in held)


def guide(ctx, folder):
    """``places guide <place>``: a place's jurisdictions over time and its repositories (GPS2-T5),
    as a proposal of the family's places.yaml, applied at once for the agent who applies (J9); without a
    project or a research, shown only."""
    from probandia.cli.data_cmd import apply_own, propose_parts
    from probandia.indexes import FamilyIndexes
    from probandia.lang import guide as G
    from probandia.lang import places as pl

    a = ctx.args
    if not a.place:
        raise UsageError(_("name the place: places guide <place>"))
    project = _project_or_none(ctx)
    family = _family(ctx, project)
    name, department = _bracketed(a.place)
    place = _family_place(name, FamilyIndexes(project, family).items("places") if family else [])
    notes, cache, stored, cog = [], None, False, None
    if place and (place.get("guide") or {}).get("built") and not (a.refresh or a.copy_from):
        built, stored = place, True
        notes.append(_("the guide of {date} in places.yaml; --refresh builds it again").format(
            date=place["guide"]["built"]))
    elif a.copy_from:
        if not family:
            raise UsageError(_("--copy-from takes the guide of another family of the project"))
        other = FamilyIndexes(project, a.copy_from).items("places")
        built = G.copy_guide(place or _family_place(name, other) or {"id": name}, other, a.copy_from)
        if built is None:
            raise UsageError(_("the family {family} has no guide for {place}").format(family=a.copy_from, place=a.place),
                             values={"REASON": "no-guide"})
    else:
        cog = pl.Cog.load(folder)
        cache = G.CachedHttp(None if a.offline else _http(ctx),
                             G.cache_folder(project) if project else None, a.refresh)
        context = None
        if place is None:
            place, question, context = _new_place(ctx, name, cog, cache, department)
            if question is not None:
                return question
        # T67: the guide stored in places.yaml is whole; --window, or the research's plan, limits what is listed
        built, notes = G.build(place, cog, cache, None, project, context=context or department)
    j, repos = built.get("jurisdictions") or [], built.get("repositories") or []
    target = _guide_research(project, family, a.research) if family else None
    window = _window(a.window) or _plan_window(target)
    listed = [x for x in repos if _crosses(x, window)]
    # C3: an empty guide is said, never proposed
    research = target if not stored and (j or repos) else None
    r = Result("OK" if j else "WARN", {"PLACE": built["id"], "JURISDICTIONS": len(j), "REPOSITORIES": len(listed)})
    if len(listed) < len(repos):   # T67: those of other years were listed at every guide (J1, ~350 characters)
        r.set("WINDOW", f"{window[0] or ''}-{window[1] or ''}")
        r.set("OUTSIDE_WINDOW", len(repos) - len(listed))
    if stored:
        r.set("STORED", built["guide"]["built"])
    if built["guide"].get("copied_from"):
        r.set("COPIED_FROM", built["guide"]["copied_from"])
    if cache is not None:
        r.set("CACHED", cache.hits)
    applied, refused = False, []
    if research:
        r.set("PROPOSAL", propose_parts(ctx, research, "guide", places=[built]))
        applied, refused = apply_own(ctx, research, r.values["PROPOSAL"])   # J9: the guide never waits
        r.set("APPLIED", applied)
    for x in j:
        span = f"{x.get('from') or '?'}..{x.get('to') or '?'}"
        r.data("jurisdiction", f"{x['level']} \"{x['name']}\" {span} {x['source']}" + (" derived" if x.get("derived") else ""))
    for x in listed:
        r.data("repository", f"\"{x['name']}\" {x.get('archive') or '-'} {len(x.get('holdings') or [])} holdings")
    # A3: where to look first in a department's archives, its address, and how to read its site
    from probandia.archives.finder import load_catalogue
    from probandia.archives.repositories import first_step

    cat = None
    for x in listed:
        if x.get("source") == "catalogue:archives" and x.get("url") and (x.get("archive") or "").startswith("ad"):
            cat = cat if cat is not None else load_catalogue(project)
            note = first_step(window) if window else x.get("note") or ""
            r.data("first", f"{x['archive']} {x['url']} {note}".rstrip())
            for step in ((cat.get(x["archive"]) or {}).get("guide") or [])[:6]:
                r.data("guide", f"{x['archive']}: {step}")
    for note in notes:
        r.line(note)
    if not (j or repos):
        r.line(_("no jurisdiction and no repository found: nothing proposed"))
        missing = _("insee: the COG files are not installed (places --update-cog)")
        if not stored and not a.copy_from and not cog and missing not in notes:
            r.line(missing)
    elif refused:
        r.status = "WARN"
        r.lines += [f"reason={x}" for x in refused[:3]]
    elif research and not applied:
        r.line(_("next: apply {id}").format(id=r.values["PROPOSAL"]))
    elif not research and not stored:   # T67: it came after a guide applied too
        r.line(_("shown only: no open research of a family to propose the guide to"))
    r.table("jurisdictions", [{"level": x["level"], "name": x["name"], "from": x.get("from") or "",
                               "to": x.get("to") or "", "source": x.get("source") or "", "derived": bool(x.get("derived")),
                               "note": x.get("note") or ""} for x in j])
    r.table("repositories", [{"name": x["name"], "archive": x.get("archive") or "", "holdings": ", ".join(
        h["type"] + (f" {h['years'][0]}-{h['years'][1]}" if h.get("years") else "") for h in x.get("holdings") or []),
        "note": x.get("note") or ""} for x in listed])
    r.view = "place_guide"
    return r


def _http(ctx):
    """The gazetteers' client; its rate state in the project's .probandia, else in the user data folder."""
    from probandia.lang import places as pl

    project = _project_or_none(ctx)
    return pl.Http(_contact(ctx), os.path.join(project, ".probandia") if project else pl.data_dir(ctx.environ),
                   ctx.config)


def _contact(ctx):
    try:
        return ctx.config.get("http.contact") if _project_or_none(ctx) else ctx.environ.get(
            "PROBANDIA_CONTACT", "")
    except Exception:
        return ""
