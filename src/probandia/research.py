"""Finding families and researches inside a project.

A research lives in ``families/<family>/research/<id>/``. A research argument
is its identifier or any unique prefix of it; when it is omitted, the command
takes the open research whose pass this session holds, otherwise the most
recent open research.
"""
import os

from probandia.errors import UsageError
from probandia.i18n import _


class Research:
    def __init__(self, project, family, rid):
        self.project = project
        self.family = family
        self.id = rid
        self.folder = os.path.join(project, "families", family, "research", rid)

    @property
    def events_path(self):
        return os.path.join(self.folder, "events.jsonl")

    @property
    def work(self):
        return os.path.join(self.folder, "work")

    @property
    def family_folder(self):
        return os.path.join(self.project, "families", self.family)

    def meta(self):
        from probandia.util import yamlio   # not at import: a hook finds the research without YAML (T145)

        return yamlio.load(os.path.join(self.folder, "research.yaml"))

    def __repr__(self):
        return f"Research({self.family!r}, {self.id!r})"


def all_researches(project):
    out = []
    root = os.path.join(project, "families")
    if not os.path.isdir(root):
        return out
    for family in sorted(os.listdir(root)):
        rdir = os.path.join(root, family, "research")
        if not os.path.isdir(rdir):
            continue
        for rid in sorted(os.listdir(rdir)):
            if os.path.isfile(os.path.join(rdir, rid, "research.yaml")):
                out.append(Research(project, family, rid))
    return out


def find_research(project, ref=None, environ=None, fallback=False):
    """The research named by ``ref`` (an identifier or a unique prefix). When
    ``ref`` is None: the only open research, or the open one whose pass lock this
    session holds. Several open and none held: AmbiguousResearch, since a write to
    the wrong journal is never undone; ``fallback`` (the hooks) takes the newest."""
    found = all_researches(project)
    if ref:
        exact = [r for r in found if r.id == ref]
        matches = exact or [r for r in found if r.id.startswith(ref)]
        if not matches:
            from probandia.suggest import lines

            raise UsageError(_("no research matches {ref}").format(ref=ref), lines=lines(ref, [r.id for r in found]))
        if len(matches) > 1:
            from probandia.errors import AmbiguousResearch

            raise AmbiguousResearch(_("{ref} matches several researches: {ids}").format(
                ref=ref, ids=", ".join(r.id for r in matches[:5])), ref, [r.id for r in matches])
        return matches[0]
    open_ones = []
    for r in found:
        meta = r.meta() or {}
        if meta.get("status", "open") == "open":
            open_ones.append((str(meta.get("created", "")), r))
    if not open_ones:
        raise UsageError(_("no open research in this project"))
    newest_first = [r for _c, r in reversed(sorted(open_ones, key=lambda x: x[0]))]
    if len(newest_first) > 1:   # several open: the one this session's pass works on
        from probandia.util.locks import Locks, session_id

        locks, me = Locks(project), session_id(environ)
        for r in newest_first:
            info, expired = locks.status(f"research:{r.id}")
            if info and not expired and (info.get("owner") or {}).get("session") == me:
                return r
        if not fallback:
            from probandia.errors import AmbiguousResearch

            ids = [r.id for r in newest_first]
            raise AmbiguousResearch(_("{n} researches are open and this session holds none of their passes: "
                                      "name the research").format(n=len(ids)), None, ids,
                                    values={"REASON": "research-not-named", "OPEN": len(ids)},
                                    lines=[f"open={i}" for i in ids[:10]])
    return newest_first[0]


def family_folder(project, family):
    folder = os.path.join(project, "families", family)
    if not os.path.isfile(os.path.join(folder, "family.yaml")):
        from probandia.lifecycle import families
        from probandia.suggest import lines

        raise UsageError(_("no family {family} in this project").format(family=family),
                         lines=lines(family, families(project)))
    return folder


def default_family(project):
    """The only family of the project, or a usage error asking for --family."""
    root = os.path.join(project, "families")
    families = sorted(f for f in os.listdir(root)
                      if os.path.isfile(os.path.join(root, f, "family.yaml"))) if os.path.isdir(root) else []
    if len(families) == 1:
        return families[0]
    if not families:
        raise UsageError(_("no family in this project"))
    raise UsageError(_("several families: name one with --family ({names})").format(
        names=", ".join(families)))


def create_research(project, family, question, language, actor, config=None, now=None, slug=None,
                    instructions=None):
    """Writes ``research.yaml`` for a new research, with its language fixed at creation
    (``new`` detects it, in the order of the language sources). Returns the Research."""
    from probandia.lang.detect import normalize
    from probandia.util.fs import iso, utc_now
    from probandia.util.ids import slugify
    from probandia.util import yamlio
    from probandia.util.schema import validate_document

    now = now or utc_now()
    rid = slug or f"{now.strftime('%Y-%m-%d')}-{slugify(question, max_length=53)}"
    research = Research(project, family, rid)
    if os.path.exists(research.folder):
        raise UsageError(_("the research {id} already exists").format(id=rid))
    get = (lambda k: config.get(k)) if config is not None else (lambda k: None)
    created_by = {"harness": actor.get("harness") or "cli", "agent": actor.get("agent") or "session"}
    if actor.get("model"):
        created_by["model"] = actor["model"]
    doc = {"schema": 1, "id": rid, "family": family, "question": question,
           "language": normalize(language) or "en", "mode": get("report.mode") or "journal",
           "numbering": get("report.numbering") or "arabic",
           "formats": list(get("report.formats") or ["md", "html"]), "created": iso(now),
           "created_by": created_by, "forked_from": None, "run": {"mode": "session"},
           "instructions": [{"pass": 1, "ts": iso(now), "text": text} for text in instructions or []],
           "status": "open", "passes": 0}
    doc["questions"] = _questions(project, family, question)
    validate_document("research", doc, "research.yaml")
    os.makedirs(research.folder)
    yamlio.dump(os.path.join(research.folder, "research.yaml"), doc)
    return research


def _questions(project, family, question):
    """The questions of a new research, read from its text with what the family
    already knows: its persons, places and period (GPS1-T2)."""
    from probandia.indexes import FamilyIndexes
    from probandia.proof.questions import from_text
    from probandia.util import yamlio

    path = os.path.join(project, "families", family, "family.yaml")
    meta = (yamlio.load(path) or {}) if os.path.isfile(path) else {}
    idx = FamilyIndexes(project, family)
    try:
        persons, places = idx.items("persons"), idx.items("places")
    except Exception:  # noqa: BLE001 — an index that does not read yet never stops a research from starting
        persons, places = [], []
    return from_text(question, meta, persons, places)
