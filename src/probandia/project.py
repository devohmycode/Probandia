"""Finding and creating a project.

A project is a folder holding ``probandia.toml``. It is found, in this order:
1. the ``--project`` option;
2. the ``PROBANDIA_PROJECT`` variable;
3. the first folder containing ``probandia.toml``, from the current folder upwards.
"""
import os

from probandia.errors import NotInProject
from probandia.i18n import _
from probandia.util.fs import atomic_write_text

PROJECT_FILE = "probandia.toml"
ENV_VAR = "PROBANDIA_PROJECT"

# Folders created with a new project. Empty ones are not kept by git, which is fine:
# each command creates what it needs.
LAYOUT_DIRS = (
    "families",
    "library/connectors",
    "library/helpers",
    ".probandia/cache",
    ".probandia/locks",
    ".probandia/logs",
)

GITIGNORE_LINES = ("work/", ".probandia/", "probandia.local.toml", ".env")

def is_project(path):
    return os.path.isfile(os.path.join(path, PROJECT_FILE))


def search_upwards(start):
    """The first folder holding probandia.toml, from ``start`` upwards, or None."""
    current = os.path.abspath(start)
    while True:
        if is_project(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def find_project(explicit=None, environ=None, cwd=None):
    """The project root. Raises NotInProject when there is none."""
    environ = os.environ if environ is None else environ
    for origin, candidate in (("--project", explicit), (ENV_VAR, environ.get(ENV_VAR))):
        if candidate:
            root = os.path.abspath(candidate)
            if not is_project(root):
                raise NotInProject(_("{origin} points to {root}, which holds no {file}")
                                   .format(origin=origin, root=root, file=PROJECT_FILE))
            return root
    root = search_upwards(cwd or os.getcwd())
    if root is None:
        raise NotInProject(_("not inside a project: no {file} here or above").format(file=PROJECT_FILE),
                           lines=[_("create one with: config init")])
    return root


def create_project(root, grade=1):
    """Creates the project layout in ``root``, with a probandia.toml written for
    ``grade`` (1 Essential, 2 Advanced, 3 Expert). Idempotent: an existing
    probandia.toml is kept, and missing .gitignore lines are appended; a
    .env.example listing the keys is written when there is none.
    Returns the list of paths written, relative to ``root``."""
    root = os.path.abspath(root)
    written = []
    os.makedirs(root, exist_ok=True)
    for d in LAYOUT_DIRS:
        os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
    toml_path = os.path.join(root, PROJECT_FILE)
    if not os.path.exists(toml_path):
        from probandia.config.tomlfile import template

        atomic_write_text(toml_path, template(grade))
        written.append(PROJECT_FILE)
    gi_path = os.path.join(root, ".gitignore")
    existing = []
    if os.path.exists(gi_path):
        with open(gi_path, encoding="utf-8-sig") as fh:
            existing = fh.read().splitlines()
    missing = [line for line in GITIGNORE_LINES if line not in (e.strip() for e in existing)]
    if missing:
        lines = existing + ([""] if existing and existing[-1].strip() else []) + missing
        atomic_write_text(gi_path, "\n".join(lines) + "\n")
        written.append(".gitignore")
    example = os.path.join(root, ".env.example")
    if not os.path.exists(example):
        from probandia.util.envfile import TEMPLATE

        atomic_write_text(example, TEMPLATE)
        written.append(".env.example")
    return written
