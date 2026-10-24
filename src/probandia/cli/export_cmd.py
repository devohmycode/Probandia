"""User commands tree, export and import-gedcom."""
import os

from probandia.cli.data_cmd import actor
from probandia.cli.output import Result
from probandia.errors import UsageError
from probandia.i18n import _


def _family(ctx):
    from probandia.research import default_family, family_folder

    family = getattr(ctx.args, "family", None) or default_family(ctx.project)
    family_folder(ctx.project, family)
    return family


def _language(ctx, family):
    from probandia.cli.report_cmd import locale_dirs, report_language
    from probandia.i18n import Translator
    from probandia.util import yamlio

    meta = yamlio.load(os.path.join(ctx.project, "families", family, "family.yaml")) or {}
    lang, _source = report_language(ctx, {"language": meta.get("language")})
    t = Translator(lang, locale_dirs(ctx))
    if t.missing:
        t = Translator("en")
        lang = "en"
    return lang, t


def _rel(ctx, path):
    return os.path.relpath(path, ctx.project).replace(os.sep, "/")


# tree


def tree_args(p, common):
    p.add_argument("--family", help=_("family slug"))
    p.add_argument("--format", "--tree-format", dest="fmt", choices=("html", "md", "all"),
                   help=_("html, md or all; default: the setting tree.format"))
    p.add_argument("--root", help=_("the person at the root (default: the last branch's root)"))


def tree(ctx):
    from probandia import events, svg, trees, treeview
    from probandia.indexes import FamilyIndexes
    from probandia.research import all_researches
    from probandia.util.fs import atomic_write_text

    family = _family(ctx)
    persons = FamilyIndexes(ctx.project, family).items("persons")
    if not persons:
        raise UsageError(_("the family {family} has no person yet").format(family=family))
    log = [e for r in all_researches(ctx.project) if r.family == family for e in events.read(r.events_path)]
    log.sort(key=lambda e: e.get("ts", ""))
    root = ctx.args.root or treeview.default_root(persons, log)
    if root not in {p["id"] for p in persons}:
        raise UsageError(_("no person {person} in the family").format(person=root))
    lang, t = _language(ctx, family)
    from probandia.report import labels as L

    tr = trees.Tree(persons, ctx.config.get("privacy.living_years"))
    folder = os.path.join(ctx.project, "families", family, "trees")
    os.makedirs(folder, exist_ok=True)
    written = []
    fmt = ctx.args.fmt or ctx.config.get("tree.format") or "all"
    if fmt in ("html", "all"):
        path = os.path.join(folder, "tree.html")
        atomic_write_text(path, treeview.html_page(tr, root, t, lang))
        written.append(path)
        for name, text in (("ancestors.svg", svg.ancestors(tr, root, 5, t(L.LIVING_PERSON), t(L.ANCESTORS_OF))),
                           ("descendants.svg", svg.descendants(tr, root, 3, t(L.LIVING_PERSON),
                                                               t(L.DESCENDANTS_OF)))):
            atomic_write_text(os.path.join(folder, name), text)
            written.append(os.path.join(folder, name))
    if fmt in ("md", "all"):
        path = os.path.join(folder, "tree.md")
        atomic_write_text(path, trees.markdown(tr, root, t(L.LIVING_PERSON),
                                               f"{t(L.TREE)} — {tr.name(root, t(L.LIVING_PERSON))}"))
        written.append(path)
    r = Result("OK", {"FAMILY": family, "ROOT": root, "PERSONS": len(persons), "LANG": lang,
                      "FILES": len(written)})
    for path in written:
        r.data("FILE", _rel(ctx, path))
    r.table("files", [{"file": _rel(ctx, path), "format": os.path.splitext(path)[1][1:]} for path in written],
            hidden=True)
    return r


# export


def export_args(p, common):
    p.add_argument("target", choices=("gedcom7", "gedcom551", "gramps"))
    p.add_argument("--family", help=_("family slug"))
    p.add_argument("--living", choices=("mask", "exclude"), default="mask",
                   help=_("presumed-living persons: masked or left out"))
    p.add_argument("--open-folder", action="store_true", help=_("open the folder of the file once written"))
    p.add_argument("--include-refuted", action="store_true", help=_("export refuted facts too"))
    p.add_argument("--dry-run", action="store_true", help=_("Gramps Web: check the import without keeping it"))


def build_export(ctx, family, version, media_prefix=""):
    from probandia import gedcom
    from probandia.indexes import FamilyIndexes

    idx = FamilyIndexes(ctx.project, family)
    lang, _t = _language(ctx, family)
    return gedcom.Export(idx.items("persons"), idx.items("sources"), idx.items("hypotheses"),
                         idx.items("searches"), idx.items("places"), lang=lang, living=ctx.args.living,
                         include_refuted=ctx.args.include_refuted,
                         living_years=ctx.config.get("privacy.living_years"), version=version,
                         media_prefix=media_prefix, analyses=idx.items("analyses"),
                         confidence=confidence_of_facts(ctx, family),
                         family_dir=os.path.join(ctx.project, "families", family))


