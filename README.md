# Probandia

Nothing is concluded until it is proven.

A genealogy research plugin for AI coding agents. Ask your agent a question
about a family; Probandia runs the research by the Genealogical Proof Standard:
it plans the searches, reads the archives and the web on free resources only,
cites every fact on its source, and writes a report, a tree and a GEDCOM 7
export. The plugin brings slash commands (`/probandia:new`, `/probandia:resume`,
`/probandia:status`…), skills, seven agent roles, hooks that keep the rules, and
an MCP server (not in Claude Code, Grok Build and Factory Droid, whose skills
call the engine through the shell); the [plugin surface](#the-plugin-surface)
lists them all. Its engine, `run_probandia.py`, needs only Python 3.11 or later.

En français : [guide d'utilisation](https://github.com/devohmycode/probandia/blob/master/guides/guide-utilisation.md).

Contents: [Requirements](#requirements) ·
[Install the plugin](#install-the-plugin) ·
[Install the command](#install-the-command) ·
[First research](#first-research) · [Use the command](#use-the-command) ·
[Command reference](#command-reference) ·
[The plugin surface](#the-plugin-surface) ·
[Projects and settings](#projects-and-settings) ·
[Model and effort of each agent](#model-and-effort-of-each-agent) ·
[Privacy and security](#privacy-and-security) ·
[Proving a conclusion](#proving-a-conclusion-the-genealogical-proof-standard) ·
[Providers](#providers) · [The terminal interface](#the-terminal-interface) ·
[Development](#development)

## Requirements

- **Systems**: Windows and Linux, tested by the CI at each change (Windows with
  Python 3.11 and 3.14, Ubuntu with Python 3.11, 3.12, 3.13 and 3.14). macOS:
  not tested.
- **Python 3.11 or later, callable as `python`**: the hooks of Claude Code
  and Codex take `python`, else `python3` (on Windows, `python` only; Claude
  Code runs them in Git Bash there); the MCP server and the hooks of Cursor
  and Antigravity run `python`, with no fallback. `probandia doctor` says when
  `python` is missing. On Debian or Ubuntu, `sudo apt install
  python-is-python3` gives that name; on Windows, the installer of python.org
  with "Add python.exe to PATH".
- **Claude Code on Windows: Git Bash.** Without it, Claude Code runs the hooks
  in PowerShell, where they fail: install Git for Windows, or point
  `CLAUDE_CODE_GIT_BASH_PATH` to its `bash.exe`. `probandia doctor` says when
  it finds none (`GIT_BASH=missing`).
- Nothing else is needed: the engine uses the standard library and carries its
  few dependencies in `src/probandia/_vendor`.

Optional tools, which `probandia doctor` checks and installs nothing itself:

| Tool | What for | Install |
|---|---|---|
| Playwright | a headless browser, for pages that need one | `python -m pip install playwright && python -m playwright install chromium` |
| Tesseract | OCR of printed records (`transcribe ocr`) | Windows: `winget install UB-Mannheim.TesseractOCR` or `scoop install tesseract`; Linux: `sudo apt install tesseract-ocr tesseract-ocr-fra`; macOS: `brew install tesseract tesseract-lang` |
| Pillow | sheets of views, crops and turns of images (`image`) | `python -m pip install "Pillow>=12,<13"`, or the `images` extra (below) |

## Install the plugin

The repository, `https://github.com/devohmycode/probandia`, is both the plugin
and its marketplace. Claude Code, Grok Build and Factory Droid install it
straight from GitHub. Codex, Antigravity, OpenCode and Claude Desktop install it
from a clone, whose folder is `<path>` below:

```sh
git clone https://github.com/devohmycode/probandia
cd probandia
```

On Windows, clone it into a short folder (`C:\Users\<you>\probandia`, not a
deep one): a few files of `bench/` have paths of 163 characters, and Windows
refuses paths longer than 260.

| Harness | Support | MCP server | Install |
|---|---|---|---|
| Claude Code (terminal, IDE, desktop app) | full | no: its skills call the engine through the shell | `/plugin marketplace add devohmycode/probandia` |
| Grok Build | full | no: it reads `.claude-plugin/` | `grok plugin install devohmycode/probandia --trust` |
| Codex | full | yes (`mcp.json`) | `codex plugin marketplace add <path>`, then `install --harness codex` (plugin and seven agents) |
| Cursor | full | yes (`cursor/mcp.json`) | `git clone` into `~/.cursor/plugins/local/probandia` |
| Factory Droid | full | no: the plugin root is not expanded in its MCP settings | `droid plugin marketplace add https://github.com/devohmycode/probandia` |
| Antigravity | beta | yes (`mcp_config.json`) | `agy plugin install <path>` |
| OpenCode | reduced | yes, merged into `opencode.json` | `install --harness opencode` |
| Claude Desktop (chat) | MCP server only | yes, the only part | `claude_desktop_config.json` |

Each section says when, and with which version, it was replayed.
Every way runs the engine from the repository's folder: keep it where it is,
and update it (`git pull`) before updating the plugin.

### Claude Code

Full support, without the MCP server. Verified on 21 October 2026 with Claude Code 2.1.304 and 2.1.306, in a
configuration of its own (`CLAUDE_CONFIG_DIR`): install from the repository's
folder, a research run to its end, update and uninstall, which leaves
`"enabledPlugins": {}` and Claude Code's copy of the plugin in its cache;
the MCP server alone was listed connected, then removed. Verified on 24 October
2026 with Claude Code 2.1.306, from GitHub: marketplace added, plugin
installed (1.0.0) and enabled, marketplace updated, then both removed. In a
session (or the same words after `claude plugin` in a terminal):

Install, from GitHub:

```text
/plugin marketplace add devohmycode/probandia
/plugin install probandia@probandia
```

From a clone, the first line is `/plugin marketplace add <path>`.

Update:

```text
/plugin marketplace update probandia
/plugin update probandia@probandia
```

Uninstall:

```text
/plugin uninstall probandia@probandia
/plugin marketplace remove probandia
```

Run a research:

```text
/probandia:new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

`claude --plugin-dir <path>` loads the folder for one session, without
installing it.

The MCP server alone, without the plugin: the engine's 17 tools
in Claude Code, without the slash commands, skills, agents or hooks. Declare it
from the project's folder:

```sh
claude mcp add probandia -- python <path>/run_probandia.py mcp
```

Once 1.0.0 is on PyPI, without the repository:
`claude mcp add probandia -- uvx probandia mcp` (on Windows, `cmd /c uvx`
instead of `uvx`). `claude mcp remove probandia` takes it out.

### Grok Build

Full support, without the MCP server: Grok Build reads the Claude Code layout
(`.claude-plugin/`). Its plugin options (`/config`) are ignored: settings come
from the files (see [Projects and settings](#projects-and-settings)).
Verified on 17 October 2026 with Grok Build 1.0.62: install from the
repository's folder, `doctor` run in the harness names it, the status command
answers `STATUS=OK`, and the uninstall leaves its configuration files as they
were.

Install, from GitHub (`grok plugin install` takes a git URL, `user/repo` or a
local path):

```sh
grok plugin install devohmycode/probandia --trust
```

From a clone: `grok plugin install <path> --trust`.

Update: installed from GitHub, this command fetches the new version. A local
path is installed as a link, so `git pull` in `<path>` is enough, and the same
command says so:

```sh
grok plugin update probandia
```

Uninstall:

```sh
grok plugin uninstall probandia
```

Run a research (the form of `/probandia:status`, verified):

```text
/probandia:new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Codex

Full support, with the MCP server. Codex plugins hold skills but no subagents:
the installer also writes the seven roles as custom agents. Run it from your
research project's folder (or pass `--path <project-folder>`).
Verified on 17 October 2026 with Codex 0.161.0: install from the repository's
folder, `doctor` run in the harness names it, the status command answers
`STATUS=OK`, and the uninstall leaves its configuration files as they were.
Verified on 21 October 2026 with Codex 0.161.0, in a new project: the
marketplace added as below is listed, the plugin is installed and enabled, the
reader agent starts, and the contradictor runs the engine in its read-only
sandbox.

Install: add the repository as a marketplace (Codex reads none from a project's
settings), write the agents, then add the plugin, from the project's folder:

```sh
codex plugin marketplace add <path>
python <path>/run_probandia.py install --harness codex
codex plugin add probandia@probandia
```

The first command writes the marketplace into your Codex settings
(`~/.codex/config.toml`); the installer enables the plugin in the project's
`.codex/config.toml` and writes the seven custom agents as
`.codex/agents/probandia-<role>.toml`. Existing Codex settings are kept. Reopen Codex in this folder, trust the project, and start a
new chat; approve the plugin hooks in `/hooks` if Codex asks. The agents use
Codex's TOML format (`name`, `description`, `developer_instructions`,
`model_reasoning_effort`), inherit your model unless you chose one (see
[Model and effort of each agent](#model-and-effort-of-each-agent)), and set the
contradictor to `sandbox_mode = "read-only"`. See the official
[custom agent format](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and [project plugin configuration](https://developers.openai.com/plugins/build/plugins).
If you installed the plugin through Codex's marketplace already,
`install --harness codex-agents` installs only the roles.

Update: `git pull` in `<path>`, then the same command again, which
rewrites the agents:

```sh
python <path>/run_probandia.py install --harness codex
```

Uninstall: `codex plugin remove` takes the plugin out of `~/.codex/config.toml`
and of Codex's cache, `--uninstall` removes what the installer wrote, and the
last command takes the marketplace out of your settings:

```sh
codex plugin remove probandia@probandia
python <path>/run_probandia.py install --harness codex --uninstall
codex plugin marketplace remove probandia
```

Run a research (the same request for `status`, verified): the Codex plugin
brings skills, not slash
commands; ask in the chat, and the `engine` skill runs `new`:

```text
Start a Probandia research: who were the parents of Victor Hugo, born in 1802 in Besançon?
```

### Cursor

Full support, with the MCP server (`cursor/mcp.json`). Cursor loads a local
plugin from `~/.cursor/plugins/local/<name>`, a folder of its own: it rejects
a link to a folder elsewhere ("symlink target … is outside"). Then restart
Cursor, or run "Developer: Reload Window" (on Teams and Enterprise, an admin
must allow local plugin imports). `cursor-agent --plugin-dir <path>` loads the
folder for one session.
Cursor shows a plugin's commands only while its option for third-party
plugins, skills and other configs is on. With that option on, it also imports
the plugins of Claude Code: when Probandia is installed there too, disable it
in Claude Code (`claude plugin disable probandia@probandia`), or Cursor shows
that copy (its commands without a prefix, `/status`) instead of this one.
Verified on 22 October 2026 with Cursor 3.27.6 (the editor): installed as a
clone, Cursor lists it as a local plugin (0.9.41) with its 19 commands, and
`/probandia-status` is offered in the chat; on 21 October 2026, with Cursor
3.26.13, the MCP server listed its 17 tools and `dates` answered, `doctor`
named Cursor, and a fork there left the original as it was.

Install, a clone of the repository:

```sh
git clone https://github.com/devohmycode/probandia ~/.cursor/plugins/local/probandia
```

```powershell
git clone https://github.com/devohmycode/probandia "$HOME\.cursor\plugins\local\probandia"
```

Update: `git pull` in the clone, then reload the window:

```sh
git -C ~/.cursor/plugins/local/probandia pull
```

Uninstall: remove the clone:

```sh
rm -rf ~/.cursor/plugins/local/probandia
```

```powershell
Remove-Item -Recurse -Force "$HOME\.cursor\plugins\local\probandia"
```

Run a research. Cursor names a plugin's commands without a prefix, so
Probandia's carry one (`cursor/commands/`), away from Cursor's own and other
plugins' (`/probandia-status`, `/probandia-resume`…):

```text
/probandia-new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Factory Droid

Full support, without the MCP server: the plugin root is not expanded in
Droid's MCP settings, so the skills call the engine through the shell. Droid
reads the repository's marketplace (`.claude-plugin/marketplace.json`), and
names it after the folder: for a folder not named `probandia`, write
`probandia@<folder-name>` and `marketplace remove <folder-name>` below.
Verified on 17 October 2026 with Factory Droid 0.242.0: install from the
repository's folder, `doctor` run in the harness names it, the status command
answers `STATUS=OK`, and the uninstall takes everything out but an empty
`"enabledPlugins": {}` in `~/.factory/settings.json` and empty folders in
`~/.factory/plugins/cache/`. The update was verified on 21 October 2026 with Factory
Droid 0.245.1.

Install, from GitHub:

```sh
droid plugin marketplace add https://github.com/devohmycode/probandia
droid plugin install probandia@probandia --scope user
```

From a clone: `droid plugin marketplace add <path>`.

Update:

```sh
droid plugin marketplace update probandia
droid plugin update probandia@probandia --scope user
```

Uninstall:

```sh
droid plugin uninstall probandia@probandia --scope user
droid plugin marketplace remove probandia
```

Run a research (verified on 21 October 2026: asked in words, it runs the
command file; `droid exec` does not expand slash commands), as Droid names a command file
(`commands/new.md` becomes `/new`). Droid reads a plugin's commands from its
`commands/` folder only, shared with Claude Code: they keep their short names
(`/new`, `/status`, `/resume`…), which a command of Droid's own or of another
plugin may take first; then ask in words ("run Probandia's status"). Otherwise:

```text
/new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Antigravity

Beta support, with the MCP server, declared in `mcp_config.json` (the root
`plugin.json` declares none). Antigravity starts the server in the plugin's
folder: the server then asks the client for its roots (MCP `roots/list`) and
works in the first one that holds a project.
Verified on 17 October 2026 with Antigravity 1.4.0: install from the
repository's folder, `doctor` run in the harness names it, the status command
answers `STATUS=OK`, and the uninstall leaves its configuration files as they
were. Its install reported "agents: skipped (not found)": since 23 October 2026
(agy 1.4.6), `agy plugin validate .` counts the seven agents of `agents/`, which
take the session's model.

Install:

```sh
agy plugin install <path>
```

Update: `git pull` in `<path>`, then install again:

```sh
agy plugin install <path>
```

Uninstall:

```sh
agy plugin uninstall probandia
```

Run a research (the form of `/status`, verified):

```text
/new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### OpenCode

Reduced support, with the MCP server. OpenCode has no package format: the
installer copies the skills, the agents and the commands (as
`probandia-<name>.md`), merges the MCP server into `opencode.json` (keeping a
`.bak` copy) and adds a small JS plugin for the hooks.
Verified on 17 October 2026 with OpenCode 1.18.29: install from the
repository's folder, `doctor` run in the harness names it, the status command
answers `STATUS=OK`, and the uninstall leaves its configuration files as they
were (`--scope user`; the skills go to `~/.agents/skills/`).

Install, for your user or for the current project:

```sh
python <path>/run_probandia.py install --harness opencode
python <path>/run_probandia.py install --harness opencode --scope project
```

Update: `git pull` in `<path>`, then the same command again:

```sh
python <path>/run_probandia.py install --harness opencode
```

Uninstall, with the same `--scope` as the install:

```sh
python <path>/run_probandia.py install --harness opencode --uninstall
```

Run a research (the form of `/probandia-status`, verified):

```text
/probandia-new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
```

### Claude Desktop

The MCP server only: Claude Desktop (the chat, not Claude Code) runs MCP
servers but no plugin. It gets the engine's tools (search, read, what is
known, verify…) without the slash commands, skills, agents or hooks. Verified on
21 October 2026: added to `claude_desktop_config.json`, its `dates` tool
answers in a chat; removed, after a restart.

Install: add the server to `claude_desktop_config.json`
(Settings › Developer › Edit Config), with the project folder it works in, then
restart Claude Desktop:

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

Update: `git pull` in `<path>`, then restart Claude Desktop:

```sh
git -C <path> pull
```

Uninstall: remove the `"probandia"` entry from `mcpServers`,
then restart Claude Desktop:

```json
{
  "mcpServers": {}
}
```

Run a research: MCP tools only. Ask in the chat; Claude calls the tools of
[the MCP server](#the-plugin-surface) (`plan`, `search`, `read`, `propose`,
`verify`…) in the project of `PROBANDIA_PROJECT`.

### What `--uninstall` does

Each `install --harness` records what it wrote, in `.probandia-install.json`
(in `.codex/` for Codex; in OpenCode's configuration folder, or the project's,
for OpenCode). `--uninstall` reads that record and:

- deletes each file the install created, even one you edited since;
- takes Probandia's keys out of the settings it shares with you
  (`.codex/config.toml`, `opencode.json`) and keeps every other key, even one
  you added after the install; when no one changed that file since the
  install, it puts back the `.bak` copy made before it;
- removes the folders the install created, when they are empty.

Installed files name the engine by its absolute path: install again if you
move the repository. `python <path>/run_probandia.py doctor` checks the harness,
the keys, Python and the optional tools.

## Install the command

The plugin needs nothing installed: agents run the engine through
`run_probandia.py`, or the project's short launcher `.probandia/pb.py`. To type
`probandia` in a terminal yourself, install the command one of these ways
(`<path>` is the repository's folder):

| Way | Install | Update | Uninstall |
|---|---|---|---|
| no install | `python <path>/run_probandia.py --version` | `git -C <path> pull` | delete the folder |
| `python -m probandia` | `<path>/src` on `PYTHONPATH`: `PYTHONPATH=<path>/src python -m probandia --version` (PowerShell: `$env:PYTHONPATH = "<path>\src"`), or any install below | `git -C <path> pull` | delete the folder |
| uv, a copy | `uv tool install <path>` | `uv tool install --force <path>` | `uv tool uninstall probandia` |
| uv, editable | `uv tool install --editable <path>` | nothing to do; after a change to `pyproject.toml`: `uv tool install --editable --force <path>` | `uv tool uninstall probandia` |
| pipx | `pipx install <path>` | `pipx install --force <path>` | `pipx uninstall probandia` |
| pip, in a virtual environment | `python -m venv .venv`, then `.venv/bin/python -m pip install <path>` (Windows: `.venv\Scripts\python`; Debian or Ubuntu: `sudo apt install python3-venv` first) | `python -m pip install --upgrade <path>` | `python -m pip uninstall probandia` |
| from PyPI, once 1.0.0 is published | `uv tool install probandia`, `pipx install probandia` or `python -m pip install probandia`; `uvx probandia` runs it without installing | `uv tool upgrade probandia`, `pipx upgrade probandia`, `python -m pip install --upgrade probandia` | `uv tool uninstall probandia`, `pipx uninstall probandia`, `python -m pip uninstall probandia` |

Then:

```sh
probandia --version
probandia doctor
```

- If `probandia` is not found after a uv install, `uv tool update-shell` adds
  uv's tool folder to the `PATH`.
- The installed command and the plugin may be different versions. The skills
  keep calling the plugin's engine (`python .probandia/pb.py`, which leads to
  the plugin's `run_probandia.py`); the command never rewrites a project's
  `.probandia/pb.py`. `--version` tells the command's version, `doctor` run by
  the agent tells the plugin's.

Extras add optional dependencies; the engine never imports them otherwise:

| Extra | What for | uv | pipx | pip |
|---|---|---|---|---|
| `tui` | [the terminal interface](#the-terminal-interface) (Textual 8) | `uv tool install --force "<path>[tui]"`; from PyPI: `uv tool install "probandia[tui]"` | `pipx install --force "<path>[tui]"` | `python -m pip install "<path>[tui]"` |
| `images` | Pillow, for `image` (sheets of views, crops, turns) | `uv tool install --force "<path>[images]"`; into the engine's own Python: `uv pip install --python <python> "Pillow>=12,<13"` | `pipx install --force "<path>[images]"` | `python -m pip install "<path>[images]"`, or `python -m pip install "Pillow>=12,<13"` |
| `dev` | the tests and the lint (jsonschema, Pillow, ruff) | `uv pip install --editable "<path>[dev]"` | not for pipx | `python -m pip install --editable ".[dev]"`, from the repository |

Extras combine: `"<path>[tui,images]"`.

## First research

1. **A project folder.** Make an empty folder and open your harness in it:
   `/probandia:new` makes it a project (`probandia.toml`) on its first run.
   At a terminal, `probandia init` does it alone, and asks the essential
   settings.
2. **Keys.** Probandia searches the web with the harness's own web search and
   the free tiers of [the providers](#providers). Without any key, a research
   runs on the harness's web search, the open archives' APIs and Jina Reader
   (which reads pages without a key). Each key adds a free tier:

   ```sh
   probandia keys                       # where each key comes from, or that it is missing
   probandia keys signup tavily         # the page where the free account is made
   probandia keys set TAVILY_API_KEY    # asks the value at the keyboard, writes it to your .env
   probandia keys check                 # reads, for free, the account of each key set
   ```

3. **Start a research.** In your agent (the form of the command for each
   harness is in [Install the plugin](#install-the-plugin)):

   ```text
   /probandia:new "Who were the parents of Victor Hugo, born in 1802 in Besançon?"
   ```

   It asks who runs the research: the session's agent, a subagent, or a team.
   Start the question with `seul :` (or `solo:`) for the session's agent alone,
   with `agents :` for a team, or pass `--mode session|subagent|team`.
4. **Continue.** Each pass ends with what it found and what is left;
   `/probandia:resume` runs the next pass (`/probandia:resume <research>` for
   another one).
5. **Where it stands.** `/probandia:status`, or in a terminal:

   ```sh
   probandia status
   ```

6. **What it writes**, in the project folder:
   - the report: `families/<family>/research/<research>/report/report.html`
     (and `report.md`, `report.json`); `probandia report open` opens it;
   - the tree: `families/<family>/trees/tree.html` (and `tree.md`,
     `ancestors.svg`, `descendants.svg`), written by `probandia tree`;
   - the export: `exports/<family>-<date>.gdz` (GEDCOM 7 with its media), by
     `probandia export gedcom7`.
7. **Check a fact on its image.** A finding counts only once it has been read
   where it is written. Open
   [`examples/hugo/death-1885-paris-16-546.jpg`](https://github.com/devohmycode/probandia/blob/master/examples/hugo/death-1885-paris-16-546.jpg),
   the death act of Victor Hugo: it is dated 23 May 1885 and says he died "hier
   au soir", the day before: **22 May 1885**. The date of a death is often not
   the date of its act. His birth act gives a Republican date, which the engine
   converts:

   ```sh
   probandia dates "7 ventôse an X"
   ```

   It answers `ISO=1802-02-26`. The records, their rights and their credit are in
   [`examples/hugo/README.md`](https://github.com/devohmycode/probandia/blob/master/examples/hugo/README.md).

## Use the command

In a project folder (the one that holds `probandia.toml`):

```sh
probandia                       # at a terminal, the welcome screen: researches, proposals waiting, lowest quotas, next steps
probandia -u                    # the free quotas, account by account (probandia usage)
probandia -s                    # status: families, researches, open passes, locks
probandia verify 2026-09        # a research id, or a unique prefix of one
probandia known 2026-09         # what the family already knows: facts, negatives, hypotheses, gaps
probandia help exit-codes
```

- `new` asks who runs the research, creates it and opens no pass at a terminal:
  continue in your agent with the command it prints (`/probandia:resume <id>`).
- Shortcuts: `-u` (`usage`), `-s` (`status`), `-r` (`report open`). Short
  options: `-p <folder>` (another project), `-l fr` (French), `-q`, `-y`
  (`--yes`), `-w` (`--watch`, on `status` and `usage`), `-V`, `-h`.
- Before spending a free quota (`search`, `read`, `archive run`) or writing what
  is hard to undo (`apply`, `quota add`, an `export` that replaces a file), the
  command asks `[y/N]`; `--yes` answers for you. Nothing is asked when no one is
  at the keyboard.
- Tab completion: add `probandia completion powershell | Out-String | Invoke-Expression`
  to your PowerShell profile (`$PROFILE`), or `eval "$(probandia completion bash)"`
  to `~/.bashrc` (also `zsh`, `fish`).

### Readable output and the contract

The same command speaks to two readers. At a terminal, with no agent detected,
it shows a readable screen, in colour, paged when it is long. Piped, redirected,
or run by an agent, it prints the contract that skills and agents read: one
`KEY=value` per line, starting with `STATUS=`, at most 40 lines.

| To choose | How |
|---|---|
| the form | `--output-format human\|contract\|json`, or `PROBANDIA_OUTPUT`; `--json` is `--output-format json` |
| no colour | `NO_COLOR=1`, `--no-color`; `--plain` also keeps to ASCII; `FORCE_COLOR=1` forces colour |
| the pager | `PROBANDIA_PAGER` (`none` turns it off); otherwise `less -R`, or a pager built in |
| the language | `-l fr`, `--lang fr` or `PROBANDIA_LANGUAGE=fr`; English by default |

### Exit codes, for scripts

| Code | Meaning |
|---|---|
| 0 | done (`STATUS=OK` or `WARN`) |
| 1 | failed: a verification rule, a refused proposal |
| 2 | usage or configuration error |
| 3 | a question waits for an answer (`STATUS=ASK`) |
| 4 | stopped: a free quota or a cap reached, or you declined (`STATUS=STOP`) |
| 5 | locked by another session |
| 6 | not inside a project |
| 7 | network or provider error |
| 10 | internal error; details in the log |
| 130 | interrupted (Ctrl+C) |

```powershell
probandia verify 2026-09 -q
if ($LASTEXITCODE -eq 1) { "a verification rule failed" }
probandia -u --json > quotas.json
```

```sh
probandia verify 2026-09 -q || echo "exit code: $?"
probandia -u --csv > quotas.csv
```

## Command reference

The commands a person types, grouped as `probandia --help` shows them;
`probandia help <command>` and `probandia <command> --help` give each one's
options and examples.

### Research

| Command | What it does | Example |
|---|---|---|
| `new` | create a research and run its first pass | `probandia new "Who were the parents of Victor Hugo?" --family hugo --mode session` |
| `resume` | run the next pass of a research | `probandia resume 2026-09` |
| `fork` | copy a research at a pass and continue it separately | `probandia fork 2026-09 --at 2 --name second-lead` |
| `verify` | check a research against the proof rules | `probandia verify --standard` |
| `question` | the questions of a research: list, add, edit, answer, unresolved, reopen | `probandia question list` |
| `matrix` | the source types each question expects, consulted or still to do; justify | `probandia matrix` |
| `fact` | record that you looked at the record a fact rests on | `probandia fact check louis-marchand-1898.birth --by "Marie Durand" --looked "the image of the act"` |
| `close` | close a research once its questions are settled and verify has run | `probandia close` |
| `status` | families, researches, passes, locks, quotas | `probandia status` |
| `board` | where you stand, in one look: the research in focus, its pass, quotas, alerts | `probandia board --json` |
| `statusline` | one line for the status bar of Claude Code | `probandia statusline` |

### Reports, trees, exports and imports

| Command | What it does | Example |
|---|---|---|
| `report` | the report of a research: open it in the browser, show it, render it | `probandia report open` |
| `tree` | write the family tree (html or md) | `probandia tree --family marchand --format html` |
| `export` | export GEDCOM 7, GEDCOM 5.5.1 or Gramps Web | `probandia export gedcom7 --family marchand --living mask` |
| `import` | import a workshop in its own format | `probandia import ../my-workshop --dry-run` |
| `import-gedcom` | import a GEDCOM file into the staging area | `probandia import-gedcom family.ged --family marchand` |

### Families and what they hold

| Command | What it does | Example |
|---|---|---|
| `research` | the researches: list, show, log, pause, close, reopen | `probandia research list` |
| `family` | the families: list, show | `probandia family show marchand` |
| `find` | find a person in every family, with the spelling variants | `probandia find Marchand` |
| `person` | a person's file: facts and sources, relatives, hypotheses, negatives, gaps | `probandia person louis-marchand-1898` |
| `searches` | what was already searched, where, and what it found | `probandia searches --family marchand` |
| `sources` | the sources of the families, with their citations | `probandia sources --family marchand` |
| `negatives` | the negative searches, and whether to check them again | `probandia negatives` |
| `hypotheses` | the hypotheses of the families, open and closed | `probandia hypotheses` |
| `gaps` | the gaps in the archives: registers lost or not filmed | `probandia gaps` |
| `proposals` | the proposals waiting: list, show, apply, drop | `probandia proposals list` |

### Free quotas

| Command | What it does | Example |
|---|---|---|
| `usage` | the free tiers account by account: what is left, what it pays for, when it starts again | `probandia usage --sync` |
| `quota` | show, sync, add or estimate free-tier usage | `probandia quota show` |
| `cache` | what the cache of responses holds and saves: stats, clear | `probandia cache stats` |

### Settings and checks

| Command | What it does | Example |
|---|---|---|
| `init` | create a project here; at a terminal, ask its essential settings | `probandia init` |
| `config` | the settings: show, explain, set, unset, init, validate, path, wizard, edit, grade, diff, roles, theme | `probandia config show --origin` |
| `keys` | the API keys: list where they come from, check, set, unset, signup | `probandia keys` |
| `providers` | the free-tier catalogue: list, show, stale, enable, disable | `probandia providers show serper` |
| `watch` | replay the archives' witnesses and list the stale catalogue entries | `probandia watch` |
| `doctor` | check the harness, keys, Python and optional tools | `probandia doctor` |
| `library` | the learned scripts and agents: find, save, test, trust, list, show, run, promote, demote, draft, install, uninstall, export, import | `probandia library list` |
| `memory` | the decisions kept in `AGENTS.md`: add, list, remove, sync | `probandia memory list` |
| `template` | the report templates: list, show, check, import, export, use, designer | `probandia template list` |
| `browser` | open the local browser for you to sign in to an archive | `probandia browser login familysearch` |

### Genealogist's tools

| Command | What it does | Example |
|---|---|---|
| `dates` | parse and convert genealogical dates | `probandia dates "7 ventôse an X"` |
| `variants` | spelling variants of a surname | `probandia variants Marchand --paleo` |
| `places` | historical place names | `probandia places "Besançon" --as-of 1802` |
| `cite` | citation sentence of a source | `probandia cite src-01JA0000000000000000000001 --family marchand` |

### Help

| Command | What it does | Example |
|---|---|---|
| `help` | short pages: quotas, negatives, grades, exit codes, project files | `probandia help grades` |
| `completion` | the Tab completion script of a shell | `probandia completion bash` |
| `tui` | the application in a terminal: its screens, the palette and the console | `probandia tui` |

The other commands (`plan`, `search`, `read`, `propose`, `apply`, `pass`…) are
the engine's, called by the skills, the agents and the MCP server; they are
marked `[engine]` in `probandia --help --all`.

## The plugin surface

**Slash commands** (`commands/`), as `/probandia:<name>` in Claude Code:
`new`, `resume`, `status`, `verify`, `close`, `fork`, `question`, `matrix`,
`config`, `doctor`, `quota`, `memory`, `library`, `template`, `tree`,
`export`, `import`, `import-gedcom`, `watch`. Each runs the engine command of
the same name with your arguments.

**Agents** (`agents/`; `droids/` and `cursor/agents/` hold their copies for
Factory Droid and Cursor):

| Agent | Role |
|---|---|
| `orchestrator` | runs a research pass in team or subagent mode; applies the proposals |
| `researcher` | one closed task (an archive, a question, a window); proposes, never applies |
| `searcher` | runs and logs the web searches it is given, nothing else |
| `reader` | finds the act in a register's views and transcribes it, doubts marked |
| `investigator` | the wave's hard case: a negative, homonyms, a damaged record |
| `contradictor` | argues against one conclusion, read-only |
| `harvester` | one mechanical task (paginate, sift, count): no web, no judgement |

**Skills** (`skills/`): `engine` (run an engine command and read its answer),
`research` (the method of a pass), `ask` (a `STATUS=ASK`), `browser` (an archive
that asks for a sign-in), `config` (settings by grade), `report` (writing the
report), `team` (messages between teammates), `transcribe` (reading a record
from its image).

**MCP server** (`run_probandia.py mcp`), where the harness runs it: `dates`,
`export`, `find_operation`, `known`, `library_find`, `places`, `plan`,
`propose`, `question`, `quota`, `read`, `render`, `run_operation`, `search`,
`tree`, `variants`, `verify`.

**Hooks** (`hooks/hooks.json`, and their copies for each harness): the guard
before each tool call (rules G-n), the log after it, and the state digest on
`/probandia:resume`.

## Projects and settings

A project is a folder that holds `probandia.toml`. `probandia init` makes one
here (and asks its essential settings at a terminal); `/probandia:new` makes
one when it runs in a folder that is not a project yet.

Settings merge seven layers, the higher winning: the defaults; the harness's
plugin options; your user file (`config.toml`: `%APPDATA%\probandia\` on
Windows, `$XDG_CONFIG_HOME/probandia/` or `~/.config/probandia/` elsewhere,
`PROBANDIA_CONFIG_DIR` replaces the folder); the project's `probandia.toml`;
`probandia.local.toml` (not versioned); `PROBANDIA_*` variables; the command's
options. `probandia config path` lists the files of the seven layers and which
exist.

Settings come in three grades: `essential` (the few most people change, by
default), `advanced` (some twenty more) and `expert` (all). `config show`
lists those of your grade; a setting above your grade keeps its default value.

| Action | What it does | Example |
|---|---|---|
| `show` | the settings in effect | `probandia config show --origin` |
| `explain` | one setting: its values, its default, its grade | `probandia config explain report.mode` |
| `set` | write a setting (the project's file; `--user`, `--local`) | `probandia config set search.max_parallel 5` |
| `unset` | remove a setting from a file | `probandia config unset search.max_parallel` |
| `init` | create `probandia.toml` | `probandia config init --grade advanced` |
| `validate` | check every layer | `probandia config validate` |
| `path` | the files of the seven layers, and which exist | `probandia config path` |
| `wizard` | the essential settings, asked at the keyboard | `probandia config wizard` |
| `edit` | open a settings file in an editor, then check it | `probandia config edit --user` |
| `grade` | change the grade, and see the settings it shows | `probandia config grade advanced` |
| `diff` | what differs from the defaults, layer by layer | `probandia config diff` |
| `roles` | the model and the effort of each agent role | `probandia config roles` |
| `theme` | the themes of `probandia tui`: list, save or delete one of yours | `probandia config theme list` |

The plugin options of Claude Code (asked at install, changed in `/plugin`):

| Option | Values |
|---|---|
| `language` | `auto` (the default), or a language code such as `en` or `fr`: the report's language |
| `run_mode` | who runs a research: `ask` (the default), `session`, `subagent` or `team` |

## Model and effort of each agent

Each agent role (`orchestrator`, `researcher`, `searcher`, `reader`,
`investigator`, `contradictor`, `harvester`) runs on the model and the effort
of its header in `.claude-plugin/agents/<role>.md` (generated from `agents/<role>.md`,
which Antigravity reads and which holds none), unless you choose otherwise:

```sh
probandia config set roles.reader.model opus
probandia config set roles.searcher.effort medium
probandia config roles
```

- Keys: `roles.<role>.model`, `roles.<role>.effort` (`low`, `medium`, `high`,
  `xhigh`, `max`), and `roles.<role>.models`, a list of `harness:model` items
  for a harness whose models have other names (`cursor:claude-opus-5`).
- Layers, as `config roles` shows them: the agent's header (`default`), then
  your user file, the project's `probandia.toml`, `probandia.local.toml`, the
  variables `PROBANDIA_ROLES_<ROLE>_MODEL` and `PROBANDIA_ROLES_<ROLE>_EFFORT`
  (`PROBANDIA_ROLES_READER_MODEL=opus`); for the orchestrator, a research's own
  `--model` and `--effort` come last. The older keys `run.*` (orchestrator) and
  `search.*` (searcher) count when the role's own key is not set.
- Where it applies: in Claude Code, the guard sets them at each launch of a
  Probandia agent; for Codex, `install --harness codex` writes them into
  `.codex/agents/` (install again after a change); OpenCode's install writes
  them too; for Cursor, Factory Droid and Grok Build, the session hook writes a
  copy of each chosen agent in the project (`.cursor/agents/`,
  `.factory/droids/`, `.grok/agents/`). A model in a form the harness does not
  take is left out, and the install says so. Antigravity: not applied.
- In Claude Code, the variables `CLAUDE_CODE_EFFORT_LEVEL` (one effort for every
  agent) and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` (one model for every agent)
  override these choices; `doctor` warns when one is set.
- Choosing is free; `config roles` warns when the `reader` goes below its
  default, since its reading of the acts carries the proof.

## Privacy and security

- **Presumed-living persons.** A person born less than `privacy.living_years`
  ago (100 by default) with no death known is presumed living. Exports mask
  them by default (`export --living mask`: written `Living`, with no events);
  `--living exclude` leaves them out. The engine never sends a presumed-living
  person's name to a provider that reuses what it is sent, and memory never
  keeps one.
- **Providers that reuse the content sent to them** (`content_reuse` in the
  catalogue: Gemini grounding, Exa, Parallel, Tavily, Linkup and ScrapeGraphAI,
  whose terms let them train on it) are not called unless you set
  `providers.allow_content_reuse` to `true` (`false` by default); even then,
  never with a presumed-living person.
- **Keys** live in a `.env` file: yours (next to your `config.toml`, the
  default) or the project's (next to `probandia.toml`, `keys set --in-project`).
  `keys set` asks the key unseen at the keyboard and writes the file readable
  by its owner only (mode 600; on Windows, where that mode does not apply, the
  file keeps the access rights of its folder). A key is never printed, and the
  memory refuses one.
- **Learned scripts** (the library) run in a child process with their network
  reduced to the hosts they declare and their environment to the variables they
  declare; what would get round it (another process, a raw socket, native code,
  `exec`) is refused before the script is kept or run. There is no sandbox of
  the file system: a script runs as you, in the project's folder. Trust one
  (`library trust`) only once you have read it.

## Proving a conclusion: the Genealogical Proof Standard

Probandia follows the five elements of the Genealogical Proof Standard of the
Board for Certification of Genealogists: a reasonably exhaustive search,
complete and accurate citations, analysis and correlation, conflicting
evidence resolved, a soundly reasoned conclusion. Each research holds its
questions (`question`); `places guide`, `matrix`, `cite`, `correlate` and
`proof` build each element, rules V-14 to V-18 of `verify` check them, and
`close` settles the research.

`probandia verify <research> --standard` shows, for each question, the five
elements, established, partial or missing, and what each lacks; the report
opens each question with the same box. Set `proof.standard` to `strict`, and a
question that does not conform keeps the research open.

Each fact can quote the exact passage it reads: lines of a transcription
(`transcribe quote <source> --lines 3-5`) or a passage of a page
(`read <url> --quote 2`). `apply` refuses a passage not found word for word,
rule V-19 checks it again at each `verify`, and the report quotes it in the
fact's note. A page is kept in the family's `evidence/pages/` only when its
site is an archive of the catalogue whose images are free; any other stays in
the research's `work/`, on this computer.

Each answered question gets a confidence, computed and never declared, on the
four levels of GEDCOM's `QUAY`: proved, probable, possible, unsupported. It
starts from the weakest fact of the conclusion and loses a step for indirect
evidence (unless an argument reviewed by the contradictor was accepted),
secondary information no second source confirms, an open objection, an
unexplained clash of dates, or a question only partly conform; it is at most
possible for a question that does not conform, and proved needs the record's
passage quoted. `verify --standard`, the report and the GEDCOM export
(`_CONF`, and `QUAY`) show it with its reasons; it blocks nothing.

Probandia helps to show a proof; it does not replace the genealogist's
judgement. The skill
[`skills/research/proofs.md`](https://github.com/devohmycode/probandia/blob/master/skills/research/proofs.md)
says how each element is checked, and where the checks stop.

## What a research teaches: the library

Probandia keeps what the agents learn in a library, the project's (`library/`)
then yours (`library/` next to `config.toml`): scripts that read an archive,
queries that worked (recipes), and, after your approval, skills and sub-agents.

- At the end of a pass, `pass end` lists what could be kept
  (`LEARN_CANDIDATES=`); the agent asks you once which to keep.
- `library list` shows each element with its uses and successes; `library find`
  searches both scopes; `library promote <id> --to user` makes one available
  to all your projects, and runs its witness again.
- A learned skill or agent is written as a draft (`library draft`), checked by
  the engine, and installed only once you read it and said yes
  (`library install <id> --scope project|user --for <harness>`). The library
  keeps the original; the harnesses get copies, which `library uninstall`
  removes exactly. No agent may write into a skills or agents folder itself.
- `library export lot.zip --ids …` and `library import lot.zip` share elements
  between projects; an imported element starts again as a draft.

## What a research teaches: the memory

Probandia also keeps the project's working decisions in one section of
`AGENTS.md`, between `<!-- probandia:begin -->` and `<!-- probandia:end -->`:
conventions, the report template, the providers kept, the archives that need a
sign-in, your preferences, the pitfalls of a source. Codex, Cursor, Factory
Droid and OpenCode read `AGENTS.md`; Claude Code reads it too, or through one
`@AGENTS.md` line when the project has a `CLAUDE.md`.

- At the end of a pass, the agent proposes the decisions worth keeping, in the
  same question as the library's candidates; nothing is written before you say
  yes (`memory add "<one line>" --kind provider`).
- Never in it: genealogical facts (the family indexes hold them), presumed-
  living persons, keys. The engine refuses them, and never touches your text
  outside the markers.
- The section stays short (40 lines, 2 KB), since every session loads it:
  merge entries (`--supersedes M2,M3`) or move the oldest to
  `memory-archive.md`, which no harness loads.
- `memory list`, `memory remove M3`, `memory sync`; `doctor` reports a missing
  import, a duplicate section or a section edited by hand. `--scope user`
  writes your own file (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`), only on
  its own approval.

## Report templates

The HTML report follows a template: one self-contained `.html` file, with no
script and no external resource, which you can print as it is.

- Shipped: `default`, `print` (serif, a chapter per page), `family-book`
  (title page, notes after each chapter), `high-contrast` and `habillage`
  (grey paper, Bodoni titles, madder red, dark on a dark screen; its fonts
  are embedded).
- `probandia template designer` opens the designer in your browser, offline:
  colours (with their WCAG contrast), fonts, width, title page and logo,
  header and footer, contents, status marks, errata, notes, tree colours,
  printing; the preview switches between English and French. Download the
  template, then `probandia template import my-template.html`.
- `probandia template use family-book` chooses it for the project; `--level
  family` or `--level research` for one family or one research, `--level user`
  for all your projects. Then `probandia render --all`.
- `template list | show | check | export` do the rest; `verify` (rule V-13)
  tells when a report's template was removed or changed.

## Providers

Probandia searches and reads the web through the harness's own web search and
the free tiers of the providers below, and never pays. The engine's `search`
and `read` call the providers' APIs with your keys (`probandia keys signup
<provider>` gives the page where each free account is made; `keys set` stores
the key). `quota show` gives what is left of each, in searches and pages, with
the day it starts again; `doctor` lists the keys found and the balances it can
read. The free tiers, costs and sources are in
[`catalogues/providers.toml`](https://github.com/devohmycode/probandia/blob/master/catalogues/providers.toml),
each entry with the date it was checked.

| Provider | Catalogue id | Role | Key |
|---|---|---|---|
| SerpApi | `serpapi` | web search, Google index | `SERPAPI_API_KEY` |
| SerpApi, Bing engine (off by default) | `serpapi_bing` | web search, Bing index | `SERPAPI_API_KEY` |
| Serper | `serper` | web search, Google index | `SERPER_API_KEY` |
| SearchApi.io | `searchapi` | web search, Google index | `SEARCHAPI_API_KEY` |
| OpenWeb Ninja Real-Time Web Search | `openwebninja_search` | web search, Google index | `OPENWEBNINJA_API_KEY` |
| OpenWeb Ninja Real-Time News Data | `openwebninja_news` | news search | `OPENWEBNINJA_API_KEY` |
| OpenWeb Ninja Real-Time Books Data | `openwebninja_books` | book search | `OPENWEBNINJA_API_KEY` |
| Gemini grounding (reuses content, off by default) | `gemini_grounding` | web search, Google index | `GEMINI_API_KEY` |
| Brave Search API | `brave` | web search, other index | `BRAVE_API_KEY` |
| Staan | `staan` | web search, other index | `STAAN_API_KEY` |
| Marginalia Search | `marginalia` | web search, other index | `MARGINALIA_API_KEY` |
| Exa (reuses content, off by default) | `exa` | web search, other index | `EXA_API_KEY` |
| Parallel Search (reuses content, off by default) | `parallel` | web search, other index | `PARALLEL_API_KEY` |
| Tavily (reuses content, off by default) | `tavily` | answers with sources; reading pages, `read --map`, `--crawl`, `--extract` | `TAVILY_API_KEY` |
| Linkup (reuses content, off by default) | `linkup` | answers with sources | `LINKUP_API_KEY` |
| Jina Reader (works without a key) | `jina` | reading pages | `JINA_API_KEY` |
| Firecrawl | `firecrawl` | reading pages, `read --map`, `--crawl`, `--extract` | `FIRECRAWL_API_KEY` |
| ScrapeGraphAI (reuses content, off by default) | `scrapegraph` | `read --extract` | `SGAI_API_KEY` |
| ZenRows | `zenrows` | reading, last resort | `ZENROWS_API_KEY` |
| ScraperAPI | `scraperapi` | reading, last resort | `SCRAPERAPI_API_KEY` |
| Apify (Google Search Scraper) | `apify` | web search, Google index | `APIFY_TOKEN` |
| Apify (RAG Web Browser) | `apify_reader` | reading, last resort | `APIFY_TOKEN` |
| OpenRouter | `openrouter` | its balance only (`doctor`, `quota sync`) | `OPENROUTER_API_KEY` |

- Keys go in a `.env` file: the user's (next to `config.toml`) or the project's
  (next to `probandia.toml`);
  [`.env.example`](https://github.com/devohmycode/probandia/blob/master/.env.example)
  lists them all. A key is never printed.
- **Refused before the call.** A provider is not called when its free quota
  left, less the reserve (`budget.reserve_percent`), cannot pay for the
  operation (`STATUS=STOP`, exit code 4); when it is not in
  `providers.enabled` or turned off (`providers disable`); when its key is
  missing; when it asks for a card (unless `providers.allow_card_required`) or
  reuses the content sent (unless `providers.allow_content_reuse`); and never
  with a presumed-living person's name. `providers` lists each one with the
  reason it is out of service.
- **The first salvo is free.** A pass opens with archives and the harness's own
  web search, in the same turn: `search.max_parallel` native searches at once (3
  by default, 1 to 8: `probandia config set search.max_parallel 5`, or
  `--parallel 5`). The engine's `search`, which spends a provider's quota, waits
  for the pass's first native search (`REASON=native-first`); a `--negative`
  search does not wait.
- **The engine, not MCP servers.** The agents load no search or scraping MCP
  server: the engine's `search` and `read` (`--map`, `--crawl <n>`,
  `--extract "<what>"`) serve the later salvos with the providers' API keys,
  counting each quota before the call. During a pass, the guard refuses a call
  to one of your own servers (Firecrawl, Tavily, Exa, a claude.ai connector…)
  and names the engine command that does the same (rule G-15); outside a pass,
  the call is let through and counted against the provider's quota afterwards.
  A claude.ai connector does not serve a pass: give the engine an API key.
- **Balances.** `probandia quota sync` reads, for free, the balance of each
  account whose key is set; `probandia usage --sync` (`-u --sync`) reads them
  before showing them.
- A web negative ("found nowhere") needs at least two independent index
  families; an engine whose answer is unrelated to the query is not counted, and
  an engine of a missing family takes over. Bing through SerpApi answered most
  exact genealogical queries with unrelated pages: it stays off unless added to
  `providers.enabled`.
- `read <url>` tries Firecrawl, then Tavily, whose free tiers come back each
  month, before Jina, whose free tokens are given once per key, and Parallel
  last, slow on a page it has not cached; `reading.readers` sets another order.
- `search --depth advanced` asks for a deeper, dearer search (Tavily, Exa,
  Parallel, Linkup only; any other engine is refused before any call).
- The last-resort readers are used without their anti-bot options (premium or
  residential proxies, stealth modes, CAPTCHA solving), after the readers
  above, once per page at their plain tier, and never on an archive portal
  or a genealogy database.
- `robots.txt` rules crawlers, not one page read for you: when it disallows a
  page, `read <url>` does not fetch it itself (by HTTP or its own browser) but
  hands it to the readers above, then to your browser or the web archives
  (never for a host whose archive forbids third parties, nor for a local
  address). `read --map` and `--crawl` obey it strictly, for every page.
- OpenWeb Ninja asks the account to subscribe to the free plan of each API
  (Real-Time Web Search, Real-Time News Data, Real-Time Books Data) before use.
- `pass end` counts the tools of the pass (`TOOLS_WEB`, `TOOLS_MCP`,
  `TOOLS_ARCHIVE`, `TOOLS_ENGINE`), also shown in the report's Method chapter;
  a pass with no web search and no MCP call warns that it is incomplete.

### Open archives

The [open archive guide](https://github.com/devohmycode/probandia/blob/master/guides/open-archives.md)
(in French) records the access conditions for Matricula, Delpher, DDB, Mémoire
des hommes, Léonore, Arolsen and the Belgian State Archives. Use `archive find "Arolsen"` for an archive reached through your browser, or
`archive run ddb.search --args '{"query":"Goethe","max":20}'` for the public
DDB API, whose metadata is CC0 (image rights remain specific to each object).
The catalogue of archives, with each one's access, is
[`catalogues/archives.yaml`](https://github.com/devohmycode/probandia/blob/master/catalogues/archives.yaml).

### The source watch

Archives and free tiers change. `probandia watch` replays the witness of each
archive connector, a small search whose answer is known, and lists the entries
of both catalogues checked more than `catalogues.max_age_days` ago (90).

- A witness that needs a key, downloaded files or a session in the browser is
  "not run", with the reason, never "failed"; `--keys` also reads, for free,
  the account of each provider whose key is set. Nothing is paid.
- It writes `.probandia/watch.json` and `watch.md`, and counts the failures in
  a row of each witness from one watch to the next.
- `probandia watch --print-schedule` prints the `schtasks` command (or the
  crontab line) that runs it every Monday: run it yourself.
- `python tools/watch_issues.py .probandia/watch.json --dry-run` shows the
  issues a watch calls for: a witness that failed three watches in a row (a
  site often blocked does not open one every week), a stale entry. Without
  `--dry-run`, `gh` opens and closes them.
- `.github/workflows/watch.yml` does all this every Monday on GitHub, the
  previous `watch.json` kept in a cache, and opens or closes the issues
  labelled `watch`. Run it by hand from the Actions tab.
- `archive stale` and `providers stale` list the stale entries alone.

## The terminal interface

`probandia tui` opens an application in the terminal. Its screens, each on its
key:

| Key | Screen | What it shows |
|---|---|---|
| 1 | `home` | the researches, the last events of the one chosen, the lowest accounts and the alerts |
| 2 | `quotas` | the free quotas of the accounts, the providers and their keys |
| 3 | `researches` | each research: its file, its log, its report and its team |
| 4 | `family` | the family's tree, its persons and their facts |
| 5 | `proposals` | the proposals waiting, read then accepted or set aside |
| 6 | `config` | the settings, the library of scripts and the diagnostic |
| 7 | `help` | every setting, where its value comes from, the providers' conditions, the keys and the variables |

- `Ctrl+P` opens the palette: a screen, or the form of a command.
- The console fills in a command in its form, and `Ctrl+R` runs it without
  leaving the application: its readable output under the form, its
  confirmations and the keys it asks for in the application's windows.
- `?` lists every key, `q` quits. The application writes nothing itself: each
  action runs a command of the engine.
- It needs the `tui` extra (Textual 8; see [the extras](#install-the-command)):
  `uv tool install --force "<path>[tui]"`, or from PyPI
  `uv tool install "probandia[tui]"`. The engine never imports Textual
  otherwise, and `probandia tui --help` describes the screens without it.

## Development

To work on Probandia itself, from the repository's folder; `AGENTS.md` gives
the architecture and the rule a change follows before it is merged:

```sh
python run_probandia.py --help                       # run the engine from the repo (no install needed; must work with no package installed)
python tools/run_tests.py                            # full test suite (unit + integration + golden files), shared out between processes (-j N, -v)
python -m unittest discover -s tests                 # the same suite in one process (as `run_tests.py -j 1`)
python tools/run_tests.py --measure                  # one process per module: rewrites tools/test_durations.json, which balances the shares
python -m unittest tests.unit.test_cli               # one test module
python -m unittest tests.unit.test_cli.SomeClass.test_name   # a single test
python -m pip install --editable ".[dev]"            # test dependencies: the `dev` extra of pyproject.toml (jsonschema, Pillow, ruff pinned)
python -m ruff check .                               # lint (F and E9, `[tool.ruff]` in pyproject.toml)
python tools/make_sample_project.py                  # regenerate tests/sample-project and tests/sample-project-gps (CI fails if `git status --porcelain` shows a difference)
python run_probandia.py manifests check              # generated plugin manifests must be up to date
python tools/check_wheel.py                          # build the wheel and sdist: files = tools/package-contents.txt, no private name; install the wheel, check it finds its data
python tools/check_wheel.py --update                 # after adding, moving or removing a packaged file: rewrite tools/package-contents.txt (read its diff)
python tools/startup_time.py                         # median startup time of `--version` and `hook guard` (measure only)
python tools/ci_local.py                             # the whole CI on this machine: every job of ci.yml, Windows and Ubuntu (WSL)
python tools/ci_local.py --quick                     # what a sprint needs: test on Windows 3.14 and Ubuntu 3.12, tui/gedcom when their files change
python tools/ci_local.py --jobs test --os windows --python 3.14   # a part of it; --rev <commit>, --parallel N (default 8), --dry-run
uv tool install --editable .                         # install the `probandia` command from the repo (add --force after pyproject.toml changes)
python tools/run_readme_examples.py                  # replay this README's examples under PowerShell and bash
```

## Versions

What each version changed, breaking changes first:
[CHANGELOG.md](https://github.com/devohmycode/probandia/blob/master/CHANGELOG.md). What 1.x keeps
stable, and how a change to it is deprecated first:
[STABILITY.md](https://github.com/devohmycode/probandia/blob/master/STABILITY.md).

## License

Apache License 2.0: see [LICENSE](https://github.com/devohmycode/probandia/blob/master/LICENSE); the
embedded libraries and fonts keep their own licences, listed in
[THIRD-PARTY-NOTICES](https://github.com/devohmycode/probandia/blob/master/THIRD-PARTY-NOTICES).
