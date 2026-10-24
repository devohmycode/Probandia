"""``watch``: the source watch (TRUST4-T3, optimize.md 6.18).

``watch [--keys] [--out <folder>]`` replays the witness of each archive connector
that can run without a key or a session (TRUST-D8) and lists the entries of the
providers' and archives' catalogues checked too long ago (``catalogues.max_age_days``).
Each witness ends ``passed``, ``failed`` or ``not-run``, with why it was not run:
a key, files to download first, a session in the browser, an archive read in the
browser only, a witness without a connector, or a site that refuses the witness
(``state.witness_refused`` of its catalogue entry, dated: never bypassed). ``--keys`` also reads, for free, the
account of each provider whose key is set (``keys check``). Nothing is ever paid.

It writes ``watch.json`` and ``watch.md`` into ``--out`` (default: the project's
``.probandia/``), which ``tools/watch_issues.py`` turns into issues. Outside a
project it works in a temporary folder.
"""
import datetime
import json
import os
import shutil
import tempfile

from probandia.cli.output import Result
from probandia.i18n import _

# what a connector needs before its witness can run here (TRUST-D8)
FILES = {"insee_cog": "insee", "bnl": "bnl"}   # data folders: places --update-cog, bnl.download
# the keys a witness cannot run without; the others are optional (Wayback, Europeana's demonstration key)
REQUIRED_KEYS = {"geonames": "GEONAMES_USERNAME"}


def watch_args(p, common):
    p.add_argument("--keys", action="store_true",
                   help=_("also read, for free, the account of each provider whose key is set"))
    p.add_argument("--out", help=_("the folder of watch.json and watch.md (default: .probandia)"))
    p.add_argument("--print-schedule", action="store_true",
                   help=_("print the command that runs the watch every Monday (schtasks or cron), run nothing"))


def _project(ctx):
    from probandia.errors import NotInProject

    try:
        return ctx.project
    except NotInProject:
        return None


def why_not(archive_id, entry, environ, data_dir):
    """Why a witness cannot run here, or None."""
    key = REQUIRED_KEYS.get(archive_id)
    if key and not environ.get(key):
        return "key"
    if archive_id in FILES:
        folder = os.path.join(data_dir or "", FILES[archive_id])
        if not (os.path.isdir(folder) and os.listdir(folder)):
            return "files"
    if ((entry or {}).get("login") or {}).get("required"):
        return "session"
    if ((entry or {}).get("state") or {}).get("witness_refused"):   # T121: the site refuses it, dated in state
        return "refused"
    return None


def witnesses(project, environ, data_dir, context_for, catalogue):
    """[{archive, operation, state, reason, count, failure}] for the archives of the catalogue and the
    connectors: each witness replayed, or why it was not."""
    from probandia import archives

    rows, modules = [], archives.connectors(project)
    for archive_id in sorted(set(modules) | set(catalogue)):
        entry, module = catalogue.get(archive_id) or {}, modules.get(archive_id)
        witness = archives.witness_of(module, catalogue=catalogue) if module else entry.get("witness")
        row = {"archive": archive_id, "operation": (witness or {}).get("operation"), "state": "not-run",
               "reason": None, "count": None, "failure": None}
        if module is None:
            row["reason"] = ("session" if (entry.get("login") or {}).get("required")
                             else "no-connector" if witness else "browser")
        elif not witness:
            row["reason"] = "no-witness"
        else:
            row["reason"] = why_not(archive_id, entry, environ, data_dir)
        if row["reason"] is None:
            try:
                result = archives.run(module, witness["operation"], dict(witness.get("args") or {}),
                                      context_for(archive_id))
                passed = archives.witness_passed(witness, result)
                row.update(state="passed" if passed else "failed", count=result.n,
                           failure=None if passed else (result.failure or "the witness did not find what it expects"))
            except Exception as err:   # noqa: BLE001 — one archive down does not stop the watch
                row.update(state="failed", failure=f"{type(err).__name__}: {err}"[:300])
        rows.append(row)
    return rows


def stale(project, config, today=None):
    """[{catalogue, entry, checked, age_days}] of both catalogues."""
    from probandia.archives.finder import load_catalogue
    from probandia.providers import catalogue as providers

    today = today or datetime.date.today()
    days = providers.max_age_days(config)
    out = []
    for pid, age in providers.ages(today=today):
        if age is None or age > days:
            checked = providers.load()[pid].get("checked")
            out.append({"catalogue": "providers", "entry": pid, "checked": str(checked) if checked else None,
                        "age_days": age})
    for aid, entry in sorted(load_catalogue(project).items()):
        checked = str((entry.get("state") or {}).get("checked") or "") or None
        try:
            age = (today - datetime.date.fromisoformat(checked)).days if checked else None
        except ValueError:
            age = None
        if age is None or age > days:
            out.append({"catalogue": "archives", "entry": aid, "checked": checked, "age_days": age})
    return out, days


