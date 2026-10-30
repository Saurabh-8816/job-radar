"""Small text and date helpers shared by parsers and the classifier."""

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, unquote, urljoin

IST = timezone(timedelta(hours=5, minutes=30))

_ZERO_WIDTH = re.compile(r"[​-‍⁠﻿­]")
_SPACES = re.compile(r"\s+")
_DATE = re.compile(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})\b")
_SIZE_SUFFIX = re.compile(r"\s*\(\s*[\d.,]+\s*(?:KB|MB|GB|bytes)\s*\)\s*$", re.I)


def clean(text: str | None) -> str:
    """NFC-normalise, drop zero-width characters, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH.sub("", text)
    return _SPACES.sub(" ", text).strip()


def strip_size(label: str) -> str:
    """'View (323 KB)' -> 'View'."""
    return _SIZE_SUFFIX.sub("", label).strip()


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    "जनवरी": 1, "फरवरी": 2, "फ़रवरी": 2, "मार्च": 3, "अप्रैल": 4, "अप्रेल": 4, "मई": 5, "जून": 6,
    "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "अक्तूबर": 10,
    "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}
_MONTH = "(" + "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True)) + r")\.?"
_ORD = r"(?:st|nd|rd|th)?"
# "15th November, 2026", "15 Nov 2026", "15-Nov-2026", "15 नवंबर 2026"
_DMY_WORD = re.compile(rf"(?<!\d)(\d{{1,2}}){_ORD}\s*(?:of\s+)?[-/.,\s]*{_MONTH}(?![a-z])[-/.,\s]*(\d{{4}})(?!\d)", re.I)
# "November 15, 2026", "Nov. 15th 2026"
_MDY_WORD = re.compile(rf"(?<![a-z]){_MONTH}(?![a-z])\s*(\d{{1,2}}){_ORD},?\s+(\d{{4}})(?!\d)", re.I)
_HINDI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def parse_date(text: str | None) -> str | None:
    """First date in text (15/11/2026, 15th November 2026, Nov 15, 2026...), as ISO."""
    return next((iso for iso, _s, _e in all_dates(text)), None)


def all_dates(text: str):
    """Yield (iso_date, start, end) for every valid date in text, in order: numeric
    (15.11.2026) or with the month written out, in English or Hindi."""
    text = (text or "").translate(_HINDI_DIGITS)     # same length, so positions still match
    found = []
    for m in _DATE.finditer(text):
        found.append((m.start(), m.end(), _iso(*m.groups())))
    for m in _DMY_WORD.finditer(text):
        d, mon, y = m.groups()
        found.append((m.start(), m.end(), _iso(d, _MONTHS[mon.lower()], y)))
    for m in _MDY_WORD.finditer(text):
        mon, d, y = m.groups()
        found.append((m.start(), m.end(), _iso(d, _MONTHS[mon.lower()], y)))
    last_end = -1
    for start, end, iso in sorted(found):
        if iso and start >= last_end:
            last_end = end
            yield iso, start, end


def _iso(d, m, y) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def today_ist() -> date:
    return datetime.now(IST).date()


def join_url(base: str, href: str) -> str:
    """urljoin that returns "" for a broken link (e.g. "http://[broken") instead of raising:
    one malformed href on a page must not lose the whole page."""
    try:
        return urljoin(base, href)
    except ValueError:
        return ""


def now_ist() -> datetime:
    return datetime.now(IST)


def now_ist_iso() -> str:
    return now_ist().isoformat(timespec="seconds")


def days_left(deadline: str | None, today: date | None = None) -> int | None:
    if not deadline:
        return None
    today = today or today_ist()
    return (date.fromisoformat(deadline) - today).days


def normalize_url(url: str) -> str:
    """Stable key for a URL: lower-case host, no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    path = unquote(parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))
