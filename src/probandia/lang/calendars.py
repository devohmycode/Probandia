"""Calendar arithmetic: Gregorian, Julian, French Republican, Easter.

Every conversion goes through the Julian Day Number (JDN).
"""
import datetime


def jdn_from_gregorian(y, m, d):
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    return d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045


def jdn_from_julian(y, m, d):
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    return d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - 32083


def gregorian_from_jdn(j):
    a = j + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return year, month, day


def julian_to_gregorian(y, m, d):
    return gregorian_from_jdn(jdn_from_julian(y, m, d))


def valid_gregorian(y, m, d):
    try:
        datetime.date(y, m, d)
        return True
    except ValueError:
        return False


def valid_julian(y, m, d):
    if not 1 <= m <= 12 or d < 1:
        return False
    days = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return d <= days[m - 1]


def iso(y, m=None, d=None):
    if m is None:
        return f"{y:04d}"
    if d is None:
        return f"{y:04d}-{m:02d}"
    return f"{y:04d}-{m:02d}-{d:02d}"


# French Republican calendar

# 1 vendémiaire of years I to XIV, as observed (years III, VII and XI were leap
# years, "sextiles", with a sixth complementary day). The calendar ended on
# 10 nivôse XIV = 31 December 1805.
REPUBLICAN_YEAR_START = {
    1: (1792, 9, 22), 2: (1793, 9, 22), 3: (1794, 9, 22), 4: (1795, 9, 23),
    5: (1796, 9, 22), 6: (1797, 9, 22), 7: (1798, 9, 22), 8: (1799, 9, 23),
    9: (1800, 9, 23), 10: (1801, 9, 23), 11: (1802, 9, 23), 12: (1803, 9, 24),
    13: (1804, 9, 23), 14: (1805, 9, 23),
}
REPUBLICAN_LEAP = {3, 7, 11}
REPUBLICAN_LAST = (14, 4, 10)  # 10 nivôse XIV


def republican_to_gregorian(year, month, day):
    """``month`` 1-12, or 13 for the complementary days. Returns (y, m, d) or None
    when the date did not exist."""
    if year not in REPUBLICAN_YEAR_START:
        return None
    if month == 13:
        if not 1 <= day <= (6 if year in REPUBLICAN_LEAP else 5):
            return None
        offset = 360 + day - 1
    else:
        if not (1 <= month <= 12 and 1 <= day <= 30):
            return None
        offset = (month - 1) * 30 + day - 1
    if (year, month, day) > REPUBLICAN_LAST:
        return None
    start = jdn_from_gregorian(*REPUBLICAN_YEAR_START[year])
    return gregorian_from_jdn(start + offset)


def republican_year_span(year):
    """First and last Gregorian day of a Republican year."""
    if year not in REPUBLICAN_YEAR_START:
        return None
    first = REPUBLICAN_YEAR_START[year]
    if year == 14:
        return first, (1805, 12, 31)
    last = gregorian_from_jdn(jdn_from_gregorian(*REPUBLICAN_YEAR_START[year + 1]) - 1) \
        if year + 1 in REPUBLICAN_YEAR_START else None
    return first, last


# Easter


def easter_gregorian(y):
    """Easter Sunday in the Gregorian calendar (anonymous algorithm)."""
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return y, month, day


def easter_julian(y):
    """Easter Sunday in the Julian calendar (Meeus), as a Julian date."""
    a = y % 4
    b = y % 7
    c = y % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    return y, month, day


def add_days(ymd, n, julian=False):
    j = (jdn_from_julian if julian else jdn_from_gregorian)(*ymd) + n
    if julian:
        # back to a Julian calendar date
        a = j + 32082
        b = (4 * a + 3) // 1461
        c = a - 1461 * b // 4
        m = (5 * c + 2) // 153
        day = c - (153 * m + 2) // 5 + 1
        month = m + 3 - 12 * (m // 10)
        year = b - 4800 + m // 10
        return year, month, day
    return gregorian_from_jdn(j)
