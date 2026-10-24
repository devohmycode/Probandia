"""File locks with expiry.

One lock per research (``research-<id>.json``), one per family
(``family-<id>.json``) and one for the user's browser (``browser.json``: one
agent at a time drives it), in ``<project>/.probandia/locks/``. Content::

    {"owner": {"harness": "codex", "session": "…", "agent": "orchestrator"},
     "since": "2026-09-30T19:12:00Z", "expires": "2026-09-30T19:42:00Z"}

- A lock is taken by creating its file exclusively, which is atomic.
- Its holder renews it at each step; it expires after ``expiry_minutes``.
- A holder whose lock has expired loses it at the next check: ``renew`` then
  fails, and the lock must be taken again.
- An expired lock is taken over by anyone. The takeover runs under a short
  guard file, so two processes cannot both take over the same expired lock.
"""
import json
import os
import time
from datetime import timedelta

from probandia.errors import LockHeld, UsageError
from probandia.i18n import _
from probandia.limits import LOCK_EXPIRY_MINUTES, LOCK_TAKEOVER_GUARD_SECONDS
from probandia.util.fs import atomic_write_json, iso, parse_iso, utc_now
from probandia.util.ids import is_slug

KINDS = ("research", "family")


def parse_scope(scope):
    """``research:<id>``, ``family:<id>``, ``browser``, or the file stem ``research-<id>``."""
    if scope == "browser":
        return "browser", ""
    kind, sep, ident = scope.partition(":")
    if not sep:
        kind, sep, ident = scope.partition("-")
    if kind not in KINDS or not is_slug(ident):
        raise UsageError(_("invalid lock scope {scope}: expected research:<id>, family:<id> or browser")
                         .format(scope=repr(scope)))
    return kind, ident


# Variables that name the harness session, in order: the calls of one session,
# and of its subagents, share them.
SESSION_VARIABLES = ("PROBANDIA_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID",
                     "CURSOR_CONVERSATION_ID", "FACTORY_SESSION_ID", "OPENCODE_SESSION_ID",
                     "GROK_SESSION_ID", "ANTIGRAVITY_SESSION_ID")


def session_id(environ=None):
    """The session of the calling process: the first of ``SESSION_VARIABLES`` that
    is set, otherwise the parent process, so two calls from one shell share it."""
    environ = os.environ if environ is None else environ
    for var in SESSION_VARIABLES:
        if environ.get(var):
            return environ[var]
    return f"ppid-{os.getppid()}"


def owner_from_env(harness="cli", agent="session", environ=None):
    """The owner of the calling process."""
    return {"harness": harness or "cli", "session": session_id(environ), "agent": agent or "session"}


def same_session(a, b):
    """Two owners of one session (their agents may differ). A harness session id
    is unique; the parent-process fallback is unique only with its harness."""
    a, b = a or {}, b or {}
    session = a.get("session")
    if not session or session != b.get("session"):
        return False
    return not str(session).startswith("ppid-") or a.get("harness") == b.get("harness")


class LockLost(LockHeld):
    """The caller held the lock, but it expired or was taken over."""

    reason = "lock-lost"


