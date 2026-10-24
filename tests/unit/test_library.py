import http.server
import io
import json
import os
import shutil
import tempfile
import threading
import unittest

from probandia import cli, events
from probandia.library import Library, fill, to_template
from probandia.research import Research
from probandia.util import yamlio
from tests import ROOT

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")
WORKSHOP = os.path.join(ROOT, "tests", "fixtures", "workshop")
RID = "2026-09-30-parents-of-victor-hugo"

OK = '''import os
def run(args, http):
    return [{"q": args.get("q"), "key": os.environ.get("MY_KEY")}]
'''
SECRET = '''import os
def run(args, http):
    return [{"secret": os.environ["OTHER_SECRET"]}]
'''
HOST = '''import urllib.request
def run(args, http):
    urllib.request.urlopen("http://example.org/", timeout=5)
    return [1]
'''
SLOW = '''import time
def run(args, http):
    time.sleep(30)
    return [1]
'''
FETCH = '''import json
def run(args, http):
    resp = http.get(args["url"])
    return json.loads(resp.body)["rows"]
'''


class Server:
    """A local HTTP server: the only host a test script may reach."""

    def __enter__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps({"rows": [{"name": "Hugo"}, {"name": "Hugot"}]}).encode()
                if self.path.startswith("/robots.txt"):
                    body = b"User-agent: *\nAllow: /\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "project")
        shutil.copytree(FIXTURE, self.dir)
        self.env = {"PROBANDIA_CONFIG_DIR": os.path.join(self.tmp.name, "user"), "PROBANDIA_SESSION": "test",
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "claude"), "LANG": "en_US.UTF-8",
                    "MY_KEY": "k1", "OTHER_SECRET": "s3cret"}
        for k in ("SYSTEMROOT", "SystemRoot", "TEMP", "TMP"):
            if k in os.environ:
                self.env[k] = os.environ[k]
        self.research = Research(self.dir, "hugo", RID)

    def call(self, *argv, env=None):
        out = io.StringIO()
        code = cli.main(list(argv), stdout=out, environ=dict(self.env, **(env or {})), cwd=self.dir)
        return code, out.getvalue()

    def value(self, out, key):
        for line in out.splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    def script(self, name, code):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(code)
        return path

    def save(self, sid, code, *extra):
        return self.call("library", "save", self.script(f"{sid}.py", code), "--id", sid, *extra)


class Lifecycle(Base):
    def test_draft_tested_then_draft_again(self):
        code, out = self.save("ok", OK, "--purpose", "echo a query of the Luxembourg archives", "--env", "MY_KEY",
                              "--witness-args", '{"q": "Hugo"}')
        self.assertEqual((code, self.value(out, "STATE")), (0, "draft"))
        code, out = self.call("library", "test", "ok")
        self.assertEqual((code, self.value(out, "STATE")), (0, "tested"), out)
        lib = Library(self.dir)
        ok, rows, _err = lib.run(lib.get("ok"), {"q": "x"}, self.env)
        self.assertEqual(rows, [{"q": "x", "key": "k1"}])  # the declared variable is there
        with open(os.path.join(self.dir, "library", "connectors", "ok.py"), "a", encoding="utf-8") as fh:
            fh.write("# changed\n")
        code, out = self.call("library", "show", "ok")
        self.assertEqual((self.value(out, "STATE"), self.value(out, "VERSION")), ("draft", "2"))

    def test_no_witness_stays_draft(self):
        code, out = self.save("nw", OK, "--purpose", "x")
        self.assertIn("no witness", out)
        code, out = self.call("library", "test", "nw")
        self.assertEqual(code, 1, out)

    def test_trust(self):
        self.save("ok", OK, "--purpose", "x", "--witness-args", "{}")
        code, out = self.call("library", "trust", "ok")
        self.assertEqual(code, 2, out)  # a draft cannot be trusted
        self.call("library", "test", "ok")
        code, out = self.call("library", "trust", "ok")
        self.assertEqual(self.value(out, "STATE"), "trusted")

    def test_auto_trust_in_expert(self):
        self.call("config", "set", "grade", "expert")
        self.call("config", "set", "library.auto_trust_after", "2")
        self.save("ok", OK, "--purpose", "x", "--witness-args", "{}")
        _c, out = self.call("library", "test", "ok")
        self.assertEqual(self.value(out, "STATE"), "tested")
        _c, out = self.call("library", "test", "ok")
        self.assertEqual(self.value(out, "STATE"), "trusted")

    def test_find(self):
        self.save("anlux-births", OK, "--purpose", "births of the Luxembourg national archives", "--hosts",
                  "anlux.public.lu", "--witness-args", "{}")
        self.save("ad25-deaths", OK, "--purpose", "deaths in the Doubs archives", "--witness-args", "{}")
        code, out = self.call("library", "find", "a birth record in Luxembourg")
        lines = [line for line in out.splitlines() if line.startswith("- script=")]
        self.assertTrue(lines[0].startswith("- script=") and "anlux-births" in lines[0], out)


