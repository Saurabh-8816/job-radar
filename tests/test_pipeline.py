"""End-to-end runs against saved pages, with the network and the clock stubbed out."""

from conftest import TODAY, district_source, fixture_text

from radar import pipeline
from radar.fetch import Response
from radar.store import Store

NEW_ROW = """
<tr><td>Recruitment of Data Entry Operator (Contractual) – Collector Office, Kondagaon</td>
<td><p>Recruitment of Data Entry Operator</p></td><td>24/10/2026</td><td>15/11/2026</td>
<td><span class="pdf-downloads"><a class="pdf-download-link" href="https://cdn.s3waas.gov.in/x/deo-2026.pdf">View (100 KB)</a></span></td></tr>
"""


def _run(monkeypatch, tmp_path, html, capsys):
    src = district_source("Kondagaon")
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, **kw: [src])
    monkeypatch.setattr(pipeline, "fetch_many", lambda urls, **kw: {u: Response(u, True, 200, text=html) for u in urls})
    monkeypatch.setattr(pipeline, "today_ist", lambda: TODAY)
    opts = pipeline.RunOptions(dry_run=True, read_docs=False, build_site=False, db_path=tmp_path / "t.db")
    stats = pipeline.run(opts)
    return stats, capsys.readouterr().out


def test_first_run_reports_open_matches_once(monkeypatch, tmp_path, capsys):
    html = fixture_text("kondagaon_recruitment.html")
    stats, out = _run(monkeypatch, tmp_path, html, capsys)
    assert stats["items_baseline"] >= 3 and stats["items_new"] == 0
    assert stats["alerts"] == 1                       # Assistant Programmer, closes 06/11 — still open
    assert "Assistant Programmer" in out and "13 days left" in out

    stats, out = _run(monkeypatch, tmp_path, html, capsys)   # same page again
    assert stats["items_new"] == 0 and stats["alerts"] == 0


def test_new_row_on_later_run_alerts(monkeypatch, tmp_path, capsys):
    html = fixture_text("kondagaon_recruitment.html")
    _run(monkeypatch, tmp_path, html, capsys)
    with_new = html.replace("</tbody>", NEW_ROW + "</tbody>", 1)
    assert with_new != html
    stats, out = _run(monkeypatch, tmp_path, with_new, capsys)
    assert stats["items_new"] == 1 and stats["alerts"] == 1
    assert "Data Entry Operator" in out and "22 days left" in out


def test_digest_skips_closed_notices_and_never_repeats(tmp_path):
    from radar import digest
    from radar.classify import Verdict
    from radar.models import Item

    store = Store(tmp_path / "d.db")
    src = district_source("Durg")
    store.sync_source(src)
    for title, deadline in [("Closed last week", "2026-10-20"), ("Closing tomorrow", "2026-10-25"),
                            ("Open next month", "2026-11-20")]:
        item = Item(source_id=src.id, title=title, url=f"https://x/{title}.pdf", notice_url=src.url,
                    docs=[("View", f"https://x/{title}.pdf")], end_date=deadline)
        row_id = store.insert_item(item, baseline=False)
        store.save_verdict(row_id, Verdict("new", "B", [], [], deadline))
    text, ids = digest.build(store, today=TODAY)
    assert "Closed last week" not in text
    assert text.count(">Closing tomorrow<") == 1   # visible link text, not the URL
    assert "Open next month" in text
    assert len(ids) == 3   # all marked digested, including the closed one


def _watch_page(n, prefix="Recruitment of Project Associate"):
    rows = "".join(f'<li><a href="/jobs/advt-{prefix[:3]}-{i}.pdf">{prefix} No. {i} (CSE)</a></li>' for i in range(n))
    return f"<html><body><ul>{rows}</ul></body></html>"


def _run_watch(monkeypatch, tmp_path, pages):
    from radar.models import Source
    srcs = [Source(id=f"inst-{n}", name=f"Institute {n}", kind="watch", url=f"https://inst{n}.ac.in/jobs",
                   group="academic", filter_jobs=True) for n in range(len(pages))]
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, **kw: srcs)
    monkeypatch.setattr(pipeline, "fetch_many", lambda urls, **kw: {
        u: Response(u, True, 200, text=pages[i]) for i, u in enumerate(urls)})
    monkeypatch.setattr(pipeline, "today_ist", lambda: TODAY)
    return pipeline.run(pipeline.RunOptions(dry_run=True, read_docs=False, build_site=False,
                                            db_path=tmp_path / "w.db"))


def test_link_format_churn_is_absorbed_and_flagged(monkeypatch, tmp_path):
    _run_watch(monkeypatch, tmp_path, [_watch_page(3)])                       # baseline
    stats = _run_watch(monkeypatch, tmp_path, [_watch_page(40, "Recruitment of Project Engineer")])
    assert stats["alerts"] == 0 and stats["items_new"] == 0
    assert stats["sources_churned"] == 1
    store = Store(tmp_path / "w.db")
    assert "absorbed" in store.unhealthy_sources()[0]["note"]


def test_a_few_new_links_still_alert(monkeypatch, tmp_path):
    _run_watch(monkeypatch, tmp_path, [_watch_page(3)])
    stats = _run_watch(monkeypatch, tmp_path, [_watch_page(5)])
    assert stats["items_new"] == 2 and stats["alerts"] == 2


def test_same_notice_on_two_institute_pages_alerts_once(monkeypatch, tmp_path):
    empty = "<html><body><p>none</p></body></html>"
    _run_watch(monkeypatch, tmp_path, [empty, empty])
    same = ('<html><body><li><a href="https://{h}/a.pdf">Walk-in interview for Project Associate-I '
            'in Computer Science, Advt 22/2026</a></li></body></html>')
    stats = _run_watch(monkeypatch, tmp_path, [same.format(h="one.in"), same.format(h="two.in")])
    assert stats["items_new"] == 2 and stats["duplicates"] == 1 and stats["alerts"] == 1


def test_failures_are_counted_for_health(monkeypatch, tmp_path):
    src = district_source("Kondagaon")
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, **kw: [src])
    monkeypatch.setattr(pipeline, "fetch_many",
                        lambda urls, **kw: {u: Response(u, False, error="ConnectionError") for u in urls})
    opts = pipeline.RunOptions(dry_run=True, read_docs=False, build_site=False, db_path=tmp_path / "f.db")
    for _ in range(3):
        pipeline.run(opts)
    store = Store(tmp_path / "f.db")
    unhealthy = store.unhealthy_sources()
    assert [s["id"] for s in unhealthy] == [src.id]
    assert unhealthy[0]["consecutive_failures"] == 3
