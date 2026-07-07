# Roadmap

This is a proposal, not a schedule — phases are sequenced by dependency.
See `CHANGELOG.md` for what's actually been done.

## Phase 0 — Project setup (in progress)

- [x] Proposal reviewed and approved (2026-07-07)
- [x] Repository created: `README.md`, `ROADMAP.md`, `CHANGELOG.md`,
      `CLAUDE.md`
- [ ] Confirm with the operator before implementation: commute origin
      and destination stations, home location for weather, the exact
      Telegram trigger phrase, and complete the Realtime Trains (and any
      other) API key signups

## Phase 1 — Minimum viable version

Manual trigger only — no scheduling, no proactive messages. On request,
replies with train status, weather advice, and a politics summary in one
message. Each section degrades independently if its source fails.

- [ ] Small, reviewable addition to `bridge.py` (in the Bizkit
      repository) so it recognizes the trigger command and routes it to
      this project's code, rather than through the general `claude -p`
      flow
- [ ] Train status fetcher (Realtime Trains)
- [ ] Weather advice fetcher (Open-Meteo)
- [ ] Politics headline summary (BBC RSS; optionally LLM-summarized with
      no tool access)
- [ ] API keys in Keychain; commute/location config gitignored
      (`config.local.json`, with `config.example.json` as the template)
- [ ] End-to-end manual test over Telegram

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
