---
description: "Import a GEDCOM file into the staging area of a family"
argument-hint: "<file> [--family <slug>]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" import-gedcom $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise what was imported and what needs review. Answer in the user's language.
