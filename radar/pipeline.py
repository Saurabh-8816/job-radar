"""One radar run: fetch → parse → store → read adverts → classify → alert → dashboard."""

import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from rapidfuzz import fuzz, process

from . import DEFAULT_DB, commands, dashboard
from .classify import Classifier
from .fetch import fetch_many, get
from .notify import Telegram, format_alert, format_line
from .parsers import parse
from .pdftext import extract, ocr_languages
from .sources import load_sources
from .store import Store
from .textutil import today_ist

_FORM_LABEL = re.compile(r"आवेदन\s*(प्रारूप|पत्र|फार्म|फॉर्म)|प्रारूप|application\s*form|format|proforma", re.I)
_ADVERT_LABEL = re.compile(r"विज्ञापन|भर्ती|advertis|advt|notification|recruit|vacanc|view", re.I)
_READABLE = (".pdf", ".jpg", ".jpeg", ".png")
MAX_INDIVIDUAL_ALERTS = 10
CHURN_LIMIT = 25


@dataclass
class RunOptions:
    only: str | None = None
    dry_run: bool = False
    read_docs: bool = True
    ocr: bool = True
    all_new: bool = False          # backtest: treat every item as new (use with a scratch DB)
    doc_item_limit: int = 40       # adverts read per run; the rest wait for the next run
    workers: int = 16
    build_site: bool = True
    db_path: Path = DEFAULT_DB


def run(opts: RunOptions) -> Counter:
    clf = Classifier.load()
    store = Store(opts.db_path)
    tg = Telegram(opts.dry_run)
    today = today_ist()
    stats = Counter()

    commands.process(tg, store)
    sources = load_sources(opts.only)
    for s in sources:
        store.sync_source(s)
    store.commit()

    print(f"Fetching {len(sources)} sources…")
    started = time.monotonic()
    responses = fetch_many([s.url for s in sources], workers=opts.workers, timeout=25)
    print(f"  fetched in {time.monotonic() - started:.0f}s")

    new_ids, baselined_now = [], []
    for s in sources:
        r = responses[s.url]
        if not r.ok:
            store.source_failed(s.id, r.error or "fetch failed")
            stats["sources_failed"] += 1
            continue
        result = parse(s, r.text, s.url)
        if result.status == "unrecognized":
            store.source_failed(s.id, "page layout not recognised", status="unrecognized")
            stats["sources_unrecognized"] += 1
            continue
        items = result.items
        if s.filter_jobs:
            items = [i for i in items if clf.is_job_related(f"{i.title} {i.description} {i.url}")]
        baseline = not opts.all_new and not store.is_baselined(s.id)
        churn = None
        if not baseline and s.kind == "watch":
            unseen = len(store.unknown_keys(i.key for i in items))
            if unseen > CHURN_LIMIT:
                # A real careers page never posts dozens of notices between two runs; this is
                # the site changing its link format. Absorb silently and flag it for review.
                baseline, churn = True, f"{unseen} links changed at once; absorbed without alerts"
        for item in items:
            doc_status = "skipped" if (baseline and s.kind == "watch") else "pending"
            row_id = store.insert_item(item, baseline, doc_status)
            if row_id:
                new_ids.append(row_id)
                stats["items_baseline" if baseline else "items_new"] += 1
        store.source_ok(s.id, result.status, len(items), baselined=True)
        if churn:
            store.flag_source(s.id, churn)
            stats["sources_churned"] += 1
        stats["sources_ok"] += 1
        if baseline and not churn:
            baselined_now.append(s)
    store.commit()

    for row_id in new_ids:  # first pass on the listing text alone
        _classify(store, clf, store.get(row_id), today)
    store.commit()

    if opts.read_docs:
        stats.update(read_documents(store, clf, opts, today))
    stats["duplicates"] = _dedupe(store, new_ids)
    store.commit()

    stats["alerts"] = send_alerts(store, tg, today)
    if baselined_now:
        _baseline_note(tg, baselined_now, stats)
    if opts.build_site:
        dashboard.build(store)
    store.close()
    return stats


def _classify(store, clf, row, today, body="", body_status=None, save_doc=False):
    verdict = clf.classify(row["title"], row["description"] or "", body,
                           row["end_date"], body_status, today)
    if save_doc:
        store.save_verdict(row["id"], verdict, doc_status=body_status, doc_text=body)
    else:
        store.save_verdict(row["id"], verdict)
    return verdict


def _rank_docs(docs: list, clf: Classifier) -> list:
    """Adverts first (labels naming a matching post, then advert words); forms last."""
    def score(doc):
        label, url = doc
        s = 0
        if clf.strong.first(label) or clf.weak.first(label):
            s += 3
        if _ADVERT_LABEL.search(label):
            s += 1
        if _FORM_LABEL.search(label):
            s -= 5
        return -s
    readable = [d for d in docs if d[1].lower().split("?")[0].endswith(_READABLE)]
    return sorted(readable, key=score)[:3]


def read_documents(store, clf, opts: RunOptions, today) -> Counter:
    rows = store.pending_docs(opts.doc_item_limit, today.isoformat())
    if not rows:
        return Counter()
    print(f"Reading adverts for {len(rows)} items (OCR: {ocr_languages() or 'unavailable'})…")
    clf_docs = clf

    def work(row):
        texts, statuses = [], []
        for _label, url in _rank_docs(json.loads(row["docs"] or "[]"), clf_docs):
            resp = get(url, binary=True, max_bytes=10_000_000, timeout=45, retries=1, total_timeout=90)
            if not resp.ok:
                statuses.append("error")
                continue
            doc = extract(resp.content, url, ocr=opts.ocr)
            statuses.append(doc.status)
            if doc.status in ("text", "ocr"):
                texts.append(doc.text)
        if texts:
            status = "ocr" if "ocr" in statuses else "text"
        elif "unreadable" in statuses:
            status = "unreadable"
        else:
            status = "error" if statuses else "none"
        return row, "\n".join(texts), status

    counts = Counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row, text, status in pool.map(work, rows):
            _classify(store, clf, row, today, text, status, save_doc=True)
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
