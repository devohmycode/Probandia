# Performances de la 1.0.0 (PRD N-8) — 17 octobre 2026

Les trois cibles de N-8 : `status` sous 2 s et `verify` sous 10 s pour 500 personnes, premières trouvailles de la passe 1 en moins de 15 minutes. Mesures de la branche `sprint/lot6-perf` (T145 à T149 de `docs/version-1.0.0.md`), machine calme : la mesure attend trois relevés de charge du processeur sous 30 %, et chaque commande est lancée en alternance avec les autres, depuis un processus Python qui chronomètre l'appel entier (`subprocess.run`, temps du mur). Dossiers de réglages et de données propres à la mesure (`PROBANDIA_CONFIG_DIR`, `PROBANDIA_DATA_DIR`) : le compteur de l'utilisateur n'y entre pas.

## La famille de 500 personnes

`python tools/make_big_family.py <dossier> [--persons 500]` copie `tests/sample-project` (30 personnes de la famille inventée `marchand`) et ajoute des copies de ses personnes, chacune avec ses identifiants (`<id>-c<n>`), jusqu'à atteindre le nombre demandé. Les faits des copies citent les sources du projet exemple et appartiennent à sa recherche, que `verify` contrôle donc en entier. Le script écrit les mêmes octets à chaque lancement.

| `--persons` | personnes | faits |
|---:|---:|---:|
| 500 | 510 | 1 071 |
| 541 | 570 | 1 197 |

`verify` rend `FAIL` (V-8 : arbres absents), code 1 : le temps compte, pas le verdict.

## Machines

| | Windows | Linux |
|---|---|---|
| système | Windows 11 Pro 10.0.26300 | Ubuntu 24.04 sous WSL 2 (noyau 6.18.33.2), même machine |
| Python | 3.14.7 | 3.12.3 |
| processeurs logiques | 16 | 12 (attribués à WSL) |
| charge au départ | 12 % | loadavg 0,21 |
| projet | disque NTFS | disque ext4 de WSL (pas `/mnt/c`) |

## Résultats

Médianes de 5 lancements (`status`, `verify`) et de 9 (démarrage), le 17 octobre 2026 à 16 h 27.

| mesure | Windows | Linux | seuil |
|---|---:|---:|---:|
| `status`, 510 personnes | 0,31 s | 0,05 s | 2 s |
| `verify 2026-09-01-ancestors-of-louis-marchand`, 510 personnes | 1,39 s | 1,08 s | 10 s |
| `verify`, 570 personnes | 1,49 s | 1,23 s | 5 s (T147) |
| `python -c pass` | 57 ms | 12 ms | — |
| `run_probandia.py --version` | 193 ms | 23 ms | 250 ms (T145) |
| `run_probandia.py hook guard`, projet exemple | 192 ms | 44 ms | 250 ms (T145) |
| `statusline`, projet exemple, moins `python -c pass` | 59 ms | 9 ms | 100 ms (T146) |

Avant ce sprint (`2435658`, même machine Windows) : `verify` 10,8 s sur 510 personnes, `persons.yaml` y étant lu et validé une vingtaine de fois (T147) ; `--version` 644 ms et `hook guard` 643 ms (T145). Les deux derniers chiffres, mesurés sous un `PYTHONDONTWRITEBYTECODE=1` hérité du harnais, comptaient aussi la compilation de chaque module importé : `run_probandia.py` écrit désormais son cache de bytecode malgré cette variable.

`statusline` donne la ligne gardée dans `.probandia/statusline.json` tant que les fichiers dont elle est lue n'ont pas changé, 30 s au plus : c'est le cas de presque tous ses appels, que Claude Code renouvelle à chaque changement de la conversation. Quand elle doit être relue (un fichier a changé, ou 30 s ont passé), elle coûte ce que coûte une commande ordinaire : environ 190 ms de plus que `python -c pass` sous Windows (mesure sous charge de 57 %).

`status` ne lit pas les index des familles : sa durée ne dépend presque pas du nombre de personnes, mais du registre des quotas, relu une fois par compte avant ce sprint (114 lectures du compteur de l'utilisateur) et une fois par processus depuis (T148).

## Premières trouvailles de la passe 1

`bench-genealogie/analyse.py` (hors dépôt, branche `perf-t149`, `4dc597a`) rend `premiere_trouvaille(projet)` : les secondes entre le `pass.started` de la passe 1 et son premier `fact.asserted`, lues dans les journaux du projet joué ; `banc.py` la range dans chaque mesure (`premiere_trouvaille_s`), dans le relevé et dans le rapport. Elle est testée sur un journal figé (`test_analyse.Analyse.test_premiere_trouvaille`).

Sur les essais déjà joués, relus sans rien relancer : les six essais J8 (12 octobre 2026) donnent 369, 666, 729, 777 et 855 s, et un essai sans aucun fait, comme le relevait T149 (6,2 à 14,2 minutes) ; les trois essais les plus récents du banc (`1f261f6`) donnent 679, 723 et 1 024 s, médiane 723 s (12,1 minutes), dont un au-delà de 15 minutes.

Sur les essais de la candidate dans la campagne de référence (T225, `bench/release-1.0.0.md`, 19 et 20 octobre 2026) : 642, 662, 832, 1 025 et 1 207 s, et un essai coupé à 30 minutes sans fait ; **médiane 832 s (13,9 minutes), sous les 15 minutes de N-8**, mais deux essais sur cinq au-delà : la marge reste mince.

## Repassé sur la candidate — 23 octobre 2026

Mêmes scripts, même machine, sur `master` à `a1e4baf` (copie propre par `git archive`, famille refaite par `tools/make_big_family.py`), machine calme (charge 22 % au départ sous Windows, loadavg 0,00 sous Linux). Médianes de 5 (`status`, `verify`) et de 9 (démarrage).

| mesure | Windows | Linux | seuil |
|---|---:|---:|---:|
| `status`, 510 personnes | 0,47 s | 0,07 s | 2 s |
| `verify 2026-09-01-ancestors-of-louis-marchand`, 510 personnes | 0,91 s | 1,33 s | 10 s |
| `verify`, 570 personnes | 0,98 s | 1,69 s | 5 s (T147) |
| `python -c pass` | 73 ms | 14 ms | — |
| `run_probandia.py --version` | 297 ms | 29 ms | 250 ms (T145) |
| `run_probandia.py hook guard`, projet exemple | 357 ms | 53 ms | 250 ms (T145) |
| `statusline`, projet exemple, moins `python -c pass` | 110 ms | 10 ms | 100 ms (T146) |

`verify` gagne sous Windows le lecteur YAML compilé (T266) ; sous Linux, le Python du système n'a pas le `_yaml` de la version vendue et garde le lecteur pur. Le démarrage sous Windows dépasse les chiffres du 17 octobre sans que le code en soit cause : lancés en alternance au même moment (16 lancements, le premier écarté), `ba45cda` (17 octobre) et `a1e4baf` donnent `hook guard` 244 et 252 ms, `--version` 235 et 224 ms ; c'est la machine qui est plus lente qu'alors. Les deux cibles N-8 de cette page restent tenues de loin ; les cibles de démarrage de T145 et T146 sont à la limite sous Windows, comme le 17 octobre une fois la machine prise en compte.

Premières trouvailles de la passe 1 : non relancées (essais payants) ; la médiane qui fait foi reste celle de T225 ci-dessus, à reprendre si le banc est repassé sur la candidate (critère 18).
