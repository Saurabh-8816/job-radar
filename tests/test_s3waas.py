from conftest import district_source, fixture_text

from radar.parsers import s3waas


def parse(fixture, district):
    src = district_source(district)
    return s3waas.parse(fixture_text(fixture), src.url, src)


def test_leading_serial_column_is_skipped():
    # CG State Legal Services Authority puts क्रमांक before the usual five columns.
    html = ("<table><tr><th>क्रमांक</th><th>Title</th><th>Description</th><th>Start Date</th>"
            "<th>End Date</th><th>File</th></tr><tr><td>1</td><td>Advertisement for Permanent Lok Adalat</td>"
            "<td></td><td>16/04/2025</td><td>12/05/2025</td><td><a href='/uploads/a.pdf'>View</a></td></tr></table>")
    src = district_source("Kondagaon")
    item = s3waas.parse(html, "https://chhattisgarh.nalsa.gov.in/notice-category/recruitments/", src).items[0]
    assert item.title == "Advertisement for Permanent Lok Adalat"
    assert (item.start_date, item.end_date) == ("2025-04-16", "2025-05-12")
    assert item.docs[0][1].endswith("/uploads/a.pdf")


def test_kondagaon_assistant_programmer_row():
    result = parse("kondagaon_recruitment.html", "Kondagaon")
    assert result.status == "ok"
    row = next(i for i in result.items if "Assistant Programmer" in i.title)
    assert row.start_date == "2026-10-14"
    assert row.end_date == "2026-11-06"
    assert len(row.docs) == 5
    labels = [label for label, _ in row.docs]
    assert "सहायक प्रोग्रामर भर्ती विज्ञापन" in labels      # size suffix "(600 KB)" stripped
    assert all(u.startswith("https://cdn.s3waas.gov.in/") for _, u in row.docs)
    assert row.key == row.docs[0][1].lower() or row.key.endswith(".pdf")


def test_raigarh_description_carries_post_names():
    result = parse("raigarh_recruitment.html", "Raigarh")
    row = next(i for i in result.items if "Assistant Programmer" in i.description)
    assert row.end_date == "2026-11-10"
    assert "Sarangarh-Bilaigarh" in row.description


def test_titles_are_clean():
    for item in parse("kondagaon_recruitment.html", "Kondagaon").items:
        assert "​" not in item.title and "  " not in item.title


def test_empty_hindi_category_is_healthy_not_broken():
    result = parse("balod_bharti_empty.html", "Balod")
    assert result.status == "empty"
    assert result.items == []


def test_unknown_layout_is_flagged():
    src = district_source("Nowhere")
    result = s3waas.parse("<html><body><h1>Maintenance</h1></body></html>", src.url, src)
    assert result.status == "unrecognized"


def test_keys_are_unique_per_page():
    for fx, d in [("kondagaon_recruitment.html", "Kondagaon"), ("raigarh_recruitment.html", "Raigarh"),
                  ("durg_recruitment.html", "Durg")]:
        keys = [i.key for i in parse(fx, d).items]
        assert len(keys) == len(set(keys)), fx
