import io
import json
import os
import shutil
import tempfile
import tomllib
import unittest

from probandia import cli
from probandia.cli.commands import COMMANDS
from probandia.install import Installer, convert, manifests, opencode
from probandia.install import uninstall
from tests import ROOT

ROLES = ["contradictor", "harvester", "investigator", "orchestrator", "reader", "researcher",
         "searcher"]
USER_COMMANDS = [c.name for c in COMMANDS if c.slash]


def call(*argv, cwd, environ=None):
    out = io.StringIO()
    code = cli.main(list(argv), stdout=out, environ=environ or {}, cwd=cwd)
    return code, out.getvalue()


def copy_sources(dst):
    """The Claude layout only: what the generator reads."""
    for folder in (".claude-plugin", "agents", "commands", "hooks", "skills"):
        shutil.copytree(os.path.join(ROOT, folder), os.path.join(dst, folder))


class Generator(unittest.TestCase):
    def test_repository_is_up_to_date(self):
        self.assertEqual(manifests.check(), [], "run: python run_probandia.py manifests generate")

    def test_claude_code_plugin_declares_no_mcp_server(self):
        # token-economy E1: Claude Code loads any .mcp.json at the plugin root; Cursor keeps its server
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".mcp.json")))
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            self.assertNotIn("mcpServers", json.load(fh))
        cursor = json.loads(manifests.targets()[".cursor-plugin/plugin.json"])["mcpServers"]
        with open(os.path.join(ROOT, *cursor.split("/")[1:]), encoding="utf-8") as fh:
            self.assertIn("probandia", json.load(fh)["mcpServers"])

    def test_cursor_mcp_is_generated_for_cursor(self):
        # T133: once written by hand for Claude Code; Cursor expands ${CURSOR_PLUGIN_ROOT}
        with open(os.path.join(ROOT, "cursor", "mcp.json"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text, manifests.targets()["cursor/mcp.json"])
        server = json.loads(text)["mcpServers"]["probandia"]
        self.assertEqual(server["env"]["PROBANDIA_HARNESS"], "cursor")
        self.assertTrue(server["args"][0].startswith("${CURSOR_PLUGIN_ROOT}/"))

    def test_capabilities_match_manifests(self):
        # T124: mcp=True only where the harness's plugin manifest declares the server (Grok reads .claude-plugin/;
        # OpenCode's server is written by install --harness opencode)
        from probandia.harness import CAPABILITIES

        targets = manifests.targets()
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            claude = fh.read()
        manifest = {"claude-code": claude, "grok": claude, "codex": targets[".codex-plugin/plugin.json"],
                    "cursor": targets[".cursor-plugin/plugin.json"], "droid": targets[".factory-plugin/plugin.json"],
                    "antigravity": targets["mcp_config.json"]}
        for harness, text in manifest.items():
            self.assertEqual(CAPABILITIES[harness]["mcp"], "mcpServers" in json.loads(text), harness)

    def test_antigravity_subagents_only_with_agents_it_loads(self):
        # T219: agy 1.4.6 skips an agent whose `tools` is not a list or whose model is not a tier of its own;
        # agents/ is written for Claude Code (`tools: Bash, Read`, `model: sonnet`), so no subagents there (T267)
        import glob
        import re

        from probandia.harness import CAPABILITIES

        loads = True
        for path in glob.glob(os.path.join(ROOT, "agents", "*.md")):
            with open(path, encoding="utf-8") as fh:
                head = fh.read().split("---")[1]
            tools = re.search(r"^tools:\s*(.*)$", head, re.M)
            model = re.search(r"^model:\s*(\S+)", head, re.M)
            if (tools and not tools.group(1).startswith("[")) or (model and model.group(1) not in ("flash", "pro")):
                loads = False
        self.assertEqual(CAPABILITIES["antigravity"]["subagents"], loads)

    def test_claude_code_reads_its_own_copies_with_each_roles_model(self):
        # T267: agents/ is written for Antigravity; Claude Code reads .claude-plugin/agents/, with ROLE_DEFAULTS
        from probandia.config.registry import ROLE_DEFAULTS
        from probandia.install import convert

        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            listed = json.load(fh)["agents"]
        roles = sorted(convert.agents(ROOT))
        self.assertEqual(listed, [f"./.claude-plugin/agents/{role}.md" for role in roles])
        for role in roles:
            with open(os.path.join(ROOT, ".claude-plugin", "agents", f"{role}.md"), encoding="utf-8") as fh:
                fm, _body = convert.split_front_matter(fh.read())
            self.assertEqual((fm["model"], fm["effort"]), ROLE_DEFAULTS[role], role)
            self.assertIsInstance(fm["tools"], str, role)   # Claude Code's own form, A, B

    def test_generate_then_check_then_a_manual_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_sources(tmp)
            self.assertGreater(len(manifests.generate(tmp)), 10)
            self.assertEqual(manifests.check(tmp), [])
            self.assertEqual(manifests.generate(tmp), [])
            path = os.path.join(tmp, "plugin.json")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(" ")
            self.assertEqual(manifests.check(tmp), ["plugin.json"])
            os.unlink(os.path.join(tmp, "droids", "reader.md"))
            self.assertEqual(manifests.check(tmp), ["plugin.json", "droids/reader.md"])

    def test_command_exit_codes(self):
        self.assertEqual(call("manifests", "check", cwd=ROOT)[0], 0)

    def test_every_target_is_valid_json(self):
        for rel, content in manifests.targets().items():
            if rel.endswith(".json"):
                json.loads(content)

    def test_codex_and_agent_plugins(self):
        t = manifests.targets()
        root = json.loads(t["plugin.json"])
        self.assertEqual(root["$schema"], manifests.AGENT_PLUGINS_SCHEMA)
        self.assertEqual(set(root) - {"$schema", "name", "version", "description", "author",
                                      "keywords", "homepage", "repository", "license", "extensions"}, set())
        self.assertIn("interface", root["extensions"]["com.openai"])
        mcp = json.loads(t["mcp.json"])["mcpServers"]["probandia"]
        self.assertEqual(mcp["args"], ["${PLUGIN_ROOT}/run_probandia.py", "mcp"])
        market = json.loads(t[".agents/plugins/marketplace.json"])["plugins"][0]
        self.assertIn("policy", market)
        self.assertIn("category", market)

    def test_cursor_commands_carry_a_prefix(self):
        # T263: Cursor names commands after their files, unprefixed; Claude Code, Grok and Droid keep commands/
        t = manifests.targets()
        self.assertEqual(json.loads(t[".cursor-plugin/plugin.json"])["commands"], "./cursor/commands/")
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "commands")) if n.endswith(".md"))
        self.assertEqual(sorted(k for k in t if k.startswith("cursor/commands/")),
                         [f"cursor/commands/probandia-{n}" for n in names])
        with open(os.path.join(ROOT, "commands", "status.md"), encoding="utf-8") as fh:
            original = fh.read()
        # Cursor names a command after its front matter's name, which the copy adds (a manual check: /status, 21 Oct.)
        self.assertEqual(t["cursor/commands/probandia-status.md"],
                         original.replace("---\n", "---\nname: probandia-status\n", 1))
        for name in names:
            self.assertTrue(t[f"cursor/commands/probandia-{name}"].startswith(f"---\nname: probandia-{name[:-3]}\n"), name)

    def test_cursor_hooks_use_its_events(self):
        hooks = json.loads(manifests.targets()["hooks/cursor.json"])
        self.assertEqual(hooks["version"], 1)
        self.assertEqual(sorted(hooks["hooks"]), ["afterMCPExecution", "beforeMCPExecution",
                                                  "beforeShellExecution", "sessionStart", "stop"])   # G1: no log after a shell
        self.assertTrue(hooks["hooks"]["beforeShellExecution"][0]["command"].endswith("hook guard --harness cursor"))

    def test_hooks_fall_back_on_python3_but_not_on_windows(self):
        # T130, T259: python, else python3, in a form sh, bash, cmd and PowerShell 7 all run; a Windows command of
        # a harness's own keeps plain python (python3 can open the Store)
        t = manifests.targets()
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as fh:
            claude = json.load(fh)["hooks"]
        for event, groups in claude.items():
            for hook in groups[0]["hooks"]:
                first, _sep, second = hook["command"].partition(manifests.FALLBACK)
                self.assertTrue(first.startswith('python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" hook '), event)
                self.assertEqual(second, first[len("python "):], event)
                self.assertNotIn("$(", hook["command"])   # no POSIX-only syntax: cmd and PowerShell run it too
        codex = json.loads(t["hooks/codex.json"])["hooks"]
        for event, groups in codex.items():
            for hook in groups[0]["hooks"]:
                self.assertIn(manifests.FALLBACK, hook["command"])
                self.assertTrue(hook["commandWindows"].startswith('python "${CLAUDE_PLUGIN_ROOT}/run_probandia.py" hook '),
                                event)
        self.assertEqual(json.loads(t[".codex-plugin/plugin.json"])["hooks"], "./hooks/codex.json")
        cursor = json.loads(t["hooks/cursor.json"])["hooks"]
        self.assertTrue(all(h["command"].startswith("python ") for hs in cursor.values() for h in hs))

    def test_antigravity_files_run_from_the_plugin_folder(self):
        t = manifests.targets()
        self.assertEqual(json.loads(t["mcp_config.json"])["mcpServers"]["probandia"]["args"],
                         ["run_probandia.py", "mcp"])
        hooks = json.loads(t["hooks.json"])["probandia"]
        self.assertEqual(sorted(hooks), ["PostToolUse", "PreInvocation", "PreToolUse"])


