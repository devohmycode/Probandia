# Stability policy for Probandia 1.x

Probandia follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) from
1.0.0 on. This page says which surfaces are public, so that a 1.x version keeps
them, and how one of them changes: first deprecated, then removed in a major
version only. What a version changed is in
[CHANGELOG.md](https://github.com/devohmycode/probandia/blob/master/CHANGELOG.md),
breaking changes first.

## The public surfaces

1. **Commands and their options**: the commands of `probandia help` (the
   `COMMANDS` registry of `src/probandia/cli/commands.py`), their actions,
   options and arguments, and the global options of `probandia --help`
   (`--project`, `--lang`, `--json`, `--output-format`, `--yes`…).
2. **Exit codes**: 0, 1, 2, 3, 4, 5, 6, 7, 10 and 130, with the meaning
   `probandia help exit-codes` gives them (`src/probandia/errors.py`).
3. **The `KEY=value` contract**: the first line `STATUS=OK|WARN|FAIL|ASK|STOP`,
   then one `KEY=value` per line, 40 lines at most, that a command prints when
   piped or run by an agent (`--output-format contract`). The keys the skills,
   agents and commands of the plugin read are frozen by
   `tests/unit/test_contract_keys.py` (version-1.0.0 T207), with reference
   outputs in `tests/golden/contract/`.
4. **The `--json` output**: one object with `status`, `values` (the contract's
   keys and values), `lines`, `details` and, for the commands that publish
   records, `data`.
5. **The MCP server's tools**: the 17 tools of `probandia mcp` (`dates`,
   `export`, `find_operation`, `known`, `library_find`, `places`, `plan`,
   `propose`, `question`, `quota`, `read`, `render`, `run_operation`, `search`,
   `tree`, `variants`, `verify`), their names and their input schemas
   (`tests/unit/test_mcp.py`).
6. **The schemas of stored records**: `schemas/*-N.json`, the files a project
   holds (`probandia.toml`, `families/`, researches, proposals, the event log).
   The `-1` schemas are frozen at 1.0.0: any change to a record's shape creates
   a `-2` schema, which the engine writes while it keeps reading the `-1`
   records (as `library-1` and `library-2` already do). A project written by a
   1.x version opens in every later 1.x version. `tests/unit/test_schema.py`
   fails when a published schema changes, and `tests/integration/test_old_project.py`
   opens a project written by the 0.9.41.
7. **The GEDCOM extension tags**: `_STATUS`, `_EVID`, `_HYPO`, `_NEGA` and
   `_CONF`, with the URIs that the `SCHMA` header of each GEDCOM 7 export gives
   them (`SCHEMA` in `src/probandia/gedcom.py`).

The settings of `probandia.toml` and of the user's settings (the registry of
`src/probandia/config/registry.py`) follow the rules of the options.

## How a public surface changes

- **Adding** is not a break: a new command, option, contract key, `--json`
  field, MCP tool, optional field of a schema or GEDCOM tag comes in a minor
  version. A reader must ignore what it does not know.
- **A new event type** is the exception: an older engine that finds it in
  `events.jsonl` stops with exit code 2 (`REASON=schema-version`), says that
  the event comes from a newer version and that Probandia must be updated, and
  rewrites nothing of the log.
- **Renaming** a command, an option, a setting or a contract key keeps the old
  name as an alias for at least one minor version: the old name still works,
  and the engine says `WARN` with the new name. A key is never renamed without
  its alias.
- **Removing** happens in a major version only, after the alias has lived
  through at least one minor version, and is listed under
  **Breaking changes** in `CHANGELOG.md`.
- **Exit codes** keep their meaning for the whole of 1.x; a new code may be
  added in a minor version.
- **Schemas**: see surface 6; a frozen `-1` schema never changes.
- **GEDCOM tags** keep their names and URIs for the whole of 1.x: an export
  already shared carries them.

Deprecated now, removed in 2.0: the settings `search.model`, `search.effort`,
`run.model` and `run.effort`, older forms of `roles.searcher.*` and
`roles.orchestrator.*`. They still count while the `roles.<role>.*` setting is
left at its default, as `config explain` says; `config validate` gives a
`WARN` that names the new key (`RENAMED` in `src/probandia/config/registry.py`),
and a new `probandia.toml` no longer offers them.

## What is not public

- The readable screens printed at a terminal (`--output-format human`), their
  words and their layout, and their translations.
- The engine's Python modules and functions: `probandia` is a command, not a
  library.
- The plugin's skills, agents, commands and hooks: they travel with the engine
  in the same version, so a change to them and to the engine lands together.
  For the same reason the contract carries no version number of its own:
  `probandia --version` (and `doctor`, run by the agent, for the plugin's
  engine) tells which version answers.
- Logs, caches and the files under `.probandia/` that belong to the plugin.
- The free-tier figures of `catalogues/providers.toml`, which follow the
  providers' own pages.
