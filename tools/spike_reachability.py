"""Phase 0: which sources answer from this machine? Prints a Markdown report.

Run it on GitHub Actions (reachability-spike workflow) and on your laptop, then
compare: sources that work locally but fail in the cloud are blocking foreign IPs.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar.fetch import fetch_many  # noqa: E402
from radar.sources import load_sources  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sources = load_sources(include_disabled=True)  # retest sites that failed from the laptop
    results = fetch_many([s.url for s in sources], workers=8, timeout=25, retries=1)
    by_group = Counter()
    rows = []
    for s in sources:
        r = results[s.url]
        ok = r.ok
        by_group[(s.group, ok)] += 1
        rows.append((ok, s.group, s.name, s.url, r.status, round(r.elapsed, 1), r.error or ("insecure TLS" if r.insecure else "")))

    total_ok = sum(1 for r in rows if r[0])
    print(f"## Reachability: {total_ok}/{len(rows)} sources answered\n")
    print("| Group | OK | Failed |\n|---|---|---|")
    for g in sorted({s.group for s in sources}):
        print(f"| {g} | {by_group[(g, True)]} | {by_group[(g, False)]} |")
    print("\n### Failures\n\n| Group | Source | Status | Seconds | Error |\n|---|---|---|---|---|")
    for ok, group, name, url, status, secs, err in sorted(rows):
        if not ok:
            print(f"| {group} | [{name}]({url}) | {status or '-'} | {secs} | {err} |")


if __name__ == "__main__":
    main()
