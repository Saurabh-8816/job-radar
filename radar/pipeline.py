"""One radar run: fetch → parse → store → read adverts → classify → alert → dashboard.

Pages from sites that block GitHub arrive as inbox files from the laptop relay and
go through the same `_ingest` path as pages fetched here.
"""

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from rapidfuzz import fuzz, process

from . import DEFAULT_DB, commands, dashboard, relay, render
from .classify import Classifier
from .docs import read_item_docs
from .fetch import fetch_many
from .notify import Telegram, format_alert, format_line
from .parsers import parse
from .pdftext import ocr_languages
from .sources import due, load_sources
from .store import Store
from .textutil import now_ist, today_ist

MAX_INDIVIDUAL_ALERTS = 10



@dataclass
class RunOptions:
    only: str | None = None
    dry_run: bool = False
    read_docs: bool = True
    ocr: bool = True
    all_new: bool = False          # backtest: treat every item as new (use with a scratch DB)
    doc_item_limit: int = 40       # adverts read per run; the rest wait for the next run
    doc_time_budget: int = 600     # seconds of advert reading (mostly OCR) per run; leftovers wait
    workers: int = 32               # different sites, so many at once is polite enough
    build_site: bool = True
    db_path: Path = DEFAULT_DB
    runner: str = "all"            # "cloud" on GitHub: skip sources only the laptop can reach
    ingest_inbox: bool = True


@dataclass
class _Run:
    store: Store
    clf: Classifier
    opts: RunOptions
    stats: Counter = field(default_factory=Counter)
    new_ids: list = field(default_factory=list)
    baselined_now: list = field(default_factory=list)
    full_text: dict = field(default_factory=dict)   # row id -> relay advert text before DB truncation
    quiet: set = field(default_factory=set)         # sources whose partial matches skip the digest


def run(opts: RunOptions) -> Counter:
    ctx = _Run(Store(opts.db_path), Classifier.load(), opts)
    store, clf, stats = ctx.store, ctx.clf, ctx.stats
    tg = Telegram(opts.dry_run)
    today = today_ist()

    commands.process(tg, store)
    _backfill_deadlines(store, clf, today)
    sources = load_sources(opts.only, runner=None if opts.runner == "all" else opts.runner)
    ctx.quiet = {s.id for s in sources if not s.digest}
    sources = due(sources, store.last_runs(), now_ist())
    for s in sources:
        store.sync_source(s)
    store.commit()

    # Sites that have refused GitHub for 3+ runs get one quick attempt (the laptop relay
    # is covering them); normal sites get the full timeout. Keeps dead sites cheap.
    # The bulk directory lists get one short try too: there are thousands, many NIC-hosted
    # ones refuse GitHub, and a site missed now is simply due again next run.
    streaks = store.cloud_streaks()
    blocked = {s.url for s in sources if streaks.get(s.id, 0) >= 3}
    bulk = {s.url for s in sources if s.every_hours} - blocked
    rendered = [s for s in sources if s.render]
    plain = [s for s in sources if not s.render]
    print(f"Fetching {len(sources)} sources ({len(bulk)} from the bulk lists, {len(blocked)} quick retries "
          f"of sites blocking GitHub, {len(rendered)} JavaScript sites in a browser)…")
    started = time.monotonic()
    responses = fetch_many([s.url for s in plain if s.url not in blocked and s.url not in bulk],
                           workers=opts.workers, timeout=25)
    responses.update(fetch_many([s.url for s in plain if s.url in bulk],
                                workers=opts.workers, timeout=12, retries=0, total_timeout=20))
    responses.update(fetch_many([s.url for s in plain if s.url in blocked],
                                workers=opts.workers, timeout=8, retries=0, total_timeout=12))
    responses.update(render.render_many([s.url for s in rendered if s.url not in blocked]))
    responses.update(render.render_many([s.url for s in rendered if s.url in blocked], timeout=12))
    print(f"  fetched in {time.monotonic() - started:.0f}s")
    for s in sources:
        r = responses[s.url]
        store.cloud_result(s.id, r.ok)
        if not r.ok:
            store.source_failed(s.id, r.error or "fetch failed")
            stats["sources_failed"] += 1
            continue
        result = parse(s, r.text, s.url)
        _ingest(ctx, s, result.status, result.items, result.texts)

    if opts.ingest_inbox:
        _ingest_inbox(ctx)
    store.commit()

    for row_id in ctx.new_ids:  # first pass: listing text, plus advert text the relay sent
        row = store.get(row_id)
        body = ctx.full_text.get(row_id) or row["doc_text"] or ""
        _classify(store, clf, row, today, body, row["doc_status"] if body else None, quiet=ctx.quiet)
    store.commit()

    if opts.read_docs:
        stats.update(read_documents(store, clf, opts, today, ctx.quiet))
    stats["duplicates"] = _dedupe(store, ctx.new_ids)
    store.commit()

    stats["alerts"] = send_alerts(store, tg, today)
    if ctx.baselined_now:
        _baseline_note(tg, ctx.baselined_now, stats)
    if opts.build_site:
        dashboard.build(store)
    store.close()
    return stats


