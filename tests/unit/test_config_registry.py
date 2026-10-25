import os
import re
import unittest

from probandia.config import registry
from tests import ROOT

ESSENTIAL = [
    # key, type, default, flag, variable
    ("language", "str", "auto", "--lang", "PROBANDIA_LANGUAGE"),
    ("report.mode", "enum", "journal", "--report-mode", "PROBANDIA_REPORT_MODE"),
    ("report.numbering", "enum", "arabic", "--numbering", "PROBANDIA_REPORT_NUMBERING"),
    ("report.formats", "list", ["md", "html"], "--format", "PROBANDIA_REPORT_FORMATS"),
    ("tree.format", "enum", "all", "--tree-format", "PROBANDIA_TREE_FORMAT"),
    ("run.mode", "enum", "ask", "--mode", "PROBANDIA_RUN_MODE"),
    ("search.max_parallel", "int", 3, "--parallel", "PROBANDIA_SEARCH_MAX_PARALLEL"),
    ("grade", "enum", "essential", "--grade", "PROBANDIA_GRADE"),
]

ADVANCED = [
    ("run.model", "str", "", "--model"),
    ("run.effort", "enum", "", "--effort"),
    ("team.max_agents", "int", None, "--agents"),
    ("team.effort", "enum", None, "--effort"),
    ("team.max_passes", "int", None, "--passes"),
    ("search.model", "str", "", None),
    ("search.effort", "enum", "low", None),
    ("roles.<role>.model", "str", None, None),
    ("roles.<role>.effort", "enum", None, None),
    ("roles.<role>.models", "list", [], None),
    ("providers.enabled", "list", list(registry.DEFAULT_PROVIDERS), None),
    ("providers.disabled", "list", [], None),
    ("providers.allow_card_required", "bool", False, None),
    ("providers.allow_content_reuse", "bool", False, None),
    ("budget.reserve_percent", "int", 10, None),
    ("archives.enabled", "list", list(registry.ARCHIVES), None),
    ("catalogues.max_age_days", "int", 90, None),   # TRUST4-T2
    ("cache.days", "int", 7, "--fresh"),
    ("web.negative_families", "int", 2, None),
    ("proof.standard", "enum", "off", None),
    ("workshop.sync", "enum", "ask", None),
    ("workshop.check", "str", "", None),
    ("privacy.living_years", "int", 100, None),
    ("report.simplified_trees", "bool", True, None),
    ("report.timeline", "enum", "main", None),
    ("report.template", "str", "habillage", None),
    ("report.images", "enum", "folder", None),
    ("report.living_views", "enum", "private", None),
    ("library.save", "enum", "ask", None),
    ("http.contact", "str", "", None),
    ("tui.theme", "str", "dark", None),
]

EXPERT = [
    ("routing.<question_type>", "list"), ("providers.<id>.monthly_cap", "int"),
    ("providers.<id>.cache_ttl", "int"), ("hosts.<host>.rate", "str"),
    ("reading.per_search", "int"),
    ("reading.ladder", "list"), ("reading.readers", "list"), ("reading.max_passages", "int"),
    ("reading.passage_chars", "int"),
    ("read.crawl_max_pages", "int"), ("report.number_pattern", "str"),
    ("templates.dir", "str"), ("locales.dir", "str"),
    ("library.auto_trust_after", "int"), ("hooks.guard", "bool"), ("hooks.digest", "bool"),
    ("hooks.journal", "bool"), ("hooks.verify", "bool"), ("mcp.code_mode", "bool"),
    ("digest.max_lines", "int"), ("locks.expiry_minutes", "int"),
    ("language.detection_order", "list"),
    ("search.native", "bool"), ("search.native_max_per_pass", "int"),
    ("witness.max_age_hours", "int"), ("negatives.recheck_days", "int"),
    ("gramps.url", "str"), ("gramps.user", "str"),
]


class Grades(unittest.TestCase):
    def test_essential(self):
        got = [(s.key, s.type, s.default, s.flag, s.env) for s in registry.by_grade(1)]
        self.assertEqual(got, ESSENTIAL)
        self.assertTrue(all(s.harness for s in registry.by_grade(1)))

    def test_advanced(self):
        got = [(s.key, s.type, None if callable(s.default) else s.default, s.flag)
               for s in registry.by_grade(2)]
        self.assertEqual(got, ADVANCED)
        self.assertFalse(any(s.harness for s in registry.by_grade(2)))

    def test_expert(self):
        self.assertEqual([(s.key, s.type) for s in registry.by_grade(3)], EXPERT)

    def test_every_setting_has_help_and_variable(self):
        for s in registry.SETTINGS:
            self.assertTrue(s.help, s.key)
            self.assertTrue(s.env.startswith("PROBANDIA_"), s.key)

    def test_unique_keys(self):
        keys = [s.key for s in registry.SETTINGS]
        self.assertEqual(len(keys), len(set(keys)))


