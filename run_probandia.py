"""Launcher of the Probandia engine inside a plugin.

Puts ``src/`` on ``sys.path`` and calls ``probandia.cli.main``. It is not named
``probandia.py``, because a root module of that name would hide the package.
"""
import os
import sys

if sys.version_info < (3, 11):   # before any import of the engine: tomllib came with 3.11
    sys.stderr.write("Python 3.11 or later is required (this is Python %d.%d)\n" % tuple(sys.version_info[:2]))
    sys.exit(2)

# A harness may export PYTHONDONTWRITEBYTECODE to its tools, hooks included: the engine would then compile
# every module it imports at each launch (some 200 ms of a hook's time, T145). Its own cache, next to its code.
sys.dont_write_bytecode = False

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

HOOK_FUNCTIONS = ("guard", "digest", "log", "verify", "session")
LEARNED_TOOLS = ("Skill", "Agent", "Task")   # hooks.LEARNED_TOOLS: their use counts outside a project too


def hook_outside_project(argv):
    """A hook run outside any project has nothing to do (token-economy G3): its answer,
    given without loading the engine, or None when the engine must run."""
    if argv[:1] != ["hook"] or len(argv) < 2 or argv[1] not in HOOK_FUNCTIONS or sys.stdin is None \
            or any(a in ("-p", "--project") or a.startswith("--project=") for a in argv):
        return None
    import io
    import json

    data = sys.stdin.buffer.read()
    sys.stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")   # the engine reads it again
    try:
        payload = json.loads(data.decode("utf-8-sig") or "{}")
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if argv[1] == "log" and (payload.get("tool_name") or (payload.get("toolCall") or {}).get("name")) in LEARNED_TOOLS:
        return None
    from probandia.errors import ProbandiaError
    from probandia.project import find_project
    from probandia.util import envfile

    try:
        find_project(None, envfile.merged(os.environ), payload.get("cwd") or os.getcwd())
        return None
    except ProbandiaError:
        pass
    harness = argv[argv.index("--harness") + 1] if "--harness" in argv[:-1] else \
        payload.get("harness") or os.environ.get("PROBANDIA_HARNESS")
    return '{"allowTool": true}\n' if argv[1] == "guard" and harness == "antigravity" else ""


if __name__ == "__main__":
    answer = hook_outside_project(sys.argv[1:])
    if answer is not None:
        sys.stdout.write(answer)
        sys.exit(0)
    from probandia.cli import main

    sys.exit(main())
