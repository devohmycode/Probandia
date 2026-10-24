"""``keys``: the API keys, without ever showing one (cli.md 5.3; decision D-7).

- ``keys``: each variable expected, present or not, where it comes from, what it
  unlocks, and its fingerprint (8 hexadecimal digits of its SHA-256, never the key);
- ``keys where``: the ``.env`` files read, the weakest first;
- ``keys check [VARIABLE]``: a free reading of the account's balance, for the 15
  entries that expose it; nothing is spent;
- ``keys set VARIABLE`` / ``keys unset VARIABLE``: write or remove it in the
  user's ``.env`` (``--in-project``: the project's), the value typed unseen;
- ``keys signup PROVIDER``: opens the provider's page, and says what its free
  tier asks for.
"""
import os

from probandia.cli.output import Result
from probandia.errors import EXIT_USAGE, NotInProject, UsageError
from probandia.i18n import _

ACTIONS = ("list", "where", "check", "set", "unset", "signup")


def configure(p, common):
    p.add_argument("action", nargs="?", default="list", choices=ACTIONS)
    p.add_argument("name", nargs="?", metavar="<variable|provider>",
                   help=_("a key variable, such as SERPER_API_KEY; a provider for signup"))
    p.add_argument("--in-project", action="store_true",
                   help=_("set, unset: the project's .env instead of the user's"))


def _project(ctx):
    try:
        return ctx.project
    except NotInProject:
        return None


def _files(ctx):
    from probandia.util import envfile

    return envfile.files(ctx.environ, _project(ctx))


def _file_values(path):
    from probandia.util import envfile

    try:
        with open(path, encoding="utf-8") as fh:
            return envfile.parse(fh.read())
    except (OSError, UnicodeDecodeError):
        return {}


def _unlocks(cat):
    """{variable: [entry ids]}, for the providers of the catalogue."""
    from probandia.providers import catalogue

    out = {}
    for pid, e in cat.items():
        env = catalogue.key_env(e)
        if env:
            out.setdefault(env, []).append(pid)
    return out


def rows(ctx, cat):
    """One record per variable: never its value."""
    from probandia import doctor
    from probandia.ledger import fingerprint

    files = _files(ctx)
    user_file = files[0]
    project_file = files[1] if len(files) > 1 else None
    in_user, in_project = _file_values(user_file), _file_values(project_file) if project_file else {}
    unlocks = _unlocks(cat)
    out = []
    for var in doctor.secret_variables(cat):
        value = ctx.environ.get(var)
        if not value:
            source = None
        elif project_file and in_project.get(var) == value:
            source = "project"
        elif in_user.get(var) == value:
            source = "user"
        else:
            source = "environment"
        out.append({"variable": var, "present": bool(value), "source": source,
                    "file": {"project": project_file, "user": user_file}.get(source),
                    "unlocks": unlocks.get(var, []), "fingerprint": fingerprint(value) if value else None})
    return out


def run(ctx):
    action = ctx.args.action
    if action in ("set", "unset", "signup") and not ctx.args.name:
        raise UsageError(_("keys {action} needs a name").format(action=action))
    return {"list": _list, "where": _where, "check": _check, "set": _set, "unset": _unset,
            "signup": _signup}[action](ctx)


def _list(ctx):
    from probandia.providers import catalogue

    cat = catalogue.load()
    found = rows(ctx, cat)
    present = [r for r in found if r["present"]]
    r = Result("OK", {"KEYS": len(found), "PRESENT": len(present)})
    for x in found:
        state = f"{x['source']} {x['fingerprint']}" if x["present"] else "missing"
        r.data("key", f"{x['variable']} {state} unlocks={','.join(x['unlocks']) or '-'}")
    r.table("keys", found, ["variable", "present", "source", "fingerprint", "unlocks", "file"])
    r.view = "keys"
    return r


