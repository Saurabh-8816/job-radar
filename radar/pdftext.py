"""Text from advert documents: every page, embedded text first, OCR for scans.

Most district adverts are scanned images with no text layer, so OCR (Tesseract,
Hindi + English) does the real work. PDFs typed in legacy Hindi fonts (Kruti Dev,
DevLys) extract as Latin junk such as "dk;kZy;"; those pages are OCR'd too. The
decision is per page, so a typed cover letter in front of a scanned table still
gets the table read.
"""

import io
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from . import ROOT

# Government PDFs are often malformed; pypdf logs a warning per broken object but still
# extracts fine. Those warnings drown the run log, so only real errors are shown.
logging.getLogger("pypdf").setLevel(logging.ERROR)

_LETTERS = re.compile(r"[A-Za-z\u0900-\u097F]")
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LOCAL_TESSDATA = ROOT / ".tessdata"
_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
_IMAGE_EXT = (".jpg", ".jpeg", ".png")


@dataclass
class DocText:
    text: str
    status: str          # "text" | "ocr" | "unreadable" | "error" | "skipped"
    pages: int = 0
    ocr_pages: int = 0


@lru_cache(maxsize=1)
def ocr_languages() -> str | None:
    """'hin+eng' when available, 'eng' as a fallback, None without Tesseract."""
    cmd = shutil.which("tesseract") or (str(_WINDOWS_TESSERACT) if _WINDOWS_TESSERACT.exists() else None)
    if not cmd:
        return None
    try:
        import pytesseract
    except ImportError:
        return None
    pytesseract.pytesseract.tesseract_cmd = cmd
    if (LOCAL_TESSDATA / "hin.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(LOCAL_TESSDATA)
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return None
    chosen = [lang for lang in ("hin", "eng") if lang in langs]
    return "+".join(chosen) or None


def looks_legacy_font(text: str) -> bool:
    letters = len(_LETTERS.findall(text))
    if letters < 200 or _DEVANAGARI.search(text):
        return False
    # Kruti Dev maps ा to 'k' and य to ';', so both are wildly over-represented.
    return text.lower().count("k") / letters > 0.06 or text.count(";") / letters > 0.02


def is_useful(text: str) -> bool:
    return len(_LETTERS.findall(text)) >= 80 and not looks_legacy_font(text)


def _ocr_image(image, langs: str) -> str:
    import pytesseract
    return pytesseract.image_to_string(image.convert("L"), lang=langs)


PAGE_BREAK = "\n\f\n"     # pages are joined with a form feed, so a match's page number is recoverable


def _page_is_readable(text: str) -> bool:
    return len(_LETTERS.findall(text)) >= 40 and not looks_legacy_font(text)


def page_of(text: str, pos: int) -> int:
    return text.count("\f", 0, pos) + 1


def extract(data: bytes, url: str = "", *, max_pages: int | None = None, ocr: bool = True,
            ocr_pages: int = 12, deadline: float | None = None) -> DocText:
    """Every page's text. Pages without a usable text layer (scans, legacy Hindi fonts)
    are OCR'd, up to `ocr_pages` per document and until `deadline` (time.monotonic());
    typed pages cost nothing, so a 45-page typed advert is read in full."""
    if url.lower().split("?")[0].endswith(_IMAGE_EXT):
        return _extract_image(data, ocr)
    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        texts = [_page_text(p) for p in (reader.pages if max_pages is None else reader.pages[:max_pages])]
    except Exception:
        return DocText("", "error")

    unreadable = [i for i, t in enumerate(texts) if not _page_is_readable(t)]
    langs = ocr_languages() if (ocr and unreadable) else None
    done = 0
    if langs:
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(data)
            for i in unreadable[:ocr_pages]:
                if deadline is not None and time.monotonic() > deadline:
                    break
                ocr_text = _ocr_image(pdf[i].render(scale=200 / 72).to_pil(), langs)
                if _page_is_readable(ocr_text):
                    texts[i] = ocr_text
                done += 1
            pdf.close()
        except Exception:
            pass

    text = PAGE_BREAK.join(t if _page_is_readable(t) else "" for t in texts)
    if not is_useful(text):
        return DocText(text, "unreadable", page_count, done)
    return DocText(text, "ocr" if done else "text", page_count, done)


def _extract_image(data: bytes, ocr: bool) -> DocText:
    langs = ocr_languages() if ocr else None
    if not langs:
        return DocText("", "unreadable")
    try:
        from PIL import Image
        text = _ocr_image(Image.open(io.BytesIO(data)), langs)
    except Exception:
        return DocText("", "error")
    return DocText(text, "ocr" if is_useful(text) else "unreadable", 1, 1)


def _page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""
