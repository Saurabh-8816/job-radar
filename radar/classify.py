"""Decide what a notice is and how much it matters, using profile.yaml.

kind:  "new" (a vacancy) or "update" (merit list, result, schedule...)
tier:  "A" instant alert · "B" daily digest · "C" stored, no alert
deadline: earliest of the listing's end date and a deadline found in the advert.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import yaml

from . import PROFILE_PATH
from .textutil import all_dates, today_ist

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_WALK_IN = re.compile(r"\bwalk[\s-]*in\b", re.I)


class Term:
    def __init__(self, spec: str):
        spec = str(spec).strip()
        self.sub = None
        if spec.startswith("re:"):
            self.rx = re.compile(spec[3:], re.I)
        elif spec.startswith("cs:"):
            self.rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(spec[3:])}(?![A-Za-z0-9])")
        elif _DEVANAGARI.search(spec):
            self.rx, self.sub = None, spec
        else:
            self.rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(spec)}(?![A-Za-z0-9])", re.I)

    def search(self, text: str) -> str | None:
        if self.rx is None:
            return self.sub if self.sub in text else None
        m = self.rx.search(text)
        return " ".join(m.group(0).split()) if m else None


class TermSet:
    def __init__(self, specs):
        self.terms = [Term(s) for s in (specs or [])]

    def first(self, text: str) -> str | None:
        for t in self.terms:
            hit = t.search(text)
            if hit:
                return hit
        return None

    def all(self, text: str) -> list[str]:
        hits = []
        for t in self.terms:
            hit = t.search(text)
            if hit and hit.lower() not in (h.lower() for h in hits):
                hits.append(hit)
        return hits


@dataclass
class Verdict:
    kind: str
    tier: str
    matched: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    deadline: str | None = None


class Classifier:
    def __init__(self, profile: dict):
        p = profile
        self.job = TermSet(p.get("job_words"))
        self.update = TermSet(p.get("update_words"))
        a = p.get("tier_a", {})
        self.strong = TermSet(a.get("strong"))
        self.weak = TermSet(a.get("weak"))
        self.combos = {name: (TermSet(c.get("role")), TermSet(c.get("with")))
                       for name, c in (a.get("combos") or {}).items()}
        self.tier_b = TermSet(p.get("tier_b"))
        self.tier_c = TermSet(p.get("tier_c"))
        self.deadline_before = TermSet(p.get("deadline_before"))
        self.deadline_after = TermSet(p.get("deadline_after"))
        self.not_job = TermSet(p.get("not_job_words"))
        self.job_core = TermSet(p.get("job_core_words"))
        self.body_ignore = [Term(s).rx for s in (p.get("body_ignore") or []) if Term(s).rx]
        region = p.get("region_filter") or {}
        self.region_keep = TermSet(region.get("keep"))
        self.region_block = TermSet(region.get("block"))

    @classmethod
    def load(cls, path=PROFILE_PATH) -> "Classifier":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def is_not_a_job(self, text: str) -> bool:
        """Admissions, student entrance tests, scholarships: no job word anywhere."""
        return self.not_job.first(text) is not None and self.job_core.first(text) is None

    def is_job_related(self, text: str) -> bool:
        return self.job.first(text) is not None and not self.is_not_a_job(text)

    def in_region(self, title: str) -> bool:
        """For all-India aggregators: False when the title names another state or its
        board, unless it also names a central / all-India body."""
        if self.region_keep.first(title):
            return True
        return self.region_block.first(title) is None

    def classify(self, title: str, description: str = "", body: str = "",
                 end_date: str | None = None, body_status: str | None = None,
                 today: date | None = None) -> Verdict:
        head = f"{title} {description}"
        if self.is_not_a_job(head):
            return Verdict("new", "C", [], ["admission / student notice, not a job"], end_date)
        for rx in self.body_ignore:
            body = rx.sub(" ", body)
        everything = f"{head} {body}"
        kind = "update" if self.update.first(head) else "new"

        matched = self.strong.all(everything) + self.weak.all(head)
        reasons, partial = [], []
        for name, (role, needs) in self.combos.items():
            roles = role.all(everything)
            if not roles:
                continue
            computing = needs.all(everything)
            if computing:
                matched += roles + computing
                reasons.append(f"{name} post in a computing field")
            else:
                partial += roles
                reasons.append(f"{name} post, field unclear")

        if matched:
            tier = "A"
        elif (b := self.tier_b.all(everything)) or partial:
            tier, matched = "B", (b or []) + partial
        elif c := self.tier_c.all(head):
            tier, matched = "C", c
            reasons.append("other-domain post")
        else:
            tier = "B"
            reasons.append("check manually: advert unreadable" if body_status == "unreadable"
                           else "no profile term matched")

        matched = _dedupe(matched)
        if tier == "A" and body:
            reasons += _evidence(body, head, matched)
        deadline = self._deadline(body, end_date, today or today_ist(), head)
        return Verdict(kind, tier, matched, reasons, deadline)

    def body_deadline(self, body: str, today: date) -> str | None:
        if not body:
            return None
        floor = (today - timedelta(days=30)).isoformat()
        hits = []
        for iso, start, end in all_dates(body):
            if iso < floor:
                continue
            if self.deadline_before.first(body[max(0, start - 80):start]) or \
               self.deadline_after.first(body[end:end + 25]):
                hits.append(iso)
        if not hits:
            return None
        return max(Counter(hits).items(), key=lambda kv: (kv[1], kv[0]))[0]

    def _deadline(self, body, end_date, today, head: str = "") -> str | None:
        found = self.body_deadline(body, today)
        dates = [d for d in (found, end_date) if d]
        if not dates and _WALK_IN.search(head):
            # "Walk-in-interview 28.10.2026": the interview date is the last chance to apply.
            floor = (today - timedelta(days=30)).isoformat()
            dates = [iso for iso, _s, _e in all_dates(head) if iso >= floor][:1]
        return min(dates) if dates else None


def _evidence(body: str, head: str, matched: list[str], limit: int = 2) -> list[str]:
    """Where in the advert the matching post appears ("advert p.21: …TGT (Computer
    Science)…"), so a 45-page notice doesn't have to be searched by hand. Terms that
    already appear in the title are skipped: the title says it."""
    out, flat_head = [], " ".join(head.lower().split())
    for term in matched:
        if " ".join(term.lower().split()) in flat_head:
            continue
        # PDF text breaks lines mid-phrase ("Computer\nScience"), so match any whitespace.
        m = re.search(r"\s+".join(map(re.escape, term.split())), body, re.I)
        if not m:
            continue
        pos = m.start()
        snippet = " ".join(body[max(0, pos - 60):m.end() + 90].replace("\f", " ").split())
        out.append(f"advert p.{body.count(chr(12), 0, pos) + 1}: …{snippet}…")
        if len(out) == limit:
            break
    return out


def _dedupe(words):
    out = []
    for w in words:
        if w.lower() not in (o.lower() for o in out):
            out.append(w)
    return out