class Confinement(Base):
    def test_undeclared_variable_fails(self):
        self.save("secret", SECRET, "--purpose", "x", "--witness-args", "{}")
        code, out = self.call("library", "test", "secret")
        self.assertEqual(code, 1, out)
        self.assertIn("KeyError: 'OTHER_SECRET'", out)

    def test_undeclared_host_fails(self):
        self.save("host", HOST, "--purpose", "x", "--hosts", "archives.lu", "--witness-args", "{}")
        code, out = self.call("library", "test", "host")
        self.assertEqual(code, 1, out)
        self.assertIn("host example.org is not declared", out)

    def test_declared_host_through_the_client(self):
        with Server() as srv:
            url = f"http://127.0.0.1:{srv.port}/data"
            self.save("fetch", FETCH, "--purpose", "x", "--hosts", "127.0.0.1",
                      "--witness-args", json.dumps({"url": url}), "--expect", "2")
            code, out = self.call("library", "test", "fetch")
            self.assertEqual(code, 0, out)
            lib = Library(self.dir)
            s = dict(lib.get("fetch"), target={"hosts": ["archives.lu"]})
            ok, _rows, error = lib.run(s, {"url": url}, self.env)
            self.assertFalse(ok)
            self.assertIn("127.0.0.1", error)

    ESCAPES = {
        "subprocess": "import subprocess\ndef run(args, http):\n    return [subprocess.run(['curl', 'x'])]\n",
        "os.system": "import os\ndef run(args, http):\n    return [os.system('curl x')]\n",
        "ctypes": "from ctypes import CDLL\ndef run(args, http):\n    return [CDLL]\n",
        "multiprocessing": "import multiprocessing.pool\ndef run(args, http):\n    return [1]\n",
        "socket": "import socket\ndef run(args, http):\n    return [socket.create_connection(('x', 80))]\n",
    }

    def test_an_escaping_script_is_refused_at_save_and_test(self):
        """T139: what gets round the confinement is found by reading the script (ast)."""
        for name, code in self.ESCAPES.items():
            sid = "esc-" + name.replace(".", "-")
            rc, out = self.save(sid, code, "--purpose", "x", "--witness-args", "{}")
            self.assertEqual(rc, 1, out)
            self.assertIn("STATUS=FAIL", out)
            self.assertIn("REASON=confinement", out)
            self.assertIn(f"IMPORTS={name}", out)
            self.assertFalse(os.path.exists(os.path.join(self.dir, "library", "connectors", sid + ".py")))
            # saved clean, then changed by hand: library test refuses it too, and it is a draft again
            self.save(sid, OK, "--purpose", "x", "--witness-args", "{}")
            self.assertEqual(self.call("library", "test", sid)[0], 0)
            with open(os.path.join(self.dir, "library", "connectors", sid + ".py"), "w", encoding="utf-8") as fh:
                fh.write(code)
            rc, out = self.call("library", "test", sid)
            self.assertEqual(rc, 1, out)
            for expected in ("STATUS=FAIL", "REASON=confinement", f"IMPORTS={name}"):
                self.assertIn(expected, out)
            self.assertEqual(Library(self.dir).get(sid)["status"], "draft")

    def test_what_stays_inside_is_kept(self):
        from probandia.library import escapes

        path = self.script("fine.py", "import os, re, json\nfrom os import path\n"
                                      "def run(args, http):\n    return [os.environ.get('X'), re.compile('a')]\n")
        self.assertEqual(escapes(path), [])
        path = self.script("hidden.py", "def run(args, http):\n    return __import__('subprocess')\n")
        self.assertEqual(escapes(path), ["__import__"])

    def test_timeout(self):
        lib = Library(self.dir)
        self.save("slow", SLOW, "--purpose", "x", "--witness-args", "{}")
        ok, _rows, error = lib.run(lib.get("slow"), {}, self.env, timeout=3)
        self.assertFalse(ok)
        self.assertEqual(error, "timeout after 3 s")


