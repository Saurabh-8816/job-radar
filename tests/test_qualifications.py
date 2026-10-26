"""BCA, B.Sc IT/CS, MCA, M.Sc IT/CS, B.Tech/M.Tech CSE/IT, B.E./M.E. CS, and the
spelled-out "Bachelor's/Master's in Computer Science / Computer Applications" are
one qualification as far as this profile is concerned: any of them in an advert
is a tier-A match, wherever it appears in the advert and however it's written."""

import pytest
from conftest import TODAY

PHRASES = [
    # abbreviations, with and without dots/spaces/brackets
    "BCA", "B.C.A.", "B.C.A", "MCA", "M.C.A.", "M. C. A.", "BCA/MCA", "B.C.A./M.C.A.",
    "B.Sc. (IT)", "B.Sc IT", "BSc IT", "B.Sc. (Computer Science)", "B.Sc. Computer Science", "BSc CS",
    "M.Sc. (IT)", "M.Sc IT", "MSc IT", "M.Sc. (Computer Science)", "M.Sc. (CS)", "MSc Computer Science",
    "B.Tech (CSE)", "B.Tech. (Computer Science & Engineering)", "B.Tech in IT", "BTech CSE",
    "M.Tech (CSE)", "M.Tech. (Computer Science)", "M.Tech in Information Technology", "MTech IT",
    "B.E. (Computer Science)", "BE (CSE)", "M.E. (Computer Engineering)", "B.E./B.Tech (IT)",
    "M.Sc in IT", "M.Sc. in Computer Science", "B.E. in Information Technology", "M.Tech in CSE",
    "B.Sc.-IT", "M.Sc.(IT)",
    # spelled out
    "Bachelor of Computer Applications", "Bachelor's degree in Computer Applications",
    "Master of Computer Applications", "Master's degree in Computer Applications",
    "Bachelor's degree in Computer Science", "Graduation in Computer Science",
    "Master's degree in Computer Science", "Masters in Computer Science",
    "Master of Science (Information Technology)", "Post Graduation in Computer Application",
    "Bachelor of Technology in Information Technology",
    "Bachelors in Computer Science", "bachelors computer science", "Bachelor in Computer Science",
    "Bachelor's in Computer Science", "BACHELORS COMPUTER SCIENCE", "bachelors in computer applications",
    "bachelors computer applications", "Masters Computer Science", "masters in computer applications",
    "masters computer applications", "Master's in Computer Applications",
    # Hindi
    "एम.सी.ए.", "बी.सी.ए.", "एमसीए", "बीसीए", "कम्प्यूटर साइंस में स्नातक", "कंप्यूटर साइंस",
    "सूचना प्रौद्योगिकी में बी.ई./बी.टेक", "कम्प्यूटर एप्लीकेशन में स्नातकोत्तर", "कंप्यूटर एप्लीकेशन",
    "एम.एस-सी. (कम्प्यूटर साइंस)", "एम.टेक (कम्प्यूटर साइंस)",
]


@pytest.mark.parametrize("phrase", PHRASES)
def test_qualification_in_title_is_tier_a(clf, phrase):
    v = clf.classify(f"Recruitment of Assistant (Contract) - qualification {phrase}", "", "", None, None, TODAY)
    assert v.tier == "A", (phrase, v.matched)


@pytest.mark.parametrize("phrase", PHRASES)
def test_qualification_deep_in_advert_is_tier_a(clf, phrase):
    body = "\f".join(["General instructions for candidates."] * 9 + [f"Essential qualification: {phrase} from a recognised university."])
    v = clf.classify("Advertisement for various contractual posts", "", body, None, "text", TODAY)
    assert v.tier == "A", (phrase, v.matched)


@pytest.mark.parametrize("text", [
    "B.Sc. (Agriculture) from a recognised university",
    "M.Sc. (Nursing)",
    "B.Tech (Civil Engineering)",       # civil is matched separately, by the civil rule
    "Bachelor of Commerce",
    "it is mandatory to attach a self attested copy",
])
def test_other_degrees_are_not_mistaken_for_computing(clf, text):
    v = clf.classify("Recruitment of Assistant", "", text, None, "text", TODAY)
    assert not any(m.lower() in ("bca", "mca", "it", "computer science") for m in v.matched), v.matched


@pytest.mark.parametrize("text", [
    "Be it a graduate or a post-graduate, candidates must apply online",
    "The selected candidate will be in it for two years",
])
def test_english_be_it_is_not_a_degree(clf, text):
    assert clf.classify("Recruitment of Assistant", "", text, None, "text", TODAY).tier != "A"
