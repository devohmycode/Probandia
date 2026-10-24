"""Engine command ``render``, and the user's ``report``: the report of a research, in its language."""
import json
import os
import shutil

from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _

FORMATS = ("md", "html", "json")
PROSE_LINES = 10   # T252: the claims shown; PROSE= counts them all


def render_args(p, common):
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--formats", help=_("comma-separated formats: md, html, json"))
    p.add_argument("--prompt-lang", metavar="<tag>", help=_("language the agent reads in the prompt"))
    p.add_argument("--template", metavar="<id>", help=_("the HTML template, for this render only"))
    p.add_argument("--all", action="store_true", help=_("render every research again, each with its template"))
    p.add_argument("--family", help=_("with --all: the researches of one family only"))


def report_language(ctx, meta):
    """(tag, source), in the order of the language sources."""
    from probandia.lang import detect

    prompt = getattr(ctx.args, "prompt_lang", None)
    if prompt:
        detect.remember_session_language(ctx.project, prompt)
    return detect.detect(arg=ctx.args.lang, research=meta.get("language"), environ=ctx.environ,
                         setting=detect.setting_value(ctx.config), project=ctx.project, prompt=prompt,
                         order=ctx.config.get("language.detection_order"))


def locale_dirs(ctx):
    dirs = [os.path.join(ctx.project, "locales")]
    if ctx.config.get("locales.dir"):
        dirs.append(os.path.join(ctx.project, ctx.config.get("locales.dir")))
    return dirs


def _formats(ctx, meta):
    text = getattr(ctx.args, "formats", None)
    chosen = [f.strip() for f in text.split(",") if f.strip()] if text else (
        meta.get("formats") or ctx.config.get("report.formats"))
    bad = [f for f in chosen if f not in FORMATS]
    if bad:
        raise UsageError(_("unknown report format {name}; allowed: md, html, json").format(name=bad[0]))
    return [f for f in FORMATS if f in chosen]


def _snapshot(folder):
    """Living mode: the previous Markdown goes to ``history/<its pass>.md``."""
    md, js = os.path.join(folder, "report.md"), os.path.join(folder, "report.json")
    if not os.path.isfile(md):
        return None
    try:
        with open(js, encoding="utf-8") as fh:
            through = int(json.load(fh).get("through_pass") or 0)
    except (OSError, ValueError, TypeError):
        through = 0
    target = os.path.join(folder, "history", f"{through}.md")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(md, target)
    return target


def render(ctx):
    from probandia.research import find_research

    if getattr(ctx.args, "all", False):
        return render_all(ctx)
    return render_research(ctx, find_research(ctx.project, ctx.args.research, ctx.environ))


def render_all(ctx):
    """``render --all [--family <slug>]``: every research again, with its template (optimize 4.6)."""
    from probandia.research import all_researches

    found = [r for r in all_researches(ctx.project) if not ctx.args.family or r.family == ctx.args.family]
    if ctx.args.family and not found:
        raise UsageError(_("no research in the family {family}").format(family=ctx.args.family))
    r = Result("OK", {"RESEARCHES": len(found)})
    failed = 0
    for research in found:
        one = render_research(ctx, research)
        if one.status not in ("OK", "WARN"):
            failed += 1
            r.status = "WARN"
        r.data("rendered", f"{research.id} {one.status} {one.values.get('TEMPLATE', '-')}")
    r.set("FAILED", failed)
    return r


def choose_template(ctx, research, meta):
    """(template, where it was chosen); raises UsageError when it is missing or refused."""
    from probandia.lifecycle import families
    from probandia.report import template as T

    tid, origin = T.choose(getattr(ctx.args, "template", None), meta,
                           families(ctx.project).get(research.family), ctx.config)
    tpl = T.find(tid, ctx.project, ctx.config, ctx.environ)
    if tpl is None:
        from probandia.suggest import lines

        known = [x.id for x in T.available(ctx.project, ctx.config, ctx.environ)]
        raise UsageError(_("no template {id} (chosen by {origin})").format(id=tid, origin=origin),
                         values={"REASON": "unknown-template", "TEMPLATE": tid}, lines=lines(tid, known))
    reasons = T.check(tpl)
    if reasons:
        raise UsageError(_("the template {id} is refused: run template check {id}").format(id=tid),
                         values={"REASON": "template-refused", "TEMPLATE": tid}, lines=reasons[:5])
    return tpl, origin


