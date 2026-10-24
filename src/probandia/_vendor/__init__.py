"""Vendored pure-Python dependencies.

PyYAML, tomlkit, markdown-it-py and mdurl are copied here, so the engine runs on
a bare Python 3.11 or later with no ``pip install``. ``install()`` puts this
folder first on ``sys.path``: the engine then imports them by their usual names
(``import yaml``, ``import tomlkit``, ``import markdown_it``), always at the
versions pinned in ``vendor.txt``. ``LICENSES.md`` lists each licence.
"""
import os
import sys

VENDOR_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGES = ("yaml", "tomlkit", "markdown_it", "mdurl")


def install():
    """Puts the vendored libraries first on sys.path. Idempotent."""
    if VENDOR_DIR not in sys.path:
        sys.path.insert(0, VENDOR_DIR)
