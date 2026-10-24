"""The local browser of the reading ladder: headless Chromium through Playwright,
when it is installed. One persistent profile (cookie jar) per host, so a
challenge solved once is not solved again."""
import importlib.util
import json
import os
import sys


def available():
    return importlib.util.find_spec("playwright") is not None


def browsers_dir(environ=None):
    """Where Playwright keeps its browsers: ``PLAYWRIGHT_BROWSERS_PATH``, else its
    folder for this system."""
    environ = os.environ if environ is None else environ
    if environ.get("PLAYWRIGHT_BROWSERS_PATH") not in (None, "", "0"):
        return environ["PLAYWRIGHT_BROWSERS_PATH"]
    if sys.platform == "win32":
        return os.path.join(environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ms-playwright")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Caches", "ms-playwright")
    return os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")


def browser_state(environ=None):
    """``missing`` (no Playwright), ``no-browser`` (Playwright without the Chromium
    build it expects: ``python -m playwright install chromium``) or ``ready``."""
    spec = importlib.util.find_spec("playwright")
    if spec is None or not spec.origin:
        return "missing"
    manifest = os.path.join(os.path.dirname(spec.origin), "driver", "package", "browsers.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            revisions = {b["name"]: b["revision"] for b in json.load(fh)["browsers"]}
    except (OSError, ValueError, KeyError, TypeError):
        return "ready"   # an unknown layout: let the ladder try
    folder = browsers_dir(environ)
    for name in ("chromium-headless-shell", "chromium"):
        rev = revisions.get(name)
        if rev and os.path.isdir(os.path.join(folder, f"{name.replace('-', '_')}-{rev}")):
            return "ready"
    return "no-browser"


def install_command():
    """The command that installs the browser, for the Python running the engine."""
    exe = sys.executable or "python"
    return f'"{exe}" -m playwright install chromium' if " " in exe else f"{exe} -m playwright install chromium"


def fetch(url, profile_dir, timeout_ms=45000):
    """(status, html, final url)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(profile_dir, headless=True)
        try:
            page = context.new_page()
            response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            status = response.status if response else 0
            return status, page.content(), page.url
        finally:
            context.close()
