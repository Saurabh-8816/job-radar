"""Sites on the "post type" CMS used by Info Tech Corporation of Goa (infotech.goa.gov.in).

The pages (/announcements, /appointments) are a Nuxt app whose rows have JavaScript
"Download" buttons and no links, so the generic watcher sees nothing. The page loads its
rows from `/api/post/type/slug/<slug>`: each post has a title, a short description, a
date and its documents in `meta`. Every post becomes one item, keyed by its id so an
edited title doesn't look like a new notice.
"""

import json
import re
from urllib.parse import urljoin, urlsplit

from ..models import Item, ParseResult
from ..textutil import clean

_FILE = re.compile(r"\.(pdf|docx?|xlsx?)(\?|$)", re.I)


def page_of(api_url: str) -> str:
    """https://x/api/post/type/slug/announcements -> https://x/announcements"""
    parts = urlsplit(api_url)
    slug = parts.path.rstrip("/").rsplit("/", 1)[-1]
    return f"{parts.scheme}://{parts.netloc}/{slug}"


def parse(text: str, page_url: str, source) -> ParseResult:
    try:
        posts = json.loads(text)["data"]
    except (ValueError, KeyError, TypeError):
        return ParseResult("unrecognized", [])
    page = page_of(page_url)
    items = []
    for post in posts or []:
        if post.get("active") is False:
            continue
        title = clean(post.get("title"))
        if not title:
            continue
        docs, notes = [], []
        for m in post.get("meta") or []:
            if m.get("isDocument") and m.get("documentUrl"):
                docs.append((clean(m.get("title") or m.get("documentName")) or "Document",
                             urljoin(page, m["documentUrl"])))
            elif m.get("linkUrl") and _FILE.search(m["linkUrl"]):
                docs.append((clean(m.get("title")) or "Document", urljoin(page, m["linkUrl"])))
            # other links (the candidate login every appointment points to) are not adverts
            note = clean(m.get("description"))
            if note and note != title:
                notes.append(note)
        description = " · ".join(x for x in dict.fromkeys([clean(post.get("shortDescription")), *notes])
                                 if x and x != title)
        items.append(Item(
            source_id=source.id, title=title, description=description[:600],
            url=docs[0][1] if docs else page, notice_url=page, docs=docs,
            start_date=(post.get("createdAt") or "")[:10] or None,
            key_hint=f"cms:{urlsplit(page).netloc}:{post.get('_id') or post.get('slug')}",
        ))
    return ParseResult("ok" if items else "empty", items)
