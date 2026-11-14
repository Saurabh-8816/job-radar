"""Single-page apps whose notices live inside their JavaScript bundle.

Some sites (the IIIT Naya Raipur AI Centre of Excellence, iftbie.co.in) are a React app
whose page is an empty <div id="root">. The recruitment notice is only reachable after
clicking through to a "Careers" view, so neither the plain page nor a rendered one shows
the link. The links are, however, written into the app's bundle (`href:"/Notice.pdf"`).

The bundle's file name changes on every redeploy (index-<hash>.js), so the source points
at the page; this parser follows the page's <script src> to the bundle and turns every
document it links to into a notice, titled from the file name and described by the text
around the link.
"""

import re
from urllib.parse import unquote, urljoin

from ..fetch import get
from ..models import Item, ParseResult
from ..textutil import clean

_SCRIPT = re.compile(r"<script[^>]+src=[\"']([^\"']+\.js)[\"']", re.I)
_DOC = re.compile(r"""href:\s*["']([^"']+\.(?:pdf|docx?|xlsx?))["']""", re.I)
_TEXT = re.compile(r"""children:\s*["']([^"']{4,200})["']""")
_FILLER = re.compile(r"(?i)^(close|view|download|click here|official (notice|pdf)|read more|apply now)\b")


def _title(url: str) -> str:
    name = unquote(url.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    name = re.sub(r"\s*\(\d+\)$", "", name)                 # "Brochure (1)"
    return clean(re.sub(r"[_]+", " ", name))


def _context(js: str, start: int, end: int) -> str:
    """The app's own strings around the link: deadlines, button captions, notes."""
    around = js[max(0, start - 600):end + 600]
    words = [t for t in _TEXT.findall(around) if not _FILLER.match(t)]
    return clean(" · ".join(dict.fromkeys(words)))[:400]


def links_in_bundle(js: str, page_url: str) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    for m in _DOC.finditer(js):
        url = urljoin(page_url, m.group(1))
        context = _context(js, m.start(), m.end())
        if len(context) > len(found.get(url, "")):     # a link repeated: keep its richest context
            found[url] = context
    return list(found.items())


def parse(html: str, page_url: str, source) -> ParseResult:
    scripts = _SCRIPT.findall(html)
    if not scripts:
        return ParseResult("unrecognized", [])
    items = []
    for src in scripts:
        resp = get(urljoin(page_url, src), max_bytes=20_000_000)
        if not resp.ok or not resp.text:
            continue
        for url, context in links_in_bundle(resp.text, page_url):
            items.append(Item(source_id=source.id, title=_title(url), url=url,
                              notice_url=page_url, description=context))
    return ParseResult("ok" if items else "empty", items)
