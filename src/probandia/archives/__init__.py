"""Archive connectors, and code mode: ``archive find`` and ``archive run``.

A connector is a Python module::

    ARCHIVE = "gallica"
    HOSTS = ["gallica.bnf.fr"]
    OPERATIONS = {"search": Operation(doc="SRU search in Gallica", params={"query": str, ...})}
    WITNESS = {"operation": "search", "args": {...}, "expect": {"min_results": 1}}
    def run(operation, args, ctx): ...   # returns an OperationResult

Built-in connectors live in ``probandia/archives/<id>.py``; learned ones in the
project's ``library/connectors/<id>.py``. An operation is addressed as
``<archive>.<operation>``.
"""
import importlib
import importlib.util
import os
import re
from dataclasses import dataclass, field

from probandia.errors import ProbandiaError, UsageError
from probandia.i18n import _

BUILT_IN = ("ad50", "gallica", "matchid", "openarchives", "wikitree", "europeana", "loc", "wayback", "bnl",
            "geonames", "gov", "insee_cog", "iiif", "ddb")


@dataclass
class Operation:
    doc: str
    params: dict = field(default_factory=dict)
    required: tuple = ()


@dataclass
class OperationResult:
    status: str = "ok"                 # ok | failed
    rows: list = field(default_factory=list)   # dicts: title, url, date, snippet, id…
    count: int | None = None           # total hits reported by the archive
    text: str | None = None            # raw text, ALTO text…
    path: str | None = None            # a file written (image, download)
    failure: str | None = None
    failure_code: str = "connector"    # FAILURE= of a failed run: connector | unexpected-answer
    url: str | None = None             # the request, for the citation and the log

    @property
    def n(self):
        return self.count if self.count is not None else len(self.rows)


class ConnectorError(ProbandiaError):
    reason = "connector-error"


class Context:
    """What a connector receives: the HTTP client, the project, the environment."""

    def __init__(self, client, project=None, environ=None, data_dir=None, work=None):
        self.client = client
        self.project = project
        self.environ = environ or {}
        self.data_dir = data_dir
        self.work = work

    def get(self, url, params=None, headers=None, api=True):
        import urllib.parse
        full = url + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        return self.client.get(full, headers=headers or {}, api=api)

    def json(self, url, params=None, headers=None, archive=""):
        import json
        resp = self.get(url, params, dict({"Accept": "application/json"}, **(headers or {})))
        if resp.status != 200:
            raise ConnectorError(_("{archive}: HTTP {status}").format(archive=archive, status=resp.status),
                                 values={"HTTP": resp.status, "URL": resp.url})
        try:
            return json.loads(resp.text), resp
        except ValueError:
            raise ConnectorError(_("{archive}: the answer is not JSON").format(archive=archive),
                                 values={"URL": resp.url})


def load(archive, project=None):
    """The connector module of an archive: the project's library first, then built-in."""
    if not re.fullmatch(r"[a-z0-9_]+", archive):
        raise UsageError(_("invalid archive id {id}").format(id=archive))
    if project:
        path = os.path.join(project, "library", "connectors", f"{archive}.py")
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location(f"probandia_library_{archive}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    if archive not in BUILT_IN:
        raise UsageError(_("no connector for {id}").format(id=archive))
    return importlib.import_module(f"probandia.archives.{archive}")


def connectors(project=None):
    """{archive id: module} of every connector."""
    out = {a: load(a) for a in BUILT_IN}
    if project:
        folder = os.path.join(project, "library", "connectors")
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.endswith(".py") and not name.startswith("_"):
                    try:
                        out[name[:-3]] = load(name[:-3], project)
                    except Exception:
                        continue
    return out


def parse_address(address):
    archive, sep, operation = address.partition(".")
    if not sep or not operation:
        raise UsageError(_("an operation is written <archive>.<operation>, not {address}").format(
            address=address))
    return archive, operation


def check_args(module, operation, args):
    op = module.OPERATIONS.get(operation)
    if op is None:
        raise UsageError(_("{archive} has no operation {operation}; it has: {ops}").format(
            archive=module.ARCHIVE, operation=operation, ops=", ".join(sorted(module.OPERATIONS))))
    out = {}
    for name, value in args.items():
        if name not in op.params:
            raise UsageError(_("{archive}.{operation} takes no parameter {name}").format(
                archive=module.ARCHIVE, operation=operation, name=name))
        kind = op.params[name]
        try:
            out[name] = kind(value) if kind in (int, float) else value
        except (TypeError, ValueError):
            raise UsageError(_("{name} must be a number").format(name=name))
    for name in op.required:
        if name not in out:
            raise UsageError(_("{archive}.{operation} needs {name}").format(
                archive=module.ARCHIVE, operation=operation, name=name))
    return out


def run(module, operation, args, ctx):
    args = check_args(module, operation, args)
    try:
        return module.run(operation, args, ctx)
    except ConnectorError as err:
        return OperationResult(status="failed", failure=err.message,
                               url=err.values.get("URL"))
    except ProbandiaError:
        raise
    except Exception as err:   # an answer the connector did not expect (a changed page, odd JSON): a failed call
        return OperationResult(status="failed", failure_code="unexpected-answer", failure=_(
            "{archive} gave an unexpected answer ({error})").format(
            archive=module.ARCHIVE, error=f"{type(err).__name__}: {err}"[:200]))


def witness_of(module, project=None, catalogue=None):
    """TRUST4-T1: the witness of a connector. The catalogue (catalogues/archives.yaml, then the project's
    library/archives.yaml) is the reference; a learned connector absent from it keeps its own WITNESS."""
    if catalogue is None:
        from probandia.archives.finder import load_catalogue

        catalogue = load_catalogue(project)
    return (catalogue.get(module.ARCHIVE) or {}).get("witness") or getattr(module, "WITNESS", None)


def witness_passed(witness, result):
    expect = witness.get("expect") or {}
    if result.status != "ok":
        return False
    if "min_results" in expect and result.n < expect["min_results"]:
        return False
    if "contains" in expect:
        blob = (result.text or "") + " ".join(str(r) for r in result.rows)
        if expect["contains"].lower() not in blob.lower():
            return False
    return True
