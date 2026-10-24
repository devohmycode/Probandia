"""The themes of probandia tui (version-1.0.0 T94): config.themes, and config theme list, save and delete."""
import io
import json
import os
import tempfile
import unittest

from probandia import cli
from probandia.config import themes


class Themes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "u")}

    def call(self, *argv):
        out = io.StringIO()
        code = cli.main([*argv, "--json"], stdout=out, environ=self.env, cwd=self.tmp.name)
        return code, json.loads(out.getvalue())

    def write(self, name, text):
        os.makedirs(themes.folder(self.env), exist_ok=True)
        with open(themes.path_of(name, self.env), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_probandia_themes_come_first(self):
        found, problems = themes.load(self.env)
        self.assertEqual(list(found), ["dark", "light"])
        self.assertEqual(problems, {})
        self.assertEqual(found["dark"]["colors"]["warning"], "#E8913A")
        self.assertEqual(found["light"]["layout"], themes.default_layout())

    def test_saved_then_read_back(self):
        saved, path, replaced = themes.save("mine", "light", None, [("primary", "#112233"), ("buttons", "tall"),
                                                                     ("zebra", "false"), ("tree_width", "60")],
                                            self.env)
        self.assertFalse(replaced)
        self.assertEqual(path, os.path.join(self.env["PROBANDIA_CONFIG_DIR"], "themes", "mine.toml"))
        found, problems = themes.load(self.env)
        self.assertEqual(problems, {})
        mine = found["mine"]
        self.assertEqual((mine["base"], mine["builtin"], mine["file"]), ("light", False, path))
        self.assertEqual(mine["colors"], dict(themes.PALETTES["light"], primary="#112233"))
        self.assertEqual(mine["layout"], dict(themes.default_layout(), buttons="tall", zebra=False, tree_width=60))
        again, _path, replaced = themes.save("mine", changes=[("accent", "#aabbcc")], environ=self.env)
        self.assertTrue(replaced)
        self.assertEqual(again["colors"]["primary"], "#112233")   # the theme itself, changed
        self.assertEqual(again["colors"]["accent"], "#AABBCC")

    def test_wrong_values_are_refused(self):
        for changes in ([("primary", "red")], [("buttons", "huge")], [("tree_width", "90")], [("zebra", "maybe")],
                        [("nothing", "1")]):
            with self.assertRaises(ValueError, msg=changes):
                themes.save("mine", changes=changes, environ=self.env)
        for name in ("dark", "light", "Mine", "-x", "a" * 41, "a b"):
            with self.assertRaises(ValueError, msg=name):
                themes.save(name, environ=self.env)
        self.assertFalse(os.path.exists(themes.folder(self.env)))   # nothing written

    def test_a_file_edited_by_hand_never_stops_the_application(self):
        self.write("hand", 'base = "light"\n[colors]\nprimary = "blue"\nerror = "#FF0000"\n'
                           '[layout]\nframes = "dotted"\nzebra = false\nother = 1\n')
        self.write("broken", "base = \n")
        self.write("Bad Name", 'base = "dark"\n')
        found, problems = themes.load(self.env)
        self.assertEqual(found["hand"]["colors"], dict(themes.PALETTES["light"], error="#FF0000"))
        self.assertEqual(found["hand"]["layout"], dict(themes.default_layout(), zebra=False))
        self.assertEqual(len(problems["hand"]), 3)   # primary, frames, other
        self.assertEqual(found["broken"]["colors"], themes.PALETTES["dark"])
        self.assertEqual(len(problems["broken"]), 1)
        self.assertNotIn("Bad Name", found)
        self.assertIn("Bad Name", problems)

    def test_config_theme_save_list_delete(self):
        code, d = self.call("config", "theme", "save", "sepia", "--base", "light", "--set", "primary=#704214",
                            "--set", "frames=double")
        self.assertEqual(code, 0, d)
        self.assertEqual((d["values"]["THEME"], d["values"]["BASE"], d["values"]["REPLACED"]), ("sepia", "light", False))
        code, d = self.call("config", "theme", "list")
        self.assertEqual(code, 0, d)
        self.assertEqual(d["values"]["IN_USE"], "dark")
        rows = {r["theme"]: r for r in d["data"]["themes"]}
        self.assertEqual(list(rows), ["dark", "light", "sepia"])
        self.assertEqual((rows["sepia"]["kind"], rows["sepia"]["base"]), ("user", "light"))
        self.assertTrue(rows["dark"]["in_use"])

        code, d = self.call("config", "set", "--user", "tui.theme", "sepia")
        self.assertEqual(code, 0, d)
        code, d = self.call("config", "theme", "list")
        self.assertEqual(d["values"]["IN_USE"], "sepia")

        code, d = self.call("config", "theme", "delete", "sepia", "--yes")
        self.assertEqual(code, 0, d)
        self.assertEqual(d["status"], "WARN")   # tui.theme still names it
        self.assertFalse(os.path.exists(themes.path_of("sepia", self.env)))
        code, d = self.call("config", "theme", "list")
        self.assertEqual(d["status"], "WARN")

    def test_config_theme_refuses_wrong_values(self):
        for argv in (("save", "mine", "--set", "primary=red"), ("save", "mine", "--set", "primary"),
                     ("save", "dark"), ("delete", "light")):
            code, d = self.call("config", "theme", *argv)
            self.assertEqual(code, 2, (argv, d))
        self.assertFalse(os.path.exists(themes.folder(self.env)))


if __name__ == "__main__":
    unittest.main()
