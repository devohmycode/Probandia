---
name: probandia-config
description: "Show, explain or change the settings, with where each value comes from"
argument-hint: "show|explain|set|unset|init|validate|path|wizard|edit|grade|diff|roles|theme [<key>] [<value>] [--origin] [--user|--local]"
allowed-tools: "Bash(python:*)"
disable-model-invocation: true
---

Run the Probandia engine with the user's arguments:

```bash
python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" config $ARGUMENTS
```

If the path still shows `${CLAUDE_PLUGIN_ROOT}`, or for anything about the arguments and the answer (`STATUS=OK`, `WARN`, `ASK`, `STOP`, `FAIL`), follow the `engine` skill.

Follow the `config` skill to explain the result. Answer in the user's language.
