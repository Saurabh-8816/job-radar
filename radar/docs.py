"""Download and read everything attached to a notice (shared by the GitHub run and
the laptop relay): every page of every advert PDF, and, when the notice is only a
link to a detail page (CG Vyapam "Post" pages, SarkariResult job pages), that
page's text plus the PDFs linked from it."""

import re
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .classify import Classifier
from .fetch import get
from .pdftext import PAGE_BREAK, extract
from .textutil import clean

_FORM_LABEL = re.compile(r"आवेदन\s*(प्रारूप|पत्र|फार्म|फॉर्म)|प्रारूप|application\s*form|format|proforma", re.I)
_ADVERT_LABEL = re.compile(r"विज्ञापन|भर्ती|advertis|advt|notification|recruit|vacanc|notice|view", re.I)
_READABLE = (".pdf", ".jpg", ".jpeg", ".png")
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


def _detail_page(url: str, clf: Classifier, ocr: bool, deadline) -> tuple[str, list, str]:
    """Text of a linked page, and the advert documents it links to. The link may itself
    be a PDF without a .pdf name (NIELIT 'Fileviewer?fileId=…', 'download.php?id=…')."""
    resp = get(url, binary=True, max_bytes=20_000_000, timeout=30, retries=1, total_timeout=90)
    if not resp.ok:
        return "", [], "error"
    if _is_pdf(resp):
        doc = extract(resp.content, url, ocr=ocr, deadline=deadline)
        return (doc.text if doc.status in ("text", "ocr") else ""), [], doc.status
    if "html" not in (resp.content_type or "text/html").lower():
        return "", [], "none"
    soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form"]):
        tag.decompose()
    docs = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"].strip())
        if href.startswith("http") and _is_readable(href):
            docs.append((clean(a.get_text(" ")) or "Document", href))
    text = clean((soup.find("main") or soup.body or soup).get_text(" "))[:PAGE_TEXT_LIMIT]
    return text, rank_docs(list(dict.fromkeys(docs)), clf)[:3], "text" if text else "none"


def read_item_docs(docs: list, clf: Classifier, ocr: bool = True, page_url: str | None = None,
                   deadline: float | None = None) -> tuple[str, str]:
    """All text for one notice and an overall status:
    text | ocr | unreadable | error | none | deferred (time budget ran out; retry next run)."""
    texts, statuses = [], []
    targets = rank_docs(docs, clf)
    if not targets and page_url:
        page_text, targets, page_status = _detail_page(page_url, clf, ocr, deadline)
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
