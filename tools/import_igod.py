"""Import every Union Government organisation from the official web directory (IGOD,
served by india.gov.in) into sources/igod_candidates.yaml, for discover_careers.py.

Usage:  python tools/import_igod.py

Covers ministries, departments, attached/subordinate offices, commissions, statutory and
autonomous bodies, PSUs / JVs / companies / societies (IFFCO, NAFED, IRCON...), academies
and institutions, regional offices and councils. Schemes / apps / portals are skipped:
they don't recruit. Organisations already in candidates.yaml (same website) are skipped,
and so are entries without a website.

Kendriya Vidyalayas (≈1,300 schools, all on the same S3WaaS template) go to
sources/kv_candidates.yaml instead: their recruitment page is found by path, not by search.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar import SOURCES_DIR  # noqa: E402
from radar.fetch import HEADERS  # noqa: E402

API = "https://www.india.gov.in/directory/web-directory/api"
TYPES = {   # IGOD organisation_type -> our group
    "E002": "central", "E053": "central", "E003": "central",   # ministries, departments
    "E005": "central",            # attached / subordinate offices
    "E013": "central",            # commissions / committees
    "E051": "central", "STABDY": "central", "AUTBDY": "central",
    "E011": "psu", "E059": "psu",  # boards / undertakings, PSUs / JVs / companies / societies
    "E009": "central",            # academies / institutions
    "DUW": "central", "RFO": "central", "CNCL": "central", "SOC": "central", "OTHR": "central",
}   # "SPMA" (schemes / programmes / apps) is left out

# Two-letter codes used across sources/*.yaml, from the state named at the end of a title.
STATES = {
    "andhra pradesh": "AP", "arunachal pradesh": "AR", "assam": "AS", "bihar": "BR",
    "chhattisgarh": "CG", "goa": "GA", "gujarat": "GJ", "haryana": "HR", "himachal pradesh": "HP",
    "jharkhand": "JH", "karnataka": "KA", "kerala": "KL", "madhya pradesh": "MP",
    "maharashtra": "MH", "manipur": "MN", "meghalaya": "ML", "mizoram": "MZ", "nagaland": "NL",
    "odisha": "OD", "orissa": "OD", "punjab": "PB", "rajasthan": "RJ", "sikkim": "SK",
    "tamil nadu": "TN", "telangana": "TG", "tripura": "TR", "uttar pradesh": "UP",
    "uttarakhand": "UK", "uttrakhand": "UK", "west bengal": "WB", "delhi": "DL", "new delhi": "DL",
    "jammu and kashmir": "JK", "jammu & kashmir": "JK", "ladakh": "LA", "puducherry": "PY",
    "chandigarh": "CH", "andaman and nicobar islands": "AN", "lakshadweep": "LD",
}
_IGOD_STATE = {"TS": "TG", "OR": "OD"}


def fetch(otype: str) -> list[dict]:
    headers = {**HEADERS, "Content-Type": "application/json", "Origin": "https://www.india.gov.in",
               "Referer": "https://www.india.gov.in/directory/web-directory"}
    rows, page = [], 1
    while True:
        body = {"dataval": {"clientvalue": "client", "querytype": "WebdirectoryCategorydetalsList",
                            "mustvalue": [{"fieldName": "category", "fieldValue": "ug"}],
                            "shouldvalue": [{"fieldName": "organization_type", "fieldValue": otype}],
                            "pageno": page, "pageSize": 1000}}
        r = requests.post(API, json=body, headers=headers, timeout=120)
        r.raise_for_status()
        data = r.json()["resultdata"]["data"]["getIgodWebDirectoryByFilters"]
        rows += data["results"]
        if page * 1000 >= data["total"]:
            return rows
        page += 1


def host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def state_of(row: dict) -> str:
    title = row["title"].lower()
    for name, code in sorted(STATES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(name)}\s*\)?\s*$", title):
            return code
    code = row.get("state_id")
    return _IGOD_STATE.get(code, code) or "IN"


def home_of(url: str) -> str:
    parts = urlsplit(url.strip())
    return f"{parts.scheme or 'https'}://{parts.netloc}/"


def main():
    known = set()
    for name in ("candidates.yaml", "watch_pages.yaml"):
        for e in yaml.safe_load((SOURCES_DIR / name).read_text(encoding="utf-8")) or []:
            for key in ("home", "url"):
                if e.get(key):
                    known.add(host(e[key]))

    orgs, kvs, seen = [], [], set()
    for otype, group in TYPES.items():
        rows = fetch(otype)
        print(f"  {otype:7} {len(rows):5} organisations")
        for row in rows:
            url = (row.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            h = host(url)
            if h in known or h in seen:
                continue
            seen.add(h)
            entry = {"name": " ".join(row["title"].split()), "home": home_of(url),
                     "group": group, "state": state_of(row)}
            if h.endswith(".kvs.ac.in"):
                kvs.append({**entry, "group": "kv"})
            else:
                orgs.append(entry)

    header = ("# Generated by tools/import_igod.py from the official Union Government web directory\n"
              "# (igod.gov.in / india.gov.in). Input to tools/discover_careers.py; re-run to refresh.\n")
    for name, rows in (("igod_candidates.yaml", orgs), ("kv_candidates.yaml", kvs)):
        rows.sort(key=lambda e: (e["group"], e["name"].lower()))
        (SOURCES_DIR / name).write_text(header + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False,
                                                                width=200), encoding="utf-8")
        print(f"Wrote sources/{name}: {len(rows)} organisations")


if __name__ == "__main__":
    main()
