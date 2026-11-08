"""NISG's hiring portal SARAL (saral.nisg.org), read from the JSON feed behind its
"Open Roles" list.

NISG recruits contract tech/consultant staff for central bodies: National Health
Authority (ABDM, PM-JAY), UIDAI, PIB, DPIIT, NMC and others. abdm.gov.in/careers and
nisg.org/careers both send applicants here. The site is a JavaScript app, so the feed
is read directly; each open role becomes one item.
"""

import json
import re

from bs4 import BeautifulSoup

from ..models import Item, ParseResult
from ..textutil import clean

ROLE = "https://saral.nisg.org/job-description?token={}"
_ROLE_PAGE = re.compile(r"^https://saral\.nisg\.org/job-description\?token=(\w+)$")


def detail_feed(url: str) -> str | None:
    """The JSON behind a role page, which carries the qualifications and last date."""
    m = _ROLE_PAGE.match(url or "")
    return f"https://saral.nisg.org/api/jobs/public/{m[1]}" if m else None


def _text(html) -> str:
    return clean(BeautifulSoup(html, "lxml").get_text(" ")) if html else ""


def parse(text: str, page_url: str, source) -> ParseResult:
    try:
        roles = json.loads(text)["vacancies"]
    except (ValueError, KeyError, TypeError):
        return ParseResult("unrecognized", [])

    items = []
    for role in roles:
        post = clean(" / ".join(role.get("designations") or []))
        token = role.get("uniqueLink")
        if not post or not token:
            continue
        project = clean(role.get("projectName"))
        details = [project, clean(role.get("location")), clean(role.get("natureOfAppointment")),
                   clean(role.get("summary")), _text(role.get("experience"))]
        items.append(Item(
            source_id=source.id,
            title=f"{post} – {project}" if project and project.lower() not in post.lower() else post,
            description=" · ".join(d for d in details if d)[:1200],
            url=ROLE.format(token),
            notice_url="https://saral.nisg.org/",
            start_date=(role.get("createdAt") or "")[:10] or None,
            key_hint=f"saral:{role.get('_id') or token}",
        ))
    return ParseResult("ok" if items else "empty", items)
