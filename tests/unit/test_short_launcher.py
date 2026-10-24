import io
import os
import tempfile
import unittest

from probandia import cli, launcher
from probandia.project import create_project


class ShortLauncher(unittest.TestCase):
    """``.probandia/pb.py`` points at the plugin's engine; a person's installed command leaves it alone."""

    def run_status(self, tmp, **extra):
        env = {"PROBANDIA_CONFIG_DIR": os.path.join(tmp, "u"), "PROBANDIA_SESSION": "s1", **extra}
        out = io.StringIO()
        code = cli.main(["status"], stdout=out, environ=env, cwd=tmp)
        self.assertEqual(code, 0, out.getvalue())
        return os.path.join(tmp, ".probandia", launcher.LAUNCHER)

    def test_a_person_does_not_rewrite_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            create_project(tmp)
            self.assertFalse(os.path.exists(self.run_status(tmp)))

    def test_a_harness_writes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            create_project(tmp)
            self.assertTrue(os.path.isfile(self.run_status(tmp, CLAUDECODE="1")))

    def test_no_engine_to_point_at(self):
        # an installed wheel has no run_probandia.py: nothing is written
        with tempfile.TemporaryDirectory() as tmp:
            create_project(tmp)
            self.assertIsNone(launcher.write_launcher(tmp, engine=os.path.join(tmp, "missing.py")))
            self.assertFalse(os.path.exists(os.path.join(tmp, ".probandia", launcher.LAUNCHER)))

    def test_the_newest_engine_runs_whatever_wrote_last(self):
        # T260: a project opened in Claude Code (0.9.40), then in Codex (0.9.41), then in Claude Code again
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            engines = {}
            for version in ("0.9.40", "0.9.41"):
                engines[version] = os.path.join(tmp, version, "run_probandia.py")
                os.makedirs(os.path.dirname(engines[version]))
                with open(engines[version], "w", encoding="utf-8") as fh:
                    fh.write(f"print({version!r})\n")
            path = launcher.write_launcher(tmp, engines["0.9.40"], "0.9.40")
            launcher.write_launcher(tmp, engines["0.9.41"], "0.9.41")
            launcher.write_launcher(tmp, engines["0.9.40"], "0.9.40")
            self.assertEqual(launcher.known_engines(path), [["0.9.41", engines["0.9.41"]], ["0.9.40", engines["0.9.40"]]])
            ran = subprocess.run([sys.executable, path], capture_output=True, text=True).stdout.strip()
            self.assertEqual(ran, "0.9.41")
            os.remove(engines["0.9.41"])   # a plugin removed: the next one runs, and leaves the list
            self.assertEqual(subprocess.run([sys.executable, path], capture_output=True, text=True).stdout.strip(),
                             "0.9.40")
            launcher.write_launcher(tmp, engines["0.9.40"], "0.9.40")
            self.assertEqual(launcher.known_engines(path), [["0.9.40", engines["0.9.40"]]])

    def test_an_older_launcher_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old", "run_probandia.py")
            os.makedirs(os.path.dirname(old))
            open(old, "w").close()
            path = os.path.join(tmp, ".probandia", launcher.LAUNCHER)
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"import runpy\nENGINE = {old!r}\nrunpy.run_path(ENGINE)\n")
            self.assertEqual(launcher.known_engines(path), [["0", old]])


if __name__ == "__main__":
    unittest.main()
