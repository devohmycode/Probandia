"""Where the engine finds its data: ``catalogues/``, ``locales/``, ``schemas/``,
``vendor-js/``, ``report-templates/`` and ``designer/``.

- An installed wheel carries them inside the package, under ``probandia/_data/``.
- The plugin and an editable install read them at the root of the repository,
  two levels above the package (``src/probandia/``).

The files of the plugin itself (``agents/``, ``commands/``, ``run_probandia.py``)
stay at the root of the repository: see ``install.convert.package_root``.
"""
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED = "_data"


def data_root(package_dir=None):
    """``probandia/_data`` when the package carries its data, else the repository root."""
    package_dir = package_dir or PACKAGE_DIR
    bundled = os.path.join(package_dir, BUNDLED)
    if os.path.isdir(bundled):
        return bundled
    return os.path.dirname(os.path.dirname(package_dir))


def data(*parts, package_dir=None):
    """The path of a data file or folder, for example ``data("catalogues", "providers.toml")``."""
    return os.path.join(data_root(package_dir), *parts)


# The user's data folder: the INSEE files, and the quota counter (cli.md § 4.4).

# Set by the test suite, so that no test ever writes into the user's own folder.
FALLBACK_DATA_DIR = None


def user_data_dir(environ=None):
    """``PROBANDIA_DATA_DIR``; else ``<PROBANDIA_CONFIG_DIR>/data`` when that variable
    relocates the user's folders; else ``%LOCALAPPDATA%/probandia`` on Windows,
    ``$XDG_DATA_HOME/probandia`` or ``~/.local/share/probandia`` elsewhere. Not the
    roaming ``%APPDATA%``: the counter grows."""
    environ = os.environ if environ is None else environ
    if environ.get("PROBANDIA_DATA_DIR"):
        return environ["PROBANDIA_DATA_DIR"]
    if environ.get("PROBANDIA_CONFIG_DIR"):
        return os.path.join(environ["PROBANDIA_CONFIG_DIR"], "data")
    if FALLBACK_DATA_DIR:
        return FALLBACK_DATA_DIR
    if os.name == "nt" and environ.get("LOCALAPPDATA"):
        return os.path.join(environ["LOCALAPPDATA"], "probandia")
    base = environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "probandia")
