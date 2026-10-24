"""A small JSON Schema validator, built in so the engine needs no extra package.

It covers the subset of JSON Schema 2020-12 that the schemas of ``schemas/`` use:

- ``type`` (one name or a list): object, array, string, integer, number, boolean, null;
- ``required``, ``properties``, ``additionalProperties`` (boolean or schema), ``propertyNames``;
- ``enum``, ``const``, ``pattern``, ``minLength``, ``maxLength``;
- ``minimum``, ``maximum``;
- ``items``, ``minItems``, ``maxItems``, ``uniqueItems``;
- ``anyOf``, ``oneOf``;
- ``$ref`` to ``#/$defs/<name>`` inside the same schema.

Errors carry the path of the faulty value, such as ``$.run.max_agents``.
Continuous integration checks the same schemas and fixtures with ``jsonschema``.
"""
import functools
import json
import os
import re

from probandia.errors import SchemaError, SchemaVersionError
from probandia.i18n import _

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}

SUPPORTED = {
    "$schema", "$id", "$defs", "$ref", "$comment", "title", "description", "examples",
    "default", "type", "required", "properties", "additionalProperties", "enum", "const",
    "pattern", "minLength", "maxLength", "minimum", "maximum", "items", "minItems",
    "maxItems", "uniqueItems", "anyOf", "oneOf", "format", "propertyNames",
}


class ValidationIssue:
    def __init__(self, path, message):
        self.path = path
        self.message = message

    def __str__(self):
        return f"{self.path}: {self.message}"

    def __repr__(self):
        return f"ValidationIssue({self.path!r}, {self.message!r})"


def _child(path, key):
    if isinstance(key, int):
        return f"{path}[{key}]"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def _show(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


class Validator:
    def __init__(self, schema):
        self.schema = schema
        self._check_keywords(schema, "#")

    def _check_keywords(self, node, where):
        """Refuses a schema that uses a keyword this validator does not know,
        so a schema can never be silently half-checked."""
        if not isinstance(node, dict):
            return
        unknown = set(node) - SUPPORTED
        if unknown:
            raise ValueError(f"schema keyword(s) not supported at {where}: {sorted(unknown)}")
        for key in ("properties", "$defs"):
            for name, sub in node.get(key, {}).items():
                self._check_keywords(sub, f"{where}/{key}/{name}")
        for key in ("items", "additionalProperties", "propertyNames"):
            if isinstance(node.get(key), dict):
                self._check_keywords(node[key], f"{where}/{key}")
        for key in ("anyOf", "oneOf"):
            for i, sub in enumerate(node.get(key, [])):
                self._check_keywords(sub, f"{where}/{key}/{i}")

    def _resolve(self, ref):
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"unsupported $ref {ref!r}")
        return self.schema["$defs"][ref[len("#/$defs/"):]]

    def errors(self, value):
        """Every issue found, in document order."""
        out = []
        self._validate(value, self.schema, "$", out)
        return out

    def _type_fits(self, v, s):
        """True when the value has the type an alternative declares (or it declares none)."""
        while "$ref" in s and "type" not in s:
            s = self._resolve(s["$ref"])
        if "type" not in s:
            return True
        types = s["type"] if isinstance(s["type"], list) else [s["type"]]
        return any(_TYPES[t](v) for t in types)

    def _validate(self, v, s, path, out):
        if "$ref" in s:
            self._validate(v, self._resolve(s["$ref"]), path, out)
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(_TYPES[t](v) for t in types):
                out.append(ValidationIssue(path, _("expected {types}, got {value}").format(
                    types=" or ".join(types), value=_show(v))))
                return
        if "const" in s and v != s["const"]:
            out.append(ValidationIssue(path, _("must be {expected}, got {value}").format(
                expected=_show(s["const"]), value=_show(v))))
        if "enum" in s and v not in s["enum"]:
            allowed = ", ".join(_show(e) for e in s["enum"])
            out.append(ValidationIssue(path, _("must be one of {allowed}; got {value}").format(
                allowed=allowed, value=_show(v))))
        if isinstance(v, str):
            if "minLength" in s and len(v) < s["minLength"]:
                out.append(ValidationIssue(path, _("shorter than {n} characters").format(n=s["minLength"])))
            if "maxLength" in s and len(v) > s["maxLength"]:
                out.append(ValidationIssue(path, _("longer than {n} characters").format(n=s["maxLength"])))
            if "pattern" in s and not re.search(s["pattern"], v):
                out.append(ValidationIssue(path, _("does not match {pattern}: {value}").format(
                    pattern=s["pattern"], value=_show(v))))
        if _TYPES["number"](v):
            if "minimum" in s and v < s["minimum"]:
                out.append(ValidationIssue(path, _("less than {n}: {value}").format(n=s["minimum"], value=v)))
            if "maximum" in s and v > s["maximum"]:
                out.append(ValidationIssue(path, _("greater than {n}: {value}").format(n=s["maximum"], value=v)))
        if isinstance(v, list):
            if "minItems" in s and len(v) < s["minItems"]:
                out.append(ValidationIssue(path, _("fewer than {n} items").format(n=s["minItems"])))
            if "maxItems" in s and len(v) > s["maxItems"]:
                out.append(ValidationIssue(path, _("more than {n} items").format(n=s["maxItems"])))
            if s.get("uniqueItems"):
                seen = []
                for i, item in enumerate(v):
                    if item in seen:
                        out.append(ValidationIssue(_child(path, i), _("duplicate item {value}").format(
                            value=_show(item))))
                    seen.append(item)
            if isinstance(s.get("items"), dict):
                for i, item in enumerate(v):
                    self._validate(item, s["items"], _child(path, i), out)
        if isinstance(v, dict):
            if isinstance(s.get("propertyNames"), dict):
                for key in v:
                    self._validate(key, s["propertyNames"], _child(path, key), out)
            for key in s.get("required", []):
                if key not in v:
                    out.append(ValidationIssue(_child(path, key), _("required")))
            props = s.get("properties", {})
            for key, item in v.items():
                if key in props:
                    self._validate(item, props[key], _child(path, key), out)
                else:
                    extra = s.get("additionalProperties", True)
                    if extra is False:
                        out.append(ValidationIssue(_child(path, key), _("unknown key")))
                    elif isinstance(extra, dict):
                        self._validate(item, extra, _child(path, key), out)
        for key in ("anyOf", "oneOf"):
            if key in s:
                results = []
                for sub in s[key]:
                    found = []
                    self._validate(v, sub, path, found)
                    results.append(found)
                matches = sum(1 for r in results if not r)
                if key == "anyOf" and matches == 0 or key == "oneOf" and matches != 1:
                    # the alternative of the value's own type explains the failure, even with
                    # more issues: an object refused by {null | object} is not "expected null"
                    best = results[min(range(len(results)),
                                       key=lambda i: (not self._type_fits(v, s[key][i]), len(results[i])))]
                    if key == "oneOf" and matches > 1:
                        out.append(ValidationIssue(path, _("matches more than one alternative")))
                    else:
                        out.extend(best)


