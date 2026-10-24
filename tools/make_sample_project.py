"""Writes ``tests/sample-project/``: an invented family for the integration tests (SPECS § 14.4); and
``tests/sample-project-gps/``, the same family with a research that meets the Genealogical Proof Standard.

    python tools/make_sample_project.py

Five generations, 30 persons, invented places and archives, one research of two
passes in journal mode. Everything is fixed (ids, timestamps): running the script
again writes the same bytes.
"""
import datetime
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import probandia  # noqa: E402,F401
from probandia import events, excerpt  # noqa: E402
from probandia.util import yamlio  # noqa: E402

OUT = os.path.join(ROOT, "tests", "sample-project")
# the same family, with a second research carried to its closing under proof.standard strict (GPS8-T4): a
# project of its own, so that the first keeps its single research
OUT_GPS = os.path.join(ROOT, "tests", "sample-project-gps")
FAMILY = "marchand"
RID = "2026-09-01-ancestors-of-louis-marchand"
SRC = {n: f"src-01JA0000000000000000000{n:03d}" for n in range(1, 10)}
SOURCES = [
    {"id": SRC[1], "repository": "Archives départementales de Valombre", "collection": "État civil, Bourg-Vert",
     "reference": "3 E 41/12", "item": "acte 57", "image_no": "33", "url": "https://archives.valombre.example/ec/41/12/33",
     "accessed": "2026-09-01", "rights": "free", "image": "evidence/images/bourg-vert-1898-57.jpg"},
    {"id": SRC[2], "repository": "Archives départementales de Valombre", "collection": "État civil, Saint-Aubry",
     "reference": "3 E 77/4", "item": "acte 12", "image_no": "8", "accessed": "2026-09-01", "rights": "free"},
    {"id": SRC[3], "repository": "Archives départementales de Valombre", "collection": "Registres paroissiaux, Les Ormes",
     "reference": "1 MI 88", "item": "f. 14", "accessed": "2026-09-02", "rights": "restricted"},
    {"id": SRC[4], "repository": "Cercle généalogique de Valombre", "collection": "Relevés des mariages",
     "reference": "R-1801-1850", "accessed": "2026-09-02", "rights": "free"},
    {"id": SRC[5], "repository": "Archives départementales de Valombre", "collection": "Recensements, Bourg-Vert",
     "reference": "6 M 120", "item": "1846, p. 3", "accessed": "2026-09-02", "rights": "free"},
    {"id": SRC[6], "repository": "Archives communales de Prémoulin", "collection": "Registres paroissiaux",
     "reference": "GG 3", "item": "f. 41", "accessed": "2026-09-03", "rights": "free"},
]
PLACES = [
    {"id": "bourg-vert", "names_as_written": ["Bourg-Vert", "Bourgvert"], "current_name": "Bourg-Vert", "type": "commune"},
    {"id": "saint-aubry", "names_as_written": ["Saint-Aubry", "St Aubry"], "current_name": "Saint-Aubry", "type": "commune"},
    {"id": "les-ormes", "names_as_written": ["Les Ormes"], "current_name": "Les Ormes", "type": "parish"},
    {"id": "premoulin", "names_as_written": ["Prémoulin", "Premoulin"], "current_name": "Prémoulin", "type": "commune"},
    {"id": "valombre", "names_as_written": ["Valombre"], "current_name": "Valombre", "type": "county"},
]
# (sosa, given, surname, sex, birth year, birth place, birth status, death year)
PEOPLE = [
    (1, "Louis", "MARCHAND", "M", 1898, "bourg-vert", "record", 1970),
    (2, "Henri", "MARCHAND", "M", 1870, "bourg-vert", "record", 1931),
    (3, "Jeanne", "ROUSSEL", "F", 1874, "saint-aubry", "record", 1950),
    (4, "Pierre", "MARCHAND", "M", 1841, "bourg-vert", "record", 1899),
    (5, "Marie", "LEBRUN", "F", 1845, "bourg-vert", "index", 1902),
    (6, "Auguste", "ROUSSEL", "M", 1840, "saint-aubry", "record", 1910),
    (7, "Rose", "TANGUY", "F", 1848, "les-ormes", "index", 1919),
    (8, "Jean", "MARCHAND", "M", 1812, "premoulin", "record", 1880),
    (9, "Anne", "GUIBERT", "F", 1815, "premoulin", "index", 1871),
    (10, "Joseph", "LEBRUN", "M", 1810, "bourg-vert", "index", 1860),
    (11, "Louise", "PERRIN", "F", 1818, "bourg-vert", "hypothesis", None),
    (12, "Mathurin", "ROUSSEL", "M", 1808, "saint-aubry", "record", 1874),
    (13, "Perrine", "BLANCHET", "F", 1811, "saint-aubry", "index", 1868),
    (14, "Yves", "TANGUY", "M", 1815, "les-ormes", "index", 1879),
    (15, "Catherine", "LE ROUX", "F", 1820, "les-ormes", "hypothesis", None),
    (16, "François", "MARCHAND", "M", 1785, "premoulin", "record", 1842),
    (17, "Julienne", "HAMEL", "F", 1788, "premoulin", "index", 1850),
    (18, "René", "GUIBERT", "M", 1784, "premoulin", "index", 1840),
    (19, "Marguerite", "COLLET", "F", 1790, "premoulin", "hypothesis", None),
    (20, "Guillaume", "LEBRUN", "M", 1780, "bourg-vert", "index", 1838),
    (21, "Jeanne", "MORIN", "F", 1784, "bourg-vert", "hypothesis", None),
    (22, "Étienne", "PERRIN", "M", 1790, "bourg-vert", "hypothesis", None),
    (24, "Jacques", "ROUSSEL", "M", 1780, "saint-aubry", "index", 1835),
    (25, "Hélène", "DUVAL", "F", 1783, "saint-aubry", "hypothesis", None),
    (26, "Olivier", "BLANCHET", "M", 1785, "saint-aubry", "index", None),
    (27, "Anne", "CORRE", "F", 1787, "saint-aubry", "hypothesis", None),
    (28, "Hervé", "TANGUY", "M", 1788, "les-ormes", "index", 1850),
    (29, "Marie", "LE GALL", "F", 1792, "les-ormes", "hypothesis", None),
    (30, "Yvon", "LE ROUX", "M", 1793, "les-ormes", "hypothesis", None),
    (31, "Anne", "PRIGENT", "F", 1796, "les-ormes", "hypothesis", None),
]
EVENT = "01JA0000000000000000EVT{:03d}"
# Louise PERRIN's father is the open hypothesis h-father-of-louise-perrin: no
# parent link until a record proves it, or the tree would show it as a fact.
UNPROVEN_PARENTS = {11}


