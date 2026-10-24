"""Integration tests: the sample project, offline. Importing ``tests`` first blocks the network (tests/__init__.py)."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tests  # noqa: E402,F401
