"""Numbers, amounts and dates for the readable output, in the language of the
messages (decision D-6: English by default, French with ``--lang fr``).

English and French are built in; any other language falls back to English.
"""
import datetime

from probandia import i18n
from probandia.i18n import N_, _

NARROW_NBSP = " "   # the French thousands separator, which a line never breaks


def _french():
    return (i18n.current() or "en").split("-")[0] == "fr"


def number(value, decimals=None):
    """``2110`` -> ``2,110`` (English) or ``2 110`` (French); ``decimals`` fixes the
    digits after the point, otherwise whole numbers stay whole."""
    if decimals is None:
        decimals = 0 if float(value) == int(float(value)) else 2
    text = f"{float(value):,.{decimals}f}"
    if _french():
        text = text.replace(",", NARROW_NBSP).replace(".", ",")
    return text


def money(value, currency="$"):
    """``4.19`` -> ``$4.19`` (English) or ``4,19 $`` (French)."""
    text = number(value, 2)
    return f"{text}{NARROW_NBSP}{currency}" if _french() else f"{currency}{text}"


def relative(when, now=None):
    """A date seen from ``now``: ``in 30 d``, ``2 h ago``, ``now``, in the local
    language. ``when`` and ``now`` are aware datetimes (UTC in the files)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    seconds = (when - now).total_seconds()
    future = seconds > 0
    seconds = abs(seconds)
    if seconds < 60:
        return _("now")
    for size, unit in ((86400, _("d")), (3600, _("h")), (60, _("min"))):
        if seconds >= size:
            amount = f"{int(seconds // size)}{NARROW_NBSP if _french() else ' '}{unit}"
            break
    return (_("in {amount}") if future else _("{amount} ago")).format(amount=amount)


def local_time(when):
    """An aware datetime in the computer's time zone, as ``2026-10-02 16:30``."""
    return when.astimezone().strftime("%Y-%m-%d %H:%M")


MONTHS = (N_("January"), N_("February"), N_("March"), N_("April"), N_("May"), N_("June"), N_("July"),
          N_("August"), N_("September"), N_("October"), N_("November"), N_("December"))


def long_date(iso):
    """``1803-12-25`` -> ``25 December 1803``; ``1803`` and ``1803-12`` keep what they say."""
    parts = str(iso).split("-")
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return str(iso)
    if len(numbers) == 3:
        day = "1er" if _french() and numbers[2] == 1 else str(numbers[2])
        return f"{day} {_(MONTHS[numbers[1] - 1]).lower() if _french() else _(MONTHS[numbers[1] - 1])} {numbers[0]}"
    if len(numbers) == 2:
        month = _(MONTHS[numbers[1] - 1])
        return f"{month.lower() if _french() else month} {numbers[0]}"
    return str(iso)