def slug(given, surname, year):
    from probandia.util.ids import slugify

    return slugify(f"{given} {surname} {year}")


def build_persons():
    ids = {s: slug(g, n, y) for s, g, n, _x, y, *_r in PEOPLE}
    out = []
    for sosa, given, surname, sex, year, place, status, death in PEOPLE:
        pid = ids[sosa]
        research = RID if sosa < 8 else None
        pass_no = 1 if sosa < 4 else (2 if sosa < 8 else None)
        source = None if status == "hypothesis" else (SRC[1] if sosa == 1 else SRC[2] if sosa < 4 else
                                                      SRC[3] if status == "record" else SRC[5])
        facts = [{"id": f"{pid}.birth", "type": "birth", "status": status,
                  "date": {"value": f"{year}", "qualifier": "exact" if status != "hypothesis" else "about"},
                  "place": {"id": place, "as_written": next(p["names_as_written"][0] for p in PLACES
                                                             if p["id"] == place)},
                  "source": source, "note": "", "research": research, "pass": pass_no}]
        if death:
            facts.append({"id": f"{pid}.death", "type": "death", "status": "index" if source else "hypothesis",
                          "date": {"value": f"{death}", "qualifier": "exact"}, "place": None,
                          "source": SRC[5] if source else None, "note": "", "research": research,
                          "pass": pass_no})
        father, mother = (None, None) if sosa in UNPROVEN_PARENTS else (ids.get(2 * sosa), ids.get(2 * sosa + 1))
        spouses = []
        partner = sosa + 1 if sosa % 2 == 0 else sosa - 1
        if sosa > 1 and partner in ids:
            husband = ids[sosa] if sosa % 2 == 0 else ids[partner]
            spouses.append({"person": ids[partner], "marriage": f"{husband}.marriage"})
            if sosa % 2 == 0:
                facts.append({"id": f"{pid}.marriage", "type": "marriage", "status": "index",
                              "date": {"value": f"{year + 26}", "qualifier": "about"},
                              "place": {"id": place, "as_written": None}, "source": SRC[4], "note": "",
                              "research": research, "pass": pass_no})
        out.append({"id": pid, "names": {"given": given, "surname": surname}, "sex": sex, "living": "auto",
                    "parents": {"father": father, "mother": mother}, "spouses": spouses, "facts": facts})
    return out, ids


