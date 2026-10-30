"""Generic watcher for career/recruitment pages with no common layout.

Every link on the page becomes an item keyed by its URL. The pipeline keeps only
job-related links (profile `job_words`) and alerts on links it hasn't seen before,
so the page's structure doesn't matter. A per-source CSS `selector` can limit the
scan to the content area when menus add noise.
"""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, ParseResult
from ..textutil import clean, join_url, normalize_url, parse_date

# Query parameters that change on every page load (NTPC signs each link with a fresh token).
_VOLATILE_PARAMS = {"token", "sid", "session", "sessionid", "phpsessid", "jsessionid",
                    "ts", "t", "timestamp", "_", "rand", "nocache", "cache", "v", "ver", "k", "key"}
_RANDOMISH = re.compile(r"[A-Za-z0-9+/=_%.-]{20,}")
# Aggregators print the deadline in the row: "Online Form 2026 | Last Date : 13/11/2026".
_LAST_DATE = re.compile(r"(?:last|closing)\s*date\s*[:\-–]?\s*(\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{4})", re.I)

_SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "#", "whatsapp:")
_DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png")
_GENERIC = {
    "click here", "here", "view", "download", "details", "more", "read more",
    "pdf", "link", "apply", "apply online", "apply here", "new", "notification",
    "advertisement", "advt", "view details", "देखें", "डाउनलोड", "यहाँ क्लिक करें",
}


def is_document(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(_DOC_EXT)


def _looks_random(value: str) -> bool:
    return bool(_RANDOMISH.fullmatch(value) and re.search(r"\d", value) and re.search(r"[A-Za-z]", value))


def stable_key(url: str, text: str, context: str) -> str | None:
    """If the URL carries per-load tokens, identify the link by its stable parts
    (path + remaining params) plus its visible text and row. None = URL is stable."""
    parts = urlsplit(url)
    params = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(k, v) for k, v in params if k.lower() not in _VOLATILE_PARAMS and not _looks_random(v)]
    if len(kept) == len(params):
        return None
    base = normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), "")))
    digest = hashlib.sha1(f"{text}|{context}".encode("utf-8")).hexdigest()[:16]
    return f"w:{base}|{digest}"


def _context_element(a):
    """The table row or list item holding the link, which usually carries the job title.
    Old sites lay whole pages out in tables, so an oversized row is skipped in favour
    of the nearest paragraph or cell."""
    for tag in ("tr", "li"):
        parent = a.find_parent(tag)
        if parent is not None and len(parent.get_text(" ", strip=True)) <= 600:
            return parent
    return a.find_parent(["p", "dd", "td"])


_DEADLINE_HEADER = re.compile(r"last\s*date|closing\s*date|अंतिम\s*(तिथि|दिनांक)", re.I)


def _table_deadline(a) -> str | None:
    """Deadline from a 'Last Date' / 'Closing Date' column of the link's table row."""
    tr = a.find_parent("tr")
    table = tr.find_parent("table") if tr else None
    if table is None:
        return None
    header = table.find("tr")
    if header is None or header is tr:
        return None
    names = [clean(c.get_text(" ")) for c in header.find_all(["th", "td"])]
    col = next((i for i, n in enumerate(names) if _DEADLINE_HEADER.search(n)), None)
    cells = tr.find_all(["td", "th"])
    if col is None or col >= len(cells):
        return None
    return parse_date(cells[col].get_text(" "))


def _scopes(soup, selector):
    """Every element the selector matches (pages often split jobs across several
    tables), else the whole body."""
    if selector:
        found = soup.select(selector)
        if found:
            return found
    return [soup.body or soup]


def parse(html: str, page_url: str, source) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    items, seen = [], set()
    for a in (a for scope in _scopes(soup, source.selector) for a in scope.find_all("a", href=True)):
        href = a["href"].strip()
        if not href or href.lower().startswith(_SKIP_SCHEMES):
            continue
        url = join_url(page_url, href)
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)

        text = clean(a.get_text(" ")) or clean(a.get("title")) or clean(a.get("aria-label"))
        row = _context_element(a)
        context = clean(row.get_text(" "))[:400] if row else text
        title = text if (len(text) >= 12 and text.lower() not in _GENERIC) else (context or text)
        if not title:
            continue
        items.append(Item(
            source_id=source.id,
            title=title[:300],
            description=context if context != title else "",
            url=url,
            notice_url=page_url,
            docs=[(text or "Document", url)] if is_document(url) else [],
            start_date=parse_date(context),
            end_date=(parse_date(m.group(1)) if (m := _LAST_DATE.search(context)) else None)
                     or _table_deadline(a),
            key_hint=stable_key(url, text, context),
        ))
    return ParseResult("ok" if items else "empty", items)
