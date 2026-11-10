"""Download and read everything attached to a notice (shared by the GitHub run and
the laptop relay): every page of every advert PDF, and, when the notice is only a
link to a detail page (CG Vyapam "Post" pages, SarkariResult job pages), that
page's text plus the PDFs linked from it."""

import json
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .classify import Classifier
from .fetch import get
from .parsers import saral
from .pdftext import PAGE_BREAK, extract
from .textutil import clean, join_url

_FORM_LABEL = re.compile(r"आवेदन\s*(प्रारूप|पत्र|फार्म|फॉर्म)|प्रारूप|application\s*form|format|proforma", re.I)
_ADVERT_LABEL = re.compile(r"विज्ञापन|भर्ती|advertis|advt|notification|recruit|vacanc|notice|view", re.I)
_READABLE = (".pdf", ".jpg", ".jpeg", ".png")
_SIDEBAR = re.compile(r"sidebar|widget|related|recent[-_]?post|popular|trending|latest[-_]?(post|job|news)|"
                      r"yarpp|share|social|comment|breadcrumb", re.I)
MAX_DOCS = 5
PAGE_TEXT_LIMIT = 60_000


def _is_readable(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(_READABLE)


def rank_docs(docs: list, clf: Classifier) -> list:
    """Adverts first (labels naming a matching post, then advert words); blank
    application forms last, and only read when there is nothing else."""
    def score(doc):
        label, _url = doc
        s = 0
        if clf.strong.first(label) or clf.weak.first(label):
            s += 3
        if _ADVERT_LABEL.search(label):
            s += 1
        if _FORM_LABEL.search(label):
            s -= 5
        return -s
    readable = sorted((d for d in docs if _is_readable(d[1])), key=score)
    adverts = [d for d in readable if not _FORM_LABEL.search(d[0])]
    return (adverts or readable)[:MAX_DOCS]


def _is_pdf(resp) -> bool:
    return "pdf" in (resp.content_type or "").lower() or resp.content[:5] == b"%PDF-"


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_JSON_SKIP = re.compile(r"^_|id$|^(postedBy\w*|hrSpoc|uniqueLink|createdAt|updatedAt|isEnabled)$", re.I)


def _json_text(raw: bytes) -> str:
    """Readable text of a JSON detail record: 'last Date Of Application: 20/11/2026 ·
    qualifications: MCA…', with any HTML in the values stripped. The keys are kept as
    words so the deadline finder still sees 'last date'."""
    def walk(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                if not _JSON_SKIP.search(k):
                    yield from walk(v, k)
        elif isinstance(value, list):
            for v in value:
                yield from walk(v, key)
        elif isinstance(value, str) and value.strip():
            text = clean(BeautifulSoup(value, "lxml").get_text(" ")) if "<" in value else clean(value)
            yield f"{_CAMEL.sub(' ', key)}: {text}" if key else text
    try:
        return " · ".join(walk(json.loads(raw)))
    except ValueError:
        return ""


def _detail_page(url: str, clf: Classifier, ocr: bool, deadline, title: str = "") -> tuple[str, list, str]:
    """Text of a linked page, and the advert documents it links to. The link may itself
    be a PDF without a .pdf name (NIELIT 'Fileviewer?fileId=…', 'download.php?id=…').
    A JavaScript-built role page is read through its JSON feed instead (NISG SARAL)."""
    resp = get(saral.detail_feed(url) or url, binary=True, max_bytes=20_000_000, timeout=30,
               retries=1, total_timeout=90)
    if not resp.ok:
        return "", [], "error"
    if _is_pdf(resp):
        doc = extract(resp.content, url, ocr=ocr, deadline=deadline)
        return (doc.text if doc.status in ("text", "ocr") else ""), [], doc.status
    if "json" in (resp.content_type or "").lower():
        text = _json_text(resp.content)[:PAGE_TEXT_LIMIT]
        return text, [], "text" if text else "none"
    if "html" not in (resp.content_type or "text/html").lower():
        return "", [], "none"
    soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form"]):
        tag.decompose()
    docs = []
    for a in soup.find_all("a", href=True):
        href = join_url(url, a["href"].strip())
        if href.startswith("http") and _is_readable(href):
            docs.append((clean(a.get_text(" ")) or "Document", href))
    docs += _embedded_docs(soup, url)
    _strip_link_lists(soup)
    text = clean((soup.find("main") or soup.body or soup).get_text(" "))[:PAGE_TEXT_LIMIT]
    docs = list(dict.fromkeys(docs))
    return text, rank_docs(_named_after(docs, title) or docs, clf)[:3], "text" if text else "none"


_FILE_ATTRS = ("data-file", "data-src", "data-url", "data-pdf", "data-href")


def _embedded_docs(soup, page_url: str) -> list:
    """Documents a page opens without a plain link: a viewer button carrying the file
    (ISI Kolkata: <button data-file="/…/ADV_MIU.pdf">Preview</button>) or an embedded
    viewer (<iframe>/<embed src=…pdf>). Labelled with the text around the button, since
    the button itself only says "Preview" ("Advertisement - MIU Preview")."""
    found = []
    for el in soup.find_all(True):
        raw = next((el.get(k) for k in _FILE_ATTRS if el.get(k)), None)
        if raw is None and el.name in ("iframe", "embed", "object"):
            raw = el.get("src") or el.get("data")
        if not raw or not isinstance(raw, str):
            continue
        href = join_url(page_url, raw.strip())
        if not (href.startswith("http") and _is_readable(href)):
            continue
        label = clean(el.get_text(" "))
        if len(label) < 12 and el.parent is not None:
            label = clean(el.parent.get_text(" ")) or label
        found.append((label[:120] or "Document", href))
    return found


_WORD = re.compile(r"[a-zऀ-ॿ]{4,}")


def _named_after(docs: list, title: str) -> list:
    """The page's documents whose link text repeats the notice's own title. NITK puts its
    whole site menu (Institute Brochure, IT policy…) inside the advert page; reading the
    brochure matched "MCA" from its course list. Empty when none match: read as before."""
    head = set(_WORD.findall((title or "").lower()))
    if not head:
        return []
    named = []
    for label, url in docs:
        words = set(_WORD.findall(label.lower()))
        common = words & head
        if len(common) >= 2 and len(common) * 2 >= len(words):
            named.append((label, url))
    return named


def _strip_link_lists(soup):
    """Drop sidebars and "related / latest posts" blocks before reading a page's text:
    on aggregator pages they name other jobs ("NRLM Karnataka … MIS Coordinator…"),
    which would otherwise read as part of this advert."""
    for tag in soup.find_all("aside"):
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        names = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
        if _SIDEBAR.search(names):
            tag.decompose()
    for block in soup.find_all(["ul", "ol", "table", "div"]):
        if block.decomposed:
            continue
        links = block.find_all("a")
        if len(links) < 5:
            continue
        total = len(clean(block.get_text(" ")))
        linked = sum(len(clean(a.get_text(" "))) for a in links)
        if total and linked / total > 0.75:
            block.decompose()


def read_item_docs(docs: list, clf: Classifier, ocr: bool = True, page_url: str | None = None,
                   deadline: float | None = None, title: str = "") -> tuple[str, str]:
    """All text for one notice and an overall status:
    text | ocr | unreadable | error | none | deferred (time budget ran out; retry next run).
    `title` (the notice's title and row text) picks the advert among a page's documents."""
    texts, statuses = [], []
    targets = rank_docs(docs, clf)
    if not targets and page_url:
        page_text, targets, page_status = _detail_page(page_url, clf, ocr, deadline, title)
        statuses.append(page_status)
        if page_text:
            texts.append(page_text)
    for _label, url in targets:
        if deadline is not None and time.monotonic() > deadline:
            return "", "deferred"
        resp = get(url, binary=True, max_bytes=20_000_000, timeout=45, retries=1, total_timeout=120)
        if not resp.ok:
            statuses.append("error")
            continue
        doc = extract(resp.content, url, ocr=ocr, deadline=deadline)
        statuses.append(doc.status)
        if doc.status in ("text", "ocr"):
            texts.append(doc.text)
    if texts:
        status = "ocr" if "ocr" in statuses else "text"
    elif "unreadable" in statuses:
        status = "unreadable"
    else:
        status = "error" if statuses else "none"
    return PAGE_BREAK.join(texts), status
