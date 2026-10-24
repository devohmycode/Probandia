"""The rules of the workshop, checked before any push (WS3-T4): a fact that breaks
one does not go, the others do. The rules are the workshop's own (its CLAUDE.md
and CONVENTIONS.md, its outils/verifier.py): three markers on every fact, volet
and chapter in Roman numerals, a known report outside the report of origin,
``volet_refute`` on a refuted fact, an image present in ``sources/``, ids of the
workshop's form and links to persons it knows.
"""
import os
import re

from probandia.i18n import _
from probandia.importer import ROMAN, STATUSES, WID

RULES = ("three-markers", "roman", "chapter", "provenance", "refutation", "image", "id", "links")
HEADING = re.compile(r"<h[1-3]\b[^>]*>\s*([IVXLCDM]+)[.)]", re.I)


def last_chapter(ctx, report, origine):
    """The highest chapter a report of the workshop has: the numbered headings of its
    rapport.html, and the chapters of its facts in personnes.yaml (0 for none)."""
    from probandia import workshop

    cache = ctx.__dict__.setdefault("_chapters", {})
    if report not in cache:
        found = [0]
        path = os.path.join(ctx.folder, "rapports", report or "", "rapport.html")
        if report and os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                found += [workshop.roman_value(m.upper()) for m in HEADING.findall(fh.read())]
        for f in workshop._facts(ctx.people):
            if f.get("rapport") == report or (origine and not f.get("rapport")):
                found.append(workshop.roman_value(str(f.get("chapitre") or "")))
        cache[report] = max(found)
    return cache[report]


def check(t, ctx, adding=()):
    """[(rule, message)] that block a Translation ``t``; ``adding``: the workshop ids
    of the persons the same push adds."""
    f = t.fact
    out = []
    missing = [k for k in ("statut", "volet", "chapitre") if not f.get(k)]
    if missing:
        out.append(("three-markers", _("{fact}: no {keys}: every fact of the workshop carries statut, volet and "
                                       "chapitre (its rule of the three markers)").format(
            fact=t.id, keys=", ".join(missing))))
    if f.get("statut") and str(f["statut"]) not in STATUSES:
        out.append(("three-markers", _("{fact}: statut {value} is not one of the workshop's: acte, index, hypothese, "
                                       "refute").format(fact=t.id, value=f["statut"])))
    for key in ("volet", "chapitre", "volet_refute"):
        if f.get(key) and not ROMAN.match(str(f[key])):
            out.append(("roman", _("{fact}: {key} {value} is not in Roman numerals, as the workshop writes "
                                   "them").format(fact=t.id, key=key, value=f[key])))
    research = t.research
    if not t.linked and research and f.get("chapitre") and ROMAN.match(str(f["chapitre"])):
        from probandia import workshop

        last = last_chapter(ctx, research.get("rapport"), research.get("origine"))
        if workshop.roman_value(str(f["chapitre"])) > last + 1:
            out.append(("chapter", _("{fact}: chapter {value} is unknown to the report {report}, whose last chapter "
                                     "is {last}: a chapter of the workshop is written in order").format(
                fact=t.id, value=f["chapitre"], report=research.get("rapport"), last=last or "-")))
    if not t.linked:
        if not research:
            out.append(("provenance", _("{fact}: its research has no report of the workshop: tie it to one first "
                                        "(workshop link)").format(fact=t.id)))
        elif not research.get("origine") and f.get("rapport") not in ctx.reports and \
                (ctx.wpersons.get(t.person) or {}).get("rapport") not in ctx.reports:
            out.append(("provenance", _("{fact}: rapport {value} is unknown: outside the report of origin, each "
                                        "fact names its folder of rapports/").format(
                fact=t.id, value=f.get("rapport") or "-")))
    if f.get("statut") == "refute" and not f.get("volet_refute"):
        out.append(("refutation", _("{fact}: a refuted fact stays, with volet_refute, the volet of its "
                                    "refutation; it is never deleted").format(fact=t.id)))
    if t.missing:
        out.append(("image", _("{fact}: the image {name} is not in the workshop's sources/: put it there, "
                               "Probandia never copies it").format(fact=t.id, name=t.missing)))
    if not WID.match(str(t.person or "")):
        out.append(("id", _("{fact}: {id} is not an id of the workshop (lower case letters and digits, joined by "
                            "hyphens)").format(fact=t.id, id=t.person)))
    known = set(ctx.wpersons) | set(adding)
    for key in ("epoux", "epouse"):
        if t.key == "unions" and f.get(key) and f[key] not in known:
            out.append(("links", _("{fact}: {id} is not a person of the workshop, nor one this push adds").format(
                fact=t.id, id=f[key])))
    if t.key == "unions" and not (f.get("epoux") and f.get("epouse")):
        out.append(("links", _("{fact}: a union of the workshop names its two spouses").format(fact=t.id)))
    return out