def _where(ctx):
    files = _files(ctx)
    read = [p for p in (ctx.environ.get("PROBANDIA_ENV_FILES") or "").split(os.pathsep) if p]
    r = Result("OK", {"FILES": len(files), "READ": len(read)})
    rows_ = []
    for n, path in enumerate(files):
        kind = "user" if n == 0 else "project"
        exists = os.path.isfile(path)
        r.data("file", f"{kind} {'present' if exists else 'absent'} {path}")
        rows_.append({"file": kind, "path": path, "present": exists, "keys": len(_file_values(path))})
    r.table("files", rows_)
    r.line(_("a variable set in the environment wins, then the project's file, then the user's"))
    r.view = "keys-where"
    return r


def _client(ctx):
    from probandia import config as cfgmod
    from probandia.paths import user_data_dir
    from probandia.util.http import Client, contact

    project = _project(ctx)
    state = os.path.join(project, ".probandia") if project else os.path.join(user_data_dir(ctx.environ), "http")
    os.makedirs(state, exist_ok=True)
    config = ctx.config if project else cfgmod.load(None, ctx.environ)
    return Client(state, contact(ctx.environ, config), config), config


def _check(ctx):
    """A free reading of each key's account: valid, refused, not subscribed."""
    from probandia.ledger import Ledger
    from probandia.providers import adapters, catalogue
    from probandia.providers.base import ProviderError

    cat = catalogue.load()
    found = rows(ctx, cat)
    if ctx.args.name:
        found = [x for x in found if x["variable"] == ctx.args.name.upper()]
        if not found:
            from probandia.suggest import lines

            raise UsageError(_("unknown key variable {name}").format(name=ctx.args.name),
                             lines=lines(ctx.args.name.upper(), [x["variable"] for x in rows(ctx, cat)]))
    client, _config = _client(ctx)
    ledger = Ledger(_project(ctx), cat, environ=ctx.environ)
    results = []
    for x in found:
        if not x["present"]:
            if ctx.args.name:
                results.append({"variable": x["variable"], "entry": None, "outcome": "missing", "detail": ""})
            continue
        checkable = [p for p in x["unlocks"] if p in adapters.SYNC]
        if not checkable:
            results.append({"variable": x["variable"], "entry": None, "outcome": "no-free-check", "detail": ""})
            continue
        # one reading per key; OpenWeb Ninja asks to subscribe to each API, so each is read
        targets = checkable if x["variable"] == "OPENWEBNINJA_API_KEY" else checkable[:1]
        for p in targets:
            try:
                info = adapters.sync(p, client, cat[p], ctx.environ, ledger)
                left = info.get("left") if info else None
                results.append({"variable": x["variable"], "entry": p, "outcome": "valid",
                                "detail": "" if left is None else f"{round(left, 2):g}"})
            except ProviderError as err:
                if "subscri" in str(err.message).lower():
                    outcome = "not-subscribed"
                elif err.status in (401, 403):
                    outcome = "refused"
                else:
                    outcome = "failed"
                results.append({"variable": x["variable"], "entry": p, "outcome": outcome,
                                "detail": f"HTTP {err.status}"})
            except Exception as err:   # a network error on one key does not stop the others
                results.append({"variable": x["variable"], "entry": p, "outcome": "failed",
                                "detail": type(err).__name__})
    bad = [x for x in results if x["outcome"] in ("refused", "not-subscribed", "failed")]
    r = Result("WARN" if bad else "OK", {"CHECKED": sum(1 for x in results if x["entry"]),
                                         "VALID": sum(1 for x in results if x["outcome"] == "valid"),
                                         "REFUSED": sum(1 for x in results if x["outcome"] == "refused")})
    for x in results:
        r.data("key", f"{x['variable']} {x['entry'] or '-'} {x['outcome']} {x['detail']}".rstrip())
    r.table("checks", results, ["variable", "entry", "outcome", "detail"])
    r.view = "keys-check"
    return r


def _target(ctx):
    from probandia.util import envfile

    if ctx.args.in_project:
        return os.path.join(ctx.project, envfile.FILE_NAME)
    return envfile.user_file(ctx.environ)


