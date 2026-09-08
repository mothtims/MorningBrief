# Changelog

All notable changes to this project. Entries are dated; no semantic
versioning (pre-release, personal-use project).

## 2026-09-08

### Added — Voice edition v1
- Added a spoken audio briefing delivered as a Telegram voice note,
  alongside the existing text brief (not instead of it — an
  intentional degradation contract, see `VOICE_PROPOSAL.md` section 4
  and `CONTEXT.md`). Pipeline: `gather_brief_data()` → Claude API
  (`claude-opus-4-8`, direct SDK call, not the `claude -p` CLI pattern
  `politics.py` uses) writes a short warm/conversational spoken-style
  script → Piper TTS synthesizes it locally → `ffmpeg` converts to
  Opus/OGG → delivered via Bizkit's new `send_voice.py` primitive
  (`services/telegram-bridge/`, see Bizkit `DECISIONS.md` ADR-0012/13
  area).
- Default voice locked to `en_GB-alba-medium` after an A/B listen
  against three other Piper voices sent as labelled Telegram voice
  notes.
- Pinned `onnxruntime==1.23.0` and Python 3.13 (`.python-version`):
  this machine is an Intel Mac (x86_64, macOS 13.7.8) and onnxruntime
  dropped x86_64 macOS wheels after 1.23.0; 1.25.0+ needs macOS 14+
  and arm64. Both pins are load-bearing.
- Registered `launchd/com.morningbrief.voice.scheduled.plist`: weekday
  mornings at 07:00, alongside the text job's own 07:00/16:30 schedule
  — a separate launchd job so a voice-pipeline failure can never affect
  the text brief's own reliability.
- Added `CONTEXT.md`, a living half-page snapshot of current state
  (distinct from this changelog) — first instance of a new
  Bizkit-wide convention, see Bizkit `DECISIONS.md` ADR-0013.

### Added — Fallback visibility
- Previously, any voice-stage failure degraded silently to the plain
  text brief with no indication anything had gone wrong. Now
  `scheduled_send_voice.py`'s text fallback appends one short line —
  e.g. "Voice brief failed today: TTS stage." — naming which stage
  failed (script generation, TTS, audio conversion, or Telegram
  upload). The note-building is wrapped defensively so that if it ever
  fails, the plain brief still goes out unmodified — the rule that
  voice problems must never block or delay the text brief still holds.

## 2026-08-04

### Checked
- Reviewed `state/morningbrief.log` after ~5 days with the 2026-07-30
  retry/logging fix in place. Confirmed the original bug (weather 503s
  degrading silently) is fixed: real `HTTP 503`s from Open-Meteo hit
  twice (Jul 30, Jul 31) and both times the retry succeeded — no
  degraded message reached the operator.

### Found and fixed
- A separate, more serious pattern surfaced: `socket.gaierror` (DNS
  resolution failure) hit all three fetchers simultaneously across 4
  runs between 2026-08-03 07:45 and 2026-08-04 07:30 — a
  workstation/network-level outage, not an issue with any of the three
  APIs. Retries can't fix a genuinely absent network; noted as a known
  failure mode rather than "fixed," since there's nothing at the
  application layer to do about it beyond what already exists (retry,
  log, degrade gracefully).
- Found and fixed a real, distinct bug this surfaced: twice (2026-08-03
  23:17, 2026-08-04 07:30), right after the RSS fetch recovered from
  the DNS flakiness above, `politics.py`'s `claude -p` call failed with
  exit 1 and *empty* stderr — no diagnostic information at all. Root
  cause: `politics.py` invoked `claude` as a bare command rather than
  an absolute path, the same PATH-resolution gotcha already hit and
  fixed for `bridge.py` under `launchd` (see Bizkit's `DESIGN.md`) —
  but that fix was never applied here. Fixed by using the same absolute
  path (`~/.local/bin/claude`), and by logging `stdout` in addition to
  `stderr` on failure, and by explicitly catching `FileNotFoundError`
  with a clear message instead of letting a bad path degrade into an
  opaque exit code. Verified the improved diagnostics work by
  deliberately breaking the path and confirming a clear log message
  appears — not just assumed the fix helps.

## 2026-07-30

### Fixed
- Investigated reports of the weather section failing "pretty
  regularly." Root cause: `weather.py` had zero retry logic and
  swallowed every failure straight into the delivered message text
  (e.g. "Weather unavailable right now (HTTP Error 503: ...)"), with
  nothing logged anywhere — so the only evidence of a failure was
  whatever the operator happened to read in Telegram. Both
  `postcodes.io` and Open-Meteo tested healthy at investigation time,
  consistent with an intermittent transient issue rather than a hard
  outage or a bug in the request itself.
- Added `httputil.py` (shared HTTP-GET-with-retry: 3 attempts,
  short backoff, immediate raise on non-retryable 4xx) and
  `logutil.py` (shared rotating-file logger, `state/morningbrief.log`,
  gitignored). Applied to all three fetchers (`weather.py`,
  `trains.py`, `politics.py`), not just weather, since all three had
  the identical gap. Verified against a real simulated 503/timeout
  (`httpbin.org/status/503`) that retries and logging both fire
  correctly, and re-verified the happy path still works for all three
  after the refactor.
- `politics.py`'s `claude -p` summarization failure fallback (silently
  degrading to a plain headline list) now also logs the failure
  instead of vanishing silently.

