"""The HTTP client against a real local server: truncated answers, robots.txt out of reach, state file names."""
import http.client
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from probandia.errors import NetworkError
from probandia.util import http as phttp
from tests import ROOT, SRC

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "project")


class Server:
    """A local HTTP server; ``routes``: {path: (status, announced length or None, body)}."""

    def __init__(self, routes):
        self.routes = routes
        self.hits = []

    def __enter__(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.hits.append(self.path)
                status, length, body = outer.routes.get(self.path, (404, None, b"not found"))
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body) if length is None else length))
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

            def log_message(self, *a):
                pass
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


# The engine in its own process: the tests' own process blocks every socket (tests/__init__.py).
ENGINE = ("import sys; sys.path.insert(0, sys.argv[1]); from probandia.util import http; "
          "http.BACKOFF = (0, 0, 0); http.DEFAULT_RATE = (100, 1.0); from probandia import cli; "
          "sys.exit(cli.main(sys.argv[2:]))")


def run_cli(tmp, *argv):
    """Runs a command in a copy of the fixture project, in a fresh interpreter."""
    project = os.path.join(tmp, "project")
    if not os.path.isdir(project):
        shutil.copytree(FIXTURE, project)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROBANDIA_")}
    env.update(PROBANDIA_CONFIG_DIR=os.path.join(tmp, "user"), PROBANDIA_SESSION="test",
               CLAUDE_CONFIG_DIR=os.path.join(tmp, "claude"), LANG="en_US.UTF-8", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-I", "-c", ENGINE, SRC, *argv], capture_output=True, text=True,
                          encoding="utf-8", cwd=project, env=env, stdin=subprocess.DEVNULL)


FAST = [mock.patch.object(phttp, "BACKOFF", (0, 0, 0)), mock.patch.object(phttp, "DEFAULT_RATE", (100, 1.0))]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, ".probandia")
        for p in FAST:
            p.start()
            self.addCleanup(p.stop)

    def client(self, **kw):
        return phttp.Client(self.state, "genealogist@example.org", sleep=lambda s: None, **kw)


class Truncated(Base):
    def test_incomplete_read_becomes_a_network_error(self):
        def transport(*a):
            raise http.client.IncompleteRead(b"0123456789", 990)
        with self.assertRaises(NetworkError) as caught:
            self.client(transport=transport).get("https://a.example/x", api=True)
        self.assertEqual(caught.exception.reason, "network")

    def test_invalid_url_becomes_a_network_error(self):
        with self.assertRaises(NetworkError):
            self.client().get("http://127.0.0.1:port/x", api=True)

    def test_read_of_a_truncated_page_says_network_code_7(self):
        with Server({"/acte": (200, 1000, b"0123456789")}) as srv:
            r = run_cli(self.tmp.name, "read", f"{srv.base}/acte", "--yes")
        self.assertIn("REASON=network", r.stdout.splitlines(), r.stdout + r.stderr)
        self.assertEqual(r.returncode, 7, r.stdout)


class RobotsOutOfReach(Base):
    def routes(self, routes):
        """A recorded transport: {path: (status, body)}; every path asked is in ``self.hits``."""
        self.hits = []

        def transport(method, url, headers, body, timeout):
            path = url.split("a.example", 1)[1]
            self.hits.append(path)
            status, out = routes.get(path, (404, b""))
            if status == 0:
                raise ConnectionRefusedError("refused")
            return status, {}, out, url
        return transport

    def test_503_refuses_for_an_hour_then_asks_again(self):
        now = [1000.0]
        routes = {"/robots.txt": (503, b"busy"), "/acte": (200, b"page")}
        c = self.client(transport=self.routes(routes), clock=lambda: now[0])
        self.assertFalse(c.allowed_by_robots("https://a.example/acte"))
        with self.assertRaises(phttp.RobotsUnreachable) as caught:
            c.get("https://a.example/acte")
        self.assertEqual(caught.exception.reason, "robots-unreachable")
        self.assertEqual(self.hits, ["/robots.txt"])   # kept: not asked again within the hour
        now[0] += 3601
        routes["/robots.txt"] = (200, b"User-agent: *\nAllow: /\n")
        self.assertEqual(c.get("https://a.example/acte").body, b"page")
        self.assertEqual(self.hits, ["/robots.txt", "/robots.txt", "/acte"])

    def test_429_and_network_errors_refuse_too(self):
        for status in (429, 500, 0):
            with self.subTest(status=status):
                c = phttp.Client(os.path.join(self.state, str(status)), sleep=lambda s: None,
                                 transport=self.routes({"/robots.txt": (status, b"")}))
                self.assertFalse(c.allowed_by_robots("https://a.example/x"))

    def test_404_still_allows(self):
        self.assertTrue(self.client(transport=self.routes({})).allowed_by_robots("https://a.example/acte"))

class StateNames(Base):
    def test_a_port_gives_a_plain_file_name(self):
        self.assertEqual(phttp.state_name("127.0.0.1:8080"), "127.0.0.1_8080")
        self.assertEqual(phttp.state_name("[::1]:80"), "___1__80")
        self.assertEqual(phttp.state_name("gallica.bnf.fr"), "gallica.bnf.fr")

    def test_read_on_an_explicit_port_writes_host_port_json(self):
        with Server({"/acte": (200, None, b"<html><body><p>Victor Hugo, 1802</p></body></html>")}) as srv:
            r = run_cli(self.tmp.name, "read", f"{srv.base}/acte", "--yes")
        rate = os.path.join(self.tmp.name, "project", ".probandia", "rate")
        names = os.listdir(rate)
        self.assertIn(f"127.0.0.1_{srv.port}.json", names, r.stdout + r.stderr)
        self.assertIn(f"127.0.0.1_{srv.port}.robots.json", names)
        self.assertFalse([n for n in names if ":" in n or n == "127.0.0.1"], names)   # no alternate stream


if __name__ == "__main__":
    unittest.main()
