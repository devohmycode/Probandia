# Campagne de référence de la 1.0.0

0.9.41 (`f1cb231`) contre la candidate (`f88959f`), au banc réel (sessions `claude -p`, Claude Opus, mode solo, 30 minutes et 7 USD au plus par essai), du 19 au 20 octobre 2026. Notateur : `bench/run.py` de `f3cd9dc`. Verdicts selon T33 : à 3 essais par variante, un écart n'est « hausse » ou « baisse » que s'il sépare toutes les valeurs. Les cas viennent de dossiers de familles réelles : ils sont nommés ici « cas A » et « cas B », et rien de leurs données n'est publié.

- **Cas A** : naissance et parents d'un homme né au début du XIXe siècle, en France ; 5 attendus.
- **Cas B** : naissance et parents d'une femme née à la fin du XVIIIe siècle, en France, connue par son acte de décès ; 5 attendus. Le nom de la mère accepte deux lectures, car le *u* et le *n* se confondent sous la main de l'acte (corrigé élargi le 20 octobre 2026, après la campagne ; la lecture en *r* reste fausse).

Un troisième cas, hors de France, a été retiré : ses actes ne s'ouvrent pas sans connexion, et la date attendue y contredit la table décennale. Il ne mesure pas la recherche, mais la conduite sans accès.

Médianes, et entre parenthèses l'étendue des 3 essais.

## Cas A

| mesure | 0.9.41 | candidate | verdict |
|---|---|---|---|
| attendus dans la réponse | 0,80 (0,00–0,80) | 0,80 (0,00–1,00) | non concluant |
| faits attendus prouvés (notateur) | 2 (2–2) | 2 (0–2) | non concluant |
| fausses promotions | 0 | 0 | — |
| tokens pondérés | 426 498 (0–597 815) | 585 246 (0–587 121) | non concluant (+37 %) |
| appels d'outils | 72 (50–73) | 79 (58–82) | non concluant |
| appels MCP | 0 | 0 | — |
| unités de quota gratuit | 0 | 0 | — |
| coût catalogue (USD) | 1,16 (1,01–1,31) | 1,21 (1,20–1,22) | trop peu d'essais |
| première trouvaille de la passe 1 (s) | 680 (606–1 765) | 844 (662–1 025) | trop peu d'essais |

Un essai de chaque variante n'a rendu aucun attendu dans sa réponse : coupés à 30 minutes ; celui de la candidate n'a pas de mesure (tokens comptés 0). Le second essai de la candidate lit la mère « Gréhault » : une erreur de lecture, vérifiée le 20 octobre 2026 sur les deux actes qu'il a lus, où le point du *i* est net ; le corrigé reste tel quel.

## Cas B

| mesure | 0.9.41 | candidate | verdict |
|---|---|---|---|
| attendus dans la réponse | 1,00 (0,80–1,00) | 1,00 (1,00–1,00) | non concluant |
| faits attendus prouvés, par un acte lu | 2 (2–2) | 2 (2–2) | — |
| fausses promotions | 0 | 0 | — |
| tokens pondérés | 517 777 (503 849–820 223) | 697 616 (538 468–894 497) | non concluant (+35 %) |
| appels d'outils | 63 (63–91) | 89 (72–120) | non concluant |
| sous-agents | 2 (2–2) | 4 (3–7) | hausse |
| appels MCP | 0 | 0 | — |
| unités de quota gratuit | 0 | 0 | — |
| coût catalogue (USD) | 1,15 (1,12–1,84) | 1,48 (1,00–1,91) | non concluant |
| première trouvaille de la passe 1 (s) | 709 (546–1 122) | 832 (642–1 207) | non concluant |

## Face aux conditions de T12

