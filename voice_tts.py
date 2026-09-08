"""
Text-to-speech via Piper (local, free, no outbound call for synthesis
itself). See VOICE_PROPOSAL.md for why Piper over ElevenLabs for v1, and
the platform note below for why onnxruntime is pinned.

Platform note: this workstation is an Intel Mac (x86_64). onnxruntime
dropped x86_64 macOS wheels after 1.23.0 (1.25.0+ is arm64-only and
requires macOS 14+, which this machine also doesn't have - it's on
13.7.8). pyproject.toml pins onnxruntime==1.23.0 and .python-version
pins this project to 3.13, since 1.23.0 has no wheel for 3.14. Both
pins are load-bearing - verify they still resolve before ever bumping
either version.
"""

from __future__ import annotations

import wave
from pathlib import Path

from piper import PiperVoice

from logutil import get_logger

log = get_logger("voice.tts")

VOICE_DIR = Path(__file__).resolve().parent / "voices"
# Locked in 2026-09-08 after an A/B listen against alan-medium,
# jenny_dioco-medium, southern_english_female-low, and cori-high (all
# in voices/, kept for future re-comparison rather than deleted).
DEFAULT_VOICE_MODEL = VOICE_DIR / "en_GB-alba-medium.onnx"

_voice_cache: PiperVoice | None = None


def _load_voice(model_path: Path = DEFAULT_VOICE_MODEL) -> PiperVoice:
    global _voice_cache
    if _voice_cache is None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found at {model_path}. Run: "
                f"uv run python3 -m piper.download_voices --download-dir voices "
                f"{model_path.stem}"
            )
        _voice_cache = PiperVoice.load(str(model_path))
    return _voice_cache


def synthesize_to_wav(text: str, output_path: Path, model_path: Path = DEFAULT_VOICE_MODEL) -> None:
    """Synthesize `text` to a WAV file at `output_path`. Raises on failure -
    caller (scheduled_send_voice.py) is responsible for the fallback-to-text
    degradation contract, not this module."""
    voice = _load_voice(model_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    log.info("Synthesized %d chars of text to %s", len(text), output_path)


if __name__ == "__main__":
    import sys

    text_arg = sys.argv[1] if len(sys.argv) > 1 else "This is a test of the Piper voice synthesis pipeline."
    out = Path("/tmp/morningbrief_tts_test.wav")
    synthesize_to_wav(text_arg, out)
    print(f"Wrote {out}")
