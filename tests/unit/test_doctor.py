import datetime
import io
import os
import tempfile
import unittest

from probandia import cli, doctor
from probandia.harness import CAPABILITIES, DEGRADATIONS, degradations, detect

SECRET = "sk-very-secret-value-0123456789"


def call(*argv, environ):
    out = io.StringIO()
    code = cli.main(list(argv), stdout=out, environ=environ, cwd=tempfile.gettempdir())
    return code, out.getvalue()


class Detection(unittest.TestCase):
    def test_argument_first(self):
        self.assertEqual(detect("cursor", {"CLAUDECODE": "1"}), ("cursor", "--harness"))

    def test_variables(self):
        self.assertEqual(detect(None, {"CLAUDECODE": "1"}), ("claude-code", "CLAUDECODE"))
        # a harness started from Claude Code's shell inherits CLAUDECODE: its own variable wins
        self.assertEqual(detect(None, {"CLAUDECODE": "1", "CODEX_THREAD_ID": "t"}), ("codex", "CODEX_THREAD_ID"))
        self.assertEqual(detect("cli", {"PROBANDIA_HARNESS": "opencode"}),
                         ("opencode", "PROBANDIA_HARNESS"))
        self.assertEqual(detect(None, {}), ("cli", "none"))

    def test_every_harness_has_its_capabilities(self):
        for name, caps in CAPABILITIES.items():
            for field in ("support", "web_search", "subagents", "question", "messaging", "hooks", "mcp",
                          "efforts"):
                self.assertIn(field, caps, name)

    def test_support_levels(self):
        levels = {h: c["support"] for h, c in CAPABILITIES.items()}
        for h in ("claude-code", "codex", "cursor", "droid", "grok"):
            self.assertEqual(levels[h], "first-class", h)
        self.assertEqual(levels["antigravity"], "beta")
        self.assertEqual(levels["opencode"], "reduced")

    def test_reference_harness_degrades_only_without_mcp(self):
        # token-economy E1: its plugin has no MCP server, its skills call the engine through the shell
        self.assertEqual(degradations("claude-code"), [DEGRADATIONS["mcp"]])

    def test_one_list_of_claude_models(self):
        # T124: the run_model question and the guard take the same aliases
        from probandia import roles

        self.assertEqual(sorted(CAPABILITIES["claude-code"]["models"]), sorted(roles.CLAUDE_CODE_MODELS))


