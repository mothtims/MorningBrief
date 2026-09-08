"""
Orchestrator: picks the relevant commute leg based on time of day, calls
the fetchers, and assembles the final Telegram message. This is what
bridge.py invokes directly as a subprocess when it sees the configured
trigger phrase - no LLM tool access involved in the fetching itself
(see README.md for why).

Split into a data layer (gather_brief_data) and a presentation layer
(format_text) so the voice pipeline (see voice_script.py, VOICE_PROPOSAL.md)
can consume the same underlying facts without going through the
emoji-joined text format built for Telegram. build_brief() keeps its
original signature and behavior for the existing text delivery paths.

Section rotation (ADR-0002, DECISIONS.md): the 07:00 send carries
politics, 16:30 carries tech news instead - is_morning_send() is the
single source of truth for that split, reused for leg selection too,
rather than a second independent time check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from calendar_events import summarize_calendar
from politics import summarize_politics
from tech_news import summarize_tech
from trains import summarize_leg
from tv_watchlist import summarize_tv_watchlist
from weather import summarize_weather

CONFIG_PATH = Path(__file__).resolve().parent / "config.local.json"
LEG_SWITCH_HOUR = 13  # before this hour -> morning send, after -> afternoon send


@dataclass
class BriefData:
    train_line: str
    weather_line: str
    news_label: str
    news_line: str
    calendar_line: str
    tv_line: str


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing {CONFIG_PATH}. Copy config.example.json and fill it in.")
    return json.loads(CONFIG_PATH.read_text())


def is_morning_send(now_hour: int | None = None) -> bool:
    hour = now_hour if now_hour is not None else datetime.now().hour
    return hour < LEG_SWITCH_HOUR


def pick_leg(config: dict, morning: bool) -> dict:
    return config["morning_leg"] if morning else config["evening_leg"]


def gather_brief_data() -> BriefData:
    config = load_config()
    morning = is_morning_send()
    leg = pick_leg(config, morning)

    return BriefData(
        train_line=summarize_leg(leg["from"], leg["to"], leg["departs"]),
        weather_line=summarize_weather(config["home_postcode"]),
        news_label="Politics headlines" if morning else "Tech news",
        news_line=summarize_politics() if morning else summarize_tech(),
        calendar_line=summarize_calendar(config.get("calendar_allowlist", [])),
        tv_line=summarize_tv_watchlist(config.get("tv_watchlist", [])),
    )


def format_text(data: BriefData) -> str:
    sections = [
        f"📅 {data.calendar_line}",
        f"🚆 {data.train_line}",
        f"🌤 {data.weather_line}",
    ]
    if data.tv_line:
        sections.append(f"📺 {data.tv_line}")
    sections.append(f"📰 {data.news_line}")
    return "\n\n".join(sections)


def build_brief() -> str:
    return format_text(gather_brief_data())


if __name__ == "__main__":
    print(build_brief())
