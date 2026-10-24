"""Development tool: set the version of Probandia everywhere it is written.

    python tools/bump_version.py 0.9.42

Writes ``src/probandia/__init__.py`` (the only source, hatch reads it) and
``.claude-plugin/plugin.json``, then regenerates the other harness manifests
(``manifests generate``). Reference files carry no number: the tests replace it
with ``<version>``. Nothing is committed or tagged.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

INIT = os.path.join(ROOT, "src", "probandia", "__init__.py")
CLAUDE = os.path.join(ROOT, ".claude-plugin", "plugin.json")
VERSION_LINE = re.compile(r'^__version__ = "[^"]*"$', re.M)


def bump(version, root=ROOT):
    """Writes ``version``; returns the files that changed, relative to ``root``."""
    from probandia.install import manifests

    init = os.path.join(root, "src", "probandia", "__init__.py")
    with open(init, encoding="utf-8") as fh:
        text = fh.read()
    new, n = VERSION_LINE.subn(f'__version__ = "{version}"', text)
    if n != 1:
        raise SystemExit(f"{init}: no single __version__ line")
    changed = []
    if new != text:
        with open(init, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
        changed.append("src/probandia/__init__.py")
    claude = os.path.join(root, ".claude-plugin", "plugin.json")
    with open(claude, encoding="utf-8") as fh:
        src = json.load(fh)
    if src.get("version") != version:
        src["version"] = version
        with open(claude, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(manifests._json(src))
        changed.append(".claude-plugin/plugin.json")
    return changed + manifests.generate(root)


def main(argv):
    if len(argv) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[0]):
        print("usage: python tools/bump_version.py <major.minor.patch>", file=sys.stderr)
        return 2
    for rel in bump(argv[0]):
        print(rel)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
