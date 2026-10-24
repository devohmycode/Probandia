---
description: "Check a research against the proof rules"
argument-hint: "[<research>] [--light] [--rule V-<n>] [--standard]"
allowed-tools: "Bash(python:*)"
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" verify $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Report each failed rule with the fact it concerns, and what would fix it. Answer in the user's language.
