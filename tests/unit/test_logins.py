"""optimize.md § 3: the manual sign-in in the browser — the ``login_required``
question, the sessions' states, the guard, the plan, the team relay, the
manual tasks and what fork and export never copy."""
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from probandia import cli, logins
from probandia.cli import reading_cmd
from probandia.paths import data_root
from probandia.reading.cache import Cache
from probandia.reading.ladder import Reader, login_sites
from probandia.util.http import Client
from tests import ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
PAGES = os.path.join(ROOT, "tests", "fixtures", "pages")
RID = "2026-09-30-parents-of-victor-hugo"
URL = "https://www.familysearch.org/ark:/61903/1:1:TEST"
SIGNIN = "https://ident.familysearch.org/cis-web/oauth2/v3/authorization"
RECORD = ("<html><body><article><h1>Naissance de Victor Hugo</h1>"
          + "".join(f"<p>Le 7 ventôse an X, naissance de Victor Marie, fils de Joseph Léopold Sigisbert Hugo "
                    f"et de Sophie Françoise Trébuchet, ligne {i}.</p>" for i in range(60))
          + "<a href='/logout'>Sign Out</a></article></body></html>")


def signin_page():
    with open(os.path.join(PAGES, "familysearch-signin.html"), encoding="utf-8") as fh:
        return fh.read()


def text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "LANG": "en_US.UTF-8",
                    "PROBANDIA_READING_LADDER": "browser"}
        self.pages = []          # what the simulated browser shows, in turn
        self.opened = []

    def browser(self, url, profile):
        self.opened.append(profile)
        return self.pages.pop(0) if self.pages else (200, RECORD, url)

    def call(self, *argv, env=None):
        def build(ctx, work=None, transport=None):
            state = os.path.join(self.dir, ".probandia")
            client = Client(state, None, ctx.config, lambda *a: (404, {}, b""), sleep=lambda s: None)
            return Reader(client, Cache(self.dir, work), ctx.config, {}, browser=self.browser,
                          state_dir=state, logins=login_sites(self.dir, data_root()))
        out = io.StringIO()
        with mock.patch.object(reading_cmd, "build_reader", build):
            code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        for line in out.splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None


class LoginRequired(Base):
    """3.4, 3.5: a sign-in screen asks the user, never records a negative; the
    answer "connected" reads again and confirms the session."""

    def test_ask_then_connected_reads_and_confirms(self):
        self.pages = [(200, signin_page(), SIGNIN)]
        code, out = self.call("read", URL)
        self.assertEqual(code, 3, out)
        for key, expected in (("STATUS", "ASK"), ("QUESTION", "login_required"), ("ARCHIVE", "familysearch"),
                              ("CHOICES", "connected|skip|stop"), ("DEFAULT", "connected"),
                              ("OPTION", "--login"), ("BROWSER_LOGIN", "probandia browser login familysearch")):
            self.assertEqual(self.value(out, key), expected, out)
        self.assertTrue(self.value(out, "LOGIN_URL").startswith("https://www.familysearch.org/auth/"))
        self.assertEqual(logins.pending(self.dir), ["familysearch"])
        # the user signed in: the same command again, with the answer
        code, out = self.call("read", URL, "--login", "connected")
        self.assertEqual(code, 0, out)
        self.assertIn("STEP=browser", out)
        record = logins.state(self.dir, "familysearch")
        self.assertEqual(record["state"], "confirmed")
        self.assertEqual(logins.pending(self.dir), [])
        # the browser step read with the archive's own profile
        self.assertTrue(self.opened[-1].endswith(os.path.join("browser", "www.familysearch.org")))
        # only a state and a time are kept: never an identifier, a cookie or a token
        self.assertEqual(set(record) - {"state", "ts", "confirmed", "url", "research", "expired"}, set())
        with open(os.path.join(self.dir, ".probandia", "logins-history.jsonl"), encoding="utf-8") as fh:
            states = [json.loads(line)["state"] for line in fh]
        self.assertEqual(states, ["pending", "confirmed"])

    def test_skip_is_not_consulted_and_stop_stops(self):
        code, out = self.call("read", URL, "--login", "skip")
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=login-skipped", out)
        self.assertIn("FAILURE=login", out)
        self.assertIn("no negative can be recorded", out)
        self.assertEqual(logins.state(self.dir, "familysearch")["state"], "skipped")
        code, out = self.call("read", URL, "--login", "stop")
        self.assertEqual(code, 4, out)
        self.assertIn("STATUS=STOP", out)
        self.assertIn("REASON=login-stopped", out)
        self.assertEqual(self.opened, [])     # neither answer opens the page

    def test_login_commands(self):
        code, out = self.call("login", "check", "familysearch")
        self.assertEqual(code, 0, out)
        for key, expected in (("REQUIRED", "true"), ("STATE", "none"), ("VALID", "false")):
            self.assertEqual(self.value(out, key), expected, out)
        self.assertIn("- logged_in_marker=Sign Out", out)
        code, out = self.call("login", "confirm", "familysearch")
        self.assertEqual((code, self.value(out, "STATE"), self.value(out, "VALID")), (0, "confirmed", "true"), out)
        self.assertEqual(self.call("login", "check", "nowhere")[0], 2)

    def test_browser_login_needs_a_terminal(self):
        code, out = self.call("browser", "login", "familysearch")
        self.assertEqual(code, 2, out)


