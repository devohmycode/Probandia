# Team mode (the orchestrator)

You are the orchestrator: call the engine with `--agent orchestrator`. Field agents
work in waves.

1. **Open the wave**: `team wave <research> --agents <n>`. The engine refuses
   more than the team's `MAX_AGENTS` (`STATUS=STOP`, `REASON=team-agents`):
   start fewer. The `native=` line gives each agent's share of the native
   searches; tell each agent its share.
2. **Brief each agent** with a closed task, per
   `${CLAUDE_PLUGIN_ROOT}/skills/research/brief.md`, its `[team]` lines
   included; in Claude Code its name is the `name` of the Agent call
   (`r1-archives`). Split the tasks so that one agent's findings feed
   another's (the archive agent's place and date help the online-bases agent).
3. **Messages** follow `${CLAUDE_PLUGIN_ROOT}/skills/team/SKILL.md`: one JSON
   object `{type, from, to, research, pass, body, refs}` as the text. Every
   field agent sends at least one `finding` to a teammate during its task.
   With a messaging tool, the engine's hook keeps a copy in the relay,
   `work/team/<name>.inbox.jsonl`; elsewhere agents use `team send` and
   `team inbox <research> --to <agent>`, and you relay between waves.
4. **Returns** (the brief's lines and proposal path): read each
   `propose` summary, not the YAML nor the notes; apply what holds. Check the
   relay (`ls work/team/`): when no message passed in a wave, say so in your
   summary. A message is a lead: what it claims enters the indexes only
   through a proposal.
   A `question` whose body is `login_required <archive> <url>`: ask the user
   (the `browser` skill), then hand the page back to its agent.
5. The **contradictor** only before promoting a conclusion: it reviews the
   proof argument a question needs (`proofs.md`), `--by contradictor`.
6. **Next wave** only after reading the returns, and only for a gap, a
   contradiction or a lead one of them brought, never "to see"; an exhausted
   source is not sent again. At most one agent per wave holds the browser
   (`lock take browser`). A team stops after its
   `max_passes` passes: `resume` answers `STATUS=STOP`, `REASON=team-passes`.

The guard refuses a field agent that writes the indexes, the events, the
report or `research.yaml`, or that runs `apply`, `event append`, `render`,
`export` or `git commit`: a refusal names its rule (`G-1`, `G-2`…).
