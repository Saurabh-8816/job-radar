"""Download and read the advert documents attached to a notice (shared by the
GitHub run and the laptop relay)."""

import re

from .classify import Classifier
from .fetch import get
from .pdftext import extract

_FORM_LABEL = re.compile(r"आवेदन\s*(प्रारूप|पत्र|फार्म|फॉर्म)|प्रारूप|application\s*form|format|proforma", re.I)
_ADVERT_LABEL = re.compile(r"विज्ञापन|भर्ती|advertis|advt|notification|recruit|vacanc|view", re.I)
_READABLE = (".pdf", ".jpg", ".jpeg", ".png")


def rank_docs(docs: list, clf: Classifier) -> list:
    """Adverts first (labels naming a matching post, then advert words); forms last."""
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
    readable = [d for d in docs if d[1].lower().split("?")[0].endswith(_READABLE)]
    return sorted(readable, key=score)[:3]


def read_item_docs(docs: list, clf: Classifier, ocr: bool = True) -> tuple[str, str]:
    """Text of the best (up to 3) documents, and an overall status:
    text | ocr | unreadable | error | none."""
    texts, statuses = [], []
    for _label, url in rank_docs(docs, clf):
        resp = get(url, binary=True, max_bytes=10_000_000, timeout=45, retries=1, total_timeout=90)
        if not resp.ok:
            statuses.append("error")
            continue
        doc = extract(resp.content, url, ocr=ocr)
        statuses.append(doc.status)
        if doc.status in ("text", "ocr"):
            texts.append(doc.text)
    if texts:
        status = "ocr" if "ocr" in statuses else "text"
    elif "unreadable" in statuses:
        status = "unreadable"
    else:
        status = "error" if statuses else "none"
    return "\n".join(texts), status
