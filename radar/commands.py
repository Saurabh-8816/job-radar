"""Telegram commands, read at the start of every run (no server needed).

  /star_12      remind me before #12 closes
  /applied_12   I've applied — stop reminding
  /hide_12      not interested
  /unhide_12    undo hide/applied/star
  /help

The dashboard app's buttons send the same through a link (t.me/<bot>?start=star_12),
which arrives as "/start star_12".

Only messages from TELEGRAM_CHAT_ID are obeyed; anyone else who finds the bot is ignored.
"""

import re

from .notify import Telegram

_CMD = re.compile(r"^/(?:start\s+)?/?(star|applied|hide|unhide)[_\s]+#?(\d+)", re.I)
_STATUS = {"star": "starred", "applied": "applied", "hide": "hidden", "unhide": ""}
_DONE = {"star": "★ Starred", "applied": "✓ Marked applied", "hide": "Hidden", "unhide": "Restored"}

HELP = ("<b>Job Radar commands</b>\n"
        "/star_ID — remind me 3 days and 1 day before it closes\n"
        "/applied_ID — I've applied, stop reminding\n"
        "/hide_ID — not interested\n"
        "/unhide_ID — undo\n"
        "The ID is the number after # in each alert.")


def process(tg: Telegram, store) -> int:
    if not tg.live:
        return 0
    offset = int(store.get_meta("telegram_offset", "0"))
    handled = 0
    for update in tg.updates(offset):
        offset = max(offset, update["update_id"] + 1)
        msg = update.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != tg.chat_id:
            continue
        text = (msg.get("text") or "").strip()
        m = _CMD.match(text)
        if m:
            verb, item_id = m.group(1).lower(), int(m.group(2))
            ok = store.set_user_status(item_id, _STATUS[verb])
            tg.send(f"{_DONE[verb]} #{item_id}" if ok else f"No item #{item_id}.")
            handled += 1
        elif text.startswith(("/help", "/start")):
            tg.send(HELP)
    store.set_meta("telegram_offset", str(offset))
    store.commit()
    return handled