def build_events(persons, ids):
    actor = {"harness": "cli", "agent": "session"}
    n = [0]

    def ev(pass_no, type_, payload, minute):
        n[0] += 1
        return {"id": EVENT.format(n[0]), "ts": f"2026-09-0{pass_no}T10:{minute:02d}:00Z", "pass": pass_no,
                "actor": actor, "type": type_, "payload": payload, "refs": [], "supersedes": None}
    by_pass = {1: [], 2: []}
    for p in persons:
        for f in p["facts"]:
            if f.get("research") == RID:
                by_pass[f["pass"]].append(f)
    out = []
    for p_no, title, body in ((1, "Les parents de Louis", "Louis MARCHAND naît à Bourg-Vert "
                               "[[f:{root}.birth]]. Ses parents sont [[p:{father}]] et [[p:{mother}]]."),
                              (2, "Les grands-parents", "Henri est le fils de [[p:{gf}]]; Jeanne la fille de "
                               "[[p:{gf2}]]. Un négatif a été vérifié aux Ormes.")):
        minute = 0
        out.append(ev(p_no, "pass.started", {"n": p_no, "run": {"mode": "session"}, "instructions": []}, minute))
        out.append(ev(p_no, "plan.made", {"plan": f"work/plan-{p_no}.yaml", "question_type": "parents"}, 1))
        out.append(ev(p_no, "search.logged", {"search": f"s-01JA00000000000000000SRC{p_no:02d}"}, 2))
        for i, f in enumerate(by_pass[p_no]):
            out.append(ev(p_no, "fact.asserted", {"fact": f}, 3 + i))
        text = body.format(root=ids[1], father=ids[2], mother=ids[3], gf=ids[4], gf2=ids[6])
        section = {"id": f"01JA000000000000000000SEC{p_no}", "parent": None, "kind": "chapter", "title": title,
                   "body_md": text, "facts": [f["id"] for f in by_pass[p_no]]}
        out.append(ev(p_no, "section.added", {"section": section}, 40))
        if p_no == 1:
            out.append(ev(1, "branch.added", {"root": ids[1], "persons": [ids[1], ids[2], ids[3]]}, 41))
        out.append(ev(p_no, "pass.ended", {"n": p_no, "summary": "parents found; look for the grandparents"
                                                   if p_no == 1 else "grandparents found; the Perrin line is open",
                                           "units": {}, "native_searches": 0, "duration_s": 900}, 50))
    return out


def searches():
    common = {"research": RID, "kind": "archive", "family": None, "filters": None, "support": "image",
              "source_state": "ok", "recheck_if": None, "recheck_after": None, "units": None, "proves": None,
              "failure": None}
    return [
        dict(common, id="s-01JA00000000000000000SRC01", ts="2026-09-01T10:02:00Z", pass_=None, pass_no=1,
             engine="ad-valombre", query="MARCHAND Bourg-Vert 1898", variants=["Marchand", "Marchant"],
             window={"from": 1897, "to": 1899, "places": ["Bourg-Vert"]}, results=1, result="positive",
             witness=None),
        dict(common, id="s-01JA00000000000000000SRC02", ts="2026-09-02T10:02:00Z", pass_no=2,
             engine="ad-valombre", query="PERRIN Les Ormes 1818", variants=["Perrin", "Perin"],
             window={"from": 1815, "to": 1821, "places": ["Les Ormes"]}, results=0, result="negative",
             witness={"operation": "search", "args": {"q": "TANGUY"}, "expected": "at least 1",
                      "passed": True, "ts": "2026-09-02T09:50:00Z"}, recheck_if="ad-valombre covers 1818"),
    ]


