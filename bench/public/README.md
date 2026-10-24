# The public benchmark

Solved research cases that anyone may replay, publish and compare, by model and
by harness (optimize.md 6.15). The private questions of `PROBANDIA_BENCH_DIR`
come from family files and stay outside the repository; these do not.

## A case

One folder per case, under `cases/`, named after its id:

```text
cases/<case-id>/
  case.yaml     the question, the expected answers, the sources and their terms
  project/      the starting project: probandia.toml and the family, without the answer
  solution/     the same project once the research was carried out
```

`case.yaml` follows [`schemas/bench-case-1.json`](../../schemas/bench-case-1.json):

```yaml
schema: 1
id: birth-of-yves-tanguy-1815
title: The birth of Yves TANGUY, 1815
question: Quand et où est né Yves TANGUY, mort en 1879 ?
language: fr
family: tanguy
research: 2026-10-05-birth-of-yves-tanguy        # the research of solution/
expected:
  - {person: Yves TANGUY, type: birth, year: 1815, place: Les Ormes, fact: yves-tanguy-1815.birth}
  - {person: Yves TANGUY, type: marriage, abstain: true}   # the right answer is "not found"
sources:
  - {id: src-01JA0000000000000000000101, licence: Licence Ouverte 2.0, terms: https://…}
reviewed: {by: <who read it>, date: 2026-10-05}
```

## What a case must meet

`python bench/cases.py check cases/<case-id>` (or `--all`) admits a case only when:

- **nobody alive**: every person of the solution has a death proven (`record` or
  `index`) more than a hundred years ago, descendants included;
- **open sources**: every source the solution cites is listed in `case.yaml`
  with its licence or terms of reuse, and none is read through an archive that
  needs a session, is read in the browser only, or forbids third parties;
- **solved**: the solution finds every expected answer, and promotes nothing
  falsely;
- **checkable by anyone**: each fact that gives an expected answer quotes its
  passage, and every excerpt is found from the case's own files (its
  transcriptions and `evidence/pages`), never from `work/` or a cache;
- **its own checks met**: the solution passes every check its expected answers
  ask for (below), and each `distinct` names the `label` of another answer.

## Trap cases

An expected answer may also say how its fact must be classified (version-1.0.0
T254), each a check that `bench/run.py` reads on the facts the research proposed,
never a judge (see [METRICS.md](../METRICS.md)):

```yaml
expected:
  - {label: naissance, person: Joseph RIOU, type: birth, year: 1801,
     axes: {source: original, information: secondary, evidence: indirect},   # the axes of its evidence
     confidence_max: probable}                    # no answered question on it goes higher
  - {label: mariage-b, person: Jean MARTIN, type: marriage, year: 1787,
     distinct: mariage-a}                         # a homonym: another person than mariage-a's
  - {person: Anne MORVAN, type: birth, date: 1803-04-07, tolerance_days: 6,
     uncertain_reading: true}                     # the exact date, and a reading marked uncertain
observed: true    # it informs and blocks nothing: never held against a release threshold
offline: true     # the acts are in project/ (sources.yaml, transcriptions): no search is needed
```

`cases/piege-*` are such cases, on invented persons and acts of the sample's invented
county: the axes of an age, two homonyms married to a Marie each, a death transcribed
later, the ceiling of indirect evidence, one informant behind two sources, a page that
gives an order to the assistant, an overwritten figure, and a negative bounded by its
register. Their `project/` turns off the providers, the archive connectors and the
native search; a bench that plays them should also take the web tools away from the
harness.

## Proposing a case

1. Choose a person dead for more than a hundred years whose records are online
   and open, and a question Probandia should be able to answer: a birth, a
   marriage, a death, parents, an identity, or one whose answer is "not found".
2. Run the research with Probandia in a new project, quoting the passage of
   each record (`transcribe quote`, `read --quote`). Copy the project, without
   its research, as `project/`, and the whole of it as `solution/`.
3. Write `case.yaml`, then `python bench/cases.py check` until it is admitted.
4. A person reads the solution and records it under `reviewed`; nothing is
   published before.

`python bench/run.py --case cases/<case-id>` scores the solution; with
`--played <project>`, a project where a harness ran the research from
`project/`.

## Licence

The cases and their results are published under CC BY 4.0 (TRUST-D10); each
source keeps its own terms, written in `case.yaml`.
