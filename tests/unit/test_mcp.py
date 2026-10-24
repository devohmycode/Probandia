import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from probandia import mcp
from tests import ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
RID = "2026-09-30-parents-of-victor-hugo"


class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "PROBANDIA_SESSION": "mcp",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"), "LANG": "en_US.UTF-8"}

    def rpc(self, method, params=None, msg_id=1):
        return mcp.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
                          self.env, self.dir)

    def call(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return r["content"][0]["text"], r["isError"]

    def test_discover_and_negotiation(self):
        d = self.rpc("server/discover")["result"]
        self.assertEqual(d["supportedVersions"][:2], ["2026-07-28", "2025-11-25"])
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "2025-11-25"})["result"]["protocolVersion"],
                         "2025-11-25")
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"],
                         "2026-07-28")
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.rpc("no/such")["error"]["code"], -32601)

    def test_tools_in_alphabetical_order(self):
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 17)
        for forbidden in ("apply", "event", "lock", "config"):
            self.assertNotIn(forbidden, names)

    def test_code_mode_off_lists_the_operations(self):
        with open(os.path.join(self.dir, "probandia.toml"), "a", encoding="utf-8") as fh:
            fh.write('grade = "expert"\n[mcp]\ncode_mode = false\n')
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertIn("op_iiif_info", names)
        self.assertEqual(names, sorted(names))

    def test_dates(self):
        text, err = self.call("dates", {"text": "vingt-six février mil huit cent deux"})
        self.assertFalse(err)
        self.assertIn("ISO=1802-02-26", text)

    def test_forbidden_host_refused_by_the_server(self):
        text, err = self.call("run_operation", {"operation": "iiif.info",
                                                "args": {"url": "https://francearchives.gouv.fr/x/info.json"}})
        self.assertTrue(err)
        self.assertIn("REASON=third-party-forbidden", text)
        self.assertIn("ARCHIVE=socface", text)

    def test_errors_and_size(self):
        text, err = self.call("verify", {"research": "no-such-research"})
        self.assertTrue(err)
        self.assertTrue(text.startswith("STATUS=FAIL"))
        long_text = "STATUS=OK\n" + "".join(f"- line {i} " + "x" * 80 + "\n" for i in range(200))
        spilled = mcp._spill(long_text, self.dir)
        self.assertLessEqual(len(spilled.encode("utf-8")), mcp.MAX_BYTES)
        path = spilled.rsplit("DETAILS=", 1)[1].strip()
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), long_text)
        self.assertLessEqual(len(json.dumps(mcp._result("y" * 9000, False)["content"][0]["text"])), 4200)

    def test_propose_and_known(self):
        proposal = {"schema": 1, "research": RID, "pass": 1, "author": {"harness": "cli", "agent": "researcher"},
                    "facts": [{"id": "victor-hugo-1802.residence", "type": "residence", "status": "hypothesis"}]}
        text, err = self.call("propose", {"research": RID, "proposal": proposal})
        self.assertFalse(err, text)
        self.assertIn("PROPOSAL=", text)
        text, err = self.call("known", {"research": RID, "names": "Hugo"})
        self.assertFalse(err, text)
        self.assertIn("victor-hugo-1802.birth", text)

    def test_question(self):
        text, err = self.call("question", {"research": RID})
        self.assertFalse(err, text)
        self.assertIn("Q1=open parents", text)
        # read only: an action is no argument of the tool, and nothing is written
        self.assertEqual(mcp.argv_for("question", {"research": RID, "action": "answer", "question": "Q1"}),
                         ["question", "list", "--research", RID])
        schema = [t for t in self.rpc("tools/list")["result"]["tools"] if t["name"] == "question"][0]
        self.assertEqual(list(schema["inputSchema"]["properties"]), ["research"])
        meta = os.path.join(self.dir, "families", "hugo", "research", RID, "research.yaml")
        with open(meta, encoding="utf-8") as fh:
            self.assertNotIn("questions:", fh.read())

    def test_resources(self):
        # T72: the settings and the digests only; a family's raw index is read with the known tool
        from probandia.research import all_researches

        uris = [r["uri"] for r in self.rpc("resources/list")["result"]["resources"]]
        self.assertEqual(uris, ["probandia://config"] + [f"probandia://research/{r.id}/digest"
                                                         for r in all_researches(self.dir)])
        self.assertIn(f"probandia://research/{RID}/digest", uris)
        self.assertFalse([u for u in uris if u.startswith("probandia://family/")], uris)
        digest = self.rpc("resources/read", {"uri": f"probandia://research/{RID}/digest"})["result"]
        self.assertIn("NEGATIVES_DUE:", digest["contents"][0]["text"])
        config = self.rpc("resources/read", {"uri": "probandia://config"})["result"]["contents"][0]["text"]
        self.assertIn("- language=", config)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "families", "hugo", "index", "persons.yaml")))
        for uri in ("probandia://family/hugo/index/persons", "probandia://nothing"):
            self.assertEqual(self.rpc("resources/read", {"uri": uri})["error"]["code"], -32002, uri)

    def test_over_stdio(self):
        msgs = "\n".join(json.dumps(m) for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "variants", "arguments": {"surname": "Hugo"}}})) + "\nnot json\n"
        env = dict(os.environ, **self.env)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "run_probandia.py"), "mcp"], input=msgs,
                             capture_output=True, text=True, encoding="utf-8", env=env, cwd=self.dir, timeout=60)
        replies = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual([r.get("id") for r in replies], [1, 2, None])
        self.assertIn("Hugot", replies[1]["result"]["content"][0]["text"])
        self.assertEqual(replies[2]["error"]["code"], -32700)

    def test_over_stdio_in_utf8_whatever_the_locale(self):
        # T131: bytes in UTF-8, with neither PYTHONUTF8 nor PYTHONIOENCODING (a Windows pipe reads cp1252)
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "variants", "arguments": {"surname": "Lefèvre"}}}, ensure_ascii=False)
        env = {k: v for k, v in dict(os.environ, **self.env).items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        out = subprocess.run([sys.executable, os.path.join(ROOT, "run_probandia.py"), "mcp"],
                             input=(msg + "\n").encode("utf-8"), capture_output=True, env=env, cwd=self.dir,
                             timeout=60)
        reply = json.loads(out.stdout.decode("utf-8"))
        self.assertIn("SURNAME=Lefèvre", reply["result"]["content"][0]["text"])

    def test_the_project_from_the_client_roots(self):
        # T132: started in the plugin's folder, the server asks the client its roots (MCP roots/list)
        import pathlib

        env = {k: v for k, v in dict(os.environ, **self.env).items() if k != "PROBANDIA_PROJECT"}
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "run_probandia.py"), "mcp"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, env=env, cwd=ROOT, text=True, encoding="utf-8")
        self.addCleanup(proc.wait, 60)

        def send(obj):
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

        def known():
            send({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "known",
                                                                              "arguments": {"research": RID}}})
            return json.loads(proc.stdout.readline())["result"]["content"][0]["text"]

        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {"roots": {"listChanged": True}},
                             "clientInfo": {"name": "test", "version": "1"}}})
            self.assertEqual(json.loads(proc.stdout.readline())["id"], 1)
            self.assertFalse(known().startswith("STATUS=OK"))   # the plugin's folder holds no project
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            asked = json.loads(proc.stdout.readline())
            self.assertEqual(asked["method"], "roots/list")
            send({"jsonrpc": "2.0", "id": asked["id"],
                  "result": {"roots": [{"uri": pathlib.Path(self.dir).as_uri(), "name": "project"}]}})
            self.assertTrue(known().startswith("STATUS=OK"))
        finally:
            proc.stdin.close()
            proc.stdout.close()

    def test_silent_outside_a_project(self):
        outside = os.path.join(self.tmp.name, "nowhere")
        os.makedirs(outside)
        r = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, self.env, outside)
        self.assertEqual(r["result"]["resources"], [])
        text, err = mcp.call_tool("dates", {"text": "1802"}, self.env, outside)
        self.assertFalse(err)
