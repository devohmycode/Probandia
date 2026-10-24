"""Settings in effect, merged from seven layers.

Layers, from lowest to highest priority:

1. ``default``  the registry's built-in defaults;
2. ``harness``  plugin options passed with ``--harness-options "k=v;..."``;
3. ``user``     the user file (``%APPDATA%\\probandia\\config.toml``,
                ``$XDG_CONFIG_HOME/probandia/config.toml`` or
                ``~/.config/probandia/config.toml``; ``PROBANDIA_CONFIG_DIR`` replaces the folder);
4. ``project``  ``probandia.toml``;
5. ``local``    ``probandia.local.toml``, not versioned;
6. ``env``      ``PROBANDIA_*`` variables;
7. ``arg``      command arguments.

Tables merge key by key and lists are replaced, never concatenated: every
setting is merged as one flat dotted key. An unknown key is a warning. An
invalid value is an error (exit code 2) naming the key, the layer and the
allowed values. Every value in effect keeps its layer and its source.
"""
import os
import tomllib

from probandia.config import registry
from probandia.errors import UsageError
from probandia.i18n import _
from probandia.util.fs import read_text

LAYERS = ("default", "harness", "user", "project", "local", "env", "arg")
PROJECT_FILE = "probandia.toml"
LOCAL_FILE = "probandia.local.toml"
TRUE = ("1", "true", "yes", "on")
FALSE = ("0", "false", "no", "off")


class ConfigError(UsageError):
    reason = "config"

    def __init__(self, problems):
        self.problems = list(problems)
        first = self.problems[0] if self.problems else _("invalid configuration")
        super().__init__(first, lines=self.problems[1:10])


class Origin:
    def __init__(self, layer, source):
        self.layer = layer
        self.source = source

    def __str__(self):
        return f"{self.layer} {self.source}"

    def __repr__(self):
        return f"Origin({self.layer!r}, {self.source!r})"


# files


def user_config_path(environ=None):
    environ = os.environ if environ is None else environ
    folder = environ.get("PROBANDIA_CONFIG_DIR")
    if not folder:
        if os.name == "nt" and environ.get("APPDATA"):
            base = environ["APPDATA"]
        else:
            base = environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        folder = os.path.join(base, "probandia")
    return os.path.join(folder, "config.toml")


def layer_paths(project_root=None, environ=None):
    """{layer: path} of the three files."""
    paths = {"user": user_config_path(environ)}
    if project_root:
        paths["project"] = os.path.join(project_root, PROJECT_FILE)
        paths["local"] = os.path.join(project_root, LOCAL_FILE)
    return paths


def flatten(table, prefix=""):
    """{"report": {"mode": "x"}} -> {"report.mode": "x"}. Settings never hold tables."""
    out = {}
    for k, v in table.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def read_toml(path):
    """The flat keys of a TOML file; {} when it does not exist."""
    try:
        data = tomllib.loads(read_text(path))   # read_text drops a BOM (Windows Notepad writes one)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as err:
        raise ConfigError([_("{path}: not valid TOML: {error}").format(path=path, error=err)])
    return flatten(data)


# values


def parse_text(setting, text):
    """A value given as text (variable, harness option, argument) -> its typed value."""
    text = text.strip()
    if setting.type == "int":
        try:
            return int(text)
        except ValueError:
            raise ValueError(text)
    if setting.type == "bool":
        low = text.lower()
        if low in TRUE:
            return True
        if low in FALSE:
            return False
        raise ValueError(text)
    if setting.type == "list":
        return [item.strip() for item in text.split(",") if item.strip()]
    return text


def check_value(setting, value):
    """Returns the value, normalised, or raises ValueError."""
    t = setting.type
    if t == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(value)
        if setting.values and not setting.values[0] <= value <= setting.values[1]:
            raise ValueError(value)
        return value
    if t == "bool":
        if not isinstance(value, bool):
            raise ValueError(value)
        return value
    if t == "list":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
            raise ValueError(value)
        if setting.items:
            bad = [i for i in value if i not in setting.items]
            if bad:
                raise ValueError(bad[0])
        if len(set(value)) != len(value):
            raise ValueError(value)
        return list(value)
    if t == "enum":
        if value not in setting.values:
            raise ValueError(value)
        return value
    if not isinstance(value, str):
        raise ValueError(value)
    if setting.check is not None and not (setting.key == "language" and value == "auto"):
        if not setting.check.match(value):
            raise ValueError(value)
    return value


def show(value):
    """A value as text: lists comma-separated, booleans in lower case."""
    if value is None:
        return _("(unset)")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(value)
    return str(value)


