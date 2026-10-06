"""
Houseplant watering model and morning-brief integration. See
PLANT_CARE_PROPOSAL.md for the full investigation and DECISIONS.md
ADR-0006 for the model's reasoning.

Three state files (all gitignored, all under state/, genuinely state
not config - they change daily):
  - state/plants.json       durable per-plant facts: name, location,
                             base range_days (never mutated by the
                             model), last_watered, learned_adjustment_days
                             (grows on "still damp", decays over time),
                             care_note (the watering-method text shown
                             to the user, e.g. pink quill's "a small
                             drink and a mist, not a soak").
  - state/plant_daily.json  today's flagged plants and their response
                             status (pending/watered/damp/notyet) -
                             overwritten daily, not accumulated. Single-
                             writer model: summarize_plants() is the
                             only thing that adds new "pending" entries
                             (merge, never overwrite an existing
                             status); plant_callback.py/plant_log.py
                             only ever update an existing entry's
                             status, never add new ones.
  - state/plant_away.json   written/read by plant_away.py.

The brief always displays each plant's ORIGINAL configured range_days
("usual 2-4"), never the computed effective range - the adjustment
model changes WHEN a plant gets flagged, not the number shown for it.
days_since(last_watered) is always the real, honest day count.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from logutil import get_logger

log = get_logger("plant_care")

STATE_DIR = Path(__file__).resolve().parent / "state"
PLANTS_PATH = STATE_DIR / "plants.json"
DAILY_PATH = STATE_DIR / "plant_daily.json"

DEFAULT_CARE_NOTE = "finger test, water if the top inch is dry"

# --- Seasonal multiplier: a tunable month lookup, not a formula ---
# Anchored so October/April (the user's own calibration month for the
# base ranges) sit at 1.0 - no change from the numbers given. Stretches
# further into winter (slower growth, less light), compresses through
# summer (thirstier). Each value independently tunable; see ADR-0006.
SEASONAL_MULTIPLIER = {
    1: 1.25, 2: 1.25,            # Jan, Feb - deep winter
    3: 1.10,                     # Mar
    4: 1.00,                     # Apr - reference
    5: 0.95,                     # May
    6: 0.85, 7: 0.85, 8: 0.85,   # Jun-Aug - summer, thirstiest
    9: 0.95,                     # Sep
    10: 1.00,                    # Oct - reference (calibration month)
    11: 1.10,                    # Nov
    12: 1.25,                    # Dec - deep winter
}

# --- Temperature factor: asymmetric, heat-dominant ---
# Cold floors at a mild 0.95 (heating dries the air, slight thirst
# increase despite the cold). Heat escalates in three steps. 30C+ is
# handled separately as a hard override (every plant -> daily check),
# not as a temperature_factor() return value - see effective_range().
COLD_FACTOR = 0.95
WARM_FACTOR = 0.85
HOT_FACTOR = 0.65
COLD_THRESHOLD_C = 10
WARM_THRESHOLD_C = 25
HOT_THRESHOLD_C = 28
DAILY_OVERRIDE_THRESHOLD_C = 30

# --- Learned adjustment: cap and decay (both tunable) ---
# "Still damp" nudges a plant's effective range longer over time - but
# without a ceiling, a wet winter's learning would quietly persist into
# next summer, and without decay, a single damp spell could permanently
# bias a plant's schedule. Cap is relative to the plant's own base
# upper bound, not a fixed day count, so it scales sensibly across
# plants with very different base ranges (basil's cap is tiny; the
# dragon tree's is much larger).
LEARNED_ADJUSTMENT_CAP_FRACTION = 0.5    # max +50% of range_days[1]
LEARNED_ADJUSTMENT_DECAY_PER_PERIOD = 1  # days shaved off per period
LEARNED_ADJUSTMENT_DECAY_PERIOD_DAYS = 28  # ~4 weeks


def load_plants() -> list[dict]:
    return json.loads(PLANTS_PATH.read_text())["plants"]


def save_plants(plants: list[dict]) -> None:
    PLANTS_PATH.write_text(json.dumps({"plants": plants}, indent=2) + "\n")


def find_plant(plants: list[dict], plant_id: str) -> dict | None:
    return next((p for p in plants if p["id"] == plant_id), None)


def load_daily(today: date) -> dict:
    """Returns {"date": ..., "flagged": {...}} for TODAY specifically -
    a file from a stale/previous day is treated as if it didn't exist,
    per the explicit instruction that a stale file means nothing
    pending, not yesterday's pending list."""
    if not DAILY_PATH.exists():
        return {"date": today.isoformat(), "flagged": {}}
    try:
        data = json.loads(DAILY_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"date": today.isoformat(), "flagged": {}}
    if data.get("date") != today.isoformat():
        return {"date": today.isoformat(), "flagged": {}}
    return data


