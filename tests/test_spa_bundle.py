"""SPA sites whose notice PDFs are only linked from the JavaScript bundle (IIIT-NR AI-CoE)."""

from radar.models import Source
from radar.parsers import spa_bundle

SRC = Source(id="iiitnr-ai-coe", name="AI-CoE", kind="spa_bundle", url="https://www.iftbie.co.in/")

JS = ('s.jsx("span",{children:"Extended: 28.11.2026"}),s.jsx("p",{children:"Click the respective button '
      'below to open the official application form in a new tab."}),s.jsxs("a",{href:"/IFTBIE_AI-CoE_'
      'Recruitment_Notice_2026.pdf",target:"_blank",children:"Official Notice (PDF)"}),'
      's.jsx("a",{href:"/IFTBIE_AI-CoE_Recruitment_Notice_2026.pdf",children:"Close"}),'
      's.jsx("a",{href:"/IndiaAI_CoE_Naya_Raipur_Brochure (1).pdf",children:"Brochure"})')


def test_bundle_document_links_become_notices():
    links = dict(spa_bundle.links_in_bundle(JS, SRC.url))
    notice = "https://www.iftbie.co.in/IFTBIE_AI-CoE_Recruitment_Notice_2026.pdf"
    assert set(links) == {notice, "https://www.iftbie.co.in/IndiaAI_CoE_Naya_Raipur_Brochure (1).pdf"}
    assert "Extended: 28.11.2026" in links[notice] and "Official Notice" not in links[notice]
    assert spa_bundle._title(notice) == "IFTBIE AI-CoE Recruitment Notice 2026"
    assert spa_bundle._title("https://x.in/IndiaAI_CoE_Naya_Raipur_Brochure%20(1).pdf") == "IndiaAI CoE Naya Raipur Brochure"


def test_page_without_scripts_is_flagged():
    assert spa_bundle.parse("<html><body>hi</body></html>", SRC.url, SRC).status == "unrecognized"