def render_research(ctx, research):
    from probandia import events
    from probandia.i18n import PSEUDO, Translator
    from probandia.indexes import FamilyIndexes
    from probandia.report import prose
    from probandia.report import render as R
    from probandia.util.fs import atomic_write_text

    meta = research.meta() or {}
    broken = events.check_chain(research.events_path)
    if broken:
        return Result("FAIL", {"REASON": "chain-broken", "RESEARCH": research.id, "LINE": broken[0]},
                      [_("events.jsonl is broken at line {n}: {what}").format(n=broken[0], what=broken[1])])
    lang, source = report_language(ctx, meta)
    t = Translator(lang, locale_dirs(ctx))
    if t.missing:
        return _ask_labels(ctx, research, meta, lang)
    formats = _formats(ctx, meta)
    tpl, origin = choose_template(ctx, research, meta)
    noted = _Noting(t)   # T70: which labels the report asks for, to tell those not translated yet
    report = _build(ctx, research, meta, lang, noted, tpl if "html" in formats else None)
    problems = R.validate(report.data)
    if problems:
        return Result("FAIL", {"REASON": "invalid-report", "RESEARCH": research.id},
                      [_("report.json does not match its schema: {first}").format(first=problems[0])])
    folder = os.path.join(research.folder, "report")
    os.makedirs(folder, exist_ok=True)
    snapshot = _snapshot(folder) if report.model.mode == "living" else None
    written = []
    changed = []   # PRD criterion 6 (T226): the text an earlier pass shows, its fingerprint kept from render to render
    if report.fingerprints:
        prints = os.path.join(folder, "passes.json")
        try:
            with open(prints, encoding="utf-8") as fh:
                kept = {int(k): v for k, v in json.load(fh).items()}
        except (OSError, ValueError):
            kept = {}
        last = max(report.fingerprints)
        changed = [p for p in sorted(kept) if p < last and p in report.fingerprints and kept[p] != report.fingerprints[p]]
        atomic_write_text(prints, json.dumps({str(p): h for p, h in sorted(report.fingerprints.items())}, indent=2)
                          + "\n")   # a control file of the engine: not among the files the report lists
    atomic_write_text(os.path.join(folder, "report.json"), R.to_json(report))
    written.append("report.json")
    if "md" in formats:
        atomic_write_text(os.path.join(folder, "report.md"), R.to_markdown(report, noted))
        written.append("report.md")
    if "html" in formats:
        atomic_write_text(os.path.join(folder, "report.html"), R.to_html(report, noted, tpl))
        written.append("report.html")
    if report.tree_mermaid:  # step 4: then the trees, one per branch.added
        trees_dir = os.path.join(research.folder, "trees")
        os.makedirs(trees_dir, exist_ok=True)
        for p in sorted(report.tree_mermaid):
            atomic_write_text(os.path.join(trees_dir, f"pass-{p}.md"),
                              "```mermaid\n" + report.tree_mermaid[p] + "\n```\n")
            atomic_write_text(os.path.join(trees_dir, f"pass-{p}.svg"), report.tree_svg[p])
            written += [f"../trees/pass-{p}.md", f"../trees/pass-{p}.svg"]
    values = {"RESEARCH": research.id, "LANG": lang, "LANG_SOURCE": source, "MODE": report.model.mode,
              "THROUGH_PASS": report.model.through_pass, "FILES": len(written)}
    if "html" in formats:
        values["TEMPLATE"] = tpl.id
        values["TEMPLATE_ORIGIN"] = origin
    claims = prose.check(events.read(research.events_path),
                         FamilyIndexes(ctx.project, research.family).items("persons"))   # T252
    status = "WARN" if report.unresolved or claims else "OK"
    r = Result(status, values)
    if report.unresolved:
        r.set("REASON", "unresolved-references")
        r.set("UNRESOLVED", len(report.unresolved))
        r.line(_("references that resolve to nothing (rule V-6):"))
        for ref in sorted(set(report.unresolved)):
            r.data("REF", ref)
    if changed:
        r.status = "WARN"
        r.set("REASON", "pass-text-changed")
        r.set("PASSES_CHANGED", ",".join(str(p) for p in changed))
        r.line(_("journal mode: the text of passes {passes} changed since the last render, where an erratum "
                 "should have been added").format(passes=", ".join(str(p) for p in changed)))
    # T70: a later pass may ask for labels the first catalogue did not hold: those only, without asking again
    try:
        missing = [] if lang == PSEUDO or lang.split("-")[0] == "en" else [
            m for m in report_labels_asked(noted.asked) if not t.catalog.get(m)]
    except OSError:   # labels.py not shipped as source: the report is written all the same
        missing = []
    if missing:
        r.status = "WARN"
        r.set("LABELS_MISSING", len(missing))
        r.set("POT", _write_pot(ctx.project, lang, missing))
        r.set("TARGET", _target(lang))
        r.line(_("labels in English: have the POT= catalogue translated into the TARGET= file, then render "
                 "again"))
    rel = os.path.relpath(folder, ctx.project).replace(os.sep, "/")
    for name in written:
        r.data("FILE", f"{rel}/{name}")
    r.table("files", [{"file": f"{rel}/{name}"} for name in written], hidden=True)
    if snapshot:
        r.data("SNAPSHOT", os.path.relpath(snapshot, ctx.project).replace(os.sep, "/"))
    if claims:   # T252: after the files, which the cut of a long output must not take
        if not report.unresolved:
            r.set("REASON", "prose-claims")
        r.set("PROSE", len(claims))
        r.line(_("prose that promises more than the data: the axes belong to a fact's evidence, "
                 "and a dated sentence cites its fact [[f:…]]:"))
        for sid, kind, text in claims[:PROSE_LINES]:
            r.data("CLAIM", f"{sid} {kind}: {text}")
        if len(claims) > PROSE_LINES:
            r.line(_("{n} more claims to check in the sections").format(n=len(claims) - PROSE_LINES))
    return r


