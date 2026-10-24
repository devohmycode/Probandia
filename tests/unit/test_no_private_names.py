"""No name from the author's own family research is in the files git tracks.

The names are not written here: only the SHA-256 of each forbidden word, or
run of two or three words, once folded (lower case, no accents). Paths count
as text too. On the author's machine, `private/forbidden-names.txt` (ignored
by git, one name per line) adds plain names to the hashed ones.
`tools/check_wheel.py` reads the built wheel and sdist with `scan` (version-1.0.0 T253).
"""
import hashlib
import re
import subprocess
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_LIST = ROOT / "private" / "forbidden-names.txt"
FORBIDDEN = {
    "bb7aa507ee307613a18d2b1eabb42e76a5e3ff8a00d021b738f6a5a8f299ed29",
    "aa68a13d298f5e4da8d237b00a71de125fde61f9001e1ece497997780f6c9d77",
    "20e25778c9e21753a34976b7d5eade328731fa391910f88cd166aa626b13b078",
    "87575c503dd9ca865033be8503a025ecd5b93b2fbb97aed7e56cccf40bbb8cae",
    "a336d2622af27319979c12379de3c9b18c0e2eefbf0b74969f3074d84e932026",
    "0a3ef58fee4d64335079650c61d2dd19c326d18a81ee7b52fec628d76eed1ae0",
    "132ef5ac829bc1bd8857e291c60b6246b260bb34e43845d2146a9634258361e0",
    "143d0dfb05e7d0682421c6fa1e6bfd3dad952d4fc84957ce71f1981b8af8348c",
    "c833265420337bb794abf80facd3fd49267b92c1d09bee17e6d23dd958582df2",
    "671b75d1592f3b736066a0f53573966fc19f9f172556dcd577a9a9c71f46334e",
    "6cfa54aea0d1175008bc7fa08f5a524a6069dc04e339e354bb4e6cfcee30ef1a",
    "4311b5ef8edbf967cfcdf93530ef138da77e12165734202c319b0ff3d6b1a3ee",
}
WORD = re.compile(r"[a-z0-9]+")
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".gdz", ".zip", ".woff", ".woff2", ".ttf"}


def fold(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def terms(text):
    words = WORD.findall(fold(text))
    runs = set(words)
    runs.update(" ".join(words[i:i + 2]) for i in range(len(words) - 1))
    runs.update(" ".join(words[i:i + 3]) for i in range(len(words) - 2))
    return runs


def local_names(path=LOCAL_LIST):
    """The plain names of the local list, folded; none where it is absent (the CI)."""
    local = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name = " ".join(WORD.findall(fold(line)))
            if name:
                local.add(name)
    return local


def scan(items, local=frozenset()):
    """The lines ``<name>: <hits>`` of the (name, text) items that hold a forbidden name:
    ``<hashed>`` for a hashed one, the name itself for one of the local list."""
    seen = {}
    found = []
    for name, text in items:
        hits = set()
        for term in terms(text):
            if term not in seen:
                seen[term] = hashlib.sha256(term.encode("utf-8")).hexdigest() in FORBIDDEN
            if seen[term]:
                hits.add("<hashed>")
            if term in local:
                hits.add(term)
        if hits:
            found.append(f"{name}: {', '.join(sorted(hits))}")
    return found


def tracked():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    # private/ is never tracked; tools/ci_local.py's copies commit it with the rest (the local list goes there)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p and not p.startswith("private/")]


class NoPrivateName(unittest.TestCase):
    def test_no_tracked_file_names_a_private_family(self):
        files = tracked()
        if files is None:
            self.skipTest("git is not available")
        def items():
            for rel in files:
                path = ROOT / rel
                text = rel
                if path.suffix.lower() not in BINARY and path.is_file():
                    text += "\n" + path.read_bytes().decode("utf-8", errors="ignore")
                yield rel, text
        self.assertEqual(scan(items(), local_names()), [], "names from the author's family research")

    def test_the_check_sees_a_forbidden_word(self):
        word = "ab" + "c"
        self.assertIn(word, terms(f"x {word.upper()} y"))
        self.assertIn("le grand", terms("Le Grand"))
        self.assertEqual(fold("Élise"), "elise")

    def test_the_scan_names_the_file_and_the_local_name(self):
        # T253: what tools/check_wheel.py reads in the built packages
        word = "ab" + "c"
        items = [("probandia/a.py", f"x {word.upper()} y"), ("probandia/b.py", "nothing")]
        self.assertEqual(scan(items, {word}), [f"probandia/a.py: {word}"])
        self.assertEqual(scan(items), [])


if __name__ == "__main__":
    unittest.main()