def _ingest(ctx: _Run, s, status: str, items, doc_texts: dict | None = None):
    store, stats = ctx.store, ctx.stats
    if status == "unrecognized":
        store.source_failed(s.id, "page layout not recognised", status="unrecognized")
        stats["sources_unrecognized"] += 1
        return
    if s.filter_jobs:
        items = [i for i in items if ctx.clf.is_job_related(f"{i.title} {i.description} {i.url}")]
    if s.region_filter:
        items = [i for i in items if ctx.clf.in_region(i.title)]
    baseline = not ctx.opts.all_new and not store.is_baselined(s.id)
    churn = None
    if not baseline and s.kind == "watch":
        unseen = len(store.unknown_keys(i.key for i in items))
        if unseen > s.churn_limit:
            # A careers page never posts dozens of notices between two runs (aggregators
            # get a higher per-source limit); this is the site changing its link format.
            # Absorb silently and flag it for review.
            baseline, churn = True, f"{unseen} links changed at once; absorbed without alerts"
    for item in items:
        text, doc_status = (doc_texts or {}).get(item.key, ("", None))
        if doc_status is None:
            doc_status = "skipped" if (baseline and s.kind == "watch") else "pending"
        row_id = store.insert_item(item, baseline, doc_status, doc_text=text)
        if row_id:
            ctx.new_ids.append(row_id)
            if text:
                ctx.full_text[row_id] = text
            stats["items_baseline" if baseline else "items_new"] += 1
    store.source_ok(s.id, status, len(items), baselined=True)
    if churn:
        store.flag_source(s.id, churn)
        stats["sources_churned"] += 1
    stats["sources_ok"] += 1
    if baseline and not churn:
        ctx.baselined_now.append(s)


def _ingest_inbox(ctx: _Run):
    done = []
    for path, generated, entries in relay.load_inbox():
        for source, status, error, items, doc_texts in entries:
            ctx.store.sync_source(source)
            if not source.digest:
                ctx.quiet.add(source.id)
            if status == "failed":
                ctx.store.source_failed(source.id, f"from laptop: {error or 'fetch failed'}")
                ctx.stats["sources_failed"] += 1
            else:
                _ingest(ctx, source, status, items, doc_texts)
        if generated and generated > (ctx.store.get_meta("relay_last") or ""):
            ctx.store.set_meta("relay_last", generated)
        ctx.stats["inbox_files"] += 1
        done.append(path)
    ctx.store.commit()
    if not ctx.opts.dry_run:
        for path in done:
            path.unlink()


def _backfill_deadlines(store, clf, today):
    """One-off: deadlines written in words ("15th November, 2026") weren't recognised
    before; re-read them from the advert text already stored. Runs once."""
    if store.get_meta("deadline_backfill") == "words-v1":
        return
    since = (today - timedelta(days=60)).isoformat()
    rows = store.db.execute(
        """SELECT id, title, description, doc_text, end_date FROM items
           WHERE deadline IS NULL AND kind='new' AND tier IN ('A','B') AND first_seen >= ?""", (since,)).fetchall()
    found = 0
    for r in rows:
        d = clf._deadline(r["doc_text"] or "", r["end_date"], today, f"{r['title']} {r['description'] or ''}")
        if d:
            store.db.execute("UPDATE items SET deadline=? WHERE id=?", (d, r["id"]))
            found += 1
    store.set_meta("deadline_backfill", "words-v1")
    store.commit()
    print(f"Deadline backfill: {found} of {len(rows)} undated notices got a last date")


