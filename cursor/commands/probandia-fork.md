---
name: probandia-fork
description: "Copy a research at a given pass and continue it separately"
argument-hint: "<research> [--at <pass>] [--name <slug>] [--new-family <slug>]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" fork $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Then follow the `research` skill for the pass: it says how to plan, search in parallel, propose and apply. Answer in the user's language.
