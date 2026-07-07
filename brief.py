"""
Orchestrator: picks the relevant commute leg based on time of day, calls
the three fetchers, and assembles the final Telegram message. This is
what bridge.py invokes directly as a subprocess when it sees the
configured trigger phrase - no LLM tool access involved in the fetching
itself (see README.md for why).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from politics import summarize_politics
from trains import summarize_leg
from weather import summarize_weather

CONFIG_PATH = Path(__file__).resolve().parent / "config.local.json"
LEG_SWITCH_HOUR = 13  # before this hour -> morning leg, after -> evening leg


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing {CONFIG_PATH}. Copy config.example.json and fill it in.")
    return json.loads(CONFIG_PATH.read_text())


def pick_leg(config: dict) -> dict:
    now_hour = datetime.now().hour
    return config["morning_leg"] if now_hour < LEG_SWITCH_HOUR else config["evening_leg"]


def build_brief() -> str:
    config = load_config()
    leg = pick_leg(config)

    train_line = summarize_leg(leg["from"], leg["to"], leg["departs"])
    weather_line = summarize_weather(config["home_postcode"])
    politics_line = summarize_politics()

    return (
        f"🚆 {train_line}\n\n"
        f"🌤 {weather_line}\n\n"
        f"📰 {politics_line}"
    )


if __name__ == "__main__":
    print(build_brief())
