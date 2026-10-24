import os
import tempfile
import unittest

from probandia import config
from probandia.config import ConfigError, parse_harness_options


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.join(self.tmp.name, "project")
        self.userdir = os.path.join(self.tmp.name, "user")
        os.makedirs(self.project)
        os.makedirs(self.userdir)
        self.env = {"PROBANDIA_CONFIG_DIR": self.userdir}

    def write(self, layer, text):
        path = {"user": os.path.join(self.userdir, "config.toml"),
                "project": os.path.join(self.project, "probandia.toml"),
                "local": os.path.join(self.project, "probandia.local.toml")}[layer]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def load(self, harness=None, args=None, env=None, strict=True):
        environ = dict(self.env, **(env or {}))
        return config.load(self.project, environ, harness, args, strict=strict)


class Precedence(Fixture):
    """default < harness < user < project < local < env < arg."""

    LAYERS = ["harness", "user", "project", "local", "env", "arg"]
    VALUES = {"harness": 2, "user": 3, "project": 4, "local": 5, "env": 6, "arg": 7}

    def build(self, present):
        harness = args = None
        env = {}
        for layer in present:
            v = self.VALUES[layer]
            if layer == "harness":
                harness = f"search_max_parallel={v}"
            elif layer == "env":
                env["PROBANDIA_SEARCH_MAX_PARALLEL"] = str(v)
            elif layer == "arg":
                args = {"search.max_parallel": str(v)}
            else:
                self.write(layer, f"search.max_parallel = {v}\n")
        return self.load(harness, args, env)

    def test_each_layer_beats_every_lower_one(self):
        for i, top in enumerate(self.LAYERS):
            with self.subTest(top=top):
                for f in ("probandia.toml", "probandia.local.toml"):
                    p = os.path.join(self.project, f)
                    if os.path.exists(p):
                        os.unlink(p)
                u = os.path.join(self.userdir, "config.toml")
                if os.path.exists(u):
                    os.unlink(u)
                cfg = self.build(self.LAYERS[: i + 1])
                self.assertEqual(cfg.get("search.max_parallel"), self.VALUES[top])
                self.assertEqual(cfg.origin("search.max_parallel").layer, top)

    def test_default(self):
        cfg = self.load()
        self.assertEqual(cfg.get("search.max_parallel"), 3)
        self.assertEqual(str(cfg.origin("search.max_parallel")), "default built-in")

    def test_project_beats_harness(self):
        self.write("project", 'report.mode = "living"\n')
        cfg = self.load("report_mode=journal")
        self.assertEqual(cfg.get("report.mode"), "living")
        self.assertEqual(str(cfg.origin("report.mode")), "project probandia.toml")

    def test_sources(self):
        self.write("user", 'tree.format = "md"\n')
        self.write("local", 'run.mode = "team"\n')
        cfg = self.load("report_mode=living", env={"PROBANDIA_GRADE": "expert"},
                        args={"language": "fr"})
        self.assertEqual(str(cfg.origin("report.mode")), "harness --harness-options")
        self.assertEqual(cfg.origin("tree.format").source, os.path.join(self.userdir, "config.toml"))
        self.assertEqual(str(cfg.origin("run.mode")), "local probandia.local.toml")
        self.assertEqual(str(cfg.origin("grade")), "env PROBANDIA_GRADE")
        self.assertEqual(str(cfg.origin("language")), "arg --lang")


class Merging(Fixture):
    def test_tables_merge_key_by_key(self):
        self.write("user", '[report]\nmode = "living"\nnumbering = "roman"\n')
        self.write("project", 'report.numbering = "arabic"\n')
        cfg = self.load()
        self.assertEqual(cfg.get("report.mode"), "living")
        self.assertEqual(cfg.get("report.numbering"), "arabic")

    def test_lists_are_replaced(self):
        self.write("user", 'report.formats = ["md", "html", "json"]\n')
        self.write("project", 'report.formats = ["json"]\n')
        self.assertEqual(self.load().get("report.formats"), ["json"])

    def test_nested_tables_and_hosts(self):
        self.write("project", '[roles.researcher]\nmodel = "opus"\n\n'
                              '[hosts."gallica.bnf.fr"]\nrate = "5/min"\n')
        cfg = self.load()
        self.assertEqual(cfg.get("roles.researcher.model"), "opus")
        self.assertEqual(cfg.get("hosts.gallica.bnf.fr.rate"), "5/min")

    def test_quoted_key_next_to_a_value(self):
        self.write("project", 'language = "fr"\n"language.detection_order" = ["setting", "default"]\n')
        cfg = self.load()
        self.assertEqual((cfg.get("language"), cfg.get("language.detection_order")), ("fr", ["setting", "default"]))

    def test_unknown_key_is_a_warning(self):
        self.write("project", 'report.colour = "blue"\nschema = 1\n')
        cfg = self.load()
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("report.colour", cfg.warnings[0])

    def test_unknown_variable_is_a_warning(self):
        cfg = self.load(env={"PROBANDIA_REPORT_COLOUR": "x", "PROBANDIA_PROJECT": "y"})
        self.assertEqual(len(cfg.warnings), 1)


