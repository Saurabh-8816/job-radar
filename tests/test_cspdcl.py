"""CG power companies' recruitment feed (web.cspdcl.co.in)."""

import json

from radar.models import Source
from radar.parsers import cspdcl

SRC = Source(id="cg-power-companies", name="CG Power Companies", kind="cspdcl",
             url="https://escapi.cspdcl.co.in/api/api/recruitment/pagination?page=1&limit=20", group="cg-state")


def _feed(*posts):
    return json.dumps({"totalItems": len(posts), "data": list(posts)})


def _post(name, *flags, enabled="1"):
    return {"RECRUITMENT_REF_SRNO": "70", "NAME_OF_POST": name, "ENABLED_DISABLED": enabled,
            "particulars": [{"SRNO": "165", "PARTICULARS_DESC": "Notices", "flags": list(flags)}]}


def test_each_file_is_an_item_read_through_its_own_link():
    res = cspdcl.parse(_feed(_post(
        "Recruitment For Various Posts in CSPTCL, CSPGCL & CSPDCL - Notice dated 07.Aug.2026",
        {"SRNO": "1630", "FILE_NAME": "Recruitment Notice for Class III and IV Employees|Class_III.pdf"},
        {"SRNO": "1672", "FILE_NAME": "Corrigendum_2|CORRIGENDUM_2.pdf"},
        {"SRNO": "9", "LINK_NAME": "Apply online|cspc.co.in/apply"})), SRC.url, SRC)
    assert res.status == "ok" and len(res.items) == 3
    notice, corrigendum, link = res.items
    assert notice.title.endswith("– Recruitment Notice for Class III and IV Employees")
    assert notice.url == "https://escapi.cspdcl.co.in/api/api/recruitment/getFile/1630?download=false"
    assert notice.key == "cspdcl:1630" and not notice.docs and notice.url != notice.notice_url
    assert corrigendum.key == "cspdcl:1672"
    assert link.url == "https://cspc.co.in/apply"


def test_disabled_posts_and_bad_feeds():
    assert cspdcl.parse(_feed(_post("Old", {"SRNO": "1", "FILE_NAME": "a|a.pdf"}, enabled="0")),
                        SRC.url, SRC).status == "empty"
    assert cspdcl.parse("<html>maintenance</html>", SRC.url, SRC).status == "unrecognized"
