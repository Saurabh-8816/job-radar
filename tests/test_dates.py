"""Deadlines written with the month in words, in titles as well as adverts, and
aggregator sidebars kept out of an advert's text."""

import pytest
from bs4 import BeautifulSoup
from conftest import TODAY

from radar.docs import _strip_link_lists
from radar.textutil import all_dates, parse_date


@pytest.mark.parametrize("text,iso", [
    ("Last date of receiving application: 15th November, 2026", "2026-11-15"),
    ("last date 15 Nov 2026", "2026-11-15"),
    ("on or before November 15, 2026", "2026-11-15"),
    ("15-Nov-2026", "2026-11-15"),
    ("Sept. 5, 2026", "2026-09-05"),
    ("अंतिम तिथि 15 नवंबर 2026", "2026-11-15"),
    ("दिनांक १५/११/२०२६ तक", "2026-11-15"),
    ("15.11.2026", "2026-11-15"),
])
def test_dates_in_words_and_numbers(text, iso):
    assert parse_date(text) == iso


def test_not_dates():
    for text in ("May 2026 issue", "posted on 12 may", "31 Feb 2026", "Advt No. 12/2026"):
        assert parse_date(text) is None, text


def test_range_gives_both_dates_in_order():
    assert [d for d, _s, _e in all_dates("from 1st Dec 2026 to 31st December 2026")] == ["2026-12-01", "2026-12-31"]


def test_deadline_in_the_title_is_used(clf):
    title = "Vacancy for Project INTERN Position at IIIT Guwahati, Last date of receiving application: 15th November, 2026"
    assert clf.classify(title, "", "Computer Science and Engineering project", None, "text", TODAY).deadline == "2026-11-15"


def test_aggregator_sidebar_is_not_advert_text():
    soup = BeautifulSoup("""<main><p>NIT Delhi Project Associate. Essential: B.Tech CSE.</p>
      <table><tr><td>Notification</td><td><a href="a.pdf">Click Here</a></td></tr></table>
      <div class="td-related-posts"><a href="x">NRLM Karnataka MIS Coordinator</a></div>
      <ul><li><a href="1">ICMR Project Research Scientist</a></li><li><a href="2">AIIMS Assistant Professor</a></li>
      <li><a href="3">SSC CGL</a></li><li><a href="4">RRB NTPC</a></li><li><a href="5">IBPS PO</a></li></ul></main>""", "lxml")
    _strip_link_lists(soup)
    text = soup.get_text(" ", strip=True)
    assert "B.Tech CSE" in text and "Notification" in text
    assert "NRLM" not in text and "Assistant Professor" not in text
