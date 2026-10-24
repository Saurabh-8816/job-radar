"""Text from advert documents: embedded PDF text first, OCR for scans.

Most district adverts are scanned images with no text layer, so OCR (Tesseract,
Hindi + English) does the real work. PDFs typed in legacy Hindi fonts (Kruti Dev,
DevLys) extract as Latin junk such as "dk;kZy;"; those are detected and OCR'd too.
"""

import io
import os
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from . import ROOT

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


def extract(data: bytes, url: str = "", *, max_pages: int = 4, ocr: bool = True,
            ocr_pages: int = 2) -> DocText:
    if url.lower().split("?")[0].endswith(_IMAGE_EXT):
        return _extract_image(data, ocr)
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = len(reader.pages)
        text = "\n".join(_page_text(p) for p in reader.pages[:max_pages])
    except Exception:
        return DocText("", "error")
    if is_useful(text):
        return DocText(text, "text", pages)

    langs = ocr_languages() if ocr else None
    if langs:
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(data)
            n = min(ocr_pages, len(pdf))
            ocr_text = "\n".join(_ocr_image(pdf[i].render(scale=200 / 72).to_pil(), langs)
                                 for i in range(n))
            pdf.close()
            if is_useful(ocr_text):
                return DocText(ocr_text, "ocr", pages, n)
        except Exception:
            pass
    return DocText(text, "unreadable", pages)


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
