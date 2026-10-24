"""The README says what the repository holds (version-1.0.0 lot 7): each test keeps one of its claims
equal to the code, and fails when either side changes alone."""
import argparse
import os
import re
import tomllib
import unittest

from tests import ROOT

README = os.path.join(ROOT, "README.md")
# The repository's page: its links work on GitHub and on PyPI, which shows the README too.
REPOSITORY = "https://github.com/devohmycode/probandia"

# The harnesses of the README's table, by the name it gives them; None: no plugin, the MCP server only.
HARNESSES = {"Claude Code": "claude-code", "Grok Build": "grok", "Codex": "codex", "Cursor": "cursor",
             "Factory Droid": "droid", "Antigravity": "antigravity", "OpenCode": "opencode",
             "Claude Desktop": None}
# The README's words for a support level of harness.CAPABILITIES.
LEVELS = {"first-class": "full", "beta": "beta", "reduced": "reduced"}
# A fenced block, indented or not (inside a list item); group 1 is its text.
FENCE = r"^[ \t]*```[\w-]*\n(.*?)^[ \t]*```"


def readme():
    with open(README, encoding="utf-8") as fh:
        return fh.read()


def code_texts(text):
    """The fenced blocks, then the inline code spans of ``text``."""
    blocks = re.findall(FENCE, text, re.S | re.M)
    rest = re.sub(FENCE, "", text, flags=re.S | re.M)
    spans = re.findall(r"`((?:[^`\n]|\n(?!\n))+)`", rest)   # a span may wrap, as Markdown allows
    return blocks + [s.replace("\n", " ") for s in spans]


def section(text, title):
    """The text under the heading ``title`` (any level), up to the next heading of the same level or above."""
    m = re.search(rf"^(#+) {re.escape(title)}\s*$", text, re.M)
    if not m:
        raise AssertionError(f"no section {title!r} in the README")
    level = len(m.group(1))
    end = re.compile(rf"^#{{1,{level}}} ", re.M).search(text, m.end())
    return text[m.end():end.start() if end else len(text)]


def table(text, first):
    """The rows of the Markdown table whose first header cell is ``first``: lists of cells."""
    rows, inside = [], False
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]] if line.startswith("|") else None
        if cells is None:
            if inside:
                break
            continue
        if not inside:
            inside = cells[0] == first
            continue
        if not set(cells[0]) <= set("-: "):
            rows.append(cells)
    if not inside:
        raise AssertionError(f"no table headed {first!r} in the README")
    return rows


def parser_commands():
    from probandia import cli

    sub = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return sub.choices


def cited_commands(text):
    """{command: the line it was found in}: the first word after ``probandia`` or ``run_probandia.py``
    in code, its global options and their values skipped. A shortcut (``-u``) is not a command."""
    from probandia.cli import SHORTCUTS, VALUE_OPTIONS

    found = {}
    pattern = re.compile(r"(?:(?<![\w.@:/\[<-])probandia|run_probandia\.py\"?)[ \t]+([^\n]*)")
    for code in code_texts(text):
        code = code.replace(" -- ", "\n")   # `claude mcp add probandia -- <the command it runs>`: two lines
        for m in pattern.finditer(code):
            words = m.group(1).split()
            i = 0
            while i < len(words):
                word = words[i]
                if word in SHORTCUTS or word[0] in "#|>&;)" or word.startswith("<"):
                    break
                if word.startswith("-"):
                    i += 2 if word in VALUE_OPTIONS else 1
                    continue
                found.setdefault(word.strip("\"'"), m.group(0))
                break
    return found


