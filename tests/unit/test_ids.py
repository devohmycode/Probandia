import unittest

from probandia.util.ids import is_slug, is_ulid, slugify, ulid, ulid_time_ms


class Ulids(unittest.TestCase):
    def test_format(self):
        u = ulid()
        self.assertEqual(len(u), 26)
        self.assertTrue(is_ulid(u), u)

    def test_time_part(self):
        self.assertEqual(ulid_time_ms(ulid(now_ms=1_727_721_252_000)), 1_727_721_252_000)
        self.assertTrue(ulid(now_ms=0).startswith("0000000000"))

    def test_sorted_by_time(self):
        a, b = ulid(now_ms=1000), ulid(now_ms=2000)
        self.assertLess(a, b)

    def test_monotonic_within_one_millisecond(self):
        ids = [ulid(now_ms=5000) for _ in range(1000)]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 1000)

    def test_is_ulid(self):
        for bad in ("", "01J9", "01J9ZZZZZZZZZZZZZZZZZZZZZI", "81J9ZZZZZZZZZZZZZZZZZZZZZZ", None, 3):
            self.assertFalse(is_ulid(bad), bad)


class Slugs(unittest.TestCase):
    def test_slugify(self):
        cases = {
            "HUGO": "hugo",
            "Léopold Hugo": "leopold-hugo",
            "  Who were the parents?  ": "who-were-the-parents",
            "Böhm / Hugot": "bohm-hugot",
            "Œuvre straße": "oeuvre-strasse",
            "a--b__c": "a-b-c",
        }
        for text, slug in cases.items():
            self.assertEqual(slugify(text), slug)
            self.assertTrue(is_slug(slug))

    def test_max_length(self):
        s = slugify("word " * 40)
        self.assertLessEqual(len(s), 64)
        self.assertTrue(is_slug(s))
        self.assertFalse(s.endswith("-"))
        self.assertEqual(len(slugify("x" * 100)), 64)

    def test_nothing_left(self):
        with self.assertRaises(ValueError):
            slugify("?!…")

    def test_is_slug(self):
        for bad in ("", "A", "a_b", "-a", "a-", "a--b", "é", "a" * 65):
            self.assertFalse(is_slug(bad), bad)
        self.assertTrue(is_slug("2026-09-30-parents-of-victor-hugo"))
