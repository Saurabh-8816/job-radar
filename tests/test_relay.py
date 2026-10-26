"""Laptop relay → inbox file → GitHub run, with the network and clock stubbed out."""

import pytest
from conftest import TODAY

from radar import digest, pipeline, relay
from radar.fetch import Response
from radar.models import Source
from radar.store import Store

VYAPAM = Source(id="cg-vyapam", name="CG Vyapam", kind="watch", url="https://vyapamcg.cgstate.gov.in/",
                state="CG", group="cg-state", filter_jobs=True, runner="local")


def page(n):
    rows = "".join(f'<li><a href="/Post?PostID=AP{i}">Recruitment of Assistant Programmer, advt {i}</a></li>'
                   for i in range(n))
    return f"<html><body><ul>{rows}<li><a href='/about'>About us</a></li></ul></body></html>"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(relay, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(relay, "CACHE", tmp_path / "relay_cache.json")
    monkeypatch.setattr(pipeline, "today_ist", lambda: TODAY)
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, runner=None: [])  # GitHub reaches nothing itself
    monkeypatch.setattr(relay, "read_item_docs", lambda *a, **kw: ("", "none"))      # no detail-page fetches
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    db = tmp_path / "jobs.db"

    def laptop(html=None, error=None):
        resp = (lambda u: Response(u, True, 200, text=html)) if html else (lambda u: Response(u, False, error=error))
        monkeypatch.setattr(relay, "fetch_many", lambda urls, **kw: {u: resp(u) for u in urls})
        return relay.collect(db, push=False, sources=[VYAPAM], ocr=False)

    def github():
        return pipeline.run(pipeline.RunOptions(read_docs=False, build_site=False, db_path=db, runner="cloud"))

    return laptop, github, db


def test_first_contact_is_indexed_silently(env):
    laptop, github, db = env
    path = laptop(page(5))
    assert path.exists()
    stats = github()
    assert stats["inbox_files"] == 1 and stats["items_baseline"] == 5 and stats["alerts"] == 0
    assert not path.exists()                          # consumed and deleted
    assert Store(db).get_meta("relay_last")


def test_new_posts_found_by_laptop_alert_from_github(env, capsys):
    laptop, github, db = env
    laptop(page(5))
    github()
    capsys.readouterr()
    path = laptop(page(7))                            # two new posts on Vyapam
    import json
    shipped = json.loads(path.read_text(encoding="utf-8"))["sources"][0]["items"]
    assert len(shipped) == 2                          # only what GitHub doesn't already have
    stats = github()
    out = capsys.readouterr().out
    assert stats["items_new"] == 2 and stats["alerts"] == 2
    assert "advt 5" in out and "advt 6" in out


def test_laptop_does_not_reship_before_github_ingests(env):
    laptop, github, db = env
    laptop(page(5))
    github()
    laptop(page(6))                                   # ships advt 5
    second = laptop(page(6))                          # GitHub hasn't run yet
    import json
    assert json.loads(second.read_text(encoding="utf-8"))["sources"][0]["items"] == []


def test_laptop_failure_is_reported_for_health(env):
    laptop, github, db = env
    laptop(error="ConnectTimeout")
    github()
    row = Store(db).source_of("cg-vyapam")
    assert row["consecutive_failures"] == 1 and "from laptop" in row["last_error"]


def test_laptop_never_modifies_the_shared_database(env):
    laptop, github, db = env
    laptop(page(3))
    github()
    before = db.read_bytes()
    laptop(page(4))
    assert db.read_bytes() == before                  # a changed jobs.db would block `git pull`


def test_laptop_takes_over_sources_github_cannot_reach(monkeypatch, tmp_path):
    from radar.models import Source
    durg = Source(id="cg-durg-recruitment", name="Durg district", kind="s3waas",
                  url="https://durg.gov.in/en/notice_category/recruitment/", group="district")
    korba = Source(id="cg-korba-recruitment", name="Korba district", kind="s3waas",
                   url="https://korba.gov.in/en/notice_category/recruitment/", group="district")
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, runner=None: [durg, korba])
    monkeypatch.setattr(relay, "load_sources",
                        lambda runner=None: [VYAPAM] if runner == "local" else [durg, korba])
    monkeypatch.setattr(pipeline, "fetch_many", lambda urls, **kw: {
        u: (Response(u, False, error="ConnectTimeout") if "durg" in u else Response(u, True, 200, text="<p>No notices found</p>"))
        for u in urls})
    db = tmp_path / "jobs.db"
    pipeline.run(pipeline.RunOptions(read_docs=False, build_site=False, db_path=db, runner="cloud", dry_run=True))
    picked = [s.id for s in relay.select_sources(db)]
    assert picked == ["cg-vyapam", "cg-durg-recruitment"]          # Korba works from GitHub: not relayed

    store = Store(db)
    assert store.cloud_streaks()["cg-durg-recruitment"] == 1
    store.close()


def test_blocked_sites_get_only_a_quick_retry(monkeypatch, tmp_path):
    from radar.models import Source
    durg = Source(id="cg-durg-recruitment", name="Durg district", kind="s3waas",
                  url="https://durg.gov.in/en/notice_category/recruitment/", group="district")
    monkeypatch.setattr(pipeline, "load_sources", lambda only=None, runner=None: [durg])
    calls = []
    monkeypatch.setattr(pipeline, "fetch_many", lambda urls, **kw: calls.append((list(urls), kw)) or {
        u: Response(u, False, error="ConnectTimeout") for u in urls})
    db = tmp_path / "jobs.db"
    for _ in range(4):
        pipeline.run(pipeline.RunOptions(read_docs=False, build_site=False, db_path=db, runner="cloud", dry_run=True))
    last_run = calls[-2:]                                      # (normal batch, quick-retry batch)
    assert last_run[0][0] == [] and last_run[1][0] == [durg.url]
    assert last_run[1][1]["timeout"] == 8 and last_run[1][1]["retries"] == 0


def test_digest_warns_when_laptop_is_silent(tmp_path):
    text, _ = digest.build(Store(tmp_path / "d.db"), today=TODAY)
    assert "laptop hasn't checked in" in text
