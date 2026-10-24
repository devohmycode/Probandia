"""tools/release_snapshot.py (version-1.0.0 T212): the commit pushed has no parent, so no message of the history
goes with it."""
import importlib.util
import os
import subprocess
import tempfile
import unittest

from tests import ROOT

spec = importlib.util.spec_from_file_location("release_snapshot", os.path.join(ROOT, "tools", "release_snapshot.py"))
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)


class Snapshot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(tmp.name, "repo")
        os.makedirs(self.repo)
        snap.git("init", "-q", cwd=self.repo)
        for n, message in ((1, "a message naming a private place"), (2, "a second commit")):
            with open(os.path.join(self.repo, "f.txt"), "w", encoding="utf-8") as fh:
                fh.write(str(n))
            snap.git("add", "f.txt", cwd=self.repo)
            snap.git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", message,
                     cwd=self.repo)

    def push(self, sha):
        bare = os.path.join(self.tmp, f"{sha[:7]}.git")
        snap.git("init", "--bare", "-q", bare)
        snap.git("push", "-q", bare, f"{sha}:refs/heads/master", cwd=self.repo)
        return bare

    def test_the_orphan_goes_alone(self):
        tree = snap.git("rev-parse", "HEAD^{tree}", cwd=self.repo).decode().strip()
        sha = snap.orphan(tree, "Version 1.0.0", "t", "t@example.org", cwd=self.repo)
        bare = self.push(sha)
        self.assertIsNone(snap.alone(bare, sha))
        log = subprocess.run(["git", "log", "--all", "--format=%B"], cwd=bare, capture_output=True, text=True).stdout
        self.assertEqual(log.strip(), "Version 1.0.0")

    def test_the_history_is_refused(self):
        head = snap.git("rev-parse", "HEAD", cwd=self.repo).decode().strip()
        self.assertEqual(snap.alone(self.push(head), head), "the commit has 1 parent(s)")

    def test_ignored_files(self):
        self.assertEqual(snap.ignored(["README.md", "docs/x.md", "private/y", "a/.env", ".env.example"]),
                         ["docs/x.md", "private/y", "a/.env"])

    def test_attribution(self):
        self.assertTrue(snap.ATTRIBUTION.search("Version 1.0.0\n\nCo-Authored-By: someone"))
        self.assertFalse(snap.ATTRIBUTION.search("t\nt@example.org\nVersion 1.0.0"))


if __name__ == "__main__":
    unittest.main()
