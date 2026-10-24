"""Parser for NIC S3WaaS notice pages (every Indian district website).

The page holds one table: Title | Description | Start Date | End Date | File.
Hindi-default sites use Hindi headers, so columns are read by position, never by
header text. A category with no active notices has no table at all, only a
"no notices found" message; that is a healthy empty page, not a broken source.
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Item, ParseResult
from ..textutil import clean, parse_date, strip_size

_EMPTY_MARKERS = (
    "कोई नोटिस नहीं",            # Hindi: no notice found
    "no notices found",
    "no notice found",
    "sorry, no",
    "no records found",
)


def _find_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        if table.select("span.pdf-downloads, a.pdf-download-link"):
            return table
        if len(table.find_all("th")) >= 4:
            return table
    return None


def _columns(table) -> dict[str, int | None]:
    header = [clean(th.get_text()).lower() for th in table.find_all("th")]
    if len(header) == 4:  # rare variant without a description column
        return {"title": 0, "desc": None, "start": 1, "end": 2, "file": 3}
    return {"title": 0, "desc": 1, "start": 2, "end": 3, "file": 4}


def parse(html: str, page_url: str, source) -> ParseResult:
    soup = BeautifulSoup(html, "lxml")
    table = _find_table(soup)
    if table is None:
        text = clean(soup.get_text(" ")).lower()
        if any(marker in text for marker in _EMPTY_MARKERS):
            return ParseResult("empty", [])
        return ParseResult("unrecognized", [])

    cols = _columns(table)
    items = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        file_td = tds[min(cols["file"], len(tds) - 1)]
        docs = []
        for a in file_td.find_all("a", href=True):
            label = strip_size(clean(a.get_text(" "))) or "Document"
            docs.append((label, urljoin(page_url, a["href"].strip())))

        title = clean(tds[cols["title"]].get_text(" "))
        desc = clean(tds[cols["desc"]].get_text(" ")) if cols["desc"] is not None else ""
        if desc == title:
            desc = ""
        items.append(Item(
            source_id=source.id,
            title=title,
            description=desc,
            url=docs[0][1] if docs else page_url,
            notice_url=page_url,
            docs=docs,
            start_date=parse_date(tds[cols["start"]].get_text()),
            end_date=parse_date(tds[cols["end"]].get_text()),
        ))
    return ParseResult("ok" if items else "empty", items)
