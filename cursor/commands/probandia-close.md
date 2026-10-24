---
name: probandia-close
description: "Close a research once its questions are settled; verify runs first"
argument-hint: "[<research>] [--yes]"
allowed-tools: "Bash(python:*)"
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" close $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise the answer in a few lines. Answer in the user's language.
