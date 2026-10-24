"""Team mode: waves of field agents, their search budget, and the message relay.

- A wave starts at most ``max_agents`` agents (the research's ``run``, else
  ``team.max_agents``); waves are recorded in ``work/team/waves.jsonl``.
- The pass's native search budget is split between the agents of a wave.
- A message is one JSON object ``{type, from, to, research, pass, body, refs}``,
  ``type`` being ``task``, ``result``, ``finding``, ``question`` or ``stop``. Where
  the harness has messaging (``SendMessage`` in Claude Code), agents use it; the
  relay keeps a copy, and is the only way elsewhere: ``work/team/<agent>.inbox.jsonl``,
  read between waves.
"""
import json
import os

from probandia.errors import UsageError
from probandia.i18n import _
from probandia.lifecycle import current_pass
from probandia.util.fs import iso, utc_now

TYPES = ("task", "result", "finding", "question", "stop")


def folder(research):
    return os.path.join(research.work, "team")


def _read_jsonl(path):
    out = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
    return out


def _append(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def caps(research, config):
    run = (research.meta() or {}).get("run") or {}
    return (run.get("max_agents") or config.get("team.max_agents") or 1,
            run.get("max_passes") or config.get("team.max_passes"))


def waves(research, pass_no=None):
    rows = _read_jsonl(os.path.join(folder(research), "waves.jsonl"))
    return [w for w in rows if pass_no is None or w["pass"] == pass_no]


def start_wave(research, config, agents, native_left, now=None):
    """Records a wave of ``agents`` agents; refuses more than the cap. Returns the
    wave, with each agent's share of the native searches."""
    from probandia.budget import split

    max_agents, _max_passes = caps(research, config)
    if agents > max_agents:
        raise TeamCap(_("a wave may start at most {n} agents").format(n=max_agents), max_agents)
    p = current_pass(research)
    wave = {"pass": p, "wave": len(waves(research, p)) + 1, "agents": agents, "ts": iso(now or utc_now()),
            "native": split(native_left, agents)}
    _append(os.path.join(folder(research), "waves.jsonl"), wave)
    return wave


class TeamCap(UsageError):
    reason = "team-agents"

    def __init__(self, message, cap):
        super().__init__(message)
        self.cap = cap


def _agent(name):
    name = str(name or "").strip()
    if not name or any(c in name for c in "/\\:") or name.startswith("."):
        raise UsageError(_("invalid agent name {name}").format(name=repr(name)))
    return name


def send(research, sender, to, type_, body, refs=(), now=None, via=None):
    """Appends a message to the inbox of ``to``; ``via`` names the harness tool that
    carried it (``SendMessage``), when the relay only keeps a copy."""
    if type_ not in TYPES:
        raise UsageError(_("unknown message type {type}; types: {types}").format(type=type_, types=", ".join(TYPES)))
    msg = {"type": type_, "from": _agent(sender), "to": _agent(to), "research": research.id,
           "pass": current_pass(research), "body": body, "refs": list(refs), "ts": iso(now or utc_now())}
    if via:
        msg["via"] = via
    _append(os.path.join(folder(research), f"{msg['to']}.inbox.jsonl"), msg)
    return msg


def inbox(research, agent, keep=False):
    """The unread messages of an agent; read ones are not shown again unless ``keep``."""
    agent = _agent(agent)
    path = os.path.join(folder(research), f"{agent}.inbox.jsonl")
    seen_path = os.path.join(folder(research), f"{agent}.read")
    rows = _read_jsonl(path)
    try:
        with open(seen_path, encoding="utf-8") as fh:
            seen = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        seen = 0
    new = rows[seen:]
    if not keep:
        os.makedirs(os.path.dirname(seen_path), exist_ok=True)
        with open(seen_path, "w", encoding="utf-8") as fh:
            fh.write(str(len(rows)))
    return new