class Defaults(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(registry.default_of("roles.orchestrator.model"), "sonnet")
        self.assertEqual(registry.default_of("roles.investigator.effort"), "high")
        self.assertEqual(registry.default_of("roles.searcher.model"), "haiku")

    def test_every_provider_is_listed(self):
        # brave and gemini_grounding are kept off by allow_card_required and
        # allow_content_reuse, not by this list; only SerpApi's Bing engine is
        # left out, for its unrelated answers (2 October 2026)
        self.assertEqual(registry.default_of("providers.enabled"),
                         [p for p in registry.PROVIDERS if p != "serpapi_bing"])
        self.assertIs(registry.default_of("providers.allow_card_required"), False)
        self.assertIs(registry.default_of("providers.allow_content_reuse"), False)

    def test_routing(self):
        self.assertEqual(registry.default_of("routing.general"), ["native", "tavily", "linkup"])

    def test_defaults_are_copies(self):
        registry.default_of("report.formats").append("json")
        self.assertEqual(registry.default_of("report.formats"), ["md", "html"])


class Lookup(unittest.TestCase):
    def test_patterns(self):
        self.assertEqual(registry.lookup("roles.reader.model").key, "roles.<role>.model")
        self.assertIsNone(registry.lookup("roles.pilot.model"))
        self.assertEqual(registry.lookup("hosts.gallica.bnf.fr.rate").key, "hosts.<host>.rate")
        self.assertEqual(registry.lookup("providers.gemini_grounding.cache_ttl").key,
                         "providers.<id>.cache_ttl")
        self.assertIsNone(registry.lookup("report.colour"))

    def test_variables(self):
        self.assertEqual(registry.env_lookup("PROBANDIA_REPORT_MODE"), "report.mode")
        self.assertEqual(registry.env_lookup("PROBANDIA_ROLES_RESEARCHER_MODEL"),
                         "roles.researcher.model")
        self.assertEqual(registry.env_lookup("PROBANDIA_PROVIDERS_GEMINI_GROUNDING_MONTHLY_CAP"),
                         "providers.gemini_grounding.monthly_cap")
        self.assertEqual(registry.env_lookup("PROBANDIA_LANG"), "language")
        self.assertEqual(registry.env_lookup("PROBANDIA_CONTACT"), "http.contact")
        self.assertIsNone(registry.env_lookup("PROBANDIA_NOTHING"))

    def test_every_variable_read_is_known(self):
        # config validate warns about unknown PROBANDIA_* variables: none the engine reads may be unknown
        src = os.path.join(ROOT, "src", "probandia")
        found = set()
        for folder, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in ("_vendor", "__pycache__")]
            for name in (f for f in files if f.endswith(".py")):
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    found.update(re.findall(r"PROBANDIA_[A-Z][A-Z_]*[A-Z]", fh.read()))
        unknown = sorted(v for v in found
                         if v not in registry.OTHER_VARIABLES and registry.env_lookup(v) is None)
        self.assertEqual(unknown, [])

    def test_harness_keys(self):
        self.assertEqual([s.harness_key for s in registry.harness_settings()],
                         ["language", "report_mode", "report_numbering", "report_formats",
                          "tree_format", "run_mode", "search_max_parallel", "grade"])


class EverySettingIsRead(unittest.TestCase):
    """T117: a setting the engine never reads is not offered."""

    def sources(self):
        src = os.path.join(ROOT, "src", "probandia")
        text = []
        for folder, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in ("_vendor", "__pycache__")]
            for name in files:
                path = os.path.join(folder, name)
                if name.endswith(".py") and path != registry.__file__:
                    with open(path, encoding="utf-8") as fh:
                        text.append(fh.read())
        return "\n".join(text)

    def test_each_key_is_read_outside_the_registry(self):
        from probandia.roles import FIELDS, OLDER

        text = self.sources()
        older = {f"{o}.{f}" for o in OLDER.values() for f in FIELDS}   # read by roles.resolve, as a fallback
        unread = []
        for s in registry.SETTINGS:
            if s.key in older:
                self.assertIn('old_key = f"{older}.{field}"', text)
                continue
            # roles.<role>.model is read as f"roles.{role}.model" or f"roles.{role}.{field}"
            pattern = re.sub(r"<[^>]+>", r"\\{[^}]+\\}", re.escape(s.key))
            pattern = re.sub(r"\\.(model|effort|models)$", r"\\.(\1|\\{[^}]+\\})", pattern)
            if not re.search(r"""["']""" + pattern + r"""["']""", text):
                unread.append(s.key)
        self.assertEqual(unread, [])

    def test_the_settings_taken_out(self):
        for key in ("evidence.axes", "exports.gedcom", "verify.on_pass_end", "report.anchor_policy", "log.level",
                    "language.detector", "exports.experimental", "gramps.tree"):
            self.assertNotIn(key, registry.BY_KEY)


class TakenOutOrFallback(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(os.path.join(self.tmp.name, "probandia.toml"), "w", encoding="utf-8") as fh:
            fh.write('schema = 1\nlog.level = "debug"\n')
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u")}

    def call(self, *argv):
        import io

        from probandia import cli

        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=self.env, cwd=self.tmp.name)
        return code, out.getvalue()

    def test_explain_a_setting_taken_out(self):
        code, out = self.call("config", "explain", "log.level")
        self.assertEqual(code, 2, out)
        self.assertIn("unknown setting log.level", out)

    def test_a_project_that_still_sets_it_loads_with_a_warning(self):
        from probandia import config as cfgmod

        cfg = cfgmod.load(self.tmp.name, self.env)
        self.assertEqual(len(cfg.warnings), 1)
        self.assertIn("log.level", cfg.warnings[0])
        self.assertEqual(self.call("status")[0], 0)

    def test_explain_says_search_model_is_a_fallback(self):
        code, out = self.call("config", "explain", "search.model")
        self.assertEqual(code, 0, out)
        self.assertIn("a fallback of roles.searcher.model", out)
        self.assertIn("a fallback of roles.orchestrator.effort", self.call("config", "explain", "run.effort")[1])