class Expiry(Base):
    """3.11: a sign-in screen after a confirmation records the session's end,
    asks again, and shows in status."""

    def test_expired_session_is_recorded_and_visible(self):
        logins.set_state(self.dir, "familysearch", "confirmed")
        self.pages = [(200, signin_page(), SIGNIN)]
        code, out = self.call("read", URL)
        self.assertEqual(code, 3, out)
        self.assertEqual(self.value(out, "EXPIRED"), "true", out)
        record = logins.state(self.dir, "familysearch")
        self.assertEqual(record["state"], "pending")
        self.assertIn("expired", record)
        code, out = self.call("status")
        self.assertIn("- login=familysearch pending", out)
        self.assertIn("expired=", out)

    def test_validity_follows_session_hours(self):
        now = datetime.datetime(2026, 10, 3, 12, tzinfo=datetime.timezone.utc)
        record = logins.set_state(self.dir, "familysearch", "confirmed", now=now)
        self.assertTrue(logins.valid(record, 12, now + datetime.timedelta(hours=11)))
        self.assertFalse(logins.valid(record, 12, now + datetime.timedelta(hours=13)))
        self.assertFalse(logins.valid({"state": "skipped"}, 12, now))


class Headless(Base):
    """3.10: with nobody to ask, the page becomes a manual task, in the digest
    and in the report; never a negative."""

    def test_manual_task_in_digest_and_report(self):
        self.pages = [(200, signin_page(), SIGNIN)]
        code, out = self.call("read", URL, "--research", RID, env={"PROBANDIA_HEADLESS": "1"})
        self.assertEqual(code, 1, out)
        self.assertIn("REASON=login-required", out)
        self.assertNotIn("STATUS=ASK", out)
        tasks = logins.manual_tasks(self.dir, RID)
        self.assertEqual([(t["archive"], t["url"]) for t in tasks], [("familysearch", URL)])
        self.assertEqual(logins.pending(self.dir), [])
        # once only, however many times the page is met
        logins.add_manual_task(self.dir, RID, "familysearch", URL)
        self.assertEqual(len(logins.manual_tasks(self.dir, RID)), 1)

        from probandia import digest
        from probandia.research import find_research

        research = find_research(self.dir, RID)
        lines = digest.build(self.dir, research)
        self.assertIn("MANUAL_TASKS:", lines)
        self.assertIn(f"  familysearch {URL} (login required)", lines)

        code, out = self.call("render", RID)
        self.assertEqual(code, 0, out)
        found = []
        for d, _dirs, names in os.walk(os.path.join(self.dir, "families")):
            for name in names:
                if name.endswith((".md", ".html")) and "report" in d:
                    with open(os.path.join(d, name), encoding="utf-8") as fh:
                        body = fh.read()
                    # the research's language is French: the labels are translated
                    if "À lire à la main" in body:
                        found.append(name)
                        self.assertIn("non consulté, une connexion est requise", body)
        self.assertTrue(any(f.endswith(".md") for f in found), found)
        self.assertTrue(any(f.endswith(".html") for f in found), found)


class GuardG9(Base):
    """3.6: no browser tool types into a page while a sign-in waits."""

    def check(self, tool, tool_input):
        from probandia import guard

        payload = {"tool_name": tool, "tool_input": tool_input, "cwd": self.dir}
        return guard.check(payload, self.env, "claude-code")

    def test_typing_refused_while_pending(self):
        fill = ("mcp__claude-in-chrome__form_input", {"ref": "password", "value": "x"})
        typing = ("mcp__claude-in-chrome__computer", {"action": "type", "text": "x"})
        click = ("mcp__claude-in-chrome__computer", {"action": "screenshot"})
        self.assertIsNone(self.check(*fill))
        logins.set_state(self.dir, "familysearch", "pending", URL)
        for tool, args in (fill, typing, ("mcp__playwright__browser_type", {"text": "x"})):
            rule, reason = self.check(tool, args)
            self.assertEqual(rule, "G-9")
            self.assertIn("familysearch", reason)
        self.assertIsNone(self.check(*click))
        logins.set_state(self.dir, "familysearch", "confirmed")
        self.assertIsNone(self.check(*fill))


