"""The themes of ``probandia tui``: the two of Probandia, dark and light, and the user's own,
one TOML file each in the ``themes`` folder of the user's configuration folder
(``themes/<name>.toml``), written by ``config theme save``, readable and editable by hand.

A theme holds its colours (``#rrggbb``) and its layout. A value missing or wrong in a file
is taken from the theme it starts from (its ``base``, dark or light) and said, never raised:
the application always starts.
"""
import os
import re
import tomllib

from probandia.i18n import N_, _
from probandia.util.fs import atomic_write_text, read_text

SCHEMA = 1
BUILTIN = ("dark", "light")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# The colours of a theme, as Textual names them, and what each one paints.
COLORS = {"primary": N_("titles, the cursor and the main buttons"),
          "secondary": N_("column headers, section titles, the inner tabs"),
          "accent": N_("the mark of the focus, the frame of the windows"),
          "warning": N_("buttons that are hard to undo, confirmations"),
          "error": N_("errors"),
          "success": N_("what passed, Accept"),
          "foreground": N_("the text"),
          "background": N_("the background"),
          "surface": N_("the background of the windows and of the files"),
          "panel": N_("the background of the titles and the lines between columns")}
PALETTES = {
    "dark": {"primary": "#D4A64A", "secondary": "#7D9B84", "accent": "#C2714F", "warning": "#E8913A",
             "error": "#E06C5F", "success": "#8DB86B", "foreground": "#E8E2D4", "background": "#1A1916",
             "surface": "#23211D", "panel": "#2E2B25"},
    "light": {"primary": "#7E5210", "secondary": "#4C6B55", "accent": "#9E4A2E", "warning": "#A65A00",
              "error": "#A8352A", "success": "#3D7533", "foreground": "#2A2620", "background": "#F4EFE4",
              "surface": "#ECE5D6", "panel": "#E0D6C2"},
}

BUTTONS = ("compact", "tall")
FRAMES = ("round", "solid", "heavy", "double", "ascii")
# The layout: (default, what it is, its values: a tuple of choices, bool, or (min, max)).
LAYOUT = {"buttons": ("compact", N_("buttons on one line, or on three"), BUTTONS),
          "section_titles": (True, N_("each table of a section says what it is in its top line"), bool),
          "focus_mark": (True, N_("a line on the left of the table that has the focus"), bool),
          "zebra": (True, N_("one line in two shaded in the lists"), bool),
          "frames": ("round", N_("the frame of the windows"), FRAMES),
          "tree_width": (45, N_("width of the tree of the Family screen, in percent"), (25, 75)),
          "commands_width": (32, N_("width of the list of commands of the console, in columns"), (20, 60))}


def folder(environ=None):
    """``themes/`` in the user's configuration folder."""
    from probandia.config import user_config_path

    return os.path.join(os.path.dirname(user_config_path(environ)), "themes")


def path_of(name, environ=None):
    return os.path.join(folder(environ), f"{name}.toml")


def default_layout():
    return {key: spec[0] for key, spec in LAYOUT.items()}


def builtin(name):
    """The theme ``dark`` or ``light`` of Probandia."""
    return {"name": name, "base": name, "builtin": True, "file": None,
            "colors": dict(PALETTES[name]), "layout": default_layout()}


def check_name(name):
    """The name of a theme of one's own, or ValueError with the reason."""
    if name in BUILTIN:
        raise ValueError(_("{name} is a theme of Probandia: choose another name").format(name=name))
    if not NAME_RE.match(name or ""):
        raise ValueError(_("a theme's name is made of small letters, digits and hyphens, 40 at most: {name}")
                         .format(name=name))
    return name


def check(key, value):
    """``value`` for the colour or the layout entry ``key``, normalised; ValueError when it is wrong.
    A value given as text (``true``, ``40``) is read as its type."""
    if key in COLORS:
        if not isinstance(value, str) or not COLOR_RE.match(value):
            raise ValueError(_("{key}: a colour is written #rrggbb, not {value}").format(key=key, value=value))
        return value.upper()
    if key not in LAYOUT:
        raise ValueError(_("{key} is neither a colour nor a layout entry of a theme").format(key=key))
    values = LAYOUT[key][2]
    if values is bool:
        if isinstance(value, str) and value.lower() in ("true", "false", "yes", "no", "on", "off"):
            value = value.lower() in ("true", "yes", "on")
        if not isinstance(value, bool):
            raise ValueError(_("{key}: true or false, not {value}").format(key=key, value=value))
        return value
    if isinstance(values[0], int):
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int) or not values[0] <= value <= values[1]:
            raise ValueError(_("{key}: a number from {low} to {high}, not {value}").format(
                key=key, low=values[0], high=values[1], value=value))
        return value
    if value not in values:
        raise ValueError(_("{key}: one of {values}, not {value}").format(key=key, values=", ".join(values),
                                                                            value=value))
    return value