# Schemas of the repository


def schemas_dir():
    """``schemas/``: in the package of a wheel, else at the root of the repository."""
    from probandia.paths import data

    return data("schemas")


def known_versions(name):
    """The schema versions available for a format, for example research -> [1]."""
    versions = []
    for f in os.listdir(schemas_dir()):
        m = re.match(rf"^{re.escape(name)}-(\d+)\.json$", f)
        if m:
            versions.append(int(m.group(1)))
    return sorted(versions)


def load_schema(name, version):
    path = os.path.join(schemas_dir(), f"{name}-{version}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# Formats whose documents carry no schema version of their own (one event per
# line of events.jsonl): the version of their schema.
UNVERSIONED = {"event": 1}


@functools.cache
def _event_types():
    return frozenset(load_schema("event", UNVERSIONED["event"])["properties"]["type"]["enum"])


def check_event_type(event, source="event"):
    """An event whose type this engine does not know was written by a newer
    version: SchemaVersionError (exit 2), not a damaged file."""
    type_ = event.get("type") if isinstance(event, dict) else None
    if isinstance(type_, str) and type_ not in _event_types():
        raise SchemaVersionError(
            _("{source}: event type {type} is newer than this engine knows; update Probandia").format(
                source=source, type=type_), [ValidationIssue("$.type", _("not a type this engine knows"))])


def validate_document(name, doc, source="document"):
    """Validates a document of format ``name`` against the schema of its version.

    Raises SchemaVersionError for a version newer than this engine knows, and
    SchemaError, carrying every issue, when the document does not match.
    """
    known = known_versions(name)
    if name in UNVERSIONED and isinstance(doc, dict) and "schema" not in doc:
        if name == "event":
            check_event_type(doc, source)
        issues = Validator(load_schema(name, UNVERSIONED[name])).errors(doc)
        if issues:
            raise SchemaError(_("{source}: {n} error(s); first: {first}").format(
                source=source, n=len(issues), first=issues[0]), issues,
                lines=[str(i) for i in issues[:10]])
        return doc
    version = doc.get("schema") if isinstance(doc, dict) else None
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SchemaError(_("{source}: missing or invalid 'schema' version").format(source=source),
                          [ValidationIssue("$.schema", _("required: a positive integer"))])
    if version > max(known):
        raise SchemaVersionError(
            _("{source}: {name} schema {version} is newer than this engine knows "
              "(up to {known}); update Probandia").format(
                source=source, name=name, version=version, known=max(known)))
    if version not in known:
        raise SchemaError(_("{source}: unknown {name} schema version {version}").format(
            source=source, name=name, version=version))
    issues = Validator(load_schema(name, version)).errors(doc)
    if issues:
        raise SchemaError(_("{source}: {n} error(s); first: {first}").format(
            source=source, n=len(issues), first=issues[0]), issues,
                          lines=[str(i) for i in issues[:10]])
    return doc
