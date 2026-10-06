"""
CLI entry point for "/plants back" (routed via the Telegram bridge's
custom_commands - exact match, no argument needed, unlike "/plants
away N" which needs text_patterns for its variable remainder - see
PLANT_CARE_PROPOSAL.md section 5).
"""

from __future__ import annotations

from plant_away import clear_away

if __name__ == "__main__":
    clear_away()
    print("Welcome back - plant reminders resumed.")
