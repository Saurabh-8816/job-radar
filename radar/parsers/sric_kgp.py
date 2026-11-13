"""IIT Kharagpur SRIC project positions, read from the JSON feed behind its
"Temporary Jobs" page (erp.iitkgp.ac.in/SricWeb/temporaryJobs.htm fills its table from
viewTemporaryJobDetails.htm). Each record is one post with its qualifications, pay,
age limit and last date, so the notice can be classified without opening anything.
"""

import json
import re

from ..models import Item, ParseResult
from ..textutil import clean

LIST_PAGE = "https://erp.iitkgp.ac.in/SricWeb/temporaryJobs.htm"
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})")


def _iso(value) -> str | None:
    v = str(value or "")
    if m := _ISO.match(v):
        return f"{m[1]}-{m[2]}-{m[3]}"
    if m := _DMY.match(v):
        return f"{m[3]}-{m[2]}-{m[1]}"
    return None


def parse(text: str, page_url: str, source) -> ParseResult:
    try:
        jobs = json.loads(text)
    except ValueError:
        return ParseResult("unrecognized", [])
    if not isinstance(jobs, list):
        return ParseResult("unrecognized", [])

    items = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        post = clean(j.get("designation"))
        if not post:
            continue
        dept, pi = clean(j.get("dept")), clean(j.get("coordinator_pi"))
        title = post + (f" – {dept}" if dept else "") + (f" (PI {pi})" if pi else "")
        details = [
            clean(j.get("project_title")),
            "Essential: " + clean(j.get("essential_qualification")) if j.get("essential_qualification") else "",
            "Desirable: " + clean(j.get("desiarable_criteria")) if j.get("desiarable_criteria") else "",
            clean(j.get("consolidated_amount")),
            f"Age limit {clean(j.get('age_limit'))}" if j.get("age_limit") else "",
            f"Posts: {clean(j.get('no_of_vacancy'))}" if j.get("no_of_vacancy") else "",
            f"Last date: {clean(j.get('last_date'))}" if j.get("last_date") else "",
            f"Ref: {clean(j.get('ref_no'))}" if j.get("ref_no") else "",
        ]
        items.append(Item(
            source_id=source.id,
            title=title[:300],
            description=" · ".join(d for d in details if d)[:1500],
            url=clean(j.get("adv_link")) or LIST_PAGE,
            notice_url=LIST_PAGE,
            start_date=_iso(j.get("ref_date")),
            end_date=_iso(j.get("adv_last_date")) or _iso(j.get("last_date")),
            key_hint=f"kgpsric:{clean(j.get('ref_no'))}|{clean(j.get('desg_code'))}",
        ))
    return ParseResult("ok" if items else "empty", items)
