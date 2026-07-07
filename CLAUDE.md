# MorningBrief

See Bizkit Engineering Standards (`~/Projects/Bizkit/CLAUDE.md`, repo
`mothtims/Bizkit`, private).

This repository additionally:

- Stores all API keys (Realtime Trains, and anything added later) in the
  macOS Keychain, never in this repository.
- Keeps commute and location details (station codes, home location) in a
  gitignored `config.local.json`, with `config.example.json` committed
  as the template — same pattern as `services/telegram-bridge` in the
  Bizkit repository.
- Integrates with `~/Projects/Bizkit/services/telegram-bridge/` by
  exposing a plain, tool-free callable interface. The bridge's LLM
  session never gets direct network access on this project's behalf —
  see `ROADMAP.md` and Bizkit's `DECISIONS.md` (ADR-0010) for why that
  boundary matters.
- Runs any LLM-assisted summarization step (e.g. politics headlines)
  with no tool access — pure text-in/text-out — so third-party feed
  content has no way to cause an action, only a bad sentence.
