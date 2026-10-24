# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project

Probandia is a genealogy research plugin for AI coding agents ("nothing is concluded until it is proven"). It follows the Genealogical Proof Standard (GPS). The repo contains both a Python engine (`src/probandia`, standard library only, Python >= 3.11) and the plugin assets (agents, commands, skills, hooks) for several harnesses. Documentation in `docs/` is largely in French; the user prefers French.

## Commands

```sh
python run_probandia.py --help                       # run the engine from the repo (no install needed; must work with no package installed)
python tools/run_tests.py                            # full test suite (unit + integration + golden files), shared out between processes (-j N, -v)
python -m unittest discover -s tests                 # the same suite in one process (as `run_tests.py -j 1`)
python tools/run_tests.py --measure                  # one process per module: rewrites tools/test_durations.json, which balances the shares
python -m unittest tests.unit.test_cli               # one test module
python -m unittest tests.unit.test_cli.SomeClass.test_name   # a single test
python -m pip install --editable ".[dev]"            # test dependencies: the `dev` extra of pyproject.toml (jsonschema, Pillow, ruff pinned)
python -m ruff check .                               # lint (F and E9, `[tool.ruff]` in pyproject.toml)
python tools/make_sample_project.py                  # regenerate tests/sample-project and tests/sample-project-gps (CI fails if `git status --porcelain` shows a difference)
python run_probandia.py manifests check              # generated plugin manifests must be up to date
python tools/check_wheel.py                          # build the wheel and sdist: files = tools/package-contents.txt, no private name; install the wheel, check it finds its data
python tools/check_wheel.py --update                 # after adding, moving or removing a packaged file: rewrite tools/package-contents.txt (read its diff)
python tools/startup_time.py                         # median startup time of `--version` and `hook guard` (measure only)
python tools/ci_local.py                             # the whole CI on this machine: every job of ci.yml, Windows and Ubuntu (WSL)
python tools/ci_local.py --quick                     # what a sprint needs: test on Windows 3.14 and Ubuntu 3.12, tui/gedcom when their files change
python tools/ci_local.py --jobs test --os windows --python 3.14   # a part of it; --rev <commit>, --parallel N (default 8), --dry-run
uv tool install --editable .                         # install the `probandia` command from the repo (add --force after pyproject.toml changes)
```

CI (`.github/workflows/ci.yml`): a `test` job (the steps above; its tests run through `tools/run_tests.py`) on Windows with Python 3.11 and 3.14, on Ubuntu with 3.11 to 3.14, and on macOS with 3.14 for `master` only; a `tui` job (the optional terminal interface) on Windows and Ubuntu with 3.11 and 3.14, macOS 3.14 on `master`; a `gedcom` job that validates GEDCOM 7 exports (`tools/check_gedcom7.py`, `tools/validate_gedcom7.mjs`). The checks after the tests run even when the tests fail; the test step fails on any `ResourceWarning`; actions are pinned by commit SHA. Nothing is pushed before the 1.0.0: `tools/ci_local.py` replays these jobs from `ci.yml` itself, each combination in a fresh copy of the source (Windows directly, Ubuntu through `wsl.exe -d Ubuntu-24.04`, the `gedcom` job under Windows, where Node is), and writes a log per combination and a bilan in `~/probandia-ci/<run>/` (exit 0 only when everything is green; macOS cannot run there).

## Merge rule

`master` has no branch protection yet, so this rule stands in for it. Before merging a sprint into `master`:

