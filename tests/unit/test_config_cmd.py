import io
import os
import re
import tempfile
import tomllib
import unittest

from probandia import cli
from probandia.config import registry, tomlfile


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "p")
        self.userdir = os.path.join(self.tmp.name, "u")
        os.makedirs(self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": self.userdir}

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def toml(self, name="probandia.toml"):
        with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
            return fh.read()

    def lines(self, out):
        return [line[2:] for line in out.splitlines() if line.startswith("- ")]


class Init(Base):
    def test_essential(self):
        """The eight Essential keys are written commented out, so the harness
        options keep their effect; every other key is commented out too."""
        code, out = self.call("config", "init", "--grade", "essential")
        self.assertEqual(code, 0, out)
        # GPS-D5: a new project checks the Genealogical Proof Standard, warn
        self.assertEqual(tomllib.loads(self.toml()), {"schema": 1, "proof": {"standard": "warn"}})
        text = self.toml()
        for key, value in registry.concrete_keys(1):
            self.assertIn(f"\n# {tomlfile.key_text(key)} = {tomlfile.value_text(value)}\n", text)
        self.assertIn('# roles.searcher.effort = "low"', text)
        self.assertNotIn("run.model", text)   # a key renamed (registry.RENAMED) is not offered
        self.assertIn('# "language.detection_order" = [', text)

    def test_harness_options_apply_after_init(self):
        self.call("config", "init")
        code, out = self.call("config", "show", "--origin", "--harness-options",
                              "report_mode=living;language=fr")
        self.assertIn("report.mode=living  # harness --harness-options", self.lines(out))
        self.assertIn("language=fr  # harness --harness-options", self.lines(out))
        self.call("config", "set", "report.mode", "journal")
        self.assertIn('\nreport.mode = "journal"\n', self.toml())
        code, out = self.call("config", "show", "--origin", "--harness-options", "report_mode=living")
        self.assertIn("report.mode=journal  # project probandia.toml", self.lines(out))

    def test_advanced(self):
        self.call("config", "init", "--grade", "advanced")
        data = tomllib.loads(self.toml())
        self.assertEqual(data["grade"], "advanced")
        self.assertNotIn("mode", data["report"])  # Essential: commented out
        self.assertEqual(data["roles"]["investigator"]["model"], "opus")
        self.assertNotIn("team", data)  # unset by default: stays commented
        self.assertNotIn("routing", data)

    def test_expert_file_is_valid(self):
        self.call("config", "init", "--grade", "expert")
        data = tomllib.loads(self.toml())
        self.assertNotIn("language", data)
        self.assertEqual(data["grade"], "expert")
        self.assertEqual(data["language.detection_order"][0], "arg")
        self.assertEqual(data["routing"]["general"], ["native", "tavily", "linkup"])
        code, out = self.call("config", "validate")
        self.assertEqual(code, 0, out)

    def test_every_commented_default_can_be_uncommented(self):
        """Uncommenting any line of the expert template gives a valid file."""
        self.call("config", "init")
        text = self.toml()
        for line in text.splitlines():
            if line.startswith("# ") and " = " in line and "<" not in line.split(" = ")[1]:
                with self.subTest(line=line):
                    tomllib.loads(text.replace(line, line[2:], 1))


class SetAndUnset(Base):
    def setUp(self):
        super().setUp()
        self.call("config", "init")

    def test_set_keeps_comments(self):
        path = os.path.join(self.dir, "probandia.toml")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("# my own note\n")
        code, out = self.call("config", "set", "report.mode", "living")
        self.assertEqual(code, 0, out)
        text = self.toml()
        self.assertIn("# my own note", text)
        self.assertIn("# Report mode: a journal with errata, or a living report", text)
        self.assertIn('report.mode = "living"', text)

    def test_set_uncomments_the_template_line(self):
        self.call("config", "set", "run.effort", "high")
        text = self.toml()
        self.assertIn('\nrun.effort = "high"\n', text)
        self.assertNotIn('# run.effort = ""', text)

    def test_set_new_keys(self):
        self.call("config", "set", "roles.reader.model", "opus")
        self.call("config", "set", "hosts.gallica.bnf.fr.rate", "5/min")
        self.call("config", "set", "providers.serpapi.monthly_cap", "100")
        self.call("config", "set", "report.formats", "md,json")
        data = tomllib.loads(self.toml())
        self.assertEqual(data["roles"]["reader"]["model"], "opus")
        self.assertEqual(data["hosts"]["gallica.bnf.fr"]["rate"], "5/min")
        self.assertEqual(data["providers"]["serpapi"]["monthly_cap"], 100)
        self.assertEqual(data["report"]["formats"], ["md", "json"])

    def test_set_into_an_existing_table(self):
        with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
            fh.write("\n[team]\nmax_agents = 3\n")
        self.call("config", "set", "team.max_passes", "2")
        self.assertEqual(tomllib.loads(self.toml())["team"], {"max_agents": 3, "max_passes": 2})

    def test_invalid_value(self):
        code, out = self.call("config", "set", "report.mode", "diary")
        self.assertEqual(code, 2)
        self.assertIn("journal, living", out)

    def test_unknown_key(self):
        code, out = self.call("config", "set", "report.colour", "blue")
        self.assertEqual(code, 2)

    def test_user_and_local(self):
        self.call("config", "set", "tree.format", "md", "--user")
        self.call("config", "set", "run.mode", "team", "--local")
        with open(os.path.join(self.userdir, "config.toml"), encoding="utf-8") as fh:
            self.assertEqual(tomllib.loads(fh.read())["tree"]["format"], "md")
        self.assertEqual(tomllib.loads(self.toml("probandia.local.toml"))["run"]["mode"], "team")

    def test_set_overridden_by_a_higher_layer(self):
        self.call("config", "set", "tree.format", "html")
        code, out = self.call("config", "set", "tree.format", "md", "--user")
        self.assertTrue(out.startswith("STATUS=WARN"))
        self.assertIn("project (probandia.toml) overrides this value", out)

    def test_set_above_grade(self):
        code, out = self.call("config", "set", "cache.days", "3")
        self.assertIn("above your grade", out)

    def test_unset(self):
        self.call("config", "set", "roles.reader.model", "opus")
        code, out = self.call("config", "unset", "roles.reader.model")
        self.assertEqual(code, 0, out)
        self.assertNotIn("roles", tomllib.loads(self.toml()))
        code, out = self.call("config", "unset", "roles.reader.model")
        self.assertTrue(out.startswith("STATUS=WARN"))


class Show(Base):
    def setUp(self):
        super().setUp()
        self.call("config", "init")

    def test_origin(self):
        self.call("config", "set", "report.mode", "living")
        code, out = self.call("config", "show", "--origin", "--lang", "fr",
                              env={"PROBANDIA_TREE_FORMAT": "md"})
        self.assertEqual(code, 0, out)
        lines = self.lines(out)
        self.assertEqual(len(lines), 9)
        self.assertIn("report.mode=living  # project probandia.toml", lines)
        self.assertIn("proof.standard=warn  # project probandia.toml  (au-dessus du grade)", lines)   # --lang fr: the messages in French
        self.assertIn("language=fr  # arg --lang", lines)
        self.assertIn("tree.format=md  # env PROBANDIA_TREE_FORMAT", lines)

    def test_above_grade_is_marked(self):
        self.call("config", "set", "cache.days", "3")
        code, out = self.call("config", "show", "--origin")
        self.assertIn("cache.days=3  # project probandia.toml  (above grade)", self.lines(out))

    def test_other_grade_and_all(self):
        code, out = self.call("config", "show", "--grade", "advanced")
        self.assertIn("SHOWN=advanced", out)
        self.assertIn("COUNT=", out)
        code, out = self.call("config", "show", "--all")
        count = int(next(l for l in out.splitlines() if l.startswith("COUNT="))[6:])
        self.assertGreater(count, 60)
        self.assertLessEqual(len(out.splitlines()), 40)
        details = next(l for l in out.splitlines() if l.startswith("DETAILS="))[8:]
        with open(os.path.join(self.dir, details), encoding="utf-8") as fh:   # relative to the project
            self.assertEqual(sum(1 for l in fh if l.startswith("- ")), count)

    def test_unknown_key_warns(self):
        with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
            fh.write("colour = 1\n")
        code, out = self.call("config", "show")
        self.assertTrue(out.startswith("STATUS=WARN"))

    def test_invalid_value_exits_2(self):
        with open(os.path.join(self.dir, "probandia.local.toml"), "w", encoding="utf-8") as fh:
            fh.write('grade = "guru"\n')
        code, out = self.call("config", "show")
        self.assertEqual(code, 2)
        self.assertIn("local", out)


class ExplainAndValidate(Base):
    def setUp(self):
        super().setUp()
        self.call("config", "init")

    def test_explain(self):
        code, out = self.call("config", "explain", "report.mode", "--harness-options",
                              "report_mode=living")
        self.assertEqual(code, 0)
        for part in ("KEY=report.mode", "TYPE=enum", "DEFAULT=journal", "VALUES=journal, living",
                     "GRADE=essential", "ENV=PROBANDIA_REPORT_MODE", "FLAG=--report-mode",
                     "HARNESS=report_mode", "VALUE=living", "ORIGIN=harness --harness-options"):
            self.assertIn(part, out)

    def test_explain_unknown(self):
        self.assertEqual(self.call("config", "explain", "nope")[0], 2)

    def test_validate(self):
        self.assertEqual(self.call("config", "validate")[0], 0)
        code, out = self.call("config", "validate", env={"PROBANDIA_RUN_MODE": "solo",
                                                         "PROBANDIA_GRADE": "guru"})
        self.assertEqual(code, 2)
        self.assertIn("ERRORS=2", out)

    def test_validate_warns_for_an_old_key(self):
        """T12 condition 6: a renamed key still counts, and validate names its new key without failing."""
        from unittest import mock

        from probandia import config

        with open(os.path.join(self.dir, "probandia.toml"), "w", encoding="utf-8") as fh:
            fh.write('[search]\neffort = "high"\n[old]\nreport_mode = "living"\n')
        with mock.patch.dict(registry.RENAMED, {"old.report_mode": "report.mode"}):
            code, out = self.call("config", "validate")
            cfg = config.load(self.dir, self.env)
        self.assertEqual(code, 0, out)
        self.assertIn("STATUS=WARN", out)
        self.assertIn("search.effort", out)
        self.assertIn("use roles.searcher.effort", out)
        self.assertIn("use report.mode", out)
        self.assertNotIn("unknown setting", out)
        self.assertEqual(cfg.get("report.mode"), "living")    # a removed key is read as its new one
        self.assertEqual(cfg.get("search.effort"), "high")    # one still known keeps its meaning


class Roles(Base):
    """agent-models R2 and R4: the model and the effort of each agent role, and where each comes from."""

    def setUp(self):
        super().setUp()
        self.call("config", "init")

    def test_each_role_its_values_and_their_layer(self):
        code, out = self.call("config", "roles")
        self.assertEqual(code, 0, out)
        self.assertIn("CHOSEN=0\n", out)
        self.assertIn("- reader=sonnet medium (default, default)\n", out)   # the agent's own header
        self.assertEqual(self.call("config", "set", "roles.reader.effort", "high")[0], 0)
        self.assertEqual(self.call("config", "set", "search.model", "sonnet")[0], 0)   # the older key of the searcher
        code, out = self.call("config", "roles")
        self.assertIn("CHOSEN=2\n", out)
        self.assertIn("- reader=sonnet high (default, project)\n", out)
        self.assertIn("- searcher=sonnet low (project, default)\n", out)

    def test_a_weaker_reader_or_a_model_the_agent_tool_does_not_take_is_said(self):
        code, out = self.call("config", "set", "roles.reader.model", "haiku")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("STATUS=WARN\n"), out)
        self.assertIn("its reading carries the proof", out)
        code, out = self.call("config", "set", "roles.investigator.model", "claude-opus-5-5")
        self.assertIn("is no alias of the Agent tool of Claude Code", out)
        code, out = self.call("config", "set", "roles.searcher.model", "opus")
        self.assertTrue(out.startswith("STATUS=OK\n"), out)
        self.assertEqual(self.call("config", "set", "roles.reader.model", "two words")[0], 2)
        self.assertIn("- reader: the reader reads the acts", self.call("config", "roles")[1])


