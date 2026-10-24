# Benchmark metrics

The benchmark runs at each release and at each change of model (SPECS § 14.6). Its
questions are research questions already solved by hand: their answers are known.
They come from private family files, so they stay outside the repository, in
`PROBANDIA_BENCH_DIR`.

## A question

```yaml
id: marchand-parents
project: ../projects/marchand          # the project where the research was run
research: 2026-09-01-ancestors-of-louis-marchand   # optional when the project holds one research
expected:
  - {person: "Henri MARCHAND", type: birth, year: 1870, place: Bourg-Vert}
  - {person: "Louise PERRIN", type: birth, abstain: true}
run: {tokens: 182000}                  # only when the stop hooks recorded none
```

- `person` is a person id or a name ("Given SURNAME", accents and case ignored).
- `abstain: true` means the right answer is "not found": no source can prove it.
- `run` holds what the engine cannot see, such as the tokens of a harness whose transcript it cannot read.
- Without `research:`, the question takes the only research of its project; a project that holds several
  is refused (exit code 2).

## The metrics

| Metric | How it is counted |
|---|---|
| findings | expected facts found among the research's proven facts (`record` or `index`): same person, same type, the year within 1, the place when one is given. The place matches without case, accents, punctuation, doubt marks (`?`), the words of the record and the article before the name ("né aux Auxons" is Les Auxons): as written, by any of its segments between commas, semicolons and brackets, each cut before "village", "hameau", "paroisse" or "lieu-dit" ("Besançon, village de Chamars", "village de Chamars, Besançon" and "… en cette commune (Besançon)" are Besançon), by its id, or by a name the family's `places.yaml` gives that id. The commune followed by a space at the head of a segment matches too ("Besançon Gd Duché de Bourgogne"). "Besançon-les-Bains" is not Besançon, and a misread name ("Besançan") is not either. The expected `place` may be a list, for a commune known under several names (`[Les Auxons, Auxon-Dessus]`): any of them matches |
| false promotions | proven facts that contradict the answer (another year or place), prove an `abstain` item, cite an online tree (`online-tree` source: finding the right date there is not reading the act), or were later revised or retracted; per 100 proven facts of the research |
| facts without a citation | proven facts whose source is missing from `sources.yaml` |
| duplicates | proven facts of the research that prove again an event of a person it already proved: the same type for the events a person has once (birth, baptism, death, burial), whatever the date; for the other types, the same type, the same word in the fact's id (`parentage` in `<person>.parentage.2`) and the same date. The first proof of each event is not counted; a high count inflates the facts per record without adding anything |
| justified abstentions | `abstain` items for which the research proved nothing |
| passages quoted, found again | findings whose fact quotes its passage (`excerpt`) and whose passage is found again in its transcription or the page kept (TRUST5) |
| tokens | from `.probandia/tokens.jsonl`, written by the stop hooks from the harness's transcript: each kind apart (input, output, cache read, cache written, and the part of it written to the five-minute cache), and their sum weighted by price, in input-equivalent tokens (cache read 0.1, cache written to the one-hour cache 2, to the five-minute cache 1.25, output 5); `run.tokens` only when none was recorded. Claude Code's main thread writes the one-hour cache, its subagents the five-minute one (`cache_write_5m` in `tokens.jsonl`, from `usage.cache_creation.ephemeral_5m_input_tokens`); a line written before `cache_write_5m` existed counts as one-hour cache. Never add the kinds as they are: cache reads are by far the most numerous and the cheapest |
| tokens by harness and model | the same kinds and weighted sum per (harness, model) pair of the lines of `tokens.jsonl`, since a research whose main thread runs on one model and its readers on another mixes tokens of different prices; shown with the research's mode and effort, taken from the `run` of each `pass.started` event (what each pass was launched with), else from the `run` of `research.yaml` |
| amount paid | the `paid` amounts of the ledger for the research: expected 0 |
| native searches | the research's native web searches in the search log |
| duration | the sum of `duration_s` of the research's `pass.ended` events |
| checks of the expected answers | version-1.0.0 T254: what an expected answer asks of the facts that give it, read on the research's proposed and applied data, never by a judge: `date` (the same date, or within `tolerance_days`), `axes` (the given axes of the fact's `evidence`), `confidence_max` (no answered question that concludes on the fact reaches a higher confidence, as the engine computes it), `uncertain_reading` (the fact carries one, or not), `distinct` (the `label` of another answer, whose person must be another person record: homonyms kept apart). Each check is passed, failed, or not judged when its answer was not found; a fact of a homonym that gives another expected answer is not a false promotion. Shown only for the cases that ask for checks, an `observed` case marked as such: it informs and blocks nothing |

