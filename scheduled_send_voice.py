"""
Scheduled entry point for the voice edition. Separate launchd job from
scheduled_send.py (weekday mornings only, not the twice-daily text
schedule) so a voice-pipeline failure can never affect the existing
text brief's reliability - see VOICE_PROPOSAL.md section 4, "the
degradation contract".

Runs alongside the existing text brief, not instead of it (confirmed
decision, VOICE_PROPOSAL.md section 8) - if this script falls back to
text on a voice-pipeline failure, and the regular scheduled_send.py
also fires that morning, the result is a duplicate text message, not
silence. That's an intentional tradeoff: worst case is redundant, never
silent.

Layered fallback, not one big try/except - each stage falls back to the
last-known-good delivery mechanism (send_message.py, the same one
scheduled_send.py already uses) rather than failing the whole run:
  - script generation fails       -> send text brief instead
  - TTS fails                     -> send text brief instead
  - audio conversion fails        -> send text brief instead
  - Telegram voice upload fails   -> send text brief instead
(No storage/R2 step yet - that's v2, not in this file.)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from brief import format_text, gather_brief_data
from logutil import get_logger
from voice_audio_convert import wav_to_opus
from voice_script import generate_script
from voice_tts import synthesize_to_wav

log = get_logger("scheduled_send_voice")

SEND_MESSAGE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_message.py"
SEND_VOICE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_voice.py"


def send_text_fallback(text: str, reason: str) -> None:
    log.warning("Falling back to text brief (%s)", reason)
    result = subprocess.run(
        [sys.executable, SEND_MESSAGE_SCRIPT],
        input=text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        log.error("Text fallback also failed: %s", result.stderr.strip())
        sys.exit(1)


def send_voice_note(ogg_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, SEND_VOICE_SCRIPT, str(ogg_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())


def main() -> None:
    data = gather_brief_data()
    text = format_text(data)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        try:
            script = generate_script(data)
        except Exception as exc:
            log.error("Script generation failed: %s", exc, exc_info=True)
            send_text_fallback(text, "script generation failed")
            return

        wav_path = tmp_dir / "brief.wav"
        try:
            synthesize_to_wav(script, wav_path)
        except Exception as exc:
            log.error("TTS failed: %s", exc, exc_info=True)
            send_text_fallback(text, "TTS failed")
            return

        ogg_path = tmp_dir / "brief.ogg"
        try:
            wav_to_opus(wav_path, ogg_path)
        except Exception as exc:
            log.error("Audio conversion failed: %s", exc, exc_info=True)
            send_text_fallback(text, "audio conversion failed")
            return

        try:
            send_voice_note(ogg_path)
        except Exception as exc:
            log.error("Telegram voice upload failed: %s", exc, exc_info=True)
            send_text_fallback(text, "Telegram voice upload failed")
            return

    log.info("Voice brief delivered successfully")


if __name__ == "__main__":
    main()
