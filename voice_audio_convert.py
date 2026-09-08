"""
WAV -> OGG/Opus (for Telegram's sendVoice) and WAV -> MP3 (for storage /
podcast, v2) via ffmpeg. Piper only produces WAV; this is the conversion
step VOICE_PROPOSAL.md flagged as missing from the original four-step
pipeline description.

Bitrate is tuned to land a 60-90s clip comfortably under Telegram's 1MB
voice-bubble threshold - confirmed against Telegram's own documented
sendVoice format requirements (OGG container, Opus codec, audio/ogg
MIME type) before writing this, not assumed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from logutil import get_logger

log = get_logger("voice.audio_convert")

# Absolute path, not a bare "ffmpeg" lookup: this script runs under
# launchd (via scheduled_send_voice.py), which gets a minimal PATH that
# may not include Homebrew - the same gotcha already hit and fixed for
# bridge.py's claude_binary and politics.py's CLAUDE_BINARY.
FFMPEG_BINARY = "/usr/local/bin/ffmpeg"

# 32kbps mono opus: a 90s clip is ~360KB, safely under Telegram's 1MB
# voice-bubble threshold with headroom. Raise if voice quality suffers.
OPUS_BITRATE = "32k"
MP3_BITRATE = "96k"


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        [FFMPEG_BINARY, "-y", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()}")


def wav_to_opus(wav_path: Path, opus_path: Path) -> None:
    """Produces an OGG container with Opus codec - what Telegram's
    sendVoice actually requires (not a bare .opus file)."""
    opus_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "-i", str(wav_path),
        "-c:a", "libopus",
        "-b:a", OPUS_BITRATE,
        "-ac", "1",
        str(opus_path),
    ])
    log.info("Converted %s -> %s (opus, %s)", wav_path.name, opus_path.name, OPUS_BITRATE)


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        "-i", str(wav_path),
        "-c:a", "libmp3lame",
        "-b:a", MP3_BITRATE,
        str(mp3_path),
    ])
    log.info("Converted %s -> %s (mp3, %s)", wav_path.name, mp3_path.name, MP3_BITRATE)


if __name__ == "__main__":
    import sys

    wav_in = Path(sys.argv[1])
    wav_to_opus(wav_in, wav_in.with_suffix(".ogg"))
    wav_to_mp3(wav_in, wav_in.with_suffix(".mp3"))
    print("done")
