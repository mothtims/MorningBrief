"""
Free-text plant logging: "watered the basil", "watered everything on
the kitchen windowsill". CLI entry point for the Telegram bridge's
text_patterns routing (prefix "watered ") - see
PLANT_CARE_PROPOSAL.md section 4h.

Matching is one-direction only: a plant's match_terms or location must
appear as a substring WITHIN the input, never the reverse. The reverse
direction was the original (rejected) design - a short input like
"watered a" would match almost every plant, since "a" is a substring
of most plant names. "everything"/"all" (matched as whole words, not
substrings - "small" shouldn't trigger it) logs every plant regardless
of match_terms/location.

Deliberately no fuzzy/NLP matching - explicit match_terms per plant in
state/plants.json, consistent with this project's established
"config-driven rules, not model inference" preference (DECISIONS.md
ADR-0005).
"""

from __future__ import annotations

import re
import sys
from datetime import date

from plant_care import load_daily, load_plants, save_daily, save_plants

ALL_WORDS = {"everything", "all"}


def _mentioned(plant: dict, lowered_input: str) -> bool:
    if plant["location"].lower() in lowered_input:
        return True
    return any(term.lower() in lowered_input for term in plant.get("match_terms", []))


def log_watering(raw_input: str) -> str:
    plants = load_plants()
    lowered = raw_input.lower()
    tokens = set(re.findall(r"[a-z']+", lowered))

    if tokens & ALL_WORDS:
        matched = plants
    else:
        matched = [p for p in plants if _mentioned(p, lowered)]

    if not matched:
        return (
            f'Didn\'t match any plant to "{raw_input}" - try a plant name, '
            'its location (e.g. "kitchen windowsill"), or "everything"/"all".'
        )

    today = date.today()
    daily = load_daily(today)
    lines = []
    for plant in matched:
        plant["last_watered"] = today.isoformat()
        plant["deferred_until"] = None
        if plant["id"] in daily["flagged"]:
            daily["flagged"][plant["id"]] = "watered"
        lines.append(f"Watered: {plant['name']} ({plant['location']})")
    save_plants(plants)
    save_daily(daily)

    return "\n".join(lines)


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    print(log_watering(text))
