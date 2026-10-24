"""The gazetteers go through util.http.Client (T156): robots.txt, Retry-After, a rate shared between processes."""
import os
import subprocess
import sys
import tempfile
import unittest

from probandia.lang import places as pl
from tests import ROOT, SRC

WORKER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from probandia.lang.places import Http
state, out = sys.argv[2], sys.argv[3]
last = {"now": 0.0, "slot": 0.0}
def clock():
    last["now"] = last["slot"] = time.time()
    return last["now"]
def sleep(seconds):
    last["slot"] = last["now"] + seconds   # the slot the client was given: the time it read, plus its wait
    time.sleep(seconds)
def transport(method, url, headers, body, timeout):
    with open(out, "a") as fh:
        fh.write(f"{last['slot']}\n")
    return 200, {}, b"[]", url
http = Http("genealogist@example.org", state, transport=transport)
http.client.clock, http.client.sleep = clock, sleep
for _ in range(2):
    http.get("https://nominatim.openstreetmap.org/search", {"q": "Besançon", "format": "json"})
"""


class SharedRate(unittest.TestCase):
    def test_two_processes_keep_to_one_request_a_second_on_nominatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "times.txt")
            worker = os.path.join(tmp, "worker.py")
            with open(worker, "w", encoding="utf-8") as fh:
                fh.write(WORKER)
            procs = [subprocess.Popen([sys.executable, "-I", worker, SRC, os.path.join(tmp, "state"), out])
                     for _ in range(2)]
            for p in procs:
                self.assertEqual(p.wait(timeout=60), 0)
            with open(out, encoding="utf-8") as fh:
                times = sorted(float(t) for t in fh.read().split())
        self.assertEqual(len(times), 4)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertGreater(min(gaps), 0.99, gaps)   # the slots given: 1/s (HOST_RATES), whatever the load


class Calls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []

    def http(self, routes):
        def transport(method, url, headers, body, timeout):
            self.calls.append(url)
            for prefix, answer in routes.items():
                if url.startswith(prefix):
                    return answer[0], {}, answer[1], url
            return 404, {}, b"", url
        h = pl.Http("genealogist@example.org", self.tmp.name, transport=transport)
        h.client.sleep = lambda s: None
        return h

    def test_gov_pages_obey_robots_txt(self):
        h = self.http({"https://gov.genealogy.net/robots.txt": (200, b"User-agent: *\nDisallow: /search\n")})
        found, notes = pl.lookup("Nancy", None, [], None, h, {}, False)
        self.assertNotIn("https://gov.genealogy.net/search/name?name=Nancy", self.calls)
        self.assertTrue(any(n.startswith("gov: failed (RobotsDenied)") for n in notes), notes)

    def test_an_error_status_is_a_network_error(self):
        from probandia.errors import NetworkError

        h = self.http({"https://www.wikidata.org/": (500, b"")})
        with self.assertRaises(NetworkError):
            h.get("https://www.wikidata.org/w/api.php", {"action": "query"})

    def test_no_urlopen_in_lang(self):
        for name in os.listdir(os.path.join(ROOT, "src", "probandia", "lang")):
            if name.endswith(".py"):
                with open(os.path.join(ROOT, "src", "probandia", "lang", name), encoding="utf-8") as fh:
                    self.assertNotIn("urlopen", fh.read(), name)


if __name__ == "__main__":
    unittest.main()
