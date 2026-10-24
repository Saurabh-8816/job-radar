"""Small text and date helpers shared by parsers and the classifier."""

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, unquote

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


def parse_date(text: str | None) -> str | None:
    """First dd/mm/yyyy-style date in text, as ISO 'YYYY-MM-DD'."""
    if not text:
        return None
    m = _DATE.search(text)
    return _iso(*m.groups()) if m else None


def all_dates(text: str):
    """Yield (iso_date, start, end) for every valid numeric date in text."""
    for m in _DATE.finditer(text or ""):
        iso = _iso(*m.groups())
        if iso:
            yield iso, m.start(), m.end()


def _iso(d: str, m: str, y: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def today_ist() -> date:
    return datetime.now(IST).date()


def now_ist_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


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
