"""Job Radar: personal alerts for government, PSU and academic job notices."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / "sources"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"
DEFAULT_DB = DATA_DIR / "jobs.db"
PROFILE_PATH = ROOT / "profile.yaml"
