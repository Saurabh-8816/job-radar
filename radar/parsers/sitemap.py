"""News sitemaps (sitemaps.org + Google News extension): the list a site gives search
engines of its articles from the last day or two, with titles and publish dates.

Exam-news sites such as PW (pw.live) have no single "latest jobs" page, but publish one
of these. Each article becomes an item; its page is read like any other notice page.
"""

import html
import re

from ..models import Item, ParseResult
from ..textutil import clean

_URL = re.compile(r"<url>(.*?)</url>", re.S | re.I)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_TITLE = re.compile(r"<(?:news:)?title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</(?:news:)?title>", re.S | re.I)
_DATE = re.compile(r"<(?:news:publication_date|lastmod)>\s*(\d{4}-\d{2}-\d{2})", re.I)


def _title_from_url(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").strip().capitalize()


def parse(text: str, page_url: str, source) -> ParseResult:
    if "<urlset" not in text[:2000] and "<url>" not in text:
        return ParseResult("unrecognized", [])
    items = []
    for block in _URL.findall(text):
        loc = _LOC.search(block)
        if not loc:
            continue
        url = html.unescape(loc.group(1)).strip()
        title = _TITLE.search(block)
        title = clean(html.unescape(title.group(1))) if title else _title_from_url(url)
        date = _DATE.search(block)
        if not url.startswith("http") or not title:
            continue
        items.append(Item(source_id=source.id, title=title, url=url, notice_url=page_url,
                          start_date=date.group(1) if date else None))
    return ParseResult("ok" if items else "empty", items)
