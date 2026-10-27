"""ServiceSetu academic jobs (servicesetu.org), read from the JSON feed its own pages use.

The website renders job cards with JavaScript and no links, but app.servicesetu.org/api/jobs
returns every job with title, employer, position type, field, full description (including
eligibility), deadline and apply link. The description is passed on as the advert text,
so classification works exactly as for a PDF and nothing else needs downloading.

Only the jobs feed is read: ServiceSetu's workshops, call-for-papers and PhD-admission
sections are different feeds, and stay out.
"""

import json

from bs4 import BeautifulSoup

from ..models import Item, ParseResult
from ..textutil import clean

SITE = "https://www.servicesetu.org"


def _label(values) -> str:
    return ", ".join(str(v).replace("_", " ").title() for v in (values or []) if v)


def _advert_text(html: str) -> str:
    """The post's description without ServiceSetu's own paragraphs (membership, WhatsApp
    channel, "trusted by IITs..."), which mention faculty positions and IITs on every post."""
    soup = BeautifulSoup(html, "lxml")
    for p in soup.find_all(["p", "li"]):
        if "servicesetu" in p.get_text(" ").lower():
            p.decompose()
    return clean(soup.get_text(" "))


def parse(text: str, page_url: str, source) -> ParseResult:
    try:
        jobs = json.loads(text)["data"]["jobs"]
    except (ValueError, KeyError, TypeError):
        return ParseResult("unrecognized", [])

    items, texts = [], {}
    for job in jobs:
        if job.get("isArchived") or job.get("approvalStatus") not in (None, "approved"):
            continue
        location = clean(job.get("location"))
        if location and "india" not in location.lower():
            continue    # ServiceSetu also lists US / UAE / Canada posts
        slug, title = job.get("slug"), clean(job.get("title"))
        if not slug or not title:
            continue
        description = " · ".join(filter(None, [
            clean(job.get("employer")), clean(job.get("location")),
            f"Positions: {_label(job.get('position'))}" if job.get("position") else "",
        ]))   # ServiceSetu's own field tags are loose ("Data Science" on electrical posts): left out
        apply = (job.get("applyNowLink") or "").strip()
        item = Item(
            source_id=source.id,
            title=title,
            description=description,
            url=f"{SITE}/jobs/{slug}",
            notice_url=f"{SITE}/jobs",
            docs=[("Apply / official site", apply)] if apply.startswith("http") else [],
            start_date=(job.get("createdAt") or "")[:10] or None,
            end_date=(job.get("applicationDeadline") or "")[:10] or None,
            key_hint=f"servicesetu:{job.get('id') or slug}",
        )
        items.append(item)
        body = _advert_text(job.get("content") or "")
        if body:
            texts[item.key] = (body, "text")
    return ParseResult("ok" if items else "empty", items, texts)
