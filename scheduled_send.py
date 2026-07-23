"""
Scheduled entry point for proactive delivery. Invoked by launchd twice
on weekdays (see launchd/) - builds the brief and sends it via Bizkit's
send_message.py, independent of the polling bridge. Not used for the
manual /brief command, which goes through bridge.py's custom_commands
instead (see README.md for the two separate paths).
"""

from __future__ import annotations

import subprocess
import sys

from brief import build_brief

SEND_MESSAGE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_message.py"


def main() -> None:
    text = build_brief()
    result = subprocess.run(
        [sys.executable, SEND_MESSAGE_SCRIPT],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        # Runs unattended - nowhere to report failure except launchd's
        # own stderr log (see launchd/ plist: StandardErrorPath).
        print(f"Failed to send scheduled brief: {result.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
