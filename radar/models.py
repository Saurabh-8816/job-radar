"""Data shapes passed between parsers, the pipeline and the store."""

import hashlib
from dataclasses import dataclass, field

from .textutil import normalize_url


@dataclass
class Source:
    id: str
    name: str
    kind: str                    # "s3waas" | "watch"
    url: str
    state: str = "CG"
    district: str | None = None
    group: str = ""              # cg-district, cg-state, central, academic, psu, state-board
    category: str = "recruitment"
    filter_jobs: bool = False    # keep only rows/links that look job-related
    selector: str | None = None  # watch pages: CSS scope to ignore menus
    enabled: bool = True
    runner: str = "cloud"        # "local": blocks GitHub's servers, fetched by the laptop relay
    churn_limit: int = 25        # more new links than this in one run = link-format change, absorbed
    region_filter: bool = False  # all-India aggregators: drop other states' posts (profile region_filter)
    render: bool = False         # page is built by JavaScript: open it in a headless browser


@dataclass
class Item:
    source_id: str
    title: str
    url: str                                   # main link (first document, or the notice page)
    notice_url: str                            # page the item was found on
    description: str = ""
    docs: list[tuple[str, str]] = field(default_factory=list)  # (label, url)
    start_date: str | None = None
    end_date: str | None = None
    key_hint: str | None = None  # parser-supplied identity when the URL itself isn't stable

    @property
    def key(self) -> str:
        if self.key_hint:
            return self.key_hint
        if self.docs:
            return normalize_url(self.docs[0][1])
        if self.url and self.url != self.notice_url:
            return normalize_url(self.url)
        raw = f"{self.source_id}|{self.title}|{self.start_date}"
        return "h:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


@dataclass
class ParseResult:
    status: str                  # "ok" | "empty" | "unrecognized"
    items: list[Item]
