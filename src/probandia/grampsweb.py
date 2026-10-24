"""Gramps Web, one way (SPECS § 11.7).

1. **Token.** ``POST <gramps.url>/api/token/`` with ``gramps.user`` and
   ``PROBANDIA_GRAMPS_PASSWORD`` returns a JWT.
2. **Upload.** ``POST /api/importers/ged/file/restore`` with the GEDCOM 5.5.1
   export: Gramps Web resets the tree to the file's content (it adds, updates and
   deletes), so the tree mirrors the family; ``--dry-run`` adds ``?dry_run=true``
   and only returns the changeset. Restoring needs the Owner or Admin role.
3. **Wait.** When Gramps Web runs the task in the background (202), ``GET
   /api/tasks/<id>`` every 2 s, for at most 10 minutes.

The tree is the one of the account ``gramps.user``: Gramps Web ties each user to one
tree and the token request names none (multi-tree page of grampsweb.org, read on 17 Oct.
2026). That tree must be dedicated to the feed: a restore replaces what is in it.
Nothing is read back from Gramps Web but the counts.
"""
import json
import time
import urllib.error
import urllib.request

from probandia.cli.output import Result
from probandia.errors import ProbandiaError, UsageError
from probandia.i18n import _

POLL_SECONDS = 2
POLL_MAX_SECONDS = 600


class GrampsError(ProbandiaError):
    reason = "gramps-web"
    exit_code = 7


def _request(method, url, data=None, token=None, content_type="application/json", timeout=120):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")[:300]
        raise GrampsError(_("Gramps Web answered HTTP {status}: {body}").format(status=err.code, body=body),
                          values={"STATUS_CODE": err.code})
    except (urllib.error.URLError, OSError) as err:
        raise GrampsError(_("Gramps Web cannot be reached: {error}").format(error=err))


def token(base, user, password):
    payload = {"username": user, "password": password}
    status, body = _request("POST", f"{base}/api/token/", json.dumps(payload).encode("utf-8"))
    if not body or not body.get("access_token"):
        raise GrampsError(_("Gramps Web gave no token"))
    return body["access_token"]


def wait(base, jwt, task_id, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + POLL_MAX_SECONDS
    while True:
        _status, body = _request("GET", f"{base}/api/tasks/{task_id}", token=jwt)
        state = (body or {}).get("state")
        if state == "SUCCESS":
            return (body or {}).get("result")
        if state in ("FAILURE", "REVOKED"):
            raise GrampsError(_("the Gramps Web task failed: {info}").format(info=(body or {}).get("info")))
        if clock() >= deadline:
            raise GrampsError(_("the Gramps Web task did not end within 10 minutes"))
        sleep(POLL_SECONDS)


def upload(base, jwt, ged_bytes, dry_run=False, sleep=time.sleep):
    url = f"{base}/api/importers/ged/file/restore" + ("?dry_run=true" if dry_run else "")
    status, body = _request("POST", url, ged_bytes, jwt, "application/octet-stream", timeout=600)
    if status == 202 and body and body.get("task", {}).get("id"):
        return wait(base, jwt, body["task"]["id"], sleep)
    return body


def summary_lines(summary):
    """``people add 3 update 0 delete 1`` lines of a restore changeset."""
    out = []
    for kind, counts in sorted((summary or {}).items()):
        if isinstance(counts, dict):
            out.append(f"{kind} " + " ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return out


def export(ctx, family, exp):
    base = (ctx.config.get("gramps.url") or "").rstrip("/")
    user = ctx.config.get("gramps.user")
    password = ctx.environ.get("PROBANDIA_GRAMPS_PASSWORD")
    if not base or not user:
        raise UsageError(_("set gramps.url and gramps.user, and PROBANDIA_GRAMPS_PASSWORD in the environment or .env"))
    if not password:
        return Result.stop("no-password", None, values={"FAMILY": family})
    jwt = token(base, user, password)
    ged = exp.text().encode("utf-8")
    from probandia.cli import asking

    if not ctx.args.dry_run and asking.will_ask(ctx):
        # a restore replaces the whole tree, hard to undo: the person sees the dry run's counts first
        changes = "; ".join(summary_lines(upload(base, jwt, ged, dry_run=True))) or _("no change")
        if not asking.confirm(ctx, _("Replace the Gramps Web tree at {server} with the family ({changes})?").format(
                server=base, changes=changes)):
            return asking.declined({"FAMILY": family, "SERVER": base})
    summary = upload(base, jwt, ged, dry_run=ctx.args.dry_run)
    r = Result("OK", {"FAMILY": family, "SERVER": base, "DRY_RUN": bool(ctx.args.dry_run),
                      "PERSONS": len(exp.indi)})
    for line in summary_lines(summary):
        r.data("changes", line)
    r.table("changes", [dict(counts, kind=kind) for kind, counts in sorted((summary or {}).items())
                        if isinstance(counts, dict)], hidden=True)
    if not ctx.args.dry_run:
        r.line(_("the Gramps Web tree now mirrors the family"))
    return r
