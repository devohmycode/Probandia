---
name: probandia-matrix
description: "Show the source types each question expects, consulted or still to do, or say why one does not apply"
argument-hint: "[<research>] [--question Q1] | justify <Q-id> <type> --reason \"<why>\" [--research <id>]"
allowed-tools: "Bash(python:*)"
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" matrix $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise the answer in a few lines. Answer in the user's language.
