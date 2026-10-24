# `_STATUS` — the status of a fact

URI: `https://probandia.replit.app/gedcom/v1/status`

| | |
|---|---|
| Superstructures | any event or attribute structure (`BIRT`, `CHR`, `DEAT`, `BURI`, `MARR`, `RESI`, `OCCU`, `CENS`, `EMIG`, `NATU`, `EVEN`…) |
| Payload | one of `record`, `index`, `hypothesis`, `refuted` |
| Cardinality | `{0:1}` |
| Substructures | none |

- `record`: read on the original record (its image or a transcription of it).
- `index`: taken from an index, a derivative or someone else's transcription.
- `hypothesis`: reasoned, not written in any record.
- `refuted`: shown to be wrong; exported only on request (`--include-refuted`).

It goes with the citation's `QUAY`: `record` 3, `index` 2, `hypothesis` 1.
GEDCOM 5.5.1 exports carry the status in a `NOTE` ("Status: record") instead.

```text
1 BIRT
2 DATE 26 FEB 1802
2 SOUR @S1@
3 QUAY 3
2 _STATUS record
```
