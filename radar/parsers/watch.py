"""Generic watcher for career/recruitment pages with no common layout.

Every link on the page becomes an item keyed by its URL. The pipeline keeps only
job-related links (profile `job_words`) and alerts on links it hasn't seen before,
so the page's structure doesn't matter. A per-source CSS `selector` can limit the
scan to the content area when menus add noise.
"""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import Item, ParseResult
from ..textutil import clean, join_url, normalize_url, parse_date

# Query parameters that change on every page load (NTPC signs each link with a fresh token).
_VOLATILE_PARAMS = {"token", "sid", "session", "sessionid", "phpsessid", "jsessionid",
                    "ts", "t", "timestamp", "_", "rand", "nocache", "cache", "v", "ver", "k", "key"}
_RANDOMISH = re.compile(r"[A-Za-z0-9+/=_%.-]{20,}")
_ROW_NUMBER = re.compile(r"^\s*\d{1,3}[.)]?\s+")
# Aggregators print the deadline in the row: "Online Form 2026 | Last Date : 13/11/2026".
_LAST_DATE = re.compile(r"(?:last|closing)\s*date\s*[:\-–]?\s*", re.I)   # date follows within ~40 chars

_SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "#", "whatsapp:")
_END_TAGS = re.compile(r"</(?:body|html)\s*>", re.I)
_DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png")
_GENERIC = {
    "click here", "here", "view", "download", "details", "more", "read more",
    "pdf", "link", "apply", "apply online", "apply here", "new", "notification",
    "advertisement", "advt", "view details", "देखें", "डाउनलोड", "यहाँ क्लिक करें",
}
# Longer button labels that still say nothing: "View Advertisement", "Download Notification (PDF)".
_GENERIC_LABEL = re.compile(
    r"^(click\s+here\s+(to|for)\s+)?(view|download|read|see|open|check)?\s*(the\s+)?"
    r"(full\s+|detailed\s+|official\s+)?(advertisement|advt\.?|notification|notice|details|pdf|file|document|corrigendum)s?"
    r"\s*(\(.{0,20}\))?\s*(here)?$"
    r"|^(click\s+here\s+(to\s+)?)?(know|read|learn|view|see)\s+more$", re.I)   # CWC: "Click here to know more"


# Page-number links of a paged list ("Page 2", "Current page 1", "Last page »", "›").
_PAGER = re.compile(
    r"^(?:[\s«»‹›<>|.…�-]*(?:current|go\s+to|page|\d{1,3}|next|prev(?:ious)?|first|last|older|newer|"
    r"पिछला|अगला|अंतिम|प्रथम|पृष्ठ)(?![a-z]))*[\s«»‹›<>|.…�-]*$", re.I)


_FILE_SIZE = re.compile(r"\s*[(\[]\s*[\d.,]+\s*[KMG]i?B\s*[)\]]\s*$", re.I)   # NCLAT: "Download(2.81 MB)"
# NPPA: the link only says "1.62 MB PDF English".
_FILE_INFO = re.compile(r"^[\d.,]+\s*[KMG]i?B(\s+(pdf|docx?|xlsx?|file|english|hindi|हिंदी|हिन्दी))*$", re.I)


# NITK: the link text is only the posting date, "Nov 09, 2026"; the row names the post.
_DATE_ONLY = re.compile(r"^[\s\d,./-]*((jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[\s\d,./-]*)?$", re.I)


# NITCON: the link is only the file's name, "Adv 17_01.pdf"; the row names the post.
_FILE_NAME = re.compile(r"^[\w .()\-]{0,60}\.(pdf|docx?|xlsx?|jpe?g|png)$", re.I)


def _says_nothing(text: str) -> bool:
    text = _FILE_SIZE.sub("", text).strip()
    return (text.lower() in _GENERIC or bool(_GENERIC_LABEL.match(text) or _FILE_INFO.match(text))
            or bool(_DATE_ONLY.match(text) or _FILE_NAME.match(text)))