class Doctor(unittest.TestCase):
    def test_what_overrides_the_settings_of_the_agent_roles(self):
        # agent-models R4: two variables and a settings file of Claude Code
        import json

        from probandia import config as cfgmod

        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "p")
            os.makedirs(os.path.join(project, ".claude"))
            with open(os.path.join(project, "probandia.toml"), "w", encoding="utf-8") as fh:
                fh.write('schema = 1\n\n[roles.reader]\nmodel = "opus"\n')
            environ = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp, "u"), "CLAUDE_CONFIG_DIR": os.path.join(tmp, "c")}
            config = cfgmod.load(project, environ, strict=False)
            self.assertEqual(doctor.agent_overrides(environ, project, config), [])
            with open(os.path.join(project, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
                json.dump({"env": {"CLAUDE_CODE_EFFORT_LEVEL": "low"}, "availableModels": ["sonnet", "haiku"]}, fh)
            lines = doctor.agent_overrides(dict(environ, CLAUDE_CODE_SUBAGENT_MODEL_FORCE="1"), project, config)
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(lines[0].startswith("CLAUDE_CODE_EFFORT_LEVEL=low sets the effort of every agent"))
        self.assertTrue(lines[1].startswith("CLAUDE_CODE_SUBAGENT_MODEL_FORCE is set"))
        self.assertTrue(lines[2].startswith("reader: the model opus is refused by "), lines[2])

    def test_support_level_and_degradations(self):
        code, out = call("doctor", "--harness", "codex", environ={})
        self.assertEqual(code, 0, out)
        self.assertIn("SUPPORT=first-class", out)
        self.assertIn("- degraded: no subagents in plugins", out)
        self.assertIn("MCP server: no", call("doctor", "--harness", "claude-code", environ={})[1])

    def test_no_python_command(self):
        # T130: the hooks run python; a system with python3 only is said
        with tempfile.TemporaryDirectory() as empty:
            code, out = call("doctor", "--harness", "claude-code", environ={"PATH": empty})
        self.assertEqual(code, 0, out)
        self.assertIn("PYTHON_COMMAND=missing", out)
        self.assertIn("python-is-python3", out)
        self.assertNotIn("PYTHON_COMMAND", call("doctor", "--harness", "claude-code", environ={})[1])

    def test_git_bash_for_claude_code_on_windows(self):
        # T130: without Git Bash, Claude Code runs the hooks in PowerShell, where they fail
        with tempfile.TemporaryDirectory() as tmp:
            def make(*parts):
                path = os.path.join(tmp, *parts)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").close()
                return path
            wsl = make("Windows", "System32", "bash.exe")
            env = {"PATH": os.path.dirname(wsl)}   # WSL's bash.exe is not Git Bash
            self.assertIsNone(doctor.git_bash(env))
            r = doctor.run("claude-code", env, system="windows")
            self.assertEqual((r.status, r.values.get("GIT_BASH")), ("WARN", "missing"))
            self.assertTrue(any("CLAUDE_CODE_GIT_BASH_PATH" in line for line in r.lines))
            self.assertNotIn("GIT_BASH", doctor.run("claude-code", env, system="linux").values)
            self.assertNotIn("GIT_BASH", doctor.run("codex", env, system="windows").values)
            given = make("Tools", "bash.exe")
            self.assertEqual(doctor.git_bash(dict(env, CLAUDE_CODE_GIT_BASH_PATH=given)), given)
            self.assertIsNone(doctor.git_bash(dict(env, CLAUDE_CODE_GIT_BASH_PATH=given + ".gone")))
            git = make("Git", "cmd", "git.exe")   # git.exe on the PATH: bash.exe in <Git>/bin
            bash = make("Git", "bin", "bash.exe")
            self.assertEqual(doctor.git_bash({"PATH": os.path.dirname(git)}), bash)
            self.assertEqual(doctor.git_bash({"PATH": "", "ProgramFiles": tmp}), bash)
            self.assertNotIn("GIT_BASH", doctor.run("claude-code", {"ProgramFiles": tmp}, system="windows").values)

    def test_codex_agents_installed_apart(self):
        # T124: in a project where install --harness codex wrote its agents, doctor names them
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".codex", "agents"))
            with open(os.path.join(tmp, "probandia.toml"), "w", encoding="utf-8") as fh:
                fh.write("schema = 1\n")
            for role in ("reader", "searcher"):
                open(os.path.join(tmp, ".codex", "agents", f"probandia-{role}.toml"), "w").close()
            code, out = call("doctor", "--harness", "codex", environ={"PWD": tmp})
        self.assertEqual(code, 0, out)
        self.assertIn("AGENTS_APART=2", out)
        self.assertIn("subagents: 2 Probandia agents installed apart in .codex", out)
        self.assertNotIn("no subagents in plugins", out)

    def test_never_prints_a_secret(self):
        env = {"BRAVE_API_KEY": SECRET, "TAVILY_API_KEY": SECRET + "2"}
        for harness in CAPABILITIES:
            code, out = call("doctor", "--harness", harness, environ=env)
            self.assertNotIn(SECRET, out, harness)
            code, out = call("doctor", "--harness", harness, "--json", environ=env)
            self.assertNotIn(SECRET, out, harness)
        self.assertIn("KEYS=BRAVE_API_KEY,TAVILY_API_KEY", call("doctor", environ=env)[1])

    def test_advises_only_what_serves(self):
        """T119: no babel, lingua nor kraken (the 1.0 has no use for them, T11); Pillow by a command
        that works as it is."""
        out = call("doctor", "--harness", "cli", "--json", environ={})[1].lower()
        for tool in ("babel", "lingua", "kraken"):
            self.assertNotIn(tool, out)
        self.assertNotIn("probandia[images]", out)
        self.assertIn("pillow", out)

    def test_fits_the_output_contract(self):
        code, out = call("doctor", "--harness", "cli", environ={})
        self.assertLessEqual(len(out.splitlines()), 40)
        self.assertTrue(out.startswith("STATUS="))

    def test_old_python(self):
        r = doctor.run("claude-code", {}, python=(3, 10, 9))
        self.assertEqual(r.status, "FAIL")

    def test_catalogue_ages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "providers.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("[a]\nchecked = 2026-09-30\n\n[b]\nchecked = 2026-01-01\n\n[c]\nname = \"x\"\n")
            ages = dict(doctor.catalogue_ages(path, today=datetime.date(2026, 10, 1)))
        self.assertEqual(ages, {"a": 1, "b": 273, "c": None})