The runner reads the indexes, the events, the search log and the ledger; it never
reads a report.

    python bench/run.py --bench-dir <dir> [--out <file>] [--json <file>]

## results.json

`--json <file>` writes, next to the Markdown report, the same scores as a document
that can be published (`schemas/bench-result-1.json`, an example in
`schemas/examples/bench-result-1.json`): the version of Probandia and the date, then
per case its id, the harness and its version, the model, the effort and the mode it
was played with, the duration and passes, the metrics (counts only), the tokens by
kind and by (harness, model) pair. It holds no fact id, no research id and no path:
they carry the names of persons and of the user's folders. The project does not
record the harness's version, and a session launched with a model or an effort of
its own leaves none in the research: the options say them.

    python bench/run.py --question <file.yaml> --json <results.json> [--harness <name>]
        [--harness-version <version>] [--model <model>] [--effort <level>]

`--question` scores one question file, wherever it lies (the session bench writes
one next to each project played). Otherwise the harness and the model are those of
the main thread's tokens (role `session`), the model and the effort those of the
research's `run`.

## Comparing results

    python bench/run.py --compare a.json b.json c.json [--out <file>]

writes a table per case: one column per (harness, model, effort), in the order the
files meet them, every entry of the same case and column being a repetition; each
cell gives the median of the repetitions and their range, `median [min–max]`. Every
column after the first gets a verdict against the first, metric by metric. A
verdict says which way a value moved, not whether that is better: fewer tokens is
good, fewer findings is not.

The verdict rule, the same as the session bench's:

- with at least 3 repetitions in each of the two columns, `lower` or `higher` only
  when the min–max ranges do not overlap (3 runs against 3: an exact permutation
  test, p = 1/20, the smallest such a sample can give), else `inconclusive`;
- under 3 repetitions in either column, `too few runs`.

A run without the value (tokens the harness did not report) is not counted. The
difference of two medians alone is never a verdict: three runs of the same code and
model have cost from 0.91 to 1.23 dollars, and one run of a version used 3.7 times
the tokens of another run of the same version.

Public cases, on persons dead for more than a hundred years and open sources, live
in the repository: see [public/README.md](public/README.md).

    python bench/run.py --case bench/public/cases/<case> [--played <project>]

## Hook cost per pass

Hooks cost time, not tokens. `tools/hook_cost.py` replays offline the tool calls of a kept
session stream as the `PreToolUse` and `PostToolUse` payloads of `hooks/hooks.json`
(`hook guard` for every tool, `hook log` for the tools its matcher takes), in a copy of
`tests/sample-project`, and times each run. The other hooks of the pass (`SessionStart`,
`UserPromptSubmit`, `Stop`, `SubagentStop`: 5 runs on this stream) are not replayed.

    python tools/hook_cost.py <session.jsonl> [--json]

| Stream | System | Runs by event | Median | Total per pass |
|---|---|---|---|---|
| J8, essai 1 (main agent and two `reader`) | Windows 11, Python 3.14.7 | `PreToolUse` 78, `PostToolUse` 5 | guard 633–658 ms, log 610–674 ms | 54.1–56.9 s |
| J8, essai 1 | Linux (WSL, Ubuntu 24.04, ext4), Python 3.12.3 | `PreToolUse` 78, `PostToolUse` 5 | guard 108–119 ms, log 121–122 ms | 10.3–10.9 s |

Measured on 13 October 2026, two replays on each system (the range), on top of `3c955f9`; every
hook exited 0 and none refused a call. This is the "before" of a lazy start of the guard.
