"""Dashboard web app: site/index.html with the data built in, plus what makes it an
installable app (manifest, service worker, icons). Opens from disk as a plain page;
served over https (GitHub Pages) it installs on a phone and works offline."""

import json
import shutil
from datetime import timedelta
from pathlib import Path

from . import SITE_DIR
from .notify import Telegram
from .textutil import now_ist_iso, today_ist

TEMPLATES = Path(__file__).parent / "templates"
TEMPLATE = TEMPLATES / "dashboard.html"
STATIC = TEMPLATES / "static"
WINDOW_DAYS = 120
UNHEALTHY_SHOWN = 60

AREA = {
    "district": "CG districts", "cg-state": "CG state", "central": "Central govt",
    "academic": "Institutes", "psu": "PSUs & banks", "state-board": "State boards",
    "aggregator": "Aggregator", "kv": "Kendriya Vidyalayas",
}


def build(store, out_dir: Path = SITE_DIR) -> Path:
    today = today_ist()
    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    items = []
    for r in store.dashboard_rows(since, today.isoformat()):
        items.append({
            "id": r["id"], "title": r["title"], "desc": (r["description"] or "")[:300],
            "url": r["url"], "page": r["notice_url"], "docs": json.loads(r["docs"] or "[]")[:6],
            "source": r["source_name"], "district": r["district"], "state": r["state"],
            "area": AREA.get(r["grp"], r["grp"] or "Other"),
            "deadline": r["deadline"], "seen": (r["first_seen"] or "")[:10], "at": r["first_seen"] or "",
            "kind": r["kind"], "tier": r["tier"], "matched": json.loads(r["matched"] or "[]")[:8],
            "reasons": json.loads(r["reasons"] or "[]"), "doc": r["doc_status"],
            "status": r["user_status"] or "",
        })
    updated = now_ist_iso()
    payload = json.dumps({"updated": updated, "bot": bot_username(store), "health": _health(store),
                          "items": items}, ensure_ascii=False)
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload.replace("</", "<\\/"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    for f in STATIC.iterdir():
        if f.name == "sw.js":   # a new cache name per build, so phones pick up the new page
            (out_dir / f.name).write_text(f.read_text(encoding="utf-8").replace("__VERSION__", updated),
                                          encoding="utf-8")
        else:
            shutil.copyfile(f, out_dir / f.name)
    return out


def bot_username(store) -> str | None:
    """For the app's "sync to bot" links (t.me/<bot>?start=star_12). Asked once, then kept."""
    name = store.get_meta("bot_username")
    if not name:
        name = Telegram(dry_run=True).username()   # dry_run: no "not configured" warning here
        if name:
            store.set_meta("bot_username", name)
            store.commit()
    return name


def _health(store) -> dict:
    counts = store.source_counts()
    unhealthy = []
    for s in store.unhealthy_sources()[:UNHEALTHY_SHOWN]:
        if s["note"]:
            problem = s["note"]
        else:
            problem = f"{s['last_error'] or s['last_status']} · {s['consecutive_failures']} checks in a row"
        unhealthy.append({"name": s["name"], "url": s["url"], "problem": problem})
    return {"total": counts["total"] or 0, "healthy": counts["healthy"] or 0, "failed": counts["failed"] or 0,
            "relay_last": store.get_meta("relay_last"), "unhealthy": unhealthy}
