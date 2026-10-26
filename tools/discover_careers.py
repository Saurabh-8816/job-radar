"""Find each organisation's careers page and write sources/watch_pages.yaml.

Usage:  python tools/discover_careers.py [name-filter] [--render] [--timeout=N]

--render opens pages in a headless browser, for sites built by JavaScript.

For each entry in sources/candidates.yaml: fetch the homepage, follow links that
look like careers/recruitment pages, and keep the page with the most job-related
links. Pinned `url:` entries are only validated. Unreachable sites are written
with `enabled: false` so they're visible in the file and easy to retry later.
"""

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar import SOURCES_DIR  # noqa: E402
from radar.classify import Classifier  # noqa: E402
from radar import render  # noqa: E402
from radar.fetch import get  # noqa: E402
from radar.models import Source  # noqa: E402
from radar.parsers import watch  # noqa: E402

CAREER_LINK = re.compile(
    r"career|recruit|vacanc|job|employment|opportunit|positions|openings|advertisement|"
    r"भर्ती|रिक्ति|रिक्त", re.I)
NOT_CAREER = re.compile(
    r"placement|student|alumni|internship|admission|coaching|finishing|higher[\s-]*stud|"
    r"career[\s_-]*(center|centre|development|guidance|counsel)", re.I)

clf = Classifier.load()


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


TIMEOUT = 25
RENDER = False   # --render: open pages in a headless browser (JavaScript-built sites)


def _fetch(url: str):
    if RENDER:
        return render.render_many([url], timeout=TIMEOUT)[url]
    return get(url, timeout=TIMEOUT, retries=1)


def score_page(url: str) -> tuple[int, str | None]:
    r = _fetch(url)
    if not r.ok:
        return -1, r.error
    src = Source(id="probe", name="probe", kind="watch", url=url)
    items = watch.parse(r.text, url, src).items
    return sum(clf.is_job_related(f"{i.title} {i.description} {i.url}") for i in items), None


def candidate_links(home: str) -> list[str]:
    r = _fetch(home)
    if not r.ok:
        return []
    host = urlsplit(r.url if hasattr(r, "url") else home).netloc
    found = []
    for a in BeautifulSoup(r.text, "lxml").find_all("a", href=True):
        text = " ".join(a.get_text(" ").split())
        href = urljoin(home, a["href"].strip())
        if not href.startswith("http") or href.lower().endswith(".pdf"):
            continue
        blob = f"{text} {href}"
        if CAREER_LINK.search(blob) and not NOT_CAREER.search(blob):
            same_site = urlsplit(href).netloc.split(".")[-3:] == host.split(".")[-3:]
            if same_site or "career" in href.lower():
                found.append(href)
    return list(dict.fromkeys(found))[:6]


def discover(entry: dict) -> dict:
    name, home = entry["name"], entry["home"]
    out = {"id": _slug(name), "name": name, "group": entry.get("group", "central"),
           "state": entry.get("state", "IN")}
    if entry.get("url"):
        score, err = score_page(entry["url"])
        out.update(url=entry["url"], job_links=max(score, 0))
        if score < 0:
            out.update(enabled=False, note=f"unreachable: {err}")
        return out

    best_url, best_score = None, -1
    home_score, home_err = score_page(home)
    if home_score >= 0:
        best_url, best_score = home, home_score
    for link in candidate_links(home):
        score, _ = score_page(link)
        if score > best_score or (score == best_score and best_url == home and score > 0):
            best_url, best_score = link, score
    if best_url is None:
        out.update(url=home, job_links=0, enabled=False, note=f"unreachable: {home_err}")
    else:
        out.update(url=best_url, job_links=best_score)
        if best_score == 0:
            out["note"] = "no job links found yet (page may be built with JavaScript); review"
    return out


def main():
    global TIMEOUT, RENDER
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for a in sys.argv[1:]:
        if a.startswith("--timeout="):
            TIMEOUT = int(a.split("=", 1)[1])
        elif a == "--render":
            RENDER = True
    # Filter: comma-separated names (exact, case-insensitive) or a single substring.
    flt = args[0].lower() if args else ""
    names = {n.strip() for n in flt.split(",")} if "," in flt else None
    entries = [e for e in yaml.safe_load((SOURCES_DIR / "candidates.yaml").read_text(encoding="utf-8"))
               if (e["name"].lower() in names if names else flt in e["name"].lower())]
    with ThreadPoolExecutor(max_workers=3 if RENDER else 8) as pool:
        results = list(pool.map(discover, entries))
    if RENDER:
        for r in results:
            r["render"] = True
    for r in results:
        flag = "OFF" if r.get("enabled") is False else f"{r['job_links']:>3}"
        print(f"  {flag}  {r['name'][:38]:38} {r['url']}")
    out = SOURCES_DIR / "watch_pages.yaml"
    if flt and out.exists():  # partial run: merge into the existing file
        existing = {e["id"]: e for e in yaml.safe_load(out.read_text(encoding="utf-8")) or []}
        for r in results:  # keep hand-set fields (runner, churn_limit, region_filter...)
            existing[r["id"]] = {**existing.get(r["id"], {}), **r}
        results = list(existing.values())
    header = ("# Careers / recruitment pages watched for new links. Generated by tools/discover_careers.py\n"
              "# from sources/candidates.yaml; safe to edit. job_links = job-related links seen at discovery.\n")
    out.write_text(header + yaml.safe_dump(results, allow_unicode=True, sort_keys=False), encoding="utf-8")
    off = sum(1 for r in results if r.get("enabled") is False)
    print(f"\nWrote {out}: {len(results) - off} enabled, {off} unreachable.")


if __name__ == "__main__":
    main()
