import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta

from probandia.errors import LockHeld, UsageError
from probandia.project import create_project
from probandia.util.fs import iso, utc_now
from probandia.util.locks import LockLost, Locks, parse_scope, session_id
from tests import ROOT

LAUNCHER = os.path.join(ROOT, "run_probandia.py")
A = {"harness": "codex", "session": "s-a", "agent": "orchestrator"}
B = {"harness": "claude-code", "session": "s-b", "agent": "session"}


class Clock:
    def __init__(self):
        self.now = utc_now()

    def __call__(self):
        return self.now


class Scopes(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_scope("research:r-1"), ("research", "r-1"))
        self.assertEqual(parse_scope("family-hugo"), ("family", "hugo"))
        for bad in ("person:x", "research:", "research:A B", "hugo"):
            with self.assertRaises(UsageError, msg=bad):
                parse_scope(bad)



class Sessions(unittest.TestCase):
    def test_harness_session_variables(self):
        # Cursor runs each command in a new shell: its conversation id is the session
        self.assertEqual(session_id({"CURSOR_CONVERSATION_ID": "9647a033"}), "9647a033")
        self.assertEqual(session_id({"PROBANDIA_SESSION": "s", "CURSOR_CONVERSATION_ID": "c"}), "s")
        self.assertTrue(session_id({}).startswith("ppid-"))
        # Grok Build also runs each command in a new shell: the lock new took was refused to the next plan
        for var in ("GROK_SESSION_ID", "ANTIGRAVITY_SESSION_ID"):
            self.assertEqual(session_id({var: "01a11fb4"}), "01a11fb4", var)

    def test_every_detected_harness_names_its_session(self):
        # a harness the engine detects by a session variable keeps that session across its shells
        from probandia.harness import DETECTION

        for harness, variables in DETECTION:
            for var in [v for v in variables if v.endswith("_SESSION_ID")]:
                self.assertEqual(session_id({var: "x"}), "x", (harness, var))

class InProcess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.locks = Locks(self.tmp.name, expiry_minutes=30, clock=self.clock)

    def test_take_writes_owner_and_expiry(self):
        info = self.locks.take("research:r", A)
        self.assertEqual(info["owner"], A)
        self.assertEqual(info["expires"], iso(self.clock.now + timedelta(minutes=30)))
        path = os.path.join(self.tmp.name, ".probandia", "locks", "research-r.json")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), info)

    def test_second_owner_is_refused(self):
        self.locks.take("family:hugo", A)
        with self.assertRaises(LockHeld) as cm:
            self.locks.take("family:hugo", B)
        self.assertEqual(cm.exception.exit_code, 5)
        self.assertEqual(cm.exception.values["HOLDER"], "codex/s-a/orchestrator")

    def test_same_owner_renews(self):
        first = self.locks.take("research:r", A)
        self.clock.now += timedelta(minutes=10)
        second = self.locks.take("research:r", A)
        self.assertEqual(second["since"], first["since"])
        self.assertGreater(second["expires"], first["expires"])

    def test_expired_lock_is_taken_over(self):
        self.locks.take("research:r", A)
        self.clock.now += timedelta(minutes=31)
        info = self.locks.take("research:r", B)
        self.assertEqual(info["owner"], B)

    def test_expired_holder_loses_it(self):
        self.locks.take("research:r", A)
        self.clock.now += timedelta(minutes=31)
        with self.assertRaises(LockLost):
            self.locks.renew("research:r", A)

    def test_renew_by_another_owner_fails(self):
        self.locks.take("research:r", A)
        with self.assertRaises(LockLost):
            self.locks.renew("research:r", B)

    def test_release(self):
        self.locks.take("research:r", A)
        with self.assertRaises(LockHeld):
            self.locks.release("research:r", B)
        self.assertTrue(self.locks.release("research:r", A))
        self.assertFalse(self.locks.release("research:r", A))
        self.assertEqual(self.locks.status("research:r"), (None, None))

    def test_corrupt_file_counts_as_expired(self):
        path = self.locks.path("research:r")
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write("{trunc")
        self.assertEqual(self.locks.take("research:r", A)["owner"], A)


def _spawn(project, scope, session):
    env = dict(os.environ, PROBANDIA_SESSION=session)
    return subprocess.Popen([sys.executable, "-I", LAUNCHER, "lock", "take", scope],
                            cwd=project, env=env, stdout=subprocess.PIPE, text=True)


class TwoProcesses(unittest.TestCase):
    """Processes competing for one lock: one wins, the others get exit code 5."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        create_project(self.tmp.name)

    def _race(self, n=4):
        procs = [_spawn(self.tmp.name, "family:hugo", f"s{i}") for i in range(n)]
        codes = []
        for p in procs:
            p.communicate(timeout=60)
            codes.append(p.returncode)
        return sorted(codes)

    def test_fresh_lock(self):
        self.assertEqual(self._race(), [0, 5, 5, 5])

    def test_expired_lock_taken_over_once(self):
        path = os.path.join(self.tmp.name, ".probandia", "locks", "family-hugo.json")
        past = utc_now() - timedelta(hours=2)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"owner": A, "since": iso(past), "expires": iso(past + timedelta(minutes=30))}, fh)
        self.assertEqual(self._race(), [0, 5, 5, 5])
        with open(path, encoding="utf-8") as fh:
            self.assertNotEqual(json.load(fh)["owner"], A)
