"""Writing configuration files with tomlkit, which keeps comments and layout.

Keys are written as dotted keys (``report.mode = "living"``). When an existing
table holds the key's parent (``[report]``), the key goes into that table.
A key whose prefix is itself a setting (``language.detection_order`` next to
``language``) is written quoted (``"language.detection_order" = [...]``), since
TOML cannot make ``language`` both a string and a table.
"""
import os
import re

import tomlkit
from tomlkit.items import Table

from probandia.config import registry
from probandia.i18n import _
from probandia.util.fs import atomic_write_text, read_text

HOSTS_RE = re.compile(r"^hosts\.(.+)\.rate$")


def key_parts(key):
    """The TOML key parts of a setting key."""
    parts = key.split(".")
    for i in range(1, len(parts)):
        prefix = registry.lookup(".".join(parts[:i]))
        if prefix is not None:
            return [key]  # the prefix is a value: the key must stay one quoted part
    m = HOSTS_RE.match(key)
    if m:
        return ["hosts", m.group(1), "rate"]
    return parts


def key_text(key):
    return ".".join(tomlkit.key(p).as_string() for p in key_parts(key))


def value_text(value):
    return tomlkit.item(value).as_string()


def _leaves(container, prefix=()):
    """(container, name, parts) for every value of a tomlkit document."""
    for name, item in list(container.items()):
        parts = prefix + (name,)
        if isinstance(item, (Table, dict)) and not isinstance(item, list):
            yield from _leaves(item, parts)
        else:
            yield container, name, parts


def _find(doc, key):
    for container, name, parts in _leaves(doc):
        if ".".join(parts) == key:
            return container, name
    return None, None


def load_document(path):
    if os.path.exists(path):
        return tomlkit.parse(read_text(path))
    return tomlkit.document()


def set_value(path, key, value, header=None):
    """Writes ``key = value`` into the file, creating it if needed."""
    text = read_text(path) if os.path.exists(path) else (header or "")
    doc = tomlkit.parse(text)
    container, name = _find(doc, key)
    if container is not None:
        container[name] = value
        new = tomlkit.dumps(doc)
    else:
        # A line left commented by `config init` is uncommented in place.
        # Only when no table already holds the key's parent: the template's lines
        # sit at the top level, where a dotted key would declare that table twice.
        rx = re.compile(rf"^#[ \t]*{re.escape(key_text(key))}[ \t]*=.*$", re.M)
        parts = key_parts(key)
        parent = doc.get(parts[0]) if len(parts) > 1 else None
        if rx.search(text) and (parent is None or isinstance(parent, Table) and parent.is_super_table()):
            new = rx.sub(lambda m: f"{key_text(key)} = {value_text(value)}", text, count=1)
        else:
            _add(doc, key_parts(key), value)
            new = tomlkit.dumps(doc)
    atomic_write_text(path, new)


def _add(doc, parts, value):
    container = doc
    for i, part in enumerate(parts[:-1]):
        item = container.get(part) if hasattr(container, "get") else None
        if isinstance(item, Table):
            container = item
            continue
        container.add(tomlkit.key(list(parts[i:])) if len(parts) - i > 1 else parts[-1], value)
        return
    container[parts[-1]] = value


def unset_value(path, key):
    """Removes the key from the file. Returns False when it was not there."""
    if not os.path.exists(path):
        return False
    doc = tomlkit.parse(read_text(path))
    container, name = _find(doc, key)
    if container is None:
        return False
    del container[name]
    _prune(doc)
    atomic_write_text(path, tomlkit.dumps(doc))
    return True


def _prune(container):
    """Removes the tables left empty."""
    for name, item in list(container.items()):
        if isinstance(item, Table):
            _prune(item)
            if not item.value:
                del container[name]


# the file written by `config init`


def _line(key, value, setting, commented):
    if value is None:
        if key.startswith("team."):
            hint = _("unset by default: asked at launch")
        elif key.endswith(".monthly_cap"):
            hint = _("unset by default: the free tier")
        else:
            hint = _("unset by default: the catalogue value")
        return f"# {key_text(key)} = <{setting.describe_values()}>  ({hint})"
    line = f"{key_text(key)} = {value_text(value)}"
    return "# " + line if commented else line


def template(grade=1):
    """The text of a new probandia.toml for a grade: the keys up to that grade,
    then the keys of higher grades, commented out with their defaults.

    The settings that a harness offers as plugin options (the Essential ones)
    are always written commented out: a value in this file wins over the
    harness, so writing them would silence the harness options for good. The
    grade is the exception when it is above Essential, since the user chose it.
    """
    name = registry.GRADES[grade]
    out = [
        "# " + _("Probandia project settings. Versioned with the project."),
        "# " + _("Local overrides that must not be versioned go to probandia.local.toml."),
        "# " + _("Show the settings in effect, and where they come from: config show --origin"),
        "schema = 1",
    ]
    titles = {1: _("Essential settings"), 2: _("Advanced settings"), 3: _("Expert settings")}
    for g in (1, 2, 3):
        commented = g > grade
        out.append("")
        title = titles[g]
        if commented:
            title += " — " + _("grade {grade}; uncomment a line to change it").format(
                grade=registry.GRADES[g])
        out.append(f"# {title}")
        if g == 1:
            out.append("# " + _("The language and who runs a research are also offered by the harness "
                              "(/config in Claude Code). Uncomment a line to fix the value for this "
                              "project: it then wins over the harness."))
        for setting in registry.by_grade(g):
            if setting.key in registry.RENAMED:   # a new file gets no old key, so no WARN
                continue
            out.append(f"# {_(setting.help)}")
            pairs = setting.expand()
            if setting.key == "grade":
                pairs = [("grade", name)]
                if grade > 1:
                    out.append(_line("grade", name, setting, False))
                    continue
            if setting.harness:
                for key, value in pairs:
                    out.append(_line(key, value, setting, True))
                continue
            if not pairs:  # open placeholder (hosts): an example
                example = setting.key.replace("<host>", "gallica.bnf.fr")
                out.append(f"# {key_text(example)} = {value_text('5/min')}")
                continue
            if "<id>" in setting.key:  # per provider: no default but the free tier
                example = setting.key.replace("<id>", "serpapi")
                out.append(_line(example, None, setting, True))
                continue
            if setting.key == "proof.standard":   # GPS-D5: a new project checks the standard, warn
                out.append(_line(setting.key, "warn", setting, False))
                continue
            for key, value in pairs:
                out.append(_line(key, value, setting, commented))
    return "\n".join(out) + "\n"