class Locks:
    def __init__(self, project_root, expiry_minutes=LOCK_EXPIRY_MINUTES, clock=utc_now):
        self.folder = os.path.join(project_root, ".probandia", "locks")
        self.expiry = timedelta(minutes=expiry_minutes)
        self.clock = clock

    def path(self, scope):
        kind, ident = parse_scope(scope)
        return os.path.join(self.folder, f"{kind}-{ident}.json" if ident else f"{kind}.json")

    # reading

    def read(self, scope):
        """The lock content, or None when there is no lock."""
        path = self.path(scope)
        for attempt in range(50):
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                break
            except FileNotFoundError:
                return None
            except PermissionError:
                # Windows: the file is being replaced or deleted by another process.
                if attempt == 49:
                    raise
                time.sleep(0.02)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if not text:
                # Created but not written yet by its new holder: a live lock.
                return {"owner": {}, "since": None, "expires": iso(self.clock() + self.expiry)}
            # A corrupt file counts as expired, so it can be taken over.
            return {"owner": None, "since": None, "expires": "1970-01-01T00:00:00Z"}

    def is_expired(self, info):
        try:
            return parse_iso(info["expires"]) <= self.clock()
        except (KeyError, TypeError, ValueError):
            return True

    def status(self, scope):
        """(info, expired), or (None, None) when free."""
        info = self.read(scope)
        if info is None:
            return None, None
        return info, self.is_expired(info)

    # writing

    def _content(self, owner, since=None):
        now = self.clock()
        return {"owner": owner, "since": since or iso(now), "expires": iso(now + self.expiry)}

    def _create(self, path, content):
        """Creates the lock file exclusively; False if it already exists."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except (FileExistsError, PermissionError):
            # PermissionError: Windows refuses to create a file that is being deleted.
            return False
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(content, fh, ensure_ascii=False)
            fh.write("\n")
        return True

    def take(self, scope, owner):
        """Takes the lock, renews it if the caller already holds it, or takes over
        an expired one. Raises LockHeld when another owner holds a live lock."""
        path = self.path(scope)
        for _attempt in range(5):   # not "_": it would hide the translation function
            if self._create(path, self._content(owner)):
                return self.read(scope)
            info = self.read(scope)
            if info is None:
                continue  # released in between: try again
            if not self.is_expired(info):
                if info.get("owner") == owner:
                    return self.renew(scope, owner)
                raise self._held(scope, info)
            if self._take_over(path, owner):
                return self.read(scope)
        raise self._held(scope, self.read(scope) or {})

    def _take_over(self, path, owner):
        """Replaces an expired lock under a guard file. True on success."""
        guard = path + ".takeover"
        try:
            if time.time() - os.path.getmtime(guard) > LOCK_TAKEOVER_GUARD_SECONDS:
                os.unlink(guard)  # left by a process that died during a takeover
        except OSError:
            pass
        if not self._create(guard, {"pid": os.getpid()}):
            return False
        try:
            scope = os.path.basename(path)[: -len(".json")]
            info = self.read(scope)
            if info is not None and not self.is_expired(info):
                return False  # someone else took it over first
            atomic_write_json(path, self._content(owner))
            return True
        finally:
            try:
                os.unlink(guard)
            except OSError:
                pass

    def renew(self, scope, owner):
        """Pushes the expiry back. Fails if the caller no longer holds a live lock."""
        info = self.read(scope)
        if info is None or info.get("owner") != owner:
            raise LockLost(_("lock {scope} is not held by this owner").format(scope=scope),
                           values=self.describe(scope, info))
        if self.is_expired(info):
            raise LockLost(_("lock {scope} expired at {expires}; take it again")
                           .format(scope=scope, expires=info.get("expires")),
                           values=self.describe(scope, info))
        content = self._content(owner, since=info.get("since"))
        atomic_write_json(self.path(scope), content)
        return content

    def release(self, scope, owner):
        """Removes the lock. True if it was removed, False if there was none.
        Raises LockHeld if another owner holds a live lock."""
        info = self.read(scope)
        if info is None:
            return False
        if info.get("owner") != owner and not self.is_expired(info):
            raise self._held(scope, info)
        try:
            os.unlink(self.path(scope))
        except FileNotFoundError:
            return False
        return True

    def describe(self, scope, info):
        info = info or {}
        owner = info.get("owner") or {}
        return {
            "LOCK": scope,
            "HOLDER": "/".join(str(owner.get(k, "?")) for k in ("harness", "session", "agent")),
            "EXPIRES": info.get("expires", ""),
        }

    def _held(self, scope, info):
        return LockHeld(
            _("lock {scope} is held by another owner").format(scope=scope),
            values=self.describe(scope, info),
            lines=[_("wait until {expires}, then run: lock take {scope}")
                   .format(expires=info.get("expires", "?"), scope=scope)],
        )
