"""SQLite state. The workflow commits data/jobs.db back to the repo after each run."""

import json
import sqlite3
from pathlib import Path

from .models import Item, Source
from .textutil import now_ist_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT, kind TEXT, url TEXT, state TEXT, district TEXT, grp TEXT, category TEXT,
    baselined INTEGER DEFAULT 0,
    last_run TEXT, last_ok TEXT, last_status TEXT, last_error TEXT,
    last_item_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    note TEXT                -- kept until the digest reports it (e.g. link-format churn)
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT, description TEXT, url TEXT, notice_url TEXT, docs TEXT,
    start_date TEXT, end_date TEXT, deadline TEXT,
    first_seen TEXT, last_seen TEXT,
    baseline INTEGER DEFAULT 0,
    kind TEXT DEFAULT 'new', tier TEXT DEFAULT 'B',
    matched TEXT DEFAULT '[]', reasons TEXT DEFAULT '[]',
    doc_status TEXT DEFAULT 'pending', doc_text TEXT DEFAULT '',
    dup_of INTEGER,
    notified_at TEXT, digested_at TEXT,
    user_status TEXT DEFAULT '', reminded TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS items_source ON items(source_id);
CREATE INDEX IF NOT EXISTS items_first_seen ON items(first_seen);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

DOC_TEXT_LIMIT = 8000   # keep the DB small enough to commit every run


