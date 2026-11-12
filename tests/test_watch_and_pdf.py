from radar.models import Source
from radar.parsers import watch
from radar.pdftext import is_useful, looks_legacy_font

PAGE = """
<html><body>
<nav><a href="/">Home</a> <a href="/careers">Careers</a></nav>
<div id="content"><table>
  <tr><td>Advt. No. 12/2026: Walk-in interview for Project Associate-I (CSE) on 05/11/2026</td>
      <td><a href="/files/advt-12-2026.pdf">Click here</a></td></tr>
  <tr><td>Result of written test for Junior Assistant</td>
      <td><a href="https://example.ac.in/files/result.pdf">Download</a></td></tr>
  <tr><td><a href="javascript:void(0)">Print</a> <a href="mailto:x@y.in">Mail</a></td></tr>
</table></div>
</body></html>
"""


def _src(selector=None):
    return Source(id="nit-x", name="NIT X", kind="watch", url="https://example.ac.in/jobs",
                  group="academic", selector=selector)


def test_watch_uses_row_context_for_generic_link_text():
    items = watch.parse(PAGE, "https://example.ac.in/jobs", _src()).items
    advt = next(i for i in items if i.url.endswith("advt-12-2026.pdf"))
    assert "Project Associate-I" in advt.title
    assert advt.url == "https://example.ac.in/files/advt-12-2026.pdf"
    assert advt.docs and advt.start_date == "2026-11-05"


def test_know_more_links_take_the_list_item_text():
    # CWC careers: "<li>Advertisement No CWC/... <a>Click here to know more</a></li>"
    html = ('<ul><li>Advertisement No CWC/I-Manpower/DR/Rectt/2026/01 '
            '<a href="/Careers/Guidelines/45/45_Detailed Advertisement.pdf">Click here to know more</a></li></ul>')
    items = watch.parse(html, "https://cwceportal.com/cwc_careers.html", _src()).items
    assert items[0].title.startswith("Advertisement No CWC/I-Manpower/DR/Rectt/2026/01")


def test_links_after_an_early_end_of_page_are_kept():
    # NITTTR Chennai prints a whole header page (ending </body></html>) before its table.
    html = ('<html><body><a href="/about.php">About us</a></body></html>'
            '<table><tr><td>Technical Officer (Workshop Superintendent)</td>'
            '<td><a href="/rec2026/staff/syllabus.pdf">View</a></td></tr></table>')
    items = watch.parse(html, "https://nitttrc.ac.in/nitttr_updated/rec_staff.php", _src()).items
    assert [i.title for i in items if i.url.endswith("syllabus.pdf")] == [
        "Technical Officer (Workshop Superintendent) View"]


def test_view_links_in_a_card_take_the_card_caption():
    html = ('<div class="common-document"><span>Advertisement 2026-27</span>'
            '<span><a href="/rec2026/staff/advt.pdf">View</a></span></div>')
    items = watch.parse(html, "https://nitttrc.ac.in/nitttr_updated/rec_staff.php", _src()).items
    assert items[0].title == "Advertisement 2026-27 View"


def test_section_heading_names_the_post_and_badges_are_ignored():
    # CG High Court: one accordion per post; the links only say "Merit List".
    item = ('<div class="accordion-item"><h2><button>Translator<span class="badge">New</span></button></h2>'
            '<ul><li>Merit List <a href="recruit/view_file_recruitment.php?token={t}">PDF</a>{b}</li></ul></div>')
    page = lambda t, b: f'<div id="acc">{item.format(t=t, b=b)}</div>'
    src = Source(id="cg-high-court", name="CG High Court", kind="watch", url="https://highcourt.cg.gov.in/x",
                 selector="#acc", sections=".accordion-item")
    first = watch.parse(page("AAAAAAAAAAAAAAAAAAAA1x", '<span class="badge">New</span>'), src.url, src).items[0]
    later = watch.parse(page("BBBBBBBBBBBBBBBBBBBB2y", ""), src.url, src).items[0]
    assert first.title == "Translator – Merit List PDF"
    assert first.key_hint == later.key_hint


def test_watch_skips_script_and_mail_links():
    urls = [i.url for i in watch.parse(PAGE, "https://example.ac.in/jobs", _src()).items]
    assert not any(u.startswith(("javascript", "mailto")) for u in urls)


