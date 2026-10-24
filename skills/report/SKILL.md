---
name: report
description: Writing the sections of a Probandia report — journal or living mode, references to sections, facts and persons, errata and revisions — then rendering it. Use it at the end of a research pass, or whenever report text must be written or corrected.
---

# Writing the report

The report is rendered by the engine from the research's events: you never
edit `report.md` or `report.html`. You add sections (and, in living mode,
rewrite them); `render` does the rest: numbering, links, citation
notes, errata notices, revision history, masking of living persons.

Write in the research's language (`LANG=`), in plain, precise prose. Every
claim about a person rests on a fact of the index, cited with `[[f:…]]`.

## Which mode

`MODE=` in the answer of `new`, `resume` or `digest`:

| Mode | The report is | You may |
|---|---|---|
| `journal` | one chapter per pass, as written then | add sections; record errata |
| `living` | the current state, by subject | add, rewrite, move and merge sections, with a reason |

In journal mode the text of a past pass is never changed: a mistake is
corrected by an erratum, which the engine shows after the section it concerns.

## Adding a section

Run the engine command:

```text
event append --type section.added --payload-file section.json
```

with `section.json`:

```json
{"section": {"parent": null, "kind": "chapter", "title": "The birth record",
             "body_md": "Émile was born on … [[f:emile-marchand-1851.birth]].",
             "facts": ["emile-marchand-1851.birth"]}}
```

- The answer gives `SECTION=<ULID>`: use it as the `parent` of the sections
  that go inside this one, and in `[[s:<ULID>]]` references.
- `kind`: `chapter` (top level, `parent: null`), `section` or `subsection`.
- `facts`: every fact the section rests on. Each fact asserted in a pass
  must appear in a section of that pass (rule V-7).
- In session mode, a pass's sections go in its one proposal
  (`sections: [ … ]`), with its facts, sources and searches; `event append`
  only when you need a new section's identifier.

### Journal mode

- In each pass, write one chapter: its title becomes "Pass n — <title>". Put
  the pass's sections inside it: what was searched, what was found, what it
  proves, what remains open.
- Say what was searched without result, with the source and the window: the
  negatives are part of the method.

### Living mode

Read `living.md` next to this file (`${CLAUDE_PLUGIN_ROOT}/skills/report/living.md`): the default
chapters, and how to rewrite, move or merge a section with its reason.

## References

| Write | Rendered as |
|---|---|
| `[[s:<ULID>]]` | a link with the section's number, such as « § I.2.1 » |
| `[[f:<fact id>]]` after your words | the citation note only: your sentence says the fact |
| `[[f:<fact id>]]` alone, after a colon, or as a list item | the fact (person, type, date, place) with its citation note |
| `[[p:<person id>]]` | the person's name, or "Living person" when presumed living |

- Never write a number by hand ("see section 3"): numbers change at each
  rendering; `[[s:…]]` follows the section.
- A reference that resolves to nothing fails rule V-6, and `render` warns.
- Never write the name or a date of a person presumed living (born less than
  100 years ago, or with no date at all, and no death recorded): use `[[p:…]]`,
  which masks it.
- Raw HTML in prose is shown as text, never rendered.
- Never write a citation by hand: `render` writes it from the source's model in
  `catalogues/citations/` (first note, then short note), ending with the passage the fact
  quotes (`excerpt`). Complete the source instead.

## Errata

When a fact recorded in an earlier pass proves wrong:

1. In a proposal, give the corrected fact and an erratum:
   `{target: {section: "<ULID>", fact: "<fact id>"}, wrong: "…",
   correction: "…", cause: misreading, detection: "how it was found"}`.
2. The cause is one of `misreading`, `homonym`, `faulty-index`,
   `outdated-negative`, `wrong-inference`, `tool-failure`, `missing-source`,
   `other`.
3. In journal mode the engine adds the notice after the section and marks the
   older mentions `†E<n>`; the earlier text stays as it was.
   In living mode, rewrite the section with `section.replaced` as well.

## Rendering

`render` writes `report/report.json`, then `report.md` and
`report.html`, in the research's language.

- `STATUS=WARN` with `REASON=unresolved-references`: fix the references listed.
- `PROSE=`, `CLAIM=` lines (`REASON=prose-claims`): a source or evidence called
  primary or secondary (say original or derivative source, primary or secondary
  information, direct or indirect evidence), or a dated sentence without
  `[[f:…]]`: cite the fact, or rewrite the sentence.
- `QUESTION=translate_labels` (the user says `translate`), later
  `LABELS_MISSING=`: one `harvester` (Haiku, effort `low`) adds the `POT=`
  entries to the `TARGET=` file, each `msgstr` translated; then render again.
- In living mode the previous Markdown is kept in `report/history/<pass>.md`.
- The HTML follows a template (`TEMPLATE=`): to change it, read `templates.md`
  next to this file (`${CLAUDE_PLUGIN_ROOT}/skills/report/templates.md`).

Then run `verify --light` (rules V-2, V-3, V-4 or V-5, V-6, V-12).
