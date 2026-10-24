---
description: "Replay the archives' witnesses and list the stale catalogue entries"
argument-hint: "[--keys] [--out <folder>]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" watch $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Report each failed witness with its error, what was not run and why, and the stale entries. Answer in the user's language.