def is_document(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(_DOC_EXT)


def _looks_random(value: str) -> bool:
    return bool(_RANDOMISH.fullmatch(value) and re.search(r"\d", value) and re.search(r"[A-Za-z]", value))


_NOT_A_NAME = re.compile(r"(?i)^\s*(publish(ed)?\s+date|date|end\s+date|last\s+date|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})")


def _lead_text(a):
    """The line just above a link's block that names the post (skipping date lines)."""
    block = a
    for parent in list(a.parents)[:3]:
        if parent.find_previous_sibling() is not None:
            block = parent
            break
    for sib in block.find_previous_siblings(limit=4):
        t = clean(sib.get_text(" "))
        if len(t) >= 15 and not _NOT_A_NAME.match(t):
            return t[:200]
    return ""


def _postback_key(page_url: str, text: str, context: str) -> str:
    """Identity of a postback link: the list page plus the link's text and row."""
    context = _ROW_NUMBER.sub("", context)
    return f"pb:{normalize_url(page_url)}|" + hashlib.sha1(f"{text}|{context}".encode("utf-8")).hexdigest()[:16]


def is_portal_root(url: str, page_url: str = "") -> bool:
    """A bare site root on another host: an application portal that every notice links to
    (CSIR-IMMT's adverts all point to https://rects.immt.res.in/). Such a URL can't tell
    one notice from the next, so the link's text and row are part of its identity."""
    parts = urlsplit(url)
    return (parts.path in ("", "/") and not parts.query
            and parts.netloc.lower() != urlsplit(page_url).netloc.lower())


def stable_key(url: str, text: str, context: str, page_url: str = "") -> str | None:
    """If the URL carries per-load tokens, identify the link by its stable parts
    (path + remaining params) plus its visible text and row; likewise a link to a
    portal's bare root (see is_portal_root). None = the URL alone identifies it."""
    parts = urlsplit(url)
    if page_url and is_portal_root(url, page_url):
        base = normalize_url(url)
    else:
        params = parse_qsl(parts.query, keep_blank_values=True)
        kept = [(k, v) for k, v in params if k.lower() not in _VOLATILE_PARAMS and not _looks_random(v)]
        if len(kept) == len(params):
            return None
        base = normalize_url(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), "")))
    # The row number shifts every time a notice is added on top (CTSP: "1 पुर्नमुल्यांकन…").
    context = _ROW_NUMBER.sub("", context)
    digest = hashlib.sha1(f"{text}|{context}".encode("utf-8")).hexdigest()[:16]
    return f"w:{base}|{digest}"


def _context_element(a):
    """The table row or list item holding the link, which usually carries the job title.
    Old sites lay whole pages out in tables, so an oversized row is skipped in favour
    of the nearest paragraph or cell."""
    for tag in ("tr", "li"):
        parent = a.find_parent(tag)
        if parent is not None and len(parent.get_text(" ", strip=True)) <= 600:
            return parent
    return a.find_parent(["p", "dd", "td"]) or _card(a)


def _card(a):
    """A small block around the link that also holds its caption: NITTTR Chennai's
    document cards are <div><span>Advertisement 2026-27</span> <a>View</a></div>."""
    own = len(a.get_text(" ", strip=True))
    for parent in list(a.parents)[:3]:
        size = len(parent.get_text(" ", strip=True))
        if size > 300:
            return None
        if size > own + 3:
            return parent
    return None


_DEADLINE_HEADER = re.compile(r"last\s*date|closing\s*date|end\s*date|due\s*date|अंतिम\s*(तिथि|दिनांक)", re.I)


def _table_deadline(a) -> str | None:
    """Deadline from a 'Last Date' / 'Closing Date' column of the link's table row."""
    tr = a.find_parent("tr")
    table = tr.find_parent("table") if tr else None
    if table is None:
        return None
    header = table.find("tr")
    if header is None or header is tr:
        return None
    names = [clean(c.get_text(" ")) for c in header.find_all(["th", "td"])]
    col = next((i for i, n in enumerate(names) if _DEADLINE_HEADER.search(n)), None)
    cells = tr.find_all(["td", "th"])
    if col is None or col >= len(cells):
        return None
    return parse_date(cells[col].get_text(" "))


def _scopes(soup, selector):
    """Every element the selector matches (pages often split jobs across several
    tables), else the whole body."""
    if selector:
        found = soup.select(selector)
        if found:
            return found
    return [soup.body or soup]


def _links(scopes):
    """Links inside the scopes; a selector may also pick the links themselves
    (IIIT Pune: each card's advert links, but not its "Apply Now" form)."""
    for scope in scopes:
        if scope.name == "a":
            if scope.get("href"):
                yield scope
        else:
            yield from scope.find_all("a", href=True)


