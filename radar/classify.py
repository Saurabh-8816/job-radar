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

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


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

    @classmethod
    def load(cls, path=PROFILE_PATH) -> "Classifier":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def is_job_related(self, text: str) -> bool:
        return self.job.first(text) is not None

    def classify(self, title: str, description: str = "", body: str = "",
                 end_date: str | None = None, body_status: str | None = None,
                 today: date | None = None) -> Verdict:
        head = f"{title} {description}"
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

        deadline = self._deadline(body, end_date, today or today_ist())
        return Verdict(kind, tier, _dedupe(matched), reasons, deadline)

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

    def _deadline(self, body, end_date, today) -> str | None:
        found = self.body_deadline(body, today)
        dates = [d for d in (found, end_date) if d]
        return min(dates) if dates else None


def _dedupe(words):
    out = []
    for w in words:
        if w.lower() not in (o.lower() for o in out):
            out.append(w)
    return out
