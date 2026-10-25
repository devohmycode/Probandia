# Guide d'utilisation de Probandia

> Rien n'est conclu avant d'être prouvé.

Probandia est un plugin de recherche généalogique pour les agents de code (Claude Code, Grok Build, Codex, Cursor,
Factory Droid, Antigravity, OpenCode) et un serveur MCP pour Claude Desktop. Il conduit une recherche selon le
*Genealogical Proof Standard* (GPS), ne paie jamais un fournisseur et ne conclut rien sans preuve citée.

Ce guide, en français, suit l'ordre d'une première utilisation : installer, créer un projet, régler les clés, mener
une recherche, la vérifier, la clore et en publier le résultat. Le [README](../README.md), en anglais, fait foi ;
`probandia --help --all` et `probandia help <commande>` donnent toujours l'état exact de la commande installée.

## Sommaire

1. [Installer](#1-installer)
2. [Créer un projet et le régler](#2-créer-un-projet-et-le-régler)
3. [Les clés et les quotas gratuits](#3-les-clés-et-les-quotas-gratuits)
4. [Mener une recherche](#4-mener-une-recherche)
5. [Prouver : le Genealogical Proof Standard](#5-prouver--le-genealogical-proof-standard)
6. [Ce que la famille sait déjà](#6-ce-que-la-famille-sait-déjà)
7. [Arbres, rapports, exports et imports](#7-arbres-rapports-exports-et-imports)
8. [Ce que Probandia apprend : bibliothèque et mémoire](#8-ce-que-probandia-apprend--bibliothèque-et-mémoire)
9. [Archives et veille des sources](#9-archives-et-veille-des-sources)
10. [La commande dans un terminal](#10-la-commande-dans-un-terminal)
11. [L'application dans un terminal (TUI)](#11-lapplication-dans-un-terminal-tui)
12. [Aide-mémoire](#12-aide-mémoire)

## 1. Installer

Il y a deux choses à installer, indépendantes : le **plugin**, dans votre agent, et, si vous le souhaitez, la
**commande** `probandia`, dans votre terminal.

### Prérequis

- **Systèmes** : Windows et Linux, testés par la CI à chaque modification (Windows avec Python 3.11 et 3.14, Ubuntu
  avec Python 3.11, 3.12, 3.13 et 3.14). macOS : non testé.
- **Python 3.11 ou plus récent, appelable sous le nom `python`** : les hooks de Claude Code et de Codex prennent
  `python`, sinon `python3` (sous Windows, `python` seulement ; Claude Code les y lance dans Git Bash) ; le serveur
  MCP et les hooks de Cursor et d'Antigravity lancent `python`, sans repli. `probandia doctor` signale l'absence de
  `python`. Sous Debian ou Ubuntu, `sudo apt install python-is-python3` donne ce nom ; sous Windows, l'installateur
  de python.org avec « Add python.exe to PATH ».
- **Claude Code sous Windows : Git Bash.** Sans lui, Claude Code lance les hooks dans PowerShell, où ils échouent :
  installez Git for Windows, ou faites pointer `CLAUDE_CODE_GIT_BASH_PATH` vers son `bash.exe`. `probandia doctor`
  signale quand il n'en trouve pas (`GIT_BASH=missing`).
- Rien d'autre : le moteur n'utilise que la bibliothèque standard et embarque ses quelques dépendances dans
  `src/probandia/_vendor`.

#### Sous Windows, depuis PowerShell

Python et Git for Windows (qui apporte Git Bash), puis fermez et rouvrez PowerShell pour qu'il relise le `PATH` :

```powershell
winget install -e --id Python.Python.3.14
winget install -e --id Git.Git --source winget
python --version
```

Si `python` ouvre le Microsoft Store, ouvrez *Alias d'exécution d'application* depuis le menu Démarrer et
désactivez les alias de Python. Sans winget, les installateurs de
[python.org](https://www.python.org/downloads/windows/) (cochez « Add python.exe to PATH ») et de
[git-scm.com](https://git-scm.com/install/windows) font de même.

Puis la CLI de votre harnais, chacune d'après sa documentation (lue le 25 octobre 2026) :

| CLI de l'agent | Installation sous Windows (PowerShell) | Documentation |
|---|---|---|
| Claude Code | `irm https://claude.ai/install.ps1 \| iex`, ou `winget install Anthropic.ClaudeCode` | [code.claude.com](https://code.claude.com/docs/en/setup) |
| Codex | `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 \| iex"`, ou `npm install -g @openai/codex` | [github.com/openai/codex](https://github.com/openai/codex) |
| Cursor (CLI) | `irm 'https://cursor.com/install?win32=true' \| iex` | [cursor.com](https://cursor.com/docs/cli/installation) |
| Factory Droid | `irm https://app.factory.ai/cli/windows \| iex` | [github.com/Factory-AI/factory](https://github.com/Factory-AI/factory) |
| Grok Build | `irm https://x.ai/cli/install.ps1 \| iex` | [docs.x.ai](https://docs.x.ai/build/overview) |
| Antigravity | `irm https://antigravity.google/cli/install.ps1 \| iex` | [github.com/google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli) |
| OpenCode | `npm install -g opencode-ai` (Node.js d'abord : `winget install OpenJS.NodeJS.LTS`), ou `scoop install opencode` ; sa documentation conseille WSL sous Windows | [opencode.ai](https://opencode.ai/docs/) |

Outils facultatifs, que `probandia doctor` vérifie sans rien installer lui-même :

| Outil | Pour quoi | Installation |
|---|---|---|
| Playwright | un navigateur sans fenêtre, pour les pages qui en demandent un, quand votre agent ne pilote aucun navigateur à vous (§ 9, « Archives derrière une connexion ») | `python -m pip install playwright && python -m playwright install chromium` |
| Tesseract | l'OCR des actes imprimés (`transcribe ocr`) | Windows : `winget install UB-Mannheim.TesseractOCR` ou `scoop install tesseract` ; Linux : `sudo apt install tesseract-ocr tesseract-ocr-fra` ; macOS : `brew install tesseract tesseract-lang` |
| Pillow | planches de vues, recadrages et rotations d'images (`image`) | `python -m pip install "Pillow>=12,<13"`, ou l'option `images` (§ 1.2) |

### 1.1 Le plugin dans votre agent

Le dépôt, `https://github.com/devohmycode/probandia`, est à la fois le plugin et sa marketplace. Claude Code, Grok
Build et Factory Droid l'installent directement depuis GitHub. Codex, Antigravity, OpenCode et Claude Desktop
l'installent depuis un clone, dont le dossier est `<chemin>` ci-dessous :

```sh
git clone https://github.com/devohmycode/probandia
cd probandia
```

Sous Windows, clonez-le dans un dossier court (`C:\Users\<vous>\probandia`, pas un dossier profond) : quelques
fichiers de `bench/` ont des chemins de 163 caractères, et Windows refuse les chemins de plus de 260.

| Harnais | Prise en charge | Serveur MCP | Installation |
|---|---|---|---|
| Claude Code (terminal, IDE, application de bureau) | complète | non : ses skills appellent le moteur par le shell | `/plugin marketplace add devohmycode/probandia` |
| Grok Build | complète | non : il lit `.claude-plugin/` | `grok plugin install devohmycode/probandia --trust` |
| Codex | complète | oui (`mcp.json`) | `codex plugin marketplace add <chemin>`, puis `install --harness codex` (plugin et sept agents) |
| Cursor | complète | oui (`cursor/mcp.json`) | `git clone` dans `~/.cursor/plugins/local/probandia` |
| Factory Droid | complète | non : la racine du plugin n'est pas développée dans ses réglages MCP | `droid plugin marketplace add https://github.com/devohmycode/probandia` |
| Antigravity | bêta | oui (`mcp_config.json`) | `agy plugin install <chemin>` |
| OpenCode | réduite | oui, fusionné dans `opencode.json` | `install --harness opencode` |
| Claude Desktop (conversation) | serveur MCP seul | oui, la seule partie | `claude_desktop_config.json` |

Chaque section dit quand, et avec quelle version, elle a été rejouée. Toutes les voies lancent le moteur depuis le dossier du dépôt : laissez-le où il est,
et mettez-le à jour (`git pull`) avant de mettre à jour le plugin. Dans les blocs, seuls `<chemin>` et la question
de la recherche sont traduits du README.

#### Claude Code

Prise en charge complète, sans le serveur MCP. Vérifié le 21 octobre 2026 avec Claude Code 2.1.304 et 2.1.306,
dans une configuration à part (`CLAUDE_CONFIG_DIR`) : installation depuis le dossier du dépôt, une recherche menée
jusqu'au bout, mise à jour et désinstallation, qui laisse `"enabledPlugins": {}` et la copie du plugin dans le
cache de Claude Code ; le serveur MCP seul a été listé connecté, puis retiré. Vérifié le 24 octobre 2026 avec
Claude Code 2.1.306, depuis GitHub : marketplace ajoutée, plugin installé (1.0.0) et activé, marketplace mise à
jour, puis l'un et l'autre retirés. Dans une session (ou les mêmes mots après `claude plugin` dans un terminal) :

Installer, depuis GitHub :

```text
/plugin marketplace add devohmycode/probandia
/plugin install probandia@probandia
```

Depuis un clone, la première ligne est `/plugin marketplace add <chemin>`.

Mettre à jour :

```text
/plugin marketplace update probandia
/plugin update probandia@probandia
```

Désinstaller :

```text
/plugin uninstall probandia@probandia
/plugin marketplace remove probandia
```

Lancer une recherche :

```text
/probandia:new "Qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?"
```

`claude --plugin-dir <chemin>` charge le dossier pour une session, sans l'installer.

Le serveur MCP seul, sans le plugin : les 17 outils du moteur dans Claude Code, sans les commandes
slash, skills, agents ni hooks. Déclarez-le depuis le dossier du projet :

```sh
claude mcp add probandia -- python <chemin>/run_probandia.py mcp
```

Une fois la 1.0.0 publiée sur PyPI, sans le dépôt : `claude mcp add probandia -- uvx probandia mcp` (sous Windows,
`cmd /c uvx` au lieu de `uvx`). `claude mcp remove probandia` le retire.

#### Grok Build

Prise en charge complète, sans le serveur MCP : Grok Build lit la disposition de Claude Code (`.claude-plugin/`).
Ses options de plugin (`/config`) sont ignorées : les réglages viennent des fichiers (voir
[§ 2.1](#21-les-réglages--config)). Vérifié le 17 octobre 2026 avec Grok Build 1.0.62 : installation depuis le
dossier du dépôt, `doctor` lancé dans le harnais le nomme, la commande de statut répond `STATUS=OK`, et la
désinstallation laisse ses fichiers de configuration tels qu'ils étaient.

Installer, depuis GitHub (`grok plugin install` accepte une URL git, `utilisateur/dépôt` ou un chemin local) :

```sh
grok plugin install devohmycode/probandia --trust
```

Depuis un clone : `grok plugin install <chemin> --trust`.

Mettre à jour : installé depuis GitHub, cette commande va chercher la nouvelle version. Un chemin local est installé
comme un lien, `git pull` dans `<chemin>` suffit, et la même commande le dit :

```sh
grok plugin update probandia
```

Désinstaller :

```sh
grok plugin uninstall probandia
```

Lancer une recherche (la forme de `/probandia:status`, vérifiée) :

```text
/probandia:new "Qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?"
```

#### Codex

Prise en charge complète, avec le serveur MCP. Les plugins Codex contiennent des skills mais pas de sous-agents :
l'installateur écrit aussi les sept rôles en agents personnalisés. Lancez-le depuis le dossier de votre projet de
recherche (ou passez `--path <dossier-du-projet>`). Vérifié le 17 octobre 2026 avec Codex 0.161.0 : installation
depuis le dossier du dépôt, `doctor` lancé dans le harnais le nomme, la commande de statut répond `STATUS=OK`, et la
désinstallation laisse ses fichiers de configuration tels qu'ils étaient.

Vérifié le 21 octobre 2026 avec Codex 0.161.0, dans un projet neuf : la marketplace ajoutée comme ci-dessous est
listée, le plugin est installé et activé, l'agent lecteur se lance, et le contradicteur lance le moteur dans son bac
à sable en lecture seule.

Installer : ajouter le dépôt comme marketplace (Codex n'en lit aucune dans les réglages d'un projet), écrire les
agents, puis ajouter le plugin, depuis le dossier du projet :

```sh
codex plugin marketplace add <chemin>
python <chemin>/run_probandia.py install --harness codex
codex plugin add probandia@probandia
```

La première commande inscrit la marketplace dans vos réglages de Codex (`~/.codex/config.toml`) ; l'installateur
active le plugin dans le `.codex/config.toml` du projet et écrit les sept agents personnalisés,
`.codex/agents/probandia-<rôle>.toml`. Les réglages Codex existants sont gardés. Rouvrez Codex dans ce dossier, faites confiance au projet, ouvrez une
nouvelle conversation ; approuvez les hooks du plugin dans `/hooks` si Codex le demande. Les agents suivent le
format TOML de Codex (`name`, `description`, `developer_instructions`, `model_reasoning_effort`), héritent de votre
modèle sauf si vous en avez choisi un (voir [§ 2.3](#23-le-modèle-et-leffort-de-chaque-agent--config-roles)), et
mettent le contradicteur en `sandbox_mode = "read-only"`. Voir le
[format des agents personnalisés](https://learn.chatgpt.com/docs/agent-configuration/subagents) et la
[configuration des plugins de projet](https://developers.openai.com/plugins/build/plugins). Si vous avez déjà
installé le plugin par la marketplace de Codex, `install --harness codex-agents` n'installe que les rôles.

Mettre à jour : `git pull` dans `<chemin>`, puis la même commande, qui réécrit les agents :

```sh
python <chemin>/run_probandia.py install --harness codex
```

Désinstaller : `codex plugin remove` retire le plugin de `~/.codex/config.toml` et du cache de Codex,
`--uninstall` retire ce que l'installateur a écrit, et la dernière commande retire la marketplace de vos réglages :

```sh
codex plugin remove probandia@probandia
python <chemin>/run_probandia.py install --harness codex --uninstall
codex plugin marketplace remove probandia
```

Lancer une recherche (la même demande pour `status`, vérifiée) : le plugin Codex apporte des skills, pas de
commandes slash ; demandez dans la conversation, et la skill `engine` lance `new` :

```text
Lance une recherche Probandia : qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?
```

#### Cursor

Prise en charge complète, avec le serveur MCP (`cursor/mcp.json`). Cursor charge un plugin local depuis
`~/.cursor/plugins/local/<nom>`, un dossier à lui : il refuse un lien vers un dossier ailleurs (« symlink target … is
outside »). Redémarrez ensuite Cursor, ou lancez « Developer: Reload Window » (en Teams et Enterprise, un
administrateur doit autoriser l'import de plugins locaux). `cursor-agent --plugin-dir <chemin>` charge le dossier pour
une session.
Cursor ne montre les commandes d'un plugin que si son option des plugins, skills et réglages tiers (*third-party*) est
activée. Elle lui fait aussi importer les plugins de Claude Code : si Probandia y est installé, désactivez-le dans
Claude Code (`claude plugin disable probandia@probandia`), sinon Cursor montre cette copie (ses commandes sans
préfixe, `/status`) à la place de celle-ci.
Vérifié le 22 octobre 2026 avec Cursor 3.27.6 (l'éditeur) : installé par un clone, Cursor le liste comme plugin local
(0.9.41) avec ses 19 commandes, et `/probandia-status` est proposé dans le chat ; le 21 octobre 2026, avec Cursor
3.26.13, le serveur MCP listait ses 17 outils et `dates` répondait, `doctor` nommait Cursor, et un fork y laissait
l'original tel qu'il était.

Installer, un clone du dépôt :

```sh
git clone https://github.com/devohmycode/probandia ~/.cursor/plugins/local/probandia
```

```powershell
git clone https://github.com/devohmycode/probandia "$HOME\.cursor\plugins\local\probandia"
```

Mettre à jour : `git pull` dans le clone, puis rechargez la fenêtre :

```sh
git -C ~/.cursor/plugins/local/probandia pull
```

Désinstaller : supprimez le clone :

```sh
rm -rf ~/.cursor/plugins/local/probandia
```

```powershell
Remove-Item -Recurse -Force "$HOME\.cursor\plugins\local\probandia"
```

Lancer une recherche. Cursor nomme les commandes d'un plugin sans préfixe : celles de Probandia en portent un
(`cursor/commands/`), à l'écart des siennes et de celles des autres plugins (`/probandia-status`,
`/probandia-resume`…) :

```text
/probandia-new "Qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?"
```

#### Factory Droid

Prise en charge complète, sans le serveur MCP : la racine du plugin n'est pas développée dans les réglages MCP de
Droid, si bien que les skills appellent le moteur par le shell. Droid lit la marketplace du dépôt
(`.claude-plugin/marketplace.json`) et la nomme d'après le dossier : pour un dossier qui ne s'appelle pas
`probandia`, écrivez `probandia@<nom-du-dossier>` et `marketplace remove <nom-du-dossier>` ci-dessous. Vérifié le
17 octobre 2026 avec Factory Droid 0.242.0 : installation depuis le dossier du dépôt, `doctor` lancé dans le
harnais le nomme, la commande de statut répond `STATUS=OK`, et la désinstallation retire tout, sauf un
`"enabledPlugins": {}` vide dans `~/.factory/settings.json` et des dossiers vides dans `~/.factory/plugins/cache/`. La mise à jour a été vérifiée le 21 octobre 2026 avec
Factory Droid 0.245.1.

Installer, depuis GitHub :

```sh
droid plugin marketplace add https://github.com/devohmycode/probandia
droid plugin install probandia@probandia --scope user
```

Depuis un clone : `droid plugin marketplace add <chemin>`.

Mettre à jour :

```sh
droid plugin marketplace update probandia
droid plugin update probandia@probandia --scope user
```

Désinstaller :

```sh
droid plugin uninstall probandia@probandia --scope user
droid plugin marketplace remove probandia
```

Lancer une recherche (vérifié le 21 octobre 2026 : demandée en mots, il lance le fichier de commande ; `droid exec`
ne développe pas les commandes slash), sous le nom que Droid donne au fichier de commande (`commands/new.md` devient `/new`). Droid ne lit les commandes d'un plugin que dans son dossier `commands/`,
partagé avec Claude Code : elles gardent leur nom court (`/new`, `/status`, `/resume`…), qu'une commande de Droid
ou d'un autre plugin peut prendre avant elles ; demandez-la alors en mots (« lance le statut de Probandia »). Sinon :

```text
/new "Qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?"
```

#### Antigravity

Prise en charge bêta, avec le serveur MCP, déclaré dans `mcp_config.json` (le `plugin.json` de la racine n'en
déclare pas). Antigravity lance le serveur dans le dossier du plugin : le serveur demande alors au client ses
racines (MCP `roots/list`) et travaille dans la première qui contient un projet. Vérifié le 17 octobre 2026 avec
Antigravity 1.4.0 : installation depuis le dossier du dépôt, `doctor` lancé dans le harnais le nomme, la commande
de statut répond `STATUS=OK`, et la désinstallation laisse ses fichiers de configuration tels qu'ils étaient. Son
installation affichait « agents: skipped (not found) » : depuis le 23 octobre 2026 (agy 1.4.6), `agy plugin validate .`
compte les sept agents de `agents/`, qui prennent le modèle de la session.

Installer :

```sh
agy plugin install <chemin>
```

Mettre à jour : `git pull` dans `<chemin>`, puis installer de nouveau :

```sh
agy plugin install <chemin>
```

Désinstaller :

```sh
agy plugin uninstall probandia
```

Lancer une recherche (la forme de `/status`, vérifiée) :

```text
/new "Qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?"
```

#### OpenCode

Prise en charge réduite, avec le serveur MCP. OpenCode n'a pas de format de paquet : l'installateur copie les
skills, les agents et les commandes (en `probandia-<nom>.md`), fusionne le serveur MCP dans `opencode.json` (en
gardant une copie `.bak`) et ajoute un petit plugin JS pour les hooks. Vérifié le 17 octobre 2026 avec OpenCode
1.18.29 : installation depuis le dossier du dépôt, `doctor` lancé dans le harnais le nomme, la commande de statut
répond `STATUS=OK`, et la désinstallation laisse ses fichiers de configuration tels qu'ils étaient (`--scope user` ;
les skills vont dans `~/.agents/skills/`).

Installer, pour votre utilisateur ou pour le projet courant :

```sh
python <chemin>/run_probandia.py install --harness opencode
python <chemin>/run_probandia.py install --harness opencode --scope project
```

Mettre à jour : `git pull` dans `<chemin>`, puis la même commande :

```sh
python <chemin>/run_probandia.py install --harness opencode
```

Désinstaller, avec le même `--scope` qu'à l'installation :

```sh
python <chemin>/run_probandia.py install --harness opencode --uninstall
```

Lancer une recherche (la forme de `/probandia-status`, vérifiée) :

```text
/probandia-new "Qui étaient les parents de Victor Hugo, né en 1802 à Besançon ?"
```

#### Claude Desktop

Le serveur MCP seul : Claude Desktop (la conversation, pas Claude Code) lance des serveurs MCP mais pas de plugin.
Il reçoit les outils du moteur (recherche, lecture, ce qui est connu, vérification…), sans commandes slash, skills,
agents ni hooks. Vérifié le 21 octobre 2026 : ajouté à `claude_desktop_config.json`, son outil `dates` répond dans une
conversation ; retiré, après un redémarrage.

Installer : ajoutez le serveur à `claude_desktop_config.json` (Paramètres › Développeur › Modifier la
configuration), avec le dossier du projet où il travaille, puis redémarrez Claude Desktop :

```json
{
  "mcpServers": {
    "probandia": {
      "command": "python",
      "args": ["<chemin>/run_probandia.py", "mcp"],
      "env": {"PROBANDIA_PROJECT": "<le dossier qui contient probandia.toml>"}
    }
  }
}
```

Mettre à jour : `git pull` dans `<chemin>`, puis redémarrez Claude Desktop :

```sh
git -C <chemin> pull
```

Désinstaller : retirez l'entrée `"probandia"` de `mcpServers`, puis redémarrez Claude Desktop :

```json
{
  "mcpServers": {}
}
```

Lancer une recherche : outils MCP seulement. Demandez dans la conversation ; Claude appelle les outils du
[serveur MCP](../README.md#the-plugin-surface) (`plan`, `search`, `read`, `propose`, `verify`…) dans le projet de
`PROBANDIA_PROJECT`.

#### Ce que fait `--uninstall`

Chaque `install --harness` note ce qu'il a écrit dans `.probandia-install.json` (dans `.codex/` pour Codex ; dans
le dossier de configuration d'OpenCode, ou celui du projet, pour OpenCode). `--uninstall` lit cette note et :

- supprime chaque fichier créé par l'installation, même modifié depuis ;
- retire les clés de Probandia des réglages qu'il partage avec vous (`.codex/config.toml`, `opencode.json`) et
  garde toutes les autres, même une clé ajoutée après l'installation ; si personne n'a touché au fichier depuis
  l'installation, il remet la copie `.bak` faite avant elle ;
- supprime les dossiers créés par l'installation, quand ils sont vides.

Les fichiers installés désignent le moteur par son chemin absolu : réinstallez si vous déplacez le dépôt.
`python <chemin>/run_probandia.py doctor` vérifie le harnais, les clés, Python et les outils facultatifs.

### 1.2 La commande `probandia` dans un terminal

Le plugin n'a besoin de rien d'installé : les agents lancent le moteur par `run_probandia.py`, ou par le lanceur
court du projet, `.probandia/pb.py`. Pour taper `probandia` vous-même dans un terminal, installez la commande de
l'une de ces façons (`<chemin>` est le dossier du dépôt) :

| Façon | Installer | Mettre à jour | Désinstaller |
|---|---|---|---|
| sans installation | `python <chemin>/run_probandia.py --version` | `git -C <chemin> pull` | supprimer le dossier |
| `python -m probandia` | `<chemin>/src` dans `PYTHONPATH` : `PYTHONPATH=<chemin>/src python -m probandia --version` (PowerShell : `$env:PYTHONPATH = "<chemin>\src"`), ou l'une des installations ci-dessous | `git -C <chemin> pull` | supprimer le dossier |
| uv, une copie | `uv tool install <chemin>` | `uv tool install --force <chemin>` | `uv tool uninstall probandia` |
| uv, éditable | `uv tool install --editable <chemin>` | rien à faire ; après une modification de `pyproject.toml` : `uv tool install --editable --force <chemin>` | `uv tool uninstall probandia` |
| pipx | `pipx install <chemin>` | `pipx install --force <chemin>` | `pipx uninstall probandia` |
| pip, dans un environnement virtuel | `python -m venv .venv`, puis `.venv/bin/python -m pip install <chemin>` (Windows : `.venv\Scripts\python` ; Debian ou Ubuntu : `sudo apt install python3-venv` d'abord) | `python -m pip install --upgrade <chemin>` | `python -m pip uninstall probandia` |
| depuis PyPI, une fois la 1.0.0 publiée | `uv tool install probandia`, `pipx install probandia` ou `python -m pip install probandia` ; `uvx probandia` la lance sans l'installer | `uv tool upgrade probandia`, `pipx upgrade probandia`, `python -m pip install --upgrade probandia` | `uv tool uninstall probandia`, `pipx uninstall probandia`, `python -m pip uninstall probandia` |

Ensuite :

```sh
probandia --version
probandia doctor
```

- Si `probandia` est introuvable après une installation par uv, `uv tool update-shell` ajoute le dossier des
  outils uv au `PATH`.
- La commande installée et le plugin peuvent être de versions différentes. Les skills continuent d'appeler le
  moteur du plugin (`python .probandia/pb.py`, qui mène au `run_probandia.py` du plugin) ; la commande ne réécrit
  jamais le `.probandia/pb.py` d'un projet. `--version` donne la version de la commande, `doctor` lancé par l'agent
  celle du plugin.

Des options (*extras*) ajoutent des dépendances facultatives ; le moteur ne les importe jamais autrement :

| Option | Pour quoi | uv | pipx | pip |
|---|---|---|---|---|
| `tui` | [l'application dans un terminal](#11-lapplication-dans-un-terminal-tui) (Textual 8) | `uv tool install --force "<chemin>[tui]"` ; depuis PyPI : `uv tool install "probandia[tui]"` | `pipx install --force "<chemin>[tui]"` | `python -m pip install "<chemin>[tui]"` |
| `images` | Pillow, pour `image` (planches de vues, recadrages, rotations) | `uv tool install --force "<chemin>[images]"` ; dans le Python du moteur : `uv pip install --python <python> "Pillow>=12,<13"` | `pipx install --force "<chemin>[images]"` | `python -m pip install "<chemin>[images]"`, ou `python -m pip install "Pillow>=12,<13"` |
| `dev` | les tests et le lint (jsonschema, Pillow, ruff) | `uv pip install --editable "<chemin>[dev]"` | pas pour pipx | `python -m pip install --editable ".[dev]"`, depuis le dépôt |

Les options se combinent : `"<chemin>[tui,images]"`.

### 1.3 Travailler sur Probandia lui-même

- **Le moteur seul**, sans rien installer : `python <chemin>/run_probandia.py <commande>`, depuis un projet de
  test (`-p <dossier>` pour en désigner un autre). `tests/sample-project` est un projet d'exemple, régénéré par
  `python tools/make_sample_project.py` : ne le modifiez pas à la main.
- **OpenCode et agents Codex** : relancez `install --harness …` après une modification des skills, agents ou
  commandes, car ce sont des copies.
- **Après une modification de `agents/`, `commands/`, `skills/`, `hooks/hooks.json` ou
  `.claude-plugin/plugin.json`**, régénérez les fichiers des autres harnais par
  `python run_probandia.py manifests generate`, puis vérifiez-les par `python run_probandia.py manifests check`.

- **Les tests** : `python -m pip install --editable ".[dev]"`, puis `python tools/run_tests.py` ; `AGENTS.md`
  donne les autres vérifications.

## 2. Créer un projet et le régler

Un projet est un dossier qui contient `probandia.toml`. Il réunit les familles (`families/`), leurs recherches,
leurs preuves et leurs exports. Trois commandes créent un projet : `probandia init` (dans un terminal, il demande
les réglages essentiels), `probandia config init` (écrit `probandia.toml` sans rien demander) et `probandia new`,
qui crée le projet dans le dossier courant s'il n'y en a pas.

```powershell
mkdir ma-genealogie; cd ma-genealogie
probandia init
probandia config show         # les réglages en vigueur
```

Toutes les autres commandes s'exécutent depuis le dossier du projet ; `-p <dossier>` en désigne un autre. Hors
d'un projet, une commande qui en a besoin s'arrête avec le code 6.

### 2.1 Les réglages : `config`

`config` exige une action :

| Action | Exemple |
|---|---|
| `show` | `probandia config show --origin` (d'où vient chaque valeur) |
| `explain` | `probandia config explain cache.days` |
| `set` | `probandia config set search.max_parallel 5` |
| `unset` | `probandia config unset search.max_parallel` |
| `init` | `probandia config init` |
| `validate` | `probandia config validate` |
| `path` | `probandia config path` (les fichiers des sept couches) |
| `wizard` | `probandia config wizard` (les réglages essentiels, au clavier) |
| `edit` | `probandia config edit` (ouvre un fichier dans un éditeur, puis le vérifie) |
| `grade` | `probandia config grade advanced` |
| `diff` | `probandia config diff` (ce qui s'écarte des valeurs par défaut) |
| `roles` | `probandia config roles` (§ 2.3) |

Les couches s'appliquent dans cet ordre, la dernière l'emportant : valeur par défaut, harnais, utilisateur, projet,
local, variables d'environnement, arguments de la commande.

### 2.2 Les grades

Les réglages se répartissent en trois grades : `essential` (8 réglages), `advanced` (une vingtaine de plus) et
`expert` (tous). `config show` liste les réglages de votre grade ; `config grade advanced` en montre davantage. Un
réglage au-dessus de votre grade garde sa valeur par défaut. `probandia help grades` le rappelle.

À l'installation dans Claude Code, le plugin demande deux options : `language` (langue du rapport : `auto`, ou un
code comme `en` ou `fr`) et `run_mode` (qui mène une recherche : `ask`, `session`, `subagent` ou `team` ; `ask`
par défaut).

### 2.3 Le modèle et l'effort de chaque agent : `config roles`

Chaque rôle (`orchestrator`, `researcher`, `searcher`, `reader`, `investigator`, `contradictor`, `harvester`) a
deux réglages, `roles.<rôle>.model` et `roles.<rôle>.effort` :

```powershell
probandia config set roles.reader.model opus
probandia config roles        # le modèle et l'effort de chaque rôle, et la couche d'où vient chacun
```

Sans réglage, l'en-tête de l'agent décide ; l'option `--model` ou `--effort` d'une recherche (`new`) passe avant
pour l'`orchestrator`. Dans Claude Code, le garde réécrit l'appel de l'agent avec ces valeurs ; Codex les reçoit
dans ses fichiers d'agent à l'installation (`install --harness codex`), sous un nom de modèle propre à Codex ;
OpenCode aussi, sous la forme `fournisseur/modèle`. Ailleurs, le modèle par défaut du harnais s'applique. Deux
variables de Claude Code écrasent ces réglages, et `doctor` le signale : `CLAUDE_CODE_EFFORT_LEVEL` (un effort pour
tous les agents) et `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (un seul modèle pour tous). Un modèle plus faible que celui
par défaut pour le `reader` est permis, avec un avertissement : c'est sa lecture des actes qui porte la preuve.

## 3. Les clés et les quotas gratuits

Probandia cherche et lit le web par les **paliers gratuits** de fournisseurs (SerpApi, Serper, Brave, Exa, Tavily,
Jina Reader, Firecrawl…). Il ne paie jamais : un appel que le quota gratuit ne couvre pas n'est pas fait
(`STATUS=STOP`, code 4).

- Gemini, Exa, Parallel, Tavily, Linkup et ScrapeGraphAI peuvent, selon leurs conditions, réutiliser ce qu'on leur
  envoie (entraîner leurs modèles sur les requêtes) : ils restent éteints tant que `providers.allow_content_reuse`
  ne vaut pas `true`, et ne reçoivent jamais le nom d'une personne présumée vivante.
- Les clés vont dans un fichier `.env`, celui de l'utilisateur (à côté de son `config.toml`, voir `config path`) ou
  celui du projet (à côté de `probandia.toml`), lisible par son seul propriétaire. [`.env.example`](../.env.example)
  les liste toutes. Une clé n'est jamais affichée.
- `probandia keys` dit d'où vient chaque clé ; `keys check` les vérifie, `keys set SERPER_API_KEY` en écrit une
  (demandée au clavier), `keys unset` la retire, `keys signup <fournisseur>` indique où s'inscrire.
- `probandia -u` (`usage`) montre, compte par compte, ce qui reste, ce que cela paie et quand cela repart ;
  `usage --sync` relit les soldes chez les fournisseurs, sans frais. `probandia quota show` donne le reste en
  recherches et en pages ; `quota sync`, `quota add` et `quota estimate` le complètent.
- `probandia providers` liste le catalogue des offres gratuites ; `providers show serper`, `providers stale`,
  `providers enable` et `providers disable` le détaillent ou le règlent.
- `probandia cache stats` dit ce que le cache des réponses a épargné aux quotas ; `cache clear` le vide.
- Jina Reader fonctionne sans clé : on peut commencer avec peu de clés.

Un « négatif web » (« trouvé nulle part ») exige au moins deux familles d'index indépendantes ; un moteur dont la
réponse n'a rien à voir avec la requête ne compte pas.

## 4. Mener une recherche

Une recherche part d'une question et avance par **passes**. À chaque passe, l'agent planifie, cherche en parallèle,
propose des faits, puis les applique une fois acceptés.

### Dans l'agent (commandes slash)

```text
/probandia:new "Qui étaient les parents de Victor Hugo ?"
/probandia:resume <id>
/probandia:verify <id>
/probandia:close <id>
```

Le plugin a 19 commandes slash, du même nom que celles du terminal : `new`, `resume`, `fork`, `verify`,
`question`, `matrix`, `close`, `status`, `tree`, `export`, `import`, `import-gedcom`, `library`, `memory`,
`template`, `quota`, `config`, `doctor`, `watch`.

Deux préfixes choisissent qui mène la recherche, au début des arguments de `new` ou de `resume` :

- `seul :` (ou `solo:`) : l'agent de la session seul, comme `--mode session` ;
- `agents :` : une équipe d'agents, comme `--mode team`.

```text
/probandia:new seul : Où est mort Victor Hugo ?
/probandia:resume agents : 2026-10
```

`new` accepte aussi `--family <slug>`, `--mode session|subagent|team`, `--agents <n>`, `--model <modèle>`,
`--effort <niveau>`, `--passes <n>`, `--prompt-lang <tag>` et `--format md,html,json`. `resume` accepte
`--instructions "<texte>"` pour orienter la passe suivante.

Quand le moteur répond `STATUS=ASK`, l'agent vous pose la question et ne choisit jamais à votre place.

### Depuis un terminal

```powershell
probandia new "Qui étaient les parents de Victor Hugo ?"
probandia                     # écran d'accueil : recherches, propositions en attente, quotas, prochaines étapes
probandia -s                  # état : familles, recherches, passes ouvertes, verrous
probandia board               # où vous en êtes : la recherche suivie et sa passe, les quotas, les alertes
probandia verify 2026-10      # un identifiant de recherche, ou un préfixe unique
```

Dans un terminal, `new` demande qui mène la recherche, la crée sans ouvrir de passe, puis affiche la commande à
reprendre dans votre agent (`/probandia:resume <id>`).

- `probandia research list` liste les recherches ; `research show`, `log`, `pause`, `close` et `reopen` en donnent
  la fiche, le journal, ou la mettent en pause, la closent, la rouvrent.
- `probandia fork <id> --at 2 --name autre-piste` copie une recherche à une passe donnée pour la poursuivre à part.
- `probandia statusline` donne une ligne pour la barre d'état de Claude Code (recherche, passe, recherches web,
  quota) ; dans `settings.json` : `"statusLine": {"type": "command", "command": "probandia statusline"}`.

### Les agents

Une recherche mobilise des rôles distincts : l'orchestrateur, le chercheur (`researcher`), le *searcher*
(requêtes), le lecteur (`reader`), l'enquêteur (`investigator`), le contradicteur (qui examine les arguments) et le
moissonneur (`harvester`). Leur modèle et leur effort se règlent par `config roles` (§ 2.3).

### Questions, matrice et propositions

- `probandia question` liste, ajoute, modifie, répond, marque non résolue ou rouvre les questions d'une recherche.
- `probandia matrix` montre, pour chaque question, les types de sources attendus, ceux déjà consultés et ceux qui
  restent à faire ; `matrix justify` dit pourquoi l'un ne s'applique pas.
- `probandia proposals` liste les propositions en attente ; `proposals show <id>` en montre une, `apply` l'accepte,
  `drop` l'écarte.
- `probandia browser login <archive>` ouvre le navigateur local pour que vous vous connectiez à une archive qui
  le demande.

### Les confirmations

Avant de dépenser un quota gratuit (`search`, `read`, `archive run`) ou d'écrire ce qui se défait mal (`apply`,
`quota add`, un `export` qui remplace un fichier), la commande demande `[o/N]`. `--yes` (`-y`) répond à votre place ;
rien n'est demandé quand personne n'est au clavier.

## 5. Prouver : le Genealogical Proof Standard

Probandia suit les cinq éléments du GPS du *Board for Certification of Genealogists* :

1. une recherche raisonnablement exhaustive ;
2. des citations complètes et exactes ;
3. l'analyse et la corrélation des preuves ;
4. la résolution des preuves contradictoires ;
5. une conclusion solidement raisonnée.

`places guide`, `matrix`, `cite`, `correlate` et `proof` construisent chaque élément ; les règles V-14 à V-18 de
`verify` les contrôlent ; `close` clôt la recherche une fois ses questions tranchées et `verify` lancé.

```powershell
probandia verify 2026-10 --standard
```

affiche, pour chaque question, les cinq éléments (établi, partiel ou manquant) et ce qui manque à chacun. Avec le
réglage `proof.standard = strict`, une question non conforme garde la recherche ouverte.

### Citer le passage exact

Chaque fait peut citer mot pour mot le passage qu'il lit : des lignes d'une transcription
(`transcribe quote <source> --lines 3-5`) ou un passage d'une page (`read <url> --quote 2`). `apply` refuse un
passage introuvable mot pour mot, et la règle V-19 le revérifie à chaque `verify`.

`probandia fact check <fait> --by "<qui>" --looked "<ce qui a été regardé>"` consigne que vous avez regardé
vous-même l'acte sur lequel repose un fait.

Une page n'est conservée dans `evidence/pages/` de la famille que si son site est une archive du catalogue dont les
images sont libres ; sinon elle reste dans le `work/` de la recherche, sur votre ordinateur.

### La confiance

Chaque question répondue reçoit une confiance **calculée, jamais déclarée**, sur les quatre niveaux du `QUAY` de
GEDCOM : prouvée, probable, possible, non étayée. Elle part du fait le plus faible de la conclusion et perd un cran
pour une preuve indirecte (sauf argument accepté après examen du contradicteur), une information secondaire non
confirmée, une objection ouverte, un conflit de dates inexpliqué ou une question partiellement conforme. « Prouvée »
exige que le passage de l'acte soit cité. Elle n'empêche rien, mais apparaît dans `verify --standard`, le rapport et
l'export GEDCOM.

Probandia aide à montrer une preuve ; il ne remplace pas le jugement du généalogiste.

## 6. Ce que la famille sait déjà

Ces commandes lisent les index des familles, sans rien écrire :

| Commande | Ce qu'elle montre |
|---|---|
| `probandia family list`, `family show <famille>` | les familles et leur fiche |
| `probandia find "Hugo"` | une personne dans toutes les familles, avec les variantes orthographiques |
| `probandia person <id>` | la fiche d'une personne : faits et sources, proches, hypothèses, négatifs, lacunes |
| `probandia searches --person <id>` | ce qui a déjà été cherché, où, et ce que cela a donné |
| `probandia sources` | les sources des familles, avec leurs citations |
| `probandia negatives` | les recherches négatives, et s'il faut les refaire |
| `probandia hypotheses` | les hypothèses, ouvertes et closes |
| `probandia gaps` | les lacunes des archives : registres perdus ou non filmés |

## 7. Arbres, rapports, exports et imports

- `probandia tree` écrit l'arbre de la famille dans `families/<famille>/trees/` (`--format html`, `md` ou `all`).
- `probandia report open` ouvre le rapport d'une recherche dans le navigateur (`-r` en raccourci), `report show`
  l'affiche, `report render` le génère ; il est écrit dans `families/<famille>/research/<id>/report/`
  (`report.html`, `report.md`, `report.json`).
- `probandia export` exporte en GEDCOM 7, en GEDCOM 5.5.1 ou vers Gramps Web, dans `exports/` ; les personnes
  présumées vivantes sont masquées par défaut (`--living mask`), ou écartées (`export gedcom7 --living exclude`).
- Le rapport HTML suit un **modèle** : un fichier `.html` sans script ni ressource venue du réseau, imprimable tel
  quel.
  - Modèles fournis (`probandia template list`) : `habillage`, le modèle par défaut, puis `default` (le plus sobre),
    `family-book`, `high-contrast`, `print`.
  - **Les vues des actes.** Après la liste des sources, le rapport montre la vue de chaque acte qui prouve un fait
    (un fait lu sur son image), réduite à 1 200 pixels (avec Pillow ; sans lui, le fichier tel quel). La règle est
    celle de l'export GEDCOM : aucun acte d'une personne vivante, et seulement une source dont les `rights` valent
    `free` ; une vue écartée est nommée, avec son fichier et la raison. Le réglage `report.images` dit où elles
    vont : `folder` (par défaut), des fichiers de `report/views/`, à côté de `report.html`, qui les appelle par un
    chemin relatif, autant que la recherche en a (copiez le dossier `report/` entier pour partager le rapport) ;
    `inline`, dans `report.html` en `data:`, tant que la page reste sous 1 Mo (la limite d'un modèle) : un seul
    fichier, mais quelques vues seulement ; `off`, aucune.
  - `probandia template designer` ouvre l'éditeur de modèles dans le navigateur, hors ligne ; téléchargez le modèle
    puis `probandia template import mon-modele.html`.
  - `probandia template use family-book` le choisit pour le projet (`--level family`, `research` ou `user` pour une
    autre portée), puis `probandia render --all`.
- Pour partir d'un arbre existant : `probandia import-gedcom <fichier>` place le contenu d'un fichier GEDCOM dans la
  zone d'attente, à valider avant qu'il n'entre dans la famille.
- `probandia import <dossier>` importe un atelier dans son propre format (`commun/personnes.yaml`, ses rapports et
  ses collecteurs) ; `--dry-run` montre ce qui serait importé.

## 8. Ce que Probandia apprend : bibliothèque et mémoire

### La bibliothèque

Probandia garde ce que les agents apprennent : scripts qui lisent une archive, requêtes qui ont marché (recettes)
et, après votre accord, skills et sous-agents. Elle existe au niveau du projet (`library/`) et de l'utilisateur.

- En fin de passe, l'agent vous demande une seule fois quels éléments garder.
- `library list`, `library find`, `library show`, `library promote <id> --to user` (pour tous vos projets).
- Une skill ou un agent appris n'est installé qu'après lecture et accord :
  `library install <id> --scope project|user --for <harnais>` ; `library uninstall` le retire exactement.
- `library export lot.zip --ids …` et `library import lot.zip` partagent des éléments entre projets.
- Un script appris ne tourne qu'avec un confinement réseau dans son propre processus, sans bac à sable du système :
  lisez-le avant de lui faire confiance (`library trust`).

### La mémoire

Les décisions de travail du projet (conventions, modèle de rapport, fournisseurs retenus, archives qui demandent une
connexion, préférences, pièges d'une source) sont consignées dans une section de `AGENTS.md`, entre
`<!-- probandia:begin -->` et `<!-- probandia:end -->`.

- Rien n'y est écrit sans votre accord : `memory add "<une ligne>" --kind provider`.
- Jamais de faits généalogiques, de personnes présumées vivantes ni de clés.
- La section reste courte (40 lignes, 2 Ko) : fusionnez (`--supersedes M2,M3`) ou archivez dans
  `memory-archive.md`.
- `memory list`, `memory remove M3`, `memory sync`.

## 9. Archives et veille des sources

- Le [guide des archives ouvertes](open-archives.md) décrit les conditions d'accès de Matricula, Delpher, DDB,
  Mémoire des hommes, Léonore, Arolsen et des Archives de l'État en Belgique.
- `archive find "Arolsen"` pour un accès par le navigateur ; `archive run ddb.search --args '{"query":"Goethe","max":20}'`
  pour l'API publique de la DDB.
- `probandia watch` rejoue le témoin de chaque connecteur d'archive (une petite recherche dont la réponse est
  connue) et liste les entrées des catalogues vérifiées il y a plus de 90 jours (`catalogues.max_age_days`). Rien
  n'est payé.
- `probandia watch --print-schedule` affiche la commande `schtasks` (ou la ligne crontab) pour la lancer chaque
  lundi ; exécutez-la vous-même.

### Archives derrière une connexion

Certaines archives (FamilySearch…) ne montrent leurs actes qu'à un utilisateur connecté. Vous vous connectez
vous-même ; l'agent ne tape jamais de mot de passe. Le plus simple est de laisser l'agent piloter **votre propre
navigateur**, où vous vous connectez une fois : rien à installer dans Probandia, pas besoin de Playwright.

| Agent | Votre navigateur, piloté par l'agent | Vos connexions |
|---|---|---|
| Claude Code | [Claude in Chrome](https://code.claude.com/docs/en/chrome) : l'extension Chrome, puis `claude --chrome`, ou `/chrome` dans une session (Chrome ou Edge ; offre Pro, Max, Team ou Enterprise ; pas sous WSL) | partagées |
| Codex, Factory Droid, Grok Build, OpenCode | [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) avec `--autoConnect` (Chrome 144 ou plus récent, débogage à distance activé dans `chrome://inspect/#remote-debugging`), par exemple `codex mcp add chrome-devtools -- npx chrome-devtools-mcp@latest --autoConnect` (sous Windows, `cmd /c npx` au lieu de `npx`) | partagées : l'agent voit toutes les fenêtres ouvertes de ce Chrome |
| Cursor, Antigravity | leur navigateur intégré | son propre profil : connectez-vous-y |

L'agent s'arrête sur la page de connexion et vous attend. Sinon, `probandia browser login <archive>` ouvre le
navigateur du moteur, qui demande Playwright (§ 1, Prérequis).

## 10. La commande dans un terminal

### Deux lecteurs

À un terminal, la commande affiche un écran lisible, en couleur, paginé s'il est long. Redirigée ou lancée par un
agent, elle imprime le **contrat** : une ligne `CLÉ=valeur` par ligne, en commençant par `STATUS=`, 40 lignes au
plus.

- Forme : `--output-format human|contract|json` ou `PROBANDIA_OUTPUT` ; `--json` équivaut à `--output-format json`.
- Couleur : `NO_COLOR=1` ou `--no-color` ; `--plain` se limite en plus à l'ASCII.
- Pagination : `PROBANDIA_PAGER` (`none` la désactive).
- Langue : `-l fr`, `--lang fr` ou `PROBANDIA_LANGUAGE=fr` ; anglais par défaut.

### Options courtes

`-u` (`usage`), `-s` (`status`), `-r` (`report open`), `-p <dossier>`, `-l fr`, `-q` (seulement `STATUS` et
`DETAILS`), `-y` (`--yes`), `-w` (`--watch`, sur `status` et `usage`), `-V`, `-h`.

### Aide et complétion par Tab

`probandia help <sujet>` donne une page courte : `quotas`, `negatives`, `grades`, `exit-codes`, `files`.
`probandia help <commande>` ou `probandia <commande> --help` décrit une commande.

```powershell
# dans $PROFILE
probandia completion powershell | Out-String | Invoke-Expression
```

Pour bash : `eval "$(probandia completion bash)"` dans `~/.bashrc` (aussi `zsh`, `fish`).

### Codes de sortie

- 0 : terminé (`STATUS=OK` ou `WARN`)
- 1 : échec (une règle de vérification, une proposition refusée)
- 2 : erreur d'usage ou de configuration
- 3 : une question attend une réponse (`STATUS=ASK`)
- 4 : arrêt (quota gratuit ou plafond atteint, ou refus de votre part ; `STATUS=STOP`)
- 5 : verrouillé par une autre session
- 6 : hors d'un projet
- 7 : erreur réseau ou de fournisseur
- 10 : erreur interne (détails dans le journal)
- 130 : interrompu (Ctrl+C)

```powershell
probandia verify 2026-10 -q
if ($LASTEXITCODE -eq 1) { "une règle de vérification a échoué" }
probandia -u --json > quotas.json
```

### Outils du généalogiste

Utilisables hors recherche :

- `probandia dates` analyse et convertit des dates généalogiques.
- `probandia variants` donne les variantes orthographiques d'un nom.
- `probandia places` traite les noms de lieux historiques.
- `probandia cite` rédige la phrase de citation d'une source.

## 11. L'application dans un terminal (TUI)

`probandia tui` ouvre une application dans le terminal ; elle demande l'option `tui` (§ 1.2), par exemple
`uv tool install --editable "<chemin>[tui]"`. Elle a six écrans, chacun sur sa touche :

| Touche | Écran | Ce qu'il montre |
|---|---|---|
| `1` | Accueil | les recherches, les derniers événements de celle choisie, les comptes les plus bas et les alertes |
| `2` | Quotas | les quotas gratuits des comptes, les fournisseurs et leurs clés |
| `3` | Recherches | chaque recherche : sa fiche, son journal, son rapport et son équipe |
| `4` | Famille | l'arbre de la famille, ses personnes et leurs faits |
| `5` | Propositions | les propositions en attente, lues puis acceptées (`a`) ou écartées (`x`) |
| `6` | Config | les réglages, la bibliothèque de scripts et le diagnostic |

`Ctrl+P` ouvre la palette : un écran, ou le formulaire d'une commande. La console remplit une commande dans son
formulaire, et `Ctrl+R` l'exécute sans quitter l'application. `[` et `]` changent d'onglet, `/` filtre une liste,
`s` relit les soldes, `r` rafraîchit, `t` bascule le thème clair ou sombre (gardé), `?` liste toutes les touches,
`q` quitte. L'application n'écrit rien elle-même : chaque action exécute une commande du moteur.

## 12. Aide-mémoire

```powershell
probandia doctor                 # tout est-il en place ?
probandia                        # écran d'accueil
probandia -u                     # quotas gratuits
probandia init                   # créer un projet ici
probandia new "<question>"       # nouvelle recherche (crée le projet s'il manque)
probandia -s                     # état du projet
probandia board                  # où j'en suis
probandia person <id>            # ce que l'on sait d'une personne
probandia verify <id> --standard # les cinq éléments du GPS
probandia close <id>             # clore
probandia tree                   # arbre de la famille
probandia export gedcom7         # export GEDCOM 7
probandia tui                    # l'application dans le terminal
probandia help <sujet>           # quotas, negatives, grades, exit-codes, files
probandia --help --all           # toutes les commandes, y compris celles du moteur
```
