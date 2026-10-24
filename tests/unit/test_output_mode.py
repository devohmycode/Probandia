import io
import unittest

from probandia import cli


class Terminal(io.StringIO):
    def isatty(self):
        return True


def mode(argv=(), terminal=True, **environ):
    args = cli.build_parser().parse_args(list(argv) + ["doctor"])
    for k, v in cli.GLOBAL_DEFAULTS.items():
        if not hasattr(args, k):
            setattr(args, k, v)
    stream = Terminal() if terminal else io.StringIO()
    return cli.output_mode(args, list(argv), stream, environ)


class OutputMode(unittest.TestCase):
    """Who reads the output (cli.md § 6.1, decision D-2): a person at a terminal, or an agent."""

    def test_a_person_at_a_terminal(self):
        self.assertEqual(mode(), "human")

    def test_redirected_output(self):
        self.assertEqual(mode(terminal=False), "contract")

    def test_a_harness_at_a_terminal(self):
        self.assertEqual(mode(CLAUDECODE="1"), "contract")
        self.assertEqual(mode(["--harness", "codex"]), "contract")

    def test_json_and_quiet(self):
        self.assertEqual(mode(["--json"]), "json")
        self.assertEqual(mode(["--quiet"]), "contract")

    def test_explicit_format(self):
        self.assertEqual(mode(["--output-format", "human"], terminal=False), "human")
        self.assertEqual(mode(["--output-format", "contract"]), "contract")
        self.assertEqual(mode(["--output-format", "json"]), "json")

    def test_variable(self):
        self.assertEqual(mode(PROBANDIA_OUTPUT="contract"), "contract")
        self.assertEqual(mode(terminal=False, PROBANDIA_OUTPUT="human"), "human")
        # a harness never gets the readable output from a variable it inherited
        self.assertEqual(mode(PROBANDIA_OUTPUT="human", CLAUDECODE="1"), "contract")

    def test_the_mcp_server_gets_the_contract(self):
        # the server calls main with a StringIO and an explicit --harness
        out = io.StringIO()
        cli.main(["dates", "1851", "--harness", "claude-code"], stdout=out, environ={})
        self.assertTrue(out.getvalue().startswith("STATUS=OK\n"))

    def test_before_the_arguments_are_parsed(self):
        self.assertEqual(cli.output_mode(None, ["--json", "nonsense"], Terminal(), {}), "json")
        self.assertEqual(cli.output_mode(None, ["nonsense"], io.StringIO(), {}), "contract")


if __name__ == "__main__":
    unittest.main()
