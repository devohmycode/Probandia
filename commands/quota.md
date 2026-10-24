---
description: "Show, sync, add or estimate the free-tier usage of each provider"
argument-hint: "[show|sync|add|estimate] [<provider> <units> --note \"<text>\"]"
allowed-tools: "Bash(python:*)"
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" quota $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Summarise the providers with the least free quota left first. Answer in the user's language.
