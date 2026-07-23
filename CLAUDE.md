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
- Integrates with `~/Projects/Bizkit/services/telegram-bridge/` via its
  `custom_commands` config (`bridge.py`): `/brief` is run directly as a
  plain subprocess (`brief.py`), never through `invoke_claude()`. The
  bridge's LLM session never gets direct network access on this
  project's behalf — see Bizkit's `DECISIONS.md` (ADR-0010, ADR-0011)
  for why that boundary matters.
- Runs any LLM-assisted summarization step (e.g. politics headlines)
  with no tool access — pure text-in/text-out (`.claude/settings-notools.json`)
  — so third-party feed content has no way to cause an action, only a
  bad sentence.
- Caches non-secret runtime state (e.g. the RTT short-lived access
  token) in a gitignored `state/` directory, same pattern as the
  Telegram bridge.
- Delivers scheduled briefs via Bizkit's `send_message.py`
  (`scheduled_send.py`, `launchd/`), independent of the polling bridge
  — see Bizkit's `DECISIONS.md` ADR-0012. Scheduling is this project's
  own responsibility; the bridge has no concept of when to send.
