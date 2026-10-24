"""Load the source registries in sources/*.yaml into Source objects."""

import re

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


def _watch() -> list[Source]:
    path = SOURCES_DIR / "watch_pages.yaml"
    if not path.exists():
        return []
    out = []
    for w in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        out.append(Source(
            id=w.get("id") or _slug(w["name"]), name=w["name"], kind="watch", url=w["url"],
            state=w.get("state", "IN"), district=w.get("district"), group=w.get("group", "central"),
            category="careers", filter_jobs=w.get("filter_jobs", True),
            selector=w.get("selector"), enabled=w.get("enabled", True),
            runner=w.get("runner", "cloud"),
        ))
    return out


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