- **Attendus** : cas B à 100 % sur les 3 essais de la candidate ; cas A à 100 % sur 1 essai, 80 % sur 1 (lecture « Gréhault »), rien sur 1 (coupé). Non tenu sur le cas A ; constat accepté le 20 octobre 2026 sans rejouer le cas, la reprise des doutes du lecteur dans la réponse étant à faire (T258).
- **Preuve** : ne recule pas ; 0 fausse promotion dans tous les essais notés.
- **Tokens** (condition révisée le 20 octobre 2026 : pas de hausse significative selon T33) : tenu, +35 % et +37 % en médiane sans verdict de hausse. L'écart va dans le même sens sur les deux cas ; il ne vient pas de la relecture des index (T257 : passe 1 inchangée). Son origine reste à trouver : la candidate lance plus de sous-agents.
- **Appels MCP de fournisseur pendant une passe** : 0 pour la candidate.
- **Payé aux fournisseurs** : 0,00 USD. Le coût catalogue est celui des sessions Claude, sous abonnement.
- **Premières trouvailles (N-8, T149)** : médiane des 5 essais de la candidate qui ont trouvé, 832 s (13,9 minutes), sous 15 minutes ; 2 sur 5 au-delà, et l'essai coupé n'a rien trouvé.

Dépense de la campagne : environ 31 USD au prix catalogue.

## Candidate de l'étiquette — 23 octobre 2026

Six essais de la candidate `a1e4baf` (cas A et B, 3 chacun), mêmes réglages que ci-dessus (Claude Opus, mode solo, mêmes serveurs MCP fixes, 30 minutes et 7 USD au plus par essai) ; notateur `bench/run.py` de `c12f811`. Choix de l'utilisateur : la candidate seule, comparée aux essais de la campagne ci-dessus, joués les 19 et 20 octobre ; les essais ne sont donc pas entrelacés avec ceux de `f88959f` et les écarts ne donnent pas de verdict. Médianes, et entre parenthèses l'étendue des 3 essais.

| mesure | cas A, `f88959f` | cas A, `a1e4baf` | cas B, `f88959f` | cas B, `a1e4baf` |
|---|---|---|---|---|
| attendus dans la réponse | 0,80 (0,00–1,00) | 1,00 (0,80–1,00) | 1,00 (1,00–1,00) | 1,00 (1,00–1,00) |
| faits attendus prouvés (notateur) | 2 (0–2) | 2 (2–2) | 2 (2–2) | 2 (2–2) |
| fausses promotions | 0 | 0 | 0 | 0 |
| tokens pondérés | 585 246 (0–587 121) | 605 036 (590 658–687 972) | 697 616 (538 468–894 497) | 621 035 (580 026–669 339) |
| appels d'outils | 79 (58–82) | 77 (74–100) | 89 (72–120) | 85 (78–88) |
| sous-agents | 3 (3–4) | 3 (3–4) | 4 (3–7) | 3 (3–3) |
| appels MCP | 0 | 0 | 0 | 0 |
| unités de quota gratuit | 0 | 0 | 0 | 0 |
| coût catalogue (USD) | 1,21 (1,20–1,22) | 1,34 (1,18–1,35) | 1,48 (1,00–1,91) | 1,19 (1,17–1,39) |
| première trouvaille de la passe 1 (s) | 844 (662–1 025) | 717 (616–792) | 832 (642–1 207) | 701 (611–779) |

- **Attendus** : cas B à 100 % sur les 3 essais ; cas A à 100 % sur 2 essais, 80 % sur 1, qui lit encore le nom de la mère avec la même erreur que l'essai de la campagne précédente ; aucun essai coupé.
- **Preuve** : 2 faits attendus prouvés par un acte lu dans chacun des 6 essais, 0 fausse promotion, 0 fait sans citation.
- **Appels MCP de fournisseur** : 0 ; **unités de quota gratuit** : 0 ; **payé aux fournisseurs** : 0,00 USD.
- **Premières trouvailles (N-8)** : les 6 essais sous 15 minutes (611 à 792 s), médiane 709 s (11,8 minutes).

Dépense : 7,62 USD au prix catalogue, sous abonnement. Le corpus public (`bench/public/cases/`, 10 cas) se note le même jour avec `bench/run.py --case …` sur chaque solution : tous les attendus passent, et `bench/cases.py check --all` admet les 10 cas.
