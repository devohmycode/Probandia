---
description: "List, add, edit, answer or set aside the questions of a research"
argument-hint: "list|add|edit|answer|unresolved|reopen [<text or Q-id>] [--research <id>]"
allowed-tools: "Bash(python:*)"
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" question $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise the answer in a few lines. Answer in the user's language.
