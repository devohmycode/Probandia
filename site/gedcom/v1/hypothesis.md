# `_HYPO` — an open genealogical question and its hypotheses

URI: `https://probandia.replit.app/gedcom/v1/hypothesis`

| | |
|---|---|
| Kind | extension record (`0 @H<n>@ _HYPO`) |
| Payload | the question, as text |
| Substructures | `NOTE`, one per competing hypothesis: `<id>: <statement> (<status>)`, the status being `open`, `retained` or `rejected` |

```text
0 @H1@ _HYPO Who was the father of Victor Hugo?
1 NOTE a: Léopold Hugot (open)
1 NOTE b: another Hugo of Besançon (open)
```

GEDCOM 5.5.1 exports write it as a `NOTE` record: `Hypothesis: <question> — a: … ; b: …`.
