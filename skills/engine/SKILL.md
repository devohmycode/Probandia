---
name: engine
description: How to run a Probandia engine command and read its answer.
---

# Calling the Probandia engine

## The command

```bash
python .probandia/pb.py <command> [arguments] --agent <role>
```

- **From the project root.** `.probandia/pb.py` is the short launcher the engine writes in each project. When it is missing (a new project), and for a session's first command, run `python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py"` instead — `run_probandia.py` sits at the root of the Probandia plugin, two folders above this `SKILL.md` file — and the launcher is written on the way. Use `python3` where `python` is missing.
- **`--harness`**: leave it out; the engine knows the harness it runs in. Give it (`claude-code`, `codex`, `cursor`, `droid`, `grok`, `antigravity`, `opencode`) only when a command says so.
- **`--agent`**: leave it out for the main agent (`session`); otherwise your role (`orchestrator`, `researcher`, `investigator`, `harvester`, `reader`, `contradictor`, `searcher`).
- **The plugin options** (report mode…) need not be passed: the hooks keep them for the session. The language of the user's message is not one of them: give `--prompt-lang <tag>` to `new`, which fixes the research's language.
- **`<research>`**: leave it out inside a pass, the engine takes the pass's research; give it after `pass end`, when your brief names it, or on `REASON=research-not-named` (the `open=` lines).
- Quote every argument that holds spaces, such as a question.

## Reading the answer

The answer starts with `STATUS=`, then `KEY=value` lines, then short lines starting with `- `, and sometimes `DETAILS=<path>`: read that file only when you need the full text.

| Status | What to do |
|---|---|
| `OK` | Done. |
| `WARN` | Done, with something to tell the user: the `- ` lines say what. |
| `ASK` | The engine needs the user (`login_required`: the `browser` skill). Ask `PROMPT` with the choices `CHOICES` (default `DEFAULT`; free text allowed when `ALLOW_OTHER=true`) using your multiple-choice question tool, or as numbered choices in your answer if you have none. Then run the same command again with the answer. Never answer it yourself, not even with the default, and not even when you run without permission prompts: only a headless run takes the defaults, and the engine does that itself. |
| `STOP` | A free quota, a budget or a cap stopped the command. Say which (`REASON=`) and offer the `ALTERNATIVE=` if there is one. Never work around it with a paid service. |
| `FAIL` | Report `REASON=` and the lines in plain words. |

Exit codes: 0 done, 1 refused, 2 usage or settings error, 3 ask, 4 stop, 5 lock held by another agent, 6 not inside a Probandia project, 7 network error, 10 internal error (a `LOG=` path holds the details).

## Rules

- Answer the user in their language.
- Never print, copy or write an API key. Keys live in environment variables only.