class Agents(unittest.TestCase):
    def setUp(self):
        self.agents = convert.agents()

    def test_seven_roles_with_defaults(self):
        self.assertEqual(list(self.agents), ROLES)
        expected = {"orchestrator": ("sonnet", "high"), "researcher": ("sonnet", "medium"),
                    "investigator": ("opus", "high"), "harvester": ("haiku", "low"),
                    "reader": ("sonnet", "medium"), "contradictor": ("opus", "high"),
                    "searcher": ("haiku", "low")}
        for role, (fm, body) in self.agents.items():
            self.assertEqual((fm["model"], fm["effort"]), expected[role], role)
            self.assertEqual(fm["name"], role)
            self.assertIn(f"`python .probandia/pb.py <command> --agent {role}`", body)

    def test_restrictions(self):
        # optimize.md 2.3: every agent lists its tools, so the user's MCP servers are not loaded
        orch = convert.tools_list(self.agents["orchestrator"][0]["tools"])
        self.assertNotIn("WebSearch", orch)
        self.assertIn("Agent", orch)
        for role in self.agents:
            self.assertTrue(convert.tools_list(self.agents[role][0].get("tools")), role)
        for role in ("researcher", "investigator"):
            tools = convert.tools_list(self.agents[role][0]["tools"])
            self.assertTrue({"Bash", "WebSearch", "SendMessage"} <= set(tools), role)
            self.assertNotIn("Skill", tools, role)   # their skill files are read by path, not through Skill
            # the user's browser only (decisions 1.1 and 3.1: genealogy databases are read there); no search or
            # reading server since T65: the engine's search and read do what they did (decision of 13 Oct. 2026)
            self.assertEqual([t for t in tools if t.startswith("mcp__")], ["mcp__claude-in-chrome"], role)
        self.assertEqual(convert.tools_list(self.agents["searcher"][0]["tools"]), ["WebSearch", "Bash", "Read"])
        for role in self.agents:   # no field agent but those two names an MCP server
            if role not in ("researcher", "investigator"):
                self.assertEqual([t for t in convert.tools_list(self.agents[role][0]["tools"])
                                  if t.startswith("mcp__")], [], role)
        self.assertNotIn("WebSearch", self.agents["harvester"][0]["tools"])
        self.assertNotIn("Write", self.agents["contradictor"][0]["tools"])
        self.assertIn("WebSearch", self.agents["searcher"][0]["tools"])

    def test_one_compact_block_and_the_team_protocol_apart(self):
        # optimize.md 2.4: no copy of the team protocol nor of the engine skill in each agent
        team = os.path.join(ROOT, "skills", "team", "SKILL.md")
        self.assertTrue(os.path.isfile(team))
        for role, (fm, body) in self.agents.items():
            with self.subTest(role=role):
                self.assertNotIn("## In a team", body)
                self.assertNotIn("`engine` skill", body)
                # token-economy E5: "and proof" only for the agents that write or judge facts
                self.assertEqual(body.count("## Engine"), 1)
                self.assertEqual("## Engine and proof" in body,
                                 role not in ("harvester", "reader", "searcher"))
                if role not in ("orchestrator", "contradictor"):
                    self.assertIn("skills/team/SKILL.md", body)   # read by path: field agents have no Skill tool

    def test_droid_tools_are_valid_ids(self):
        # Factory Droid rejects an unknown id; Skill is always there and is not listed
        valid = {"Read", "LS", "Grep", "Glob", "Create", "Edit", "ApplyPatch", "Execute", "WebSearch", "FetchUrl"}
        for role, (fm, body) in self.agents.items():
            droid, _ = convert.split_front_matter(manifests.droid_agent(role, fm, body))
            with self.subTest(role=role):
                self.assertLessEqual(set(droid.get("tools") or []), valid)

    def test_effort_mapping(self):
        mapping = convert.EFFORT_MAP
        self.assertEqual(mapping["cursor"]["xhigh"], "high")
        self.assertEqual(mapping["droid"]["max"], "max")
        self.assertEqual(mapping["grok"]["max"], "xhigh")
        self.assertEqual(mapping["opencode"]["xhigh"], "xhigh")
        self.assertEqual(mapping["opencode"]["max"], "max")
        self.assertEqual(mapping["antigravity"]["medium"], "flash")
        for role, (fm, body) in self.agents.items():
            effort = fm["effort"]
            droid, _ = convert.split_front_matter(manifests.droid_agent(role, fm, body))
            self.assertEqual(droid["reasoningEffort"], mapping["droid"][effort], role)
            oc, _ = convert.split_front_matter(opencode.opencode_agent(role, fm, body, "/x"))
            self.assertNotIn("reasoningEffort", oc, role)  # the user's model may not reason
            self.assertEqual(oc["mode"], "subagent")
            self.assertNotIn("tools", oc)   # OpenCode refuses a tools string
            self.assertNotIn("model", oc)   # OpenCode wants provider/model
            codex = tomllib.loads(convert.codex_agent(role, fm, body))
            self.assertEqual(codex["model_reasoning_effort"], mapping["codex"][effort], role)
            cursor, _ = convert.split_front_matter(manifests.cursor_agent(role, fm, body))
            self.assertEqual(cursor["model"], "inherit")

    def test_droid_tool_names(self):
        fm, body = self.agents["harvester"]
        droid, _ = convert.split_front_matter(manifests.droid_agent("harvester", fm, body))
        self.assertEqual(droid["tools"], ["Execute", "Read", "Create", "Edit", "Grep", "Glob"])

    def test_the_reader_has_neither_grep_nor_glob(self):
        # T68: none of the 33 readers of J7, J8 and I3 called them, and each tool's definition is in its first context
        for rel in ("agents/reader.md", "droids/reader.md", "cursor/agents/reader.md"):
            with self.subTest(rel=rel):
                fm, _body = convert.split_front_matter(convert.read(os.path.join(ROOT, *rel.split("/"))))
                tools = fm["tools"] if isinstance(fm["tools"], list) else convert.tools_list(fm["tools"])
                self.assertTrue(tools, rel)
                self.assertFalse({"Grep", "Glob"} & set(tools), (rel, tools))
        with open(os.path.join(ROOT, "skills", "transcribe", "SKILL.md"), encoding="utf-8") as fh:
            self.assertNotIn("Into the facts", fh.read())   # for who writes the proposal: in its example
        with open(os.path.join(ROOT, "schemas", "examples", "proposal-1.yaml"), encoding="utf-8") as fh:
            example = fh.read()
        self.assertIn("# record: read on the image; index: an index or another's transcription", example)
        self.assertIn("transcribe check's UNCERTAIN_READING= text", example)


