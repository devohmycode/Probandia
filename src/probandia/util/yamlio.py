"""Reading and writing YAML.

Timestamps are kept as strings: PyYAML would turn ``2026-09-30T18:40:00Z`` or
``1851-03-02`` into date objects, which the schemas, the JSON files and
genealogical dates (often partial or uncertain) cannot use.
"""
import os
import sys

import yaml

from probandia.util.fs import atomic_write_text, read_text


class Loader(yaml.SafeLoader):
    """SafeLoader without the timestamp resolver."""


Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class Dumper(yaml.SafeDumper):
    """Block style, keys in their given order, Unicode kept as is."""


class InputLoader(Loader):
    """For a file an agent or a person wrote: a key given twice is refused, never the last one kept silently
    (T76: a second ``sources:`` added at the end of a proposal's draft would drop the first)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _value in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} is given twice",
                                                        key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_FAST = []   # [the loader], once looked for


def fast_loader():
    """T266: ``Loader`` on libyaml's parser, when this Python holds PyYAML's compiled ``_yaml`` at the vendored
    version (the same nodes, about ten times faster on a workshop of 14,000 lines); else None, and the pure
    Python loader reads. ``PROBANDIA_YAML_PURE=1`` keeps the pure one."""
    if not _FAST:
        _FAST.append(None if os.environ.get("PROBANDIA_YAML_PURE") else _find_fast())
    return _FAST[0]


def _find_fast():
    import glob
    import importlib.util

    try:
        for entry in [p for p in sys.path if p and os.path.isdir(os.path.join(p, "yaml"))]:
            same = glob.glob(os.path.join(entry, f"[Pp]y[Yy][Aa][Mm][Ll]-{yaml.__version__}.dist-info"))
            built = glob.glob(os.path.join(entry, "yaml", "_yaml*.pyd")) + glob.glob(os.path.join(entry, "yaml",
                                                                                                "_yaml*.so"))
            if not (same and built):
                continue
            if "yaml._yaml" not in sys.modules:
                spec = importlib.util.spec_from_file_location("yaml._yaml", built[0])
                module = importlib.util.module_from_spec(spec)
                sys.modules["yaml._yaml"] = module
                spec.loader.exec_module(module)
            from yaml import cyaml

            class FastLoader(cyaml.CSafeLoader):
                """CSafeLoader without the timestamp resolver, as Loader."""

            FastLoader.yaml_implicit_resolvers = Loader.yaml_implicit_resolvers
            return FastLoader
    except Exception:  # noqa: BLE001 — a compiled module that does not load leaves the pure loader
        sys.modules.pop("yaml._yaml", None)
    return None


def loads(text):
    return yaml.load(text, Loader=fast_loader() or Loader)


def load(path):
    return loads(read_text(path))


def load_input(path):
    """``load`` for a file written by an agent or a person: a syntax error becomes
    YamlSyntaxError, with its line, its column and a hint, never an internal error."""
    import os

    from probandia.errors import YamlSyntaxError
    from probandia.i18n import _

    try:
        return yaml.load(read_text(path), Loader=InputLoader)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        line, column = (mark.line + 1, mark.column + 1) if mark else (None, None)
        problem = getattr(err, "problem", None) or str(err).splitlines()[0]
        name = os.path.basename(path)
        where = f"{name}:{line}:{column}" if line else name
        raise YamlSyntaxError(_("{where}: not valid YAML: {problem}").format(where=where, problem=problem),
                              values={"FILE": name, "LINE": line, "COLUMN": column},
                              lines=[_("put double quotes around a value that holds : [ ] {{ }} # or starts "
                                       "with a quote, then run the command again")]) from None


def dumps(data):
    return yaml.dump(data, Dumper=Dumper, allow_unicode=True, sort_keys=False,
                     default_flow_style=False, width=100)


def dump(path, data):
    atomic_write_text(path, dumps(data))