def test_watch_selector_ignores_menus():
    items = watch.parse(PAGE, "https://example.ac.in/jobs", _src("#content")).items
    assert not any(i.url.endswith("/careers") for i in items)
    assert len(items) == 2


def test_token_links_keep_the_same_identity_across_page_loads():
    # NTPC signs every link with a fresh token on each load.
    row = '<tr><td>Advt. 14/26 Executive Trainee</td><td><a href="/recruitment/pdf_viewer.php?token={t}">Adv English</a></td></tr>'
    html = "<table>{}</table>"
    first = watch.parse(html.format(row.format(t="SHEyWlkzdG5MRE0rMG9EOEk1aDFqUz")), "https://careers.ntpc.co.in/recruitment/", _src())
    second = watch.parse(html.format(row.format(t="M2o1NDhhTklidFUxTUFDY1luaEtxMG")), "https://careers.ntpc.co.in/recruitment/", _src())
    assert first.items[0].key == second.items[0].key
    assert first.items[0].url != second.items[0].url   # the clickable link is still the fresh one


def test_stable_query_urls_are_untouched():
    assert watch.stable_key("https://x.ac.in/Recruitment/AdvNum?type=3052&level=54", "Advt", "") is None
    items = watch.parse('<a href="/jobs.php?id=12">Project Associate (CSE)</a>', "https://x.ac.in/", _src()).items
    assert items[0].key == "https://x.ac.in/jobs.php?id=12"


def test_aggregator_row_deadline_becomes_end_date():
    html = ('<ul><li><a href="/2026/up-dairy-deo-sept26/">UP Dairy Development DEO Data Entry Operator '
            'Recruitment 2026 | Last Date : 18/09/2026</a></li></ul>')
    item = watch.parse(html, "https://www.sarkariresult.com/latestjob/", _src()).items[0]
    assert item.end_date == "2026-09-18"


FJA = """<html><body><nav><a href="/bank-jobs/">Bank Jobs</a></nav>
<table class="kar-table kar-jobs"><tr><th>Post Date</th><th>Job Title</th><th>Post name</th><th>Vacancies</th>
<th>Qualification</th><th>Last Date</th><th>Notification</th></tr>
<tr><td>26/10/2026</td><td>PRSU Vacancy 2026 - 2 Junior Research Fellow</td><td>Junior Research Fellow</td>
<td>2 Posts</td><td>M.Sc, M.A</td><td>26-11-2026</td><td><a href="/articles/prsu-jrf-3074161">View</a></td></tr></table>
<table class="kar-table kar-jobs"><tr><th>Post Date</th><th>Job Title</th><th>Post name</th><th>Vacancies</th>
<th>Qualification</th><th>Last Date</th><th>Notification</th></tr>
<tr><td>25/10/2026</td><td>CHiPS Recruitment 2026</td><td>Programmer</td><td>5 Posts</td><td>MCA, B.Tech</td>
<td>15-11-2026</td><td><a href="/articles/chips-3074200">View</a></td></tr></table>
<table class="kar-table"><tr><th>Post Date</th><th>Title</th><th>Action</th></tr>
<tr><td>26/10/2026</td><td>Admit Card</td><td><a href="/articles/admit-1">View</a></td></tr></table></body></html>"""


def test_selector_reads_every_matching_table_and_skips_menus():
    src = Source(id="fja", name="FJA", kind="watch", url="https://www.freejobalert.com/x/", selector="table.kar-jobs")
    items = watch.parse(FJA, src.url, src).items
    assert [i.url.rsplit("/", 1)[-1] for i in items] == ["prsu-jrf-3074161", "chips-3074200"]
    assert "Programmer" in items[1].title and "MCA" in items[1].title     # row text, not just "View"


def test_last_date_column_becomes_the_deadline():
    src = Source(id="fja", name="FJA", kind="watch", url="https://www.freejobalert.com/x/", selector="table.kar-jobs")
    items = watch.parse(FJA, src.url, src).items
    assert [i.end_date for i in items] == ["2026-11-26", "2026-11-15"]


def test_legacy_hindi_font_is_not_useful_text():
    kruti = "dk;kZy; ftyk iapk;r dksaMkxkao NRrhlx<+ fokKkiu lgk;d izksxzkej in gsrq vkosnu i= " * 6
    assert looks_legacy_font(kruti)
    assert not is_useful(kruti)


