"""The family indexes: ``families/<family>/index/*.yaml``.

They are the single source of truth of a family. They are read freely and
validated against their schema. They are written only under the family lock,
atomically, and each write is appended to ``.probandia/index-changes.jsonl``.
"""
import contextlib
import copy
import json
import os
import time

from probandia.errors import LockHeld
from probandia.util import yamlio
from probandia.util.fs import iso, utc_now
from probandia.util.locks import Locks
from probandia.util.schema import validate_document

# file name -> (schema name, list key)
FILES = {
    "persons": ("persons", "persons"),
    "places": ("places", "places"),
    "sources": ("sources", "sources"),
    "searches": ("searches", "searches"),
    "hypotheses": ("hypotheses", "hypotheses"),
    "variants": ("variants", None),
    "non-links": ("non-links", "non_links"),
    "gaps": ("gaps", "gaps"),
    "analyses": ("analyses", "analyses"),   # GPS4: the analyses of disputed conclusions
    "proofs": ("proofs", "proofs"),   # GPS5: the proof arguments and their review
}

_CACHE = {}   # path -> ((mtime_ns, size, inode), the document read)

CHANGES_LOG = os.path.join(".probandia", "index-changes.jsonl")


def empty(name):
    _schema, key = FILES[name]
    if key is None:
        return {"schema": 1, "surnames": {}, "given": {}}
    return {"schema": 1, key: []}


class FamilyIndexes:
    def __init__(self, project, family):
        self.project = project
        self.family = family
        self.folder = os.path.join(project, "families", family, "index")

    def path(self, name):
        return os.path.join(self.folder, f"{name}.yaml")

    def load(self, name):
        """The index as a dict; an empty index when the file does not exist. Each file is read and
        validated once per process while its date and size stay the same (T147): ``verify`` asks
        for ``persons`` some twenty times. The caller gets its own copy, free to change it."""
        path = self.path(name)
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return empty(name)
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)   # a replaced file (atomic write) has a new inode
        hit = _CACHE.get(path)
        if hit is None or hit[0] != stamp:
            doc = yamlio.load(path) or empty(name)
            validate_document(FILES[name][0], doc, os.path.relpath(path, self.project))
            _CACHE[path] = hit = (stamp, doc)
        return copy.deepcopy(hit[1])

    def items(self, name):
        key = FILES[name][1]
        return self.load(name).get(key, [])

    def load_all(self):
        return {name: self.load(name) for name in FILES}

    def write(self, docs, actor, reason):
        """Writes several index files. The caller holds the family lock."""
        written = []
        for name, doc in docs.items():
            validate_document(FILES[name][0], doc, f"{name}.yaml")
            yamlio.dump(self.path(name), doc)
            _CACHE.pop(self.path(name), None)
            written.append(f"{name}.yaml")
        log = os.path.join(self.project, CHANGES_LOG)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        entry = {"ts": iso(utc_now()), "family": self.family, "files": written,
                 "actor": actor, "reason": reason}
        with open(log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return written


@contextlib.contextmanager
def locked(project, scope, owner, expiry_minutes=30, wait_seconds=30.0, poll=0.1):
    """Holds a lock for the block, waiting up to ``wait_seconds`` for another
    holder to release it; then raises LockHeld (exit code 5).

    When the caller's session already holds the lock for a whole pass (``new``,
    ``resume``), the block runs inside that lock: the pass's own writes."""
    from probandia.util.locks import same_session

    locks = Locks(project, expiry_minutes=expiry_minutes)
    info, expired = locks.status(scope)
    if info is not None and not expired and "pid" not in (info.get("owner") or {})             and same_session(info.get("owner"), owner):
        yield
        return
    owner = dict(owner, pid=os.getpid())  # two processes of one session are two writers
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            locks.take(scope, owner)
            break
        except LockHeld:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll)
    try:
        yield
    finally:
        try:
            locks.release(scope, owner)
        except LockHeld:
            pass
