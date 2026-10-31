"""CG power companies (CSPDCL / CSPTCL / CSPGCL), read from the JSON feed behind
web.cspdcl.co.in/#/FrmViewRecruitment.

The page is built by JavaScript and its PDF links have no href, so the radar used to see
only cspc.co.in's menu. The feed lists each recruitment with its files (notices,
corrigenda, syllabus, results). Every file becomes an item, so a detailed advertisement
or corrigendum added to an existing recruitment is reported as new.
"""

import json

from ..models import Item, ParseResult
from ..textutil import clean

PAGE = "https://web.cspdcl.co.in/#/FrmViewRecruitment"
FILE = "https://escapi.cspdcl.co.in/api/api/recruitment/getFile/{}?download=false"


def _split(value) -> tuple[str, str]:
    """'Title|file.pdf' -> ('Title', 'file.pdf'), the way the site's own code splits it."""
    value = str(value or "").strip()
    title, _, target = value.partition("|")
    return clean(title) or clean(target), target.strip() or title.strip()


def parse(text: str, page_url: str, source) -> ParseResult:
    try:
        posts = json.loads(text)["data"]
    except (ValueError, KeyError, TypeError):
        return ParseResult("unrecognized", [])

    items = []
    for post in posts:
        if str(post.get("ENABLED_DISABLED", "1")) != "1":
            continue
        name = clean(post.get("NAME_OF_POST"))
        if not name:
            continue
        for part in post.get("particulars") or []:
            box = clean(part.get("PARTICULARS_DESC"))
            for f in part.get("flags") or []:
                if f.get("FILE_NAME"):
                    label, _ = _split(f["FILE_NAME"])
                    url = FILE.format(f["SRNO"])
                elif f.get("LINK_NAME"):
                    label, url = _split(f["LINK_NAME"])
                    url = url if url.startswith("http") else f"https://{url}"
                else:
                    continue
                items.append(Item(
                    source_id=source.id,
                    title=f"{name} – {label}",
                    description=box,
                    url=url,
                    notice_url=PAGE,   # no docs: getFile links have no .pdf name, so the
                                       # item link itself is read (it answers with the PDF)
                    key_hint=f"cspdcl:{f['SRNO']}",
                ))
    return ParseResult("ok" if items else "empty", items)
