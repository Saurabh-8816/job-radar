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
