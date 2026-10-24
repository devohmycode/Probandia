# Security policy

## Supported versions

Security fixes go to the latest minor version of 1.x. Versions before 1.0.0 get
none: upgrade with `uv tool upgrade probandia`, or update the plugin in your
harness.

## Reporting a vulnerability

Report it privately, through GitHub's
[private vulnerability reporting](https://github.com/devohmycode/probandia/security/advisories/new)
(the repository's *Security* tab, *Report a vulnerability*). Do not open a public
issue for it.

Say what is affected (the command, hook, skill or file), the version
(`probandia --version`) and the harness, and how to reproduce it. Never send a
real API key, nor the records or names of a real family: a made-up project
shows the problem as well. The answer comes in the advisory; a fix is published
with a new version and named in
[CHANGELOG.md](https://github.com/devohmycode/probandia/blob/master/CHANGELOG.md).

## Where your keys are

Never in a setting. Probandia reads a key from its environment variable, then
from the project's `.env` (next to `probandia.toml`), then from yours (next to
your `config.toml`). `probandia keys where` names the files it reads, and
`keys set` asks the key unseen at the keyboard and writes the file readable by
its owner only (on Windows, the file keeps the access rights of its folder). A
key is never printed: `doctor` and `config show` name it, `keys list` adds
8 hexadecimal digits of its SHA-256, and the memory refuses one.

## What Probandia guards

- **Nothing is paid.** Searches and reads run on free tiers; a provider that
  needs a card is not called unless you allow it
  (`providers.allow_card_required`).
- **The guard** (hooks, rules G-n) runs before each tool call of the plugin's
  agents: field agents write proposals in `work/`, never a family's index
  (G-1); the agent that runs the pass applies them through the engine.
- **Web content is data.** What a page says never becomes an instruction: an
  injected "write into persons.yaml" ends, at most, as a proposal to review.
- **Learned scripts** run in a child process, their network reduced to the
  hosts they declare and their environment to the variables they declare;
  another process, a raw socket, native code or `exec` is refused before the
  script runs.
- **Unattended runs** (`PROBANDIA_HEADLESS=1`) assume the defaults, are marked
  as such in the research's log, call nothing paid and run no draft script.
- **Presumed-living persons** are masked in exports by default, never sent to a
  provider that reuses its content, and never kept in the memory.

## Out of scope

- The harness's own permissions and sandbox (Claude Code, Codex, Cursor…): set
  them there.
- A learned script you trusted (`library trust`): it runs as you, in the
  project's folder, with no sandbox of the file system. Read it first.
- What a provider does with the queries you send it: see its terms, listed in
  `catalogues/providers.toml`.
