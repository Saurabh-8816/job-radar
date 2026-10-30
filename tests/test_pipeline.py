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


def test_alerts_stay_queued_when_telegram_is_not_configured(monkeypatch, tmp_path, capsys):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    src = district_source("Kondagaon")
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, **kw: [src])
    html = fixture_text("kondagaon_recruitment.html")
    monkeypatch.setattr(pipeline, "fetch_many", lambda urls, **kw: {u: Response(u, True, 200, text=html) for u in urls})
    monkeypatch.setattr(pipeline, "today_ist", lambda: TODAY)
    opts = pipeline.RunOptions(dry_run=False, read_docs=False, build_site=False, db_path=tmp_path / "q.db")
    pipeline.run(opts)
    assert "Telegram not configured" in capsys.readouterr().out
    store = Store(tmp_path / "q.db")
    assert len(store.alerts_due(TODAY.isoformat())) == 1     # still waiting, not lost

    monkeypatch.setattr(pipeline.Telegram, "_call", lambda self, method, **p: {"ok": True, "result": []})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    stats = pipeline.run(opts)                                # secrets fixed: it goes out now
    assert stats["alerts"] == 1
    assert Store(tmp_path / "q.db").alerts_due(TODAY.isoformat()) == []


def test_javascript_sources_go_through_the_browser(monkeypatch, tmp_path):
    from radar.models import Source
    from radar import render
    plain = Source(id="plain", name="Plain", kind="watch", url="https://plain.example/jobs", group="central")
    js = Source(id="nielit", name="NIELIT", kind="watch", url="https://www.nielit.gov.in/form?formName=Recruitments",
                group="central", render=True)
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, **kw: [plain, js])
    fetched, rendered = [], []
    monkeypatch.setattr(pipeline, "fetch_many", lambda urls, **kw: fetched.extend(urls) or {
        u: Response(u, True, 200, text="<p>none</p>") for u in urls})
    monkeypatch.setattr(render, "render_many", lambda urls, **kw: rendered.extend(urls) or {
        u: Response(u, True, 200, text='<li><a href="/blog?x=1">Walk in Interview for Consultant (IT)</a></li>')
        for u in urls})
    monkeypatch.setattr(pipeline, "today_ist", lambda: TODAY)
    stats = pipeline.run(pipeline.RunOptions(dry_run=True, read_docs=False, build_site=False,
                                             db_path=tmp_path / "r.db"))
    assert fetched == [plain.url] and rendered == [js.url]
    assert stats["items_baseline"] == 1


def test_without_a_browser_rendered_sources_fail_softly(monkeypatch):
    from radar import render
    monkeypatch.setattr(render, "available", lambda: False)
    out = render.render_many(["https://ssc.gov.in/"])
    assert not out["https://ssc.gov.in/"].ok and "pip install playwright" in out["https://ssc.gov.in/"].error


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


def test_source_moved_to_a_new_page_is_indexed_quietly_again(tmp_path):
    from dataclasses import replace
    store = Store(tmp_path / "m.db")
    src = district_source("Durg")
    store.sync_source(src)
    store.source_ok(src.id, "ok", 3, baselined=True)
    store.sync_source(src)                              # same page: stays baselined
    assert store.is_baselined(src.id)
    store.sync_source(replace(src, url="https://durg.gov.in/en/careers/"))
    assert not store.is_baselined(src.id)
