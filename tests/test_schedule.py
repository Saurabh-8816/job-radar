"""The bulk directory lists (all central bodies / PSUs, all Kendriya Vidyalayas): checked
on their own schedule, a capped number per run, far-away KVs alert only clear matches."""

from datetime import datetime, timedelta

import yaml
from conftest import TODAY

from radar import pipeline, sources
from radar.fetch import Response
from radar.models import Source
from radar.store import Store
from radar.textutil import IST

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=IST)


def _src(sid, every=0):
    return Source(id=sid, name=sid, kind="watch", url=f"https://{sid}.gov.in/", every_hours=every)


def _ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat(timespec="seconds")


def test_scheduled_sources_wait_until_due():
    srcs = [_src("always"), _src("fresh", 12), _src("stale", 12), _src("almost", 12), _src("never", 12)]
    last = {"always": _ago(1), "fresh": _ago(3), "stale": _ago(13), "almost": _ago(11.7)}
    assert [s.id for s in sources.due(srcs, last, NOW)] == ["always", "never", "stale", "almost"]


def test_a_new_bulk_list_spreads_over_several_runs():
    srcs = [_src("regular")] + [_src(f"kv{i}", 24) for i in range(10)]
    picked = sources.due(srcs, {}, NOW, limit=4)
    assert [s.id for s in picked] == ["regular", "kv0", "kv1", "kv2", "kv3"]


def test_bulk_list_schedules_and_far_kvs_are_quiet(monkeypatch, tmp_path):
    (tmp_path / "watch_kv.yaml").write_text(yaml.safe_dump([
        {"id": "kv-bhilai", "name": "KV Bhilai", "url": "https://bhilai.kvs.ac.in/recruitment/", "group": "kv", "state": "CG"},
        {"id": "kv-agra", "name": "KV Agra", "url": "https://agra.kvs.ac.in/recruitment/", "group": "kv", "state": "UP"},
    ]), encoding="utf-8")
    (tmp_path / "watch_igod.yaml").write_text(yaml.safe_dump([
        {"id": "iffco", "name": "IFFCO", "url": "https://www.iffco.in/en/careers", "group": "psu"},
    ]), encoding="utf-8")
    monkeypatch.setattr(sources, "SOURCES_DIR", tmp_path)
    got = {s.id: s for s in sources.load_sources()}
    assert got["kv-bhilai"].every_hours == 12 and got["kv-bhilai"].digest
    assert not got["kv-agra"].digest
    assert got["iffco"].every_hours == 6 and got["iffco"].digest


KV_PAGE = """<table class="documents-table"><tr><th>Name</th><th>Published On</th><th>View</th></tr>
<tr><td>Walk-in interview for contractual teachers 2026-27 (TGT Hindi, PRT)</td><td>10/29/26</td>
<td><a href="https://agra.kvs.ac.in/uploads/walkin.pdf">View</a></td></tr></table>"""


def test_far_kv_partial_match_is_stored_without_digest(monkeypatch, tmp_path):
    src = Source(id="kv-agra", name="KV Agra", kind="watch", url="https://agra.kvs.ac.in/recruitment/",
                 state="UP", group="kv", selector="table.documents-table", filter_jobs=False,
                 every_hours=24, digest=False)
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, **kw: [src])
    monkeypatch.setattr(pipeline, "today_ist", lambda: TODAY)
    empty = KV_PAGE.split("<tr><td>")[0] + "</table>"
    for html in (empty, KV_PAGE):
        monkeypatch.setattr(pipeline, "fetch_many", lambda urls, html=html, **kw: {u: Response(u, True, 200, text=html) for u in urls})
        monkeypatch.setattr(pipeline, "due", lambda srcs, last, now: srcs)
        pipeline.run(pipeline.RunOptions(dry_run=True, read_docs=False, build_site=False, db_path=tmp_path / "t.db"))
    row = Store(tmp_path / "t.db").db.execute("SELECT tier, reasons FROM items").fetchone()
    assert row["tier"] == "C" and "far-away" in row["reasons"]
