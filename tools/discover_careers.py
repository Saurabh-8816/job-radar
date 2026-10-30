"""Find each organisation's careers page and write sources/watch_pages.yaml.

Usage:  python tools/discover_careers.py [name-filter] [--render] [--timeout=N]
        python tools/discover_careers.py --from=igod_candidates.yaml --to=watch_igod.yaml
        python tools/discover_careers.py --from=kv_candidates.yaml --to=watch_kv.yaml

--render opens pages in a headless browser, for sites built by JavaScript.
--from / --to read and write other files in sources/ (default candidates.yaml ->
watch_pages.yaml); --workers=N sets how many sites are probed at once (default 8).

For each entry in sources/candidates.yaml: fetch the homepage, follow links that
look like careers/recruitment pages, and keep the page with the most job-related
links. Pinned `url:` entries are only validated. Unreachable sites are written
with `enabled: false` so they're visible in the file and easy to retry later.
"""

import re
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar import SOURCES_DIR  # noqa: E402
from radar.classify import Classifier  # noqa: E402
from radar import render  # noqa: E402
from radar.fetch import get  # noqa: E402
from radar.models import Source  # noqa: E402
from radar.parsers import watch  # noqa: E402
from radar.textutil import join_url  # noqa: E402

CAREER_LINK = re.compile(
    r"career|recruit|vacanc|job|employment|opportunit|positions|openings|advertisement|"
    r"भर्ती|रिक्ति|रिक्त|नियुक्ति", re.I)
NOT_CAREER = re.compile(
    r"placement|student|alumni|internship|admission|coaching|finishing|higher[\s-]*stud|"
    r"career[\s_-]*(center|centre|development|guidance|counsel)|"
    # Archives have the most links but get a notice only after it closes.
    r"archive|past[\s_-]*(openings?|jobs|recruit|advert|vacanc)|previous[\s_-]*(openings?|jobs|recruit|advert|vacanc)|"
    r"old[\s_-]*(jobs|recruit|advert|vacanc|notice)|expired|closed", re.I)

clf = Classifier.load()
warnings.filterwarnings("ignore", module="bs4")   # XML sitemaps served as pages


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
        href = join_url(home, a["href"].strip())
        if not href.startswith("http") or href.lower().endswith(".pdf"):
            continue
        blob = f"{text} {href}"
        if CAREER_LINK.search(blob) and not NOT_CAREER.search(blob):
            same_site = urlsplit(href).netloc.split(".")[-3:] == host.split(".")[-3:]
            if same_site or "career" in href.lower():
                found.append(href)
    return list(dict.fromkeys(found))[:6]


KV_PATHS = ("recruitment/", "en/recruitment/")


def discover_kv(entry: dict, out: dict) -> dict:
    """Kendriya Vidyalayas share one S3WaaS template: notices are rows of a documents
    table on /recruitment/ or, at schools without one, on the /notice/ board. A school
    with neither is watched on its homepage."""
    for path in KV_PATHS:
        r = get(entry["home"] + path, timeout=TIMEOUT, retries=1)
        if r.ok and "documents-table" in r.text:
            return {**out, "url": entry["home"] + path, "selector": "table.documents-table",
                    "filter_jobs": False, "job_links": r.text.count("<tr") - 1}
    # No recruitment page: walk-ins go on the general notice board, next to admission notices.
    r = get(entry["home"] + "notice/", timeout=TIMEOUT, retries=1)
    if r.ok and "documents-table" in r.text:
        return {**out, "url": entry["home"] + "notice/", "selector": "table.documents-table",
                "job_links": r.text.count("<tr") - 1, "note": "general notice board; job notices filtered"}
    score, err = score_page(entry["home"])
    if score < 0:
        return {**out, "url": entry["home"], "job_links": 0, "enabled": False, "note": f"unreachable: {err}"}
    return {**out, "url": entry["home"], "job_links": score, "note": "no /recruitment/ page; homepage watched"}


def discover(entry: dict) -> dict:
    name, home = entry["name"], entry["home"]
    out = {"id": _slug(name), "name": name, "group": entry.get("group", "central"),
           "state": entry.get("state", "IN")}
    if entry.get("group") == "kv":
        return discover_kv(entry, out)
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


_done = {"n": 0, "of": 0}
_done_lock = threading.Lock()


def _safe_discover(entry: dict) -> dict:
    try:
        return discover(entry)
    except Exception as e:  # one odd site must not lose hours of results
        return {"id": _slug(entry["name"]), "name": entry["name"], "group": entry.get("group", "central"),
                "state": entry.get("state", "IN"), "url": entry["home"], "job_links": 0,
                "enabled": False, "note": f"discovery error: {type(e).__name__}: {e}"[:200]}
    finally:
        with _done_lock:
            _done["n"] += 1
            if _done["n"] % 100 == 0:
                print(f"  ... {_done['n']}/{_done['of']} sites checked", flush=True)


def _unique_ids(results):
    """Two offices can share a name ("Regional Office, ..."): suffix repeats."""
    seen = {}
    for r in results:
        n = seen[r["id"]] = seen.get(r["id"], 0) + 1
        if n > 1:
            r["id"] = f"{r['id']}-{n}"


def main():
    global TIMEOUT, RENDER
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, dst, workers = "candidates.yaml", "watch_pages.yaml", 8
    for a in sys.argv[1:]:
        if a.startswith("--timeout="):
            TIMEOUT = int(a.split("=", 1)[1])
        elif a == "--render":
            RENDER = True
        elif a.startswith("--from="):
            src = a.split("=", 1)[1]
        elif a.startswith("--to="):
            dst = a.split("=", 1)[1]
        elif a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
    # Filter: comma-separated names (exact, case-insensitive) or a single substring.
    flt = args[0].lower() if args else ""
    names = {n.strip() for n in flt.split(",")} if "," in flt else None
    entries = [e for e in yaml.safe_load((SOURCES_DIR / src).read_text(encoding="utf-8"))
               if (e["name"].lower() in names if names else flt in e["name"].lower())]
    with ThreadPoolExecutor(max_workers=3 if RENDER else workers) as pool:
        _done["of"] = len(entries)
        results = list(pool.map(_safe_discover, entries))
    _unique_ids(results)
    if RENDER:
        for r in results:
            r["render"] = True
    for r in results:
        flag = "OFF" if r.get("enabled") is False else f"{r['job_links']:>3}"
        print(f"  {flag}  {r['name'][:38]:38} {r['url']}")
    out = SOURCES_DIR / dst
    if flt and out.exists():  # partial run: merge into the existing file
        existing = {e["id"]: e for e in yaml.safe_load(out.read_text(encoding="utf-8")) or []}
        for r in results:  # keep hand-set fields (runner, churn_limit, region_filter...)
            existing[r["id"]] = {**existing.get(r["id"], {}), **r}
        results = list(existing.values())
    header = ("# Careers / recruitment pages watched for new links. Generated by tools/discover_careers.py\n"
              f"# from sources/{src}; safe to edit. job_links = job-related links seen at discovery.\n")
    out.write_text(header + yaml.safe_dump(results, allow_unicode=True, sort_keys=False), encoding="utf-8")
    off = sum(1 for r in results if r.get("enabled") is False)
    print(f"\nWrote {out}: {len(results) - off} enabled, {off} unreachable.")


if __name__ == "__main__":
    main()