def test_real_text_is_useful():
    english = "Applications are invited for the post of Assistant Programmer on contract basis. " * 3
    hindi = "सहायक प्रोग्रामर के पद हेतु आवेदन पत्र आमंत्रित किये जाते हैं। " * 4
    assert is_useful(english) and is_useful(hindi)
    assert not looks_legacy_font(english)


def test_page_number_links_are_not_notices():
    from radar.models import Source
    from radar.parsers import watch
    html = """<div class="view-content"><table><tr><td>Revival of 11 vacancies, Post Code 68/24 Junior Environmental Engineer
      <a href="/sites/default/files/68-24.pdf">Download</a></td></tr></table></div>
      <nav class="pager"><a href="?page=0">Current page 1</a> <a href="?page=1">Page 2</a> <a href="?page=2">3</a>
      <a href="?page=1">Next ›</a> <a href="?page=9">Last page Last »</a></nav>"""
    src = Source(id="dsssb", name="DSSSB", kind="watch", url="https://dsssb.delhi.gov.in/dsssb-vacancies")
    titles = [i.title for i in watch.parse(html, src.url, src).items]
    assert len(titles) == 1 and "Junior Environmental Engineer" in titles[0]


def test_end_date_column_is_the_deadline():
    """CPCB's jobs table: S. No | Title | Start Date | End Date | Advertisement."""
    from radar.models import Source
    from radar.parsers import watch
    src = Source(id="cpcb", name="CPCB", kind="watch", url="https://cpcb.gov.in/jobs.php")
    html = """<table><tr><th>S. No</th><th>Title</th><th>Start Date</th><th>End Date</th><th>Advertisement</th></tr>
      <tr><td>1</td><td>Advertisement for Scientists (51) posts</td><td>24-08-2026</td><td>07-09-2026</td>
      <td><a href="openpdffile.php?id=Q2FyZWVyRmlsZXMvMjU1XzE3ODcyMjg1MzlfbWVkaWFwaG90bzg3MDYucGRm">View</a></td></tr></table>"""
    (item,) = watch.parse(html, src.url, src).items
    assert item.end_date == "2026-09-07"


def test_download_link_with_file_size_takes_the_row_title():
    """NCLAT: Sr. No. | Title | Closing Date | Advocacy Title | Documents ("Download(2.81 MB)")."""
    src = Source(id="nclat", name="NCLAT", kind="watch", url="https://nclat.nic.in/recruitment")
    html = """<table><tr><th>Sr. No.</th><th>Title</th><th>Closing Date</th><th>Documents</th></tr>
      <tr><td>1</td><td>Filling up of various posts in the NCLAT on deputation basis</td><td>09/12/2026</td>
      <td><a href="/files/Vacancy circular.pdf">Download(2.81 MB)</a></td></tr></table>"""
    (item,) = watch.parse(html, src.url, src).items
    assert item.title.startswith("1 Filling up of various posts")
    assert item.end_date == "2026-12-09"


def test_due_date_column_and_icon_only_link():
    # TIFR: Reference No | Description | Due Date | File (a PDF icon whose only text is title="nfile")
    html = ('<table><tr><td>Reference No</td><td>Description</td><td>Due Date</td><td>File</td></tr>'
            '<tr><td>Advertisement No.2026/30</td><td>Applications are invited for various categories of posts</td>'
            '<td>24-11-2026</td><td><a href="viewNoticeFile.php?f=YVJlRTZKSVNFTmVaT01RQ1hSeU96QT09" title="nfile">'
            '<i class="fa fa-file-pdf"></i></a></td></tr></table>')
    src = Source(id="tifr", name="TIFR", kind="watch", url="https://www.tifr.res.in/positions", use_base=True)
    (item,) = watch.parse('<head><base href="/maincampus/"></head>' + html, src.url, src).items
    assert "various categories of posts" in item.title
    assert item.end_date == "2026-11-24"
    assert item.url.startswith("https://www.tifr.res.in/maincampus/viewNoticeFile.php?f=")   # <base> honoured


def test_file_size_only_link_takes_the_row_title():
    # NPPA: "<td>Hiring of Seven (07) Consultants…</td><td><a>1.62 MB PDF English</a></td>"
    html = ('<table><tr><td>1</td><td>06-Oct-2026</td><td>Hiring of Seven (07) Consultants/Young Professionals</td>'
            '<td><a href="/storage/uploads/tender/vacancynotice-ef3a.pdf">1.62 MB PDF English</a></td></tr></table>')
    (item,) = watch.parse(html, "https://nppa.gov.in/en/view_more?id=5", _src()).items
    assert "Hiring of Seven (07) Consultants" in item.title


