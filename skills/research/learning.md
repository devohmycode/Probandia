# What the pass taught: the library and the memory

`pass end` lists what the library could keep (`LEARN_CANDIDATES=`, one
`learn=<kind> <detail>` line each): `script <path>`, a script you wrote in
`work/` and never saved; `helper <archive>.<op> xN`, the same archive
operation again and again; `skill <host> read N times in the browser`, a way
of reading a site; `promote <recipe>`, a query that worked several times.

**Ask the user once**, in one question, which to keep, with the memory's
entries below; never keep one they did not choose. Then, for each:

1. A script: `library save <file> --id <slug> --purpose "…" --witness-args '{…}'`.
2. A skill or an agent: write it (`SKILL.md`, or an agent file in Claude Code's
   format) named `probandia-<name>`, then
   `library draft <file> --kind skill|agent --id probandia-<name> --trigger "…"`.
   The engine refuses one that would pay, bypass the guard, use an anti-bot
   option, conclude without proof or write the indexes itself.
3. A recipe: `library promote <id> --to user`.

**Install** only after the user saw the whole text:
`library install <id> --scope project|user` answers `QUESTION=library_install`
with `FILE=`; show that file in full, ask, and run it again with
`--approve yes` only if they said yes. Never write into `.claude/skills`,
`.agents/skills` or an agents folder yourself: the guard refuses it (`G-8`).
`library uninstall <id>` removes exactly what was installed.

## The memory: AGENTS.md

`MEMORY_CANDIDATES=` (`memory=<kind> <detail>` lines) and the pass's own
decisions go in the same question. **In it**: working decisions, one dated line
each: conventions, the report template, providers kept, archives that need a
sign-in, the user's preferences, a source's pitfalls. **Never**: a genealogical
fact (the indexes hold them), a presumed-living person, a key or secret; the
engine refuses those.

`memory add "<one line>" --kind <kind> [--supersedes M3]` answers
`QUESTION=memory_add`: show its `show=` lines, ask, then `--approve yes`. Full
(`memory_full`): merge with `--supersedes`, or `--overflow archive`.
`--scope user` reaches every project: ask for it on its own. Never edit the
section between the `probandia` markers yourself (`G-10`).
