"""Converting the Claude Code sources (agents, commands, hooks, MCP) for each harness.

The Claude layout is the single source. Every other harness's files are
written from it by ``manifests generate`` or by the installers.
"""
import json
import os

from probandia.errors import UsageError
from probandia.i18n import _
from probandia.util import yamlio

CLAUDE_ROOT = "${CLAUDE_PLUGIN_ROOT}"

# Probandia effort -> the value each harness accepts. Checked on 1 October 2026 with each
# CLI: Droid lists low to max for the current Claude models (`droid exec --help`); Grok
# accepts low, medium, high, xhigh (`grok --effort`); OpenCode's variants of current
# models run from low to max (`opencode models --verbose`).
EFFORT_MAP = {
    "claude-code": {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
    "codex": {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
    "cursor": {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"},
    "droid": {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
    "opencode": {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
    "grok": {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"},
    "antigravity": {"low": "flash", "medium": "flash", "high": "pro", "xhigh": "pro", "max": "pro"},
}


def package_root():
    """The root of the plugin package (the repository)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


class NotAPluginCopy(UsageError):
    reason = "not-a-plugin-copy"


def plugin_root():
    """``package_root()`` when it holds the plugin's files: the wheel has no ``agents/``, ``commands/`` nor
    ``skills/`` (T128)."""
    root = package_root()
    if not os.path.isdir(os.path.join(root, "agents")):
        raise NotAPluginCopy(_("this installation of probandia holds no plugin files (agents, skills, commands): "
                               "install from the repository with python <repository>/run_probandia.py install …, "
                               "or from an editable install (uv tool install --editable <repository>)"))
    return root


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split_front_matter(text):
    """(front matter as a dict, body) of a Markdown file with a YAML header."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.index("\n---\n", 4)
    return yamlio.loads(text[4:end]) or {}, text[end + 5:].lstrip("\n")


def front_matter(fields):
    """A YAML header; strings are quoted when they need it."""
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            plain = value and all(c not in value for c in ':#{}[],&*!|>\'"%@`') and value.strip() == value
            lines.append(f"{key}: {value if plain else json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (list, dict)):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def agents(root=None):
    """{role: (front matter, body)} from agents/*.md, in name order. Their headers hold no model nor effort,
    which Antigravity would refuse (version-1.0.0 T267): each role's come from ``ROLE_DEFAULTS``."""
    from probandia.config.registry import ROLE_DEFAULTS

    folder = os.path.join(root or package_root(), "agents")
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".md"):
            fm, body = split_front_matter(read(os.path.join(folder, name)))
            model, effort = ROLE_DEFAULTS.get(name[:-3], (None, None))
            fm = {**fm, "model": fm.get("model") or model, "effort": fm.get("effort") or effort}
            out[name[:-3]] = ({k: v for k, v in fm.items() if v is not None}, body)
    return out


def commands(root=None):
    """{name: (front matter, body)} from commands/*.md, in name order."""
    folder = os.path.join(root or package_root(), "commands")
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".md"):
            out[name[:-3]] = split_front_matter(read(os.path.join(folder, name)))
    return out


def with_root(text, variable):
    """Replaces Claude's plugin root variable with another harness's."""
    return text.replace(CLAUDE_ROOT, variable)


def with_harness(text, harness):
    """Commands and skills tell the engine which harness calls it."""
    return text.replace("--harness claude-code", f"--harness {harness}")


def tools_list(value):
    """The tools of an agent's header: a YAML list (agents/, which Antigravity reads) or ``A, B`` (Claude Code)."""
    if not value:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(t).strip() for t in items if str(t).strip()]


# Codex custom agents


def codex_agent(role, fm, body):
    """``.codex/agents/<role>.toml``: name, description, effort, instructions."""
    import tomlkit

    doc = tomlkit.document()
    doc["name"] = f"probandia_{role}"
    doc["description"] = fm.get("description", "")
    doc["model_reasoning_effort"] = EFFORT_MAP["codex"][fm.get("effort", "medium")]
    if role == "contradictor":
        doc["sandbox_mode"] = "read-only"
    instructions = with_harness(with_root(body, "${PLUGIN_ROOT}"), "codex")
    doc["developer_instructions"] = tomlkit.string(instructions, multiline=True)
    return tomlkit.dumps(doc)