# GPS8-T4: a second research, carried to its closing under proof.standard strict: structured questions, the
# locality guide of Bourg-Vert, a settled exhaustiveness matrix, a conflict resolved, two reviewed proof
# arguments, typed citations and a timeline. The departmental archives of Bourg-Vert burned in 1871; the town
# hall kept its copy of the registers, and the ten-year index, copied later, gives 1871 for a birth of 1870.
RID2 = "2026-09-04-birth-of-henri-marchand"
HENRI = "henri-marchand-1870"
TYPED = [
    {"id": SRC[7], "type": "civil-registration", "jurisdiction": "Bourg-Vert", "register": "naissances, 1870",
     "repository": "Archives communales de Bourg-Vert", "reference": "1 E 12", "act": "naissance", "act_no": "31",
     "act_date": "1870-03-14", "accessed": "2026-09-04", "rights": "free",
     "transcription": f"evidence/transcriptions/{SRC[7]}.md"},
    {"id": SRC[8], "type": "decennial-table", "jurisdiction": "Bourg-Vert", "register": "1863-1872",
     "repository": "Archives départementales de Valombre", "reference": "3 E 41/TD 7", "page": "4",
     "url": "https://archives.valombre.example/td/41/7/4", "accessed": "2026-09-04", "rights": "free"},
    {"id": SRC[9], "type": "census", "jurisdiction": "Bourg-Vert", "act_date": "1872",
     "repository": "Archives départementales de Valombre", "reference": "6 M 121", "item": "p. 5",
     "accessed": "2026-09-04", "rights": "free"},
]
# TRUST1-T7: the act of Henri's birth, as transcribed from the town hall's register, and the page of the
# ten-year index, kept in the family's evidence (both invented, free to reuse)
ACT_LINES = [
    "N° 31 Marchand Henri",
    "L'an mil huit cent soixante-dix, le quatorze mars, à dix heures du matin,",
    "par devant nous maire de Bourg-Vert, est comparu Pierre Marchand, cultivateur,",
    "âgé de vingt-neuf ans, lequel nous a présenté un enfant du sexe masculin né ce jour,",
    "de lui et de Marie Lebrun, son épouse, auquel il a donné le prénom d'Henri.",
    "Témoins : Joseph Lebrun, aïeul, et Jean Guibert, voisin.",
]
ACT_PERSONS = [
    ("child", "Marchand Henri", "Henri MARCHAND", "", "Bourg-Vert", "", ""),
    ("declarant", "Pierre Marchand", "Pierre MARCHAND", "29", "cultivateur, Bourg-Vert", "father", "signed"),
    ("mother", "Marie Lebrun", "Marie LEBRUN", "", "Bourg-Vert", "mother", ""),
]
ACT_NORMALISED = ("Number 31, Marchand, Henri. On 14 mars 1870, at ten in the morning, before the mayor of Bourg-Vert "
                  "appeared Pierre Marchand, farmer, aged 29, who presented a male child born that day of him and of "
                  "Marie Lebrun, his wife, named Henri. Witnesses: Joseph Lebrun, grandfather, and Jean Guibert, "
                  "neighbour.")
TABLE_URL = "https://archives.valombre.example/td/41/7/4"
TABLE_PAGE = ("Tables décennales de Bourg-Vert, 1863-1872. Naissances, lettre M.\n\n"
              "MARCHAND Henri, 14 mars 1871. MARCHAND Marie, 2 juin 1866. MOREL Jean, 8 avril 1869.")
