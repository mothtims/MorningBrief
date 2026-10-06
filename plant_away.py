"""
Away mode for plant reminders: pauses the normal per-plant flagging in
favour of a one-line summary of what falls due while away, and tells
plant_checkin.py (the evening check-in) to skip entirely. See
PLANT_CARE_PROPOSAL.md section 5 for the full design.

Two sources, composing rather than competing:
  - Manual override ("/plants away N" / "/plants back", routed by the
    Telegram bridge's text_patterns/custom_commands - see
    plant_away_set.py/plant_away_clear.py). Always wins when valid.
  - Calendar detection (automatic): an all-day, genuinely multi-day
    event (more than one calendar day), whose title contains a
    configured away keyword, AND that the simplified household
    heuristic below attributes to the listener rather than someone
    else. Persisted to state/plant_away.json (source="calendar") the
    first time it's detected, so other callers (plant_checkin.py,
    plant_weekend.py) see the same determination without each
    re-scanning the calendar.

Household attribution here is a deliberate SIMPLIFICATION of the full
plain-English attribution_rules fed to the voice-script prompt
(DECISIONS.md ADR-0005) - those rules are designed for an LLM to apply
with nuance (pickups, child-only activities, implications). Away
detection only needs one narrow yes/no: does this event's title name
some other adult, in which case it's clearly not the listener's own
trip. config["household"]["other_adult_names"] is a new, separate,
explicit list (first names only) for exactly this narrow check - kept
apart from attribution_rules/implication_rules, which stay prose aimed
at a model, not data aimed at a string-match.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from logutil import get_logger

log = get_logger("plant_away")

AWAY_PATH = Path(__file__).resolve().parent / "state" / "plant_away.json"
DEFAULT_AWAY_KEYWORDS = ["away", "holiday", "trip"]


def _read_away_file() -> dict | None:
    if not AWAY_PATH.exists():
        return None
    try:
        return json.loads(AWAY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_away_file(state: dict) -> None:
    AWAY_PATH.write_text(json.dumps(state, indent=2) + "\n")


def _clear_away_file() -> None:
    if AWAY_PATH.exists():
        AWAY_PATH.unlink()


def set_manual_away(away_until: date) -> None:
    _write_away_file({"away_until": away_until.isoformat(), "source": "command"})


def clear_away() -> None:
    _clear_away_file()


def _mentions_other_adult(title: str, other_adult_names: list[str]) -> bool:
    lowered = title.lower()
    return any(
        re.search(rf"\b{re.escape(name.lower())}\b", lowered) for name in other_adult_names
    )


def _detect_calendar_away(config: dict) -> dict | None:
    import calendar_events

    allowed_calendars = config.get("calendar_allowlist", [])
    if not allowed_calendars:
        return None

    keywords = [k.lower() for k in config.get("plant_away_keywords", DEFAULT_AWAY_KEYWORDS)]
    other_adult_names = config.get("household", {}).get("other_adult_names", [])
    today = date.today()

    try:
        events = calendar_events.get_events(allowed_calendars, days_back=1, days_ahead=60)
    except Exception as exc:
        log.warning("Calendar read failed during away detection: %s", exc)
        return None

    candidates = []
    for ev in events:
        if not ev["all_day"]:
            continue
        span_days = (ev["end"].date() - ev["start"].date()).days
        if span_days < 1:
            continue  # single-day all-day event - not "away," e.g. a one-off school non-uniform day
        title_lower = ev["title"].lower()
        if not any(kw in title_lower for kw in keywords):
            continue
        if _mentions_other_adult(ev["title"], other_adult_names):
            continue  # someone else's trip, not the listener's
        if ev["start"].date() <= today <= ev["end"].date():
            candidates.append(ev)

    if not candidates:
        return None

    # If multiple qualifying events somehow overlap today, use the
    # latest end date - the longer one governs.
    latest = max(candidates, key=lambda ev: ev["end"].date())
    return {"away_until": latest["end"].date().isoformat(), "source": "calendar"}


def get_effective_away_state(config: dict) -> dict | None:
    """Manual override always wins over calendar detection when both
    are present and the manual one hasn't lapsed. Returns None (not
    away) if neither applies, clearing any stale file found along the
    way."""
    today = date.today()
    stored = _read_away_file()

    if stored and stored.get("source") == "command":
        away_until = date.fromisoformat(stored["away_until"])
        if away_until >= today:
            return stored
        # Manual override expired - fall through to re-check calendar.

    detected = _detect_calendar_away(config)
    if detected:
        _write_away_file(detected)
        return detected

    if stored:
        _clear_away_file()
    return None


if __name__ == "__main__":
    from brief import load_config

    state = get_effective_away_state(load_config())
    print(state or "(not away)")