class Store:
    def __init__(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(sources)")}
        if "note" not in cols:  # databases created before the column existed
            self.db.execute("ALTER TABLE sources ADD COLUMN note TEXT")

    def close(self):
        self.db.commit()
        self.db.close()

    def commit(self):
        self.db.commit()

    # ---- meta -------------------------------------------------------------
    def get_meta(self, k: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row["v"] if row else default

    def set_meta(self, k: str, v: str):
        self.db.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    # ---- sources ----------------------------------------------------------
    def sync_source(self, s: Source):
        self.db.execute(
            """INSERT INTO sources(id, name, kind, url, state, district, grp, category)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind, url=excluded.url,
                 state=excluded.state, district=excluded.district, grp=excluded.grp,
                 category=excluded.category""",
            (s.id, s.name, s.kind, s.url, s.state, s.district, s.group, s.category))

    def is_baselined(self, source_id: str) -> bool:
        row = self.db.execute("SELECT baselined FROM sources WHERE id=?", (source_id,)).fetchone()
        return bool(row and row["baselined"])

    def source_ok(self, source_id: str, status: str, count: int, baselined: bool):
        now = now_ist_iso()
        self.db.execute(
            """UPDATE sources SET last_run=?, last_ok=?, last_status=?, last_error=NULL,
               last_item_count=?, consecutive_failures=0, baselined=MAX(baselined, ?) WHERE id=?""",
            (now, now, status, count, int(baselined), source_id))

    def source_failed(self, source_id: str, error: str, status: str = "failed"):
        self.db.execute(
            """UPDATE sources SET last_run=?, last_status=?, last_error=?,
               consecutive_failures=consecutive_failures+1 WHERE id=?""",
            (now_ist_iso(), status, error, source_id))

    def flag_source(self, source_id: str, message: str):
        self.db.execute("UPDATE sources SET note=? WHERE id=?",
                        (f"{now_ist_iso()[:10]}: {message}", source_id))

    def clear_notes(self):
        self.db.execute("UPDATE sources SET note=NULL WHERE note IS NOT NULL")

    def unhealthy_sources(self, min_failures: int = 3):
        return self.db.execute(
            """SELECT * FROM sources WHERE consecutive_failures >= ? OR last_status='unrecognized'
                 OR note IS NOT NULL
               ORDER BY consecutive_failures DESC""", (min_failures,)).fetchall()

    def source_counts(self) -> dict:
        row = self.db.execute(
            """SELECT COUNT(*) AS total, SUM(last_status IN ('ok','empty')) AS healthy,
                      SUM(last_status='failed') AS failed FROM sources""").fetchone()
        return dict(row)

    # ---- items ------------------------------------------------------------
    def insert_item(self, item: Item, baseline: bool, doc_status: str = "pending",
                    doc_text: str = "") -> int | None:
        """Insert if unseen; returns the new row id, or None when already known."""
        now = now_ist_iso()
        cur = self.db.execute(
            """INSERT OR IGNORE INTO items(key, source_id, title, description, url, notice_url, docs,
                 start_date, end_date, deadline, first_seen, last_seen, baseline, doc_status, doc_text)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item.key, item.source_id, item.title, item.description, item.url, item.notice_url,
             json.dumps(item.docs, ensure_ascii=False), item.start_date, item.end_date,
             item.end_date, now, now, int(baseline),
             # documents to read, or a detail page to follow (watch links that aren't the page itself)
             doc_status if (item.docs or (item.url and item.url != item.notice_url)) else "none",
             (doc_text or "")[:DOC_TEXT_LIMIT]))
        if cur.rowcount:
            return cur.lastrowid
        self.db.execute("UPDATE items SET last_seen=? WHERE key=?", (now, item.key))
        return None

    def unknown_keys(self, keys) -> set[str]:
        keys = list(set(keys))
        known = set()
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = f"SELECT key FROM items WHERE key IN ({','.join('?' * len(chunk))})"
            known.update(r["key"] for r in self.db.execute(q, chunk))
        return set(keys) - known

    def recent_non_district(self, since_iso: str):
        return self.db.execute(
            """SELECT i.id, i.title, i.source_id FROM items i JOIN sources s ON s.id = i.source_id
               WHERE i.first_seen >= ? AND s.grp != 'district' AND i.dup_of IS NULL""",
            (since_iso,)).fetchall()

    def get(self, item_id: int):
        return self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()

    def save_verdict(self, item_id: int, verdict, doc_status: str | None = None, doc_text: str | None = None):
        sets = ["kind=?", "tier=?", "matched=?", "reasons=?", "deadline=?"]
        args = [verdict.kind, verdict.tier, json.dumps(verdict.matched, ensure_ascii=False),
                json.dumps(verdict.reasons, ensure_ascii=False), verdict.deadline]
        if doc_status is not None:
            sets.append("doc_status=?")
            args.append(doc_status)
        if doc_text is not None:
            sets.append("doc_text=?")
            args.append(doc_text[:DOC_TEXT_LIMIT])
        self.db.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", (*args, item_id))

    def pending_docs(self, limit: int, today_iso: str):
        """Items whose advert still needs reading. Fresh items first, then baseline backlog;
        skip anything already past its deadline."""
        return self.db.execute(
            """SELECT * FROM items WHERE doc_status='pending'
                 AND (deadline IS NULL OR deadline >= ?)
               ORDER BY baseline ASC, first_seen DESC LIMIT ?""", (today_iso, limit)).fetchall()

    def recent_titles(self, since_iso: str, exclude_source: str):
        return self.db.execute(
            """SELECT id, title FROM items WHERE first_seen >= ? AND source_id != ? AND dup_of IS NULL""",
            (since_iso, exclude_source)).fetchall()

    def mark_dup(self, item_id: int, of_id: int):
        self.db.execute("UPDATE items SET dup_of=? WHERE id=?", (of_id, item_id))

    def alerts_due(self, today_iso: str):
        """Tier-A vacancies not yet sent. Baseline items qualify only when they are
        provably still open (future deadline), so the first run reports jobs you can
        apply for today without replaying years of old links."""
        return self.db.execute(
            """SELECT * FROM items WHERE tier='A' AND kind='new' AND notified_at IS NULL
                 AND dup_of IS NULL AND user_status != 'hidden'
                 AND ((baseline=0 AND (deadline IS NULL OR deadline >= ?))
                      OR (baseline=1 AND deadline IS NOT NULL AND deadline >= ?))
               ORDER BY COALESCE(deadline, '9999') ASC""", (today_iso, today_iso)).fetchall()

    def mark_notified(self, item_id: int):
        self.db.execute("UPDATE items SET notified_at=? WHERE id=?", (now_ist_iso(), item_id))

    def open_matches(self, today_iso: str, baseline_only: bool = True):
        q = """SELECT * FROM items WHERE tier='A' AND kind='new' AND dup_of IS NULL
                 AND deadline IS NOT NULL AND deadline >= ?"""
        if baseline_only:
            q += " AND baseline=1"
        return self.db.execute(q + " ORDER BY deadline ASC", (today_iso,)).fetchall()

    def digest_items(self):
        return self.db.execute(
            """SELECT * FROM items WHERE baseline=0 AND digested_at IS NULL AND dup_of IS NULL
                 AND user_status != 'hidden'
               ORDER BY tier ASC, COALESCE(deadline, '9999') ASC""").fetchall()

    def mark_digested(self, ids):
        now = now_ist_iso()
        self.db.executemany("UPDATE items SET digested_at=? WHERE id=?", [(now, i) for i in ids])

    def closing_soon(self, today_iso: str, until_iso: str):
        return self.db.execute(
            """SELECT * FROM items WHERE tier IN ('A','B') AND kind='new' AND dup_of IS NULL
                 AND user_status NOT IN ('hidden','applied')
                 AND deadline BETWEEN ? AND ?
               ORDER BY deadline ASC, tier ASC""", (today_iso, until_iso)).fetchall()

    def set_user_status(self, item_id: int, status: str) -> bool:
        cur = self.db.execute("UPDATE items SET user_status=? WHERE id=?", (status, item_id))
        return bool(cur.rowcount)

    def dashboard_rows(self, since_iso: str, today_iso: str):
        """Notices that appeared since `since`, plus anything still open. Baseline items
        without a deadline (years of archived links on careers pages) are left out."""
        return self.db.execute(
            """SELECT i.*, s.name AS source_name, s.state, s.district, s.grp
               FROM items i JOIN sources s ON s.id = i.source_id
               WHERE i.dup_of IS NULL
                 AND ((i.baseline = 0 AND i.first_seen >= ?) OR i.deadline >= ?)
               ORDER BY i.first_seen DESC""", (since_iso, today_iso)).fetchall()

    def source_of(self, source_id: str):
        return self.db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
