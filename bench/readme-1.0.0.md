# The README's examples, replayed (version-1.0.0 T191)

Written by `python tools/run_readme_examples.py` on 2026-10-17, at `3cb3551` (the README of the working tree), on win32, Python 3.14.7; bash: GNU bash, version 5.3.15(2)-release (x86_64-pc-cygwin); PowerShell: 7.6.7.

Each example ran in a copy of `tests/sample-project`, in the order of the README, without a key or a network (an empty settings folder, the key variables removed, a proxy that does not answer).

Result: 73 examples, 0 exit code(s) not the one expected.

| # | Example | bash | PowerShell | Expected | Note |
|---|---|---|---|---|---|
| 1 | `probandia --version` | 0 | 0 | 0 |  |
| 2 | `probandia doctor` | 0 | 0 | 0 |  |
| 3 | `probandia keys` | 0 | 0 | 0 |  |
| 4 | `probandia keys signup tavily` | 0 | 0 | 0 |  |
| 5 | `probandia keys set TAVILY_API_KEY` | not run | not run | - | asks the key at the keyboard |
| 6 | `probandia keys check` | 0 | 0 | 0 |  |
| 7 | `probandia status` | 0 | 0 | 0 |  |
| 8 | `probandia dates "7 ventôse an X"` | 0 | 0 | 0 |  |
| 9 | `probandia` | not run | not run | - | the welcome screen needs a terminal (elsewhere: a usage error, 2) |
| 10 | `probandia -u` | 0 | 0 | 0 |  |
| 11 | `probandia -s` | 0 | 0 | 0 |  |
| 12 | `probandia verify 2026-09` | 0 | 0 | 0 |  |
| 13 | `probandia known 2026-09` | 0 | 0 | 0 |  |
| 14 | `probandia help exit-codes` | 0 | 0 | 0 |  |
| 15 | `probandia verify 2026-09 -q` | 0 | 0 | 0 |  |
| 16 | `probandia -u --json > quotas.json` | 0 | 0 | 0 |  |
| 17 | `probandia verify 2026-09 -q || echo "exit code: $?"` | 0 | not in this shell | 0 |  |
| 18 | `probandia -u --csv > quotas.csv` | 0 | 0 | 0 |  |
| 19 | `probandia new "Who were the parents of Victor Hugo?" --family hugo --mode session` | 0 | 0 | 0 |  |
| 20 | `probandia resume 2026-09` | 0 | 0 | 0 |  |
| 21 | `probandia fork 2026-09 --at 2 --name second-lead` | 0 | 0 | 0 |  |
| 22 | `probandia verify --standard` | 0 | 0 | 0 |  |
| 23 | `probandia question list` | 0 | 0 | 0 |  |
| 24 | `probandia matrix` | 0 | 0 | 0 |  |
| 25 | `probandia fact check louis-marchand-1898.birth --by "Marie Durand" --looked "the image of the act"` | not run | not run | - | records what a person looked at: at a terminal only |
| 26 | `probandia close` | not run | not run | - | the research has a pass open (opened by resume above): close wants every pass ended |
| 27 | `probandia board --json` | 0 | 0 | 0 |  |
| 28 | `probandia statusline` | 0 | 0 | 0 |  |
| 29 | `probandia report open` | not run | not run | - | opens the report in the browser |
| 30 | `probandia tree --family marchand --format html` | 0 | 0 | 0 |  |
| 31 | `probandia export gedcom7 --family marchand --living mask` | 0 | 0 | 0 |  |
| 32 | `probandia import ../my-workshop --dry-run` | 0 | 0 | 0 |  |
| 33 | `probandia import-gedcom family.ged --family marchand` | 0 | 0 | 0 |  |
| 34 | `probandia research list` | 0 | 0 | 0 |  |
| 35 | `probandia family show marchand` | 0 | 0 | 0 |  |
| 36 | `probandia find Marchand` | 0 | 0 | 0 |  |
| 37 | `probandia person louis-marchand-1898` | 0 | 0 | 0 |  |
| 38 | `probandia searches --family marchand` | 0 | 0 | 0 |  |
| 39 | `probandia sources --family marchand` | 0 | 0 | 0 |  |
| 40 | `probandia negatives` | 0 | 0 | 0 |  |
| 41 | `probandia hypotheses` | 0 | 0 | 0 |  |
| 42 | `probandia gaps` | 0 | 0 | 0 |  |
| 43 | `probandia proposals list` | 0 | 0 | 0 |  |
| 44 | `probandia usage --sync` | 0 | 0 | 0 |  |
| 45 | `probandia quota show` | 0 | 0 | 0 |  |
| 46 | `probandia cache stats` | 0 | 0 | 0 |  |
| 47 | `probandia init` | 0 | 0 | 0 |  |
| 48 | `probandia config show --origin` | 0 | 0 | 0 |  |
| 49 | `probandia providers show serper` | 0 | 0 | 0 |  |
| 50 | `probandia watch` | 0 | 0 | 0 |  |
| 51 | `probandia library list` | 0 | 0 | 0 |  |
| 52 | `probandia memory list` | 0 | 0 | 0 |  |
| 53 | `probandia template list` | 0 | 0 | 0 |  |
| 54 | `probandia browser login familysearch` | not run | not run | - | opens a browser for a sign-in |
| 55 | `probandia variants Marchand --paleo` | 0 | 0 | 0 |  |
| 56 | `probandia places "Besançon" --as-of 1802` | 0 | 0 | 0 |  |
| 57 | `probandia cite src-01JA0000000000000000000001 --family marchand` | 0 | 0 | 0 |  |
| 58 | `probandia help grades` | 0 | 0 | 0 |  |
| 59 | `probandia completion bash` | 0 | 0 | 0 |  |
| 60 | `probandia tui` | not run | not run | - | needs an interactive terminal |
| 61 | `probandia config explain report.mode` | 0 | 0 | 0 |  |
| 62 | `probandia config set search.max_parallel 5` | 0 | 0 | 0 |  |
| 63 | `probandia config unset search.max_parallel` | 0 | 0 | 0 |  |
| 64 | `probandia config init --grade advanced` | 0 | 0 | 0 |  |
| 65 | `probandia config validate` | 0 | 0 | 0 |  |
| 66 | `probandia config path` | 0 | 0 | 0 |  |
| 67 | `probandia config wizard` | not run | not run | - | asks the settings at the keyboard |
| 68 | `probandia config edit --user` | not run | not run | - | opens an editor |
| 69 | `probandia config grade advanced` | 0 | 0 | 0 |  |
| 70 | `probandia config diff` | 0 | 0 | 0 |  |
| 71 | `probandia config roles` | 0 | 0 | 0 |  |
| 72 | `probandia config set roles.reader.model opus` | 0 | 0 | 0 |  |
| 73 | `probandia config set roles.searcher.effort medium` | 0 | 0 | 0 |  |
