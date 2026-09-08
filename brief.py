"""
Orchestrator: picks the relevant commute leg based on time of day, calls
the three fetchers, and assembles the final Telegram message. This is
what bridge.py invokes directly as a subprocess when it sees the
configured trigger phrase - no LLM tool access involved in the fetching
itself (see README.md for why).

Split into a data layer (gather_brief_data) and a presentation layer
(format_text) so the voice pipeline (see voice/, VOICE_PROPOSAL.md) can
consume the same underlying facts without going through the emoji-joined
text format built for Telegram. build_brief() keeps its original
signature and behavior for the existing text delivery paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from calendar_events import summarize_calendar
from politics import summarize_politics
from trains import summarize_leg
from weather import summarize_weather

CONFIG_PATH = Path(__file__).resolve().parent / "config.local.json"
LEG_SWITCH_HOUR = 13  # before this hour -> morning leg, after -> evening leg


@dataclass
class BriefData:
    train_line: str
    weather_line: str
    politics_line: str
    calendar_line: str


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing {CONFIG_PATH}. Copy config.example.json and fill it in.")
    return json.loads(CONFIG_PATH.read_text())


def pick_leg(config: dict) -> dict:
    now_hour = datetime.now().hour
    return config["morning_leg"] if now_hour < LEG_SWITCH_HOUR else config["evening_leg"]


def gather_brief_data() -> BriefData:
    config = load_config()
    leg = pick_leg(config)

    return BriefData(
        train_line=summarize_leg(leg["from"], leg["to"], leg["departs"]),
        weather_line=summarize_weather(config["home_postcode"]),
        politics_line=summarize_politics(),
        calendar_line=summarize_calendar(config.get("calendar_allowlist", [])),
    )


def format_text(data: BriefData) -> str:
    return (
        f"📅 {data.calendar_line}\n\n"
        f"🚆 {data.train_line}\n\n"
        f"🌤 {data.weather_line}\n\n"
        f"📰 {data.politics_line}"
    )


def build_brief() -> str:
    return format_text(gather_brief_data())


if __name__ == "__main__":
    print(build_brief())
