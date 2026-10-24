# `_CONF` — the confidence of a conclusion

URI: `https://probandia.replit.app/gedcom/v1/confidence`

| | |
|---|---|
| Superstructures | any event or attribute structure that concludes a research question |
| Payload | one of `proved`, `probable`, `possible`, `unsupported` |
| Cardinality | `{0:1}` |
| Substructures | none |

Probandia computes it, never takes it from the user: it starts from the
weakest fact of the conclusion, loses a step for indirect evidence (unless a
reviewed argument was accepted), secondary information no second source
confirms, an open objection, an unexplained clash of dates, or a question only
partly conform to the Genealogical Proof Standard; it is at most `possible`
for a question that does not conform, and `proved` needs the record's passage
quoted. A fact that answers several questions carries the lowest.

The citation's `QUAY` follows it when it is lower than the fact's status gives:
`proved` 3, `probable` 2, `possible` 1, `unsupported` 0. GEDCOM 5.5.1 exports
add it to the status `NOTE` ("confidence of the conclusion: probable").

```text
1 BIRT
2 DATE 14 MAR 1870
2 SOUR @S7@
3 QUAY 3
2 _STATUS record
2 _CONF proved
```