class Plan(Base):
    """3.7: the plan names every archive that needs a sign-in, before the field agents."""

    def test_login_needed_until_confirmed(self):
        from probandia.cli.search_cmd import login_needed

        class Ctx:
            project = self.dir

        doc = {"question": "Birth of Victor Hugo in Besançon", "calls": [{"engine": "familysearch"}],
               "axes": {"places": ["Besançon"], "record_types": ["birth"],
                        "window": {"from": 1797, "to": 1807}}}
        self.assertIn("familysearch", login_needed(Ctx, doc))
        logins.set_state(self.dir, "familysearch", "confirmed")
        self.assertNotIn("familysearch", login_needed(Ctx, doc))

    def new(self, question):
        code, out = self.call("new", question, "--family", "hugo", "--open-pass", "--mode", "session",
                              "--effort", "high", "--output-format", "contract", env={"PROBANDIA_SESSION": "t"})
        self.assertEqual(code, 0, out)
        return out

    def test_a_place_whose_civil_records_all_need_a_sign_in(self):
        # Luxembourg: the civil births and deaths only on FamilySearch, Matricula has the parish registers
        out = self.new("Birth of Victor Hugo, born 1802 at Vianden (Luxembourg), "
                       "died 1885 at Echternach (Luxembourg)")
        self.assertEqual(self.value(out, "PLACE_CODES"), "LU")
        self.assertEqual(self.value(out, "LOGIN_NEEDED"), "familysearch")

    def test_a_department_with_free_registers_needs_no_sign_in(self):
        out = self.new("Birth of Victor Hugo, born 1826 at Octeville (Manche)")
        self.assertEqual(self.value(out, "PLACE_CODES"), "FR-50")
        self.assertEqual(self.value(out, "LOGIN_NEEDED"), "none")


class TeamRelay(Base):
    """3.8: a field agent never asks the user; its login_required question reaches
    the orchestrator through the relay."""

    def test_question_reaches_the_orchestrator(self):
        code, out = self.call("resume", RID, "--mode", "team", "--agents", "3", "--effort", "high",
                              "--passes", "2")
        self.assertEqual(code, 0, out)
        body = f"login_required familysearch {URL}"
        code, out = self.call("team", "send", RID, "--from", "r1-archives", "--to", "orchestrator",
                              "--type", "question", "--body", body)
        self.assertEqual(code, 0, out)
        code, out = self.call("team", "inbox", RID, "--to", "orchestrator")
        self.assertEqual(self.value(out, "MESSAGES"), "1", out)
        self.assertIn('"type": "question"', out)
        self.assertIn(body, out)


class NeverCopied(Base):
    """3.9: the browser profiles, which hold the user's session, stay where they are."""

    def test_fork_and_export_leave_browser_profiles(self):
        profile = os.path.join(self.dir, ".probandia", "browser", "www.familysearch.org")
        os.makedirs(profile)
        with open(os.path.join(profile, "Cookies"), "w", encoding="utf-8") as fh:
            fh.write("session")

        def files():
            return {os.path.relpath(os.path.join(d, f), self.dir).replace(os.sep, "/")
                    for d, _dirs, names in os.walk(self.dir) for f in names}

        before = files()
        self.assertEqual(self.call("fork", RID, "--name", "other", "--no-pass")[0], 0)
        self.call("export", "gedcom551", "--yes")
        added = files() - before
        self.assertTrue(added)
        self.assertEqual([f for f in added if "Cookies" in f or "/browser/" in f], [])


class Documents(unittest.TestCase):
    """3.5, 3.6, 3.8: what the skills and the agents say."""

    def test_browser_skill(self):
        skill = text("skills", "browser", "SKILL.md")
        for needle in ("never type a username or a password", "never create an account",
                       "BROWSER_LOGIN=", "login confirm <archive>", "--login connected", "after two tries",
                       "LOGIN_NEEDED=", "login_required <archive> <url>", "MANUAL_TASKS:"):
            self.assertIn(needle, skill)

    def test_references(self):
        self.assertIn("`LOGIN_NEEDED=`: the `browser` skill", text("skills", "research", "SKILL.md"))
        self.assertIn("`login_required`: the `browser` skill", text("skills", "research", "SKILL.md"))
        self.assertIn("`login_required`", text("skills", "ask", "SKILL.md"))
        self.assertIn("login_required <archive> <url>", text("skills", "team", "SKILL.md"))
        self.assertIn("login_required <archive> <url>", text("skills", "research", "team.md"))
        for agent in ("researcher", "investigator", "reader"):
            self.assertIn("never type in it", text("agents", f"{agent}.md"))


if __name__ == "__main__":
    unittest.main()