def confidence_of_facts(ctx, family):
    """TRUST3-T4: {fact id: (level, name)}, the lowest confidence of the answered questions each fact
    concludes, over the family's researches."""
    from probandia.proof import standard as S
    from probandia.research import all_researches

    out = {}
    for research in all_researches(ctx.project):
        meta = research.meta() or {}
        if research.family != family or not meta.get("questions"):
            continue
        for q in S.of_research(ctx.project, research, meta,
                               strict=ctx.config.get("proof.standard") == "strict"):
            conf = q.get("confidence")
            for fid in (next((x for x in meta["questions"] if x["id"] == q["question"]), {}).get("conclusion")
                        or []) if conf else []:
                if fid not in out or conf["level"] < out[fid][0]:
                    out[fid] = (conf["level"], conf["name"])
    return out


def export(ctx):
    from probandia import gedcom
    from probandia.util.fs import atomic_write_bytes, utc_now

    family = _family(ctx)
    if ctx.args.target == "gramps":
        from probandia import grampsweb

        return grampsweb.export(ctx, family, build_export(ctx, family, 5))
    folder = os.path.join(ctx.project, "exports")
    os.makedirs(folder, exist_ok=True)
    stamp = utc_now().strftime("%Y-%m-%d")
    if ctx.args.target == "gedcom7":
        exp = build_export(ctx, family, 7)
        data = gedcom.gedzip(exp, os.path.join(ctx.project, "families", family))
        path = os.path.join(folder, f"{family}-{stamp}.gdz")
    else:
        prefix = os.path.relpath(os.path.join(ctx.project, "families", family), folder).replace(os.sep, "/") + "/"
        exp = build_export(ctx, family, 5, prefix)
        data = exp.text().encode("utf-8")
        path = os.path.join(folder, f"{family}-{stamp}.ged")
    from probandia.cli import asking

    if os.path.exists(path) and not asking.confirm(ctx, _("{path} already exists. Replace it?").format(
            path=_rel(ctx, path))):
        return asking.declined({"FILE": _rel(ctx, path)})
    atomic_write_bytes(path, data)
    r = Result("OK", {"FAMILY": family, "FORMAT": ctx.args.target, "PERSONS": len(exp.indi),
                      "FAMILIES": len(exp.fams), "SOURCES": len(exp.sour), "MEDIA": len(exp.media),
                      "LIVING": ctx.args.living})
    r.data("FILE", _rel(ctx, path))
    if exp.missing:   # a view no file of the family's folder holds is no reference to nothing: it is left out
        r.status = "WARN"
        r.set("MEDIA_MISSING", len(exp.missing))
        r.line(_("views left out of the export, for no file of the family's folder: {views}").format(
            views=", ".join(exp.missing[:5]) + (" …" if len(exp.missing) > 5 else "")))
    r.table("files", [{"file": _rel(ctx, path), "format": ctx.args.target}], hidden=True)
    r.view = "export"
    r.extra = {"living": len(exp.living), "folder": _rel(ctx, folder)}
    if ctx.args.open_folder:
        open_folder(folder)
    return r


def open_folder(folder):
    """Shows ``folder`` in the file manager of the system, or opens a file in its application;
    False when it cannot."""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            os.startfile(folder)  # a folder of the project, opened for the person
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
    except OSError:
        return False
    return True


# import-gedcom


def import_gedcom_args(p, common):
    p.add_argument("file", help=_("a .ged or .gdz file"))
    p.add_argument("--family", help=_("family slug"))


def import_gedcom(ctx):
    from probandia.gedcom_import import Import
    from probandia.indexes import FamilyIndexes
    from probandia.research import all_researches

    family = _family(ctx)
    if not os.path.isfile(ctx.args.file):
        raise UsageError(_("no file {path}").format(path=ctx.args.file))
    idx = FamilyIndexes(ctx.project, family)
    researches = [r for r in all_researches(ctx.project) if r.family == family]
    research = None
    if researches:
        meta = {r.id: r.meta() or {} for r in researches}
        open_ones = [r for r in researches if meta[r.id].get("status", "open") == "open"] or researches
        research = sorted(open_ones, key=lambda r: str(meta[r.id].get("created", "")))[-1]
    imp = Import(ctx.project, family, ctx.args.file, actor(ctx))
    stage, written = imp.write(idx.items("persons"), idx.items("places"), research)
    matched = sum(1 for _p, why in written for v in why.values() if v != ["no match in the family"])
    r = Result("OK" if research else "WARN",
               {"FAMILY": family, "VERSION": imp.data["version"], "PERSONS": len(imp.data["persons"]),
                "MATCHED": matched, "PROPOSALS": len(written)}, details=_rel(ctx, stage))
    if research is None:
        r.line(_("no research in this family: the file is staged, and no proposal is written"))
    else:
        r.set("RESEARCH", research.id)
    for path, why in written:
        for pid, reasons in why.items():
            r.data("proposal", f"{os.path.basename(path)[:-5]} {pid}: {'; '.join(reasons)}")
    r.table("proposals", [{"proposal": os.path.basename(path)[:-5], "person": pid, "why": "; ".join(reasons)}
                          for path, why in written for pid, reasons in why.items()])
    r.view = "import-gedcom"
    r.line(_("every fact is a hypothesis; review the proposals, then apply them one by one"))
    return r