def test_card_heading_link_selector_and_card_last_date():
    """IIIT Pune careers: one card per post; the selector picks its advert links (not the
    form), the <h3> names the post (minus its NEW tag), the card gives the last date."""
    html = ('<main><div class="p-6 border-b"><h3>Advertisement for JRF in ISRO Project<span>NEW</span></h3>'
            '<div class="mb-3"><a href="/careers-documents/Advt.pdf">Details</a>'
            '<a href="https://forms.gle/x">Apply Now</a></div>'
            '<div>Date of Upload: 06-11-2026 Last Date to Apply: 25-11-2026</div></div></main>')
    src = Source(id="iiit-pune", name="IIIT Pune", kind="watch", url="https://www.iiitp.ac.in/careers",
                 selector='main div.mb-3 > a:not([href*="forms.gle"])', sections="main div.border-b")
    (item,) = watch.parse(html, src.url, src).items
    assert item.title == "Advertisement for JRF in ISRO Project – Details"
    assert item.end_date == "2026-11-25"


def test_date_only_link_text_takes_the_row_title():
    # NITK: "<li><a>Nov 09, 2026</a> Advertisement for the position of Project Associate</li>"
    html = ('<ul><li><a href="/advertisement-for-the-postition-of-project-associate">Nov 09, 2026</a> '
            'Advertisement for the position of Project Associate</li></ul>')
    (item,) = watch.parse(html, "https://www.nitk.ac.in/", _src()).items
    assert "Project Associate" in item.title


def test_two_notices_linking_the_same_portal_root_are_two_items():
    html = ('<ul><li><a href="https://rects.immt.res.in/">Project Staff Recruitment Advertisement (Advt. No. PME/P87/2026)</a></li>'
            '<li><a href="https://rects.immt.res.in/">Project Staff Recruitment via Advt No. PME/P86/2026</a></li>'
            '<li><a href="/">Home</a> <a href="/">Main page</a></li></ul>')
    items = watch.parse(html, "https://www.immt.res.in/", _src()).items
    portal = [i for i in items if i.url == "https://rects.immt.res.in/"]
    assert len(portal) == 2 and portal[0].key != portal[1].key
    assert all(i.key.startswith("w:https://rects.immt.res.in") for i in portal)
    assert len([i for i in items if i.url == "https://www.immt.res.in/"]) == 1   # own-site root: still one, by URL


def test_page_with_thin_text_over_a_scanned_image_is_ocrd(monkeypatch):
    """IIST, Nov 2026: page 1 had a Hindi letterhead as text over an image of the post
    table, so it counted as 'readable' and the table (Masters in Computer Science) was lost."""
    import io

    import pytest
    pytest.importorskip("reportlab")   # builds the sample PDF; not a radar dependency
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from radar import pdftext
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 800, "Government of India Department of Space Indian Institute")   # thin text layer
    c.drawImage(ImageReader(Image.new("RGB", (200, 100), "white")), 72, 400)
    c.showPage()
    c.save()
    monkeypatch.setattr(pdftext, "ocr_languages", lambda: "eng")
    monkeypatch.setattr(pdftext, "_ocr_image", lambda image, langs: "PROJECT ASSOCIATE-I Masters in Computer "
                        "Science and Engineering or AIML, Rs 31000 plus HRA, maximum age 35 years " * 2)
    doc = pdftext.extract(buf.getvalue(), "advt.pdf")
    assert doc.status == "ocr" and "Computer Science" in doc.text


def test_file_name_link_text_takes_the_row_title():
    # NITCON: "NIT/ICAT/2026-27/17/01 | Engineer | <a>Adv 17_01.pdf</a> | <a>Application Form.pdf</a>"
    html = ('<table><tr><td>NIT/ICAT/2026-27/17/01</td><td>Engineer</td>'
            '<td><a href="/pdfdownload/17_01_Engineer_(Fatigue Lab).pdf">Adv 17_01.pdf</a></td></tr></table>')
    (item,) = watch.parse(html, "https://www.nitcon.org/Career/", _src()).items
    assert "Engineer" in item.title and "NIT/ICAT/2026-27/17/01" in item.title
