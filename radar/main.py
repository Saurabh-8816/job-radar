"""Command line entry point.

  python -m radar.main run --runner cloud   # the 4-hourly GitHub job
  python -m radar.main relay --push         # laptop: fetch sites that block GitHub, push to data/inbox/
  python -m radar.main run --dry-run        # local test: print alerts instead of sending
  python -m radar.main run --only cg        # just Chhattisgarh sources (also: district, academic, durg…)
  python -m radar.main backtest --only cg   # treat every live notice as new: "what would alert today?"
  python -m radar.main digest [--dry-run]   # the 8 PM summary
  python -m radar.main dashboard            # rebuild site/index.html from the DB

Outside GitHub Actions, `run` and `digest` use data/dryrun.db unless --db is given:
the real data/jobs.db belongs to the workflow, and a locally modified copy would
block the laptop relay's `git pull`.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import DATA_DIR, DEFAULT_DB, dashboard, digest, relay
from .pipeline import RunOptions, run
from .store import Store

IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def _db(args, scratch: Path) -> Path:
    if args.db:
        return args.db
    return DEFAULT_DB if IN_ACTIONS and not getattr(args, "dry_run", False) else scratch


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Hindi titles on the Windows console

    ap = argparse.ArgumentParser(prog="radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "backtest"):
        p = sub.add_parser(name)
        p.add_argument("--only", help="comma list: state (cg), group (district, academic, psu…) or id fragment")
        p.add_argument("--runner", choices=["all", "cloud"], default="all",
                       help="cloud = skip sources only the laptop relay can reach")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--no-docs", action="store_true", help="skip reading advert PDFs")
        p.add_argument("--no-ocr", action="store_true")
        p.add_argument("--doc-limit", type=int, default=40, help="adverts to read per run")
        p.add_argument("--db", type=Path)
        p.add_argument("--no-site", action="store_true")
    r = sub.add_parser("relay")
    r.add_argument("--push", action="store_true", help="git pull first, then commit and push the inbox file")
    r.add_argument("--no-ocr", action="store_true")
    r.add_argument("--doc-limit", type=int, default=40)
    d = sub.add_parser("digest")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--db", type=Path)
    s = sub.add_parser("dashboard")
    s.add_argument("--db", type=Path)
    args = ap.parse_args(argv)

    if args.cmd in ("run", "backtest"):
        backtest = args.cmd == "backtest"
        if backtest and not args.db:
            db = Path(tempfile.mkdtemp(prefix="jobradar-")) / "backtest.db"
        else:
            db = _db(args, DATA_DIR / "dryrun.db")
        stats = run(RunOptions(
            only=args.only, dry_run=args.dry_run or backtest, read_docs=not args.no_docs,
            ocr=not args.no_ocr, all_new=backtest, doc_item_limit=args.doc_limit,
            build_site=not args.no_site and not backtest, db_path=db, runner=args.runner,
            ingest_inbox=not backtest))
        print("\nRun summary: " + ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
        print(f"(database: {db})")
    elif args.cmd == "relay":
        relay.collect(DEFAULT_DB, push=args.push, doc_limit=args.doc_limit, ocr=not args.no_ocr)
    elif args.cmd == "digest":
        n = digest.run(_db(args, DATA_DIR / "dryrun.db"), dry_run=args.dry_run)
        print(f"Digest covered {n} notices.")
    elif args.cmd == "dashboard":
        store = Store(args.db or DEFAULT_DB)
        print(f"Wrote {dashboard.build(store)}")
        store.close()


if __name__ == "__main__":
    main()
