# Sources ouvertes : conditions d'accès

Première vérification le 5 octobre 2026, Mémoire des hommes relue le 17 octobre 2026. « Ouvert » ne signifie pas
que toutes les images sont librement redistribuables. Le catalogue (`catalogues/archives.yaml`) conserve les
conditions et les hôtes ; les portails passent par le navigateur du harnais, avec la session ouverte par
l'utilisateur si nécessaire. Aucun téléchargement massif.

| Source | Accès retenu | Conditions officielles et limites |
|---|---|---|
| DDB | `ddb.search`, API v2 publique | [OpenAPI](https://api.deutsche-digitale-bibliothek.de/2/q/openapi), [recherche](https://deutsche-digitale-bibliothek.atlassian.net/wiki/spaces/DDBDOK/pages/47830749/Search+API). Métadonnées CC0, droits des objets conservés dans `rights`. Le GET public de recherche répond sans clé ; les autres interfaces peuvent exiger une authentification. |
| Matricula | Navigateur | [CGU](https://data.matricula-online.eu/en/nutzungsbedingungen/) : images CC BY-NC-ND 2.0, notification du dépôt en cas de publication. Pas d'API publique documentée vérifiée. |
| Delpher | Navigateur, seulement, pour la 1.0 | [CGU](https://www.delpher.nl/over-delpher/gebruiksvoorwaarden), [accès aux données KB](https://www.kb.nl/en/research-find/datasets/delpher-newspapers). L'accès SRU/OAI nécessite une autorisation préalable de la KB ; aucun point d'accès supposé n'est appelé. Décidé le 13 octobre 2026 : Delpher reste au navigateur pour la 1.0 ; demander l'accès SRU/OAI à la KB est renvoyé après la 1.0. |
| Mémoire des hommes | Navigateur (relu le 17 octobre 2026) | [CGU](https://www.memoiredeshommes.defense.gouv.fr/cgu) « en vigueur au 17 octobre 2026 », lues directement ce jour-là : usage strictement privé ; toute reproduction, publication ou copie demande l'autorisation préalable du site, avec l'auteur et la source cités ; tout usage commercial ou publicitaire est interdit. [Droits de consultation](https://www.memoiredeshommes.defense.gouv.fr/droits-de-consultation) : la réutilisation commerciale de la base et des dossiers des fusillés de la Première Guerre mondiale est proscrite. Aucune API ni accès automatisé n'est documenté : l'accès reste le navigateur. |
| Léonore | Navigateur | [Portail](https://www.leonore.archives-nationales.culture.gouv.fr/), [réutilisation aux Archives nationales](https://www.archives-nationales.culture.gouv.fr/quelles-sont-les-modalites-de-reproduction-et-de-reutilisation). Crédit archivistique obligatoire ; exceptions pour droits de tiers et données personnelles. |
| Arolsen | Navigateur | [Notice du portail](https://collections.arolsen-archives.org/en/search/), [conditions](https://arolsen-archives.org/en/materials/terms-of-use/). Données sensibles ; droits à vérifier pour les copies provenant d'autres dépôts. |
| Archives de l'État en Belgique | Navigateur, compte gratuit pour les images | [Aide AGATHA](https://agatha.arch.be/fr/help/). Usage personnel des téléchargements, 100 actes/jour maximum ; une publication peut entraîner une redevance, hors du parcours gratuit de Probandia. |

## Utilisation

Depuis un projet Probandia :

```sh
probandia archive find "Matricula"
probandia archive find "Mémoire des hommes"
probandia archive find "AGATHA"
probandia archive run ddb.search --args '{"query":"Goethe","max":20,"offset":0}'
probandia archive run ddb.witness
```

La recherche DDB fait une seule requête, 1 à 100 résultats, sans pagination automatique. `offset` permet une
page choisie explicitement. Une réponse invalide ou une erreur HTTP échoue ; elle ne vaut jamais un résultat
négatif. Les identifiants et les droits accompagnent les liens vers les notices.

Le témoin DDB est une réponse réelle enregistrée, rejouée sans réseau dans les tests. Les six parcours navigateur
sont testés pour la découverte, les hôtes protégés et la connexion belge ; ces tests ne prétendent pas avoir
exécuté les recherches dans les interfaces de chaque portail. Aucun témoin API fictif n'est déclaré pour ces
parcours. L'ajout d'autres API attend une interface documentée et des conditions permettant cet usage.

`probandia watch` rejoue les témoins des connecteurs et liste les entrées du catalogue vérifiées il y a plus de
90 jours : c'est le signal pour relire ces conditions.
