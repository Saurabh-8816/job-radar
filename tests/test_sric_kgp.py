from conftest import fixture_text
from radar.models import Source
from radar.parsers import sric_kgp

SRC = Source(id="iit-kharagpur-sric-temporary-jobs", name="IIT KGP SRIC", kind="sric_kgp",
             url="https://erp.iitkgp.ac.in/SricWeb/viewTemporaryJobDetails.htm")


def test_feed_records_become_classifiable_notices(clf):
    items = sric_kgp.parse(fixture_text("kgp_sric.json"), SRC.url, SRC).items
    cse = next(i for i in items if "Computer Science" in i.title)
    assert cse.end_date and cse.key.startswith("kgpsric:IIT/SRIC/")
    assert cse.url.startswith("https://erp.iitkgp.ac.in/SRICStaffRecruitment/Login.jsp?ref_no=")
    assert "MCA" in cse.description
    assert clf.classify(cse.title, cse.description, "").tier == "A"


def test_html_is_unrecognized():
    assert sric_kgp.parse("<html></html>", SRC.url, SRC).status == "unrecognized"
