"""
Tech news summary for the afternoon send: Ars Technica + BBC Technology
RSS -> a small number of recent headlines from each -> a single
claude -p call with NO tool access (see .claude/settings-notools.json),
same pattern as politics.py. See TV_TECH_PROPOSAL.md section 2 for why
these two feeds (both proper RSS 2.0 - The Verge is Atom and was
skipped to avoid a second parser branch for one feed).
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from httputil import get_bytes
from logutil import get_logger

log = get_logger("tech_news")

FEED_URLS = [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
]
SETTINGS_PATH = Path(__file__).resolve().parent / ".claude" / "settings-notools.json"
HEADLINES_PER_FEED = 3

# Absolute path, not a bare "claude" lookup - see politics.py's docstring
# for why (same launchd PATH gotcha).
CLAUDE_BINARY = "/Users/mothtims/.local/bin/claude"


def fetch_headlines(count_per_feed: int = HEADLINES_PER_FEED) -> list[tuple[str, str]]:
    headlines = []
    for url in FEED_URLS:
        xml_bytes = get_bytes(url, log, headers={"User-Agent": "MorningBrief/0.1"})
        root = ET.fromstring(xml_bytes)
        items = root.findall("./channel/item")[:count_per_feed]
        headlines.extend(
            (item.findtext("title", default="").strip(), item.findtext("description", default="").strip())
            for item in items
        )
    return headlines


def summarize_tech() -> str:
    try:
        headlines = fetch_headlines()
    except Exception as exc:
        log.error("Tech headline fetch failed after retries: %s", exc, exc_info=True)
        return f"Tech news unavailable right now ({exc})."

    if not headlines:
        return "No tech news available right now."

    headline_text = "\n".join(f"- {title}: {desc}" for title, desc in headlines)
    prompt = (
        "Summarize these technology headlines into a short, neutral paragraph "
        "(3-4 sentences) suitable for a daily briefing. Do not add commentary "
        "or facts beyond what's given. Just the summary text, nothing else:\n\n"
        f"{headline_text}"
    )

    try:
        result = subprocess.run(
            [
                CLAUDE_BINARY,
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
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.error("claude -p invocation failed to run at all: %s", exc, exc_info=True)
        return "Headlines: " + "; ".join(title for title, _ in headlines)

    if result.returncode != 0:
        log.error(
            "claude -p summarization failed (exit %s): stdout=%r stderr=%r",
            result.returncode,
            result.stdout[:2000],
            result.stderr[:2000],
        )
        return "Headlines: " + "; ".join(title for title, _ in headlines)

    import json

    try:
        parsed = json.loads(result.stdout)
        return parsed.get("result") or parsed.get("response") or result.stdout.strip()
    except json.JSONDecodeError:
        return result.stdout.strip()


if __name__ == "__main__":
    print(summarize_tech())