- `python tools/ci_local.py --quick` is green (on the sprint's branch, or `--rev <its last commit>`). It runs `test (windows-latest, 3.14)` and `test (ubuntu-latest, 3.12)`, plus `tui (windows-latest, 3.14)` when the sprint changes a file of the TUI (`src/probandia/cli/tui_*`, `tests/unit/test_tui*`) and `gedcom` when it changes a file of the GEDCOM export; the files are counted since the merge base with `master`. When the sprint changes the CI itself, the package or the version (`.github/workflows/ci.yml`, `tools/ci_local.py`, `tools/run_tests.py`, `tools/check_wheel.py`, `pyproject.toml` and its `force-include`, `run_probandia.py`, `src/probandia/__init__.py`), `--quick` runs the whole CI by itself and says so: that run must be green;
- `python run_probandia.py manifests check` passes;
- `python tools/make_sample_project.py` leaves no difference (`git status --porcelain -- tests/sample-project tests/sample-project-gps` is empty);
- `python -m unittest tests.unit.test_no_private_names` passes;
- when the sprint changes a file of the TUI, `python -m unittest tests.unit.test_tui_speed` passes with its times, on a calm machine (processor load under 30 %, no CI nor agent running) and in an environment with the `tui` extra (without Textual it is skipped). `tools/ci_local.py` sets `CI_LOCAL_NO_TIMING=1`, under which these tests skip their assertions of time and check the rest: its own load (some 34 processes on 16 cores) makes the times vary tenfold.

Before a version (a new number in `src/probandia/__init__.py`, a tag), the whole CI is green on the commit that carries it: `python tools/ci_local.py --rev <commit>` (every combination), not `--quick`; and `test_tui_speed` passes with its times, on a calm machine.

GitHub Actions is disabled on the repository until the 1.0.0 (14 October 2026: its minutes are billed on a private repository): the local CI is the CI. It is enabled again with the first push of the 1.0.0 (`gh api -X PUT repos/<owner>/probandia/actions/permissions -F enabled=true`). From then on, after each push (only with the user's agreement), read `gh run list --limit 1`. A red run on `master` is fixed before the next merge.

## Architecture

- **Launcher**: `run_probandia.py` puts `src/` on `sys.path` and calls `probandia.cli.main`. It is deliberately not named `probandia.py` (it would shadow the package). `src/probandia/_vendor` is installed on import in `__init__.py`.
- **Version**: lives only in `src/probandia/__init__.py` (hatch reads it).
- **Data at repo root, copied into the wheel**: `catalogues/`, `locales/`, `schemas/`, `vendor-js/`, `report-templates/`, `designer/` are force-included in the wheel under `probandia/_data/`; `probandia.paths` resolves both layouts. Keep new data files in these root folders and update `force-include` if adding a new one.
- **Engine layout (`src/probandia/`)**: `cli/` (one `*_cmd.py` per command group, `commands.py` registry, `output.py`/`human.py` rendering, `helptext.py`, `completion.py`), `ledger/`, `proof/` (GPS elements: questions, matrix, arguments, conflicts, confidence, standard), `providers/` and `archives/` (search/read sources, free-quota accounting via `budget.py`/`limits.py`), `reading/`, `report/`, `harness/` (per-agent-tool integration), `mcp/`, `install/`, `config/`, `i18n/`, `lang/`, `util/`; plus top-level modules such as `verify.py` (rules V-nn), `guard.py`/`hooks.py` (hook handlers), `research.py`, `lifecycle.py`, `gedcom*.py`, `known.py`.
- **Two output readers**: the same command prints a human screen at a terminal, and a "contract" when piped or run by an agent (one `KEY=value` per line starting with `STATUS=`, max 40 lines), or JSON (`--output-format human|contract|json`). Skills and agents parse the contract, so changing its keys is a breaking change. Exit codes are meaningful (0 ok, 1 verification failed, 2 usage, 3 question waiting, 4 stopped by quota, 5 locked, 6 not in a project, 7 network, 10 internal, 130 interrupted); see `probandia help exit-codes`.
- **Project data model**: a user project is a folder holding `probandia.toml`, with `families/`, researches, and a `.probandia/pb.py` that belongs to the plugin (the installed command never rewrites it). JSON schemas in `schemas/*-N.json` define stored records.
- **Plugin surface (multi-harness)**: `agents/` and `droids/` hold the same seven agents (orchestrator, researcher, searcher, reader, investigator, contradictor, harvester) for different harnesses; `commands/*.md` are slash commands; `skills/` (engine, research, ask, browser, config, report, team, transcribe) are agent instructions; `hooks.json`, `hooks/`, `.claude-plugin`, `.codex-plugin`, `.cursor-plugin`, `.factory-plugin`, `plugin.json`, `mcp*.json` are per-harness manifests, generated and verified by `manifests check`. When editing agents/commands, check that sibling copies (`agents/` vs `droids/`) and manifests stay in sync.
- **i18n**: user-facing strings go through `locales/` (gettext-style, `probandia.pot`, `en`/`fr`, with a pseudo-locale exercised by tests). English is the default; `-l fr` or `PROBANDIA_LANGUAGE=fr`.
- **Tests (`tests/`)**: `unit/`, `integration/`, `fixtures/`, `golden/` (golden-file outputs), `sample-project*/` (generated; don't edit by hand). `bench/` holds the benchmark harness (`bench/run.py`; its plan, `docs/benchmarks.md`, is not tracked).
- **Examples (`examples/hugo/`)**: real records of the example family, Victor Hugo's, that may be shared (public domain, CC0), each in `manifest.yaml` with its source, rights, credit and SHA-256 (`tests/unit/test_examples.py` checks them); not in the wheel. An image added there needs its manifest entry.

## Notes

- Hooks are invoked as `python run_probandia.py hook <guard|log|digest> --harness <name>`; keep them fast (timeouts of 10-15 s).
- Free-quota actions (`search`, `read`, `archive run`) and hard-to-undo writes (`apply`, `quota add`, replacing `export`) prompt `[y/N]` at a terminal; `--yes` answers for you, and nothing is asked when no one is at the keyboard. Concurrent sessions are guarded by locks (`PROBANDIA_SESSION` env var identifies a session, as used in CI).
- `.remember/` contains local session notes, not project documentation.