ARCHIVES = [
    {"id": "ad_valombre", "name": "Archives départementales de Valombre", "nature": "image",
     "reliability": "civil registers, ten-year indexes and censuses (images); the registers of 1870-1872 burned in 1871",
     "coverage": {"types": ["birth", "marriage", "death", "decennial_table", "census"], "years": [1792, 1936],
                  "places": ["FR-VB"]},
     "access": {"mode": "browser", "third_party": "forbidden", "hosts": ["archives.valombre.example"]},
     "image_rights": "free"},
    {"id": "ac_bourg_vert", "name": "Archives communales de Bourg-Vert", "nature": "image",
     "reliability": "the town hall's copy of the civil registers",
     "coverage": {"types": ["birth", "marriage", "death"], "years": [1792, 1936], "places": ["FR-VB"]},
     "access": {"mode": "browser", "third_party": "forbidden", "hosts": ["mairie.bourg-vert.example"]},
     "image_rights": "free"},
]
GUIDE = {
    "jurisdictions": [
        {"level": "commune", "name": "Bourg-Vert", "from": "1790", "to": None, "source": "catalogue:invented"},
        {"level": "department", "name": "Valombre", "from": "1790", "to": None, "source": "catalogue:invented",
         "note": "department VB"},
        {"level": "country", "name": "FR", "from": None, "to": None, "source": "catalogue:invented"}],
    "repositories": [
        {"name": "Archives départementales de Valombre", "archive": "ad_valombre", "source": "catalogue:archives",
         "holdings": [{"type": "birth", "years": [1792, 1936], "reference": "3 E 41"},
                      {"type": "decennial_table", "years": [1802, 1932], "reference": "3 E 41/TD"},
                      {"type": "census", "years": [1836, 1936], "reference": "6 M"}]},
        {"name": "Archives communales de Bourg-Vert", "archive": "ac_bourg_vert", "source": "catalogue:archives",
         "holdings": [{"type": "birth", "years": [1792, 1936], "reference": "1 E"}]}],
    "guide": {"built": "2026-09-04", "sources": ["catalogue:invented", "catalogue:archives"]},
}
DIRECT = {"source": "original", "information": "primary", "evidence": "direct"}
TABLE = {"source": "derivative", "information": "secondary", "evidence": "direct"}
QUESTIONS = [
    {"id": "Q1", "text": "Quand et où est né Henri MARCHAND ?", "type": "birth", "persons": [HENRI],
     "window": {"from": 1869, "to": 1871}, "places": ["bourg-vert"], "status": "answered",
     "conclusion": [f"{HENRI}.birth"], "updated": "2026-09-04T11:10:00Z"},
    {"id": "Q2", "text": "Qui sont les parents d'Henri MARCHAND ?", "type": "parents", "persons": [HENRI],
     "window": {"from": 1869, "to": 1871}, "places": ["bourg-vert"], "status": "answered",
     "conclusion": [f"{HENRI}.birth"], "updated": "2026-09-04T11:11:00Z"},
]
ANALYSIS = {
    "id": f"an-{HENRI}-birth", "question": "Q1", "research": RID2, "person": HENRI, "fact_kind": "birth",
    "items": [
        {"source": SRC[7], "fact": f"{HENRI}.birth", "asserts": "1870", "informant": "le père, à la déclaration",
         "axes": dict(DIRECT)},
        {"source": SRC[8], "fact": f"{HENRI}.birth.2", "asserts": "1871",
         "informant": "le greffier qui dressa la table, après l'incendie", "axes": dict(TABLE)}],
    "resolution": {"value": "1870", "fact": f"{HENRI}.birth",
                   "reasoning": "L'acte fut dressé à la mairie le jour de la déclaration, par le père ; la table, "
                                "recopiée après l'incendie de 1871, est dérivée et se trompe d'année"},
    "status": "resolved"}
PARTS = {
    "Q1": {"question": "Quand et où est né Henri MARCHAND ?",
           "sources": "L'acte de naissance du registre de la mairie (1870) ; la table décennale 1863-1872.",
           "analysis": "L'acte est un original dressé par l'officier d'état civil sur la déclaration du père ; la "
                       "table est une copie dressée après l'incendie de 1871.",
           "correlation": "Le recensement de 1872 donne à Henri deux ans, ce qui s'accorde avec 1870.",
           "conflicts": "La table donne 1871 : une erreur de copie, l'acte original fait foi.",
           "conclusion": "Henri MARCHAND est né à Bourg-Vert le 14 mars 1870."},
    "Q2": {"question": "Qui sont les parents d'Henri MARCHAND ?",
           "sources": "L'acte de naissance du registre de la mairie (1870).",
           "analysis": "Le père déclare lui-même la naissance et nomme la mère : information primaire.",
           "correlation": "Le recensement de 1872 montre Henri au foyer de Pierre et de Marie.",
           "conflicts": "La table décennale ne contredit que l'année, pas la filiation.",
           "conclusion": "Henri MARCHAND est le fils de Pierre MARCHAND et de Marie LEBRUN."},
}


# the source types a question expects that do not apply, and why (matrix justify)
NOT_APPLICABLE = [
    {"question": "Q2", "type": "notarial", "reason": "l'acte de naissance nomme les deux parents ; aucun acte "
     "notarié n'est attendu pour un nouveau-né", "ts": "2026-09-04T10:55:00Z", "agent": "session"},
    {"question": "Q2", "type": "military_registers", "reason": "Henri, de la classe 1890, n'a pas de matricule "
     "dans la fenêtre 1869-1871", "ts": "2026-09-04T10:56:00Z", "agent": "session"},
    {"question": "Q2", "type": "registration", "reason": "aucune mutation ni succession n'est attendue pour la "
     "naissance d'un enfant", "ts": "2026-09-04T10:57:00Z", "agent": "session"},
]