class Readme(unittest.TestCase):
    def setUp(self):
        self.text = readme()

    def test_each_cited_command_exists(self):
        """(1) Every command written after ``probandia`` or ``run_probandia.py`` is one of the parser's."""
        commands = parser_commands()
        cited = cited_commands(self.text)
        self.assertGreater(len(cited), 10)
        unknown = {c: line for c, line in cited.items() if c not in commands}
        self.assertEqual(unknown, {})

    def test_exit_codes_are_the_engine_s(self):
        """(2) The table of exit codes is the ``EXIT_*`` constants of ``errors.py``, and 130."""
        from probandia import errors

        rows = table(section(self.text, "Exit codes, for scripts"), "Code")
        codes = {int(r[0]) for r in rows}
        expected = {v for k, v in vars(errors).items() if k.startswith("EXIT_") and isinstance(v, int)} | {130}
        self.assertEqual(codes, expected)
        self.assertEqual(len(rows), len(codes))

    def test_harnesses_and_their_support(self):
        """(3) The harnesses of the table are those of ``CAPABILITIES`` (``cli`` aside), with Claude Desktop
        (the MCP server only), each at the support level of the code."""
        from probandia.harness import CAPABILITIES

        rows = table(self.text, "Harness")
        names = {}
        for row in rows:
            name = next((n for n in HARNESSES if row[0].startswith(n)), None)
            self.assertIsNotNone(name, row[0])
            names[name] = row[1]
        self.assertEqual(sorted(HARNESSES[n] or "" for n in names),
                         sorted([h for h in CAPABILITIES if h != "cli"] + [""]))
        for name, support in names.items():
            harness = HARNESSES[name]
            if harness is None:
                self.assertTrue(support.startswith("MCP server only"), support)
                continue
            self.assertTrue(support.startswith(LEVELS[CAPABILITIES[harness]["support"]]), (name, support))

    def test_cited_extras_exist(self):
        """(4) Each extra written ``probandia[x]``, ``<path>[x]`` or ``.[x]`` is in ``pyproject.toml``."""
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
            extras = set(tomllib.load(fh)["project"]["optional-dependencies"])
        cited = set()
        for code in code_texts(self.text):
            for m in re.finditer(r"(?:probandia|>|\.)\[([a-z,]+)\]", code):
                cited.update(m.group(1).split(","))
        self.assertTrue({"tui", "dev"} <= cited, cited)
        self.assertEqual(cited - extras, set())

    # T177: a section per harness

    def test_each_harness_has_its_section(self):
        """Each harness: its support, whether it has the MCP server, and four blocks (install, update,
        uninstall, run a research; Claude Desktop runs MCP tools only)."""
        rows = {next(n for n in HARNESSES if r[0].startswith(n)): r for r in table(self.text, "Harness")}
        for name, row in rows.items():
            body = section(self.text, name)
            self.assertIn(row[1].split(",")[0].split(" ")[0].lower(), body.lower(), name)
            self.assertIn("MCP server", body, name)
            labels = ("Install", "Update", "Uninstall", "Run a research")
            for label in labels:
                m = re.search(rf"^{label}\b(?:[^\n]|\n(?!\n))*:\n\n[ \t]*```", body, re.M)
                if name == "Claude Desktop" and label == "Run a research":
                    self.assertIn("MCP tools only", body)
                    continue
                self.assertIsNotNone(m, f"{name}: no block under {label}")

    def test_mcp_server_as_the_files_declare_it(self):
        """The MCP column says yes exactly where the harness's files declare a server."""
        import json
        import tempfile

        def declared(*rel):
            with open(os.path.join(ROOT, *rel), encoding="utf-8") as fh:
                return bool(json.load(fh).get("mcpServers"))

        claude = declared(".claude-plugin", "plugin.json")
        from probandia.install import opencode

        with tempfile.TemporaryDirectory() as tmp:
            opencode.install("project", tmp, {"PROBANDIA_CONFIG_DIR": tmp})
            with open(os.path.join(tmp, "opencode.json"), encoding="utf-8") as fh:
                opencode_mcp = "probandia" in json.load(fh).get("mcp", {})
        expected = {"Claude Code": claude, "Grok Build": claude,
                    "Codex": declared(".codex-plugin", "plugin.json"),
                    "Cursor": declared(".cursor-plugin", "plugin.json"),
                    "Factory Droid": declared(".factory-plugin", "plugin.json"),
                    "Antigravity": declared("mcp_config.json") and not declared("plugin.json"),
                    "OpenCode": opencode_mcp, "Claude Desktop": True}
        rows = {next(n for n in HARNESSES if r[0].startswith(n)): r for r in table(self.text, "Harness")}
        said = {n: r[2].startswith("yes") for n, r in rows.items()}
        self.assertEqual(said, expected)

    # T179, T180: install the command, requirements

    def test_install_commands_the_engine_gives_are_in_the_table(self):
        """The commands the engine prints (REASON=tui-unavailable, doctor's Pillow, NoPillow) are the README's."""
        from probandia import doctor

        install = section(self.text, "Install the command")
        with open(os.path.join(ROOT, "src", "probandia", "cli", "tui_cmd.py"), encoding="utf-8") as fh:
            tui = re.search(r"command='([^']+)'", fh.read()).group(1)
        self.assertIn(f"`{tui}`", install)
        for way in doctor.INSTALL["pillow"]["any"]:   # NoPillow gives the first of them
            self.assertTrue(f"`{way.replace('{python}', 'python')}`" in install
                            or f"`{way.replace('{python}', '<python>')}`" in install, way)
        for way in ("uv tool install", "--editable", "--force", "pipx install", "python -m pip install",
                    "uv tool uninstall", "pipx uninstall", "python -m pip uninstall", "python -m probandia",
                    "run_probandia.py --version", "uvx probandia"):
            self.assertIn(way, install)

    def test_optional_tools_are_doctor_s(self):
        from probandia import doctor

        rows = table(section(self.text, "Requirements"), "Tool")
        self.assertEqual(sorted(r[0].lower() for r in rows), sorted(doctor.optional_tools()))

    # T181: first research

    def test_first_research_paths(self):
        """The paths the section gives are those render, tree and export write in a copy of the sample project."""
        import contextlib
        import io
        import shutil
        import tempfile

        from probandia import cli

        first = section(self.text, "First research")
        patterns = re.findall(r"`((?:families|exports)/[^`]+)`", first)
        self.assertGreaterEqual(len(patterns), 3)
        for rel in re.findall(r"blob/master/([^)\s]+)\)", first):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "project")
            shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), project)
            environ = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp, "config"), "PROBANDIA_SESSION": "readme"}
            written = []
            for argv in (["report", "render"], ["tree"], ["export", "gedcom7"]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main([*argv, "--yes", "-p", project], stdout=out, environ=environ, cwd=project)
                self.assertEqual(code, 0, out.getvalue())
                written += re.findall(r"FILE=(\S+)", out.getvalue())
        for pattern in patterns:
            rx = re.sub(r"<[a-z]+>", "[^/]+", re.escape(pattern).replace(r"\<", "<").replace(r"\>", ">"))
            self.assertTrue(any(re.fullmatch(rx, w.replace("\\", "/")) for w in written), (pattern, written))
        for word in ("seul :", "agents :", "--mode", "/probandia:resume", "probandia keys"):
            self.assertIn(word, first)

    # T182: command reference

    def test_command_reference_names_every_user_command(self):
        from probandia.cli import commands
        from probandia.cli.helptext import GROUPS

        reference = section(self.text, "Command reference")
        named = []
        for title, _names in GROUPS:
            named += [r[0].strip("`") for r in table(section(reference, title), "Command")]
        wanted = {c.name for c in commands.COMMANDS if not c.engine} | {n for _t, ns in GROUPS for n in ns}
        self.assertEqual(sorted(named), sorted(wanted))
        for title, names in GROUPS:   # grouped as the help groups them
            self.assertEqual(sorted(r[0].strip("`") for r in table(section(reference, title), "Command")),
                             sorted(names))

    # T183: the plugin surface

    def test_plugin_surface(self):
        from probandia import mcp

        surface = section(self.text, "The plugin surface")

        def listed(label):
            m = re.search(rf"^\*\*{label}\*\*(.*?)(?:\n\n|\Z)", surface, re.S | re.M)
            self.assertIsNotNone(m, label)
            return m.group(1)

        def names(folder, suffix=""):
            return sorted(n[:-len(suffix)] if suffix else n for n in os.listdir(os.path.join(ROOT, folder))
                          if n.endswith(suffix))

        commands = re.findall(r"`([a-z-]+)`", listed("Slash commands").split(":", 1)[1])
        self.assertEqual(sorted(commands), names("commands", ".md"))
        agents = [r[0].strip("`") for r in table(surface, "Agent")]
        self.assertEqual(sorted(agents), names("agents", ".md"))
        skills = re.findall(r"`([a-z-]+)` \(", listed("Skills"))
        self.assertEqual(sorted(skills), names("skills"))
        tools = re.findall(r"`([a-z_]+)`", listed("MCP server").split(":", 1)[1])
        self.assertEqual(sorted(tools), sorted(mcp.TOOLS))

    # T184, T185: settings

    def config_actions(self):
        sub = next(a for a in parser_commands()["config"]._actions if isinstance(a, argparse._SubParsersAction))
        return list(sub.choices)

    def test_model_and_effort(self):
        self.assertIn("roles", self.config_actions())
        body = section(self.text, "Model and effort of each agent")
        self.assertGreaterEqual(body.count("config roles"), 1)
        for word in ("roles.<role>.model", "roles.<role>.effort", "CLAUDE_CODE_EFFORT_LEVEL",
                     "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "reader"):
            self.assertIn(word, body)

    def test_settings_section(self):
        import json

        from probandia.cli.config_cmd import GRADE_CHOICES

        body = section(self.text, "Projects and settings")
        actions = [r[0].strip("`") for r in table(body, "Action")]
        self.assertEqual(sorted(actions), sorted(self.config_actions()))
        for grade in GRADE_CHOICES:
            self.assertIn(f"`{grade}`", body)
        for word in ("probandia init", "config path"):
            self.assertIn(word, body)
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            options = json.load(fh)["userConfig"]
        rows = {r[0].strip("`"): r[1] for r in table(body, "Option")}
        self.assertEqual(sorted(rows), sorted(options))
        for key, spec in options.items():
            for value in spec.get("options") or [spec.get("default")]:
                self.assertIn(f"`{value}`", rows[key])

    # T186: privacy

    def test_privacy_settings_are_real(self):
        from probandia.config import registry

        body = section(self.text, "Privacy and security")
        keys = {s.key for s in registry.SETTINGS}
        for key in re.findall(r"`((?:privacy|providers)\.[a-z_.]+)`", body):
            self.assertIn(key, keys)
        self.assertIn("privacy.living_years", body)
        self.assertIn(f"{registry.default_of('privacy.living_years')} by default", body)
        export = parser_commands()["export"]
        living = next(a for a in export._actions if a.dest == "living")
        for choice in living.choices:
            self.assertIn(f"--living {choice}", body)

    # T187: providers

    def test_providers_are_the_catalogue_s(self):
        with open(os.path.join(ROOT, "catalogues", "providers.toml"), "rb") as fh:
            catalogue = tomllib.load(fh)
        with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as fh:
            example = set(re.findall(r"^([A-Z_]+)=", fh.read(), re.M))
        rows = table(section(self.text, "Providers"), "Provider")
        ids = [r[1].strip("`") for r in rows]
        self.assertEqual(sorted(ids), sorted(catalogue))
        for row in rows:
            key = row[3].strip("`")
            self.assertEqual(key, catalogue[row[1].strip("`")]["auth"]["env"])
            self.assertIn(key, example)
        body = section(self.text, "Providers")
        for word in ("keys signup", "quota sync", "usage --sync", "--map", "--crawl", "--extract", "G-15"):
            self.assertIn(word, body)

    # T188: the terminal interface

    def test_tui_screens(self):
        """The screens are ``SCREENS`` of tui_cmd.py, read without importing Textual."""
        import ast

        with open(os.path.join(ROOT, "src", "probandia", "cli", "tui_cmd.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "SCREENS")
        screens = [elt.elts[0].value for elt in node.value.elts]
        body = section(self.text, "The terminal interface")
        rows = table(body, "Key")
        self.assertEqual([r[1].strip("`") for r in rows], screens)
        self.assertEqual([r[0] for r in rows], [str(n) for n in range(1, len(screens) + 1)])
        self.assertNotIn("forms", body.lower())
        install = section(self.text, "Install the command")
        commands = [c for c in re.findall(r"`([^`]*\[tui\][^`]*)`", body)]
        self.assertTrue(commands)
        for command in commands:
            self.assertIn(f"`{command}`", install)

    # T190: links

    def test_links_reach_tracked_files(self):
        """Each link to a file of the repository (relative, or to its GitHub page) reaches a file that is
        there and not ignored by git; each anchor, a heading."""
        import subprocess

        links = re.findall(r"\]\(([^)\s]+)\)", self.text)
        self.assertTrue(links)
        anchors = {re.sub(r"[^\w\- ]", "", h).strip().lower().replace(" ", "-")
                   for h in re.findall(r"^#+ (.+)$", re.sub(FENCE, "", self.text, flags=re.S | re.M), re.M)}
        files = []
        for link in links:
            if link.startswith("#"):
                self.assertIn(link[1:], anchors)
            elif link.startswith(REPOSITORY + "/blob/master/"):
                files.append(link[len(REPOSITORY + "/blob/master/"):])
            elif not re.match(r"[a-z]+:", link):
                files.append(link)
        self.assertTrue(files)
        for rel in files:
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)
        try:
            ignored = subprocess.run(["git", "check-ignore", *files], cwd=ROOT, capture_output=True, text=True)
        except OSError:
            self.skipTest("git is not available")
        self.assertEqual(ignored.stdout.split(), [])

    # T191: development

    def test_development_cites_agents_md_commands(self):
        with open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8") as fh:
            agents = section(fh.read(), "Commands")
        block = re.search(FENCE, agents, re.S | re.M).group(1)
        body = section(self.text, "Development")
        for line in block.splitlines():
            command = line.split("  #")[0].strip()
            if command:
                self.assertIn(command, body)


if __name__ == "__main__":
    unittest.main()
