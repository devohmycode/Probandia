# Who were the parents of Victor Hugo, born about 1802 in Besançon?

## Sommaire

- [I Passe 1 — Acte de naissance](#s-pass-1)
  - [I.1 Le père présumé](#s-01j9zm00000000000000000002)
    - [I.1.1 Détail](#s-01j9zm00000000000000000003)
  - [I.2 Arbre](#s-tree-1)
- [II Passe 2 — Vérifications](#s-pass-2)
  - [II.1 Index](#s-01j9zm00000000000000000007)
  - [II.2 Arbre](#s-tree-2)
- [III Méthode](#s-method)
- [IV Sources](#s-sources)

<a id="s-pass-1"></a>
<a id="s-01j9zm00000000000000000001"></a>

## I Passe 1 — Acte de naissance

Victor : Victor HUGO, naissance, 26 février 1802, Besançon[^1]. Voir [§ I.1](#s-01j9zm00000000000000000002).

&lt;script>alert(1)&lt;/script>

<a id="s-01j9zm00000000000000000002"></a>

### I.1 Le père présumé

Léopold HUGOT : Léopold HUGOT, naissance, vers 1773, Nanzig[^2].

<a id="s-01j9zm00000000000000000003"></a>

#### I.1.1 Détail

Une sous-section.

<a id="s-tree-1"></a>

### I.2 Arbre

```mermaid
flowchart TB
  P_victor_hugo_1802["Victor HUGO<br/>° 1802"]:::record
  P_leopold_hugo_1773["Léopold HUGOT<br/>° 1773"]:::index
  U_1(( )):::union
  P_leopold_hugo_1773 --> U_1
  U_1 --> P_victor_hugo_1802
  classDef record stroke-width:2px
  classDef index stroke-width:1px
  classDef hypothesis stroke-dasharray:5 5
  classDef living fill:#eee,color:#555
  classDef union width:6px,height:6px
```

<a id="s-pass-2"></a>
<a id="s-01j9zm00000000000000000006"></a>

## II Passe 2 — Vérifications

Les index concordent. Personne vivante est citée.

<a id="s-01j9zm00000000000000000007"></a>

### II.1 Index

Une table.

| a | b |
|---|---|
| 1 | 2 |

<a id="s-tree-2"></a>

### II.2 Arbre

```mermaid
flowchart TB
  P_living_1["Personne vivante"]:::living
  classDef record stroke-width:2px
  classDef index stroke-width:1px
  classDef hypothesis stroke-dasharray:5 5
  classDef living fill:#eee,color:#555
  classDef union width:6px,height:6px
```

<a id="s-method"></a>

## III Méthode

Rédigé avec l'aide d'agents d'IA : chaque fait cite sa source, et le moteur vérifie les citations et les règles de preuve ; relire les sources reste le travail du lecteur.

| Passe | Environnement | Agent | Modèle |
|---|---|---|---|
| 1 | claude-code | session |  |
| 2 | claude-code | session | claude-opus-5-5 |

<a id="s-sources"></a>

## IV Sources

- Archives municipales de Besançon, État civil, Besançon, E-1802-N, acte 112, image 45, https://example.org/amb/e-1802-n/45 (consulted on 2026-09-30).
- Open Archives, Index of births, https://example.org/oa/1 (consulted on 2026-09-30).

[^1]: Acte. Archives municipales de Besançon, État civil, Besançon, E-1802-N, acte 112, image 45, https://example.org/amb/e-1802-n/45 (consulted on 2026-09-30).
[^2]: Index. Open Archives, Index of births, https://example.org/oa/1 (consulted on 2026-09-30).