def _target(lang):
    return f"locales/{lang}/LC_MESSAGES/probandia.po"


class _Noting:
    """A report's translator that notes each message it is asked for (T70)."""

    def __init__(self, t):
        self.t, self.asked = t, set()

    def __call__(self, message):
        self.asked.add(message)
        return self.t(message)

    def plural(self, singular, plural, n):
        self.asked.add(singular)
        return self.t.plural(singular, plural, n)


def report_labels_asked(asked):
    """The report's labels among the messages a render asked for, and the trees' legend always (T70); a
    label with no word outside its fields (``{date}``) has nothing to translate."""
    import re

    from probandia.i18n.extract import report_labels
    from probandia.report import labels as L

    asked = set(asked) | set(L.LEGEND.values())
    return [m for m in report_labels() if m in asked and re.search(r"[^\W\d_]", re.sub(r"\{[^}]*\}", "", m))]


def _write_pot(project, lang, labels):
    """``locales/<lang>/LC_MESSAGES/report-labels.pot`` of the project: the labels to translate."""
    from probandia.i18n.extract import REPORT_LABELS, render_pot
    from probandia.util.fs import atomic_write_text

    rel = f"locales/{lang}/LC_MESSAGES/report-labels.pot"
    text = render_pot([(m, None, [REPORT_LABELS]) for m in labels]).replace(
        "# This file is generated by: python -m probandia.i18n.extract",
        "# The labels a report asks for (render): translate each into probandia.po, next to this file")
    atomic_write_text(os.path.join(project, *rel.split("/")), text)
    return rel


