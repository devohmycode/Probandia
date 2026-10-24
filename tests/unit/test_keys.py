"""keys: where the keys come from, check, set, unset, signup (cli.md 5.3; CLI7)."""
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, i18n
from probandia.cli import keys_cmd
from probandia.util import envfile
from probandia.util.http import Client
from tests import ROOT
from tests.unit.test_adapters import fixture
from tests.unit.test_keyboard import TTY

SECRETS = {"SERPER_API_KEY": "serper-SECRET-1111", "TAVILY_API_KEY": "tvly-SECRET-2222",
           "EXA_API_KEY": "exa-SECRET-3333", "BRAVE_API_KEY": "brave-SECRET-4444",
           "OPENWEBNINJA_API_KEY": "own-SECRET-5555"}


class KeysCase(unittest.TestCase):
    def setUp(self):
        i18n.activate("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "sample")
        shutil.copytree(os.path.join(ROOT, "tests", "sample-project"), self.dir)
        self.user = os.path.join(self.tmp.name, "u")
        os.makedirs(self.user)
        with open(os.path.join(self.user, ".env"), "w", encoding="utf-8") as fh:
            fh.write("# my keys\nSERPER_API_KEY=%s\nTAVILY_API_KEY=%s\nOPENWEBNINJA_API_KEY=%s\n" % (
                SECRETS["SERPER_API_KEY"], SECRETS["TAVILY_API_KEY"], SECRETS["OPENWEBNINJA_API_KEY"]))
        with open(os.path.join(self.dir, ".env"), "w", encoding="utf-8") as fh:
            fh.write("EXA_API_KEY=%s\n" % SECRETS["EXA_API_KEY"])
        self.env = {"PROBANDIA_CONFIG_DIR": self.user, "PROBANDIA_DATA_DIR": os.path.join(self.tmp.name, "d"),
                    "NO_COLOR": "1", "PROBANDIA_PAGER": "none", "BRAVE_API_KEY": SECRETS["BRAVE_API_KEY"]}

    def call(self, *argv, terminal=False, keys=None, cwd=None):
        out = TTY() if terminal else io.StringIO()
        stdin = TTY("".join(k + "\n" for k in keys or []))
        code = cli.main(list(argv), stdout=out, environ=self.env, cwd=cwd or self.dir, stdin=stdin)
        return code, out.getvalue()

    def assertNoSecret(self, text):
        for value in SECRETS.values():
            self.assertNotIn(value, text)
            self.assertNotIn(value[-8:], text)


class Listing(KeysCase):
    """CLI7-T1: keys and keys where."""

    def test_every_format_hides_the_values(self):
        for argv, terminal in ((["keys"], False), (["keys"], True), (["keys", "--json"], False),
                               (["keys", "where"], True), (["keys", "where", "--json"], False)):
            code, out = self.call(*argv, terminal=terminal)
            self.assertEqual(code, 0, out)
            self.assertNoSecret(out)

    def test_where_each_key_comes_from(self):
        rows = {r["variable"]: r for r in json.loads(self.call("keys", "--json")[1])["data"]["keys"]}
        self.assertEqual(rows["SERPER_API_KEY"]["source"], "user")
        self.assertEqual(rows["EXA_API_KEY"]["source"], "project")
        self.assertEqual(rows["BRAVE_API_KEY"]["source"], "environment")
        self.assertFalse(rows["LINKUP_API_KEY"]["present"])
        self.assertEqual(rows["OPENWEBNINJA_API_KEY"]["unlocks"],
                         ["openwebninja_search", "openwebninja_news", "openwebninja_books"])
        from probandia.ledger import fingerprint

        self.assertEqual(rows["SERPER_API_KEY"]["fingerprint"], fingerprint(SECRETS["SERPER_API_KEY"]))

    def test_readable(self):
        code, out = self.call("keys", terminal=True)
        self.assertIn("✓ SERPER_API_KEY", out)
        self.assertIn("project .env", out)

    def test_where(self):
        code, out = self.call("keys", "where")
        self.assertIn("- file=user present ", out)
        self.assertIn("- file=project present ", out)

    def test_outside_a_project(self):
        folder = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(folder)
        code, out = self.call("keys", "--json", cwd=folder)
        self.assertEqual(code, 0, out)
        rows = {r["variable"]: r for r in json.loads(out)["data"]["keys"]}
        self.assertFalse(rows["EXA_API_KEY"]["present"])


class Checking(KeysCase):
    """CLI7-T2: keys check reads the balances, for free."""

    def check(self, *argv, answers):
        sent = []

        def transport(method, url, headers, body, timeout):
            sent.append(url)
            for prefix, (provider, name) in answers.items():
                if url.startswith(prefix):
                    fx = fixture(provider, name)
                    b = fx["body"]
                    return fx["status"], fx.get("headers", {}), (b if isinstance(b, str) else json.dumps(b)).encode(), url
            return 404, {}, b"no route", url

        def make_client(ctx):
            from probandia import config

            return Client(os.path.join(self.dir, ".probandia"), None, config.load(self.dir, ctx.environ), transport,
                          sleep=lambda s: None), None

        with mock.patch.object(keys_cmd, "_client", make_client):
            code, out = self.call("keys", "check", *argv)
        return code, out, sent

    def test_valid_refused_and_no_free_check(self):
        code, out, sent = self.check(answers={
            "https://google.serper.dev/account": ("serper", "account.json"),
            "https://api.tavily.com/usage": ("tavily", "error-401.json"),
            "https://api.openwebninja.com/usage": ("openwebninja_search", "error-403-not-subscribed.json")})
        self.assertEqual(code, 0, out)
        self.assertIn("- key=SERPER_API_KEY serper valid", out)
        self.assertIn("- key=TAVILY_API_KEY tavily refused HTTP 401", out)
        self.assertIn("- key=OPENWEBNINJA_API_KEY openwebninja_search not-subscribed", out)
        self.assertIn("- key=BRAVE_API_KEY - no-free-check\n", out)
        self.assertIn("- key=EXA_API_KEY - no-free-check\n", out)
        self.assertFalse(any("brave" in u or "exa.ai" in u for u in sent))   # no call where no free check exists
        self.assertNoSecret(out)

    def test_one_variable(self):
        code, out, sent = self.check("SERPER_API_KEY", answers={
            "https://google.serper.dev/account": ("serper", "error-401.json")})
        self.assertIn("refused", out)
        self.assertEqual(len(sent), 1)

    def test_unknown_variable(self):
        code, out, sent = self.check("SERPER_KEY", answers={})
        self.assertEqual(code, 2)
        self.assertIn("did you mean SERPER_API_KEY?", out)


class Writing(KeysCase):
    """CLI7-T4: keys set and unset (decision D-7)."""

    def user_env(self):
        with open(os.path.join(self.user, ".env"), encoding="utf-8") as fh:
            return fh.read()

    def test_add_without_echo(self):
        code, out = self.call("keys", "set", "LINKUP_API_KEY", terminal=True, keys=["lk-NEW-VALUE-9999"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("lk-NEW-VALUE-9999", out)
        self.assertIn("LINKUP_API_KEY=lk-NEW-VALUE-9999\n", self.user_env())
        self.assertIn("# my keys\n", self.user_env())   # comments and other lines stay
        self.assertIn("SERPER_API_KEY=%s" % SECRETS["SERPER_API_KEY"], self.user_env())

    def test_getpass_at_a_real_terminal(self):
        import sys

        class Real(io.StringIO):
            def isatty(self):
                return True

        with mock.patch.object(sys, "stdin", Real()), \
                mock.patch("getpass.getpass", return_value="gp-VALUE-7777") as gp:
            out = io.StringIO()
            ctx = mock.Mock(stdin=sys.stdin, stdout=out, asks=True)
            self.assertEqual(keys_cmd._secret(ctx, "X: "), "gp-VALUE-7777")
        gp.assert_called_once()
        self.assertEqual(out.getvalue(), "")

    def test_replace_asks_first(self):
        code, out = self.call("keys", "set", "SERPER_API_KEY", terminal=True, keys=["n"])
        self.assertEqual(code, 4, out)
        self.assertIn("SERPER_API_KEY=%s" % SECRETS["SERPER_API_KEY"], self.user_env())
        code, out = self.call("keys", "set", "SERPER_API_KEY", terminal=True, keys=["y", "serper-NEW-0000"])
        self.assertEqual(code, 0, out)
        self.assertIn("SERPER_API_KEY=serper-NEW-0000\n", self.user_env())
        self.assertNotIn(SECRETS["SERPER_API_KEY"], self.user_env())

    def test_in_project(self):
        self.call("keys", "set", "LINKUP_API_KEY", "--in-project", keys=["lk-P"])
        with open(os.path.join(self.dir, ".env"), encoding="utf-8") as fh:
            self.assertIn("LINKUP_API_KEY=lk-P\n", fh.read())
        self.assertNotIn("LINKUP", self.user_env())

    def test_unset(self):
        code, out = self.call("keys", "unset", "TAVILY_API_KEY", terminal=True, keys=["y"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("TAVILY_API_KEY", self.user_env())
        code, out = self.call("keys", "unset", "TAVILY_API_KEY")
        self.assertIn("STATUS=WARN", out)

    def test_restricted_rights_on_posix(self):
        if os.name == "nt":
            self.skipTest("POSIX rights")
        self.call("keys", "set", "LINKUP_API_KEY", keys=["x"])
        self.assertEqual(os.stat(os.path.join(self.user, ".env")).st_mode & 0o777, 0o600)

    def test_values_round_trip(self):
        path = os.path.join(self.tmp.name, "t.env")
        for value in ("plain", "with space", 'q"uote', "back\\slash", "#hash", "a # b"):
            envfile.set_value(path, "K", value)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(envfile.parse(fh.read())["K"], value)


class Signup(KeysCase):
    """CLI7-T5: keys signup opens the page and recalls the tier."""

    def test_opens_the_page(self):
        with mock.patch.object(keys_cmd, "_open", return_value=True) as opened:
            code, out = self.call("keys", "signup", "serper")
        self.assertEqual(code, 0, out)
        opened.assert_called_once()
        self.assertTrue(opened.call_args[0][0].startswith("https://serper.dev"))
        self.assertIn("then: probandia keys set SERPER_API_KEY", out)

    def test_card_and_openwebninja_notes(self):
        with mock.patch.object(keys_cmd, "_open", return_value=True):
            self.assertIn("credit card", self.call("keys", "signup", "brave")[1])
            self.assertIn("subscribe the account", self.call("keys", "signup", "openwebninja_search")[1])


if __name__ == "__main__":
    unittest.main()
