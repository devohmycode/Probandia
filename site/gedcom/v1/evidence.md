# `_EVID` — the evidence axes of a fact

URI: `https://probandia.replit.app/gedcom/v1/evidence`

| | |
|---|---|
| Superstructures | any event or attribute structure |
| Payload | three words, in this order: source, information, evidence |
| Cardinality | `{0:1}` |
| Substructures | none |

| Axis | Values |
|---|---|
| source | `original`, `derivative`, `authored` |
| information | `primary`, `secondary`, `undetermined` |
| evidence | `direct`, `indirect`, `negative` |

These are the three axes of the Genealogical Proof Standard's evidence analysis.

```text
1 DEAT
2 DATE 1930
2 _STATUS record
2 _EVID original primary direct
```
