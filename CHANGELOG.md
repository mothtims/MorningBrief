# Changelog

All notable changes to this project. Entries are dated; no semantic
versioning (pre-release, personal-use project).

## 2026-09-23

### Added — v2 delivery: voice brief mirrored to Cloudflare R2
- Added `voice_storage.py`: pushes the voice brief's MP3 to a private
  R2 bucket at a stable `latest.mp3` key, overwritten every run, via
  R2's S3-compatible API. Hand-rolled AWS SigV4 signing via stdlib
  (`hashlib`/`hmac`/`urllib`) rather than `boto3` — one well-defined
  HTTP operation doesn't justify a heavy dependency chain, same
  reasoning as Bizkit's `send_voice.py` hand-rolling multipart
  encoding. The signer was verified correct by cross-checking its
  output against `botocore`'s own SigV4 implementation for synthetic
  requests (exact signature match, two independent test cases) rather
  than trusting a hand-derived test vector — an earlier attempt to
  verify against a manually-recalled AWS test vector mismatched, which
  is exactly why the cross-check against a trusted implementation was
  worth doing instead of assuming the recollection was right.
- Added `cloudflare/brief-worker.js`: a Cloudflare Worker (not run on
  this machine — pasted into the Cloudflare dashboard) that gates read
  access to the R2 object behind a static token passed as a custom
  header (`X-Brief-Token`), never a query parameter, since URLs get
  logged at nearly every HTTP hop by default while headers generally
  don't. Proxies the object through with `Last-Modified` set from R2's
  own `.uploaded` timestamp, so a freshness check reflects the real
  push time. See `DECISIONS.md` ADR-0003 for the full access-mechanism
  reasoning (Worker + private bucket + header token, rejecting both an
  unguessable-URL public bucket and presigned URLs).
- `scheduled_send_voice.py`: the R2 push runs strictly *after* Telegram
  voice delivery succeeds, wrapped in its own try/except, so it can
  never block or delay the delivery that actually matters. A push
  failure sends a small separate supplementary Telegram text message
  (new `send_text_note()` helper) rather than being woven inline,
  since by the time it's discovered the main message has already gone
  out. If R2 isn't configured yet (`r2_account_id`/`r2_bucket` missing
  from config), the step is skipped cleanly with a log line — no
  spurious failure notes before setup is complete.
- `voice_audio_convert.py`'s `wav_to_mp3()`, written during the v1
  build and unused until now, is wired in as-is — no changes needed.
- `config.example.json`/`config.local.json` gained `r2_account_id`/
  `r2_bucket` keys (not secret — the two actual credentials go in
  Keychain as `morningbrief-r2-access-key-id`/
  `morningbrief-r2-secret-access-key`, per this project's existing
  pattern).
- Verified: real pipeline run with R2 left unconfigured correctly
  skipped the push step cleanly (exit 0, clear log line, normal voice
  delivery unaffected); `push_latest_brief()` raises a clean, readable
  error when Keychain secrets don't exist yet, confirming the failure
  path is well-formed. **Not yet verified**: an actual push against a
  real R2 bucket, the Worker's live behavior, or a phone fetch — all
  blocked on the user creating the Cloudflare account/bucket/token/
  Worker (see `R2_DELIVERY_PROPOSAL.md` section 4/5).

### Fixed — pre-deployment review of `cloudflare/brief-worker.js`
- **Fail-open window, caught before deployment**: `env.BRIEF_ACCESS_TOKEN`
  defaulting to `""` when unset meant a missing/empty request header
  would match a missing secret and serve the file with no
  authentication at all — and the documented setup order (bind the
  bucket, *then* set the secret) created exactly that window during
  setup. Fixed to fail closed: if the secret is missing or empty,
  every request gets the same 404, with no code path that can serve
  the object without it.
- Collapsed every non-success response (wrong method, missing/wrong
  token, missing secret, missing object) to one identical 404 — no
  more 403 for a bad token or 405 for a bad method, so a probe can't
  distinguish "wrong token" from "nothing here" from "method not
  supported."
- Replaced the hand-rolled XOR comparison loop with
  `crypto.subtle.timingSafeEqual` over SHA-256 digests of both the
  provided and expected token — confirmed `timingSafeEqual` is a real
  (if non-standard) Cloudflare Workers API before using it, not
  assumed. Hashing both sides to a fixed 32-byte digest first sidesteps
  `timingSafeEqual`'s equal-length requirement entirely, which is
  cleaner than Cloudflare's own documented example (a length-mismatch
  branch that compares a value against itself when lengths differ).
