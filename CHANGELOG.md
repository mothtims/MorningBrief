# Changelog

All notable changes to this project. Entries are dated; no semantic
versioning (pre-release, personal-use project).

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
