"""The contract's keys that skills, agents and commands read, frozen (AGENTS.md "Two output readers").

A key read by the plugin's text must still be written by the engine: renaming it
in ``src/`` breaks ``test_every_key_read_is_written`` and the contract goldens of
``tests/golden/contract/``. ``PROBANDIA_UPDATE_GOLDEN=1`` rewrites the goldens and
``keys-read.txt``, the list of the keys read: a change there is a change of the
contract (see STABILITY.md).
"""
import json
import os
import re
import unittest
from unittest import mock

from probandia import questions
from probandia.cli.output import ASK_GROUP_PREFIXES
from tests import REUSE, ROOT
from tests.unit.test_human import golden
from tests.unit.test_views import RESEARCH, ViewCase, steady

CONTRACT = os.path.join(ROOT, "tests", "golden", "contract")
PLUGIN = ("skills", "agents", "commands", "droids", "cursor")
KEY = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]*)=")
GENERIC = {"KEY"}  # "KEY=value", the contract's form itself


def _texts(*folders):
    for folder in folders:
        for base, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for name in files:
                with open(os.path.join(base, name), encoding="utf-8", errors="replace") as fh:
                    yield fh.read()


def keys_read():
    return sorted({k for text in _texts(*PLUGIN) for k in KEY.findall(text)})


class KeysRead(unittest.TestCase):
    def test_the_keys_read_are_frozen(self):
        golden(self, "keys-read", "\n".join(keys_read()) + "\n", folder=CONTRACT)

    def test_every_key_read_is_written(self):
        src = "\n".join(_texts(os.path.join("src", "probandia")))
        missing = []
        for key in keys_read():
            if key in GENERIC:
                continue
            group = next((p for p in ASK_GROUP_PREFIXES if key.startswith(p)), None)
            if group and key[len(group):].lower() in questions.SPECS:
                continue  # PROMPT_<ID>, CHOICES_<ID>…: written for each grouped question (questions.ask)
            if not re.search(rf"[\"']{key}[\"'=]", src):
                missing.append(key)
        self.assertEqual(missing, [], "keys read by the plugin that the engine no longer writes")


class Goldens(ViewCase):
    """The contract of the commands the skills run, line for line."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch("probandia.cli.search_cmd.auto_sync", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def contract(self, *argv, env=None):
        code, out = self.call(*argv, "--output-format", "contract", terminal=False, env=env)
        return code, out

    def steady(self, text):
        import datetime as dt

        text = text.replace(self.dir, "<project>").replace(self.tmp.name, "<tmp>").replace("\\", "/")
        text = text.replace(dt.date.today().isoformat(), "<today>")
        return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", "<time>", steady(text))

    def check(self, name, expected_code, *argv, env=None):
        code, out = self.contract(*argv, env=env)
        self.assertEqual(code, expected_code, out)
        self.assertTrue(out.startswith("STATUS="), out)
        golden(self, name, self.steady(out), folder=CONTRACT)
        return out

    def test_new(self):
        self.check("new", 0, "new", "Who were the parents of Henri Marchand?", env={"PROBANDIA_RUN_MODE": "session"})

    def test_status_and_quota(self):
        self.check("status", 0, "status")
        self.check("quota", 0, "quota", "show")

    def test_verify(self):
        self.check("verify", 1, "verify", "2026-09")

    def test_a_pass(self):
        agent = {"CLAUDECODE": "1"}
        self.check("resume", 0, "resume", RESEARCH, env=agent)
        self.check("plan", 0, "plan", RESEARCH, env=agent)
        draft = os.path.join(self.tmp.name, "draft.json")
        with open(draft, "w", encoding="utf-8") as fh:
            json.dump({"hypotheses": [{"id": "h-contract", "question": "Who was Henri Marchand's father?",
                                       "hypotheses": [{"id": "a", "statement": "Jean Marchand",
                                                       "status": "open"}]}]}, fh)
        out = self.check("propose", 0, "propose", RESEARCH, draft, env=agent)
        proposal = re.search(r"^PROPOSAL=(\S+)", out, re.M).group(1)
        self.check("apply", 0, "apply", proposal, env=agent)
        self.check("pass-end", 0, "pass", "end", RESEARCH, "--summary", "a hypothesis opened", env=agent)

    def test_search(self):
        from probandia.cli import search_cmd
        from probandia.util.http import Client
        from tests.unit.test_adapters import fixture

        def transport(method, url, headers, body, timeout):
            if url.startswith("https://api.tavily.com/search"):
                fx = fixture("tavily", "search-ok.json")
                return fx["status"], fx.get("headers", {}), json.dumps(fx["body"]).encode(), url
            return 404, {}, b"", url

        def make_client(ctx):
            return Client(os.path.join(self.dir, ".probandia"), None, ctx.config, transport, sleep=lambda s: None)

        with mock.patch.object(search_cmd, "_client", make_client):
            self.check("search", 0, "search", "Hugo Besançon", "--engine", "tavily", "--research", RESEARCH,
                       env=REUSE)   # T217: Tavily may train on what it is sent

    def test_read(self):
        from probandia.cli import reading_cmd
        from probandia.reading.ladder import ReadResult

        class Reader:
            def read(self, url, fresh=False, max_step=None):
                r = ReadResult(url)
                r.status, r.step, r.extractor = "ok", "reader", "jina"
                r.text = "Acte de naissance de Louis Marchand, né à Bourg-Vert le 2 mars 1898, fils de Henri."
                r.tried = [("http", "blocked"), ("reader:jina", "ok")]
                r.spent = [("jina", "read", 3000)]
                return r

        with mock.patch.object(reading_cmd, "build_reader", lambda ctx, work: Reader()):
            self.check("read", 0, "read", "https://example.org/acte", "--question", "naissance Louis Marchand")


if __name__ == "__main__":
    unittest.main()