class Commands(unittest.TestCase):
    def test_every_user_command_has_its_file(self):
        commands = convert.commands()
        self.assertEqual(sorted(commands), sorted(USER_COMMANDS))
        for name, (fm, body) in commands.items():
            self.assertTrue(fm.get("description"), name)
            self.assertIn(f"run_probandia.py\" {name} $ARGUMENTS", body, name)
            self.assertIn("`engine` skill", body, name)

    def test_engine_skill_says_where_the_engine_is(self):
        text = convert.read(os.path.join(ROOT, "skills", "engine", "SKILL.md"))
        self.assertIn("two folders above this `SKILL.md`", text)


class Installs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def snapshot(self):
        out = {}
        for folder, dirs, files in os.walk(self.dir):
            out[folder] = None
            for f in files:
                with open(os.path.join(folder, f), "rb") as fh:
                    out[os.path.join(folder, f)] = fh.read()
        return out

    def test_codex_agents(self):
        before = self.snapshot()
        code, out = call("install", "--harness", "codex-agents", "--path", self.dir, cwd=self.dir)
        self.assertEqual(code, 0, out)
        for role in ROLES:
            with open(os.path.join(self.dir, ".codex", "agents", f"probandia-{role}.toml"), "rb") as fh:
                data = tomllib.load(fh)
            self.assertEqual(data["name"], f"probandia_{role}")
            self.assertNotIn("${", data["developer_instructions"])
            self.assertNotIn("model", data)
            if role == "contradictor":
                self.assertEqual(data["sandbox_mode"], "read-only")
        call("install", "--harness", "codex-agents", "--path", self.dir, "--uninstall", cwd=self.dir)
        self.assertEqual(self.snapshot(), before)

    def test_from_a_wheel_a_clear_refusal(self):
        # T128: a non-editable install holds no agents/: refused before anything is written
        from unittest import mock

        root = os.path.join(self.dir, "site-packages")
        os.makedirs(root)
        before = self.snapshot()
        with mock.patch.object(convert, "package_root", return_value=root):
            for target in ("codex", "opencode"):
                code, out = call("install", "--harness", target, "--path", self.dir, cwd=self.dir)
                self.assertEqual(code, 2, out)
                self.assertIn("REASON=not-a-plugin-copy", out)
                self.assertIn("run_probandia.py install", out)
            code, out = call("-l", "fr", "install", "--harness", "codex", "--path", self.dir, cwd=self.dir)
            self.assertIn("installation éditable", out)
        self.assertEqual(self.snapshot(), before)

    def test_codex_complete_install_preserves_settings_and_uninstalls(self):
        os.makedirs(os.path.join(self.dir, ".codex"))
        config = os.path.join(self.dir, ".codex", "config.toml")
        with open(config, "w", encoding="utf-8") as fh:
            fh.write('# Keep my settings\nmodel = "my-model"\n[plugins."other@local"]\nenabled = true\n')
        os.makedirs(os.path.join(self.dir, ".agents", "plugins"))
        market = os.path.join(self.dir, ".agents", "plugins", "marketplace.json")
        other = {"name": "other", "source": {"source": "local", "path": "./other"}}
        with open(market, "w", encoding="utf-8") as fh:
            json.dump({"name": "local", "plugins": [other]}, fh)
        before = self.snapshot()
        code, out = call("install", "--harness", "codex", cwd=self.dir)
        self.assertEqual(code, 0, out)
        data = tomllib.loads(convert.read(config))
        self.assertEqual(data["model"], "my-model")
        self.assertTrue(data["plugins"]["other@local"]["enabled"])
        self.assertTrue(data["plugins"]["probandia@probandia"]["enabled"])
        # T222: Codex reads no marketplace from the project's config; the install names the command that adds it
        self.assertNotIn("marketplaces", data)
        self.assertIn("codex plugin marketplace add", out)
        self.assertIn("# Keep my settings", convert.read(config))
        data = json.loads(convert.read(market))
        self.assertEqual(data["plugins"][0], other)
        self.assertEqual(data["plugins"], [other])
        self.assertEqual(len(os.listdir(os.path.join(self.dir, ".codex", "agents"))), 7)
        installed = self.snapshot()
        code, out = call("install", "--harness", "codex", cwd=self.dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), installed)
        # code 10 once under the full local CI (Windows 3.11, 18 Oct. 2026), never again alone: say why
        code, out = call("install", "--harness", "codex", "--uninstall", cwd=self.dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before)

    def test_codex_complete_install_in_empty_folder(self):
        before = self.snapshot()
        code, out = call("install", "--harness", "codex", "--path", self.dir, cwd=ROOT)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".agents")))
        config = tomllib.loads(convert.read(os.path.join(self.dir, ".codex", "config.toml")))
        self.assertTrue(config["plugins"]["probandia@probandia"]["enabled"])
        call("install", "--harness", "codex", "--uninstall", cwd=self.dir)
        self.assertEqual(self.snapshot(), before)

    def test_codex_uninstall_keeps_a_key_added_after_the_install(self):
        # T11: --uninstall takes out Probandia's keys only, whether the install made the file or not
        for existed in (True, False):
            with self.subTest(existed=existed), tempfile.TemporaryDirectory() as tmp:
                config = os.path.join(tmp, ".codex", "config.toml")
                if existed:
                    os.makedirs(os.path.dirname(config))
                    with open(config, "w", encoding="utf-8") as fh:
                        fh.write('model = "my-model"\n[plugins."other@local"]\nenabled = true\n')
                self.assertEqual(call("install", "--harness", "codex", cwd=tmp)[0], 0)
                with open(config, "a", encoding="utf-8") as fh:
                    fh.write('\n[profiles.mine]\nmodel = "added-later"\n')
                self.assertEqual(call("install", "--harness", "codex", cwd=tmp)[0], 0)   # a second install
                code, out = call("install", "--harness", "codex", "--uninstall", cwd=tmp)
                self.assertEqual(code, 0, out)
                data = tomllib.loads(convert.read(config))
                self.assertEqual(data["profiles"]["mine"]["model"], "added-later")
                self.assertNotIn("marketplaces", data)
                self.assertNotIn("probandia@probandia", data.get("plugins", {}))
                if existed:
                    self.assertEqual(data["model"], "my-model")
                    self.assertTrue(data["plugins"]["other@local"]["enabled"])
                self.assertFalse(os.path.exists(config + ".bak"))
                self.assertFalse(os.path.exists(os.path.join(tmp, ".codex", "agents")))

    def test_codex_rejects_invalid_config_before_writing(self):
        for relative, content in ((".codex/config.toml", "broken = ["),
                                  (".codex/config.toml", "plugins = false")):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, relative)
                os.makedirs(os.path.dirname(path))
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                code, out = call("install", "--harness", "codex", cwd=tmp)
                self.assertEqual(code, 2, out)
                self.assertEqual(convert.read(path), content)
                self.assertFalse(os.path.exists(os.path.join(tmp, ".codex", "agents")))

    def opencode_env(self):
        env = {"HOME": os.path.join(self.dir, "home"), "USERPROFILE": os.path.join(self.dir, "home"),
               "XDG_CONFIG_HOME": os.path.join(self.dir, "cfg")}
        os.makedirs(env["HOME"])
        os.makedirs(os.path.join(env["XDG_CONFIG_HOME"], "opencode"))
        with open(os.path.join(env["XDG_CONFIG_HOME"], "opencode", "opencode.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"theme": "dark", "mcp": {"other": {"type": "local", "command": ["x"]}}}, fh)
        return env

    def test_opencode(self):
        env = self.opencode_env()
        before = self.snapshot()
        code, out = call("install", "--harness", "opencode", cwd=self.dir, environ=env)
        self.assertEqual(code, 0, out)
        cfg = os.path.join(env["XDG_CONFIG_HOME"], "opencode")
        with open(os.path.join(cfg, "opencode.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["theme"], "dark")
        self.assertIn("other", data["mcp"])
        self.assertEqual(data["mcp"]["probandia"]["command"][-1], "mcp")
        self.assertTrue(os.path.exists(os.path.join(cfg, "opencode.json.bak")))
        self.assertEqual(len(os.listdir(os.path.join(cfg, "agents"))), 7)
        self.assertEqual(len(os.listdir(os.path.join(cfg, "commands"))), len(USER_COMMANDS))
        self.assertTrue(os.path.exists(os.path.join(cfg, "plugins", "probandia.js")))
        skill = os.path.join(env["HOME"], ".agents", "skills", "probandia-engine", "SKILL.md")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", convert.read(skill))
        # a second install changes nothing, and the uninstall restores the initial state
        self.assertIn("WRITTEN=0", call("install", "--harness", "opencode", cwd=self.dir,
                                        environ=env)[1])
        code, out = call("install", "--harness", "opencode", "--uninstall", cwd=self.dir, environ=env)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.snapshot(), before)

    def test_opencode_uninstall_keeps_a_key_added_after_the_install(self):
        env = self.opencode_env()
        config = os.path.join(env["XDG_CONFIG_HOME"], "opencode", "opencode.json")
        self.assertEqual(call("install", "--harness", "opencode", cwd=self.dir, environ=env)[0], 0)
        data = json.loads(convert.read(config))
        data["model"] = "added/later"
        with open(config, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, out = call("install", "--harness", "opencode", "--uninstall", cwd=self.dir, environ=env)
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(convert.read(config)),
                         {"theme": "dark", "mcp": {"other": {"type": "local", "command": ["x"]}},
                          "model": "added/later"})
        self.assertFalse(os.path.exists(config + ".bak"))

    def test_uninstall_without_install(self):
        code, out = call("install", "--harness", "codex-agents", "--path", self.dir, "--uninstall",
                         cwd=self.dir)
        self.assertEqual(code, 2)

    def test_installer_keeps_one_backup(self):
        path = os.path.join(self.dir, "a.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("1")
        inst = Installer(self.dir)
        inst.write(path, "2")
        inst.write(path, "3")
        inst.save()
        self.assertEqual(convert.read(path + ".bak"), "1")
        uninstall(self.dir)
        self.assertEqual(convert.read(path), "1")
