"""The system clipboard, through the tool each system ships: ``clip`` on Windows,
``pbcopy`` on macOS, ``wl-copy`` under Wayland, ``xclip`` under X11.

Standard library only (PRD N-2): the text goes to the tool's standard input.
"""
import os
import shutil
import subprocess
import sys

# (tool, arguments, encoding of its input)
TOOLS = {
    "win32": [("clip", [], "utf-16-le")],
    "darwin": [("pbcopy", [], "utf-8")],
    "linux": [("wl-copy", [], "utf-8"), ("xclip", ["-selection", "clipboard"], "utf-8")],
}


def tools(environ=None, platform=None):
    """The candidate tools, best first, for this system."""
    environ = os.environ if environ is None else environ
    platform = platform or sys.platform
    found = TOOLS.get(platform) or TOOLS["linux"]
    if found is TOOLS["linux"] and not environ.get("WAYLAND_DISPLAY"):
        found = found[::-1]   # X11: xclip first
    return found


def copy(text, environ=None, platform=None):
    """Puts ``text`` in the clipboard. The name of the tool used, or None when no
    tool is installed or it failed."""
    for name, args, encoding in tools(environ, platform):
        path = shutil.which(name)
        if not path:
            continue
        try:
            done = subprocess.run([path, *args], input=text.encode(encoding), check=False,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            return name
    return None