def markdown(doc):
    """The summary of a watch, for a person or an issue."""
    lines = [f"# Watch of {doc['date']}", "", f"Probandia {doc['version']}; stale after {doc['days']} days.", ""]
    failed = [w for w in doc["witnesses"] if w["state"] == "failed"]
    lines += ["## Witnesses that failed", ""] + ([f"- `{w['archive']}.{w['operation']}`: {w['failure']}"
                                                   for w in failed] or ["- none"])
    lines += ["", "## Not run", ""] + [f"- `{w['archive']}`: {w['reason']}" for w in doc["witnesses"]
                                        if w["state"] == "not-run"]
    lines += ["", "## Stale catalogue entries", ""] + ([f"- {s['catalogue']}: `{s['entry']}`, checked "
                                                        f"{s['checked'] or 'never'}" for s in doc["stale"]] or ["- none"])
    if doc.get("keys"):
        lines += ["", "## Provider accounts", ""] + [f"- {k['variable']} {k['entry'] or '-'}: {k['outcome']}"
                                                      for k in doc["keys"]]
    return "\n".join(lines) + "\n"


def schedule(folder, python, windows):
    """TRUST4-T4: the command that runs the watch every Monday at 8:00, in ``folder``: schtasks on Windows,
    a crontab line elsewhere. Probandia prints it; the user runs it."""
    run = f'"{python}" -m probandia watch'
    if windows:
        action = f'cmd /c cd /d "{folder}" && {run}'
        return 'schtasks /Create /SC WEEKLY /D MON /ST 08:00 /TN "Probandia watch" /TR "' + action.replace('"', '\\"') + '"'
    return f"0 8 * * 1 cd '{folder}' && {run}"


def watch(ctx, context_for=None, today=None):
    from probandia import __version__
    from probandia.archives.finder import load_catalogue
    from probandia.cli.providers_cmd import _config
    from probandia.lang.places import data_dir
    from probandia.util.fs import atomic_write_text

    project = _project(ctx)
    if ctx.args.print_schedule:
        import sys

        line = schedule(project or ctx.cwd, sys.executable, os.name == "nt")
        r = Result("OK", {"SYSTEM": "schtasks" if os.name == "nt" else "cron"})
        r.data("schedule", line)
        r.line(_("run it yourself to watch every Monday; nothing is scheduled by Probandia"))
        return r
    config = _config(ctx)
    scratch = None if project else tempfile.mkdtemp(prefix="probandia-watch-")
    try:
        if context_for is None:
            from probandia.archives import Context
            from probandia.util.http import Client, contact

            base = project or scratch
            client = Client(os.path.join(base, ".probandia"), contact(ctx.environ, config), config)

            def context_for(_archive_id):
                return Context(client, project, ctx.environ, data_dir(ctx.environ))
        catalogue = load_catalogue(project)
        rows = witnesses(project, ctx.environ, data_dir(ctx.environ), context_for, catalogue)
        old, days = stale(project, config, today)
        keys = _keys(ctx) if ctx.args.keys else []
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    out = os.path.join(ctx.cwd, ctx.args.out) if ctx.args.out else (
        os.path.join(project, ".probandia") if project else ctx.cwd)   # T213: --out relative to the command's folder
    os.makedirs(out, exist_ok=True)
    streaks(rows, previous(out))
    doc = {"schema": 1, "date": (today or datetime.date.today()).isoformat(), "version": __version__,
           "days": days, "witnesses": rows, "stale": old, "keys": keys}
    atomic_write_text(os.path.join(out, "watch.json"), json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    atomic_write_text(os.path.join(out, "watch.md"), markdown(doc))
    failed = [w for w in rows if w["state"] == "failed"]
    bad_keys = [k for k in keys if k["outcome"] in ("refused", "not-subscribed", "failed")]
    r = Result("WARN" if failed or old or bad_keys else "OK",
               {"PASSED": sum(1 for w in rows if w["state"] == "passed"), "FAILED": len(failed),
                "NOT_RUN": sum(1 for w in rows if w["state"] == "not-run"), "STALE": len(old)},
               details=os.path.join(out, "watch.json"))
    for w in rows:
        r.data("witness", f"{w['archive']} {w['state']}" + (f" {w['reason']}" if w["reason"] else ""))
    for s in old:
        r.data("stale", f"{s['catalogue']}:{s['entry']} checked={s['checked'] or 'never'}")
    r.table("witnesses", rows, ["archive", "operation", "state", "reason", "count", "failure", "streak"])
    r.table("stale", old, ["catalogue", "entry", "checked", "age_days"])
    return r


def previous(folder):
    """The last watch written in ``folder``, or None."""
    try:
        with open(os.path.join(folder, "watch.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def streaks(rows, before):
    """Each witness gets ``streak``, its failures in a row, counted from the last watch: a failure adds
    one, anything else starts again from 0. An issue opens only after a few (TRUST-D7, made precise:
    sites often blocked or offline would otherwise open one every week)."""
    last = {w["archive"]: w.get("streak") or 0 for w in (before or {}).get("witnesses") or []}
    for w in rows:
        w["streak"] = last.get(w["archive"], 0) + 1 if w["state"] == "failed" else 0
    return rows


def _keys(ctx):
    """``keys check`` for every key set: a free reading of each account."""
    from probandia.cli import keys_cmd

    if not hasattr(ctx.args, "name"):
        ctx.args.name = None
    return keys_cmd._check(ctx).tables["checks"]["rows"]
