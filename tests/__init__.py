"""Test package of Probandia.

Importing it does two things:
- puts ``src/`` on ``sys.path``, so the tests run without installing the package;
- blocks every socket connection, so a test that touches the network fails.
  Tests use recorded responses instead.

``python -m unittest discover -s tests`` does not import this file by itself:
each test sub-package imports it first (see ``tests/unit/__init__.py``).
"""
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# version-1.0.0 T217: Exa, Parallel, Tavily and Linkup may train on what they are sent; a test that runs them allows it
REUSE = {"PROBANDIA_PROVIDERS_ALLOW_CONTENT_REUSE": "true"}
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# No test writes into the user's own data folder (the quota counter, the INSEE files).
import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

from probandia.project import search_upwards  # noqa: E402

# Nor into a project of the user's: a test "outside a project" works in a temporary folder or in the
# checkout, and the engine looks for probandia.toml upwards from there. A project above them (at the
# root of the home folder, 26 October 2026) took the tests' writes and failed some hundred of them.
for _start in (tempfile.gettempdir(), ROOT):
    _above = search_upwards(_start)
    if _above:
        raise RuntimeError(f"a Probandia project ({os.path.join(_above, 'probandia.toml')}) holds {_start}: "
                           "the tests would write into it; move it, or point TMP/TEMP elsewhere")

from probandia import paths  # noqa: E402

if paths.FALLBACK_DATA_DIR is None:
    paths.FALLBACK_DATA_DIR = tempfile.mkdtemp(prefix="probandia-tests-data-")
    atexit.register(shutil.rmtree, paths.FALLBACK_DATA_DIR, ignore_errors=True)   # nothing left in the temp folder


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to open a network connection."""


def _blocked(*args, **kwargs):
    sys.audit("socket.connect", None, args)   # as a connection would: an audit hook sees the attempt (T109)
    raise NetworkBlocked("network access is blocked in tests")


if not getattr(socket, "_probandia_blocked", False):
    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
    socket._probandia_blocked = True
