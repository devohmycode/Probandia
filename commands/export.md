---
description: "Export a family to GEDCOM 7, GEDCOM 5.5.1 or Gramps Web"
argument-hint: "gedcom7|gedcom551|gramps [--family <slug>] [--living mask|exclude] [--dry-run]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" export $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Give the path of the exported file and the number of persons masked or left out. Answer in the user's language.