class DraftApproval(Base):
    def test_never_without_a_recorded_approval(self):
        self.call("resume", RID, "--mode", "session")
        marker = os.path.join(self.tmp.name, "ran.txt")
        code_text = f'''def run(args, http):
    open({marker!r}, "a").write("x")
    return [1]
'''
        self.save("draft", code_text, "--purpose", "x")
        code, out = self.call("library", "run", "draft", "--research", RID)
        self.assertEqual(code, 3, out)
        self.assertIn("QUESTION=library_run_draft", out)
        self.assertFalse(os.path.exists(marker))
        code, out = self.call("library", "run", "draft", "--research", RID, "--approve")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(marker))
        with open(os.path.join(self.dir, ".probandia", "approved-scripts.json"), encoding="utf-8") as fh:
            approvals = json.load(fh)
        self.assertEqual(approvals[0]["id"], "draft")
        used = [e for e in events.read(self.research.events_path) if e["type"] == "library.used"]
        self.assertEqual(used[0]["payload"]["approval"]["id"], "draft")
        # the guard lets the approved version through, and stops a changed one
        from probandia import guard

        cmd = {"tool_name": "Bash", "cwd": self.dir,
               "tool_input": {"command": "python library/connectors/draft.py"}}
        self.assertIsNone(guard.check(cmd, self.env, "claude-code"))
        with open(os.path.join(self.dir, "library", "connectors", "draft.py"), "a", encoding="utf-8") as fh:
            fh.write("# changed\n")
        Library(self.dir).scripts()
        self.assertEqual(guard.check(cmd, self.env, "claude-code")[0], "G-5")

    def test_stale_witness_is_run_again(self):
        self.save("ok", OK, "--purpose", "x", "--witness-args", "{}")
        self.call("library", "test", "ok")
        Library(self.dir).update("ok", runs={"ok": 1, "failed": 0, "last_ok": "2026-01-01T00:00:00Z"})
        code, out = self.call("library", "run", "ok", "--args", '{"q": "y"}')
        self.assertEqual(code, 0, out)
        self.assertEqual(Library(self.dir).get("ok")["runs"]["ok"], 2)


class Recipes(Base):
    def test_a_query_that_found_a_fact_comes_first(self):
        self.call("resume", RID, "--mode", "session")
        code, out = self.call("plan", RID, "--question-type", "parents")
        self.assertEqual(code, 0, out)
        from probandia.providers import searchlog

        entry = searchlog.entry('"Hugo" Besançon', "provider", "serper", "G", "positive", RID, 2, 7)
        searchlog.append(self.dir, "hugo", [entry], {"harness": "cli", "agent": "session"})
        proposal = {"schema": 1, "id": "01J9ZM00000000000000000088", "research": RID, "pass": 2,
                    "author": {"harness": "cli", "agent": "researcher"},
                    "facts": [{"id": "victor-hugo-1802.marriage", "type": "marriage", "status": "index",
                               "source": "src-01J9ZK3M4X0000000000000002"}]}
        path = os.path.join(self.tmp.name, "p.yaml")
        yamlio.dump(path, proposal)
        self.call("propose", RID, path)
        code, out = self.call("apply", proposal["id"])
        self.assertEqual(code, 0, out)
        recipes = Library(self.dir).recipes("parents")
        self.assertEqual(len(recipes), 1)
        self.assertIn("{surname}", recipes[0]["query_template"])
        self.call("pass", "end", RID, "--summary", "marriage found")
        self.call("resume", RID, "--mode", "session")
        code, out = self.call("plan", RID, "--question-type", "parents", env={"SERPER_API_KEY": "test"})
        plan = yamlio.load(os.path.join(self.research.work, "plan-3.yaml"))
        first = plan["calls"][0]
        self.assertEqual((first["engine"], first["query"], first.get("recipe")),
                         ("serper", '"Hugo" Besançon', recipes[0]["id"]))
        self.assertEqual(sum(1 for c in plan["calls"] if c["engine"] == "serper" and c["query"] == first["query"]), 1)

    def test_templates(self):
        axes = {"names": ["Hugo", "Hugot"], "given": ["Victor"], "places": ["Besançon"],
                "window": {"from": 1797, "to": 1807}}
        t = to_template('"Hugot" Victor Besançon 1797', axes)
        self.assertEqual(t, '"{surname}" {given} {place} {from}')
        self.assertEqual(fill(t, {"names": ["Trébuchet"], "given": ["Sophie"], "places": ["Nantes"],
                                  "window": {"from": 1772}}), '"Trébuchet" Sophie Nantes 1772')


