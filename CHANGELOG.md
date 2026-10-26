# Changelog

Every notable change of Probandia, newest first. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); before 1.0.0 the third number
runs on two digits (0.9.3, then 0.9.40, 0.9.41…).

No version before 1.0.0 was tagged or published: each section below sums up the
merges of `git log --merges` between two version commits. Each version has a
**Breaking changes** heading when it changed something a reader of the engine
relies on: a key of the `KEY=value` contract or of `--json`, a schema of
`schemas/`, a command, an option or a setting.
What 1.x keeps stable, and how such a change is deprecated first, is written
in [STABILITY.md](https://github.com/devohmycode/probandia/blob/master/STABILITY.md).

## [1.0.0] - 2026-10-26

### Breaking changes

- The public address is `https://probandia.replit.app`, in place of
  `https://probandia.dev`, which was never registered: the URIs of the five
  GEDCOM 7 extension tags, the `$id` of every schema, the `$schema` of
  `report.json` and the contact of the User-Agent. The schemas are frozen
  again with these ids.
- Exa, Parallel, Tavily and Linkup, whose terms let them reuse what is sent to
  them, are off until `providers.allow_content_reuse` is set.
- `pass end` checks rule V-1 for the pass it closes: a pass with no `plan`
  stays open (`REASON=verify`, `V-1=FAIL … no plan.made`).
- Field agents load no search or reading MCP server any more: every search and
  every read goes through the engine (`search`, `read`, and `read --map`,
  `--crawl`, `--extract`); guard rule G-15 sends a provider's MCP tool called
  during a pass back to the engine.
- The MCP server no longer lists or reads a family's raw index files as
  resources: only the settings and the research digests.
- Eight settings that nothing read are removed from the registry
  (`evidence.axes`, `exports.gedcom`, `verify.on_pass_end`,
  `report.anchor_policy`, `log.level`, `language.detector`,
  `exports.experimental`, `gramps.tree`).
- `tree.format` takes the value `all`, its new default (the four files, as
  before when nothing is set), and `tree` now reads it.
- The `tui` extra installs Textual 8 (`textual>=8.2,<9`) without `argparse-tui`.
- The report counts the elements of the Genealogical Proof Standard the data
  establish and no longer claims conformity.
- Failures that raised an internal error (code 10) now answer a network error
  (`REASON=network`, code 7) for a truncated answer or an invalid URL,
  `REASON=tesseract-failed` for Tesseract, `REASON=robots-unreachable` for a
  robots.txt out of reach, and `FAILURE=unexpected-answer` in the search log
  for an archive connector.

### Added

- A continuous integration replayed on the development machine, under Windows
  and Ubuntu (`tools/ci_local.py`), a test suite shared out between processes,
  the lint, pinned actions and a merge rule.
- The benchmark measures what the 1.0 needs: tokens per harness and model,
  `bench/run.py --json`, duplicates and `--compare`, hook cost per pass.
- Searching and reading through the engine only: costs per operation from the
  providers' pages, ScrapeGraph as an extraction provider, map, crawl and
  extract, Tavily as a reader; balances read without asking, `monthly_cap`
  applied, `search --engine auto` moving to the next free provider, an alert
  under 20 % of a quota, `usage --forecast`; a native search logged once and
  refused once when run again; cache statistics and `cache clear`.
- The proof traps found in an analysis of genealogical research assistants,
  closed in the engine: V-20 on a refuted conclusion, the three axes of a
  concluding fact, a fact checked against the date of its act, a blind second
  reading of each act that concludes, an act on several views, a qualified
  filiation, no one their own ancestor, a fact a person checked.
- Readers that place the act on a small view and read the act alone; the views
  of a register on one sheet, in one call.
- The terminal interface on six screens (Home, Quotas, Researches, Family,
  Proposals, Config), each with its key, a console that runs a form's command
  inside it, a remembered theme, reads off the interface thread with a cache.
- Workshop synchronisation: `workshop status`, `diff`, `push` and `pull`,
  `personnes.yaml` read line by line and written without rewriting anything.
- Every user command publishes `data` in `--json`; `report open`, `show` and
  `render`; `board --json`; the French catalogue complete; the help naming every
  command and action; accessible `report.html` and `tree.html`.
- Two public-domain records of the example family (Victor Hugo), with their
  manifest of rights.
- A README that the tests keep true to the engine, a French user guide and an
  open archives guide under `guides/`.
- `new --prompt-lang`: the agent gives the language of the user's message, and
  the research keeps it (`LANG_SOURCE=prompt`).
- In journal mode an earlier pass renders as it was written, its facts, notes
  and tree included; `report/passes.json` keeps a fingerprint of each pass's
  text, and `render` answers `REASON=pass-text-changed` when a closed one
  changes.
- `pass end` names the readings a reader marked doubtful (`DOUBTFUL_NAMES`), to
  be given with their reserve; a source keeps its image, and a transcription is
  not replaced in silence.
- Two public benchmark cases on records of Victor Hugo (CC BY 4.0), and the
  release candidate measured at the bench (`bench/release-1.0.0.md`) and for
  speed (`bench/perf-1.0.0.md`).
- The seven agents in Antigravity, and Claude Code reading its own copies with
  each role's model; Cursor installed by a clone, its commands as
  `/probandia-<name>`.
- The `LICENSE` (Apache-2.0), `THIRD-PARTY-NOTICES`, the licences of the
  embedded fonts, this changelog, `STABILITY.md`, the package's classifiers and
  addresses, and a release workflow (`.github/workflows/release.yml`).

### Changed

- The engine loads only the command it runs: `--version` and `hook guard`
  start in about a third of the time; `verify` reads each index once.
- A fact cited after the agent's own sentence (`[[f:…]]`) renders as its
  citation note only, not its text a second time.
- `search --negative` looks at the free quota before every call, and a wave
  cut short proves no absence.
- The GEDCOM export keeps every view of a source, writes `FILE` as a URI and
  leaves out, and says, a view no file holds.
- YAML is read by the compiled loader when it is there (`PROBANDIA_YAML_PURE=1`
  keeps the pure one): a workshop push under 5 seconds.
- The provider catalogue read again on 23 October 2026: rates, addresses and
  free tiers.
- The sdist takes only the root entries git tracks; the content of both
  packages is a frozen list (`tools/package-contents.txt`).

### Fixed

- WikiTree: every request carries an `appId`; without one, its API answered
  429 "Limit exceeded." from the first request, and the witness failed.
- A key in a URL is never written; `.env` is born with mode 0600; a learned
  script escaping its confinement is refused; an injected page writes nothing;
  the guard normalises paths and knows PowerShell writes and inline
  interpreters; `tree.html` escapes what could close its script block.
- The MCP server reads its requests in UTF-8 whatever the locale.
- `CAPABILITIES` is true to the manifests; Grok Build's tool calls are read by
  the guard and the log; the Codex contradictor is read-only.

## [0.9.41] - 2026-10-12

### Breaking changes

- Each agent role takes the model and the effort chosen for it
  (`roles.<role>.model`, `roles.<role>.effort`); `run.*` and `search.*` remain
  as fallbacks.

### Added

- A pass with an act transcribed and never proposed stays open, and an index
  never decides a reading.
- Two safety nets: a small view never transcribed, and a rejected proposal
  never left behind.
- `cite --type` takes the names agents guess, and a place's guide is stored at
  once by whoever applies.
- `propose` fills the head of a proposal it knows.

### Changed

- Readers see a whole view on a sheet only; a reading crop is the act, not the
  page; no more search once the question is proven.
- Shorter reads for the main agent; an invented example family in everything
  the agent reads.

### Fixed

- `pass end` no longer stops on a cache file that is no response.

## [0.9.40] - 2026-10-11

### Added

- A register's views go to a reader; the guard refuses the main agent's first
  image of a pass.
- `propose` gives a search with no id its own.

### Changed

- Guard rule G-13 lets the main agent open a view a transcription names, to
  check a doubt.

## [0.9.3] - 2026-10-11

### Fixed

- `propose` reads `support: record` as an image, and says why a transcription
  has no numbered line.

### Changed

- Shorter agent descriptions, no brief rule repeated in the agents.

## [0.9.2] - 2026-10-11

### Breaking changes

- The Claude Code plugin no longer declares the MCP server: its skills call
  the engine through the shell. Cursor keeps the server in `cursor/mcp.json`.

### Added

- `known` and `plan` run by `new`, `propose --apply`, excerpts by reference,
  read filters, a lighter plan.
- Departmental archive connectors, image tools and a reader for records.
- A plan from the event a question seeks, its window and its places; calls
  filtered by the catalogue's coverage; the surname's particle in the variants.
- The workshop's skin (`habillage`) as a built-in report template.
- A record fact asks for its search; `pass end` counts, tidies, renders and
  checks, and is held only by what the pass brought.

### Changed

- The research skill is read at every pass in one file, 15 % smaller; shorter
  outputs; the digest given once.
- The Stop message speaks only when there is something to say; a hook outside
  any project answers without loading the engine; the log hook runs only after
  the tools it records.
- Commands inside a pass need not name the research; Probandia never poses as
  a browser toward an archive.

## [0.9.1] - 2026-10-09

The first version number since 0.9.0 (1 October 2026), the engine's first
complete layout.

### Added

- The readable command: `probandia -u`, the user's quota counter, readable
  output for every command, questions, confirmations, the welcome screen and
  Tab completion; keys, providers, the archive list and coverage, `init` and
  the configuration wizard; researches, families, persons, indexes and
  proposals read from the terminal.
- The Genealogical Proof Standard: structured questions and `close`, place
  jurisdictions and repositories, the source-types catalogue and the
  exhaustiveness matrix, analyses of disputed evidence and `correlate`, proof
  arguments reviewed by the contradictor, typed sources and `cite`, chronology
  findings and SVG timelines, and the conformity of each question in the report
  (rules V-14 to V-18, G-11).
- Trust: each fact cites the exact passage it reads, checked word for word
  (V-19); the confidence of each conclusion in `verify --standard`, the report
  and the GEDCOM export; a source watch with one witness per archive; the format
  of a public benchmark case.
- Report templates, `template`, `render --all` and an offline template designer;
  the project's memory in `AGENTS.md`; the library's user scope; a manual
  sign-in in the browser.
- The optional terminal interface (`tui`), with the DDB connector and open
  archive browser routes.
- The link between a project and its workshop (`workshop link`).
- Lessons from field work: a mixed first salvo, the MCP search servers the user
  chooses, the volet, dated refutations, divergences left unresolved, run-mode
  prefixes in any message.

## [0.9.0] - 2026-10-01

The engine (standard library only), its contract and its exit codes, the
providers' free-tier catalogue and quota ledger, archive connectors, reading,
the genealogical toolkit, the family indexes and the hash-chained event log,
reports, trees and exports, transcription, the self-learning library, the MCP
server, and the plugin for every harness from one source.

[Unreleased]: https://github.com/devohmycode/probandia/commits/master