def _soup(html: str):
    """lxml stops reading at </html>. NITTTR Chennai prints its header include as a whole
    page (ending </body></html>) before the recruitment table, which was lost; both end
    tags are optional, so they're dropped first."""
    return BeautifulSoup(_END_TAGS.sub("", html), "lxml")


def _section_headings(soup, sections):
    """{block: heading text} for a source's `sections` blocks. CG High Court lists each
    post as an accordion ("Translator") whose links only say "Notice" or "Merit List"."""
    if not sections:
        return {}
    found = {}
    for block in soup.select(sections):
        heading = block.find(["h1", "h2", "h3", "h4", "h5", "h6", "button", "legend"])
        if heading is not None:
            found[id(block)] = (_NEW_TAG.sub("", clean(heading.get_text(" "))), block)
    return found


_NEW_TAG = re.compile(r"\s*\bnew\b\s*$", re.I)   # IIIT Pune: "<h3>Advertisement… <span>NEW</span></h3>"


def _section_of(a, headings) -> tuple[str, object]:
    """(heading, block) of the section holding the link, else ('', None)."""
    return next((headings[id(p)] for p in a.parents if id(p) in headings), ("", None))


def parse(html: str, page_url: str, source) -> ParseResult:
    soup = _soup(html)
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    # "New" badges come and go; left in, they'd change a token link's identity when removed.
    for tag in soup.select(".badge"):
        if len(tag.get_text(strip=True)) <= 10:
            tag.decompose()
    headings = _section_headings(soup, getattr(source, "sections", None))
    # Relative links resolve against <base href> on sources that opt in (TIFR: "/maincampus/").
    # Opt-in, because honouring it everywhere would change other sites' link URLs (= item keys).
    base = soup.find("base", href=True) if getattr(source, "use_base", False) else None
    link_base = join_url(page_url, base["href"].strip()) if base and base["href"].strip() else page_url

    items, seen = [], set()
    allow_postback = getattr(source, "postback", False)
    for a in _links(_scopes(soup, source.selector)):
        href = a["href"].strip()
        # ASP.NET sites (PNB) open each advert through javascript:__doPostBack(...): no URL
        # of its own, so on sources that opt in the row becomes a notice on the list page.
        postback = allow_postback and href.lower().startswith("javascript:__dopostback")
        if not href or (href.lower().startswith(_SKIP_SCHEMES) and not postback):
            continue
        url = page_url if postback else join_url(link_base, href)
        if not url.startswith("http"):
            continue

        text = clean(a.get_text(" ")) or clean(a.get("title")) or clean(a.get("aria-label"))
        if text and _PAGER.match(text):
            continue
        row = _context_element(a)
        context = clean(row.get_text(" "))[:400] if row else text
        key_hint = (_postback_key(page_url, text, context) if postback
                    else stable_key(url, text, context, page_url))
        if (key_hint or url) in seen:   # one item per notice; a shared portal link can carry several
            continue
        seen.add(key_hint or url)
        title = text if (len(text) >= 12 and not _says_nothing(text)) else (context or text)
        if postback and _says_nothing(text):
            lead = _lead_text(a)
            if lead:   # PNB: "<p>RECRUITMENT OF LOCAL BANK OFFICERS…</p> <div><a>DETAILED ADVERTISEMENT</a>…</div>"
                title = f"{lead} – {text}"
        if not title:
            continue
        section, block = _section_of(a, headings)
        if section:   # the heading names the post; the row or link label says which file
            in_row = row is not None and row.name in ("tr", "li", "p", "dd", "td")
            label = title if in_row else (text or title)   # a button bar's text lists every button
            title = label if section in label else f"{section} – {label}"
        end_date = ((parse_date(context[m.end():m.end() + 40]) if (m := _LAST_DATE.search(context)) else None)
                    or _table_deadline(a))
        if not end_date and block is not None:   # the post's "Last Date to Apply" sits in its card
            card = clean(block.get_text(" "))
            end_date = parse_date(card[m.end():m.end() + 40]) if (m := _LAST_DATE.search(card)) else None
        items.append(Item(
            source_id=source.id,
            title=title[:300],
            description=context if context != title else "",
            url=url,
            notice_url=page_url,
            docs=[(text or "Document", url)] if is_document(url) else [],
            start_date=parse_date(context),
            end_date=end_date,
            key_hint=key_hint,
        ))
    return ParseResult("ok" if items else "empty", items)
