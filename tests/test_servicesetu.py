"""ServiceSetu jobs feed, and the classifier rules its real posts exposed."""

import json

import pytest
from conftest import FIXTURES, TODAY

from radar.models import Source
from radar.parsers import servicesetu

SRC = Source(id="servicesetu-jobs", name="ServiceSetu", kind="servicesetu",
             url="https://app.servicesetu.org/api/jobs?page=1&limit=100", group="academic")


def _feed(*jobs):
    return json.dumps({"status": "success", "data": {"jobs": list(jobs), "total": len(jobs)}})


def _job(**kw):
    base = {"id": "id-1", "title": "NIT Patna Recruitment 2026 – Project Assistant", "slug": "nit-patna-pa",
            "content": "<p>Essential: B.Tech in CSE or MCA.</p>", "location": "India", "employer": "NIT Patna",
            "position": ["project_staff"], "field": ["engineering_technology"], "approvalStatus": "approved",
            "isArchived": False, "applicationDeadline": "2026-11-06T00:00:00.000Z",
            "applyNowLink": "https://www.nitp.ac.in/", "createdAt": "2026-10-26T10:00:00.000Z"}
    return {**base, **kw}


def test_real_feed_sample_parses_with_advert_text():
    res = servicesetu.parse((FIXTURES / "servicesetu_jobs.json").read_text(encoding="utf-8"), SRC.url, SRC)
    assert res.status == "ok" and res.items
    assert all(i.url.startswith("https://www.servicesetu.org/jobs/") for i in res.items)
    assert all(i.key in res.texts for i in res.items)            # description = advert text, no PDF fetch


def test_fields_deadline_and_apply_link():
    item = servicesetu.parse(_feed(_job()), SRC.url, SRC).items[0]
    assert item.end_date == "2026-11-06" and item.start_date == "2026-10-26"
    assert "Project Staff" in item.description and "NIT Patna" in item.description
    assert item.docs == [("Apply / official site", "https://www.nitp.ac.in/")]
    assert item.key == "servicesetu:id-1"


def test_foreign_and_archived_posts_are_skipped():
    res = servicesetu.parse(_feed(_job(id="us", slug="us", location="United States"),
                                  _job(id="old", slug="old", isArchived=True),
                                  _job(id="in", slug="in")), SRC.url, SRC)
    assert [i.key for i in res.items] == ["servicesetu:in"]


def test_broken_feed_is_flagged():
    assert servicesetu.parse("<html>maintenance</html>", SRC.url, SRC).status == "unrecognized"


# ---- rules exposed by real ServiceSetu posts -------------------------------------

@pytest.mark.parametrize("title,body", [
    ("IIT Gandhinagar Senior Research Fellow Recruitment 2026 – Electrical Engineering",
     "computational modelling and simulation using specialised software tools to study semiconductor devices"),
    ("IIT Gandhinagar Junior Research Fellow (JRF) – Biological Sciences",
     "DNA Nanotechnology for Biological Systems Programming"),
    ("NIT Raipur JRF / Project Staff Recruitment 2026 – Electrical Engineering",
     "desirable: electrical engineering software proficiency, power electronics"),
    ("IIT Roorkee JRF Recruitment 2026 – Civil Engineering | DRDO Research Project",
     "M.Tech in Civil Engineering with GATE"),
])
def test_research_posts_in_other_fields_are_digest_only(clf, title, body):
    assert clf.classify(title, "", body, None, "text", TODAY).tier == "B"


@pytest.mark.parametrize("title,body", [
    ("IIT Kanpur Assistant Professor Recruitment 2026 – Special Drive",
     "Departments: Civil Engineering, Computer Science and Engineering. Ph.D. with first class in preceding degree."),
    ("IIT Hyderabad Faculty Recruitment 2026–27 – Assistant Professor",
     "Computer Science & Engineering. Ph.D. required."),
])
def test_phd_level_faculty_posts_are_digest_only(clf, title, body):
    v = clf.classify(title, "", body, None, "text", TODAY)
    assert v.tier == "B"
    assert any("MCA/NET" in r for r in v.reasons)


def test_college_assistant_professor_open_to_mca_net_is_tier_a(clf):
    body = "Assistant Professor (Computer Science): MCA / M.Tech with 55% marks and UGC-NET / SET qualified."
    assert clf.classify("Recruitment of Assistant Professor 2026", "", body, None, "text", TODAY).tier == "A"


def test_project_staff_in_cse_stays_tier_a(clf):
    body = "Project Assistant: B.Tech in Electronics and Communication Engineering (ECE), Computer Science and Engineering (CSE)"
    assert clf.classify("NIT Patna Recruitment 2026 – Project Assistant", "", body, None, "text", TODAY).tier == "A"


def test_iiit_name_is_not_an_it_qualification(clf):
    body = "The Indian Institute of Information Technology Dharwad invites applications for Junior Assistant."
    assert clf.classify("IIIT Dharwad Non-Teaching Recruitment 2026 – Junior Assistant", "", body,
                        None, "text", TODAY).tier != "A"


def test_servicesetu_boilerplate_and_field_tags_are_not_read():
    content = ("<p>Project Associate in Electrical Engineering.</p>"
               "<p>You may join the ServiceSetu Whatsapp Channel to get updates on faculty positions.</p>")
    res = servicesetu.parse(_feed(_job(content=content, field=["data_science"])), SRC.url, SRC)
    item = res.items[0]
    assert "faculty positions" not in res.texts[item.key][0]
    assert "Data Science" not in item.description
