"""Accurate Jalali calendar utilities using the Borkowski/Jalaali algorithm.

The implementation is adapted from the date-conversion algorithm used in the
source duplicate reviewer. Dates are converted to Gregorian ordinals for exact
ordering rather than relying on a simplified 33-year leap-cycle approximation.
"""
from __future__ import annotations

import re
from datetime import date

_DIGITS = str.maketrans({**{ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}, **{ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}})
_JALALI_BREAKS = [
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181,
    1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394,
    2456, 3178,
]


def _int_div(a: int, b: int) -> int:
    """Integer division truncated toward zero (as used by the reference algorithm)."""
    return int(a / b)


def _int_mod(a: int, b: int) -> int:
    return a - _int_div(a, b) * b


def _jalali_calendar(jy: int) -> dict[str, int]:
    leap_j = -14
    jp = _JALALI_BREAKS[0]
    jump = 0
    for jm in _JALALI_BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _int_div(jump, 33) * 8 + _int_div(_int_mod(jump, 33), 4)
        jp = jm

    n = jy - jp
    leap_j += _int_div(n, 33) * 8 + _int_div(_int_mod(n, 33) + 3, 4)
    if _int_mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1

    gy = jy + 621
    leap_g = (
        _int_div(gy, 4)
        - _int_div((_int_div(gy, 100) + 1) * 3, 4)
        - 150
    )
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _int_div(jump + 4, 33) * 33
    leap = _int_mod(_int_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return {"leap": leap, "gy": gy, "march": march}


def _gregorian_to_jdn(gy: int, gm: int, gd: int) -> int:
    return (
        _int_div((gy + _int_div(gm - 8, 6) + 100100) * 1461, 4)
        + _int_div(153 * _int_mod(gm + 9, 12) + 2, 5)
        + gd - 34840408
        - _int_div(
            _int_div(gy + 100100 + _int_div(gm - 8, 6), 100) * 3,
            4,
        )
        + 752
    )


def _jdn_to_gregorian(jdn: int) -> tuple[int, int, int]:
    j = 4 * jdn + 139361631
    j += _int_div(_int_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _int_div(_int_mod(j, 1461), 4) * 5 + 308
    gd = _int_div(_int_mod(i, 153), 5) + 1
    gm = _int_mod(_int_div(i, 153), 12) + 1
    gy = _int_div(j, 1461) - 100100 + _int_div(8 - gm, 6)
    return gy, gm, gd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    if not (-61 <= jy < 3178):
        raise ValueError(f"Jalali year out of supported range: {jy}")
    if not 1 <= jm <= 12:
        raise ValueError(f"Invalid Jalali month: {jm}")
    cal = _jalali_calendar(jy)
    if jm <= 6:
        max_day = 31
    elif jm <= 11:
        max_day = 30
    else:
        max_day = 30 if cal["leap"] == 0 else 29
    if not 1 <= jd <= max_day:
        raise ValueError(f"Invalid Jalali day: {jy}/{jm:02d}/{jd:02d}")

    start = _gregorian_to_jdn(cal["gy"], 3, cal["march"])
    offset = (jm - 1) * 31 + (jd - 1) if jm <= 7 else (jm - 1) * 30 + jd + 5
    return _jdn_to_gregorian(start + offset)


def is_jalali_leap(year: int) -> bool:
    """Return leap status according to the Borkowski/Jalaali algorithm."""
    if not (-61 <= int(year) < 3178):
        raise ValueError(f"Jalali year out of supported range: {year}")
    return _jalali_calendar(int(year))["leap"] == 0


def validate_jalali(value: str) -> tuple[int, int, int]:
    normalized = str(value or "").translate(_DIGITS).strip()
    normalized = normalized.replace("/", ".").replace("-", ".")
    match = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", normalized)
    if not match:
        raise ValueError("Use Jalali dates in YYYY.MM.DD format, for example 1405.08.17")
    year, month, day = map(int, match.groups())
    # UI and source datasets are modern Jalali dates; limiting to 1200–1499
    # avoids accidentally accepting a Gregorian year as a Jalali year.
    if not 1200 <= year <= 1499:
        raise ValueError("Jalali year must be between 1200 and 1499")
    jalali_to_gregorian(year, month, day)  # strict month/day/leap-year validation
    return year, month, day


def jalali_ordinal(year: int, month: int, day: int) -> int:
    gy, gm, gd = jalali_to_gregorian(year, month, day)
    return date(gy, gm, gd).toordinal()


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian calendar date to Jalali using the same breakpoints."""
    # Binary-search the Jalali year by Gregorian start date, then calculate the
    # offset from Farvardin 1. This keeps both conversion directions consistent.
    target = date(gy, gm, gd).toordinal()
    low, high = gy - 622, gy - 620
    while low <= high:
        mid = (low + high) // 2
        start_g = jalali_to_gregorian(mid, 1, 1)
        start = date(*start_g).toordinal()
        if start <= target:
            low = mid + 1
        else:
            high = mid - 1
    jy = high
    start = date(*jalali_to_gregorian(jy, 1, 1)).toordinal()
    offset = target - start
    if offset < 186:
        jm, jd = offset // 31 + 1, offset % 31 + 1
    else:
        offset -= 186
        jm, jd = 7 + offset // 30, offset % 30 + 1
    return jy, jm, jd


def format_jalali(year: int, month: int, day: int) -> str:
    return f"{year:04d}.{month:02d}.{day:02d}"
