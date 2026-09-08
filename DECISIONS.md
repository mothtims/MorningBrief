# Decisions

A log of significant design decisions made about MorningBrief, and the
reasoning behind them — MorningBrief's own equivalent of Bizkit's
`DECISIONS.md`. Not every configuration choice belongs here, only
decisions that shape how the project is designed or operates going
forward. Entries are numbered and never renumbered or deleted, even if a
later decision supersedes one; supersession is noted in the entry itself.

Format, loosely: Context, Decision, Consequences.

Distinct from `CHANGELOG.md` (dated history of what changed) and
`CONTEXT.md` (a living half-page snapshot of current state) — this is
where the reasoning behind load-bearing choices lives. Earlier decisions
(Piper vs. ElevenLabs, direct Anthropic SDK vs. `claude -p`, the flat-file
layout) predate this file and are recorded as prose in `VOICE_PROPOSAL.md`
rather than here; new decisions from this point on belong in this file.

---

## ADR-0001: Local EventKit read for calendar awareness, not Google Calendar API

**Context:** The morning brief should include today's calendar — timed
and all-day events — read from macOS Calendar.app, which mirrors a mix
of local/iCloud calendars and one synced Google account. Two approaches
were available: read locally via macOS's own calendar store (no cloud
auth), or integrate directly with the Google Calendar API (would also
require separate handling for the iCloud-only calendars, and adds
outbound cloud auth this project has deliberately avoided elsewhere —
see `weather.py`/`trains.py`, both unauthenticated public APIs).

**Decision:** Read locally via `EventKit` (through
`pyobjc-framework-EventKit`), not `icalBuddy` and not the Google Calendar
API. `icalBuddy` was evaluated and rejected: no confirmed recent upstream
releases, several community forks (a sign of abandonment), and
documented TCC/permission confusion reports on macOS Ventura and later.
`pyobjc-framework-EventKit` is actively maintained (releases through
mid-2026), talks to EventKit with structured data instead of parsing CLI
text output, and — critically — was empirically verified to work
end-to-end under a real headless `launchd` LaunchAgent using this
project's actual interpreter, including surviving job re-registration
(see `CALENDAR_PROPOSAL.md` for the full investigation). Since
Calendar.app already syncs the Google account locally, no separate
Google API integration or cloud auth is needed; this also automatically
covers any future calendar source added through Calendar.app itself, not
just Google.

**Consequences:** TCC's Calendar grant is bound to the specific
interpreter binary's path (`~/.local/share/uv/python/cpython-3.13.14-.../python3.13`
as of this writing) — same caveat class as the existing
`onnxruntime`/Python-3.13 pin: changing the interpreter (e.g. a future
Python version bump) requires re-confirming the grant, not just
re-testing functionality. The read is strictly one-way and read-only —
no write access is requested or needed. `pyobjc-framework-EventKit` adds
a real dependency (pulls in `pyobjc-core` and Cocoa bindings), heavier
than this project's other dependencies, but has proper wheel coverage
for this platform (verified during investigation) so doesn't reopen the
onnxruntime wheel-gap problem. Calendar allowlist is `Home` and
`thomasandrewfaber@gmail.com` (see `config.local.json`) — the other 6
discovered calendars (`Birthdays`, `Work`, both holiday sources, and
both `sarahfoxfaber@gmail.com` entries) are deliberately excluded, partly
to avoid noise and partly because two of the excluded calendars were
found to duplicate each other's events verbatim.

## ADR-0002: Section rotation reuses the existing leg-selection time check, not a parallel switch

**Context:** The 16:30 send needs to carry a technology section instead
of politics, while the 07:00 send keeps politics — a genuine content
swap, not an additional section. `brief.py` already computes
`now_hour < LEG_SWITCH_HOUR` once, to pick which commute leg
(`morning_leg`/`evening_leg`) to report on. Adding a second,
independently-computed time check for the news-section choice would
create two sources of truth for "is this a morning or afternoon send,"
with the attendant risk of them disagreeing (e.g. one gets a threshold
tweak later and the other doesn't).

**Decision:** Factor the existing hour check into a named
`is_morning_send()` function, computed once per `gather_brief_data()`
call, and use that single boolean for both `pick_leg()` and the
news-section choice (`summarize_politics()` vs `summarize_tech()`).
`BriefData.politics_line` is renamed to `BriefData.news_line` (with a
paired `news_label` field), since a field named for one topic holding
another topic's content half the time would be misleading.

**Consequences:** `LEG_SWITCH_HOUR` (13:00) now implicitly governs three
things — leg selection, train direction, and news topic — from one
place. Any future section that should also vary by time of day (rather
than being a new independent fetcher like TV) should extend this same
boolean rather than adding another time check. The rename touches
`brief.py` and `voice_script.py`'s prompt-formatting call; no other
files reference the old field name.

Same rotation introduced the TV watchlist as an always-present but
often-silent section: `BriefData.tv_line` is `""` on most days
(nothing airing), and both `format_text()` and `voice_script.py`'s
data-block assembly omit the section entirely when empty, rather than
rendering an empty placeholder. See `TV_TECH_PROPOSAL.md` for the
TVmaze investigation and the resolved watchlist (`config.local.json`).
