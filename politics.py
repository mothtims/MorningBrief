"""
UK politics headline summary: BBC politics RSS -> a small number of
recent headlines -> a single claude -p call with NO tool access (see
.claude/settings-notools.json) to turn them into a short paragraph.

No tool access is deliberate, not incidental: the fed-in text is
third-party content this process doesn't control, so the summarization
step should have nothing it could be tricked into *doing* - only
something it could be tricked into *saying*, which is a much smaller
problem for a personal daily brief.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from httputil import get_bytes
from logutil import get_logger

log = get_logger("politics")

RSS_URL = "https://feeds.bbci.co.uk/news/politics/rss.xml"
SETTINGS_PATH = Path(__file__).resolve().parent / ".claude" / "settings-notools.json"
HEADLINE_COUNT = 4


def fetch_headlines(count: int = HEADLINE_COUNT) -> list[tuple[str, str]]:
    xml_bytes = get_bytes(RSS_URL, log, headers={"User-Agent": "MorningBrief/0.1"})
    root = ET.fromstring(xml_bytes)
    items = root.findall("./channel/item")[:count]
    return [
        (item.findtext("title", default="").strip(), item.findtext("description", default="").strip())
        for item in items
    ]


def summarize_politics() -> str:
    try:
        headlines = fetch_headlines()
    except Exception as exc:
        log.error("Headline fetch failed after retries: %s", exc, exc_info=True)
        return f"Politics headlines unavailable right now ({exc})."

    if not headlines:
        return "No politics headlines available right now."

    headline_text = "\n".join(f"- {title}: {desc}" for title, desc in headlines)
    prompt = (
        "Summarize these UK politics headlines into a short, neutral paragraph "
        "(3-4 sentences) suitable for a morning briefing. Do not add commentary "
        "or facts beyond what's given. Just the summary text, nothing else:\n\n"
        f"{headline_text}"
    )

    result = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--permission-mode",
            "dontAsk",
            "--settings",
            str(SETTINGS_PATH),
            "--output-format",
            "json",
        ],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        log.error(
            "claude -p summarization failed (exit %s): stderr=%r",
            result.returncode,
            result.stderr[:2000],
        )
        # Fall back to a plain headline list rather than fail the whole brief.
        return "Headlines: " + "; ".join(title for title, _ in headlines)

    import json

    try:
        parsed = json.loads(result.stdout)
        return parsed.get("result") or parsed.get("response") or result.stdout.strip()
    except json.JSONDecodeError:
        return result.stdout.strip()


if __name__ == "__main__":
    print(summarize_politics())