- `cache-control` tightened to `private, no-store`.
- Caught via review before this was ever deployed — the R2/Worker/phone
  verification in section 5 still hasn't happened, so this fix shipped
  before the fail-open window was ever live.

### Verified — v2 delivery is live, full loop closed
- Real `scheduled_send_voice.py` run pushed a real brief (657,702
  bytes) to `morningbrief-brief/latest.mp3`; confirmed independently of
  the Worker via a signed HEAD request straight to R2's S3 API —
  correct size, `content-type: audio/mpeg`, `Last-Modified` matching
  the push time.
- Worker deployed at `https://rapid-snowflake-a468.bizkitbrewing.workers.dev/`.
  Fail-closed/uniform-404 behavior confirmed live via `curl`: no token,
  a wrong token, and a wrong method (POST) all return the identical
  `404 Not Found` — no 403, no 405, nothing to distinguish one failure
  reason from another.
- Positive path (correct token) verified by the user directly, not by
  Claude — the real `BRIEF_ACCESS_TOKEN` never touches this codebase or
  conversation, per ADR-0003. Confirmed working via `curl` from the
  user's own Terminal, then for real from an iPhone over cellular:
  audio played.
- All three items in `R2_DELIVERY_PROPOSAL.md` section 5 are now
  complete. v2 delivery is live, not just built.

### Added — freshness enforcement in `brief-worker.js`
- The Worker now rejects any object older than 3 hours
  (`MAX_AGE_MS`), returning the same uniform 404 as every other
  rejection path — no distinct status or body. Closes a real gap: a
  failed voice run leaves the previous brief in place rather than
  removing it (by design, per the degradation contract), and iOS
  Shortcuts' `"Get Contents of URL"` action can't read the
  `Last-Modified` header the Worker already exposes, so a stale brief
  would otherwise play as if it were current — worst case, the
  morning brief playing at 17:00.
- 3 hours specifically, not a round number picked for convenience: the
  user's play windows are 07:10–09:30 and 16:40–19:00, each closing
  roughly 2.5h after its corresponding push, so a genuinely fresh
  brief always passes and a stale one from the other send always
  fails, with headroom either side.
- Everything else in the Worker (fail-closed secret check, uniform
  404s, `crypto.subtle.timingSafeEqual` token comparison, cache
  headers) is unchanged.
- Recorded as `DECISIONS.md` ADR-0004 (a short follow-on to ADR-0003,
  not an amendment — freshness enforcement is a distinct decision with
  its own reasoning worth preserving on its own).
- **Not yet deployed or verified**: the user redeploys by pasting the
  updated script into the Cloudflare dashboard, then confirms via
  `curl` (with the real token, which never comes to Claude) that an
  object older than 3h now 404s.

## 2026-09-08

### Added — TV watchlist and tech news rotation
- Added `tv_watchlist.py`: checks TVmaze (free, no key) for episodes of
  13 watched shows airing today or in the next ~48h. Silent by design
  on most days — the section costs nothing in either text or voice
  when nothing's airing, per a three-way contract different from the
  other fetchers (silence / a short line / a visible failure note,
  never raising). Show names resolved to TVmaze IDs via real API
  searches, with two flagged for confirmation (Peacemaker had a
  same-title anime near-tie in search score, resolved by content
  check; Demon Slayer stays in config despite showing "Ended," since
  its current story is theatrical-only and TVmaze tracks TV broadcast
  only). See `TV_TECH_PROPOSAL.md` for the full investigation.
- Added `tech_news.py`: mirrors `politics.py` exactly (Ars Technica +
  BBC Technology RSS, summarized via the same `claude -p` no-tool-access
  pattern). The Verge was evaluated and skipped — it's an Atom feed,
  not RSS, and wasn't worth a second parser branch for one source.
- **Section rotation**: the 07:00 send carries politics, 16:30 carries
  tech news instead — a genuine swap, not an addition. `brief.py` gained
  `is_morning_send()`, reusing the same hour check that already picked
  the commute leg, rather than a second independent time check (see
  `DECISIONS.md` ADR-0002). `BriefData.politics_line` renamed to
  `news_line` (paired with a new `news_label` field), since a field
  named for one topic holding another's content half the time would be
  misleading.
- `format_text()` and `voice_script.py`'s prompt data block both
  changed from fixed templates to conditional section assembly, so the
  TV line can be omitted cleanly when empty — the same mechanism any
  future optional section can reuse.
- `voice_script.py`'s prompt tone is unchanged; the data-supplying
  section was generalized (no longer hardcodes "headline summaries")
  and gained an explicit trim-priority instruction (news first, then
  TV, calendar/train never cut) now that up to five data points share
  the same ~140-170 word budget.
