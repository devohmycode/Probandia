# Briefing field agents

Every agent you start (subagent or team mode) gets its brief in this order:
the harness caches the longest prefix shared by prompts, so anything that
varies before the common part breaks the cache for all that follows.

```text
Probandia research <research>, pass <n>. Language of the prose: <LANG>.
Question: <the question of the pass, as `plan` gave it>.
Known: <the lines of the digest that every agent needs>.
Run the engine with your role as `--agent`. Return at most 45 lines (55 for
the investigator, 10 for the searcher), then the path of your proposal.
[team] You work in a team: read `${CLAUDE_PLUGIN_ROOT}/skills/team/SKILL.md` and follow it.
[team] Team: <every agent's name, in the same order for all>.
---
Name: <name>. Task: <one archive or one query family>. Window: <from>-<to>.
Native searches: <share>. Proposal: work/proposals/<name>.yaml.
[browser] Guide: <its guide= lines from archive find>.
```

- **Common part** (above `---`): built once per wave, then copied unchanged
  into each brief, the same from one wave to the next when it holds.
- **Task part** (below `---`): last, the only part that differs.
- Never at the head, nor in the common part: a time or today's date, a wave or
  agent number, a counter, a random id, a figure that changes during the wave
  (quota left, searches done).

A `reader`'s brief: `reader.md`.
