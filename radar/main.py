"""Command line entry point.

  python -m radar.main run                  # the 4-hourly job (used by GitHub Actions)
  python -m radar.main run --dry-run        # print alerts instead of sending; uses data/dryrun.db
  python -m radar.main run --only cg        # just Chhattisgarh sources (also: district, academic, durg…)
  python -m radar.main backtest --only cg   # treat every live notice as new: "what would alert today?"
  python -m radar.main digest [--dry-run]   # the 8 PM summary
  python -m radar.main dashboard            # rebuild site/index.html from the DB
"""

import argparse
import sys
import tempfile
from pathlib import Path

from . import DATA_DIR, DEFAULT_DB, dashboard, digest
from .pipeline import RunOptions, run
from .store import Store


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Hindi titles on the Windows console

    ap = argparse.ArgumentParser(prog="radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "backtest"):
        p = sub.add_parser(name)
        p.add_argument("--only", help="comma list: state (cg), group (district, academic, psu…) or id fragment")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--no-docs", action="store_true", help="skip reading advert PDFs")
        p.add_argument("--no-ocr", action="store_true")
        p.add_argument("--doc-limit", type=int, default=40, help="adverts to read per run")
        p.add_argument("--db", type=Path)
        p.add_argument("--no-site", action="store_true")
    d = sub.add_parser("digest")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--db", type=Path)
    s = sub.add_parser("dashboard")
    s.add_argument("--db", type=Path)
    args = ap.parse_args(argv)

    if args.cmd in ("run", "backtest"):
        backtest = args.cmd == "backtest"
        if args.db:
            db = args.db
        elif backtest:
            db = Path(tempfile.mkdtemp(prefix="jobradar-")) / "backtest.db"
        else:
            db = DATA_DIR / "dryrun.db" if args.dry_run else DEFAULT_DB
        stats = run(RunOptions(
            only=args.only, dry_run=args.dry_run or backtest, read_docs=not args.no_docs,
            ocr=not args.no_ocr, all_new=backtest, doc_item_limit=args.doc_limit,
            build_site=not args.no_site and not backtest, db_path=db))
        print("\nRun summary: " + ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
        if backtest:
            print(f"(backtest database: {db})")
    elif args.cmd == "digest":
        db = args.db or (DATA_DIR / "dryrun.db" if args.dry_run else DEFAULT_DB)
        n = digest.run(db, dry_run=args.dry_run)
        print(f"Digest covered {n} notices.")
    elif args.cmd == "dashboard":
        store = Store(args.db or DEFAULT_DB)
        print(f"Wrote {dashboard.build(store)}")
        store.close()


if __name__ == "__main__":
    main()