- Verified end-to-end for real: `tv_watchlist.py`/`tech_news.py` run
  standalone, `brief.py` picks the correct rotation for both explicit
  hours and the real current time, and a full `scheduled_send.py` +
  `scheduled_send_voice.py` run delivered both a text and voice brief
  with the tech section and (correctly) no TV line, since nothing was
  airing in the watchlist at test time.

### Changed
- Voice brief schedule expanded from weekday mornings only to the same
  weekday twice-daily schedule as the text brief (07:00/16:30).
  Originally morning-only by design (see `VOICE_PROPOSAL.md` section
  4), reconsidered same-day — there was no real reason for voice to
  run less often than text. `launchd/com.morningbrief.voice.scheduled.plist.template`
  updated with the additional `StartCalendarInterval` entries; live
  plist regenerated and reloaded.

### Fixed
- **Real production outage, caught same-day**: the text brief's
  `com.morningbrief.scheduled` launchd job still pointed at a bare
  system `python3` (`/usr/local/bin/python3`), a leftover from when
  the text-only pipeline had zero third-party dependencies. The
  calendar feature broke that assumption (`brief.py` now imports
  `calendar_events.py`, which needs `pyobjc-framework-EventKit`, only
  installed in this project's own `.venv`) but the live plist was
  never updated to match — unlike the voice job's plist, which already
  used `.venv/bin/python3` correctly. Today's real scheduled 16:30
  send crashed with `ModuleNotFoundError` and was silently missed
  (launchd doesn't retry or alert on a crashed job, it just logs and
  waits for the next scheduled time — caught by chance while answering
  a question about tomorrow's schedule, not by any alerting). Fixed by
  regenerating the live plist from the template with the correct
  interpreter, reloading it, and verifying a real kickstarted run
  completes cleanly. `launchd/com.morningbrief.scheduled.plist.template`
  updated with an explicit warning so a future re-registration doesn't
  regress the same way.
- A manual afternoon test run of the voice pipeline (verifying the new
  calendar feature) surfaced that `voice_script.py`'s prompt always
  opened with "Good morning" regardless of actual send time, since it
  hardcoded "spoken morning briefing script." Masked in production
  because the voice `launchd` job currently only runs at 07:00, but
  would misfire on any manual trigger later in the day or if the
  schedule ever expands. Fixed by computing an actual time-of-day
  label (morning/afternoon/evening) and passing it into the prompt,
  with an explicit instruction not to assume morning. Verified for
  real at 17:02 BST — correctly opened with "Good afternoon."

### Added — Voice edition v1
- Added a spoken audio briefing delivered as a Telegram voice note,
  alongside the existing text brief (not instead of it — an
  intentional degradation contract, see `VOICE_PROPOSAL.md` section 4
  and `CONTEXT.md`). Pipeline: `gather_brief_data()` → Claude API
  (`claude-opus-4-8`, direct SDK call, not the `claude -p` CLI pattern
  `politics.py` uses) writes a short warm/conversational spoken-style
  script → Piper TTS synthesizes it locally → `ffmpeg` converts to
  Opus/OGG → delivered via Bizkit's new `send_voice.py` primitive
  (`services/telegram-bridge/`, see Bizkit `DECISIONS.md` ADR-0012/13
  area).
- Default voice locked to `en_GB-alba-medium` after an A/B listen
  against three other Piper voices sent as labelled Telegram voice
  notes.
- Pinned `onnxruntime==1.23.0` and Python 3.13 (`.python-version`):
  this machine is an Intel Mac (x86_64, macOS 13.7.8) and onnxruntime
  dropped x86_64 macOS wheels after 1.23.0; 1.25.0+ needs macOS 14+
  and arm64. Both pins are load-bearing.
- Registered `launchd/com.morningbrief.voice.scheduled.plist`: weekday
  mornings at 07:00, alongside the text job's own 07:00/16:30 schedule
  — a separate launchd job so a voice-pipeline failure can never affect
  the text brief's own reliability.
- Added `CONTEXT.md`, a living half-page snapshot of current state
  (distinct from this changelog) — first instance of a new
  Bizkit-wide convention, see Bizkit `DECISIONS.md` ADR-0013.

### Added — Fallback visibility
- Previously, any voice-stage failure degraded silently to the plain
  text brief with no indication anything had gone wrong. Now
  `scheduled_send_voice.py`'s text fallback appends one short line —
  e.g. "Voice brief failed today: TTS stage." — naming which stage
  failed (script generation, TTS, audio conversion, or Telegram
  upload). The note-building is wrapped defensively so that if it ever
  fails, the plain brief still goes out unmodified — the rule that
  voice problems must never block or delay the text brief still holds.

### Added — Calendar awareness
- Added `calendar_events.py`: reads today's timed and all-day events
  from an explicit allowlist of macOS Calendar.app calendars
  (`Home`, `thomasandrewfaber@gmail.com`) via `EventKit`
  (`pyobjc-framework-EventKit`), local read only — no Google Calendar
  API integration, no cloud auth. See `DECISIONS.md` ADR-0001 and
  `CALENDAR_PROPOSAL.md` for the investigation behind the choice
  (`icalBuddy` rejected: unmaintained, documented TCC issues on
  Ventura+) and the TCC/permissions verification (confirmed working
  under a real headless `launchd` LaunchAgent using this project's
  actual interpreter, and to survive job re-registration).
- Follows the same degrade-independently contract as
  `weather.py`/`trains.py`: a calendar read failure returns a visible
  "Calendar unavailable right now (...)" line rather than raising or
  going silent, and can't block the rest of the brief.
- Wired into `brief.py` (`BriefData.calendar_line`, shown first in the
  text brief) and `voice_script.py`'s prompt (calendar mentioned
  naturally alongside train/weather/politics, with an explicit
  brevity nudge added to the prompt now that there are four data
  points sharing the same ~140-170 word budget).
- A live 21-day scan during investigation found the same events
  duplicated across two differently-named calendar sources syncing
  the same underlying Google calendar — `calendar_events.py` dedupes
  by `(title, start, end)` as a safety net regardless of which
  calendars end up allowlisted.
- Added `MorningBrief/DECISIONS.md` — a project-local decision log,
  its own equivalent of Bizkit's `DECISIONS.md`, starting with
  ADR-0001 for this feature.

## 2026-08-04

### Checked
- Reviewed `state/morningbrief.log` after ~5 days with the 2026-07-30
  retry/logging fix in place. Confirmed the original bug (weather 503s
  degrading silently) is fixed: real `HTTP 503`s from Open-Meteo hit
  twice (Jul 30, Jul 31) and both times the retry succeeded — no
  degraded message reached the operator.

### Found and fixed
- A separate, more serious pattern surfaced: `socket.gaierror` (DNS
  resolution failure) hit all three fetchers simultaneously across 4
  runs between 2026-08-03 07:45 and 2026-08-04 07:30 — a
  workstation/network-level outage, not an issue with any of the three
  APIs. Retries can't fix a genuinely absent network; noted as a known
  failure mode rather than "fixed," since there's nothing at the
  application layer to do about it beyond what already exists (retry,
  log, degrade gracefully).
- Found and fixed a real, distinct bug this surfaced: twice (2026-08-03
  23:17, 2026-08-04 07:30), right after the RSS fetch recovered from
  the DNS flakiness above, `politics.py`'s `claude -p` call failed with
  exit 1 and *empty* stderr — no diagnostic information at all. Root
  cause: `politics.py` invoked `claude` as a bare command rather than
  an absolute path, the same PATH-resolution gotcha already hit and
  fixed for `bridge.py` under `launchd` (see Bizkit's `DESIGN.md`) —
  but that fix was never applied here. Fixed by using the same absolute
  path (`~/.local/bin/claude`), and by logging `stdout` in addition to
  `stderr` on failure, and by explicitly catching `FileNotFoundError`
  with a clear message instead of letting a bad path degrade into an
  opaque exit code. Verified the improved diagnostics work by
  deliberately breaking the path and confirming a clear log message
  appears — not just assumed the fix helps.

## 2026-07-30

### Fixed
- Investigated reports of the weather section failing "pretty
  regularly." Root cause: `weather.py` had zero retry logic and
  swallowed every failure straight into the delivered message text
  (e.g. "Weather unavailable right now (HTTP Error 503: ...)"), with
  nothing logged anywhere — so the only evidence of a failure was
  whatever the operator happened to read in Telegram. Both
  `postcodes.io` and Open-Meteo tested healthy at investigation time,
  consistent with an intermittent transient issue rather than a hard
  outage or a bug in the request itself.
- Added `httputil.py` (shared HTTP-GET-with-retry: 3 attempts,
  short backoff, immediate raise on non-retryable 4xx) and
  `logutil.py` (shared rotating-file logger, `state/morningbrief.log`,
  gitignored). Applied to all three fetchers (`weather.py`,
  `trains.py`, `politics.py`), not just weather, since all three had
  the identical gap. Verified against a real simulated 503/timeout
  (`httpbin.org/status/503`) that retries and logging both fire
  correctly, and re-verified the happy path still works for all three
  after the refactor.
- `politics.py`'s `claude -p` summarization failure fallback (silently
  degrading to a plain headline list) now also logs the failure
  instead of vanishing silently.

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