def _build(ctx, research, meta, lang, t, tpl=None):
    """The report of ``research`` in ``lang``, its labels from ``t``; nothing is written."""
    from probandia import events, factcheck, logins
    from probandia.indexes import FamilyIndexes
    from probandia.proof import matrix, standard
    from probandia.report import render as R

    docs = FamilyIndexes(ctx.project, research.family).load_all()
    found = matrix.build(research, meta)
    report = R.build_report(meta, events.read(research.events_path), docs, lang, t,
                            numbering_style=meta.get("numbering") or ctx.config.get("report.numbering"),
                            pattern=ctx.config.get("report.number_pattern"),
                            living_years=ctx.config.get("privacy.living_years"),
                            trees=ctx.config.get("report.simplified_trees"),
                            timelines=ctx.config.get("report.timeline"), matrix=found,
                            standard=standard.of_research(ctx.project, research, meta, docs=docs, matrix_doc=found,
                                                          strict=ctx.config.get("proof.standard") == "strict"),
                            checks=factcheck.of_family(ctx.project, research.family))   # T248
    report.manual = logins.manual_tasks(ctx.project, research.id)
    if tpl is not None:
        report.data["template"] = tpl.fingerprint()
    return report


def _ask_labels(ctx, research, meta, lang):
    """``translate_labels`` (T70): POT= holds the labels a render of this research asks for and the trees'
    legend, about a hundred, where the engine's whole catalogue holds some two thousand messages; a small
    model translates them."""
    from probandia.i18n import Translator
    from probandia.i18n.extract import report_labels
    from probandia.report import render as R

    noted = _Noting(Translator("en"))
    try:   # the labels a render in English asks for; a template refused is said by the render that follows
        try:
            tpl = choose_template(ctx, research, meta)[0]
        except UsageError:
            tpl = None
        report = _build(ctx, research, meta, lang, noted, tpl)
        R.to_markdown(report, noted)
        if tpl is not None:
            R.to_html(report, noted, tpl)
        labels = report_labels_asked(noted.asked)
    except Exception:   # noqa: BLE001 — the question is asked even when the report cannot be built yet
        labels = report_labels_asked(report_labels())
    target = _target(lang)
    pot = _write_pot(ctx.project, lang, labels)
    r = Result.ask("translate_labels",
                   _("No report labels exist in {lang}. Translate the catalogue {pot} ({n} labels) into {po}, "
                     "then render again.").format(lang=lang, pot=pot, n=len(labels), po=target),
                   ["translate", "english"], "translate", values={"RESEARCH": research.id, "LANG": lang})
    r.set("POT", pot)
    r.set("LABELS", len(labels))
    r.set("TARGET", target)
    return r


# report (cli.md 5.9.1 to 5.9.3, T112): the user's command around render


def report_args(p, common):
    p.add_argument("action", choices=("open", "show", "render"))
    p.add_argument("research", nargs="?", help=_("research id or unique prefix"))
    p.add_argument("--formats", help=_("comma-separated formats: md, html, json"))
    p.add_argument("--template", metavar="<id>", help=_("the HTML template, for this render only"))


def _stale(research, path):
    """True when ``path`` is missing or older than the research's log."""
    try:
        return os.path.getmtime(path) < os.path.getmtime(research.events_path)
    except OSError:
        return True


def report(ctx):
    """``report open``: the report rendered again when the log is newer, then opened in the
    browser; ``report show``: its Markdown at the terminal; ``report render``: as ``render``."""
    from probandia.cli.export_cmd import open_folder
    from probandia.research import find_research

    research = find_research(ctx.project, ctx.args.research, ctx.environ)
    if ctx.args.action == "render":
        return render_research(ctx, research)
    folder = os.path.join(research.folder, "report")
    name = "report.html" if ctx.args.action == "open" else "report.md"
    path = os.path.join(folder, name)
    rendered = None
    if _stale(research, path):
        rendered = render_research(ctx, research)
        if rendered.status not in ("OK", "WARN"):
            return rendered
        if not os.path.isfile(path):   # the research's formats leave it out
            raise UsageError(_("the report has no {file}: render it with --formats md,html").format(file=name),
                             values={"REASON": "no-file", "RESEARCH": research.id})
    rel = os.path.relpath(path, ctx.project).replace(os.sep, "/")
    r = Result("OK", {"RESEARCH": research.id, "FILE": rel, "RENDERED": rendered is not None})
    r.table("files", [{"file": rel, "rendered": rendered is not None}], hidden=True)
    if ctx.args.action == "show":
        if ctx.human:
            with open(path, encoding="utf-8") as fh:
                r.raw = fh.read()
        return r
    r.set("OPENED", open_folder(path))
    return r
