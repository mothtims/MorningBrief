"""
Scheduled entry point for the voice edition. Separate launchd job from
scheduled_send.py, running the same weekday twice-daily schedule
(07:00/16:30) so a voice-pipeline failure can never affect the existing
text brief's reliability - see VOICE_PROPOSAL.md section 4, "the
degradation contract". (Originally morning-only; changed 2026-09-08 to
match the text schedule.)

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

v2 storage mirror (R2_DELIVERY_PROPOSAL.md, DECISIONS.md ADR-0003):
runs strictly *after* Telegram delivery succeeds, never before and
never blocking it. Since the failure is discovered after the main
message has already gone out, its visibility note can't be prepended
the way the four fallbacks above do - it's a small separate
supplementary Telegram message instead (send_text_note()).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from brief import format_text, gather_brief_data, load_config
from logutil import get_logger
from voice_audio_convert import wav_to_mp3, wav_to_opus
from voice_script import generate_script
from voice_storage import push_latest_brief
from voice_tts import synthesize_to_wav

log = get_logger("scheduled_send_voice")

SEND_MESSAGE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_message.py"
SEND_VOICE_SCRIPT = "/Users/mothtims/Projects/Bizkit/services/telegram-bridge/send_voice.py"


def send_text_fallback(text: str, stage: str) -> None:
    log.warning("Falling back to text brief (%s failed)", stage)

    # Best-effort only: if this note can't be built for any reason, the
    # plain brief still has to go out - never let visibility logic block
    # or delay the one thing this script must not fail to do.
    try:
        text_to_send = f"{text}\n\nVoice brief failed today: {stage} stage."
    except Exception:
        text_to_send = text

    result = subprocess.run(
        [sys.executable, SEND_MESSAGE_SCRIPT],
        input=text_to_send,
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


def send_text_note(note: str) -> None:
    """Small standalone Telegram text message, for visibility on
    failures discovered *after* the main delivery already succeeded.
    Never raises - a broken notification must never break an
    otherwise-successful run; worst case it just logs."""
    try:
        result = subprocess.run(
            [sys.executable, SEND_MESSAGE_SCRIPT],
            input=note,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("Supplementary note failed to send: %s", result.stderr.strip())
    except Exception as exc:
        log.error("Supplementary note failed to send: %s", exc, exc_info=True)


def main() -> None:
    data = gather_brief_data()
    text = format_text(data)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        try:
            script = generate_script(data)
        except Exception as exc:
            log.error("Script generation failed: %s", exc, exc_info=True)
            send_text_fallback(text, "script generation")
            return

        wav_path = tmp_dir / "brief.wav"
        try:
            synthesize_to_wav(script, wav_path)
        except Exception as exc:
            log.error("TTS failed: %s", exc, exc_info=True)
            send_text_fallback(text, "TTS")
            return

        ogg_path = tmp_dir / "brief.ogg"
        try:
            wav_to_opus(wav_path, ogg_path)
        except Exception as exc:
            log.error("Audio conversion failed: %s", exc, exc_info=True)
            send_text_fallback(text, "audio conversion")
            return

        try:
            send_voice_note(ogg_path)
        except Exception as exc:
            log.error("Telegram voice upload failed: %s", exc, exc_info=True)
            send_text_fallback(text, "Telegram upload")
            return

        log.info("Voice brief delivered successfully")

        # v2 storage mirror - only ever attempted after the line above,
        # so it can never block or delay the delivery that matters.
        config = load_config()
        r2_account_id = config.get("r2_account_id")
        r2_bucket = config.get("r2_bucket")
        if not r2_account_id or not r2_bucket:
            log.info("R2 not configured (r2_account_id/r2_bucket missing) - skipping storage push")
            return

        mp3_path = tmp_dir / "brief.mp3"
        try:
            wav_to_mp3(wav_path, mp3_path)
            push_latest_brief(mp3_path, r2_account_id, r2_bucket)
        except Exception as exc:
            log.error("R2 push failed: %s", exc, exc_info=True)
            send_text_note(f"R2 upload failed today ({exc}) - voice/text still delivered normally via Telegram.")


if __name__ == "__main__":
    main()
