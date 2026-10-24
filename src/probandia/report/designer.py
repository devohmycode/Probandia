"""The template designer (optimize.md § 4.7 to 4.11): one HTML page, offline,
with no external dependency, that builds a report template and shows it live on
a sample report.

The page is assembled from ``designer/designer.html`` (the shell),
``designer/designer.js`` (the code, also run by Node in the tests),
``designer/sample.json`` (the engine's slots for the sample report, in English
and French, and the labels) and the built-in templates. ``template designer``
writes it into the project, under ``templates/designer/``, and opens it.

``sample.json`` is built from ``tests/sample-project-gps`` by
``tools/make_designer_sample.py``; a test checks that it is up to date.
"""
import datetime
import json
import os
import webbrowser

from probandia.util.fs import atomic_write_text

LANGS = ("en", "fr")
PLACEHOLDER_DATA = "/*@@DATA@@*/"
PLACEHOLDER_CODE = "/*@@CODE@@*/"


def data_dir():
    from probandia.paths import data

    return data("designer")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _json_safe(text):
    """JSON that cannot close the inline <script> it sits in: ``<`` only occurs in its
    strings, where ``\\u003c`` means the same."""
    return text.replace("<", "\\u003c")


def page():
    """The designer page, whole."""
    from probandia.report import template as T

    shell = _read(os.path.join(data_dir(), "designer.html"))
    code = _read(os.path.join(data_dir(), "designer.js"))
    sample = json.loads(_read(os.path.join(data_dir(), "sample.json")))
    builtin = {}
    for name in sorted(os.listdir(T.builtin_dir())):
        if name.endswith(".html"):
            builtin[name[:-5]] = _read(os.path.join(T.builtin_dir(), name))
    data = dict(sample, builtin=builtin, contract=T.CONTRACT)
    blob = "const DATA = " + _json_safe(json.dumps(data, ensure_ascii=False, sort_keys=True)) + ";"
    if "</script" in code.lower():
        raise ValueError("designer.js must not hold </script")
    return shell.replace(PLACEHOLDER_DATA, blob).replace(PLACEHOLDER_CODE, code)


def write(folder, environ=None):
    """Writes ``<folder>/designer/designer.html``; returns its path."""
    path = os.path.join(folder, "designer", "designer.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_text(path, page())
    return path


def open_page(path):
    """Opens the page in the default browser; False when none could be started."""
    try:
        return bool(webbrowser.open(_file_uri(path)))
    except Exception:   # noqa: BLE001 — no browser: the page is still written
        return False


def _file_uri(path):
    from pathlib import Path

    return Path(os.path.abspath(path)).as_uri()


# the sample (tools/make_designer_sample.py)

def _sample_events(log, persons):
    """The sample research, with one more pass that cites a fact of each status and
    corrects one: the preview shows every style."""
    by_status = {}
    for p in persons:
        for f in p.get("facts", []):
            by_status.setdefault(f.get("status"), f["id"])
    last = log[-1]
    n = last["pass"] + 1
    refs = [f"[[f:{by_status[s]}]]" for s in ("record", "index", "hypothesis", "refuted") if s in by_status]
    base = {"actor": last["actor"], "refs": [], "supersedes": None}

    def event(i, type_, payload):
        return dict(base, id=f"01JA0000000000000000DSG{i:03d}", ts=f"2026-09-03T09:{i:02d}:00Z", pass_=n,
                    type=type_, payload=payload)
    extra = [
        event(1, "pass.started", {"n": n, "run": {"mode": "session"}, "instructions": []}),
        event(2, "section.added", {"section": {
            "id": "01JA000000000000000000DSG1", "parent": None, "kind": "chapter", "title": "Synthèse",
            "body_md": "Les faits établis : " + ", ".join(refs) + ".\n\n| Personne | Statut |\n|---|---|\n"
                       "| Louis MARCHAND | acte |\n| Henri MARCHAND | index |", "facts": []}}),
    ]
    revised = by_status.get("index")
    if revised:
        extra.append(event(3, "fact.revised", {"fact": revised, "before": "1870", "after": "1871",
                                               "wrong": "vers 1870", "reason": "relecture de l'acte",
                                               "cause": "misreading"}))
    for e in extra:
        e["pass"] = e.pop("pass_")
    return log + extra


def sample_data(project):
    """The engine's slots for the sample report of ``project``, per language and
    notes mode, and the labels in both languages."""
    from probandia import events
    from probandia.i18n import Translator
    from probandia.indexes import FamilyIndexes
    from probandia.proof import matrix, standard
    from probandia.report import render as R
    from probandia.report import template as T
    from probandia.research import all_researches

    # the first research with structured questions: the preview shows their coverage and conformity (GPS3, GPS8)
    found = all_researches(project)
    research = next((r for r in found if (r.meta() or {}).get("questions")), found[0])
    meta = research.meta() or {}
    docs = FamilyIndexes(project, research.family).load_all()
    # the sample's coverage and conformity (GPS3, GPS8), as on the day the sample was written: the same bytes
    expected = matrix.build(research, meta, now=datetime.datetime(2026, 9, 4, tzinfo=datetime.timezone.utc))
    today = datetime.date(2026, 9, 4)
    log = _sample_events(events.read(research.events_path), docs["persons"].get("persons", []))
    slots = {}
    for lang in LANGS:
        t = Translator(lang)
        report = R.build_report(meta, log, docs, lang, t, numbering_style="arabic", matrix=expected,
                                standard=standard.of_research(project, research, meta, today, docs=docs,
                                                              matrix_doc=expected))
        report.manual = [{"archive": "familysearch", "url": "https://www.familysearch.org/ark:/61903/3:1:EXAMPLE"}]
        slots[lang] = {mode: R.html_slots(report, t, mode) for mode in ("end", "chapter")}
    fr = Translator("fr")
    labels = {msgid: {"en": msgid, "fr": fr(msgid)} for msgid in sorted(T.label_ids())}
    return {"slots": slots, "labels": labels, "research": research.id}