def _classify(store, clf, row, today, body="", body_status=None, save_doc=False, quiet=()):
    verdict = clf.classify(row["title"], row["description"] or "", body,
                           row["end_date"], body_status, today)
    if verdict.tier == "B" and row["source_id"] in quiet:
        # e.g. a KV walk-in in another state: kept on the dashboard, alerted only if it's a clear match
        verdict.tier = "C"
        verdict.reasons.append("far-away school: only computer posts are alerted")
    if save_doc:
        store.save_verdict(row["id"], verdict, doc_status=body_status, doc_text=body)
    else:
        store.save_verdict(row["id"], verdict)
    return verdict


def read_documents(store, clf, opts: RunOptions, today, quiet=()) -> Counter:
    rows = store.pending_docs(opts.doc_item_limit, today.isoformat())
    if not rows:
        return Counter()
    print(f"Reading adverts for {len(rows)} items, every page (OCR: {ocr_languages() or 'unavailable'})…")
    deadline = time.monotonic() + opts.doc_time_budget

    def work(row):
        docs = json.loads(row["docs"] or "[]")
        # A notice that's only a link to a detail page: read that page and its PDFs.
        page_url = row["url"] if (not docs and row["url"] and row["url"] != row["notice_url"]) else None
        text, status = read_item_docs(docs, clf, opts.ocr, page_url=page_url, deadline=deadline)
        return row, text, status

    counts = Counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row, text, status in pool.map(work, rows):
            if status == "deferred":      # time budget spent: stays pending for the next run
                counts["docs_deferred"] += 1
                continue
            _classify(store, clf, row, today, text, status, save_doc=True, quiet=quiet)
            counts[f"docs_{status}"] += 1
    store.commit()
    return counts


def _dedupe(store, new_ids) -> int:
    """Same notice reached through two non-district pages (e.g. an institute's
    'careers' and 'news' pages). District notices are never merged: two districts
    posting near-identical titles are two different jobs. Baseline items are skipped:
    they never alert, so merging them buys nothing."""
    fresh = [store.get(i) for i in new_ids]
    fresh = [r for r in fresh if not r["baseline"] and len(r["title"]) >= 25]
    if not fresh:
        return 0
    since = (today_ist() - timedelta(days=14)).isoformat()
    recent = store.recent_non_district(since)   # includes items inserted earlier this run
    dups = 0
    for row in fresh:
        candidates = [o for o in recent if o["source_id"] != row["source_id"] and o["id"] < row["id"]]
        if not candidates:
            continue
        match = process.extractOne(row["title"].casefold(), [c["title"].casefold() for c in candidates],
                                   scorer=fuzz.ratio, score_cutoff=97)
        if match:
            store.mark_dup(row["id"], candidates[match[2]]["id"])
            dups += 1
    return dups


def send_alerts(store, tg: Telegram, today) -> int:
    rows = store.alerts_due(today.isoformat())
    if not rows:
        return 0
    if len(rows) > MAX_INDIVIDUAL_ALERTS:
        lines = [f"<b>{len(rows)} matching jobs open right now</b>"]
        lines += [format_line(r, store.source_of(r["source_id"]), today) for r in rows]
        lines.append("\nReply /star_ID, /applied_ID or /hide_ID with the number after #.")
        if tg.send("\n".join(lines)):
            for r in rows:
                store.mark_notified(r["id"])
    else:
        for r in rows:
            if tg.send(format_alert(r, store.source_of(r["source_id"]), today)):
                store.mark_notified(r["id"])
            if tg.live:
                time.sleep(1.1)  # stay under Telegram's per-chat rate limit
    store.commit()
    return len(rows)


def _baseline_note(tg, sources, stats):
    names = ", ".join(s.name for s in sources[:6]) + (" …" if len(sources) > 6 else "")
    tg.send(f"<b>Job Radar: now watching {len(sources)} new source(s)</b>\n"
            f"{names}\nIndexed {stats['items_baseline']} existing notices. "
            "Older notices stay quiet; anything still open that matches was sent above.")
