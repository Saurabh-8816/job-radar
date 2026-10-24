import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar.classify import Classifier  # noqa: E402
from radar.models import Source  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 24)  # the day the fixtures were captured


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def district_source(name="Kondagaon", category="recruitment") -> Source:
    slug = name.lower()
    return Source(id=f"cg-{slug}-{category}", name=f"{name} district", kind="s3waas",
                  url=f"https://{slug}.gov.in/en/notice_category/{category}/",
                  state="CG", district=name, group="district", category=category)


@pytest.fixture(scope="session")
def clf() -> Classifier:
    return Classifier.load()


@pytest.fixture(autouse=True)
def isolated_inbox(monkeypatch, tmp_path):
    """No test may read or delete the real data/inbox or relay cache."""
    from radar import relay
    monkeypatch.setattr(relay, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(relay, "CACHE", tmp_path / "relay_cache.json")