def save_daily(daily: dict) -> None:
    DAILY_PATH.write_text(json.dumps(daily, indent=2) + "\n")


def seasonal_multiplier(month: int) -> float:
    return SEASONAL_MULTIPLIER[month]


def temperature_factor(forecast_high_c: float) -> float:
    """Does not itself implement the 30C+ daily-override - that's a
    distinct hard override applied by effective_range(), not a point on
    this continuum, since "every plant becomes a daily check" isn't
    expressible as a multiplier on a range that might be much longer
    than 1 day."""
    if forecast_high_c <= COLD_THRESHOLD_C:
        return COLD_FACTOR
    if forecast_high_c <= WARM_THRESHOLD_C:
        return 1.0
    if forecast_high_c <= HOT_THRESHOLD_C:
        return WARM_FACTOR
    return HOT_FACTOR


def decayed_learned_adjustment(plant: dict, today: date) -> float:
    """Read-only: computes the current, decayed value from the stored
    raw value and last-bump date, without writing anything back. Decay
    is only ever persisted implicitly, as part of the next bump (see
    bump_learned_adjustment) - there's no separate daily decay job."""
    raw = plant.get("learned_adjustment_days", 0) or 0
    if raw <= 0:
        return 0.0
    last_bump = plant.get("learned_adjustment_last_bump")
    if not last_bump:
        return max(0.0, raw)
    days_since = (today - date.fromisoformat(last_bump)).days
    periods = days_since // LEARNED_ADJUSTMENT_DECAY_PERIOD_DAYS
    return max(0.0, raw - periods * LEARNED_ADJUSTMENT_DECAY_PER_PERIOD)


def bump_learned_adjustment(plant: dict, today: date) -> float:
    """The new value to store after a "still damp" signal - decay-to-date
    applied first, then +1, then capped at LEARNED_ADJUSTMENT_CAP_FRACTION
    of the plant's own base upper bound."""
    current = decayed_learned_adjustment(plant, today)
    cap = plant["range_days"][1] * LEARNED_ADJUSTMENT_CAP_FRACTION
    return min(current + 1, cap)


def effective_low(plant: dict, month: int, forecast_high_c: float, today: date) -> float:
    if forecast_high_c >= DAILY_OVERRIDE_THRESHOLD_C:
        return 1.0
    base_low = plant["range_days"][0]
    adjustment = decayed_learned_adjustment(plant, today)
    return base_low * seasonal_multiplier(month) * temperature_factor(forecast_high_c) + adjustment


def is_due(plant: dict, today: date, effective_low_days: float) -> bool:
    deferred_until = plant.get("deferred_until")
    if deferred_until and date.fromisoformat(deferred_until) > today:
        return False
    last_watered = date.fromisoformat(plant["last_watered"])
    days_since = (today - last_watered).days
    return days_since >= effective_low_days


def _days_since(plant: dict, today: date) -> int:
    return (today - date.fromisoformat(plant["last_watered"])).days


