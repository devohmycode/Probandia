"""Settings that a harness exposes as plugin options.

Claude Code declares them as ``userConfig`` in ``.claude-plugin/plugin.json``.
Its keys cannot hold dots, so they use underscores (``report_mode``). Plugin
option variables do not reach the agent's shell commands, but Claude Code
exports them to its hooks (``CLAUDE_PLUGIN_OPTION_<KEY>``): the session hooks
keep them for the engine's calls (``launcher``), the second configuration
layer. ``--harness-options "language=fr;report_mode=living"`` still sets them.

An empty value means that the option is not set. ``report_formats`` is a
comma-separated string, because Claude does not show multi-valued options in
``/config``.
"""
from probandia.config import registry

TITLES = {
    "language": "Report language",
    "report.mode": "Report mode",
    "report.numbering": "Numbering",
    "report.formats": "Report formats (comma-separated: md, html, json)",
    "tree.format": "Tree file format",
    "run.mode": "Who runs a research",
    "search.max_parallel": "Parallel web searches",
    "grade": "Settings grade",
}
DESCRIPTIONS = {
    "language": "auto, or a language code such as en or fr",
}
# Values offered in /config: roman-outline stays an expert value, set in a file.
OPTIONS = {"report.numbering": ["arabic", "roman"]}
# Claude Code shows every option at install, where it cannot be changed: only the
# two that matter before a first research. The others stay in probandia.toml,
# /probandia:config and --harness-options.
CLAUDE_CODE = ("language", "run.mode")


def user_config():
    """The ``userConfig`` object of the Claude Code manifest."""
    out = {}
    for s in registry.harness_settings():
        if s.key not in CLAUDE_CODE:
            continue
        entry = {"type": "number" if s.type == "int" else "string", "title": TITLES[s.key]}
        if s.key in DESCRIPTIONS:
            entry["description"] = DESCRIPTIONS[s.key]
        else:
            entry["description"] = s.help
        if s.type == "enum":
            entry["options"] = OPTIONS.get(s.key, list(s.values))
        if s.type == "int":
            entry["min"], entry["max"] = s.values
        entry["default"] = ",".join(s.default) if s.type == "list" else s.default
        out[s.harness_key] = entry
    return out
