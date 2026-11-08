"""NISG's hiring portal feed (saral.nisg.org), which carries NHA / ABDM roles."""

import json

from radar.models import Source
from radar.parsers import saral

SRC = Source(id="national-institute-for-smart-government-nisg", name="NISG – SARAL", kind="saral",
             url="https://saral.nisg.org/api/jobs/public", group="psu")


def _role(**kw):
    role = {"_id": "6af1", "projectName": "National Health Authority(ABDM)",
            "designations": ["Project Coordinator"], "location": "Delhi",
            "experience": "<ul><li>B.E./B.Tech/M.Tech/<b>MCA</b> or equivalent</li></ul>",
            "natureOfAppointment": "Contractual", "uniqueLink": "3b92", "createdAt": "2026-10-19T09:00:00Z",
            "summary": "Support states in ABDM implementation"}
    return {**role, **kw}


def test_each_open_role_is_an_item_with_its_project_and_eligibility():
    res = saral.parse(json.dumps({"success": True, "vacancies": [
        _role(), _role(_id="6af2", uniqueLink="9db1", designations=["Team Lead - PIB"],
                       projectName="Press Information Bureau")]}), SRC.url, SRC)
    nha, pib = res.items
    assert res.status == "ok"
    assert nha.title == "Project Coordinator – National Health Authority(ABDM)"
    assert nha.url == "https://saral.nisg.org/job-description?token=3b92"
    assert "MCA" in nha.description and "<" not in nha.description
    assert nha.key == "saral:6af1" and nha.start_date == "2026-10-19"
    assert pib.title == "Team Lead - PIB – Press Information Bureau"


def test_roles_without_a_link_are_skipped_and_odd_replies_flagged():
    assert saral.parse(json.dumps({"vacancies": [_role(uniqueLink="")]}), SRC.url, SRC).status == "empty"
    assert saral.parse("<html>down</html>", SRC.url, SRC).status == "unrecognized"


def test_role_page_is_read_through_its_json_detail():
    from radar.docs import _json_text
    assert saral.detail_feed("https://saral.nisg.org/job-description?token=3b92") == \
        "https://saral.nisg.org/api/jobs/public/3b92"
    assert saral.detail_feed("https://saral.nisg.org/") is None
    text = _json_text(json.dumps({"success": True, "vacancy": {
        "_id": "x", "postedByName": "A Recruiter", "hrSpoc": "hr@example.org",
        "qualifications": "<p>B.Tech / <b>MCA</b></p>", "lastDateOfApplication": "20/11/2026"}}).encode())
    assert "qualifications: B.Tech / MCA" in text and "last Date Of Application: 20/11/2026" in text
    assert "Recruiter" not in text and "hr@" not in text