class Invalid(Fixture):
    def check(self, **kw):
        with self.assertRaises(ConfigError) as cm:
            self.load(**kw)
        self.assertEqual(cm.exception.exit_code, 2)
        return cm.exception.message

    def test_names_key_layer_and_allowed_values(self):
        self.write("project", 'report.mode = "diary"\n')
        msg = self.check()
        for part in ("report.mode", "project", "probandia.toml", "journal, living"):
            self.assertIn(part, msg)

    def test_out_of_range(self):
        self.assertIn("1 to 8", self.check(env={"PROBANDIA_SEARCH_MAX_PARALLEL": "9"}))

    def test_wrong_type_in_toml(self):
        self.write("project", 'search.max_parallel = "3"\n')
        self.check()

    def test_bad_list_item(self):
        self.assertIn("report.formats", self.check(harness="report_formats=md,pdf"))

    def test_bad_language(self):
        self.check(args={"language": "French"})

    def test_bad_toml(self):
        self.write("local", "report.mode = \n")
        self.assertIn("probandia.local.toml", self.check())

    def test_not_strict_collects_every_problem(self):
        self.write("project", 'report.mode = "diary"\ngrade = "guru"\n')
        cfg = self.load(strict=False)
        self.assertEqual(len(cfg.problems), 2)


class TextValues(Fixture):
    def test_lists_and_booleans_from_variables(self):
        cfg = self.load(env={"PROBANDIA_REPORT_FORMATS": "md, json",
                             "PROBANDIA_PROVIDERS_ALLOW_CARD_REQUIRED": "1",
                             "PROBANDIA_REPORT_SIMPLIFIED_TREES": "false",
                             "PROBANDIA_ROLES_RESEARCHER_MODEL": "opus"})
        self.assertEqual(cfg.get("report.formats"), ["md", "json"])
        self.assertIs(cfg.get("providers.allow_card_required"), True)
        self.assertIs(cfg.get("report.simplified_trees"), False)
        self.assertEqual(cfg.get("roles.researcher.model"), "opus")

    def test_bad_boolean(self):
        with self.assertRaises(ConfigError):
            self.load(env={"PROBANDIA_REPORT_SIMPLIFIED_TREES": "maybe"})

    def test_language_alias_ranks_below_main_name(self):
        cfg = self.load(env={"PROBANDIA_LANG": "de", "PROBANDIA_LANGUAGE": "fr"})
        self.assertEqual(cfg.get("language"), "fr")
        cfg = self.load(env={"PROBANDIA_LANG": "de"})
        self.assertEqual(cfg.get("language"), "de")


class HarnessOptions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_harness_options("language=fr;report_mode=living;grade=;"),
                         {"language": "fr", "report_mode": "living"})

    def test_unsubstituted_values_are_unset(self):
        self.assertEqual(parse_harness_options("language=${user_config.language}"), {})

    def test_bad_pair(self):
        with self.assertRaises(ConfigError):
            parse_harness_options("language")

    def test_eight_options(self):
        text = ("language=fr;report_mode=living;report_numbering=roman;report_formats=md,json;"
                "tree_format=md;run_mode=team;search_max_parallel=5;grade=advanced")
        cfg = config.load(None, {"PROBANDIA_CONFIG_DIR": tempfile.mkdtemp()}, text)
        expected = {"language": "fr", "report.mode": "living", "report.numbering": "roman",
                    "report.formats": ["md", "json"], "tree.format": "md", "run.mode": "team",
                    "search.max_parallel": 5, "grade": "advanced"}
        for key, value in expected.items():
            self.assertEqual(cfg.get(key), value, key)
            self.assertEqual(cfg.origin(key).layer, "harness", key)


class UserFile(unittest.TestCase):
    def test_locations(self):
        p = config.user_config_path({"PROBANDIA_CONFIG_DIR": "/x"})
        self.assertEqual(p, os.path.join("/x", "config.toml"))
        if os.name == "nt":
            self.assertEqual(config.user_config_path({"APPDATA": r"C:\A"}),
                             os.path.join(r"C:\A", "probandia", "config.toml"))
        else:
            self.assertEqual(config.user_config_path({"XDG_CONFIG_HOME": "/c"}),
                             "/c/probandia/config.toml")


class ByteOrderMark(unittest.TestCase):
    """T153: a probandia.toml saved with a BOM (Windows Notepad) is read like any other."""

    def test_status_of_a_project_whose_toml_starts_with_a_bom(self):
        import io
        import shutil

        from probandia import cli
        from tests import ROOT

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = os.path.join(tmp.name, "project")
        shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "project"), project)
        path = os.path.join(project, "probandia.toml")
        with open(path, "rb") as fh:
            body = fh.read()
        with open(path, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + body)
        out = io.StringIO()
        code = cli.main(["status"], stdout=out, cwd=project,
                        environ={"PROBANDIA_CONFIG_DIR": os.path.join(tmp.name, "user"), "PROBANDIA_SESSION": "t"})
        self.assertEqual((code, out.getvalue().splitlines()[0]), (0, "STATUS=OK"), out.getvalue())
