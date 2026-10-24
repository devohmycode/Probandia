import datetime
import unittest

from probandia import i18n
from probandia.i18n import formats

NOW = datetime.datetime(2026, 10, 2, 16, 30, tzinfo=datetime.timezone.utc)
NB = formats.NARROW_NBSP


class Formats(unittest.TestCase):
    """English by default, French with --lang fr (decision D-6)."""

    def tearDown(self):
        i18n.activate("en")

    def test_english(self):
        i18n.activate("en")
        self.assertEqual(formats.number(2110), "2,110")
        self.assertEqual(formats.number(8814000), "8,814,000")
        self.assertEqual(formats.number(4.5), "4.50")
        self.assertEqual(formats.money(4.19), "$4.19")
        self.assertEqual(formats.relative(NOW + datetime.timedelta(days=30), NOW), "in 30 d")
        self.assertEqual(formats.relative(NOW - datetime.timedelta(hours=2), NOW), "2 h ago")
        self.assertEqual(formats.relative(NOW, NOW), "now")

    def test_french(self):
        i18n.activate("fr")
        self.assertEqual(formats.number(2110), f"2{NB}110")
        self.assertEqual(formats.number(4.5), "4,50")
        self.assertEqual(formats.money(4.19), f"4,19{NB}$")
        self.assertEqual(formats.relative(NOW + datetime.timedelta(days=30), NOW), f"dans 30{NB}j")
        self.assertEqual(formats.relative(NOW - datetime.timedelta(hours=2), NOW), f"il y a 2{NB}h")
        self.assertEqual(formats.relative(NOW - datetime.timedelta(minutes=5), NOW), f"il y a 5{NB}min")

    def test_other_languages_fall_back_to_english(self):
        i18n.activate("de")
        self.assertEqual(formats.number(2110), "2,110")


if __name__ == "__main__":
    unittest.main()
