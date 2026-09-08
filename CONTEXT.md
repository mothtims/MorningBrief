# Context

*Last updated: 2026-09-08 — keep this current as things change. This is a
living snapshot, not history — full history lives in `CHANGELOG.md`, full
reasoning behind decisions in `DECISIONS.md` (project-local, from
ADR-0001 on), `VOICE_PROPOSAL.md`/`CALENDAR_PROPOSAL.md` (design
proposals), and the inline comments/docstrings each module carries.*

## What this is

MorningBrief is a personal daily briefing pipeline: it gathers today's
calendar, train status, weather, and UK politics headlines each
morning, and delivers them to one person over Telegram — as text (live
since launch) and, as of the voice edition, also as a short spoken
audio briefing. It runs unattended via macOS `launchd` on the user's
own machine.

## Current state

- **Text brief**: live, running weekday mornings and afternoons
  (07:00/16:30) via the registered launchd job
  (`launchd/com.morningbrief.scheduled.plist`).
- **Voice brief (v1)**: live and scheduled, running **alongside** the
  text brief, not replacing it. `com.morningbrief.voice.scheduled` is
  registered in `launchd` on the same weekday twice-daily schedule as
  the text job (07:00/16:30) — originally morning-only, changed
  2026-09-08 since there was no real reason for voice to run less
  often than text. Pipeline: gather data → Claude API
  (`claude-opus-4-8`) writes a ~140-170 word spoken-style script →
  Piper TTS synthesizes it locally → ffmpeg converts to Opus/OGG →
  delivered via Telegram's `sendVoice`. Any stage failure falls back to
  the existing text delivery, now with a short visible note naming
  which stage failed (e.g. "Voice brief failed today: TTS stage.")
  rather than degrading silently.
- **Default voice**: `en_GB-alba-medium`, locked in 2026-09-08 after an
  A/B listen against three other Piper voices sent as labelled
  Telegram voice notes.
- **Calendar awareness**: live, in both text and voice briefs. Reads
  today's events from macOS Calendar.app (`Home` and
  `thomasandrewfaber@gmail.com` calendars only, via an explicit
  allowlist in `config.local.json`) using `EventKit`
  (`pyobjc-framework-EventKit`) — local read only, no Google API
  integration. Same degrade-independently contract as
  weather/trains/politics: a read failure shows a visible "Calendar
  unavailable" line rather than going silent or blocking the rest of
  the brief.
- **v2 (not started)**: Cloudflare R2 hosting + iOS Shortcuts pull +
  optional podcast RSS feed, so the brief is available outside
  Telegram too.
- All work described above is committed and pushed.

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
- **Local EventKit over icalBuddy or Google Calendar API**: `icalBuddy`
  was rejected as unmaintained with documented TCC issues on Ventura+;
  the Google API was rejected because Calendar.app already syncs that
  account locally, so a local read covers it (and any future source
  added through Calendar.app) without adding cloud auth. See
  `DECISIONS.md` ADR-0001.
- **Calendar allowlist excludes two calendars deliberately**: a live
  scan during investigation found `sarahfoxfaber@gmail.com` synced
  under two different calendar sources, producing verbatim duplicate
  events. Neither is allowlisted, sidestepping the issue; a
  `(title, start, end)` dedupe in `calendar_events.py` is a safety net
  regardless.

## Known issues / caveats

- `en_GB-southern_english_female-low` (one of the four A/B-tested
  voices, not the default) logs a missing-phoneme warning on at least
  one character — minor possible pronunciation quality issue if ever
  switched to.
- Kokoro TTS's actual performance on this specific Intel CPU is
  genuinely unverified — don't assume it would be faster or better
  without testing.
- Calendar TCC access is bound to the specific interpreter binary path
  (`~/.local/share/uv/python/cpython-3.13.14-.../python3.13`, same one
  the `onnxruntime` pin depends on) — a future Python version bump
  would need the Calendar grant re-confirmed, not just re-tested for
  functionality.
- Multi-day events spanning today were designed for defensively but
  never verified against a real one (none existed on the allowlisted
  calendars during testing) — worth a manual check whenever one
  naturally occurs.