# transcribe


def transcribe_args(p, common):
    p.add_argument("action", choices=("template", "check", "quote", "ocr", "new", "compare"))
    p.add_argument("target", nargs="?", help=_("a source id (src-…), a transcription file, or an image for ocr"))
    p.add_argument("other", nargs="?", help=_("compare: the second reading, <source>.2 or a transcription file"))
    p.add_argument("--second", action="store_true",
                   help=_("template: the skeleton of a second reading, made without the first"))
    p.add_argument("--image", help=_("new: the image of a record read before its source is proposed"))
    p.add_argument("--family", help=_("family slug"))
    p.add_argument("--language", default="fr", help=_("language of the record"))
    p.add_argument("--script", default="cursive", help=_("script: cursive, print, gothic…"))
    p.add_argument("--name", help=_("check, compare: the person whose name may be doubtful"))
    p.add_argument("--ocr-lang", default="fra", help=_("Tesseract languages, such as fra, deu or frak2021"))
    p.add_argument("--lines", help=_("quote: the lines cited, such as 3-5"))


def _quote(ctx, target, parsed):
    """``transcribe quote <source> --lines a-b`` (TRUST1-T2): the excerpt of a fact, ready for a proposal."""
    import json
    import re

    from probandia import excerpt as X

    m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", ctx.args.lines or "")
    if not m:
        raise UsageError(_("give the lines cited, such as --lines 3-5"))
    first, last = int(m.group(1)), int(m.group(2) or m.group(1))
    try:
        found = X.from_lines(parsed["lines"], first, last)
    except ValueError as err:
        raise UsageError(str(err), values={"REASON": "lines"}) from None
    r = Result("OK", {"SOURCE": parsed["header"].get("Source") or target, "LINES": f"{first}-{last}",
                      "DIGEST": found["sha256"]})
    r.data("excerpt", json.dumps(found, ensure_ascii=False))
    r.line(_("put it in the fact as excerpt; the fact cites this source"))
    return r


def _new(ctx):
    """``transcribe new --image <file>`` (token-economy B5): the id of a source to come, the skeleton of
    its transcription, and its ``sources:`` entry to copy into the proposal."""
    import json

    from probandia import transcription as T
    from probandia.util.fs import atomic_write_text
    from probandia.util.ids import ulid

    if not ctx.args.image:
        raise UsageError(_("give the image read: transcribe new --image <file>"))
    from probandia.images import is_small

    if is_small(ctx.project, os.path.join(ctx.cwd, ctx.args.image)):   # J10: it finds the act, never reads it
        raise UsageError(_("{image} is a small view, or made from one: it finds the act, never reads it; transcribe "
                           "the view saved whole (no \"size\") or a region of it").format(image=ctx.args.image),
                         values={"REASON": "small-view"})
    folder =os.path.join(ctx.project, "families", _family(ctx))
    source = f"src-{ulid()}"
    path = T.path_for(folder, source)
    image = ctx.args.image   # T224: a file of the family is named from the family's folder, as a source names it
    given = os.path.abspath(os.path.join(ctx.cwd, image))
    if os.path.isfile(given) and not os.path.relpath(given, os.path.abspath(folder)).startswith(os.pardir):
        image = os.path.relpath(given, os.path.abspath(folder)).replace(os.sep, "/")
    atomic_write_text(path, T.template(source, image, ctx.args.language, ctx.args.script))
    r = Result("OK", {"SOURCE": source}, details=_rel(ctx, path))
    r.data("source", json.dumps({"id": source, "image": image,
                                 "transcription": os.path.relpath(path, folder).replace(os.sep, "/")},
                                ensure_ascii=False))
    r.line(_("fill the transcription; put this source in the proposal, with its type and the fields "
             "cite --form --type <type> asks for"))
    return r


