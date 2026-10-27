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
