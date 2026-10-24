---
name: probandia-library
description: "Find, save, test, trust, run or install the project's learned scripts"
argument-hint: "find|save|test|trust|list|show|run|promote|demote|draft|install|uninstall|export|import [<name>]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" library $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise the answer in a few lines. Answer in the user's language.
