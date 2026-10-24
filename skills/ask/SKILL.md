---
name: ask
description: What to do when a Probandia command answers `STATUS=ASK`.
---

# Asking the user

When an engine command answers `STATUS=ASK`, it needs the user. It never
guesses: you ask, then you run the **same command again** with the answer.

Never answer a question yourself, not even with its default, and not even
when the session runs without permission prompts: the question is the
user's. Only a headless run takes the defaults, and the engine does it.

## What the answer holds

```text
STATUS=ASK
QUESTION=team_agents
PROMPT=Agents
CHOICES=1|3|5|10
ALLOW_OTHER=true
DEFAULT=3
TOOL=AskUserQuestion
QUESTIONS=team_agents|team_effort|team_passes
PROMPT_TEAM_EFFORT=Which effort?
CHOICES_TEAM_EFFORT=low|medium|high|xhigh|max
DEFAULT_TEAM_EFFORT=medium
OPTION_TEAM_EFFORT=--effort
…
```

- `QUESTIONS=` lists the questions to ask **together, in one call**. For each
  one, `PROMPT_<ID>`, `CHOICES_<ID>`, `DEFAULT_<ID>`, `ALLOW_OTHER_<ID>` and
  `OPTION_<ID>` (the argument that carries the answer) are given.
- When `QUESTIONS=` is missing, there is one question: `PROMPT`, `CHOICES`,
  `DEFAULT`, `ALLOW_OTHER`, and `OPTION` (or the `- answer with …` line)
  names the option.
- Translate the prompts and the choices' labels into the user's language;
  keep the values themselves (`session`, `team`, `high`…) for the command.
- Put the default first and mark it as recommended.
- When `ALLOW_OTHER` is true, the user may type another value (a number of
  agents, a model name…).
- `SUGGESTED_MODEL=sonnet`: in one line, offer to switch this session to it
  with `/model`; never switch it yourself.

## Which tool

`TOOL=` names the harness's question tool (`AskUserQuestion` takes up to four
questions in one call); `none` means numbered choices in your answer.

### Numbered choices (no question tool)

Write the questions as numbered lists, then **stop and wait** for the reply:

```text
Who runs this research?
  1. session — this session's agent (recommended)
  2. subagent — one subagent, with its own model and effort
  3. team — a team of subagents that talk to each other
Answer with the number, or type another value.
```

With several questions, number each block (1a, 1b…, 2a…) and ask them in the
same message.

## Then

Run the command again with every answer as its option, for example:

```text
new "<question>" --mode team --agents 3 --effort high --passes 2
resume <research> --interrupted close
new "<question>" --family marchand
```

## Without a user

In a headless run (`PROBANDIA_HEADLESS=1`, or a child run with
`PROBANDIA_WORKER=1`), the engine asks nothing: it takes the defaults, records
`assumed: true` in `pass.started`, and answers `ASSUMED=true`. Say so in your
summary.

## The questions

| Id | Asked when |
|---|---|
| `run_mode` | `new` or `resume`, when neither `--mode`, the research nor `run.mode` says who runs it |
| `run_model`, `run_effort` | a subagent: asked together; only the models and efforts the harness accepts |
| `team_agents`, `team_effort`, `team_passes` | a team: asked together |
| `family` | `new`, when the question names no known family |
| `interrupted_pass` | `resume`, when the last pass never ended |
| `workshop` | `new`, in a workshop never imported |
| `translate_labels` | `render`, a language without labels; `translate`: the `report` skill |
| `use_browser`, `place_ambiguous`, `library_run_draft` | reading, places, learned scripts |
| `login_required` | `read` meets a sign-in screen: the `browser` skill; `connected`, `skip` or `stop`, given as `--login` |
| `library_install`, `memory_add`, `memory_remove`, `memory_import`, `memory_full` | installing a learned element, writing `AGENTS.md`: show the `FILE=` or `show=` lines first |