def proofs():
    out = []
    for q in QUESTIONS:
        out.append({"id": f"pf-{q['id'].lower()}-{RID2}", "research": RID2, "question": q["id"],
                    "conclusion": list(q["conclusion"]), "analyses": [ANALYSIS["id"]], "parts": PARTS[q["id"]],
                    "review": {"state": "accepted", "rounds": [{
                        "date": "2026-09-04T11:0{}:00Z".format(5 + int(q["id"][1])), "reviewer": "contradictor",
                        "returned": "objection: un autre Henri MARCHAND est né à Bourg-Vert vers 1870.",
                        "objections": [{"n": 1, "text": "Un autre Henri MARCHAND est né à Bourg-Vert vers 1870.",
                                        "fact": f"{HENRI}.birth",
                                        "would_settle": "la table décennale, qui ne nomme qu'un Henri MARCHAND",
                                        "answer": "La table 1863-1872 ne compte qu'un Henri MARCHAND.",
                                        "state": "answered"}]}]}})
    return out


def gps_searches():
    common = {"research": RID2, "kind": "archive", "family": None, "support": "image", "source_state": "ok",
              "recheck_if": None, "recheck_after": None, "units": None, "proves": None, "failure": None,
              "variants": ["Marchand", "Marchant"], "witness": None, "result": "positive", "pass": 1}
    return [
        dict(common, id="s-01JA00000000000000000SRC03", ts="2026-09-04T10:02:00Z", engine="ac_bourg_vert",
             query="MARCHAND Bourg-Vert naissances 1870", filters={"archive": "ac_bourg_vert"},
             window={"from": 1869, "to": 1871, "places": ["Bourg-Vert"]}, results=1),
        dict(common, id="s-01JA00000000000000000SRC04", ts="2026-09-04T10:03:00Z", engine="ad_valombre",
             query="MARCHAND tables décennales Bourg-Vert 1863-1872",
             filters={"archive": "ad_valombre", "types": ["decennial_tables"]},
             window={"from": 1863, "to": 1872, "places": ["Bourg-Vert"]}, results=1),
        dict(common, id="s-01JA00000000000000000SRC05", ts="2026-09-04T10:04:00Z", engine="ad_valombre",
             query="MARCHAND recensement Bourg-Vert 1872", filters={"archive": "ad_valombre", "types": ["census"]},
             window={"from": 1869, "to": 1872, "places": ["Bourg-Vert"]}, results=1),
    ]


def gps_events(table_fact):
    actor = {"harness": "cli", "agent": "session"}
    n = [0]

    def ev(type_, payload, minute, pass_no=1, refs=()):
        n[0] += 1
        return {"id": f"01JA0000000000000000GPS{n[0]:03d}", "ts": f"2026-09-04T{10 + minute // 60}:{minute % 60:02d}:00Z",
                "pass": pass_no, "actor": actor, "type": type_, "payload": payload, "refs": list(refs),
                "supersedes": None}
    out = [ev("pass.started", {"n": 1, "run": {"mode": "session"}, "instructions": []}, 0),
           ev("plan.made", {"plan": "work/plan-1.yaml", "question_type": "birth"}, 1)]
    out += [ev("search.logged", {"search": s["id"]}, 2 + i) for i, s in enumerate(gps_searches())]
    out += [ev("fact.asserted", {"fact": table_fact}, 10),
            ev("analysis.recorded", {"analysis": ANALYSIS["id"], "status": "resolved",
                                     "resolution": ANALYSIS["resolution"]}, 20, refs=[ANALYSIS["id"]])]
    out += [ev("proof.recorded", {"proof": p["id"], "question": p["question"], "state": "accepted"}, 30 + i,
               refs=[p["id"]]) for i, p in enumerate(proofs())]
    body = (f"L'acte de naissance d'Henri, au registre de la mairie, donne 1870 [[f:{HENRI}.birth]] ; la table "
            f"décennale, recopiée après l'incendie de 1871, donne 1871 [[f:{HENRI}.birth.2]]. L'acte fait foi.")
    out.append(ev("section.added", {"section": {"id": "01JA000000000000000000GPS1", "parent": None,
                                                "kind": "chapter", "title": "La naissance d'Henri",
                                                "body_md": body, "facts": [f"{HENRI}.birth.2"]}}, 40))
    out.append(ev("pass.ended", {"n": 1, "summary": "birth and parents of Henri proven", "units": {},
                                 "native_searches": 0, "duration_s": 1200}, 50))
    for i, q in enumerate(QUESTIONS):
        out.append(ev("question.added", {"question": q["id"], "status": "open"}, 51 + i))
    for i, q in enumerate(QUESTIONS):
        out.append(ev("question.updated", {"question": q["id"], "status": "answered", "conclusion": q["conclusion"]},
                      70 + i))
    return out