def from_document(name, doc, file=None):
    """(theme, [problems]) of a theme's TOML document: what is missing or wrong is its base's."""
    problems = []
    base = doc.get("base", "dark")
    if base not in BUILTIN:
        problems.append(_("base: dark or light, not {value}").format(value=base))
        base = "dark"
    theme = dict(builtin(base), name=name, base=base, builtin=False, file=file)
    for section, keys in (("colors", COLORS), ("layout", LAYOUT)):
        given = doc.get(section, {})
        if not isinstance(given, dict):
            problems.append(_("{section} is a table").format(section=section))
            continue
        for key, value in given.items():
            if key not in keys:
                problems.append(_("{key} is neither a colour nor a layout entry of a theme").format(key=key))
                continue
            try:
                theme[section][key] = check(key, value)
            except ValueError as err:
                problems.append(str(err))
    return theme, problems


def read(name, environ=None):
    """(theme, [problems]) of the file of the theme ``name``; FileNotFoundError when there is none."""
    path = path_of(name, environ)
    try:
        doc = tomllib.loads(read_text(path))
    except tomllib.TOMLDecodeError as err:
        theme = dict(builtin("dark"), name=name, builtin=False, file=path)
        return theme, [_("not TOML: {error}").format(error=err)]
    return from_document(name, doc, path)


def load(environ=None):
    """{name: theme} of every theme, Probandia's first, then the user's in the order of their names;
    and {name: [problems]} of the files that hold a wrong value."""
    out = {name: builtin(name) for name in BUILTIN}
    problems = {}
    try:
        names = sorted(n[:-5] for n in os.listdir(folder(environ)) if n.endswith(".toml"))
    except OSError:
        names = []
    for name in names:
        try:
            check_name(name)
        except ValueError as err:
            problems[name] = [str(err)]
            continue
        try:
            out[name], found = read(name, environ)
        except OSError as err:
            problems[name] = [str(err)]
            continue
        if found:
            problems[name] = found
    return out, problems


def document(theme):
    """The text of the file of ``theme``."""
    def value(v):
        return ("true" if v else "false") if isinstance(v, bool) else str(v) if isinstance(v, int) else f'"{v}"'

    out = ["# " + _("A theme of probandia tui: its colours (#rrggbb) and its layout."),
           "# " + _("Edited in the application (Config, Themes), with config theme save, or by hand."),
           f"schema = {SCHEMA}", f'base = "{theme["base"]}"', "", "[colors]"]
    out += [f"{key} = {value(theme['colors'][key])}" for key in COLORS]
    out += ["", "[layout]"] + [f"{key} = {value(theme['layout'][key])}" for key in LAYOUT]
    return "\n".join(out) + "\n"


def save(name, base=None, start=None, changes=(), environ=None):
    """Writes the theme ``name``: the values of ``start`` (a theme's name: its own file when it has
    one, else ``base``), then ``changes`` [(key, value)]. Returns (theme, path, replaced).
    ValueError when a name or a value is wrong; nothing is written then."""
    check_name(name)
    themes, _problems = load(environ)
    origin = start or (name if name in themes else None) or base or "dark"
    if origin not in themes:
        raise ValueError(_("no theme named {name}").format(name=origin))
    theme = {**themes[origin], "colors": dict(themes[origin]["colors"]), "layout": dict(themes[origin]["layout"])}
    if base is not None:
        if base not in BUILTIN:
            raise ValueError(_("base: dark or light, not {value}").format(value=base))
        theme["base"] = base
    for key, value in changes:
        theme["colors" if key in COLORS else "layout"][key] = check(key, value)
    path = path_of(name, environ)
    replaced = os.path.isfile(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    theme.update(name=name, builtin=False, file=path)
    atomic_write_text(path, document(theme))
    return theme, path, replaced


def delete(name, environ=None):
    """Removes the file of the theme ``name``; False when there was none."""
    check_name(name)
    try:
        os.remove(path_of(name, environ))
    except FileNotFoundError:
        return False
    return True
