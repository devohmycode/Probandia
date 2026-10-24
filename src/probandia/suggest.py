"""``did you mean …?``: the closest name to a typo, by difflib (standard library;
cli.md § 6.5). Commands, providers, settings and families use it."""
from difflib import get_close_matches

from probandia.i18n import _


def closest(word, candidates):
    """The closest candidate to ``word``, or None."""
    found = get_close_matches(str(word), [str(c) for c in candidates], n=1, cutoff=0.6)
    return found[0] if found else None


def lines(word, candidates):
    """``["did you mean serpapi?"]``, or [] when nothing is close."""
    name = closest(word, candidates)
    return [_("did you mean {name}?").format(name=name)] if name else []
