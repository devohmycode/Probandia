# Probandia

Rien n'est conclu tant que ce n'est pas prouvé.

Un plugin de recherche généalogique pour les agents IA de code. Posez à votre agent une question
sur une famille ; Probandia mène la recherche selon le Genealogical Proof Standard :
il planifie les recherches, lit les archives et le web avec des ressources gratuites seulement,
cite chaque fait sur sa source, et rédige un rapport, un arbre et un export
GEDCOM 7. Le plugin apporte des commandes slash (`/probandia:new`, `/probandia:resume`,
`/probandia:status`…), des skills, sept rôles d'agents, des hooks qui font respecter les règles, et
un serveur MCP (sauf dans Claude Code, Grok Build et Factory Droid, dont les skills
appellent le moteur par le shell) ; la section [Ce que le plugin apporte](#ce-que-le-plugin-apporte)
les liste tous. Son moteur, `run_probandia.py`, ne demande que Python 3.11 ou plus récent.

[English](https://github.com/devohmycode/probandia/blob/master/README.md) · Français · [Guide d'utilisation](https://github.com/devohmycode/probandia/blob/master/guides/guide-utilisation.md).

Sommaire : [Fonctionnement](#fonctionnement) · [Prérequis](#prérequis) ·
[Installer le plugin](#installer-le-plugin) ·
[Installer la commande](#installer-la-commande) ·
[Première recherche](#première-recherche) · [Utiliser la commande](#utiliser-la-commande) ·
[Référence des commandes](#référence-des-commandes) ·
[Ce que le plugin apporte](#ce-que-le-plugin-apporte) ·
[Projets et réglages](#projets-et-réglages) ·
[Modèle et effort de chaque agent](#modèle-et-effort-de-chaque-agent) ·
[Confidentialité et sécurité](#confidentialité-et-sécurité) ·
[Prouver une conclusion](#prouver-une-conclusion--le-genealogical-proof-standard) ·
[Fournisseurs](#fournisseurs) · [L'interface en terminal](#linterface-en-terminal) ·
[Développement](#développement)

## Fonctionnement

Votre agent de code charge le plugin ; ses commandes, ses skills et ses agents appellent le moteur par la
commande `probandia`, ou par son serveur MCP. Le moteur planifie, prouve et vérifie ; il écrit
le projet de recherche, interroge les archives par ses fournisseurs et produit le rapport.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/architecture.fr.dark.svg">
  <img alt="L'agent de code charge le plugin Probandia, qui appelle le moteur de preuve GPS par la CLI ou le serveur MCP ; le moteur lit et écrit le projet, interroge les archives en ligne par ses fournisseurs et rend le rapport." src="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/architecture.fr.light.svg">
</picture>

## Prérequis

- **Systèmes** : Windows et Linux, testés par la CI à chaque modification (Windows avec
  Python 3.11 et 3.14, Ubuntu avec Python 3.11, 3.12, 3.13 et 3.14). macOS :
  non testé.
- **Python 3.11 ou plus récent, appelable sous le nom `python`** : les hooks de Claude Code
  et de Codex prennent `python`, sinon `python3` (sous Windows, `python` seulement ; Claude
  Code les y lance dans Git Bash) ; le serveur MCP et les hooks de Cursor
  et d'Antigravity lancent `python`, sans repli. `probandia doctor` signale l'absence de
  `python`. Sous Debian ou Ubuntu, `sudo apt install
  python-is-python3` donne ce nom ; sous Windows, l'installateur de python.org
  avec « Add python.exe to PATH ».
- **Claude Code sous Windows : Git Bash.** Sans lui, Claude Code lance les hooks
  dans PowerShell, où ils échouent : installez Git for Windows, ou faites pointer
  `CLAUDE_CODE_GIT_BASH_PATH` vers son `bash.exe`. `probandia doctor` signale quand
  il n'en trouve pas (`GIT_BASH=missing`).
- Rien d'autre : le moteur n'utilise que la bibliothèque standard et embarque ses
  quelques dépendances dans `src/probandia/_vendor`.

### Sous Windows, depuis PowerShell

Python et Git for Windows (qui apporte Git Bash), puis fermez et rouvrez
PowerShell pour qu'il relise le `PATH` :

```powershell
winget install -e --id Python.Python.3.14
winget install -e --id Git.Git --source winget
python --version
```

Si `python` ouvre le Microsoft Store, ouvrez *Alias d'exécution d'application*
depuis le menu Démarrer et désactivez les alias de Python. Sans winget, les installateurs de
[python.org](https://www.python.org/downloads/windows/) (cochez « Add python.exe
to PATH ») et de [git-scm.com](https://git-scm.com/install/windows) font de même.

Puis la CLI de votre harness, chacune selon sa propre documentation (lue le 25
octobre 2026) :

| CLI de l'agent | Installation sous Windows (PowerShell) | Documentation |
|---|---|---|
| Claude Code | `irm https://claude.ai/install.ps1 \| iex`, ou `winget install Anthropic.ClaudeCode` | [code.claude.com](https://code.claude.com/docs/en/setup) |
| Codex | `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 \| iex"`, ou `npm install -g @openai/codex` | [github.com/openai/codex](https://github.com/openai/codex) |
| Cursor (CLI) | `irm 'https://cursor.com/install?win32=true' \| iex` | [cursor.com](https://cursor.com/docs/cli/installation) |
| Factory Droid | `irm https://app.factory.ai/cli/windows \| iex` | [github.com/Factory-AI/factory](https://github.com/Factory-AI/factory) |
| Grok Build | `irm https://x.ai/cli/install.ps1 \| iex` | [docs.x.ai](https://docs.x.ai/build/overview) |
| Antigravity | `irm https://antigravity.google/cli/install.ps1 \| iex` | [github.com/google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli) |
| OpenCode | `npm install -g opencode-ai` (d'abord Node.js : `winget install OpenJS.NodeJS.LTS`), ou `scoop install opencode` ; sa documentation conseille WSL sous Windows | [opencode.ai](https://opencode.ai/docs/) |

Outils facultatifs, que `probandia doctor` vérifie sans rien installer lui-même :

| Outil | Pour quoi faire | Installation |
|---|---|---|
| Playwright | un navigateur sans interface, pour les pages qui en exigent un, quand votre agent ne pilote aucun de vos navigateurs (voir [Archives derrière une connexion](#archives-derrière-une-connexion)) | `python -m pip install playwright && python -m playwright install chromium` |
| Tesseract | OCR des actes imprimés (`transcribe ocr`) | Windows : `winget install UB-Mannheim.TesseractOCR` ou `scoop install tesseract` ; Linux : `sudo apt install tesseract-ocr tesseract-ocr-fra` ; macOS : `brew install tesseract tesseract-lang` |
| Pillow | planches de vues, recadrages et rotations d'images (`image`) | `python -m pip install "Pillow>=12,<13"`, ou l'extra `images` (ci-dessous) |

## Installer le plugin

Le dépôt, `https://github.com/devohmycode/probandia`, est à la fois le plugin
et sa marketplace. Claude Code, Grok Build et Factory Droid l'installent
directement depuis GitHub. Codex, Antigravity, OpenCode et Claude Desktop l'installent
depuis un clone, dont le dossier est `<path>` ci-dessous :

```sh
git clone https://github.com/devohmycode/probandia
cd probandia
```

Sous Windows, clonez-le dans un dossier court (`C:\Users\<you>\probandia`, pas un
dossier profond) : quelques fichiers de `bench/` ont des chemins de 163 caractères, et Windows
refuse les chemins de plus de 260.

| Harness | Prise en charge | Serveur MCP | Installation |
|---|---|---|---|
| Claude Code (terminal, IDE, application de bureau) | complète | non : ses skills appellent le moteur par le shell | `/plugin marketplace add devohmycode/probandia` |
| Grok Build | complète | non : il lit `.claude-plugin/` | `grok plugin install devohmycode/probandia --trust` |
| Codex | complète | oui (`mcp.json`) | `codex plugin marketplace add <path>`, puis `install --harness codex` (plugin et sept agents) |
| Cursor | complète | oui (`cursor/mcp.json`) | `git clone` dans `~/.cursor/plugins/local/probandia` |
| Factory Droid | complète | non : la racine du plugin n'est pas développée dans ses réglages MCP | `droid plugin marketplace add https://github.com/devohmycode/probandia` |
| Antigravity | bêta | oui (`mcp_config.json`) | `agy plugin install <path>` |
| OpenCode | réduite | oui, fusionné dans `opencode.json` | `install --harness opencode` |
| Claude Desktop (chat) | serveur MCP seulement | oui, la seule partie | `claude_desktop_config.json` |

Chaque section indique quand, et avec quelle version, elle a été rejouée.
Toutes les voies lancent le moteur depuis le dossier du dépôt : laissez-le où il est,
et mettez-le à jour (`git pull`) avant de mettre à jour le plugin.

### Claude Code

Prise en charge complète, sans le serveur MCP. Vérifié le 21 octobre 2026 avec Claude Code 2.1.304 et 2.1.306, dans une
configuration à part (`CLAUDE_CONFIG_DIR`) : installation depuis le dossier du
dépôt, une recherche menée jusqu'au bout, mise à jour et désinstallation, qui laisse
`"enabledPlugins": {}` et la copie du plugin par Claude Code dans son cache ;
le serveur MCP seul a été listé connecté, puis retiré. Vérifié le 24 octobre
2026 avec Claude Code 2.1.306, depuis GitHub : marketplace ajoutée, plugin
installé (1.0.0) et activé, marketplace mise à jour, puis les deux retirés. Dans une
session (ou les mêmes mots après `claude plugin` dans un terminal) :

Installation, depuis GitHub :

```text
/plugin marketplace add devohmycode/probandia
/plugin install probandia@probandia
```

Depuis un clone, la première ligne est `/plugin marketplace add <path>`.

Mise à jour :

```text
/plugin marketplace update probandia
/plugin update probandia@probandia
```

Désinstallation :

```text
/plugin uninstall probandia@probandia
/plugin marketplace remove probandia
```

Lancer une recherche :

```text
/probandia:new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

`claude --plugin-dir <path>` charge le dossier pour une session, sans
l'installer.

Le serveur MCP seul, sans le plugin : les 17 outils du moteur
dans Claude Code, sans les commandes slash, les skills, les agents ni les hooks. Déclarez-le
depuis le dossier du projet :

```sh
claude mcp add probandia -- python <path>/run_probandia.py mcp
```

Sans le dépôt, depuis PyPI :
`claude mcp add probandia -- uvx probandia mcp` (sous Windows, `cmd /c uvx`
au lieu de `uvx`). `claude mcp remove probandia` le retire.

### Grok Build

Prise en charge complète, sans le serveur MCP : Grok Build lit la disposition de Claude Code
(`.claude-plugin/`). Ses options de plugin (`/config`) sont ignorées : les réglages viennent
des fichiers (voir [Projets et réglages](#projets-et-réglages)).
Vérifié le 17 octobre 2026 avec Grok Build 1.0.62 : installation depuis le
dossier du dépôt, `doctor` lancé dans le harness le nomme, la commande d'état
répond `STATUS=OK`, et la désinstallation laisse ses fichiers de configuration tels
qu'ils étaient.

Installation, depuis GitHub (`grok plugin install` prend une URL git, `user/repo` ou un
chemin local) :

```sh
grok plugin install devohmycode/probandia --trust
```

Depuis un clone : `grok plugin install <path> --trust`.

Mise à jour : installé depuis GitHub, cette commande récupère la nouvelle version. Un chemin
local est installé sous forme de lien : `git pull` dans `<path>` suffit, et la même
commande le dit :

```sh
grok plugin update probandia
```

Désinstallation :

```sh
grok plugin uninstall probandia
```

Lancer une recherche (la forme de `/probandia:status`, vérifiée) :

```text
/probandia:new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Codex

Prise en charge complète, avec le serveur MCP. Les plugins Codex contiennent des skills mais pas de sous-agents :
l'installateur écrit donc aussi les sept rôles comme agents personnalisés. Lancez-le depuis le dossier de votre
projet de recherche (ou passez `--path <project-folder>`).
Vérifié le 17 octobre 2026 avec Codex 0.161.0 : installation depuis le dossier du
dépôt, `doctor` lancé dans le harness le nomme, la commande d'état répond
`STATUS=OK`, et la désinstallation laisse ses fichiers de configuration tels qu'ils étaient.
Vérifié le 21 octobre 2026 avec Codex 0.161.0, dans un nouveau projet : la
marketplace ajoutée comme ci-dessous est listée, le plugin est installé et activé, l'agent
reader démarre, et le contradictor lance le moteur dans son bac à sable
en lecture seule.

Installation : ajoutez le dépôt comme marketplace (Codex n'en lit aucune dans les
réglages d'un projet), écrivez les agents, puis ajoutez le plugin, depuis le dossier du projet :

```sh
codex plugin marketplace add <path>
python <path>/run_probandia.py install --harness codex
codex plugin add probandia@probandia
```

La première commande écrit la marketplace dans vos réglages Codex
(`~/.codex/config.toml`) ; l'installateur active le plugin dans le
`.codex/config.toml` du projet et écrit les sept agents personnalisés sous la forme
`.codex/agents/probandia-<role>.toml`. Les réglages Codex existants sont conservés. Rouvrez Codex dans ce dossier, accordez votre confiance au projet, et ouvrez une
nouvelle conversation ; approuvez les hooks du plugin dans `/hooks` si Codex le demande. Les agents utilisent
le format TOML de Codex (`name`, `description`, `developer_instructions`,
`model_reasoning_effort`), héritent de votre modèle sauf si vous en avez choisi un (voir
[Modèle et effort de chaque agent](#modèle-et-effort-de-chaque-agent)), et placent le
contradictor en `sandbox_mode = "read-only"`. Voir le
[format des agents personnalisés](https://learn.chatgpt.com/docs/agent-configuration/subagents)
et la [configuration des plugins de projet](https://developers.openai.com/plugins/build/plugins) officiels.
Si vous avez déjà installé le plugin par la marketplace de Codex,
`install --harness codex-agents` n'installe que les rôles.

Mise à jour : `git pull` dans `<path>`, puis de nouveau la même commande, qui
réécrit les agents :

```sh
python <path>/run_probandia.py install --harness codex
```

Désinstallation : `codex plugin remove` retire le plugin de `~/.codex/config.toml`
et du cache de Codex, `--uninstall` supprime ce que l'installateur a écrit, et la
dernière commande retire la marketplace de vos réglages :

```sh
codex plugin remove probandia@probandia
python <path>/run_probandia.py install --harness codex --uninstall
codex plugin marketplace remove probandia
```

Lancer une recherche (la même demande pour `status`, vérifiée) : le plugin Codex
apporte des skills, pas de commandes
slash ; demandez dans la conversation, et la skill `engine` lance `new` :

```text
Start a Probandia research: who were the parents of Victor Hugo, born in 1802 in Besançon?
```

### Cursor

Prise en charge complète, avec le serveur MCP (`cursor/mcp.json`). Cursor charge un plugin
local depuis `~/.cursor/plugins/local/<name>`, un dossier qui lui est propre : il refuse
un lien vers un dossier situé ailleurs (« symlink target … is outside »). Redémarrez ensuite
Cursor, ou lancez « Developer: Reload Window » (sur les offres Teams et Enterprise, un administrateur
doit autoriser l'import de plugins locaux). `cursor-agent --plugin-dir <path>` charge le
dossier le temps d'une session.
Cursor n'affiche les commandes d'un plugin que si son option pour les plugins, skills et autres
configurations tiers est activée. Avec cette option, il importe aussi
les plugins de Claude Code : si Probandia y est aussi installé, désactivez-le
dans Claude Code (`claude plugin disable probandia@probandia`), sinon Cursor affiche
cette copie (ses commandes sans préfixe, `/status`) au lieu de celle-ci.
Vérifié le 22 octobre 2026 avec Cursor 3.27.6 (l'éditeur) : installé sous forme de
clone, Cursor le liste comme plugin local (0.9.41) avec ses 19 commandes, et
`/probandia-status` est proposé dans le chat ; le 21 octobre 2026, avec Cursor
3.26.13, le serveur MCP a listé ses 17 outils et `dates` a répondu, `doctor`
a nommé Cursor, et un fork y a laissé l'original intact.

Installation, par un clone du dépôt :

```sh
git clone https://github.com/devohmycode/probandia ~/.cursor/plugins/local/probandia
```

```powershell
git clone https://github.com/devohmycode/probandia "$HOME\.cursor\plugins\local\probandia"
```

Mise à jour : `git pull` dans le clone, puis rechargez la fenêtre :

```sh
git -C ~/.cursor/plugins/local/probandia pull
```

Désinstallation : supprimez le clone :

```sh
rm -rf ~/.cursor/plugins/local/probandia
```

```powershell
Remove-Item -Recurse -Force "$HOME\.cursor\plugins\local\probandia"
```

Lancer une recherche. Cursor nomme les commandes d'un plugin sans préfixe, aussi
celles de Probandia en portent un (`cursor/commands/`), pour les distinguer de celles de Cursor et des
autres plugins (`/probandia-status`, `/probandia-resume`…) :

```text
/probandia-new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Factory Droid

Prise en charge complète, sans le serveur MCP : la racine du plugin n'est pas développée dans
les réglages MCP de Droid, donc les skills appellent le moteur par le shell. Droid
lit la marketplace du dépôt (`.claude-plugin/marketplace.json`) et
lui donne le nom du dossier : pour un dossier qui ne s'appelle pas `probandia`, écrivez
`probandia@<folder-name>` et `marketplace remove <folder-name>` ci-dessous.
Vérifié le 17 octobre 2026 avec Factory Droid 0.242.0 : installation depuis le
dossier du dépôt, `doctor` lancé dans le harness le nomme, la commande de statut
répond `STATUS=OK`, et la désinstallation retire tout, sauf un
`"enabledPlugins": {}` vide dans `~/.factory/settings.json` et des dossiers vides dans
`~/.factory/plugins/cache/`. La mise à jour a été vérifiée le 21 octobre 2026 avec Factory
Droid 0.245.1.

Installation, depuis GitHub :

```sh
droid plugin marketplace add https://github.com/devohmycode/probandia
droid plugin install probandia@probandia --scope user
```

Depuis un clone : `droid plugin marketplace add <path>`.

Mise à jour :

```sh
droid plugin marketplace update probandia
droid plugin update probandia@probandia --scope user
```

Désinstallation :

```sh
droid plugin uninstall probandia@probandia --scope user
droid plugin marketplace remove probandia
```

Lancer une recherche (vérifié le 21 octobre 2026 : demandée en toutes lettres, elle exécute le
fichier de commande ; `droid exec` ne développe pas les commandes slash), selon le nom que Droid donne à un fichier de commande
(`commands/new.md` devient `/new`). Droid lit les commandes d'un plugin dans son
seul dossier `commands/`, partagé avec Claude Code : elles gardent leurs noms courts
(`/new`, `/status`, `/resume`…), qu'une commande propre à Droid ou à un autre
plugin peut prendre en premier ; demandez alors en toutes lettres (« lance le statut de Probandia »). Sinon :

```text
/new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Antigravity

Prise en charge bêta, avec le serveur MCP, déclaré dans `mcp_config.json` (le
`plugin.json` racine n'en déclare aucun). Antigravity démarre le serveur dans le dossier du
plugin : le serveur demande alors ses racines au client (MCP `roots/list`) et
travaille dans la première qui contient un projet.
Vérifié le 17 octobre 2026 avec Antigravity 1.4.0 : installation depuis le
dossier du dépôt, `doctor` lancé dans le harness le nomme, la commande de statut
répond `STATUS=OK`, et la désinstallation laisse ses fichiers de configuration tels
qu'ils étaient. Son installation indiquait « agents: skipped (not found) » : depuis le 23 octobre 2026
(agy 1.4.6), `agy plugin validate .` compte les sept agents de `agents/`, qui
prennent le modèle de la session.

Installation :

```sh
agy plugin install <path>
```

Mise à jour : `git pull` dans `<path>`, puis réinstallez :

```sh
agy plugin install <path>
```

Désinstallation :

```sh
agy plugin uninstall probandia
```

Lancer une recherche (la forme de `/status`, vérifiée) :

```text
/new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### OpenCode

Prise en charge réduite, avec le serveur MCP. OpenCode n'a pas de format de paquet : l'installateur
copie les skills, les agents et les commandes (sous la forme
`probandia-<name>.md`), fusionne le serveur MCP dans `opencode.json` (en gardant une
copie `.bak`) et ajoute un petit plugin JS pour les hooks.
Vérifié le 17 octobre 2026 avec OpenCode 1.18.29 : installation depuis le
dossier du dépôt, `doctor` lancé dans le harness le nomme, la commande de statut
répond `STATUS=OK`, et la désinstallation laisse ses fichiers de configuration tels
qu'ils étaient (`--scope user` ; les skills vont dans `~/.agents/skills/`).

Installation, pour votre utilisateur ou pour le projet courant :

```sh
python <path>/run_probandia.py install --harness opencode
python <path>/run_probandia.py install --harness opencode --scope project
```

Mise à jour : `git pull` dans `<path>`, puis la même commande :

```sh
python <path>/run_probandia.py install --harness opencode
```

Désinstallation, avec le même `--scope` qu'à l'installation :

```sh
python <path>/run_probandia.py install --harness opencode --uninstall
```

Lancer une recherche (la forme de `/probandia-status`, vérifiée) :

```text
/probandia-new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Claude Desktop

Le serveur MCP seulement : Claude Desktop (le chat, pas Claude Code) exécute des serveurs
MCP mais aucun plugin. Il reçoit les outils du moteur (recherche, lecture, ce qui est
connu, vérification…) sans les commandes slash, les skills, les agents ni les hooks. Vérifié le
21 octobre 2026 : ajouté à `claude_desktop_config.json`, son outil `dates`
répond dans un chat ; retiré, après un redémarrage.

Installation : ajoutez le serveur à `claude_desktop_config.json`
(Settings › Developer › Edit Config), avec le dossier de projet où il travaille, puis
redémarrez Claude Desktop :

```json
{
  "mcpServers": {
    "probandia": {
      "command": "python",
      "args": ["<path>/run_probandia.py", "mcp"],
      "env": {"PROBANDIA_PROJECT": "<the folder that holds probandia.toml>"}
    }
  }
}
```

Mise à jour : `git pull` dans `<path>`, puis redémarrez Claude Desktop :

```sh
git -C <path> pull
```

Désinstallation : retirez l'entrée `"probandia"` de `mcpServers`,
puis redémarrez Claude Desktop :

```json
{
  "mcpServers": {}
}
```

Lancer une recherche : outils MCP seulement. Demandez dans le chat ; Claude appelle les outils
[du serveur MCP](#ce-que-le-plugin-apporte) (`plan`, `search`, `read`, `propose`,
`verify`…) dans le projet de `PROBANDIA_PROJECT`.

### Ce que fait `--uninstall`

Chaque `install --harness` enregistre ce qu'il a écrit, dans `.probandia-install.json`
(dans `.codex/` pour Codex ; dans le dossier de configuration d'OpenCode, ou celui du projet,
pour OpenCode). `--uninstall` lit cet enregistrement et :

- supprime chaque fichier créé par l'installation, même un fichier que vous avez modifié depuis ;
- retire les clés de Probandia des réglages qu'il partage avec vous
  (`.codex/config.toml`, `opencode.json`) et garde toutes les autres clés, même une clé
  ajoutée après l'installation ; si personne n'a modifié ce fichier depuis
  l'installation, il remet la copie `.bak` faite avant elle ;
- supprime les dossiers créés par l'installation, s'ils sont vides.

Les fichiers installés désignent le moteur par son chemin absolu : réinstallez si vous
déplacez le dépôt. `python <path>/run_probandia.py doctor` vérifie le harness,
les clés, Python et les outils facultatifs.

## Installer la commande

Le plugin n'a besoin d'aucune installation : les agents lancent le moteur par
`run_probandia.py`, ou par le lanceur court du projet, `.probandia/pb.py`. Pour taper
vous-même `probandia` dans un terminal, installez la commande de l'une de ces façons
(`<path>` est le dossier du dépôt) :

| Façon | Installation | Mise à jour | Désinstallation |
|---|---|---|---|
| sans installation | `python <path>/run_probandia.py --version` | `git -C <path> pull` | supprimer le dossier |
| `python -m probandia` | `<path>/src` dans `PYTHONPATH` : `PYTHONPATH=<path>/src python -m probandia --version` (PowerShell : `$env:PYTHONPATH = "<path>\src"`), ou l'une des installations ci-dessous | `git -C <path> pull` | supprimer le dossier |
| uv, une copie | `uv tool install <path>` | `uv tool install --force <path>` | `uv tool uninstall probandia` |
| uv, modifiable | `uv tool install --editable <path>` | rien à faire ; après une modification de `pyproject.toml` : `uv tool install --editable --force <path>` | `uv tool uninstall probandia` |
| pipx | `pipx install <path>` | `pipx install --force <path>` | `pipx uninstall probandia` |
| pip, dans un environnement virtuel | `python -m venv .venv`, puis `.venv/bin/python -m pip install <path>` (Windows : `.venv\Scripts\python` ; Debian ou Ubuntu : d'abord `sudo apt install python3-venv`) | `python -m pip install --upgrade <path>` | `python -m pip uninstall probandia` |
| depuis PyPI | `uv tool install probandia`, `pipx install probandia` ou `python -m pip install probandia` ; `uvx probandia` la lance sans l'installer | `uv tool upgrade probandia`, `pipx upgrade probandia`, `python -m pip install --upgrade probandia` | `uv tool uninstall probandia`, `pipx uninstall probandia`, `python -m pip uninstall probandia` |

Ensuite :

```sh
probandia --version
probandia doctor
```

- Si `probandia` est introuvable après une installation par uv, `uv tool update-shell` ajoute
  le dossier des outils de uv au `PATH`.
- La commande installée et le plugin peuvent être de versions différentes. Les skills
  continuent d'appeler le moteur du plugin (`python .probandia/pb.py`, qui mène au
  `run_probandia.py` du plugin) ; la commande ne réécrit jamais le
  `.probandia/pb.py` d'un projet. `--version` donne la version de la commande, `doctor` lancé par
  l'agent celle du plugin.

Les extras ajoutent des dépendances facultatives ; sinon, le moteur ne les importe jamais :

| Extra | À quoi il sert | uv | pipx | pip |
|---|---|---|---|---|
| `tui` | [l'interface en terminal](#linterface-en-terminal) (Textual 8) | `uv tool install --force "<path>[tui]"` ; depuis PyPI : `uv tool install "probandia[tui]"` | `pipx install --force "<path>[tui]"` | `python -m pip install "<path>[tui]"` |
| `images` | Pillow, pour `image` (planches de vues, recadrages, rotations) | `uv tool install --force "<path>[images]"` ; dans le Python du moteur : `uv pip install --python <python> "Pillow>=12,<13"` | `pipx install --force "<path>[images]"` | `python -m pip install "<path>[images]"`, ou `python -m pip install "Pillow>=12,<13"` |
| `dev` | les tests et le lint (jsonschema, Pillow, ruff) | `uv pip install --editable "<path>[dev]"` | pas pour pipx | `python -m pip install --editable ".[dev]"`, depuis le dépôt |

Les extras se combinent : `"<path>[tui,images]"`.

## Première recherche

Une recherche avance par passes. À chaque passe, les agents de terrain cherchent, lisent et proposent ; seul
l'orchestrateur (ou la session elle-même) applique ce qu'ils proposent, puis termine la passe :

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/pass-sequence.fr.dark.svg">
  <img alt="La session ouvre la passe et confie un brief à l'orchestrateur ; à chaque vague, les agents de terrain cherchent, lisent et proposent, le reader transcrit les vues d'un registre ; seul l'orchestrateur applique les propositions puis termine la passe." src="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/pass-sequence.fr.light.svg">
</picture>

Entre deux passes, `resume` ouvre la suivante, et `close` clôt la recherche une fois chaque
question tranchée :

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/research-lifecycle.fr.dark.svg">
  <img alt="Une recherche créée par new enchaîne des passes : la passe ouverte applique ses propositions puis se termine par pass end ; resume ouvre la suivante, une passe coupée se continue ou se clôt, et close ferme la recherche, que resume peut rouvrir." src="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/research-lifecycle.fr.light.svg">
</picture>

1. **Un dossier de projet.** Créez un dossier vide et ouvrez-y votre harness :
   `/probandia:new` en fait un projet (`probandia.toml`) à son premier lancement.
   Dans un terminal, `probandia init` le fait seul, et demande les réglages
   essentiels.
2. **Les clés.** Probandia cherche sur le web avec la recherche web du harness lui-même et
   les offres gratuites [des fournisseurs](#fournisseurs). Sans aucune clé, une recherche
   s'appuie sur la recherche web du harness, les API des archives ouvertes et Jina Reader
   (qui lit les pages sans clé). Chaque clé ajoute une offre gratuite :

   ```sh
   probandia keys                       # d'où vient chaque clé, ou qu'elle manque
   probandia keys signup tavily         # la page où créer le compte gratuit
   probandia keys set TAVILY_API_KEY    # demande la valeur au clavier, l'écrit dans votre .env
   probandia keys check                 # lit, gratuitement, le compte de chaque clé définie
   ```

3. **Lancer une recherche.** Dans votre agent (la forme de la commande pour chaque
   harness est dans [Installer le plugin](#installer-le-plugin)) :

   ```text
   /probandia:new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
   ```

   Elle demande qui mène la recherche : l'agent de la session, un sous-agent ou une équipe.
   Commencez la question par `seul :` (ou `solo:`) pour l'agent de la session seul,
   par `agents :` pour une équipe, ou passez `--mode session|subagent|team`.
4. **Continuer.** Chaque passe se termine par ce qu'elle a trouvé et ce qui reste à faire ;
   `/probandia:resume` lance la passe suivante (`/probandia:resume <research>` pour
   une autre recherche).
5. **Où elle en est.** `/probandia:status`, ou dans un terminal :

   ```sh
   probandia status
   ```

6. **Ce qu'elle écrit**, dans le dossier du projet :
   - le rapport : `families/<family>/research/<research>/report/report.html`
     (et `report.md`, `report.json`, et `views/`, les vues des actes qu'il
     montre) ; `probandia report open` l'ouvre ;
   - l'arbre : `families/<family>/trees/tree.html` (et `tree.md`,
     `ancestors.svg`, `descendants.svg`), écrit par `probandia tree` ;
   - l'export : `exports/<family>-<date>.gdz` (GEDCOM 7 avec ses médias), par
     `probandia export gedcom7`.
7. **Vérifier un fait sur son image.** Une trouvaille ne compte qu'une fois lue
   là où elle est écrite. Ouvrez
   [`examples/hugo/death-1885-paris-16-546.jpg`](https://github.com/devohmycode/probandia/blob/master/examples/hugo/death-1885-paris-16-546.jpg),
   l'acte de décès de Victor Hugo : il est daté du 23 mai 1885 et dit qu'il est mort « hier
   au soir », la veille : **22 mai 1885**. La date d'un décès n'est souvent pas
   celle de son acte. Son acte de naissance donne une date républicaine, que le moteur
   convertit :

   ```sh
   probandia dates "7 ventôse an X"
   ```

   Il répond `ISO=1802-02-26`. Les actes, leurs droits et leur crédit sont dans
   [`examples/hugo/README.md`](https://github.com/devohmycode/probandia/blob/master/examples/hugo/README.md).

### Archives derrière une connexion

Certaines archives (FamilySearch…) ne montrent leurs actes qu'à un utilisateur connecté.
Vous vous connectez vous-même ; l'agent ne tape jamais de mot de passe. Le plus simple est de
laisser l'agent piloter **votre propre navigateur**, où vous vous connectez une fois : rien à
installer dans Probandia, et Playwright n'est pas nécessaire.

| Agent | Votre navigateur, piloté par l'agent | Vos connexions |
|---|---|---|
| Claude Code | [Claude in Chrome](https://code.claude.com/docs/en/chrome) : l'extension Chrome, puis `claude --chrome`, ou `/chrome` dans une session (Chrome ou Edge ; une offre Pro, Max, Team ou Enterprise ; pas sous WSL) | partagées |
| Codex, Factory Droid, Grok Build, OpenCode | [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) avec `--autoConnect` (Chrome 144 ou plus récent, débogage à distance activé dans `chrome://inspect/#remote-debugging`), par exemple `codex mcp add chrome-devtools -- npx chrome-devtools-mcp@latest --autoConnect` (sous Windows, `cmd /c npx` au lieu de `npx`) | partagées : l'agent voit toutes les fenêtres ouvertes de ce Chrome |
| Cursor, Antigravity | leur navigateur intégré | son propre profil : connectez-vous-y |

L'agent s'arrête sur la page de connexion et vous attend. Sinon,
`probandia browser login <archive>` ouvre le navigateur propre au moteur, qui a besoin de
Playwright (voir [Prérequis](#prérequis)).

## Utiliser la commande

Dans un dossier de projet (celui qui contient `probandia.toml`) :

```sh
probandia                       # dans un terminal, l'écran d'accueil : recherches, propositions en attente, quotas les plus bas, étapes suivantes
probandia -u                    # les quotas gratuits, compte par compte (probandia usage)
probandia -s                    # état : familles, recherches, passes ouvertes, verrous
probandia verify 2026-09        # l'identifiant d'une recherche, ou un préfixe qui n'en désigne qu'une
probandia known 2026-09         # ce que la famille sait déjà : faits, négatifs, hypothèses, lacunes
probandia help exit-codes
```

- `new` demande qui mène la recherche, la crée et n'ouvre aucune passe dans un terminal :
  poursuivez dans votre agent avec la commande qu'il affiche (`/probandia:resume <id>`).
- Raccourcis : `-u` (`usage`), `-s` (`status`), `-r` (`report open`). Options
  courtes : `-p <folder>` (un autre projet), `-l fr` (français), `-q`, `-y`
  (`--yes`), `-w` (`--watch`, sur `status` et `usage`), `-V`, `-h`.
- Avant de dépenser un quota gratuit (`search`, `read`, `archive run`) ou d'écrire ce
  qui est difficile à défaire (`apply`, `quota add`, un `export` qui remplace un fichier), la
  commande demande `[y/N]` ; `--yes` répond à votre place. Rien n'est demandé quand personne
  n'est au clavier.
- Complétion par Tab : ajoutez `probandia completion powershell | Out-String | Invoke-Expression`
  à votre profil PowerShell (`$PROFILE`), ou `eval "$(probandia completion bash)"`
  à `~/.bashrc` (aussi `zsh`, `fish`).

### Sortie lisible et contrat

La même commande parle à deux lecteurs. Dans un terminal, sans agent détecté,
elle affiche un écran lisible, en couleur, paginé quand il est long. Redirigée vers un tube ou un fichier,
ou lancée par un agent, elle affiche le contrat que lisent les skills et les agents : un
`KEY=value` par ligne, en commençant par `STATUS=`, 40 lignes au plus.

| À choisir | Comment |
|---|---|
| la forme | `--output-format human\|contract\|json`, ou `PROBANDIA_OUTPUT` ; `--json` vaut `--output-format json` |
| sans couleur | `NO_COLOR=1`, `--no-color` ; `--plain` s'en tient en plus à l'ASCII ; `FORCE_COLOR=1` force la couleur |
| le pager | `PROBANDIA_PAGER` (`none` le désactive) ; sinon `less -R`, ou un pager intégré |
| la langue | `-l fr`, `--lang fr` ou `PROBANDIA_LANGUAGE=fr` ; anglais par défaut |

### Codes de sortie, pour les scripts

| Code | Signification |
|---|---|
| 0 | terminé (`STATUS=OK` ou `WARN`) |
| 1 | échec : une règle de vérification, une proposition refusée |
| 2 | erreur d'usage ou de configuration |
| 3 | une question attend une réponse (`STATUS=ASK`) |
| 4 | arrêté : un quota gratuit ou un plafond atteint, ou vous avez refusé (`STATUS=STOP`) |
| 5 | verrouillé par une autre session |
| 6 | hors d'un projet |
| 7 | erreur de réseau ou de fournisseur |
| 10 | erreur interne ; détails dans le journal |
| 130 | interrompu (Ctrl+C) |

```powershell
probandia verify 2026-09 -q
if ($LASTEXITCODE -eq 1) { "a verification rule failed" }
probandia -u --json > quotas.json
```

```sh
probandia verify 2026-09 -q || echo "exit code: $?"
probandia -u --csv > quotas.csv
```

## Référence des commandes

Les commandes que l'on tape, regroupées comme les montre `probandia --help` ;
`probandia help <command>` et `probandia <command> --help` donnent les
options et les exemples de chacune.

### Recherche

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `new` | crée une recherche et mène sa première passe | `probandia new "Who were the parents of Victor Hugo?" --family hugo --mode session` |
| `resume` | mène la passe suivante d'une recherche | `probandia resume 2026-09` |
| `fork` | copie une recherche à une passe donnée et la poursuit à part | `probandia fork 2026-09 --at 2 --name second-lead` |
| `verify` | confronte une recherche aux règles de preuve | `probandia verify --standard` |
| `question` | les questions d'une recherche : lister, ajouter, modifier, répondre, non résolue, rouvrir | `probandia question list` |
| `matrix` | les types de sources qu'attend chaque question, consultés ou encore à faire ; justifier | `probandia matrix` |
| `fact` | note que vous avez regardé l'acte sur lequel repose un fait | `probandia fact check louis-marchand-1898.birth --by "Marie Durand" --looked "the image of the act"` |
| `close` | clôt une recherche une fois ses questions réglées et `verify` passé | `probandia close` |
| `status` | familles, recherches, passes, verrous, quotas | `probandia status` |
| `board` | où vous en êtes, d'un coup d'œil : la recherche en cours, sa passe, les quotas, les alertes | `probandia board --json` |
| `statusline` | une ligne pour la barre d'état de Claude Code | `probandia statusline` |

### Rapports, arbres, exports et imports

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `report` | le rapport d'une recherche : l'ouvrir dans le navigateur, l'afficher, le produire | `probandia report open` |
| `tree` | écrit l'arbre de la famille (html ou md) | `probandia tree --family marchand --format html` |
| `export` | exporte en GEDCOM 7, GEDCOM 5.5.1 ou Gramps Web | `probandia export gedcom7 --family marchand --living mask` |
| `import` | importe un atelier dans son propre format | `probandia import ../my-workshop --dry-run` |
| `import-gedcom` | importe un fichier GEDCOM dans la zone d'attente | `probandia import-gedcom family.ged --family marchand` |

### Les familles et leur contenu

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `research` | les recherches : lister, afficher, journal, suspendre, clore, rouvrir | `probandia research list` |
| `family` | les familles : lister, afficher | `probandia family show marchand` |
| `find` | trouve une personne dans toutes les familles, avec les variantes d'orthographe | `probandia find Marchand` |
| `person` | la fiche d'une personne : faits et sources, proches, hypothèses, négatifs, lacunes | `probandia person louis-marchand-1898` |
| `searches` | ce qui a déjà été cherché, où, et ce que cela a trouvé | `probandia searches --family marchand` |
| `sources` | les sources des familles, avec leurs citations | `probandia sources --family marchand` |
| `negatives` | les recherches négatives, et s'il faut les refaire | `probandia negatives` |
| `hypotheses` | les hypothèses des familles, ouvertes et closes | `probandia hypotheses` |
| `gaps` | les lacunes des archives : registres perdus ou non filmés | `probandia gaps` |
| `proposals` | les propositions en attente : lister, afficher, appliquer, abandonner | `probandia proposals list` |

### Quotas gratuits

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `usage` | les offres gratuites compte par compte : ce qui reste, ce qu'elles permettent, quand elles repartent | `probandia usage --sync` |
| `quota` | afficher, synchroniser, ajouter ou estimer la consommation des offres gratuites | `probandia quota show` |
| `cache` | ce que contient et économise le cache des réponses : statistiques, vidage | `probandia cache stats` |

### Réglages et vérifications

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `init` | crée un projet ici ; dans un terminal, demande ses réglages essentiels | `probandia init` |
| `config` | les réglages : show, explain, set, unset, init, validate, path, wizard, edit, grade, diff, roles, theme | `probandia config show --origin` |
| `keys` | les clés d'API : lister leur provenance, vérifier, définir, retirer, s'inscrire | `probandia keys` |
| `providers` | le catalogue des offres gratuites : lister, afficher, périmés, activer, désactiver | `probandia providers show serper` |
| `watch` | rejoue les témoins des archives et liste les entrées périmées du catalogue | `probandia watch` |
| `doctor` | vérifie le harness, les clés, Python et les outils facultatifs | `probandia doctor` |
| `library` | les scripts et agents appris : find, save, test, trust, list, show, run, promote, demote, draft, install, uninstall, export, import | `probandia library list` |
| `memory` | les décisions gardées dans `AGENTS.md` : add, list, remove, sync | `probandia memory list` |
| `template` | les modèles de rapport : list, show, check, import, export, use, designer | `probandia template list` |
| `browser` | ouvre le navigateur local pour que vous vous connectiez à une archive | `probandia browser login familysearch` |

### Outils du généalogiste

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `dates` | analyse et convertit les dates généalogiques | `probandia dates "7 ventôse an X"` |
| `variants` | variantes d'orthographe d'un nom de famille | `probandia variants Marchand --paleo` |
| `places` | noms de lieux historiques | `probandia places "Besançon" --as-of 1802` |
| `cite` | phrase de citation d'une source | `probandia cite src-01JA0000000000000000000001 --family marchand` |

### Aide

| Commande | Ce qu'elle fait | Exemple |
|---|---|---|
| `help` | pages courtes : quotas, négatifs, niveaux, codes de sortie, fichiers du projet | `probandia help grades` |
| `completion` | le script de complétion par Tab d'un shell | `probandia completion bash` |
| `tui` | l'application dans un terminal : ses écrans, la palette et la console | `probandia tui` |

Les autres commandes (`plan`, `search`, `read`, `propose`, `apply`, `pass`…) sont
celles du moteur, appelées par les skills, les agents et le serveur MCP ; elles sont
marquées `[engine]` dans `probandia --help --all`.

## Ce que le plugin apporte

**Commandes slash** (`commands/`), sous la forme `/probandia:<name>` dans Claude Code :
`new`, `resume`, `status`, `verify`, `close`, `fork`, `question`, `matrix`,
`config`, `doctor`, `quota`, `memory`, `library`, `template`, `tree`,
`export`, `import`, `import-gedcom`, `watch`. Chacune lance la commande du moteur
du même nom avec vos arguments.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/agents.fr.dark.svg">
  <img alt="La session confie la passe à l'orchestrateur, qui répartit le travail entre trois groupes : chercher (researcher, investigator, searcher), lire et extraire (reader, harvester) et contester (contradictor) ; seuls l'orchestrateur et la session appliquent les propositions." src="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/agents.fr.light.svg">
</picture>

**Agents** (`agents/` ; `droids/` et `cursor/agents/` en gardent les copies pour
Factory Droid et Cursor) :

| Agent | Rôle |
|---|---|
| `orchestrator` | mène une passe de recherche en mode équipe ou sous-agent ; applique les propositions |
| `researcher` | une tâche fermée (une archive, une question, une période) ; propose, n'applique jamais |
| `searcher` | lance et consigne les recherches web qu'on lui confie, rien d'autre |
| `reader` | trouve l'acte dans les vues d'un registre et le transcrit, doutes signalés |
| `investigator` | le cas difficile de la vague : un négatif, des homonymes, un acte abîmé |
| `contradictor` | argumente contre une conclusion, en lecture seule |
| `harvester` | une tâche mécanique (paginer, trier, compter) : pas de web, pas de jugement |

**Skills** (`skills/`) : `engine` (lancer une commande du moteur et lire sa réponse),
`research` (la méthode d'une passe), `ask` (un `STATUS=ASK`), `browser` (une archive
qui demande une connexion), `config` (les réglages par niveau), `report` (rédiger le
rapport), `team` (les messages entre coéquipiers), `transcribe` (lire un acte
sur son image).

**Serveur MCP** (`run_probandia.py mcp`), là où le harness le lance : `dates`,
`export`, `find_operation`, `known`, `library_find`, `places`, `plan`,
`propose`, `question`, `quota`, `read`, `render`, `run_operation`, `search`,
`tree`, `variants`, `verify`.

**Hooks** (`hooks/hooks.json`, et leurs copies pour chaque harness) : le garde
avant chaque appel d'outil (règles G-n), le journal après, et le résumé d'état sur
`/probandia:resume`.

## Projets et réglages

Un projet est un dossier qui contient `probandia.toml`. `probandia init` en crée un
ici (et demande ses réglages essentiels dans un terminal) ; `/probandia:new` en crée
un quand il est lancé dans un dossier qui n'est pas encore un projet.

Les réglages fusionnent sept couches, la plus haute l'emportant : les valeurs par défaut ; les options
du plugin dans le harness ; votre fichier utilisateur (`config.toml` : `%APPDATA%\probandia\` sous
Windows, `$XDG_CONFIG_HOME/probandia/` ou `~/.config/probandia/` ailleurs,
`PROBANDIA_CONFIG_DIR` remplace le dossier) ; le `probandia.toml` du projet ;
`probandia.local.toml` (non versionné) ; les variables `PROBANDIA_*` ; les options
de la commande. `probandia config path` liste les fichiers des sept couches et ceux qui
existent.

Les réglages se répartissent en trois niveaux : `essential` (les quelques-uns que la plupart changent, par
défaut), `advanced` (une vingtaine de plus) et `expert` (tous). `config show`
liste ceux de votre niveau ; un réglage au-dessus de votre niveau garde sa valeur par défaut.

| Action | Ce qu'elle fait | Exemple |
|---|---|---|
| `show` | les réglages en vigueur | `probandia config show --origin` |
| `explain` | un réglage : ses valeurs, sa valeur par défaut, son niveau | `probandia config explain report.mode` |
| `set` | écrit un réglage (le fichier du projet ; `--user`, `--local`) | `probandia config set search.max_parallel 5` |
| `unset` | retire un réglage d'un fichier | `probandia config unset search.max_parallel` |
| `init` | crée `probandia.toml` | `probandia config init --grade advanced` |
| `validate` | vérifie chaque couche | `probandia config validate` |
| `path` | les fichiers des sept couches, et ceux qui existent | `probandia config path` |
| `wizard` | les réglages essentiels, demandés au clavier | `probandia config wizard` |
| `edit` | ouvre un fichier de réglages dans un éditeur, puis le vérifie | `probandia config edit --user` |
| `grade` | change le niveau, et montre les réglages qu'il affiche | `probandia config grade advanced` |
| `diff` | ce qui diffère des valeurs par défaut, couche par couche | `probandia config diff` |
| `roles` | le modèle et l'effort de chaque rôle d'agent | `probandia config roles` |
| `theme` | les thèmes de `probandia tui` : lister, enregistrer ou supprimer l'un des vôtres | `probandia config theme list` |

Les options du plugin dans Claude Code (demandées à l'installation, modifiables dans `/plugin`) :

| Option | Valeurs |
|---|---|
| `language` | `auto` (par défaut), ou un code de langue comme `en` ou `fr` : la langue du rapport |
| `run_mode` | qui mène une recherche : `ask` (par défaut), `session`, `subagent` ou `team` |

## Modèle et effort de chaque agent

Chaque rôle d'agent (`orchestrator`, `researcher`, `searcher`, `reader`,
`investigator`, `contradictor`, `harvester`) tourne avec le modèle et l'effort
de son en-tête dans `.claude-plugin/agents/<role>.md` (généré à partir de `agents/<role>.md`,
que lit Antigravity et qui n'en contient aucun), sauf si vous en choisissez d'autres :

```sh
probandia config set roles.reader.model opus
probandia config set roles.searcher.effort medium
probandia config roles
```

- Clés : `roles.<role>.model`, `roles.<role>.effort` (`low`, `medium`, `high`,
  `xhigh`, `max`), et `roles.<role>.models`, une liste d'éléments `harness:model`
  pour un harness dont les modèles portent d'autres noms (`cursor:claude-opus-5`).
- Couches, telles que les montre `config roles` : l'en-tête de l'agent (`default`), puis
  votre fichier utilisateur, le `probandia.toml` du projet, `probandia.local.toml`, les
  variables `PROBANDIA_ROLES_<ROLE>_MODEL` et `PROBANDIA_ROLES_<ROLE>_EFFORT`
  (`PROBANDIA_ROLES_READER_MODEL=opus`) ; pour l'orchestrateur, les options `--model`
  et `--effort` propres à une recherche viennent en dernier. Les anciennes clés `run.*` (orchestrateur) et
  `search.*` (searcher) comptent quand la clé propre au rôle n'est pas définie.
- Où cela s'applique : dans Claude Code, le garde les fixe à chaque lancement d'un
  agent Probandia ; pour Codex, `install --harness codex` les écrit dans
  `.codex/agents/` (réinstaller après un changement) ; l'installation d'OpenCode les écrit
  aussi ; pour Cursor, Factory Droid et Grok Build, le hook de session écrit une
  copie de chaque agent choisi dans le projet (`.cursor/agents/`,
  `.factory/droids/`, `.grok/agents/`). Un modèle sous une forme que le harness n'accepte pas
  est laissé de côté, et l'installation le signale. Antigravity : non appliqué.
- Dans Claude Code, les variables `CLAUDE_CODE_EFFORT_LEVEL` (un seul effort pour tous
  les agents) et `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (un seul modèle pour tous les agents)
  priment sur ces choix ; `doctor` avertit quand l'une d'elles est définie.
- Le choix est libre ; `config roles` avertit quand le `reader` descend sous sa
  valeur par défaut, car c'est sa lecture des actes qui porte la preuve.

## Confidentialité et sécurité

- **Personnes présumées vivantes.** Une personne née il y a moins de `privacy.living_years`
  ans (100 par défaut) sans décès connu est présumée vivante. Les exports la masquent
  par défaut (`export --living mask` : écrite `Living`, sans événements) ;
  `--living exclude` l'omet. Le moteur n'envoie jamais le nom d'une personne présumée
  vivante à un fournisseur qui réutilise ce qu'on lui envoie, et la mémoire n'en
  garde jamais.
- **Les fournisseurs qui réutilisent le contenu qu'on leur envoie** (`content_reuse` dans le
  catalogue : Gemini grounding, Exa, Parallel, Tavily, Linkup et ScrapeGraphAI,
  dont les conditions les autorisent à s'en servir pour l'entraînement) ne sont pas appelés sauf si vous mettez
  `providers.allow_content_reuse` à `true` (`false` par défaut) ; même alors,
  jamais avec une personne présumée vivante.
- **Les clés** sont rangées dans un fichier `.env` : le vôtre (à côté de votre `config.toml`, par
  défaut) ou celui du projet (à côté de `probandia.toml`, `keys set --in-project`).
  `keys set` demande la clé au clavier sans l'afficher et écrit le fichier lisible
  par son seul propriétaire (mode 600 ; sous Windows, où ce mode ne s'applique pas, le
  fichier garde les droits d'accès de son dossier). Une clé n'est jamais affichée, et la
  mémoire en refuse.
- **Les scripts appris** (la bibliothèque) tournent dans un processus enfant, leur réseau
  réduit aux hôtes qu'ils déclarent et leur environnement aux variables qu'ils
  déclarent ; ce qui permettrait de contourner cela (un autre processus, une socket brute, du code natif,
  `exec`) est refusé avant que le script soit gardé ou lancé. Le système de fichiers
  n'est pas isolé : un script tourne en votre nom, dans le dossier du projet. N'accordez votre confiance à un script
  (`library trust`) qu'après l'avoir lu.

## Prouver une conclusion : le Genealogical Proof Standard

Probandia suit les cinq éléments du Genealogical Proof Standard du
Board for Certification of Genealogists : une recherche raisonnablement exhaustive,
des citations complètes et exactes, l'analyse et la corrélation, les preuves
contradictoires résolues, une conclusion solidement raisonnée. Chaque recherche contient ses
questions (`question`) ; `places guide`, `matrix`, `cite`, `correlate` et
`proof` construisent chaque élément, les règles V-14 à V-18 de `verify` les vérifient, et
`close` clôt la recherche.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/gps-proof.fr.dark.svg">
  <img alt="Pour chacun des cinq éléments du Genealogical Proof Standard, les commandes de Probandia qui le construisent, les données qu'elles produisent et la règle de verify qui le contrôle." src="https://raw.githubusercontent.com/devohmycode/probandia/master/guides/diagrams/gps-proof.fr.light.svg">
</picture>

`probandia verify <research> --standard` montre, pour chaque question, les cinq
éléments, établis, partiels ou manquants, et ce qui manque à chacun ; le rapport
ouvre chaque question par le même encadré. Mettez `proof.standard` à `strict`, et une
question non conforme garde la recherche ouverte.

Chaque fait peut citer le passage exact qu'il lit : des lignes d'une transcription
(`transcribe quote <source> --lines 3-5`) ou un passage d'une page
(`read <url> --quote 2`). `apply` refuse un passage introuvable mot pour mot,
la règle V-19 le vérifie de nouveau à chaque `verify`, et le rapport le cite dans la
note du fait. Une page n'est gardée dans le `evidence/pages/` de la famille que si son
site est une archive du catalogue dont les images sont libres ; toute autre reste dans le
`work/` de la recherche, sur cet ordinateur.

Chaque question répondue reçoit une confiance, calculée et jamais déclarée, sur les
quatre niveaux du `QUAY` de GEDCOM : prouvée, probable, possible, non étayée. Elle
part du fait le plus faible de la conclusion et perd un cran pour une preuve
indirecte (sauf si un argument examiné par le contradicteur a été accepté),
une information secondaire qu'aucune seconde source ne confirme, une objection ouverte, un
conflit de dates inexpliqué, ou une question seulement en partie conforme ; elle est au plus
possible pour une question non conforme, et « prouvée » exige que le
passage de l'acte soit cité. `verify --standard`, le rapport et l'export GEDCOM
(`_CONF`, et `QUAY`) l'affichent avec ses raisons ; elle ne bloque rien.

Probandia aide à montrer une preuve ; il ne remplace pas le jugement du
généalogiste. Le skill
[`skills/research/proofs.md`](https://github.com/devohmycode/probandia/blob/master/skills/research/proofs.md)
dit comment chaque élément est vérifié, et où s'arrêtent les vérifications.

## Ce qu'une recherche apprend : la bibliothèque

Probandia garde ce que les agents apprennent dans une bibliothèque, celle du projet (`library/`)
puis la vôtre (`library/` à côté de `config.toml`) : des scripts qui lisent une archive,
des requêtes qui ont marché (recettes), et, après votre accord, des skills et des sous-agents.

- À la fin d'une passe, `pass end` liste ce qui pourrait être gardé
  (`LEARN_CANDIDATES=`) ; l'agent vous demande une seule fois lesquels garder.
- `library list` montre chaque élément avec ses usages et ses réussites ; `library find`
  cherche dans les deux portées ; `library promote <id> --to user` en rend un disponible
  pour tous vos projets, et rejoue son témoin.
- Un skill ou un agent appris est écrit comme brouillon (`library draft`), vérifié par
  le moteur, et installé seulement une fois que vous l'avez lu et avez dit oui
  (`library install <id> --scope project|user --for <harness>`). La bibliothèque
  garde l'original ; les harness reçoivent des copies, que `library uninstall`
  retire exactement. Aucun agent ne peut écrire lui-même dans un dossier de skills ou d'agents.
- `library export lot.zip --ids …` et `library import lot.zip` partagent des éléments
  entre projets ; un élément importé repart comme brouillon.

## Ce qu'une recherche apprend : la mémoire

Probandia garde aussi les décisions de travail du projet dans une section de
`AGENTS.md`, entre `<!-- probandia:begin -->` et `<!-- probandia:end -->` :
conventions, modèle de rapport, fournisseurs retenus, archives qui demandent une
connexion, vos préférences, les pièges d'une source. Codex, Cursor, Factory
Droid et OpenCode lisent `AGENTS.md` ; Claude Code le lit aussi, ou par une ligne
`@AGENTS.md` quand le projet a un `CLAUDE.md`.

- À la fin d'une passe, l'agent propose les décisions qui méritent d'être gardées, dans la
  même question que les candidats de la bibliothèque ; rien n'est écrit avant votre
  oui (`memory add "<one line>" --kind provider`).
- Jamais dedans : des faits généalogiques (les index des familles les contiennent), des personnes
  présumées vivantes, des clés. Le moteur les refuse, et ne touche jamais votre texte
  hors des marqueurs.
- La section reste courte (40 lignes, 2 Ko), car chaque session la charge :
  fusionnez des entrées (`--supersedes M2,M3`) ou déplacez les plus anciennes vers
  `memory-archive.md`, qu'aucun harness ne charge.
- `memory list`, `memory remove M3`, `memory sync` ; `doctor` signale un import
  manquant, une section en double ou une section modifiée à la main. `--scope user`
  écrit votre propre fichier (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`), seulement avec
  son propre accord.

## Modèles de rapport

Le rapport HTML suit un modèle : un fichier `.html` sans script ni ressource
venue du réseau, que vous pouvez imprimer tel quel.

- Fournis : `habillage`, le modèle par défaut (papier gris, titres en Bodoni,
  rouge garance, sombre sur un écran sombre ; ses polices sont embarquées),
  `default` (le plus sobre), `print` (avec empattements, un chapitre par page),
  `family-book` (page de titre, notes après chaque chapitre) et `high-contrast`.
- **Les vues des actes.** Après la liste des sources, le rapport montre la vue
  de chaque acte qui prouve un fait (un fait lu sur son image), réduite à
  1 200 pixels (avec Pillow ; sans lui, le fichier tel quel). Une vue écartée
  est nommée, avec son fichier et la raison. Le réglage `report.images` dit où
  elles vont :
  - `folder` (par défaut) : des fichiers de `report/views/`, à côté de
    `report.html`, qui les appelle par un chemin relatif. Autant de vues que la
    recherche en compte. C'est votre copie privée : une vue dont la source n'a
    pas `rights` à `free` (le cas de la plupart des archives, dont la
    réutilisation suit leurs propres règles) est montrée aussi, marquée
    « Usage privé », de même que l'acte d'une personne vivante, marqué
    « Personne vivante : ne pas diffuser » (`report.living_views = off` les
    écarte). Lisez les règles de l'archive, et demandez aux vivants, avant de
    partager le dossier `report/` ;
  - `inline` : dans `report.html`, en `data:`, tant que la page reste sous
    1 Mo (la limite d'un modèle) : un seul fichier, fait pour voyager, donc
    seulement les vues dont la source a `rights: free`, et aucun acte d'une
    personne vivante ;
  - `off` : aucune.

  L'export GEDCOM garde la règle stricte : seulement les vues d'une source avec
  `rights: free`, jamais celles d'une personne vivante. Mettez `rights: free`
  sur une source (dans `families/<family>/index/sources.yaml`) dès que les
  règles de l'archive le permettent. Une personne née il y a moins de 100 ans
  est présumée vivante (`privacy.living_years`), sauf décès connu.
- `probandia template designer` ouvre l'atelier dans votre navigateur, hors
  ligne : couleurs (avec leur contraste WCAG), polices, largeur, page de titre
  et logo, en-tête et pied de page, sommaire, marques de statut, errata, notes,
  couleurs de l'arbre, impression ; l'aperçu passe de l'anglais au français.
  Téléchargez le modèle, puis `probandia template import my-template.html`.
- `probandia template use family-book` le choisit pour le projet ; `--level
  family` ou `--level research` pour une famille ou une recherche, `--level user`
  pour tous vos projets. Puis `probandia render --all`.
- `template list | show | check | export` font le reste ; `verify` (règle V-13)
  signale quand le modèle d'un rapport a été retiré ou modifié.

## Fournisseurs

Probandia cherche et lit sur le web avec la recherche web du harness lui-même
et les offres gratuites des fournisseurs ci-dessous, et ne paie jamais. Les
commandes `search` et `read` du moteur appellent les API des fournisseurs avec
vos clés (`probandia keys signup <provider>` donne la page où créer chaque
compte gratuit ; `keys set` enregistre la clé). `quota show` donne ce qui reste
de chacun, en recherches et en pages, avec le jour où il repart ; `doctor`
liste les clés trouvées et les soldes qu'il peut lire. Les offres gratuites,
coûts et sources sont dans
[`catalogues/providers.toml`](https://github.com/devohmycode/probandia/blob/master/catalogues/providers.toml),
chaque entrée avec la date de sa vérification.

| Fournisseur | Id du catalogue | Rôle | Clé |
|---|---|---|---|
| SerpApi | `serpapi` | recherche web, index Google | `SERPAPI_API_KEY` |
| SerpApi, moteur Bing (désactivé par défaut) | `serpapi_bing` | recherche web, index Bing | `SERPAPI_API_KEY` |
| Serper | `serper` | recherche web, index Google | `SERPER_API_KEY` |
| SearchApi.io | `searchapi` | recherche web, index Google | `SEARCHAPI_API_KEY` |
| OpenWeb Ninja Real-Time Web Search | `openwebninja_search` | recherche web, index Google | `OPENWEBNINJA_API_KEY` |
| OpenWeb Ninja Real-Time News Data | `openwebninja_news` | recherche d'actualités | `OPENWEBNINJA_API_KEY` |
| OpenWeb Ninja Real-Time Books Data | `openwebninja_books` | recherche de livres | `OPENWEBNINJA_API_KEY` |
| Gemini grounding (réutilise le contenu, désactivé par défaut) | `gemini_grounding` | recherche web, index Google | `GEMINI_API_KEY` |
| Brave Search API | `brave` | recherche web, autre index | `BRAVE_API_KEY` |
| Staan | `staan` | recherche web, autre index | `STAAN_API_KEY` |
| Marginalia Search | `marginalia` | recherche web, autre index | `MARGINALIA_API_KEY` |
| Exa (réutilise le contenu, désactivé par défaut) | `exa` | recherche web, autre index | `EXA_API_KEY` |
| Parallel Search (réutilise le contenu, désactivé par défaut) | `parallel` | recherche web, autre index | `PARALLEL_API_KEY` |
| Tavily (réutilise le contenu, désactivé par défaut) | `tavily` | réponses avec sources ; lecture de pages, `read --map`, `--crawl`, `--extract` | `TAVILY_API_KEY` |
| Linkup (réutilise le contenu, désactivé par défaut) | `linkup` | réponses avec sources | `LINKUP_API_KEY` |
| Jina Reader (fonctionne sans clé) | `jina` | lecture de pages | `JINA_API_KEY` |
| Firecrawl | `firecrawl` | lecture de pages, `read --map`, `--crawl`, `--extract` | `FIRECRAWL_API_KEY` |
| ScrapeGraphAI (réutilise le contenu, désactivé par défaut) | `scrapegraph` | `read --extract` | `SGAI_API_KEY` |
| ZenRows | `zenrows` | lecture, dernier recours | `ZENROWS_API_KEY` |
| ScraperAPI | `scraperapi` | lecture, dernier recours | `SCRAPERAPI_API_KEY` |
| Apify (Google Search Scraper) | `apify` | recherche web, index Google | `APIFY_TOKEN` |
| Apify (RAG Web Browser) | `apify_reader` | lecture, dernier recours | `APIFY_TOKEN` |
| OpenRouter | `openrouter` | son solde seulement (`doctor`, `quota sync`) | `OPENROUTER_API_KEY` |

- Les clés vont dans un fichier `.env` : celui de l'utilisateur (à côté de
  `config.toml`) ou celui du projet (à côté de `probandia.toml`) ;
  [`.env.example`](https://github.com/devohmycode/probandia/blob/master/.env.example)
  les liste toutes. Une clé n'est jamais affichée.
- **Refusé avant l'appel.** Un fournisseur n'est pas appelé quand son quota
  gratuit restant, moins la réserve (`budget.reserve_percent`), ne peut pas
  payer l'opération (`STATUS=STOP`, code de sortie 4) ; quand il n'est pas dans
  `providers.enabled` ou qu'il est désactivé (`providers disable`) ; quand sa
  clé manque ; quand il demande une carte (sauf `providers.allow_card_required`)
  ou réutilise le contenu envoyé (sauf `providers.allow_content_reuse`) ; et
  jamais avec le nom d'une personne présumée vivante. `providers` les liste
  chacun avec la raison de sa mise hors service.
- **La première salve est gratuite.** Une passe s'ouvre avec les archives et la
  recherche web du harness lui-même, dans le même tour : `search.max_parallel`
  recherches natives à la fois (3 par défaut, de 1 à 8 :
  `probandia config set search.max_parallel 5`, ou `--parallel 5`). La commande
  `search` du moteur, qui dépense le quota d'un fournisseur, attend la première
  recherche native de la passe (`REASON=native-first`) ; une recherche
  `--negative` n'attend pas.
- **Le moteur, pas des serveurs MCP.** Les agents ne chargent aucun serveur MCP
  de recherche ou de scraping : les commandes `search` et `read` du moteur
  (`--map`, `--crawl <n>`, `--extract "<what>"`) servent les salves suivantes
  avec les clés d'API des fournisseurs, en comptant chaque quota avant l'appel.
  Pendant une passe, la garde refuse un appel à l'un de vos propres serveurs
  (Firecrawl, Tavily, Exa, un connecteur claude.ai…) et nomme la commande du
  moteur qui fait la même chose (règle G-15) ; hors d'une passe, l'appel passe
  et il est décompté ensuite du quota du fournisseur. Un connecteur claude.ai
  ne sert pas une passe : donnez une clé d'API au moteur.
- **Soldes.** `probandia quota sync` lit, gratuitement, le solde de chaque
  compte dont la clé est réglée ; `probandia usage --sync` (`-u --sync`) les lit
  avant de les afficher.
- Un négatif web (« trouvé nulle part ») demande au moins deux familles d'index
  indépendantes ; un moteur dont la réponse est sans rapport avec la requête
  n'est pas compté, et un moteur d'une famille manquante prend le relais. Bing
  via SerpApi a répondu à la plupart des requêtes généalogiques exactes par des
  pages sans rapport : il reste désactivé sauf ajout à `providers.enabled`.
- `read <url>` essaie Firecrawl, puis Tavily, dont les offres gratuites se
  renouvellent chaque mois, avant Jina, dont les tokens gratuits sont donnés
  une seule fois par clé, et Parallel en dernier, lent sur une page qu'il n'a
  pas en cache ; `reading.readers` fixe un autre ordre.
- `search --depth advanced` demande une recherche plus profonde et plus chère
  (Tavily, Exa, Parallel, Linkup seulement ; tout autre moteur est refusé avant
  tout appel).
- Les lecteurs de dernier recours sont utilisés sans leurs options anti-bot
  (proxys premium ou résidentiels, modes furtifs, résolution de CAPTCHA), après
  les lecteurs ci-dessus, une fois par page à leur niveau de base, et jamais
  sur un portail d'archives ou une base de données généalogique.
- `robots.txt` régit les robots d'exploration, pas une page lue pour vous :
  quand il interdit une page, `read <url>` ne la récupère pas lui-même (par HTTP
  ou par son propre navigateur) mais la confie aux lecteurs ci-dessus, puis à
  votre navigateur ou aux archives du web (jamais pour un hôte dont l'archive
  interdit les tiers, ni pour une adresse locale). `read --map` et `--crawl` le
  respectent strictement, pour chaque page.
- OpenWeb Ninja demande au compte de s'abonner à l'offre gratuite de chaque API
  (Real-Time Web Search, Real-Time News Data, Real-Time Books Data) avant usage.
- `pass end` compte les outils de la passe (`TOOLS_WEB`, `TOOLS_MCP`,
  `TOOLS_ARCHIVE`, `TOOLS_ENGINE`), montrés aussi dans le chapitre Méthode du
  rapport ; une passe sans recherche web ni appel MCP avertit qu'elle est
  incomplète.

### Archives ouvertes

Le [guide des archives ouvertes](https://github.com/devohmycode/probandia/blob/master/guides/open-archives.md)
(en français) consigne les conditions d'accès à Matricula, Delpher, DDB, Mémoire
des hommes, Léonore, Arolsen et aux Archives de l'État en Belgique. Utilisez `archive find "Arolsen"` pour une archive atteinte par votre navigateur, ou
`archive run ddb.search --args '{"query":"Goethe","max":20}'` pour l'API
publique de DDB, dont les métadonnées sont sous CC0 (les droits des images
restent propres à chaque objet). Le catalogue des archives, avec l'accès de
chacune, est
[`catalogues/archives.yaml`](https://github.com/devohmycode/probandia/blob/master/catalogues/archives.yaml).

### La veille des sources

Les archives et les offres gratuites changent. `probandia watch` rejoue le
témoin de chaque connecteur d'archive, une petite recherche dont la réponse est
connue, et liste les entrées des deux catalogues vérifiées il y a plus de
`catalogues.max_age_days` jours (90).

- Un témoin qui demande une clé, des fichiers téléchargés ou une session dans
  le navigateur est « non lancé », avec la raison, jamais « en échec » ;
  `--keys` lit aussi, gratuitement, le compte de chaque fournisseur dont la clé
  est réglée. Rien n'est payé.
- Elle écrit `.probandia/watch.json` et `watch.md`, et compte les échecs
  consécutifs de chaque témoin d'une veille à la suivante.
- `probandia watch --print-schedule` affiche la commande `schtasks` (ou la
  ligne crontab) qui la lance chaque lundi : lancez-la vous-même.
- `python tools/watch_issues.py .probandia/watch.json --dry-run` montre les
  issues qu'une veille appelle : un témoin en échec trois veilles de suite (un
  site souvent bloqué n'en ouvre pas une chaque semaine), une entrée périmée.
  Sans `--dry-run`, `gh` les ouvre et les ferme.
- `.github/workflows/watch.yml` fait tout cela chaque lundi sur GitHub, le
  `watch.json` précédent gardé dans un cache, et ouvre ou ferme les issues
  étiquetées `watch`. Lancez-le à la main depuis l'onglet Actions.
- `archive stale` et `providers stale` listent les seules entrées périmées.

## L'interface en terminal

`probandia tui` ouvre une application dans le terminal. Ses écrans, chacun sur
sa touche :

| Touche | Écran | Ce qu'il montre |
|---|---|---|
| 1 | `home` | les recherches, les derniers événements de celle choisie, les comptes les plus bas et les alertes |
| 2 | `quotas` | les quotas gratuits des comptes, les fournisseurs et leurs clés |
| 3 | `researches` | chaque recherche : son fichier, son journal, son rapport et son équipe |
| 4 | `family` | l'arbre de la famille, ses personnes et leurs faits |
| 5 | `proposals` | les propositions en attente, lues puis acceptées ou mises de côté |
| 6 | `config` | les réglages, la bibliothèque de scripts et le diagnostic |
| 7 | `help` | chaque réglage, d'où vient sa valeur, les conditions des fournisseurs, les clés et les variables |

- `Ctrl+P` ouvre la palette : un écran, ou le formulaire d'une commande.
- La console remplit une commande dans son formulaire, et `Ctrl+R` la lance
  sans quitter l'application : sa sortie lisible sous le formulaire, ses
  confirmations et les clés qu'elle demande dans les fenêtres de l'application.
- `?` liste toutes les touches, `q` quitte. L'application n'écrit rien
  elle-même : chaque action lance une commande du moteur.
- Elle demande l'extra `tui` (Textual 8 ; voir [les extras](#installer-la-commande)) :
  `uv tool install --force "<path>[tui]"`, ou depuis PyPI
  `uv tool install "probandia[tui]"`. Sinon, le moteur n'importe jamais
  Textual, et `probandia tui --help` décrit les écrans sans lui.

## Développement

Pour travailler sur Probandia lui-même, depuis le dossier du dépôt ; `AGENTS.md`
donne l'architecture et la règle que suit une modification avant sa fusion :

```sh
python run_probandia.py --help                       # lancer le moteur depuis le dépôt (sans installation ; doit marcher sans aucun paquet installé)
python tools/run_tests.py                            # suite de tests complète (unitaires + intégration + fichiers de référence), répartie entre processus (-j N, -v)
python -m unittest discover -s tests                 # la même suite en un seul processus (comme `run_tests.py -j 1`)
python tools/run_tests.py --measure                  # un processus par module : réécrit tools/test_durations.json, qui équilibre les parts
python -m unittest tests.unit.test_cli               # un module de tests
python -m unittest tests.unit.test_cli.SomeClass.test_name   # un seul test
python -m pip install --editable ".[dev]"            # dépendances de test : l'extra `dev` de pyproject.toml (jsonschema, Pillow, ruff épinglé)
python -m ruff check .                               # lint (F et E9, `[tool.ruff]` dans pyproject.toml)
python tools/make_sample_project.py                  # régénérer tests/sample-project et tests/sample-project-gps (la CI échoue si `git status --porcelain` montre une différence)
python run_probandia.py manifests check              # les manifestes générés du plugin doivent être à jour
python tools/check_wheel.py                          # construire le wheel et le sdist : fichiers = tools/package-contents.txt, aucun nom privé ; installer le wheel, vérifier qu'il trouve ses données
python tools/check_wheel.py --update                 # après ajout, déplacement ou retrait d'un fichier empaqueté : réécrire tools/package-contents.txt (lire son diff)
python tools/startup_time.py                         # temps de démarrage médian de `--version` et `hook guard` (mesure seulement)
python tools/ci_local.py                             # toute la CI sur cette machine : chaque job de ci.yml, Windows et Ubuntu (WSL)
python tools/ci_local.py --quick                     # ce qu'il faut à un sprint : test sous Windows 3.14 et Ubuntu 3.12, tui/gedcom quand leurs fichiers changent
python tools/ci_local.py --jobs test --os windows --python 3.14   # une partie ; --rev <commit>, --parallel N (8 par défaut), --dry-run
uv tool install --editable .                         # installer la commande `probandia` depuis le dépôt (ajouter --force après une modification de pyproject.toml)
python tools/run_readme_examples.py                  # rejouer les exemples de ce README sous PowerShell et bash
```

## Versions

Ce que chaque version a changé, les changements incompatibles d'abord :
[CHANGELOG.md](https://github.com/devohmycode/probandia/blob/master/CHANGELOG.md). Ce que la 1.x garde
stable, et comment un changement de ces points est d'abord déprécié :
[STABILITY.md](https://github.com/devohmycode/probandia/blob/master/STABILITY.md).

## Licence

Apache License 2.0 : voir [LICENSE](https://github.com/devohmycode/probandia/blob/master/LICENSE) ; les
bibliothèques et polices embarquées gardent leurs propres licences, listées dans
[THIRD-PARTY-NOTICES](https://github.com/devohmycode/probandia/blob/master/THIRD-PARTY-NOTICES).
