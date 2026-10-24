"""agent-models R5 and R6: the installers write the model and the effort chosen for each role, in the form
each harness takes (Codex: a slug of its own; OpenCode: provider/model, the effort as its variant)."""
import os
import tempfile
import tomllib
import unittest
from unittest import mock

from probandia import roles
from probandia.install import convert, install_codex_agents, opencode

SETTINGS = """schema = 1

[roles.reader]
model = "{reader}"
effort = "high"

[roles.searcher]
model = "opus"
"""


class Base(unittest.TestCase):
    def project(self, reader):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "user"),
                    "HOME": os.path.join(tmp.name, "home"), "USERPROFILE": os.path.join(tmp.name, "home"),
                    "XDG_CONFIG_HOME": os.path.join(tmp.name, "cfg")}
        project = os.path.join(tmp.name, "p")
        os.makedirs(project)
        with open(os.path.join(project, "probandia.toml"), "w", encoding="utf-8") as fh:
            fh.write(SETTINGS.format(reader=reader))
        return project


class ForInstall(Base):
    def test_a_model_only_in_the_form_the_harness_takes(self):
        project = self.project("gpt-6.1-sol")
        self.assertEqual(roles.for_install(project, self.env, "codex"),
                         {"reader": {"model": "gpt-6.1-sol", "effort": "high"}})   # opus: Claude's, left out
        self.assertEqual(roles.for_install(project, self.env, "opencode"), {"reader": {"effort": "high"}})
        project = self.project("anthropic/claude-opus-5-5")
        self.assertEqual(roles.for_install(project, self.env, "opencode"),
                         {"reader": {"model": "anthropic/claude-opus-5-5", "effort": "high"}})
        self.assertEqual(roles.for_install(None, self.env, "codex"), {})   # outside a project: the user's only


class Codex(Base):
    def test_the_agent_files_carry_the_chosen_model_and_effort(self):
        project = self.project("gpt-6.1-sol")
        with mock.patch.dict(os.environ, self.env):
            install_codex_agents(project)

        def agent(role):
            with open(os.path.join(project, ".codex", "agents", f"probandia-{role}.toml"), "rb") as fh:
                return tomllib.load(fh)

        reader, searcher, orchestrator = agent("reader"), agent("searcher"), agent("orchestrator")
        self.assertEqual((reader["model"], reader["model_reasoning_effort"]), ("gpt-6.1-sol", "high"))
        self.assertNotIn("${", reader["developer_instructions"])
        self.assertNotIn("model", searcher)   # opus is no model of Codex: the parent's is used
        self.assertEqual(searcher["model_reasoning_effort"], "low")   # the header's own
        self.assertEqual((orchestrator.get("model"), orchestrator["model_reasoning_effort"]), (None, "high"))