def gps_case(out, fam, persons):
    """Writes the second research and what it adds to the family's indexes."""
    from probandia.proof import matrix
    from probandia.research import Research

    idx = os.path.join(fam, "index")
    henri = next(p for p in persons if p["id"] == HENRI)
    birth = next(f for f in henri["facts"] if f["type"] == "birth")
    birth.update(source=SRC[7], date={"value": "1870-03-14", "qualifier": "exact"}, evidence=dict(DIRECT))
    table_fact = {"id": f"{HENRI}.birth.2", "type": "birth", "status": "index",
                  "date": {"value": "1871", "qualifier": "exact"}, "place": {"id": "bourg-vert", "as_written": "Bourg-Vert"},
                  "source": SRC[8], "note": "", "research": RID2, "pass": 1, "evidence": dict(TABLE)}
    henri["facts"].insert(henri["facts"].index(birth) + 1, table_fact)
    # TRUST1-T7: each birth fact quotes its passage, the act from its transcription, the index from its page
    from probandia import transcription as T

    path = T.path_for(fam, SRC[7])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = T.template(SRC[7], "1 E 12, vue 8", "fr", "cursive", ACT_LINES)
    text = text.replace("| " + " | ".join(T.PERSON_COLUMNS) + " |\n|" + "---|" * len(T.PERSON_COLUMNS) + "\n",
                        "| " + " | ".join(T.PERSON_COLUMNS) + " |\n|" + "---|" * len(T.PERSON_COLUMNS) + "\n"
                        + "".join(f"| {' | '.join(row)} |\n" for row in ACT_PERSONS))
    text = text.replace("## Normalised transcription\n\n…", "## Normalised transcription\n\n" + ACT_NORMALISED)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    birth["excerpt"] = excerpt.from_lines(ACT_LINES, 1, 4)
    page = os.path.join(fam, "evidence", "pages", f"{SRC[8]}.md")
    os.makedirs(os.path.dirname(page), exist_ok=True)
    with open(page, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"<!-- {TABLE_URL} -->\n{TABLE_PAGE}\n")
    quoted = "MARCHAND Henri, 14 mars 1871"
    table_fact["excerpt"] = excerpt.from_page(TABLE_PAGE, excerpt.offset_of(TABLE_PAGE, quoted), len(quoted),
                                              url=TABLE_URL, captured="2026-09-04")
    yamlio.dump(os.path.join(idx, "analyses.yaml"), {"schema": 1, "analyses": [ANALYSIS]})
    yamlio.dump(os.path.join(idx, "proofs.yaml"), {"schema": 1, "proofs": proofs()})
    os.makedirs(os.path.join(out, "library"), exist_ok=True)
    yamlio.dump(os.path.join(out, "library", "archives.yaml"), {"schema": 1, "archives": ARCHIVES})
    rdir = os.path.join(fam, "research", RID2)
    os.makedirs(rdir)
    yamlio.dump(os.path.join(rdir, "research.yaml"), {
        "schema": 1, "id": RID2, "family": FAMILY, "question": "Quand et où est né Henri MARCHAND, et de qui ?",
        "language": "fr", "mode": "journal", "numbering": "arabic", "formats": ["md", "html"],
        "created": "2026-09-04T09:00:00Z", "created_by": {"harness": "cli", "agent": "session"},
        "forked_from": None, "run": {"mode": "session"}, "instructions": [], "status": "open", "passes": 1,
        "questions": QUESTIONS})
    events.append(os.path.join(rdir, "events.jsonl"), gps_events(table_fact))
    return Research(out, FAMILY, RID2), matrix