## 2026-07-23

### Added — Phase 2 (scheduled delivery)
- Added `scheduled_send.py`: builds the brief via `brief.py` and pipes
  it to Bizkit's new `send_message.py` primitive
  (`services/telegram-bridge/`, see Bizkit `DECISIONS.md` ADR-0012),
  independent of the manual `/brief` path and of whether the polling
  bridge is running.
- Added `launchd/com.morningbrief.scheduled.plist.template`: weekdays,
  07:00 and 16:30 (ahead of the 07:39 and 17:11 commute legs). A
  periodic task, not a persistent daemon — no `RunAtLoad`/`KeepAlive`.
  Registered and verified under real `launchd` conditions with a forced
  `kickstart` before trusting it to fire unattended, not just tested by
  running the script manually.
- This was the first item in Phase 2 that was explicitly blocked on
  Bizkit's own infrastructure (no proactive-messaging capability
  existed before today) — see Bizkit's `CHANGELOG.md` for the
  `send_message.py` addition that unblocked it.

## 2026-07-07

### Added
- Project proposed and approved: a Telegram-delivered morning briefing
  covering Southeastern train status, practical weather advice, and a UK
  politics headline summary — replacing a previous ad hoc setup
  ("OpenClaw"). Starts as a manual Telegram command; scheduled/proactive
  delivery is explicitly deferred to a later phase.
- Created `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `CLAUDE.md`.

### Fixed
- Corrected the train data source description: Southeastern has no API
  of its own — confirmed via research, since National Rail's own
  developer documentation states all UK operators share the Darwin
  engine. Updated `README.md` to name the current official route (Rail
  Data Marketplace) rather than the outdated National Rail Data Portal.

### Added
- Confirmed commute stations (Cannon Street/Whitstable, CRS codes
  verified), train times, and home postcode with the operator; recorded
  in gitignored `config.local.json`, with `config.example.json` added as
  the committed template.
- Confirmed Telegram trigger phrase: `/brief`.
- Completed Realtime Trains API signup; refresh token stored in Keychain
  (`realtimetrains-api-token`) and verified against the real
  `/api/get_access_token` endpoint (HTTP 200, valid token returned).
  Phase 0 is now complete.

### Fixed
- Corrected the Realtime Trains integration notes in `README.md`:
  discovered mid-verification that RTT launched a "Next Generation API"
  (`data.rtt.io`, 2026-03) using a two-step Bearer-token exchange, not
  the HTTP Basic Auth scheme described in their older, now-deprecated
  docs. The stored Keychain secret is a refresh token, not usable
  directly against data endpoints — implementation needs to exchange it
  for a short-lived access token first. Verified this end-to-end against
  the real API before recording it, rather than trusting either the old
  docs or assumption.
- Replaced the ambiguous single `origin_station_crs`/`destination_station_crs`
  config pair with explicit `morning_leg`/`evening_leg` objects (each
  with `from`, `to`, `departs`), after realizing the original fields
  didn't actually match the stated commute direction. Caught before any
  code was written.

### Added — Phase 1 (MVP) implementation
- `trains.py`: Realtime Trains fetcher. Implements and caches the
  two-step Bearer-token exchange (`state/rtt_access_token.json`,
  respecting `validUntil`); queries `gb-nr/location` filtered by
  destination; picks the service closest to the configured departure
  time; reports operator, on-time/delay/cancelled status, and platform
  (or "not yet announced"). Verified against real Cannon
  Street↔Whitstable services in both directions.
- `weather.py`: postcode → coordinates (postcodes.io) → forecast
  (Open-Meteo) → plain practical advice (umbrella/temperature
  thresholds), not raw numbers.
- `politics.py`: BBC politics RSS → top headlines → summarized into a
  short paragraph by a `claude -p` call with zero tool access
  (`.claude/settings-notools.json`) — deliberately no `Read`/`Bash`/etc.
  available, so third-party feed content has nothing to act on, only
  something to (at most) say.
- `brief.py`: orchestrator. Picks the morning or evening leg by time of
  day, calls all three fetchers, assembles the final message. This is
  what `bridge.py` invokes.
- Added `custom_commands` routing to Bizkit's `bridge.py` (small,
  reviewed diff — see Bizkit `CHANGELOG.md` and `DECISIONS.md`
  ADR-0011): `/brief` now bypasses `invoke_claude()` entirely and runs
  `brief.py` directly as a subprocess. The bridge's existing permission
  gate is completely untouched by this integration.
- End-to-end live test over Telegram: confirmed working, correct
  section for each data source, graceful under real conditions.

### Fixed
- A real bug caught during implementation, not review: `trains.py`'s
  first version built the RTT query URL by raw string concatenation,
  so the `+` in `+01:00` (timezone offset) was interpreted as a literal
  space by the server, causing HTTP 400s. Fixed by using
  `urllib.parse.urlencode` for all query parameters instead.
