# Living mode

The default chapters are Summary, Question and scope, Persons, Evidence and
analysis, Hypotheses, Negative searches, Open questions, Sources, Method and
Revision history. The engine fills Question, Persons, Hypotheses, Negative
searches, Sources, Method and Revision history itself. To write in a default
chapter, add a chapter with its name in the report's language (for example
"Synthèse" in French): it is merged into it. Other chapters go before Sources.

To change a section, never add a second one: rewrite it.

```json
{"section": "<ULID>", "title": "…", "body_md": "…", "reason": "the new record shows …"}
```

`--type section.replaced` rewrites a section and keeps its anchor;
`section.moved` takes `{"section", "parent", "position", "reason"}`;
`section.merged` takes `{"sections": [ … ], "into", "reason"}` and keeps the
merged anchors as aliases. Every rewrite needs its `reason`: it goes into the
revision history (rule V-5).
