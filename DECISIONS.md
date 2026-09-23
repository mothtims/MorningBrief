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

## ADR-0003: R2 delivery — Worker-gated static header token, not an unguessable URL or presigned URLs

**Context:** v2 needs the voice brief reachable by an iOS Shortcut's
`"Get Contents of URL"` action — a consumer limited to a fixed,
pre-saved URL and optionally one fixed custom header, with no dynamic
auth support (no OAuth, no per-request signing). The file carries
personal schedule/movement information, so access control matters.
Three approaches were evaluated: an unguessable path on a public
bucket, presigned URLs, and a Cloudflare Worker gating a private
bucket on a static token.

**Decision:** A Cloudflare Worker in front of a private R2 bucket,
checking a long random static token passed as a custom HTTP header
(`X-Brief-Token`), constant-time-compared against a Worker environment
secret, proxying the R2 object through on match. Header chosen over
query parameter because URLs are logged by default at nearly every
HTTP hop (edge/CDN logs, intermediate proxies, browser history) while
headers generally aren't — meaningful for content this personal. An
unguessable-path public bucket was rejected because its entire security
model is "nobody finds this URL," with no revocation short of changing
the URL (breaking "stable"). Presigned URLs were rejected because they
expire by design (~7 days with static credentials), conflicting with a
Shortcut that saves one URL indefinitely.

**Consequences:** This is new external infrastructure beyond this
machine — a Cloudflare account, an R2 bucket, a deployed Worker.
Two independent secrets exist and must not be confused: the R2 API
token (Object Read & Write, scoped to one bucket — R2's token model has
no true write-only tier) authenticates the Python pipeline's *push* to
R2, stored in Keychain like every other credential in this project
(`morningbrief-r2-access-key-id`/`morningbrief-r2-secret-access-key`).
The Worker's gating token authenticates the phone's *read* from the
Worker — it lives only in the Worker's own environment
(`cloudflare/brief-worker.js`) and is embedded in the saved Shortcut;
it never touches this codebase, Keychain, or any config file. Rotating
the gating token later is a one-line Worker secret update plus
re-saving the Shortcut, touching neither R2 nor the Python pipeline.
`voice_storage.py`'s SigV4 signer is hand-rolled via stdlib
(`hashlib`/`hmac`/`urllib`), not `boto3` — verified correct by
cross-checking its output against `botocore`'s own signer for
synthetic requests (exact signature match across independent test
cases) rather than trusting a hand-derived test vector. See
`R2_DELIVERY_PROPOSAL.md` for the full investigation.

## ADR-0004: Freshness enforced server-side in the Worker, not left to the Shortcut

**Context:** `latest.mp3` is overwritten on every voice run, but a
failed run (any of the four fallback stages in `scheduled_send_voice.py`)
leaves the *previous* brief in place rather than removing it — by
design, per the degradation contract, the pipeline never blocks or
deletes on failure. The Worker already passes the object's real
`Last-Modified` through (ADR-0003), but iOS Shortcuts' `"Get Contents
of URL"` action has no way to read response headers, so a Shortcut
built against this Worker has no way to notice a stale object and
would simply play the last successful brief as if it were current —
worst case, the previous afternoon's brief played the next morning.

**Decision:** Enforce a maximum object age of 3 hours directly in the
Worker: if `object.uploaded` is older than `MAX_AGE_MS` at request
time, return the identical uniform 404 used by every other rejection
path (ADR-0003) — no distinct status or body, so this failure mode
isn't distinguishable from a bad token or a missing object either. The
3-hour figure isn't arbitrary: play windows are 07:10–09:30 and
16:40–19:00, each closing roughly 2.5 hours after its corresponding
push, so a genuinely fresh brief always passes and a stale one from
the *other* send always fails, with headroom either side.

**Consequences:** This is enforcement, not just exposure — freshness
no longer depends on the client checking anything. If the play windows
ever change materially, `MAX_AGE_MS` needs revisiting alongside them,
since it's derived from them, not independent. A voice run failing
twice in a row (both sends in one day) means no audio is servable at
all for that whole day rather than a stale fallback — considered and
accepted: playing hours-old, wrong-context audio silently would be
worse than the Shortcut/HTTP request simply failing.
