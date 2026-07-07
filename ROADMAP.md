# Roadmap

This is a proposal, not a schedule — phases are sequenced by dependency.
See `CHANGELOG.md` for what's actually been done.

## Phase 0 — Project setup (complete)

- [x] Proposal reviewed and approved (2026-07-07)
- [x] Repository created: `README.md`, `ROADMAP.md`, `CHANGELOG.md`,
      `CLAUDE.md`
- [x] Commute stations, train times, and home postcode confirmed with
      the operator and recorded in `config.local.json` (gitignored —
      see `CLAUDE.md`; `config.example.json` has the shape without real
      values)
- [x] Telegram trigger phrase confirmed: `/brief`
- [x] Realtime Trains API signup complete; refresh token stored in
      Keychain (`realtimetrains-api-token`) and verified against the
      real `/api/get_access_token` endpoint (HTTP 200, valid token
      returned, entitlements empty as expected) — see `README.md` for
      the auth flow this implies for implementation

## Phase 1 — Minimum viable version (complete, 2026-07-07)

Manual trigger only — no scheduling, no proactive messages. On request,
replies with train status, weather advice, and a politics summary in one
message. Each section degrades independently if its source fails.

- [x] Small, reviewable addition to `bridge.py` (in the Bizkit
      repository): a `custom_commands` config mapping routes `/brief`
      directly to `brief.py` as a plain subprocess, bypassing
      `invoke_claude()` entirely — see Bizkit `DECISIONS.md` ADR-0011
- [x] Train status fetcher (`trains.py`) — Realtime Trains, two-step
      Bearer-token exchange with access-token caching
- [x] Weather advice fetcher (`weather.py`) — postcodes.io + Open-Meteo
- [x] Politics headline summary (`politics.py`) — BBC RSS, summarized by
      a `claude -p` call with zero tool access
      (`.claude/settings-notools.json`)
- [x] Orchestrator (`brief.py`) — picks morning or evening leg by time
      of day, assembles the final message
- [x] API keys in Keychain; commute/location config gitignored
- [x] End-to-end manual test over Telegram — confirmed working

## Phase 2 — Later versions

Blocked on Bizkit's own Phase 4 "later tier" — the Telegram bridge is
currently reply-only by design; unsolicited/proactive messages aren't
built yet:

- [ ] Scheduled proactive morning briefing
- [ ] Real-time disruption alerts

Not blocked — can happen anytime after Phase 1:

- [ ] Return-journey / multi-leg commute support
- [ ] Richer weather (hourly breakdown, official warnings)
- [ ] Broader or filtered news topics
