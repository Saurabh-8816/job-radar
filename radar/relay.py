"""Laptop relay for sites that block GitHub's (non-Indian) servers.

The laptop fetches only `runner: local` sources, reads new adverts (with OCR), and
pushes the result as a small JSON file in data/inbox/. The next GitHub run ingests
those files exactly like pages it fetched itself, so classification, alerts, the
digest and the dashboard stay in one place. The laptop never writes jobs.db and
never needs the Telegram token. New files only, so git never conflicts.

    python -m radar.main relay --push     # what the Windows scheduled task runs
"""

import json
import socket
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import DATA_DIR, DEFAULT_DB, ROOT
from .classify import Classifier
from .docs import read_item_docs
from .fetch import fetch_many
from .models import Item, Source
from .parsers import parse
from .sources import load_sources
from .textutil import IST, now_ist_iso

INBOX = DATA_DIR / "inbox"
CACHE = DATA_DIR / "relay_cache.json"      # keys already shipped (local only, git-ignored)
CACHE_DAYS = 10


# ---- laptop side --------------------------------------------------------------

def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _read_state(db_path: Path, source_ids) -> tuple[set, set]:
    """Keys GitHub already has and sources it has baselined, read-only so the
    laptop's copy of jobs.db never changes (that would block `git pull`)."""
    if not Path(db_path).exists():
        return set(), set()
    db = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        ids = list(source_ids)
        marks = ",".join("?" * len(ids)) or "''"
        keys = {r[0] for r in db.execute(f"SELECT key FROM items WHERE source_id IN ({marks})", ids)}
        based = {r[0] for r in db.execute(f"SELECT id FROM sources WHERE baselined=1 AND id IN ({marks})", ids)}
        return keys, based
    finally:
        db.close()


def _load_cache() -> dict:
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cutoff = time.time() - CACHE_DAYS * 86400
    return {k: t for k, t in data.items() if t >= cutoff}


def _save_cache(cache: dict):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")


def collect(db_path: Path = DEFAULT_DB, push: bool = False, doc_limit: int = 40,
            ocr: bool = True, sources: list[Source] | None = None) -> Path | None:
    if push:
        pulled = _git("pull", "--rebase", "--autostash", "-q")
        if pulled.returncode != 0:
            print("git pull failed; not relaying this time:\n" + pulled.stderr.strip())
            return None

    sources = sources if sources is not None else load_sources(runner="local")
    if not sources:
        print("No sources are marked `runner: local`.")
        return None
    known, baselined = _read_state(db_path, [s.id for s in sources])
    cache = _load_cache()
    clf = Classifier.load()

    print(f"Relay: fetching {len(sources)} sources GitHub can't reach…")
    responses = fetch_many([s.url for s in sources], timeout=25)
    entries, to_read = [], []
    for s in sources:
        r = responses[s.url]
        entry = {"source": asdict(s), "status": "failed", "error": r.error, "items": []}
        entries.append(entry)
        if not r.ok:
            continue
        result = parse(s, r.text, s.url)
        entry.update(status=result.status, error=None)
        items = result.items
        if s.filter_jobs:
            items = [i for i in items if clf.is_job_related(f"{i.title} {i.description} {i.url}")]
        if s.region_filter:
            items = [i for i in items if clf.in_region(i.title)]
        first_contact = s.id not in baselined   # GitHub indexes these silently; no need to read adverts
        for item in items:
            if item.key in cache or (item.key in known and not first_contact):
                continue
            row = {**asdict(item), "doc_text": "", "doc_status": None}
            entry["items"].append(row)
            if item.docs and not first_contact:
                to_read.append(row)

    to_read = to_read[:doc_limit]
    if to_read:
        print(f"  reading {len(to_read)} new adverts…")
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row, (text, status) in zip(to_read, pool.map(
                    lambda r: read_item_docs([tuple(d) for d in r["docs"]], clf, ocr), to_read)):
                row["doc_text"], row["doc_status"] = text[:8000], status

    INBOX.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y%m%dT%H%M%S")
    path = INBOX / f"relay-{socket.gethostname().lower()}-{stamp}.json"
    payload = {"generated": now_ist_iso(), "host": socket.gethostname(), "sources": entries}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    shipped = sum(len(e["items"]) for e in entries)
    ok = sum(e["status"] != "failed" for e in entries)
    now = time.time()
    for e in entries:
        for row in e["items"]:
            cache[Item(**_item_fields(row)).key] = now
    _save_cache(cache)
    print(f"  {ok}/{len(entries)} sources answered, {shipped} new notices → {path.name}")

    if push:
        _push(path)
    return path


def _push(path: Path):
    rel = path.relative_to(ROOT).as_posix()
    _git("add", rel)
    commit = _git("commit", "-q", "-m", f"relay: {path.stem} [skip ci]")
    if commit.returncode != 0:
        print("git commit failed:\n" + commit.stderr.strip())
        return
    for attempt in range(3):
        pushed = _git("push", "-q")
        if pushed.returncode == 0:
            print("  pushed to GitHub")
            return
        _git("pull", "--rebase", "--autostash", "-q")   # GitHub committed meanwhile; inbox files never conflict
        time.sleep(3 * (attempt + 1))
    print("git push failed; the file stays committed locally and goes up next time:\n" + pushed.stderr.strip())


# ---- GitHub side --------------------------------------------------------------

def _item_fields(row: dict) -> dict:
    fields = {k: row.get(k) for k in Item.__dataclass_fields__}
    fields["docs"] = [tuple(d) for d in (row.get("docs") or [])]
    fields["description"] = fields.get("description") or ""
    return fields


def load_inbox():
    """Yield (path, generated_at, [(Source, status, error, items, doc_texts)])."""
    for path in sorted(INBOX.glob("*.json")) if INBOX.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"  skipping unreadable inbox file {path.name}: {e}")
            continue
        entries = []
        for e in payload.get("sources", []):
            source = Source(**e["source"])
            items, doc_texts = [], {}
            for row in e.get("items", []):
                item = Item(**_item_fields(row))
                items.append(item)
                if row.get("doc_status"):
                    doc_texts[item.key] = (row.get("doc_text") or "", row["doc_status"])
            entries.append((source, e.get("status", "failed"), e.get("error"), items, doc_texts))
        yield path, payload.get("generated"), entries