class AcceptanceSixteen(Base):
    """A value in the project file overrides the harness option, an argument
    overrides both, and config show --origin shows where each value comes from."""

    def test(self):
        self.call("config", "init")
        self.call("config", "set", "language", "de")
        self.call("config", "set", "report.mode", "journal")
        options = ("language=fr;report_mode=living;report_numbering=;report_formats=;"
                   "tree_format=;run_mode=;search_max_parallel=;grade=")
        # the project file holds language=de and report.mode=journal
        code, out = self.call("config", "show", "--origin", "--harness-options", options)
        lines = self.lines(out)
        self.assertIn("language=de  # project probandia.toml", lines)
        self.assertIn("report.mode=journal  # project probandia.toml", lines)
        # a key absent from the project file: the harness option applies
        self.call("config", "unset", "report.mode")
        code, out = self.call("config", "show", "--origin", "--harness-options", options)
        self.assertIn("report.mode=living  # harness --harness-options", self.lines(out))
        # an argument overrides both
        code, out = self.call("config", "show", "--origin", "--harness-options", options,
                              "--lang", "es")
        self.assertIn("language=es  # arg --lang", self.lines(out))
        # T226: each value shown says where it comes from
        shown = [line for line in out.splitlines() if line.startswith("- ") and "=" in line]
        self.assertTrue(shown)
        self.assertEqual([line for line in shown if not re.search(
            r"  # (default|harness|user|project|local|env|arg) ", line)], [])
