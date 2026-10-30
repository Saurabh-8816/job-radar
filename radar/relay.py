"""Laptop relay for sites that block GitHub's (non-Indian) servers.

The laptop fetches only `runner: local` sources, reads new adverts (with OCR), and
pushes the result as a small JSON file in data/inbox/. The next GitHub run ingests
those files exactly like pages it fetched itself, so classification, alerts, the
digest and the dashboard stay in one place. The laptop only reads jobs.db (a copy of
the `state` branch) and never needs the Telegram token. New files only, so git never
conflicts.

    python -m radar.main relay --push     # what the Windows scheduled task runs
"""

import gzip
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
from . import render
from .fetch import fetch_many
from .models import Item, Source
from .parsers import parse
from .sources import due, load_sources
from .textutil import IST, now_ist, now_ist_iso

INBOX = DATA_DIR / "inbox"
CACHE = DATA_DIR / "relay_cache.json"      # keys already shipped (local only, git-ignored)
CACHE_DAYS = 10
SHIP_TEXT_LIMIT = 120_000   # full advert text travels to GitHub; only the DB copy is trimmed


# ---- laptop side --------------------------------------------------------------

def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def load_state():
    """Latest database and dashboard from the `state` branch (tools/state.sh). Both are
    git-ignored here, so refreshing them never gets in the way of `git pull`."""
    if _git("fetch", "-q", "origin", "state").returncode != 0:
        print("  no state branch to read; using the local copy")
        return

    def show(name):
        out = subprocess.run(["git", "show", f"FETCH_HEAD:{name}"], cwd=ROOT, capture_output=True)
        return out.stdout if out.returncode == 0 else None

    packed = show("jobs.db.gz")
    db = gzip.decompress(packed) if packed is not None else show("jobs.db")   # older state: uncompressed
    for data, dest in ((db, DEFAULT_DB), (show("index.html"), ROOT / "site" / "index.html")):
        if data is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)


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


def cloud_blocked_ids(db_path: Path) -> set[str]:
    """Sources GitHub failed to fetch on its last run (read-only)."""
    if not Path(db_path).exists():
        return set()
    db = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        return {r[0] for r in db.execute("SELECT id FROM sources WHERE cloud_fail_streak >= 1")}
    except sqlite3.OperationalError:   # database from before the column existed
        return {r[0] for r in db.execute("SELECT id FROM sources WHERE last_status = 'failed'")}
    finally:
        db.close()


def _last_runs(db_path: Path) -> dict[str, str]:
    if not Path(db_path).exists():
        return {}
    db = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        return {r[0]: r[1] for r in db.execute("SELECT id, last_run FROM sources WHERE last_run IS NOT NULL")}
    finally:
        db.close()


def select_sources(db_path: Path = DEFAULT_DB) -> list[Source]:
    """`runner: local` sources, plus any GitHub source that GitHub couldn't reach last
    time (NIC blocks GitHub for some district sites, SarkariResult answers it 403...).
    No manual list: if a site starts blocking GitHub, the laptop picks it up next run.
    Twice-a-day / daily sources (the bulk directory lists) wait until they're due."""
    blocked = cloud_blocked_ids(db_path)
    picked = load_sources(runner="local") + [s for s in load_sources(runner="cloud") if s.id in blocked]
    return due(picked, _last_runs(db_path), now_ist(), limit=400)


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
            ocr: bool = True, sources: list[Source] | None = None,
            time_budget: int = 900) -> Path | None:
    if push:
        pulled = _git("pull", "--rebase", "--autostash", "-q")
        if pulled.returncode != 0:
            print("git pull failed; not relaying this time:\n" + pulled.stderr.strip())
            return None
        load_state()

    sources = sources if sources is not None else select_sources(db_path)
    if not sources:
        print("Nothing to relay: GitHub currently reaches every source.")
        return None
    known, baselined = _read_state(db_path, [s.id for s in sources])
    cache = _load_cache()
    clf = Classifier.load()

    fallback = sum(1 for s in sources if s.runner != "local")
    print(f"Relay: fetching {len(sources)} sources GitHub can't reach "
          f"({len(sources) - fallback} laptop-only, {fallback} GitHub is failing on)...")
    responses = fetch_many([s.url for s in sources if not s.render], timeout=25)
    responses.update(render.render_many([s.url for s in sources if s.render]))
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
            text, status = result.texts.get(item.key, ("", None))
            row = {**asdict(item), "doc_text": text[:SHIP_TEXT_LIMIT], "doc_status": status}
            entry["items"].append(row)
            if status:          # the source already supplied the advert text
                continue
            if (item.docs or item.url != item.notice_url) and not first_contact:
                to_read.append(row)

    # GitHub can't fetch these sites' adverts itself, so a notice is only shipped once its
    # advert has been read here. Anything over the limit or the time budget waits for the
    # next relay run (it isn't cached, so it's picked up again).
    later = to_read[doc_limit:]
    to_read = to_read[:doc_limit]
    if to_read:
        print(f"  reading {len(to_read)} new adverts, every page...")
        deadline = time.monotonic() + time_budget

        def read(row):
            docs = [tuple(d) for d in row["docs"]]
            page = row["url"] if not docs and row["url"] != row["notice_url"] else None
            return read_item_docs(docs, clf, ocr, page_url=page, deadline=deadline)

        with ThreadPoolExecutor(max_workers=3) as pool:
            for row, (text, status) in zip(to_read, pool.map(read, to_read)):
                if status == "deferred":
                    later.append(row)
                else:
                    row["doc_text"], row["doc_status"] = text[:SHIP_TEXT_LIMIT], status
    if later:
        held = {id(r) for r in later}
        for e in entries:
            e["items"] = [r for r in e["items"] if id(r) not in held]
        print(f"  {len(later)} adverts left for the next relay run")

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
    print(f"  {ok}/{len(entries)} sources answered, {shipped} new notices -> {path.name}")

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
