from radar import docs, notify


def test_page_documents_named_after_the_notice_are_read_not_the_site_brochure():
    page_docs = [("Institute Brochure", "https://www.nitk.ac.in/document/attachments/5132/Brochure_Dec_2022.pdf"),
                 ("IT policy", "https://www.nitk.ac.in/Docs/nitk-it-policy.pdf"),
                 ("Advertisement for the position  of Project Associate",
                  "https://www.nitk.ac.in/document/attachments/10325/Advertisement.pdf")]
    picked = docs._named_after(page_docs, "Nov 09, 2026 Advertisement for the position of Project Associate")
    assert [u for _l, u in picked] == ["https://www.nitk.ac.in/document/attachments/10325/Advertisement.pdf"]


def test_no_named_document_means_no_narrowing():
    assert docs._named_after([("Download", "https://x.in/a.pdf")], "Programmer recruitment 2026") == []


def test_alert_links_the_notice_page_of_its_own():
    row = {"docs": "[]", "url": "https://www.nitk.ac.in/advertisement-for-the-postition-of-project-associate",
           "notice_url": "https://www.nitk.ac.in/"}
    links = notify.doc_links(row)
    assert ">Advert page<" in links and "advertisement-for-the-postition" in links and ">Notice page<" in links


def test_no_advert_page_link_when_the_url_is_the_document():
    row = {"docs": '[["Advt", "https://x.in/a.pdf"]]', "url": "https://x.in/a.pdf", "notice_url": "https://x.in/jobs"}
    assert ">Advert page<" not in notify.doc_links(row)


def test_viewer_button_and_embedded_documents_are_found():
    from bs4 import BeautifulSoup
    html = ('<div class="att"><span>Advertisement - MIU</span> '
            '<button data-file="/isical_web/admin/uploads/jobs/ADV_MIU.pdf">Preview</button></div>'
            '<iframe src="/files/notice.pdf"></iframe><button data-file="/x/photo.php">x</button>')
    found = docs._embedded_docs(BeautifulSoup(html, "lxml"), "https://www.isical.ac.in/isical_web/public/jobs_view.php?id=93")
    assert ("Advertisement - MIU Preview", "https://www.isical.ac.in/isical_web/admin/uploads/jobs/ADV_MIU.pdf") in found
    assert any(u == "https://www.isical.ac.in/files/notice.pdf" for _l, u in found)
    assert len(found) == 2
