---
description: "Run the next pass of a research, from its state digest"
argument-hint: "[<research>] [--instructions \"<text>\"]"
allowed-tools: "Bash(python:*)"
---

If the arguments start with `seul :` (or `solo:`), drop that prefix and add `--mode session`; with `agents :`, drop it and add `--mode team`.

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" resume $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill. On `STATUS=ASK`, ask the user with the `ask` skill before anything else, and never choose for them.

Then follow the `research` skill for the pass: it says how to plan, search in parallel, propose and apply. Answer in the user's language.
