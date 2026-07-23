# Morning Brief

A personal daily briefing delivered over Telegram: Southeastern train
status for the commute, practical weather advice, and a short summary of
notable UK politics headlines. Successor to a previous ad hoc setup
("OpenClaw"), rebuilt as a proper Bizkit-maintained project.

This is a project Bizkit works on, not part of Bizkit's own governance —
see the `Bizkit` repository (private, this account) for the
workstation-level engineering standards this project inherits.

## What it does

Two ways to get it: a manual Telegram command (`/brief`), or
automatically twice on weekdays. Either way, it replies with:

- **Trains** — live status for a specific Southeastern commute leg:
  delays, cancellations, and platform number when announced. Platform
  numbers genuinely aren't always available until close to departure;
  the brief says so rather than guessing.
- **Weather** — practical advice for the day (umbrella, temperature),
  not just raw forecast numbers.
- **Politics** — a short summary of notable UK headlines.

Each section degrades independently: if one data source is unavailable,
the other two are still delivered, with a note about what's missing.

## Data sources

- **Trains**: [Realtime Trains](https://www.realtimetrains.co.uk) for
  the MVP, via their **Next Generation API** (`data.rtt.io`, launched
  2026-03). Southeastern has no separate API of its own — like every UK
  operator, its live data flows through the shared National Rail
  **Darwin** engine. The official access route is the
  [Rail Data Marketplace](https://raildata.org.uk) (the older National
  Rail Data Portal is being retired in early 2026); Realtime Trains is a
  third-party wrapper over the same underlying data, easier to integrate
  with for personal use. RDM stays available as a fallback if needed.

  **Auth flow** (implemented in `trains.py`, verified against the real
  API): the Keychain-stored secret (`realtimetrains-api-token`) is a
  long-lived *refresh* token. It's exchanged for a short-lived access
  token via `GET data.rtt.io/api/get_access_token`
  (`Authorization: Bearer <refresh_token>`), cached to
  `state/rtt_access_token.json` until its `validUntil` expiry so normal
  use stays well under the 30/min rate limit. Departures are queried via
  `GET data.rtt.io/gb-nr/location?code=<CRS>&filterTo=<CRS>&timeFrom=...`
  (`Authorization: Bearer <access_token>`) — confirmed against real
  Cannon Street↔Whitstable services, including a live cancelled/on-time
  and platform-number check.
- **Weather**: [Open-Meteo](https://open-meteo.com) — no API key
  required. Paired with [postcodes.io](https://postcodes.io) (also free,
  no key) to turn a UK postcode into coordinates.
- **Politics**: BBC News politics RSS feed.

All API keys live in the macOS Keychain, never committed to this
repository — see `CLAUDE.md`.

## How it's triggered

Through Bizkit's existing Telegram bridge
(`services/telegram-bridge/` in the `Bizkit` repository). `bridge.py`'s
`custom_commands` config maps the exact text `/brief` to `brief.py`,
which it runs as a plain subprocess and relays the stdout of, verbatim —
bypassing `invoke_claude()` entirely. This is a deliberate design
choice: the bridge's permission gate denies the model general network
access (`curl`/`wget`) by design, and this project doesn't need or want
that changed — see Bizkit's `DECISIONS.md` ADR-0011 for the mechanism.
The one LLM call involved, in `politics.py`, gets zero tool access —
pure text-in/text-out — so third-party feed content can't do anything
even in principle, only say something.

## Scheduled delivery

Weekdays at 07:00 and 16:30, `launchd` (`com.morningbrief.scheduled`,
`~/Library/LaunchAgents/`) runs `scheduled_send.py`, which builds the
brief and sends it via Bizkit's `send_message.py` — independent of the
manual `/brief` path above, and independent of whether the polling
bridge is even running. See Bizkit's `DECISIONS.md` ADR-0012 for why
proactive sending is a separate, minimal primitive rather than a new
mode of the bridge. Same caveat as the rest of Bizkit: if the machine is
asleep at 07:00 or 16:30, that run just doesn't happen — accepted, not a
bug (see Bizkit `DECISIONS.md`, "resident engineer, not cloud service").

## Files

- `brief.py` — orchestrator; picks morning or evening leg by time of
  day, calls the three fetchers below, assembles the final message.
  Used by both delivery paths.
- `scheduled_send.py` — entry point for the `launchd` schedule; calls
  `brief.py` then pipes the result to Bizkit's `send_message.py`.
- `trains.py`, `weather.py`, `politics.py` — the three fetchers, each
  independently degrading to a plain-text "unavailable" message on
  failure rather than raising.
- `config.local.json` (gitignored) / `config.example.json` — commute
  legs, home postcode, trigger phrase.
- `.claude/settings-notools.json` — the empty-permission profile used
  for the politics summarization call.
- `launchd/com.morningbrief.scheduled.plist.template` — the schedule
  (weekdays, 07:00 and 16:30); copy to `~/Library/LaunchAgents/` with
  placeholders substituted per the comment at its top.

## Status

Phase 2's first item (scheduled proactive delivery) is live as of
2026-07-23 — see `ROADMAP.md`. Both the manual `/brief` command and the
weekday 07:00/16:30 schedule are active.
