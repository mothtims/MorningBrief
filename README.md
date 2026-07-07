# Morning Brief

A personal daily briefing delivered over Telegram: Southeastern train
status for the commute, practical weather advice, and a short summary of
notable UK politics headlines. Successor to a previous ad hoc setup
("OpenClaw"), rebuilt as a proper Bizkit-maintained project.

This is a project Bizkit works on, not part of Bizkit's own governance —
see the `Bizkit` repository (private, this account) for the
workstation-level engineering standards this project inherits.

## What it does

On request — a manual Telegram command, not a scheduled push; see
`ROADMAP.md` for why — it replies with:

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

  **Auth flow** (confirmed working against the real API, see
  `CHANGELOG.md`): the Keychain-stored secret
  (`realtimetrains-api-token`) is a long-lived *refresh* token, not used
  directly against data endpoints. Implementation needs to exchange it
  for a short-lived access token via `GET data.rtt.io/api/get_access_token`
  (`Authorization: Bearer <refresh_token>`), cache that access token
  until its `validUntil` expiry, and use *it* (`Authorization: Bearer
  <access_token>`) against actual departure-board endpoints — rate
  limits (30/min, 750/hour) make re-exchanging on every request wasteful
  and unnecessary. Endpoint paths for actual departure queries are in
  the [OpenAPI spec](https://realtimetrains.github.io/api-specification/)
  and still need reviewing before implementation.
- **Weather**: [Open-Meteo](https://open-meteo.com) — no API key
  required. Paired with [postcodes.io](https://postcodes.io) (also free,
  no key) to turn a UK postcode into coordinates.
- **Politics**: BBC News politics RSS feed.

All API keys live in the macOS Keychain, never committed to this
repository — see `CLAUDE.md`.

## How it's triggered

Through Bizkit's existing Telegram bridge
(`services/telegram-bridge/` in the `Bizkit` repository). `bridge.py`
recognizes a specific trigger command and calls directly into this
project's own code — deterministic data-fetching, not the LLM itself.
This is a deliberate design choice: the bridge's permission gate denies
the model general network access (`curl`/`wget`) by design, and this
project doesn't need or want that changed. If headline text is ever
summarized by an LLM, that call gets no tool access at all — pure
text-in/text-out — so third-party feed content can't do anything even in
principle, only say something.

## Status

Proposal approved 2026-07-07. Not yet implemented — see `ROADMAP.md` for
the current phase.
