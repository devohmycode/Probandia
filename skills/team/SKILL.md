---
name: team
description: Messages between Probandia teammates; only when your brief says team.
---

# Working in a team

Your brief gives the research id, the pass, the whole team (`Team:`, your
teammates are the other names) and, at its end, your own name.

- **Send at least one message.** As soon as you find something a teammate's
  task needs (a name, a place, a date, a record reference, a dead end that
  spares them a search), send it to that teammate as a `finding`. Before you
  return, make sure you sent at least one.
- **Format**: the message's text is one JSON object:
  `{"type": "finding", "from": "<your name>", "to": "<name>", "research": "<id>", "pass": <n>, "body": "…", "refs": ["<url or source id>"]}`.
  `type` is `task`, `result`, `finding`, `question` or `stop`.
- **How**: with a messaging tool (`SendMessage` in Claude Code, `send_message`
  in Codex, Antigravity), put the JSON in `message` as one line of text, not
  an object; the engine keeps a copy. If it refuses, or none, run
  `team send <research> --from <your name> --to <name> --type finding --body "…" --refs …`.
- **Read yours**: a messaging tool delivers them; otherwise run
  `team inbox <research> --to <your name>` when you start and before you write
  your proposal. Answer a `question`; stop on a `stop`.
- A message is a lead, never a fact: check it before it enters your proposal.
- A sign-in screen (`login_required`): never ask the user; send the
  orchestrator a `question`, body `login_required <archive> <url>`, go on.
