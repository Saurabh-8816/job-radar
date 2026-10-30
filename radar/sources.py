"""Load the source registries in sources/*.yaml into Source objects."""

import re
from datetime import datetime, timedelta

import yaml

from . import SOURCES_DIR
from .models import Source


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _districts() -> list[Source]:
    path = SOURCES_DIR / "s3waas_districts.yaml"
    if not path.exists():
        return []
    out = []
    for d in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        name, slug = d["district"], _slug(d["district"])
        state = d.get("state", "CG")
        if d.get("recruitment"):
            out.append(Source(id=f"{state.lower()}-{slug}-recruitment", name=f"{name} district",
                              kind="s3waas", url=d["recruitment"], state=state, district=name,
                              group="district", category="recruitment"))
        if d.get("announcements"):
            out.append(Source(id=f"{state.lower()}-{slug}-announcements", name=f"{name} district",
                              kind="s3waas", url=d["announcements"], state=state, district=name,
                              group="district", category="announcements", filter_jobs=True))
    return out


# Watch lists and their defaults. The two bulk lists come from the official Union
# Government directory (tools/import_igod.py): ~2,400 central bodies / PSUs, checked every
# 6 hours, and ~1,300 Kendriya Vidyalayas, checked twice a day.
WATCH_FILES = {
    "watch_pages.yaml": {},
    "watch_igod.yaml": {"every_hours": 6},
    "watch_kv.yaml": {"every_hours": 12},
}
# A KV walk-in far from home is only worth hearing about when it's a computer post.
KV_HOME_STATES = {"CG", "MP", "OD", "MH", "TG", "DL"}


def _watch() -> list[Source]:
    out = []
    for name, defaults in WATCH_FILES.items():
        path = SOURCES_DIR / name
        if path.exists():
            out += [_watch_source({**defaults, **w})
                    for w in yaml.safe_load(path.read_text(encoding="utf-8")) or []]
    return out


def _watch_source(w: dict) -> Source:
    state = w.get("state", "IN")
    digest = w.get("digest", not (w.get("group") == "kv" and state not in KV_HOME_STATES))
    return Source(
        id=w.get("id") or _slug(w["name"]), name=w["name"], kind=w.get("kind", "watch"), url=w["url"],
        state=state, district=w.get("district"), group=w.get("group", "central"),
        category="careers", filter_jobs=w.get("filter_jobs", True),
        selector=w.get("selector"), enabled=w.get("enabled", True),
        runner=w.get("runner", "cloud"), churn_limit=w.get("churn_limit", 25),
        region_filter=w.get("region_filter", False), render=w.get("render", False),
        every_hours=w.get("every_hours", 0), digest=digest,
    )


def due(sources: list[Source], last_runs: dict, now: datetime, limit: int = 1500) -> list[Source]:
    """Sources to fetch this run. An `every_hours` source is skipped until that long has
    passed since its last check (30 min early is fine: cron start times drift). At most
    `limit` of them per run, longest-waiting first, so a newly added list of thousands
    spreads itself over a few runs instead of one very long one."""
    always, scheduled = [], []
    for s in sources:
        if not s.every_hours:
            always.append(s)
            continue
        last = last_runs.get(s.id)
        if not last or datetime.fromisoformat(last) <= now - timedelta(hours=s.every_hours, minutes=-30):
            scheduled.append((last or "", s))
    scheduled.sort(key=lambda pair: pair[0])
    return always + [s for _last, s in scheduled[:limit]]


def load_sources(only: str | None = None, include_disabled: bool = False,
                 runner: str | None = None) -> list[Source]:
    sources = [s for s in _districts() + _watch()
               if (s.enabled or include_disabled) and (runner is None or s.runner == runner)]
    if only:
        wanted = [o.strip().lower() for o in only.split(",") if o.strip()]
        sources = [s for s in sources
                   if any(w == s.state.lower() or w == s.group.lower() or w in s.id for w in wanted)]
    seen, unique = set(), []
    for s in sources:
        if s.id not in seen:
            seen.add(s.id)
            unique.append(s)
    return unique
