import io
import unittest

from probandia import __version__, cli
from probandia.errors import UsageError


class Shortcuts(unittest.TestCase):
    """Root shortcuts and short options (decision D-5)."""

    def test_status_shortcut(self):
        self.assertEqual(cli.expand_shortcut(["-s", "--family", "x"]), ["status", "--family", "x"])
        self.assertEqual(cli.expand_shortcut(["--status"]), ["status"])

    def test_after_global_options(self):
        self.assertEqual(cli.expand_shortcut(["-p", "C:/x", "-q", "-s"]), ["-p", "C:/x", "-q", "status"])
        self.assertEqual(cli.expand_shortcut(["--lang=fr", "-s"]), ["--lang=fr", "status"])

    def test_commands_are_left_alone(self):
        self.assertEqual(cli.expand_shortcut(["status", "-s"]), ["status", "-s"])
        self.assertEqual(cli.expand_shortcut(["-h"]), ["-h"])

    def test_unknown_shortcut_lists_the_known_ones(self):
        with self.assertRaises(UsageError) as err:
            cli.expand_shortcut(["-x"])
        self.assertIn("-s (status)", " ".join(err.exception.lines))
        out = io.StringIO()
        self.assertEqual(cli.main(["-x"], stdout=out, environ={}), 2)

    def test_short_options(self):
        args = cli.build_parser().parse_args(["-p", "C:/x", "-l", "fr", "-q", "doctor"])
        self.assertEqual((args.project, args.lang, args.quiet), ("C:/x", "fr", True))

    def test_version(self):
        out = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["-V"])
        self.assertEqual(out.getvalue().strip(), f"probandia {__version__}")


if __name__ == "__main__":
    unittest.main()
