---
name: probandia-template
description: "List, check, import, export or choose the report templates, or open the template designer"
argument-hint: "list|show|check|import|export|use|designer [<id or file>]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" template $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise the answer in a few lines. Answer in the user's language.
