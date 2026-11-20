"""Info Tech Corporation of Goa: notices come from the CMS's JSON API, not the page."""

from conftest import fixture_text

from radar.models import Source
from radar.parsers import cms_posts

API = "https://infotech.goa.gov.in/api/post/type/slug/appointments"
SRC = Source(id="itg-goa-appointments", name="ITG", kind="cms_posts", url=API)


def test_posts_become_notices_with_their_documents():
    res = cms_posts.parse(fixture_text("itg_appointments.json"), API, SRC)
    assert res.status == "ok" and len(res.items) == 3
    first = res.items[0]
    assert first.notice_url == "https://infotech.goa.gov.in/appointments"
    # appointments point at the candidate login, which is not an advert: the item opens the page
    assert first.url == first.notice_url and not first.docs
    assert first.key_hint.startswith("cms:infotech.goa.gov.in:") and first.start_date
    assert len({i.key for i in res.items}) == 3


def test_documents_are_the_adverts():
    post = {"data": [{"_id": "a1", "title": "Detailed Advertisement - DEO", "shortDescription": "Apply by 3 July",
                      "createdAt": "2026-06-17T05:00:00Z", "meta": [{"title": "Advt", "isDocument": True,
                      "documentUrl": "/uploads/deo/advt.pdf"}]}]}
    import json
    item = cms_posts.parse(json.dumps(post), "https://infotech.goa.gov.in/api/post/type/slug/announcements", SRC).items[0]
    assert item.url == "https://infotech.goa.gov.in/uploads/deo/advt.pdf" and item.description == "Apply by 3 July"


def test_not_json_is_flagged():
    assert cms_posts.parse("<html>maintenance</html>", API, SRC).status == "unrecognized"
