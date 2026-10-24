# Working in a workshop

Read this when the engine's answer names this file: the project is linked to a workshop
(`workshop.yaml`), whose `commun/personnes.yaml` is the source of truth. Its rule 4: every
discovery or corrected date reaches that file in the same pass.

- Never write `commun/personnes.yaml` yourself, by an edit tool or the shell: the guard refuses
  it (G-18). Apply the facts in Probandia, then `workshop status`; `workshop push` writes them,
  as added lines, under the workshop's rules.
- `ASK` with `QUESTION=workshop_push` (once a pass, after an apply): ask the user. `push`: run
  `workshop push <research>`. `later`: go on; `pass end` refuses to close until they are pushed,
  or until `--defer-workshop "<reason>"` says why not.
- A fact a rule blocks (`BLOCKED=`, its line names the rule): fix it in Probandia (a new
  proposal), or defer it with its reason. Never bend the workshop's rule.
- `DIVERGENT=`: the workshop wins (WS-D1). Show both values with `workshop diff` and let the user
  choose: keep the workshop's, or `workshop push --accept <fact>`. A precision (a day in its year,
  a stronger status) is still the user's choice.
- `CHANGED_SINCE_SYNC=true`: the workshop was edited by hand. `workshop pull <research>`, then
  `apply` the proposal it names; never a second `import`.
- After a push, `CHECK=failed`: tell the user and give the command to run again; the file stays
  as written. At `pass end`, recall `python outils/build.py` once; never run it.
