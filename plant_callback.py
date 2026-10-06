"""
Button-press handler for the evening plant check-in, invoked by the
Telegram bridge's callback_commands routing (prefix "plant") with the
raw callback_data as its one argument - see Bizkit's DECISIONS.md
ADR-0014 and PLANT_CARE_PROPOSAL.md section 4g.

Must be fast: Telegram requires the bridge to answer the callback
within ~10 seconds of the press, and the bridge's own script timeout
for this path is 8 seconds (bridge.py's callback_command_timeout_seconds).
This script only ever touches local JSON files - no network calls -
so that's comfortably within budget.

Idempotent, not message-editing: re-pressing a button for an
already-answered plant is a safe no-op with its own toast ("Already
logged"), rather than the bridge/this script trying to edit the
original message's keyboard to remove a row. See the proposal's
section 4g for the tradeoff this accepts.

The bridge has already validated callback_data's *shape* (length,
charset) before this script ever runs - this script is the trust
boundary for *semantics*: does this plant id actually exist, is this
a real action, matching the same split custom_commands established
(DESIGN.md "Custom commands").
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta

from plant_care import bump_learned_adjustment, find_plant, load_daily, load_plants, save_daily, save_plants

CALLBACK_PATTERN = re.compile(r"^plant:([a-z0-9_]{1,40}):(watered|damp|notyet)$")


def handle_callback(data: str) -> str:
    match = CALLBACK_PATTERN.match(data)
    if not match:
        return "Didn't understand that."

    plant_id, action = match.group(1), match.group(2)

    plants = load_plants()
    plant = find_plant(plants, plant_id)
    if not plant:
        return "Unknown plant."

    today = date.today()
    daily = load_daily(today)
    current_status = daily["flagged"].get(plant_id)

    if current_status and current_status != "pending":
        return "Already logged 👍"

    if action == "watered":
        plant["last_watered"] = today.isoformat()
        plant["deferred_until"] = None
        daily["flagged"][plant_id] = "watered"
        reply = f"Marked {plant['name']} as watered 🌱"
    elif action == "damp":
        plant["learned_adjustment_days"] = bump_learned_adjustment(plant, today)
        plant["learned_adjustment_last_bump"] = today.isoformat()
        plant["deferred_until"] = (today + timedelta(days=2)).isoformat()
        daily["flagged"][plant_id] = "damp"
        reply = f"Noted - checking {plant['name']} again in a couple of days."
    else:  # notyet
        daily["flagged"][plant_id] = "notyet"
        reply = f"OK, {plant['name']} will come up again tomorrow if still due."

    save_plants(plants)
    save_daily(daily)
    return reply


if __name__ == "__main__":
    callback_data = sys.argv[1] if len(sys.argv) > 1 else ""
    print(handle_callback(callback_data))
