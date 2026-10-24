---
name: config
description: Explain and change Probandia settings by grade (essential, advanced, expert), and show where each value comes from. Use when the user asks about Probandia's settings, wants to change one, or asks why a value is in effect.
---

# Probandia settings

Settings come in three grades: **essential** (8 settings, for a beginner), **advanced** (about 20 more) and **expert** (all of them). The grade is itself a setting; it only changes what is shown, never what takes effect.

## Calling the engine

Call the engine from the project root; the values chosen in `/config` reach it as their own layer through the hooks, which keep them for the session:

```bash
python .probandia/pb.py config <action>
```

The `engine` skill says where the engine is when the path still shows a variable, and how to read every answer. If a `DETAILS=` path is given, read that file for the full list.

## Actions

| The user wants to… | Action |
|---|---|
| see the settings in effect | `config show --origin` |
| see the settings of a higher grade, or all of them | `config show --origin --grade advanced`, `config show --origin --all` |
| understand one setting | `config explain <key>` |
| change a setting for this project | `config set <key> <value>` |
| change it for every project of this user | `config set <key> <value> --user` |
| change it on this machine only, without versioning it | `config set <key> <value> --local` |
| go back to the default | `config unset <key>` (with `--user` or `--local` if it was set there) |
| check every source of settings | `config validate` |
| create the settings file of a new project | `config init --grade essential` |
| see or change each agent's model and effort | `config roles`; `config set roles.reader.model opus`, `roles.reader.effort high`; per harness: `roles.reader.models cursor:claude-opus-5` |

## Where a value comes from

From lowest to highest priority: built-in default, the harness options (`/config` in Claude Code), the user file, the project file `probandia.toml`, the local file `probandia.local.toml`, `PROBANDIA_*` variables, then command arguments. `config show --origin` prints the layer and the source after each value, for example `report.mode=living  # project probandia.toml`.

- A new `probandia.toml` leaves the eight essential settings commented out, so `/config` keeps its effect. Once a value is set in `probandia.toml`, it wins over `/config`, so a research behaves the same in every harness. When the user changes a value in `/config` and nothing happens, check with `config show --origin` whether the project file sets it, and offer `config unset <key>`.
- A value marked `(above grade)` takes effect even though the user's grade does not show it.
- API keys are never settings: they live in environment variables or in a `.env` file, the user's (next to `config.toml`) or the project's (next to `probandia.toml`). Never write a key into a file yourself, and never print one: give the user the variable name and the file, and let them paste the key.

## Providers and their keys

`.env.example` lists every key. The ones a user asks about most:

| Provider | Key | Free tier | Note |
|---|---|---|---|
| SerpApi (Google; Bing off by default) | `SERPAPI_API_KEY` | 250 searches a month | Bing draws on the same 250 and answered most exact queries beside the point: add `serpapi_bing` to `providers.enabled` only to try it |
| Serper | `SERPER_API_KEY` | 2,500 credits once | expire 6 months after sign-up |
| OpenWeb Ninja (web, news, books) | `OPENWEBNINJA_API_KEY` | 100 requests a month per API | subscribe to each API's free plan first |
| Firecrawl | `FIRECRAWL_API_KEY` | 1,000 credits a month | |
| ZenRows, ScraperAPI | `ZENROWS_API_KEY`, `SCRAPERAPI_API_KEY` | 5,000 and 1,000 credits a month | last-resort readers, never on archive portals |
| Apify | `APIFY_TOKEN` | 5 $ a month | a few allowed actors only |

- `doctor` says which keys are found and which balances can be read; `quota show` what is left of each, in searches and pages, and when it starts again; `quota sync` reads the providers' own counts.
- `watch` replays the archives' witnesses and lists the catalogue entries older than `catalogues.max_age_days`; `watch --print-schedule` gives the weekly task for the user to run.
- `providers.enabled` (advanced) turns a provider off; `reading.per_search` (expert) is the number of pages a wave plans to read for each search.

## Answering

- Explain in the user's language, in a few sentences, and quote the keys exactly.
- Before `config set`, say which file will change. After it, report the `WARN` lines: they say when a higher layer still overrides the new value.
- Lists are comma-separated on the command line: `config set report.formats md,html,json`.
