"""Forking a research at a pass.

The fork gets ``<today>-<slug>``: ``--name``, else the parent's slug with
``-fork-<n>``. It copies ``research.yaml`` (new id, ``forked_from``, new
instructions) and the lines of ``events.jsonl`` up to the ``pass.ended`` of pass
``n``, byte for byte, so the copied chain stays valid. ``report/``, ``trees/``
and ``work/`` are not copied: the report is rendered again. With
``--new-family``, ``family.yaml`` and ``index/`` are copied into the new family,
which the fork then belongs to. The original is never written.
"""
import json
import os
import re
import shutil

from probandia import events
from probandia.errors import UsageError
from probandia.i18n import _
from probandia.research import Research
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now
from probandia.util.ids import is_slug, slugify
from probandia.util.schema import validate_document

DATED = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def fork(project, parent, at=None, name=None, new_family=None, instructions=(), actor=None, now=None):
    now = now or utc_now()
    lines = events.read_lines(parent.events_path)
    ends = {}
    for i, line in enumerate(lines):
        e = json.loads(line)
        if e["type"] == "pass.ended":
            ends[e["pass"]] = i
    if not ends:
        raise UsageError(_("{id} has no completed pass to fork from").format(id=parent.id))
    at = at if at is not None else max(ends)
    if at not in ends:
        raise UsageError(_("pass {n} of {id} is not completed").format(n=at, id=parent.id))
    if name:
        slug = slugify(name, max_length=53)
    else:
        suffix = f"-fork-{at}"
        slug = slugify(DATED.sub("", parent.id), max_length=53 - len(suffix)) + suffix
    rid = f"{now.strftime('%Y-%m-%d')}-{slug}"
    if not is_slug(rid):
        raise UsageError(_("invalid research name {name}").format(name=slug))
    family = parent.family
    if new_family:
        if not is_slug(new_family):
            raise UsageError(_("invalid family name {name}").format(name=new_family))
        family = new_family
    child = Research(project, family, rid)
    if os.path.exists(child.folder):
        raise UsageError(_("the research {id} already exists").format(id=rid))

    if new_family:
        target = os.path.join(project, "families", new_family)
        if os.path.exists(os.path.join(target, "family.yaml")):
            raise UsageError(_("the family {family} already exists").format(family=new_family))
        source = parent.family_folder
        doc = yamlio.load(os.path.join(source, "family.yaml")) or {}
        doc["id"] = new_family
        validate_document("family", doc, "family.yaml")
        os.makedirs(target, exist_ok=True)
        yamlio.dump(os.path.join(target, "family.yaml"), doc)
        if os.path.isdir(os.path.join(source, "index")):
            shutil.copytree(os.path.join(source, "index"), os.path.join(target, "index"))
        for sub in ("research", "evidence", "trees"):
            os.makedirs(os.path.join(target, sub), exist_ok=True)

    meta = dict(parent.meta() or {})
    history = [i for i in meta.get("instructions") or [] if i.get("pass", 0) <= at]
    history += [{"pass": at + 1, "ts": iso(now), "text": t.strip()} for t in instructions if t and t.strip()]
    meta.update({"id": rid, "family": family, "forked_from": {"research": parent.id, "pass": at},
                 "created": iso(now), "instructions": history, "status": "open", "passes": at})
    if actor:
        meta["created_by"] = {k: actor[k] for k in ("harness", "agent", "model") if actor.get(k)}
    validate_document("research", meta, "research.yaml")
    os.makedirs(child.folder)
    yamlio.dump(os.path.join(child.folder, "research.yaml"), meta)
    with open(child.events_path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines[: ends[at] + 1]:
            fh.write(line + "\n")
    return child, at
