"""
Evening plant check-in: ~19:30, every day (see
PLANT_CARE_PROPOSAL.md section 4f - originally weekdays only, changed
to seven days a week per the approved changes). Sends one combined
Telegram message with Watered/Still damp/Not yet buttons for every
plant still "pending" from this morning's flagging.

Never regenerates state/plant_daily.json's flagged list itself - only
reads it (via plant_care.load_daily(), which already treats a stale
file, i.e. not from today, as "nothing pending" per the explicit
instruction to verify the date before trusting it) and reports what's
there. The single writer of new "pending" entries is
plant_care.summarize_plants(), called once each morning by brief.py
(weekdays) or plant_weekend.py (weekends) - never by this script.

Best-effort, like the R2 push in scheduled_send_voice.py: if nothing's
pending, or state can't be read, this sends nothing and just logs -
not a failure worth interrupting an evening for. A genuine failure to
reach Telegram gets one small supplementary text note.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from brief import load_config
from logutil import get_logger
from plant_away import get_effective_away_state
from plant_care import find_plant, load_daily, load_plants

log = get_logger("plant_checkin")

SEND_MESSAGE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_message.py"
SEND_KEYBOARD_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_message_with_keyboard.py"


def _build_keyboard(pending_ids: list[str], plants: list[dict]) -> tuple[str, list[list[dict]]]:
    lines = ["🌱 Evening plant check:"]
    keyboard = []
    for plant_id in pending_ids:
        plant = find_plant(plants, plant_id)
        if not plant:
            continue
        lines.append(f"\n{plant['name']} ({plant['location']})")
        keyboard.append(
            [
                {"text": "Watered", "callback_data": f"plant:{plant_id}:watered"},
                {"text": "Still damp", "callback_data": f"plant:{plant_id}:damp"},
                {"text": "Not yet", "callback_data": f"plant:{plant_id}:notyet"},
            ]
        )
    return "\n".join(lines), keyboard


def send_text_note(note: str) -> None:
    try:
        result = subprocess.run(
            [sys.executable, SEND_MESSAGE_SCRIPT],
            input=note,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("Supplementary note failed to send: %s", result.stderr.strip())
    except Exception as exc:
        log.error("Supplementary note failed to send: %s", exc, exc_info=True)


def main() -> None:
    try:
        config = load_config()
    except Exception as exc:
        log.error("Could not load config: %s", exc, exc_info=True)
        return

    away = get_effective_away_state(config)
    if away:
        log.info("Away until %s - skipping evening check-in", away["away_until"])
        return

    today = date.today()
    try:
        plants = load_plants()
        daily = load_daily(today)
    except Exception as exc:
        log.error("Plant state read failed - skipping evening check-in: %s", exc, exc_info=True)
        return

    pending_ids = [pid for pid, status in daily["flagged"].items() if status == "pending"]
    if not pending_ids:
        log.info("Nothing pending - skipping evening check-in")
        return

    text, keyboard = _build_keyboard(pending_ids, plants)
    payload = json.dumps({"text": text, "keyboard": keyboard})

    try:
        result = subprocess.run(
            [sys.executable, SEND_KEYBOARD_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
    except Exception as exc:
        log.error("Evening check-in send failed: %s", exc, exc_info=True)
        send_text_note(f"Plant check-in failed today ({exc}).")
        return

    log.info("Evening check-in sent for %d plant(s): %s", len(pending_ids), pending_ids)


if __name__ == "__main__":
    main()
