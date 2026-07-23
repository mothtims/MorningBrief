# Changelog

All notable changes to this project. Entries are dated; no semantic
versioning (pre-release, personal-use project).

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
