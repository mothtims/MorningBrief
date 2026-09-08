# Context

*Last updated: 2026-09-08 — keep this current as things change. This is a
living snapshot, not history — full history lives in `CHANGELOG.md`, full
reasoning behind decisions in `VOICE_PROPOSAL.md` (voice edition) and the
inline comments/docstrings each module carries.*

## What this is

MorningBrief is a personal daily briefing pipeline: it gathers train
status, weather, and UK politics headlines each morning, and delivers
them to one person over Telegram — as text (live since launch) and, as
of the voice edition, also as a short spoken audio briefing. It runs
unattended via macOS `launchd` on the user's own machine.

## Current state

- **Text brief**: live, running daily via the registered launchd job
  (`launchd/com.morningbrief.scheduled.plist`).
- **Voice brief (v1)**: built and verified working end-to-end (real
  Telegram voice note delivered), running **alongside** the text
  brief, not replacing it. Pipeline: gather data → Claude API
  (`claude-opus-4-8`) writes a ~140-170 word spoken-style script →
  Piper TTS synthesizes it locally → ffmpeg converts to Opus/OGG →
  delivered via Telegram's `sendVoice`. Any stage failure falls back
  silently to the existing text delivery (never silence).
- **Default voice**: `en_GB-alba-medium`, locked in 2026-09-08 after an
  A/B listen against three other Piper voices sent as labelled
  Telegram voice notes.
- **The voice launchd job is written but not yet registered** —
  `launchd/com.morningbrief.voice.scheduled.plist.template` exists,
  awaiting explicit go-ahead before being copied into
  `~/Library/LaunchAgents/` and loaded.
- **v2 (not started)**: Cloudflare R2 hosting + iOS Shortcuts pull +
  optional podcast RSS feed, so the brief is available outside
  Telegram too.
- Nothing in the voice-edition work is committed yet — it's all
  reviewed, tested working-tree state, pending a commit pass.

## Why things are the way they are

- **Pinned to Python 3.13 and `onnxruntime==1.23.0`**: this machine is
  an Intel Mac (x86_64, macOS 13.7.8); onnxruntime dropped x86_64 macOS
  wheels after 1.23.0, and 1.25.0+ needs macOS 14+ and arm64. Both pins
  are load-bearing — don't bump either without re-checking wheel
  availability first.
- **Voice is additive, not a replacement**: explicit decision — text
  stays as the reliable baseline; voice is a nicer alternative, so the
  whole voice pipeline degrades to "just don't send voice" on any
  failure rather than risking the morning brief going silent.
- **Direct Anthropic SDK, not the `claude -p` CLI**: the scripting step
  (data → spoken script) calls the API directly via the `anthropic`
  Python SDK, unlike `politics.py`'s summarization step which shells
  out to `claude -p`. Deliberate, separate integration point — see
  `VOICE_PROPOSAL.md`.
- **Piper over ElevenLabs for v1**: local, free, no outbound call for
  synthesis itself, and good enough quality after the A/B test.
  ElevenLabs was considered as a fallback option in the original
  proposal but wasn't needed once Piper (with Alba) tested well.
  Kokoro TTS was also evaluated as a more expressive alternative;
  research-only, no install approved, and real performance on this
  Intel hardware remains unverified (no benchmarks exist for this CPU).
- **Flat file layout, no subdirectories**: matches the existing
  convention (`trains.py`, `weather.py`, `politics.py` all live at the
  project root) — a `voice/` package was tried first and abandoned
  because it broke same-directory imports and didn't match the rest of
  the codebase.
- **Prompt tuned for tone and length together**: warm/conversational
  phrasing plus an explicit "140-170 words" anchor — earlier prompt
  versions produced tone that was right but scripts too long for a
  60-90s briefing.

## Known issues / caveats

- `en_GB-southern_english_female-low` (one of the four A/B-tested
  voices, not the default) logs a missing-phoneme warning on at least
  one character — minor possible pronunciation quality issue if ever
  switched to.
- Kokoro TTS's actual performance on this specific Intel CPU is
  genuinely unverified — don't assume it would be faster or better
  without testing.
- The voice launchd job isn't registered yet, so voice briefs currently
  only run when triggered manually (`uv run python3
  scheduled_send_voice.py`), not on the daily schedule.
