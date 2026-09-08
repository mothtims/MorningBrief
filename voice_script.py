"""
Turns the structured brief data into a natural, ~60-90s spoken-word
script via the Anthropic API directly (the `anthropic` SDK) - not the
`claude -p` CLI pattern politics.py uses. Confirmed as a deliberate,
separate integration point; see VOICE_PROPOSAL.md open question 1.

No tool access: this call is deliberately a pure text-in/text-out
request with no tools declared, matching the same reasoning already
applied to politics.py's summarization step - the input is data our own
fetchers produced, but keeping the synthesis step tool-free is cheap
insurance and keeps the security posture consistent project-wide.
"""

from __future__ import annotations

import subprocess
from datetime import datetime

import anthropic

from brief import BriefData
from logutil import get_logger

log = get_logger("voice.script")

KEYCHAIN_SERVICE_NAME = "morningbrief-anthropic-api-key"
MODEL = "claude-opus-4-8"


def _time_of_day_label(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if hour < 12:
        return "morning"
    elif hour < 18:
        return "afternoon"
    else:
        return "evening"


SCRIPT_PROMPT_TEMPLATE = """\
You're writing a spoken daily briefing script for one person, to be \
read aloud by a text-to-speech voice at a natural, unhurried pace. It's \
currently the {time_of_day} - open with a greeting appropriate to that \
(e.g. "good {time_of_day}"), not necessarily "good morning." \
Target 140-170 words total - that's roughly 60-90 seconds spoken aloud, \
which matters more than hitting an exact word count.

Tone: warm and cheerful, like a friend giving you the rundown before \
you head out the door - not a newsreader, not a corporate assistant. \
Short sentences. Use contractions (it's, you're, that's). Talk \
directly to the listener ("you," "your train") rather than describing \
things in third person. Light humour is welcome if something in the \
data genuinely invites it - never forced, and never at the expense of \
clarity on anything practical like delays or cancellations. Avoid \
list-like phrasing ("first... next... finally...") - let one thing \
lead conversationally into the next the way a person actually talks.

Given the data below - today's calendar, train status, weather, and \
news, plus TV when there's an upcoming episode - turn it into that \
kind of script. Be concise rather than elaborating on each item. If \
you need to trim to stay in budget, shorten or drop the news section \
first, then TV if present - calendar and train details should never \
be cut. If a data point is unavailable or degraded, mention that \
naturally rather than skipping it silently. Output only the script \
text - no headers, no labels, no markdown.

{data_block}
"""


def _load_api_key() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE_NAME, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read Anthropic API key from Keychain "
            f"(service '{KEYCHAIN_SERVICE_NAME}'): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def generate_script(data: BriefData) -> str:
    """Raises on failure - caller (scheduled_send_voice.py) handles the
    fallback-to-text degradation contract, not this module."""
    client = anthropic.Anthropic(api_key=_load_api_key())

    data_lines = [
        f"Calendar: {data.calendar_line}",
        f"Train: {data.train_line}",
        f"Weather: {data.weather_line}",
    ]
    if data.tv_line:
        data_lines.append(f"TV: {data.tv_line}")
    data_lines.append(f"{data.news_label}: {data.news_line}")

    prompt = SCRIPT_PROMPT_TEMPLATE.format(
        time_of_day=_time_of_day_label(),
        data_block="\n\n".join(data_lines),
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    script = "".join(text_blocks).strip()

    if not script:
        raise RuntimeError("Claude API returned no text content for the script")

    log.info("Generated %d-char spoken script (%d words)", len(script), len(script.split()))
    return script


if __name__ == "__main__":
    from brief import gather_brief_data

    print(generate_script(gather_brief_data()))
