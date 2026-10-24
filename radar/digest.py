"""The 8 PM digest: closing soon, starred reminders, tier-B finds, updates, source health."""

from collections import defaultdict
from datetime import timedelta

from . import commands
from .notify import Telegram, format_line
from .store import Store
from .textutil import days_left, today_ist

SECTION_CAP = 25


def _section(title, rows, store, today, cap=SECTION_CAP):
    if not rows:
        return []
    out = [f"\n<b>{title} ({len(rows)})</b>"]
    out += [format_line(r, store.source_of(r["source_id"]), today) for r in rows[:cap]]
    if len(rows) > cap:
        out.append(f"…and {len(rows) - cap} more on the dashboard.")
    return out


def build(store: Store, today=None) -> tuple[str, list[int]]:
    today = today or today_ist()
    rows = store.digest_items()
    closing = store.closing_soon(today.isoformat(), (today + timedelta(days=3)).isoformat())

    # Starred items get one reminder at 3 days and one at 1 day.
    reminders = []
    for r in closing:
        n = days_left(r["deadline"], today)
        if r["user_status"] == "starred" and n in (0, 1, 3) and str(n) not in (r["reminded"] or "").split(","):
            reminders.append(r)
            store.db.execute("UPDATE items SET reminded=? WHERE id=?",
                             (",".join(filter(None, [r["reminded"], str(n)])), r["id"]))

    today_iso = today.isoformat()
    shown = {r["id"] for r in closing}

    def still_open(r):
        return not r["deadline"] or r["deadline"] >= today_iso

    worth_a_look = [r for r in rows if r["kind"] == "new" and r["tier"] == "B"
                    and still_open(r) and r["id"] not in shown]
    updates = [r for r in rows if r["kind"] == "update" and r["tier"] in ("A", "B")
               and still_open(r) and r["id"] not in shown]
    other = sum(1 for r in rows if r["tier"] == "C")

    by_area = defaultdict(list)
    for r in worth_a_look:
        src = store.source_of(r["source_id"])
        area = "Chhattisgarh districts" if src["grp"] == "district" else {
            "cg-state": "Chhattisgarh state", "central": "Central government", "academic": "IITs, NITs & institutes",
            "psu": "PSUs & banks", "state-board": "Neighbouring states"}.get(src["grp"], src["grp"] or "Other")
        by_area[area].append(r)

    lines = [f"<b>Job Radar digest · {today.strftime('%a %d %b %Y')}</b>"]
    lines += _section("⭐ Starred, closing soon", reminders, store, today)
    lines += _section("⏳ Closing within 3 days", [r for r in closing if r not in reminders], store, today)
    for area, items in by_area.items():
        lines += _section(f"Worth a look: {area}", items, store, today)
    lines += _section("Updates on existing drives (lists, results, schedules)", updates, store, today, cap=15)
    if other:
        lines.append(f"\n{other} other-domain notice(s) stored without alert (nurse, driver, pharmacist…). See the dashboard.")

    unhealthy = store.unhealthy_sources()
    counts = store.source_counts()
    lines.append(f"\n<b>Coverage</b>: {counts['healthy'] or 0}/{counts['total'] or 0} sources healthy.")
    for s in unhealthy[:10]:
        if s["note"]:
            lines.append(f"• ⚠ {s['name']}: {s['note']}")
        if s["consecutive_failures"] >= 3 or s["last_status"] == "unrecognized":
            lines.append(f"• ⚠ {s['name']}: {s['last_error'] or s['last_status']} "
                         f"({s['consecutive_failures']} runs in a row)")

    if len(lines) <= 2 and not unhealthy:
        lines.insert(1, "Nothing new since the last digest.")
    return "\n".join(lines), [r["id"] for r in rows]


def run(db_path, dry_run=False) -> int:
    store = Store(db_path)
    tg = Telegram(dry_run)
    commands.process(tg, store)
    text, ids = build(store)
    if tg.send(text) and not dry_run:
        store.mark_digested(ids)
        store.clear_notes()
    store.close()
    return len(ids)
