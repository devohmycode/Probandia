# Learned scripts

Before writing a script to reach a source or read a format, run
`library find "<need>"`: reuse a `tested` or `trusted` script as it is
(`library run <id> --args '<json>'`), repair a failing one rather than writing
another. A new script has an entry point `run(args, http)` (use `http`, the
engine's client, for every request) and is saved with its witness:
`library save <file> --id <slug> --purpose "…" --hosts <hosts> --env <vars>
--witness-args '<json>'`, then `library test <id>`. A `draft` runs inside a
pass only after the user agreed (`QUESTION=library_run_draft`, then
`--approve`). The queries that found facts come back first in the next plan.

Never pose as a browser: no browser User-Agent, `fake_useragent` or
`cloudscraper` (the guard refuses them toward an archive). A cookie a plain
redirect sets may be replayed under the engine's identity; a challenge or a
refusal is read in the browser, never forced.