def _format_due_line(due_plants: list[dict], today: date) -> str:
    bits = []
    for plant in due_plants:
        low, high = plant["range_days"]
        days_since = _days_since(plant, today)
        care_note = plant.get("care_note") or DEFAULT_CARE_NOTE
        bits.append(
            f"{plant['name']}'s at day {days_since} of its usual {low}-{high} ({care_note})"
        )
    return "🌱 " + "; ".join(bits) + "."


def _away_summary_line(plants: list[dict], away_until: date, today: date, month: int) -> str:
    due_while_away = []
    for plant in plants:
        # Projected forward with no temperature adjustment (no forecast
        # that far out) - seasonal only, a reasonable approximation for
        # "roughly when will this need attention."
        low = plant["range_days"][0] * seasonal_multiplier(month)
        last_watered = date.fromisoformat(plant["last_watered"])
        due_date = last_watered + timedelta(days=low)
        if today <= due_date <= away_until:
            due_while_away.append((plant["name"], due_date))
    if not due_while_away:
        return f"🌱 You're away until {away_until.strftime('%b %-d')} - nothing due while you're gone."
    due_while_away.sort(key=lambda item: item[1])
    bits = [f"{name} (~{due_date.strftime('%b %-d')})" for name, due_date in due_while_away]
    return f"🌱 You're away until {away_until.strftime('%b %-d')} - due while away: " + ", ".join(bits) + "."


def _ahead_of_heat_line(today_high: float, tomorrow_high: float) -> str:
    return (
        f"🌱 Heads up - tomorrow's forecast is {tomorrow_high:.0f}°C, "
        "so give everything a quick check today just in case."
    )


def summarize_plants(config: dict) -> str:
    """The brief's single entry point - never raises, matching the
    degrade-independently contract every other fetcher follows. Also
    performs the one necessary side effect (merging newly-due plants
    into state/plant_daily.json as "pending") so the evening check-in
    has something to read; see the module docstring's "single-writer
    model" note for why this merges rather than overwrites."""
    try:
        plants = load_plants()
    except Exception as exc:
        log.error("Plant state read failed: %s", exc, exc_info=True)
        return f"Plant check unavailable right now ({exc})."

    today = date.today()
    month = today.month

    import plant_away  # local import: avoids a circular import, since
    # plant_away.py's calendar-detection path doesn't need plant_care at
    # module-load time, only when actually checking away status.

    away = plant_away.get_effective_away_state(config)
    if away:
        away_until = date.fromisoformat(away["away_until"])
        daily = load_daily(today)
        save_daily(daily)  # nothing pending while away - see module docstring
        return _away_summary_line(plants, away_until, today, month)

    try:
        today_high, tomorrow_high = weather_highs(config)
    except Exception as exc:
        log.warning("Forecast fetch failed for plant temperature factor: %s", exc)
        today_high, tomorrow_high = 18.0, 18.0  # mid-band -> factor 1.0, no adjustment

    due_plants = []
    for plant in plants:
        low = effective_low(plant, month, today_high, today)
        if is_due(plant, today, low):
            due_plants.append(plant)

    daily = load_daily(today)
    for plant in due_plants:
        daily["flagged"].setdefault(plant["id"], "pending")
    save_daily(daily)

    lines = []
    if tomorrow_high >= HOT_THRESHOLD_C and today_high < HOT_THRESHOLD_C:
        lines.append(_ahead_of_heat_line(today_high, tomorrow_high))
    if due_plants:
        lines.append(_format_due_line(due_plants, today))

    log.info(
        "%d plant(s) due today (of %d total); ahead-of-heat warning: %s",
        len(due_plants), len(plants), tomorrow_high >= HOT_THRESHOLD_C and today_high < HOT_THRESHOLD_C,
    )
    return " ".join(lines)


def weather_highs(config: dict) -> tuple[float, float]:
    import weather

    highs = weather.forecast_highs(config["home_postcode"], days=2)
    return highs[0], highs[1]


if __name__ == "__main__":
    from brief import load_config

    print(summarize_plants(load_config()) or "(nothing due - silent by design)")
