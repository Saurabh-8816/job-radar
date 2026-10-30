"""News sitemaps (PW / pw.live): articles become notices, read like any notice page."""

from radar.models import Source
from radar.parsers import sitemap

SRC = Source(id="pw-news", name="PW", kind="sitemap", url="https://www.pw.live/sitemaps/pwlive/news/sitemap_1.xml")

XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url><loc>https://www.pw.live/news/tspc-aso-notification-out</loc>
    <news:news><news:publication_date>2026-10-30</news:publication_date>
      <news:title>TSPSC MPSO ASO Notification 2026 Out for 102 Posts &amp; More</news:title></news:news></url>
  <url><loc>https://www.pw.live/news/rrb-ntpc-recruitment-2026-vacancy-details</loc><lastmod>2026-10-29</lastmod></url>
</urlset>"""


def test_news_sitemap_articles_become_notices():
    res = sitemap.parse(XML, SRC.url, SRC)
    assert res.status == "ok" and len(res.items) == 2
    first, second = res.items
    assert first.title == "TSPSC MPSO ASO Notification 2026 Out for 102 Posts & More"
    assert first.start_date == "2026-10-30" and first.notice_url == SRC.url
    assert first.url != first.notice_url             # so the article page itself gets read
    assert second.title == "Rrb ntpc recruitment 2026 vacancy details" and second.start_date == "2026-10-29"


def test_a_sitemap_index_or_html_page_is_flagged():
    assert sitemap.parse("<html><body>Maintenance</body></html>", SRC.url, SRC).status == "unrecognized"
