"""
Shared logging for the fetchers. Added 2026-07-30 after a weather
failure was only visible by reading the delivered Telegram message —
nothing was logged anywhere, so there was no way to diagnose it after
the fact. See CHANGELOG.md for the incident this was added for.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"
LOG_FILE = STATE_DIR / "morningbrief.log"


def get_logger(name: str) -> logging.Logger:
    STATE_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger(f"morningbrief.{name}")
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
