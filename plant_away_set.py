"""
CLI entry point for "/plants away ..." (routed via the Telegram
bridge's text_patterns - see PLANT_CARE_PROPOSAL.md section 5 and
Bizkit's config.local.json). Takes either a number of days ("5") or an
explicit return date ("2026-10-15") as its one argument - two separate
tiny scripts (this one and plant_away_clear.py) rather than one script
trying to infer which command fired it, since the bridge only passes
the matched remainder, not which prefix matched it.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from plant_away import set_manual_away


def parse_away_arg(arg: str) -> date:
    arg = arg.strip()
    if arg.isdigit():
        return date.today() + timedelta(days=int(arg))
    return date.fromisoformat(arg)


if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        away_until = parse_away_arg(raw)
    except ValueError:
        print(f'Didn\'t understand "{raw}" - try a number of days ("5") or a date ("2026-10-15").')
        sys.exit(0)

    set_manual_away(away_until)
    print(f"Plant reminders paused until {away_until.strftime('%b %-d')}.")
