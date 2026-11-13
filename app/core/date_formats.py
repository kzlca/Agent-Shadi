"""User-facing collection date parsing.

The collectors use a single canonical Jalali date internally because the
Telegram/Rubika history parsers already normalize their UI date labels to that
calendar. Users may enter the requested range in Jalali, Gregorian ISO, an
unambiguous auto-detected format, or an explicit Python strptime format.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from app.core.jalali import (
    format_jalali,
    gregorian_to_jalali,
    jalali_to_gregorian,
    validate_jalali,
)

_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)


def _normalise(value: str) -> str:
    return str(value or "").translate(_DIGIT_MAP).strip()


def _parse_gregorian_iso(value: str) -> date:
    raw = _normalise(value)
    candidates = (raw, raw.replace("/", "-"), raw.replace(".", "-"))
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    raise ValueError("Use Gregorian ISO format YYYY-MM-DD, for example 2026-11-09")


def parse_collection_date(value: str, date_system: str = "jalali", custom_format: str = "") -> date:
    """Parse a user-entered date into a Gregorian ``date`` for ordering."""
    raw = _normalise(value)
    system = (date_system or "jalali").strip().lower()
    if not raw:
        raise ValueError("Enter both a start date and an end date")

    if system == "jalali":
        jy, jm, jd = validate_jalali(raw)
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        return date(gy, gm, gd)

    if system == "gregorian":
        return _parse_gregorian_iso(raw)

    if system == "custom":
        fmt = str(custom_format or "").strip()
        if not fmt or not all(token in fmt for token in ("%Y", "%m", "%d")):
            raise ValueError("Custom format must include %Y, %m and %d (example: %d/%m/%Y)")
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError as exc:
            raise ValueError(f"Date does not match custom format {fmt!r}") from exc

    if system == "auto":
        # A four-digit modern Persian year is unambiguously Jalali.
        if re.match(r"^(12|13|14)\d{2}[./-]", raw):
            jy, jm, jd = validate_jalali(raw)
            gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
            return date(gy, gm, gd)
        try:
            return _parse_gregorian_iso(raw)
        except ValueError:
            pass
        # Accept month-name Gregorian dates without locale-dependent parsing.
        for fmt in ("%d %b %Y", "%b %d %Y", "%d %B %Y", "%B %d %Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        # Slash/dot numeric formats can be ambiguous (01/02/2026); force the
        # user to choose a custom format instead of silently swapping month/day.
        raise ValueError("Could not safely detect this date. Choose Gregorian or Custom format.")

    raise ValueError("Date system must be Jalali, Gregorian, Auto-detect or Custom")


def canonical_jalali(value: str, date_system: str = "jalali", custom_format: str = "") -> str:
    """Return a validated canonical Jalali date for the current collectors."""
    gregorian = parse_collection_date(value, date_system, custom_format)
    jy, jm, jd = gregorian_to_jalali(gregorian.year, gregorian.month, gregorian.day)
    return format_jalali(jy, jm, jd)
