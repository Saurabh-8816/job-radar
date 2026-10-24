"""Static dashboard: site/index.html with the data embedded (works from disk or Cloudflare Pages)."""

import json
from datetime import timedelta
from pathlib import Path

from . import SITE_DIR
from .textutil import now_ist_iso, today_ist

TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"
WINDOW_DAYS = 120

AREA = {
    "district": "CG districts", "cg-state": "CG state", "central": "Central govt",
    "academic": "Institutes", "psu": "PSUs & banks", "state-board": "Neighbour states",
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
            "deadline": r["deadline"], "seen": (r["first_seen"] or "")[:10],
            "kind": r["kind"], "tier": r["tier"], "matched": json.loads(r["matched"] or "[]")[:8],
            "reasons": json.loads(r["reasons"] or "[]"), "doc": r["doc_status"],
            "status": r["user_status"] or "",
        })
    payload = json.dumps({"updated": now_ist_iso(), "items": items}, ensure_ascii=False)
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload.replace("</", "<\\/"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out
