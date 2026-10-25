import pytest
from conftest import TODAY, fixture_text


def classify(clf, title, desc="", body="", end=None, status=None):
    return clf.classify(title, desc, body, end, status, TODAY)


# ---- the three real examples that motivated the project ------------------------

def test_kondagaon_title_is_tier_a(clf):
    v = classify(clf, "Recruitment – For the posts of Programme Officer, Assistant Programmer, and "
                      "Accountant – Office of the District Panchayat, Kondagaon (Chhattisgarh)", end="2026-11-06")
    assert (v.kind, v.tier) == ("new", "A")
    assert v.deadline == "2026-11-06"


def test_raigarh_generic_title_matches_via_description(clf):
    v = classify(clf, "Vacancy | Office of the District Panchayat, Raigarh",
                 "Three posts of Assistant Programmer for Janpad Panchayat in Raigarh district")
    assert v.tier == "A"


def test_durg_generic_title_is_promoted_by_ocr_text(clf):
    title = "Office of the District Panchayat, Durg (Chhattisgarh) – Advertisement"
    assert classify(clf, title).tier == "B"
    v = classify(clf, title, body=fixture_text("durg_advert_ocr.txt"), end="2026-10-30", status="ocr")
    assert v.tier == "A"
    assert "प्रोग्रामर" in v.matched


def test_kondagaon_ocr_text_matches_in_hindi(clf):
    v = classify(clf, "विज्ञापन", body=fixture_text("kondagaon_advert_ocr.txt"), status="ocr")
    assert v.tier == "A"


@pytest.mark.parametrize("title", [
    "VB-GRAM G, recruitment for various posts",
    "Advertisement for contractual recruitment on various posts under Vikasit Bharat-Ji Ram-Ji",
    "Office of the District Panchayat, Korba Viksit Bharat Guarantee Mission for Employment",
    "Recruitment – Advertisement for various posts under VB-G Ram-G",
])
def test_statewide_drive_spellings(clf, title):
    assert classify(clf, title).tier == "A"


# ---- updates vs new vacancies ----------------------------------------------------

@pytest.mark.parametrize("title", [
    "Office of the Chief Medical and Health Officer, District Durg: Merit list for the skill test",
    "Selection-cum-Waiting List of Candidates for the Posts of Block Project Manager",
    "List regarding the resolution of claims and objections, and the list of eligible candidates",
    "Corrigendum-cum-Revised Selection List for Panchayat Secretary Recruitment",
    "// Notice of Advertisement Cancellation //",
    "Regarding the extension of the date for the recruitment of 05 Accountant posts",
    "Recruitment – Appointment order of selected candidates under National Health Mission",
    "सहायक प्रोग्रामर पद हेतु दावा आपत्ति निराकरण सूची",
])
def test_updates_are_not_new_vacancies(clf, title):
    assert classify(clf, title).kind == "update"


def test_update_about_matching_post_is_still_an_update(clf):
    v = classify(clf, "Publication of results following the computer proficiency test for Assistant Programmer")
    assert v.kind == "update"


# ---- tiers ----------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Recruitment of Data Entry Operator (Contractual)",
    "Walk-in interview for Project Associate-I in Computer Science and Engineering",
    "Advertisement for Junior Research Fellow (JRF) in a DST project on machine learning",
    "Guest faculty in Computer Science for session 2026-27",
    "Sub Engineer (Civil) recruitment 2026",
    "भर्ती विज्ञापन – कम्प्यूटर ऑपरेटर",
    "Recruitment of IT Assistant on contract basis",
    "Scientist 'B' recruitment at NIELIT",
])
def test_profile_posts_are_tier_a(clf, title):
    assert classify(clf, title).tier == "A"


def test_ocr_noise_is_not_a_project_post(clf):
    body = "NRLM ... Ra 2 ... कम्प्यूटर ज्ञान अनिवार्य ... pa 1"
    assert classify(clf, "Advertisement for NRLM contractual posts", body=body).tier == "B"
    assert classify(clf, "Walk-in for RA-II in computer vision").tier == "A"


def test_research_post_outside_computing_goes_to_digest(clf):
    v = classify(clf, "Project Associate-I in Organic Chemistry")
    assert v.tier == "B"


def test_weak_term_only_in_pdf_is_not_tier_a(clf):
    body = "Accountant post. Candidates must have basic computer knowledge and typing skills."
    assert classify(clf, "Recruitment of Accountant", body=body).tier == "B"


def test_word_it_in_lowercase_is_not_information_technology(clf):
    body = "Research associate in sociology. It is a temporary position and it ends in March."
    assert classify(clf, "Research Associate (Sociology)", body=body).tier == "B"


def test_any_graduate_goes_to_digest(clf):
    assert classify(clf, "Recruitment of Block Coordinator", body="Qualification: any graduate").tier == "B"


@pytest.mark.parametrize("title", [
    "Vacancy for the recruitment of a Physical Education Teacher on an honorarium basis",
    "Recruitment of Staff Nurse and ANM under NHM",
    "Advertisement for the post of Driver and Peon",
])
def test_other_domain_posts_are_tier_c(clf, title):
    assert classify(clf, title).tier == "C"


def test_panchayat_secretary_is_not_buried(clf):
    # Permanent CG post open to graduates: digest, not tier C.
    assert classify(clf, "Advertisement for recruitment of Gram Panchayat Secretary").tier == "B"


def test_unreadable_advert_is_flagged_for_manual_check(clf):
    v = classify(clf, "Office of the District Panchayat", status="unreadable")
    assert v.tier == "B"
    assert any("check manually" in r for r in v.reasons)


# ---- deadlines ------------------------------------------------------------------

def test_deadline_from_text_before_date(clf):
    v = classify(clf, "Advertisement", body="Last date for receipt of applications: 15/11/2026.")
    assert v.deadline == "2026-11-15"


def test_deadline_from_hindi_tak(clf):
    v = classify(clf, "विज्ञापन", body="आवेदन दिनांक 06/11/2026 तक कार्यालयीन समय में स्वीकार किये जायेंगे")
    assert v.deadline == "2026-11-06"


def test_earlier_of_listing_and_advert_deadline_wins(clf):
    v = classify(clf, "Advertisement", body="Last date: 05/11/2026", end="2026-11-30")
    assert v.deadline == "2026-11-05"


def test_old_reference_dates_are_not_deadlines(clf):
    v = classify(clf, "Advertisement", body="letter dated 05.08.2025 तक", end="2026-11-06")
    assert v.deadline == "2026-11-06"


def test_job_word_filter_for_announcements(clf):
    assert clf.is_job_related("Advertisement for recruitment to vacant contractual posts")
    assert clf.is_job_related("रिक्त पदों पर संविदा भर्ती हेतु विज्ञापन")
    assert clf.is_job_related("UP Police Constable Online Form 2026")      # aggregator wording
    assert not clf.is_job_related("Information regarding vacant Nazul land in Raipur district")
    assert not clf.is_job_related("Uploading of the Awaas Plus list under Pradhan Mantri Awas Yojana")