def _variable(ctx):
    import re

    name = ctx.args.name.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise UsageError(_("invalid variable name {name}").format(name=name))
    return name


def _secret(ctx, prompt):
    """The key, typed unseen at a terminal (getpass), or in the masked field of the terminal
    application (``asking.through``); otherwise one line of input."""
    import getpass
    import sys

    from probandia.cli import asking

    if asking.given() is not None:
        return (asking.given()("secret", prompt) or "").strip()
    stdin = ctx.stdin or sys.stdin
    try:
        if stdin is sys.stdin and sys.stdin.isatty():
            return getpass.getpass(prompt)
    except (AttributeError, ValueError):
        pass
    if ctx.stdout is not None and getattr(ctx, "asks", False):
        ctx.stdout.write(prompt)
        ctx.stdout.flush()
    return stdin.readline().strip() if stdin else ""


def _set(ctx):
    from probandia.cli import asking
    from probandia.ledger import fingerprint
    from probandia.util import envfile

    var = _variable(ctx)
    path = _target(ctx)
    old = _file_values(path).get(var)
    if old and not asking.confirm(ctx, _("{var} is already set in {path}. Replace it?").format(var=var, path=path)):
        return asking.declined({"KEY": var, "FILE": path})
    value = _secret(ctx, _("{var} (typed unseen): ").format(var=var))
    if ctx.stdout is not None and getattr(ctx, "asks", False):
        ctx.stdout.write("\n")
    if not value:
        raise UsageError(_("no value typed: nothing written"))
    envfile.set_value(path, var, value)
    r = Result("OK", {"KEY": var, "FILE": path, "STATE": "replaced" if old else "added",
                      "FINGERPRINT": fingerprint(value)})
    r.line(_("the value is never shown; its fingerprint tells keys apart"))
    return r


def _unset(ctx):
    from probandia.cli import asking
    from probandia.util import envfile

    var = _variable(ctx)
    path = _target(ctx)
    if var not in _file_values(path):
        return Result("WARN", {"KEY": var, "FILE": path, "STATE": "absent"},
                      [_("{var} is not set in {path}").format(var=var, path=path)])
    if not asking.confirm(ctx, _("Remove {var} from {path}?").format(var=var, path=path)):
        return asking.declined({"KEY": var, "FILE": path})
    envfile.unset_value(path, var)
    return Result("OK", {"KEY": var, "FILE": path, "STATE": "removed"})


def _open(url):
    import webbrowser

    return webbrowser.open(url)


def _signup(ctx):
    from probandia.providers import catalogue

    cat = catalogue.load()
    p = ctx.args.name
    if p not in cat:
        from probandia.suggest import lines

        raise UsageError(_("unknown provider {provider}").format(provider=p), lines=lines(p, cat))
    entry = cat[p]
    url = entry.get("signup_url") or entry.get("source_url")
    if not url:
        return Result("FAIL", {"REASON": "no-url", "PROVIDER": p}, exit_code=EXIT_USAGE)
    r = Result("OK", {"PROVIDER": p, "NAME": entry.get("name", p), "URL": url,
                      "KEY": catalogue.key_env(entry) or "none",
                      "CARD_REQUIRED": bool(entry.get("card_required")),
                      "CONTENT_REUSE": bool(entry.get("content_reuse"))})
    if entry.get("card_required"):
        r.line(_("its free tier asks for a credit card; Probandia uses it only with "
                 "providers.allow_card_required, and never pays"))
    if entry.get("content_reuse"):
        r.line(_("it may reuse the content sent to it; Probandia uses it only with providers.allow_content_reuse"))
    if p.startswith("openwebninja"):
        r.line(_("subscribe the account to the free plan of each API (web search, news, books) before use"))
    if catalogue.key_env(entry):
        r.line(_("then: probandia keys set {var}").format(var=catalogue.key_env(entry)))
    r.set("OPENED", bool(_open(url)))
    return r