def _compare(ctx, folder):
    """``transcribe compare <a> <b>`` (T245): where two readings of an act, the second made without the
    first, differ; each divergence a ``doubt=``, the one that touches ``--name`` its ``UNCERTAIN_READING=``."""
    from probandia import transcription as T

    if not ctx.args.other:
        raise UsageError(_("give the two readings: transcribe compare <source> <source>.2"))
    names, read = (ctx.args.target, ctx.args.other), []
    for target in names:
        path = target if os.path.isfile(target) else T.path_for(folder, target)
        if not os.path.isfile(path):
            raise UsageError(_("no transcription {path}").format(path=path))
        with open(path, encoding="utf-8") as fh:
            read.append(T.check(fh.read())[1])
    problems = [_("{name}: the diplomatic transcription is empty").format(name=name)
                for name, parsed in zip(names, read) if parsed["lines"] in ([], ["…"])]
    ids = {parsed["header"].get("Source") for parsed in read} - {None, ""}
    if len(ids) > 1:
        problems.append(_("not the same source: {ids}").format(ids=", ".join(sorted(ids))))
    found = [] if problems else T.compare(read[0]["lines"], read[1]["lines"])
    r = Result("FAIL" if problems else "WARN" if found else "OK",
               {"LINES": len(read[0]["lines"]), "DIVERGENCES": len(found)}, problems)
    if found:
        r.line(_("look at the image again where they differ; a doubt that stays goes under Uncertain readings "
                 "of the first, and into the fact it touches as uncertain_reading"))
        if ctx.args.name:
            reading = T.divergence_for(found, read[0]["lines"], ctx.args.name)
            if reading:
                r.set("UNCERTAIN_READING", reading)
    for d in found:
        r.data("doubt", d["text"])
    return r


def transcribe(ctx):
    from probandia import transcription as T
    from probandia.indexes import FamilyIndexes
    from probandia.util.fs import atomic_write_text

    if ctx.args.action == "new":
        return _new(ctx)
    if not ctx.args.target:
        raise UsageError(_("give a source id, a transcription file, or an image for ocr"))
    if ctx.args.action == "ocr":
        lines = T.tesseract(ctx.args.target, ctx.args.ocr_lang)
        if lines is None:
            return Result.stop("no-tesseract", "vision", values={"IMAGE": ctx.args.target})
        r = Result("OK", {"IMAGE": ctx.args.target, "LINES": len(lines)})
        for i, line in enumerate(lines[:30], 1):
            r.data(str(i), line)
        r.view, r.extra = "ocr", {"lines": lines[:30]}
        return r
    family = _family(ctx)
    folder = os.path.join(ctx.project, "families", family)
    if ctx.args.action == "compare":
        return _compare(ctx, folder)
    target = ctx.args.target
    path = target if os.path.isfile(target) else T.path_for(folder, target)
    if ctx.args.action == "template":
        sources = {s["id"]: s for s in FamilyIndexes(ctx.project, family).items("sources")}
        if target not in sources:
            raise UsageError(_("no source {id} in the family").format(id=target))
        if ctx.args.second:   # T245: the blind second reading, next to the first
            path = T.second_path(folder, target)
        if os.path.exists(path):
            return Result("WARN", {"SOURCE": target}, [_("the transcription already exists: complete it")],
                          details=_rel(ctx, path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from probandia.images import views

        atomic_write_text(path, T.template(target, ", ".join(views(sources[target])), ctx.args.language,
                                           ctx.args.script))   # T247: every view of the act
        r = Result("OK", {"SOURCE": target}, details=_rel(ctx, path))
        if ctx.args.second:
            r.line(_("fill it from the image alone, without opening the first transcription"))
        elif not sources[target].get("transcription"):   # only apply writes the source (TRUST1-T2)
            r.line(_("propose this file as the source's transcription"))
        return r
    if not os.path.isfile(path):
        raise UsageError(_("no transcription {path}").format(path=path))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    problems, parsed = T.check(text)
    if ctx.args.action == "quote":
        return _quote(ctx, target, parsed)
    bad_dates = T.check_dates(parsed["normalised"])
    problems += [f"date not read by dates: {d} ({why})" for d, why in bad_dates]
    doubts = T.doubts_of(parsed)
    r = Result("FAIL" if problems else "OK", {"LINES": len(parsed["lines"]), "PERSONS": len(parsed["persons"]),
                                              "DOUBTS": len(doubts)}, details=_rel(ctx, path))
    state = parsed["image_state"]
    if state and state.split()[0].strip(",;:.").lower() != T.GOOD:   # T246: another copy may read better
        r.set("IMAGE_STATE", state)
        r.line(_("the image is not good ({state}): look for the register's other copy").format(state=state))
    for p in problems:
        r.line(p)
    for d in doubts:
        r.data("doubt", d)
    if ctx.args.name:
        reading = T.reading_for(parsed, ctx.args.name)
        if reading:
            r.set("UNCERTAIN_READING", reading)
    return r
