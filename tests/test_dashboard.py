"""The dashboard web app: data built into the page, installable-app files beside it,
and the bot understanding the app's "sync" links."""

import json
import re

from conftest import TODAY, district_source

from radar import commands, dashboard
from radar.classify import Verdict
from radar.models import Item
from radar.store import Store


def _store(tmp_path):
    store = Store(tmp_path / "d.db")
    src = district_source("Durg")
    store.sync_source(src)
    item = Item(source_id=src.id, title="Recruitment of Assistant Programmer", url="https://x/ap.pdf",
                notice_url=src.url, docs=[("View", "https://x/ap.pdf")], end_date="2026-11-10")
    row_id = store.insert_item(item, baseline=False)
    store.save_verdict(row_id, Verdict("new", "A", ["Assistant Programmer"], ["advert p.2: …MCA…"], "2026-11-10"))
    store.set_meta("bot_username", "my_radar_bot")
    store.commit()
    return store, row_id


def test_app_page_has_data_and_install_files(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "today_ist", lambda: TODAY)
    store, row_id = _store(tmp_path)
    out = dashboard.build(store, tmp_path / "site")
    html = out.read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert data["bot"] == "my_radar_bot"
    item = data["items"][0]
    assert item["id"] == row_id and item["tier"] == "A" and item["area"] == "CG districts" and item["at"]
    assert data["health"]["total"] == 1
    for name in ("manifest.webmanifest", "sw.js", "icon-192.png", "icon-512.png", "icon-maskable-512.png"):
        assert (tmp_path / "site" / name).exists(), name
    sw = (tmp_path / "site" / "sw.js").read_text(encoding="utf-8")
    assert "__VERSION__" not in sw and data["updated"] in sw     # new cache per build
    manifest = json.loads((tmp_path / "site" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert {i["sizes"] for i in manifest["icons"]} >= {"192x192", "512x512"}


def test_a_title_cannot_break_out_of_the_data_block(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "today_ist", lambda: TODAY)
    store, row_id = _store(tmp_path)
    store.db.execute("UPDATE items SET title=? WHERE id=?", ("Post </script><script>alert(1)</script>", row_id))
    html = dashboard.build(store, tmp_path / "site").read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in html


def test_app_sync_links_work_as_bot_commands():
    for text, verb, item in (("/start star_12", "star", "12"), ("/start applied_7", "applied", "7"),
                             ("/hide_3", "hide", "3"), ("/start unhide_44", "unhide", "44")):
        m = commands._CMD.match(text)
        assert m and m.group(1) == verb and m.group(2) == item, text
    assert commands._CMD.match("/start") is None
