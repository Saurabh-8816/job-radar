"""Telegram delivery and message formatting.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment (GitHub secrets).
Without them, or with --dry-run, messages are printed instead of sent.
"""

import html
import json
import os
import re
from datetime import date

import requests

from .textutil import days_left

_API = "https://api.telegram.org/bot{token}/{method}"
_TAG = re.compile(r"<[^>]+>")
LIMIT = 3900  # Telegram's hard limit is 4096 characters


class Telegram:
    """Sends for real when configured. In --dry-run, prints and reports success so a
    scratch DB behaves like a real one. In a real run WITHOUT credentials it prints and
    reports failure, so alerts stay unsent until the secrets are fixed instead of
    being marked delivered and lost."""

    def __init__(self, dry_run: bool = False):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.dry_run = dry_run
        self.configured = bool(self.token and self.chat_id)
        self.live = self.configured and not dry_run
        if not dry_run and not self.configured:
            missing = [n for n, v in (("TELEGRAM_BOT_TOKEN", self.token), ("TELEGRAM_CHAT_ID", self.chat_id)) if not v]
            # GitHub turns this line into a yellow warning on the run page.
            print(f"::warning title=Telegram not configured::{' and '.join(missing)} missing; "
                  "nothing will be sent and alerts stay queued until the secrets are set.")

    def _call(self, method: str, **payload):
        r = requests.post(_API.format(token=self.token, method=method), json=payload, timeout=25)
        if not r.ok:
            print(f"  telegram {method} failed: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.ok else None

    def send(self, text: str) -> bool:
        """True only when the message was delivered (or simulated in --dry-run)."""
        for chunk in split_message(text):
            if not self.live:
                print("\n----- telegram (not sent) -----\n" + html.unescape(_TAG.sub("", chunk)))
                if not self.dry_run:
                    return False
                continue
            if self._call("sendMessage", chat_id=self.chat_id, text=chunk, parse_mode="HTML",
                          disable_web_page_preview=True) is None:
                return False
        return True

    def username(self) -> str | None:
        if not self.configured:
            return None
        try:
            data = self._call("getMe")
        except (requests.RequestException, ValueError):
            return None
        return ((data or {}).get("result") or {}).get("username")

    def updates(self, offset: int) -> list:
        if not self.live:
            return []
        data = self._call("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
        return (data or {}).get("result", [])


def split_message(text: str, limit: int = LIMIT):
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > limit and chunk:
            yield chunk
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        yield chunk


# ---- formatting ---------------------------------------------------------------

def _fmt_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d %b %Y")


def deadline_phrase(deadline: str | None, today: date | None = None) -> str:
    if not deadline:
        return "Deadline not stated, check the advert"
    n = days_left(deadline, today)
    when = _fmt_date(deadline)
    if n is None or n < 0:
        return f"Closed {when}"
    if n == 0:
        return f"Closes TODAY ({when})"
    if n == 1:
        return f"Closes tomorrow ({when})"
    return f"Closes {when} ({n} days left)"


def where(source) -> str:
    if source is None:
        return ""
    bits = [source["name"]]
    if source["state"] and source["state"] not in ("IN",) and source["grp"] != "district":
        bits.append(source["state"])
    elif source["grp"] == "district":
        bits.append("Chhattisgarh" if source["state"] == "CG" else source["state"])
    return " · ".join(bits)


def doc_links(row, limit: int = 3) -> str:
    docs = json.loads(row["docs"] or "[]")[:limit]
    links = [f'<a href="{html.escape(u, quote=True)}">{html.escape(label[:40] or "Document")}</a>'
             for label, u in docs]
    links.append(f'<a href="{html.escape(row["notice_url"], quote=True)}">Notice page</a>')
    return " · ".join(links)


def format_alert(row, source, today: date | None = None) -> str:
    matched = ", ".join(json.loads(row["matched"] or "[]")[:6])
    evidence = [r for r in json.loads(row["reasons"] or "[]") if r.startswith("advert p.")]
    title = html.escape(row["title"][:280])
    i = row["id"]
    lines = [
        f"<b>{title}</b>",
        html.escape(where(source)),
        f"⏳ {deadline_phrase(row['deadline'], today)}",
        f"Why: {html.escape(matched)}" if matched else "",
        *[f"📄 <i>{html.escape(e[:230])}</i>" for e in evidence],
        doc_links(row),
        f"#{i}   /star_{i}   /applied_{i}   /hide_{i}",
    ]
    return "\n".join(line for line in lines if line)


def format_line(row, source, today: date | None = None) -> str:
    """One compact line for digests."""
    title = html.escape(row["title"][:140])
    url = html.escape(row["url"] or row["notice_url"], quote=True)
    src = html.escape(source["name"] if source else "")
    dl = row["deadline"]
    tail = f" — {deadline_phrase(dl, today)}" if dl else ""
    return f'• <a href="{url}">{title}</a> <i>({src})</i>{tail}  #{row["id"]}'