def write(out, gps=False):
    """Writes one sample project; with ``gps``, the second research and what it adds (GPS8-T4)."""
    if os.path.exists(out):
        shutil.rmtree(out)
    fam = os.path.join(out, "families", FAMILY)
    for sub in ("index", "research", "evidence/images", "trees"):
        os.makedirs(os.path.join(fam, sub), exist_ok=True)
    with open(os.path.join(out, "probandia.toml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('schema = 1\ngrade = "essential"\n')
    with open(os.path.join(fam, "evidence", "images", "bourg-vert-1898-57.jpg"), "wb") as fh:
        fh.write(b"invented image")
    yamlio.dump(os.path.join(fam, "family.yaml"), {"schema": 1, "id": FAMILY, "name": "MARCHAND",
                                                   "surnames": ["Marchand", "Marchant"],
                                                   "places": ["Bourg-Vert", "Saint-Aubry"],
                                                   "period": [1780, 1970], "language": "fr"})
    persons, ids = build_persons()
    idx = os.path.join(fam, "index")
    research2, matrix = gps_case(out, fam, persons) if gps else (None, None)
    yamlio.dump(os.path.join(idx, "persons.yaml"), {"schema": 1, "persons": persons})
    typed = [dict(x, sha256=excerpt.digest(TABLE_PAGE)) if x["id"] == SRC[8] else x for x in TYPED]   # TRUST1-T4
    yamlio.dump(os.path.join(idx, "sources.yaml"), {"schema": 1, "sources": SOURCES + (typed if gps else [])})
    places = [dict(p, **GUIDE) if gps and p["id"] == "bourg-vert" else p for p in PLACES]
    yamlio.dump(os.path.join(idx, "places.yaml"), {"schema": 1, "places": places})
    rows = []
    for s in searches():
        s = dict(s)
        s["pass"] = s.pop("pass_no")
        s.pop("pass_", None)
        rows.append(s)
    yamlio.dump(os.path.join(idx, "searches.yaml"), {"schema": 1, "searches": rows + (gps_searches() if gps else [])})
    yamlio.dump(os.path.join(idx, "hypotheses.yaml"), {"schema": 1, "hypotheses": [{
        "id": "h-father-of-louise-perrin", "question": "Who was the father of Louise PERRIN?",
        "hypotheses": [{"id": "a", "statement": "Étienne PERRIN", "status": "open"},
                       {"id": "b", "statement": "another Perrin of Bourg-Vert", "status": "open"}],
        "evidence": [], "discriminating": "the baptism of Louise in Les Ormes", "opened": "2026-09-02",
        "closed": None, "outcome": None}]})
    yamlio.dump(os.path.join(idx, "variants.yaml"), {"schema": 1, "surnames": {"Marchand": [
        {"form": "Marchant", "source": SRC[4]}]}, "given": {}})
    yamlio.dump(os.path.join(idx, "non-links.yaml"), {"schema": 1, "non_links": []})
    yamlio.dump(os.path.join(idx, "gaps.yaml"), {"schema": 1, "gaps": [{
        "archive": "ad-valombre", "reference": "3 E 41", "window": {"from": 1870, "to": 1872}, "kind": "destroyed",
        "source": "fire of 1871"}]})
    rdir = os.path.join(fam, "research", RID)
    os.makedirs(rdir)
    yamlio.dump(os.path.join(rdir, "research.yaml"), {
        "schema": 1, "id": RID, "family": FAMILY, "question": "Who were the ancestors of Louis MARCHAND?",
        "language": "fr", "mode": "journal", "numbering": "roman", "formats": ["md", "html"],
        "created": "2026-09-01T09:00:00Z", "created_by": {"harness": "cli", "agent": "session"},
        "forked_from": None, "run": {"mode": "session"}, "instructions": [], "status": "open", "passes": 2})
    events.append(os.path.join(rdir, "events.jsonl"), build_events(persons, ids))
    if gps:   # the matrix of the second research, once every index is written; what does not apply, and why
        doc = matrix.build(research2, not_applicable=NOT_APPLICABLE,
                           now=datetime.datetime(2026, 9, 4, 11, 0, tzinfo=datetime.timezone.utc))
        matrix.write(research2, doc)
    print(f"wrote {out}: {len(persons)} persons")


def main():
    write(OUT)
    write(OUT_GPS, gps=True)


if __name__ == "__main__":
    main()