def parse_harness_options(text):
    """``"language=fr;report_mode=living;grade="`` -> {"language": "fr", ...}.
    Empty values, and values the harness left unsubstituted (``${...}``), are unset."""
    out = {}
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        name, sep, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name:
            raise ConfigError([_("--harness-options: expected k=v pairs separated by ';', got {part!r}")
                               .format(part=part)])
        if value and "${" not in value:
            out[name] = value
    return out


class Config:
    """The settings in effect."""

    def __init__(self):
        self.values = {}
        self.origins = {}
        self.warnings = []
        self.problems = []
        for key, default in registry.concrete_keys():
            self.values[key] = default
            self.origins[key] = Origin("default", "built-in")

    def get(self, key):
        if key in self.values:
            return self.values[key]
        return registry.default_of(key)

    def origin(self, key):
        return self.origins.get(key) or Origin("default", "built-in")

    @property
    def grade(self):
        return registry.GRADE_NUMBERS[self.values["grade"]]

    def above_grade(self, key):
        """Set (not left at its default) by a setting above the user's grade."""
        setting = registry.lookup(key)
        return bool(setting) and setting.grade > self.grade and self.origin(key).layer != "default"

    def keys(self, max_grade=3):
        """Concrete keys up to a grade, plus any key set above it that is open-ended."""
        out = [k for k, default in registry.concrete_keys(max_grade)]
        extra = [k for k in self.values if k not in out and registry.lookup(k)
                 and registry.lookup(k).grade <= max_grade]
        return out + extra

    # merging

    def apply(self, layer, source, items, text=False):
        """Merges one layer. ``items``: {key: value}; ``text``: values are strings to parse.
        ``source`` is a string, or a function key -> string (for variables)."""
        for key, raw in items.items():
            where = source(key) if callable(source) else source
            if key in registry.META_KEYS and layer in ("user", "project", "local"):
                continue
            setting = registry.lookup(key)
            new = registry.RENAMED.get(key)
            if new and layer in ("user", "project", "local"):
                self.warnings.append(_("{key} in {layer} ({source}) is deprecated; use {new}")
                                     .format(key=key, layer=layer, source=where, new=new))
                if setting is None:
                    key, setting = new, registry.lookup(new)
            if setting is None:
                self.warnings.append(_("unknown setting {key} in {layer} ({source}); ignored")
                                     .format(key=key, layer=layer, source=where))
                continue
            try:
                value = parse_text(setting, raw) if text and isinstance(raw, str) else raw
                value = check_value(setting, value)
            except ValueError:
                self.problems.append(
                    _("invalid value {value} for {key} in {layer} ({source}); allowed: {allowed}")
                    .format(value=repr(raw), key=key, layer=layer, source=where,
                            allowed=setting.describe_values()))
                continue
            self.values[key] = value
            self.origins[key] = Origin(layer, where)


def env_items(environ):
    """{key: (value, variable)} from PROBANDIA_* variables; aliases rank below main names."""
    found, unknown = {}, []
    names = sorted((v for v in environ if v.startswith("PROBANDIA_") and v not in registry.OTHER_VARIABLES),
                   key=lambda v: _is_alias(v))
    for var in reversed(names):  # main names last, so they win
        value = environ[var]
        key = registry.env_lookup(var)
        if key is None:
            unknown.append(var)
        elif value.strip():
            found[key] = (value, var)
    return found, unknown


def _is_alias(var):
    return any(var in s.env_aliases for s in registry.SETTINGS)


def load(project_root=None, environ=None, harness_options=None, args=None, strict=True):
    """The settings in effect. ``args``: {key: value} from command arguments.
    Raises ConfigError on an invalid value unless ``strict`` is False."""
    environ = os.environ if environ is None else environ
    cfg = Config()
    paths = layer_paths(project_root, environ)
    if harness_options:
        by_name = {s.harness_key: s.key for s in registry.harness_settings()}
        items = {}
        for name, value in parse_harness_options(harness_options).items():
            items[by_name.get(name, name)] = value
        cfg.apply("harness", "--harness-options", items, text=True)
    for layer in ("user", "project", "local"):
        path = paths.get(layer)
        if path:
            try:
                items = read_toml(path)
            except ConfigError as err:
                cfg.problems.extend(err.problems)
                continue
            shown = os.path.basename(path) if layer != "user" else path
            cfg.apply(layer, shown, items)
    found, unknown = env_items(environ)
    for var in unknown:
        cfg.warnings.append(_("unknown variable {var}; ignored").format(var=var))
    cfg.apply("env", lambda key: found[key][1], {k: pair[0] for k, pair in found.items()}, text=True)
    if args:
        cfg.apply("arg", lambda key: registry.lookup(key).flag or "argument", args, text=True)
    if strict and cfg.problems:
        raise ConfigError(cfg.problems)
    return cfg
