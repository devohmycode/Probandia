# `_NEGA` — a negative search

URI: `https://probandia.replit.app/gedcom/v1/negative`

| | |
|---|---|
| Kind | extension record (`0 @N<n>@ _NEGA`) |
| Payload | `<query> (<engine or archive>, <from>-<to>)` |
| Substructures | none |

A negative search is a search that found nothing where something was looked for:
an archive, a query, a window of years. Probandia records it only with a witness
search that passed on the same source, so "not found" is evidence, not an outage.

```text
0 @N1@ _NEGA Hugo Besançon (openarchives, 1797-1807)
```

GEDCOM 5.5.1 exports write it as a `NOTE` record: `Negative search: …`.
