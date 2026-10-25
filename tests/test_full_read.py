"""Adverts are read from the first page to the last, and detail pages are followed."""

import re
import time

from conftest import FIXTURES, TODAY

from radar import docs
from radar.fetch import Response
from radar.pdftext import extract, page_of

DSSSB = (FIXTURES / "dsssb_advt_03_2026.pdf").read_bytes()
TITLE = "VACANCY NOTICE / ADVERTISEMENT NO. 03/2026 for various Posts from Post code 21/26 to 45/26"


def test_every_page_of_a_long_typed_advert_is_read():
    doc = extract(DSSSB, "advt.pdf", ocr=False)
    assert doc.status == "text" and doc.pages == 45
    m = re.search(r"Trained\s+Graduate\s+Teacher\s+\(Computer\s+Science\)\s+Department", doc.text)
    assert m and page_of(doc.text, m.start()) >= 15        # deep inside; the old 4-page read missed it


def test_dsssb_03_2026_alerts_with_page_evidence(clf):
    body = extract(DSSSB, "advt.pdf", ocr=False).text
    v = clf.classify(TITLE, "", body, None, "text", TODAY)
    assert v.tier == "A"
    evidence = [r for r in v.reasons if r.startswith("advert p.")]
    assert evidence and any("Computer Science" in e or "I.T. Assistant" in e for e in evidence)


def test_evidence_survives_pdf_line_breaks(clf):
    body = "Instructions\fPost Code 41/26 Trained Graduate Teacher (Computer\nScience) Directorate of Education"
    v = clf.classify("Advertisement for various posts", "", body, None, "text", TODAY)
    assert any(r.startswith("advert p.2:") and "Computer Science" in r for r in v.reasons)


def test_match_only_on_page_30_is_found(clf):
    body = "\f".join(["General conditions of recruitment and instructions to candidates."] * 29
                     + ["Post Code 07/26: Assistant Programmer, qualification MCA."])
    v = clf.classify("Advertisement No. 9/2026 for various posts", "", body, None, "text", TODAY)
    assert v.tier == "A"
    assert any(r.startswith("advert p.30:") for r in v.reasons)


def test_detail_page_and_its_pdf_are_read(monkeypatch, clf):
    page = ('<html><body><main><h1>Assistant Programmer Recruitment 2026</h1>'
            '<p>Eligibility: BCA / MCA.</p><a href="/files/advt.pdf">Download notification</a></main></body></html>')

    def fake_get(url, **kw):
        if url.endswith(".pdf"):
            return Response(url, True, 200, content=DSSSB, content_type="application/pdf")
        return Response(url, True, 200, text=page, content_type="text/html")

    monkeypatch.setattr(docs, "get", fake_get)
    text, status = docs.read_item_docs([], clf, ocr=False, page_url="https://vyapam.example/Post?PostID=AP1")
    assert status == "text"
    assert "Eligibility: BCA / MCA" in text                     # the detail page itself
    assert "Trained Graduate Teacher (Computer Science)" in text  # the PDF linked from it


def test_blank_application_forms_are_skipped_when_an_advert_exists(clf):
    ranked = docs.rank_docs([("आवेदन प्रारूप", "https://x/form.pdf"), ("View", "https://x/a.pdf"),
                             ("सहायक प्रोग्रामर भर्ती विज्ञापन", "https://x/ap.pdf")], clf)
    assert [u for _, u in ranked] == ["https://x/ap.pdf", "https://x/a.pdf"]


def test_time_budget_defers_instead_of_skipping(clf):
    text, status = docs.read_item_docs([("Advert", "https://x/a.pdf")], clf,
                                       deadline=time.monotonic() - 1)
    assert status == "deferred"                                 # stays pending for the next run
