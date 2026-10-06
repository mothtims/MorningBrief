"""
Weekend-only plant check: Sat/Sun ~09:00 (PLANT_CARE_PROPOSAL.md
section 9, option (b)) - the existing text/voice brief pipeline only
runs weekdays (com.morningbrief.scheduled.plist has no Saturday/Sunday
entries), which left basil's 2-4 day range able to silently cross its
whole range over a weekend with zero warning. This is plant-only,
text-only: no train/weather/news, just whatever
plant_care.summarize_plants() has to say (including the ahead-of-heat
warning, same as the weekday morning brief), sent via send_message.py
if there's anything to report.

Also the daily "establish today's flagged plants" moment for
Saturdays/Sundays specifically, mirroring brief.py's role on weekdays -
summarize_plants() is the single writer of new "pending" entries in
state/plant_daily.json (see plant_care.py's module docstring); this
script calling it on a weekend is what makes plant_checkin.py's 19:30
run (now seven days a week) have anything to check in on.

Silent when there's nothing to report - same "absence costs nothing"
contract as every other optional section in this project.
"""

from __future__ import annotations

import subprocess
import sys

from brief import load_config
from logutil import get_logger
from plant_care import summarize_plants

log = get_logger("plant_weekend")

SEND_MESSAGE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_message.py"


def main() -> None:
    try:
        config = load_config()
        text = summarize_plants(config)
    except Exception as exc:
        log.error("Weekend plant check failed: %s", exc, exc_info=True)
        return

    if not text:
        log.info("Nothing to report - silent weekend check")
        return

    try:
        result = subprocess.run(
            [sys.executable, SEND_MESSAGE_SCRIPT],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("Weekend plant check send failed: %s", result.stderr.strip())
            return
    except Exception as exc:
        log.error("Weekend plant check send failed: %s", exc, exc_info=True)
        return

    log.info("Weekend plant check sent")


if __name__ == "__main__":
    main()