class Said(Base):
    """T125: what the install did not write, and a change made after it."""

    def call(self, project, *argv):
        import io

        from probandia import cli

        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env):
            code = cli.main(list(argv), stdout=out, environ=dict(self.env), cwd=project)
        return code, out.getvalue()

    def test_a_model_left_out_is_said_with_its_role_and_form(self):
        project = self.project("opus")
        code, out = self.call(project, "install", "--harness", "codex-agents", "--path", project)
        self.assertEqual(code, 0, out)
        self.assertIn("NOT_WRITTEN=2", out)   # the reader's opus and the searcher's
        self.assertIn("reader: the model opus is not in the form codex takes (a model name of its own, "
                      "neither a Claude alias nor provider/model)", out)
        with open(os.path.join(project, ".codex", "agents", "probandia-reader.toml"), "rb") as fh:
            self.assertNotIn("model", tomllib.load(fh))

    def test_config_set_after_an_install_gives_the_command_again(self):
        project = self.project("gpt-6.1-sol")
        code, out = self.call(project, "config", "set", "roles.reader.effort", "high")
        self.assertNotIn("REINSTALL", out)   # nothing installed yet
        for rel, command in ((".codex/agents/probandia-reader.toml", "install --harness codex-agents"),
                             (".opencode/agents/probandia-reader.md", "install --harness opencode --scope project")):
            path = os.path.join(project, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
            code, out = self.call(project, "config", "set", "roles.reader.effort", "high")
            self.assertEqual(code, 0, out)
            self.assertIn(f"REINSTALL=probandia {command}", out)
            self.assertIn(f"rewrite it with: probandia {command}", out)
            os.remove(path)


class OpenCode(Base):
    def test_a_provider_model_and_its_variant_go_in_the_agent(self):
        project = self.project("anthropic/claude-opus-5-5")
        opencode.install("project", project, self.env)
        agents = os.path.join(project, ".opencode", "agents")

        def agent(role):
            with open(os.path.join(agents, f"probandia-{role}.md"), encoding="utf-8") as fh:
                return convert.split_front_matter(fh.read())[0]

        self.assertEqual((agent("reader")["model"], agent("reader")["variant"]), ("anthropic/claude-opus-5-5", "high"))
        for role in ("searcher", "orchestrator"):   # opus is no provider/model; nothing chosen
            self.assertFalse({"model", "variant", "reasoningEffort"} & set(agent(role)), role)


COPIES = """schema = 1

[roles.reader]
model = "opus"
effort = "high"
models = ["cursor:claude-opus-5", "grok:grok-4.7", "claude-code:haiku"]

[roles.searcher]
effort = "medium"
"""


class Copies(Base):
    """agent-models R6: Cursor, Factory Droid and Grok take a project's copy of each agent."""

    def setUp(self):
        self.dir = self.project("unused")
        with open(os.path.join(self.dir, "probandia.toml"), "w", encoding="utf-8") as fh:
            fh.write(COPIES)

    def read(self, rel):
        with open(os.path.join(self.dir, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_the_harness_own_model_first(self):
        self.assertEqual(roles.for_install(self.dir, self.env, "cursor")["reader"]["model"], "claude-opus-5")
        self.assertNotIn("model", roles.for_install(self.dir, self.env, "codex")["reader"])   # opus: Claude's

    def test_one_copy_per_set_role_in_the_form_of_each_harness(self):
        from probandia.install import copies

        done = {h: copies.sync(self.dir, h, self.env) for h in ("cursor", "droid", "grok")}
        # Cursor: the effort lives inside the model; a role with an effort only gets no copy
        self.assertEqual(done["cursor"], [("wrote", ".cursor/agents/probandia-reader.md")])
        cursor = self.read(".cursor/agents/probandia-reader.md")
        self.assertIn("\nmodel: claude-opus-5[effort=high]\n", cursor)
        self.assertIn("\nname: probandia-reader\n", cursor)
        self.assertNotIn('"', cursor.split("\n---\n")[0])   # read line by line, never unquoted
        self.assertNotIn("${", cursor)                       # the engine named by its path
        # Factory Droid: its own model and reasoning effort, Claude's alias kept (it maps them)
        droid, _body = convert.split_front_matter(self.read(".factory/droids/probandia-reader.md"))
        self.assertEqual((droid["name"], droid["model"], droid["reasoningEffort"]), ("probandia-reader", "opus", "high"))
        searcher, _body = convert.split_front_matter(self.read(".factory/droids/probandia-searcher.md"))
        self.assertEqual((searcher["model"], searcher["reasoningEffort"]), ("haiku", "medium"))   # the header's model
        # Grok: model and effort, a model only of its own
        grok, _body = convert.split_front_matter(self.read(".grok/agents/probandia-reader.md"))
        self.assertEqual((grok["model"], grok["effort"]), ("grok-4.7", "high"))
        self.assertNotIn("model", convert.split_front_matter(self.read(".grok/agents/probandia-searcher.md"))[0])
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".grok", "agents", "probandia-orchestrator.md")))
        # again: nothing to write; a file Probandia did not write is never touched; a setting gone, its copy goes
        self.assertEqual(copies.sync(self.dir, "grok", self.env), [])
        with open(os.path.join(self.dir, ".cursor", "agents", "probandia-searcher.md"), "w", encoding="utf-8") as fh:
            fh.write("mine")
        with open(os.path.join(self.dir, "probandia.toml"), "w", encoding="utf-8") as fh:
            fh.write(COPIES.replace('models = ["cursor:claude-opus-5", "grok:grok-4.7", "claude-code:haiku"]', "")
                     .replace('effort = "medium"', 'model = "claude-sonnet-5"'))
        self.assertEqual(sorted(copies.sync(self.dir, "cursor", self.env)),
                         [("kept", ".cursor/agents/probandia-searcher.md"),
                          ("removed", ".cursor/agents/probandia-reader.md")])
        self.assertEqual(self.read(".cursor/agents/probandia-searcher.md"), "mine")

    def hook(self, function, payload, env):
        import io
        import json

        from probandia import hooks

        text = hooks.run(function, io.StringIO(json.dumps(payload)), dict(self.env, **env))
        return json.loads(text) if text.strip() else None

    def test_the_session_hook_writes_them_and_the_guard_sends_grok_to_its_copy(self):
        grok = {"GROK_SESSION_ID": "s1"}
        self.hook("session", {"hookEventName": "SessionStart", "cwd": self.dir}, grok)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, ".grok", "agents", "probandia-reader.md")))

        def launch(role):
            return self.hook("guard", {"hookEventName": "PreToolUse", "cwd": self.dir, "toolName": "spawn_subagent",
                                       "toolInput": {"prompt": "p", "subagent_type": f"probandia:{role}"}}, grok)

        out = launch("reader")["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(out, {"prompt": "p", "subagent_type": "probandia-reader"})
        self.assertIsNone(launch("orchestrator"))   # nothing set for it: the plugin's agent
        # Cursor's session hook names the workspace, not a cwd
        self.hook("session", {"hook_event_name": "sessionStart", "workspace_roots": [self.dir]}, {"CURSOR_AGENT": "1"})
        self.assertTrue(os.path.isfile(os.path.join(self.dir, ".cursor", "agents", "probandia-reader.md")))

    def test_claude_code_takes_its_own_model_first(self):
        out = self.hook("guard", {"tool_name": "Agent", "cwd": self.dir,
                                  "tool_input": {"prompt": "p", "subagent_type": "probandia:reader"}},
                        {"CLAUDECODE": "1"})["hookSpecificOutput"]["updatedInput"]
        self.assertEqual((out["model"], out["effort"]), ("haiku", "high"))


if __name__ == "__main__":
    unittest.main()