class ImportedConnectors(Base):
    def test_the_import_report_says_tested_or_why_draft(self):
        workshop = os.path.join(self.tmp.name, "workshop")
        shutil.copytree(WORKSHOP, workshop)
        shutil.rmtree(os.path.join(self.dir, "families", "hugo"))
        code, out = self.call("import", workshop)
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.dir, "work", "import-report.md"), encoding="utf-8") as fh:
            report = fh.read()
        self.assertIn("connector ad25: stays draft — no run(args, http) entry point", report)
        self.assertIn("connector echo-index: tested", report)
        scripts = {s["id"]: s for s in Library(self.dir).scripts()}
        self.assertEqual(scripts["ad25"]["target"]["hosts"], ["archives.doubs.fr"])
        self.assertEqual((scripts["ad25"]["status"], scripts["echo-index"]["status"]), ("draft", "tested"))

    def test_a_collector_out_of_its_confinement_is_left_out_alone(self):
        # T175: a collector of the real workshop imports ssl; the import stopped there, half written
        workshop = os.path.join(self.tmp.name, "workshop")
        shutil.copytree(WORKSHOP, workshop)
        with open(os.path.join(workshop, "outils", "collecte", "tls.py"), "w", encoding="utf-8") as fh:
            fh.write("import ssl\n\n\ndef run(args, http):\n    return ssl.OPENSSL_VERSION\n")
        shutil.rmtree(os.path.join(self.dir, "families", "hugo"))
        code, out = self.call("import", workshop)
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.dir, "work", "import-report.md"), encoding="utf-8") as fh:
            report = fh.read()
        self.assertIn("connector tls: not kept — the script gets round its confinement: ssl", report)
        self.assertIn("connector echo-index: tested", report)
        self.assertNotIn("tls", {s["id"] for s in Library(self.dir).scripts()})


class Acceptance(Base):
    """PRD criterion 13: a connector written in pass 1 is reused unchanged in pass 2."""

    def test_saved_found_and_reused(self):
        self.call("resume", RID, "--mode", "session")  # pass 2 stands for the pass that writes it
        self.call("plan", RID)
        code, out = self.save("anlux-births", OK, "--purpose", "births of the Luxembourg national archives",
                              "--env", "MY_KEY", "--witness-args", '{"q": "Hugo"}')
        self.call("library", "test", "anlux-births")
        manifest = yamlio.load(os.path.join(self.dir, "library", "manifest.yaml"))
        saved = manifest["scripts"][0]
        self.assertEqual((saved["status"], saved["witness"]["args"]), ("tested", {"q": "Hugo"}))
        # T226: the script itself is kept in the library, and its bytes are those the manifest names
        import hashlib

        script = os.path.join(self.dir, "library", saved["path"]) if saved.get("path") else next(
            os.path.join(root, f) for root, _d, files in os.walk(os.path.join(self.dir, "library"))
            for f in files if f.startswith("anlux-births") and f.endswith(".py"))
        with open(script, "rb") as fh:
            written = fh.read()
        self.assertEqual(hashlib.sha256(written).hexdigest(), saved["sha256"])
        self.call("pass", "end", RID, "--summary", "connector written")
        self.call("resume", RID, "--mode", "session")
        code, out = self.call("library", "find", "Luxembourg births")
        self.assertIn("anlux-births [tested] v1", out)
        code, out = self.call("library", "run", "anlux-births", "--research", RID, "--args", '{"q": "Hugot"}')
        self.assertEqual(code, 0, out)
        used = [e for e in events.read(self.research.events_path) if e["type"] == "library.used"]
        self.assertEqual(len(used), 1)
        self.assertEqual(used[0]["pass"], 3)
        self.assertEqual((used[0]["payload"]["version"], used[0]["payload"]["sha256"]), (1, saved["sha256"]))
        self.assertNotIn("approval", used[0]["payload"])
        with open(script, "rb") as fh:
            self.assertEqual(fh.read(), written)   # reused unchanged
        from probandia import verify

        self.assertEqual(verify.run(self.dir, self.research, rules=["V-11"])[0][1], "PASS")
