# Houseplant Watering Reminders: Design Proposal

Investigation-first, per instructions. No implementation yet — this
whole document is for review. **This feature genuinely spans two
repositories** — flagging that split up front since it's the first
feature that does:

- **`MorningBrief`** (this repo): the plant library/state, the
  learning/adjustment model, morning-brief integration, the evening
  check-in's content, free-text log parsing, away-mode logic.
- **Bizkit's `services/telegram-bridge`**: the only place that holds
  the bot token and talks to Telegram, so it's the only place that can
  send an inline keyboard, receive a button press, or receive
  free-text messages at all. Two real capability gaps exist there
  today (no callback-query handling, no proactive-message-with-buttons
  primitive) that this feature needs filled before any of
  MorningBrief's side can work.

Everything below is organized so you can approve each repo's slice
separately if you want to.

## 1. Investigation findings (Telegram Bot API specifics — verified, not assumed)

Since this introduces an entirely new interaction shape (buttons, not
just text), I verified the relevant API mechanics directly rather than
assuming from memory:

- **Inline keyboards**: `sendMessage`'s `reply_markup` takes
  `{"inline_keyboard": [[{"text": "...", "callback_data": "..."}, ...], ...]}`
  — a list of rows, each a list of buttons. `callback_data` is capped
  at **1–64 bytes UTF-8** — a real constraint on how much state can
  ride in the button itself (see schema below, this comfortably fits).
- **Button presses arrive as a new update type**, `callback_query`, not
  a `message` — bridge.py's `getUpdates` call currently passes
  `"allowed_updates": ["message"]`, which would silently never deliver
  button presses at all until `"callback_query"` is added to that list.
- **`CallbackQuery` fields**: `id` (str, needed to answer it), `from`
  (the pressing user — this is what gets checked against the
  allowlist, not the original message's sender), `message` (the
  message the button was attached to), `data` (the `callback_data`
  string, **untrusted input** — arrives from Telegram's servers, but
  nothing stops a malformed or adversarial value reaching the bridge).
- **`answerCallbackQuery` must be called for every callback_query**,
  success or failure — until it is, Telegram's client shows a loading
  spinner on the pressed button. It takes `callback_query_id`
  (required) and an optional `text` (0–200 chars) that shows as a
  small toast notification — no new message needs to be sent for a
  simple confirmation.
- **Critical timing constraint, verified**: a `callback_query` must be
  answered within roughly **10 seconds** of being received, or
  Telegram's API starts rejecting the `answerCallbackQuery` call with
  "query is too old." This directly affects the bridge design below —
  callback handling must be fast and must not be blocked behind a slow
  conversational turn.

## 2. The real bridge-side problem this surfaces

`bridge.py`'s poll loop is single-threaded and processes one
`getUpdates` batch's updates **in arrival order** — confirmed in
`DESIGN.md`'s own concurrency write-up ("a second message physically
cannot start a `claude -p` invocation while one is in flight, it
queues"). That's a deliberate, good property for conversational
messages. But it creates a real correctness problem for callback
queries specifically: if a slow `claude -p` turn (up to
`claude_timeout_seconds`, currently 300s) and a button press land in
the *same* batch, with the conversational message first in arrival
order, the button press won't even start being handled until the
300s-capable turn finishes — blowing past the ~10s answer window every
time.

**Proposed fix**: within a single batch, sort callback-query updates
to the front before processing — handle every `callback_query` in
this poll's batch first, then fall through to `message` handling in
original order. This is a small, local change (sort key, not a
redesign) and doesn't touch the existing concurrency guarantee for
messages. `offset` advancement is unaffected either way, since it only
needs to reflect the highest `update_id` seen once the whole batch is
done, not a strict per-item order.

## 3. Bizkit-side changes

### 3a. `callback_commands`: deterministic, bypass-the-LLM routing for button presses

Mirrors `custom_commands` (ADR-0011) exactly, applied to the new update
type. New `config.local.json` key:

```json
"callback_commands": {
  "plant": "/Users/mothtims/Projects/Personal/MorningBrief/plant_callback.py"
},
"callback_command_timeout_seconds": 8
```

Routing: `callback_data` is required to have the shape
`"<prefix>:<rest>"` — the bridge splits on the first `:`, looks up
`<prefix>` in `callback_commands`, and (if found) runs that script
with the **full, unmodified** `callback_data` string as `argv[1]`. If
no prefix matches, or the sender's `from.id` isn't the allowlisted
user, the bridge answers the callback with a generic empty
acknowledgement and does **not** run anything — same "silently drop"
posture as unauthorised messages today.

**Validation split, matching the `custom_commands` trust model**: the
bridge itself only validates (1) sender identity, and (2) that
`callback_data` is a bounded-length string matching a safe character
set (e.g. `^[a-z0-9_]+:[a-z0-9_:.-]{1,60}$` — conservative, rejects
anything that doesn't look like our own button data before it ever
reaches a script). The *script* (`plant_callback.py`, living in
MorningBrief, not Bizkit) is responsible for the actual semantic
validation — does this plant id exist, is this action one of the three
we know about — exactly the same "the script is the trust boundary"
split `custom_commands` already established. `callback_data` is never
passed to `invoke_claude()` under any circumstance.

**Timeout is deliberately much shorter than `custom_command_timeout_seconds`**
(8s vs 120s) — given the ~10s answer window above, a callback script
has to be fast by construction: no network calls, just local state-file
reads/writes. This is a real constraint on `plant_callback.py`'s design,
not just a config nicety — flagging it as a hard requirement to carry
into section 4.

**Always answer, using the script's stdout as the toast**: after
running the script (or immediately, if routing failed above), the
bridge calls `answerCallbackQuery` with `text` set to the script's
stdout (truncated to 200 chars) — e.g. `"Marked Basil as watered 🌱"` —
mirroring `invoke_custom_command()`'s "script's stdout is the reply"
pattern, just delivered as a toast instead of a new message. **Message
editing (removing/updating buttons after a press) is deliberately out
of scope** — see section 5's idempotency note for why this is fine.

### 3b. Prefix-matched free-text routing (new capability, needs its own ADR)

`custom_commands` is exact-match only (`/brief` must be the *entire*
message). Free-text plant logging ("watered the basil") has variable
content after a fixed-ish lead-in, so exact match doesn't fit. New
config key:

```json
"text_patterns": [
  {"prefix": "watered ", "script": ".../plant_log.py"}
]
```

Matching is deliberately narrow — **case-insensitive `str.startswith()`
only, never a general regex** — to keep the auditability property
`custom_commands` was designed around (DESIGN.md: "a smaller, simpler,
and more auditable surface"). A matching message is routed to the
script with the *remainder* of the text (after stripping the matched
prefix) as `argv[1]`; the script's stdout becomes a normal
`sendMessage` reply, exactly like `custom_commands` today. A
non-matching message falls through to the existing conversational path
completely unchanged — this is additive, not a change to today's
behavior for anything that isn't plant-logging shaped.

This is a generalization of ADR-0011's trust model, so it needs its own
Bizkit ADR (drafted in section 7) rather than silently extending
ADR-0011's text.

### 3c. New primitive: `send_message_with_keyboard.py`

Sibling to `send_message.py`/`send_voice.py` (ADR-0012's "separate,
minimal primitive" pattern) — same Keychain token, same
`allowed_user_id`, one new capability: accepts a JSON payload on stdin
with `{"text": "...", "keyboard": [[{"text": "...", "callback_data": "..."}]]}`
and calls `sendMessage` with `reply_markup` attached. This is the only
new piece needed to make the 19:30 check-in possible — everything else
in this primitive matches `send_message.py` exactly (timeout, chunking
isn't needed since check-in text is always short, error handling).

## 4. MorningBrief-side: plant state and the learning/adjustment model

### 4a. State file: `state/plants.json`

Gitignored, like the rest of `state/` — this is explicitly *state*,
not config, per your framing. Seeded with your 7 plants:

```json
{
  "plants": [
    {"id": "banana", "name": "Banana (Musa)", "location": "warm spot by conservatory",
     "range_days": [5, 7], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": null},
    {"id": "croton_gold_dust", "name": "Croton 'Gold Dust'", "location": "playroom windowsill",
     "range_days": [6, 9], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": null},
    {"id": "croton_narrow", "name": "Croton (narrow-leaf)", "location": "playroom windowsill",
     "range_days": [6, 9], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": null},
    {"id": "dragon_tree", "name": "Dragon tree (Dracaena marginata)", "location": "on the piano",
     "range_days": [10, 14], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": null},
    {"id": "basil", "name": "Basil", "location": "kitchen windowsill",
     "range_days": [2, 4], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": null},
    {"id": "flaming_katy", "name": "Flaming Katy (Kalanchoe)", "location": "kitchen windowsill",
     "range_days": [14, 21], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": null},
    {"id": "pink_quill", "name": "Pink quill (Tillandsia cyanea)", "location": "kitchen windowsill",
     "range_days": [7, 10], "last_watered": "2026-10-06",
     "learned_adjustment_days": 0, "deferred_until": null, "notes": "bright indirect light"}
  ]
}
```

`id` is a stable slug used in `callback_data` (comfortably within the
64-byte limit: `plant:pink_quill:watered` is 24 bytes). `range_days` is
the **base, unadjusted** range you gave me — the seasonal/temperature
model (4b) never mutates this; it's the input, not a running value.
`learned_adjustment_days` is the one field the "still damp" signal
nudges over time (4c). `deferred_until` is set by "still damp" to
suppress re-flagging for a couple of days without touching
`last_watered` (since the plant wasn't actually watered).

**One thing I need your call on**: you wrote "Pink quill ... 7–10,
light" — I've interpreted "light" as a care note (bright indirect
light, stored in `notes`, informational only) rather than something
that feeds the watering model. If you meant something that should
actually *change* the math (e.g. "epiphytic, don't water the
soil/pot the way the others are watered — mist or soak instead"),
tell me and I'll fold it into the brief's phrasing for that plant
specifically. As given, it has zero effect on the due-date
calculation.

**Daily/ephemeral state is a separate file**, `state/plant_daily.json`,
overwritten each morning rather than accumulated:

```json
{"date": "2026-10-06", "flagged": {"basil": "pending", "pink_quill": "pending"}}
```

Values: `"pending"` (flagged this morning, no response yet),
`"watered"`/`"damp"`/`"notyet"` (a button was pressed). This is what
the 19:30 check-in reads to know who still needs asking, and keeping
it separate from `plants.json` means the durable plant facts file
never has today-shaped clutter mixed into the plants themselves.

**Away state**, also separate, `state/plant_away.json`, absent/empty
when not away: `{"away_until": "2026-10-11", "source": "calendar"}`.

### 4b. Seasonal multiplier — a tunable month lookup table, not a formula

You described the 7 ranges as "my starting autumn values" — so October
is the calibration point, not a hypothetical baseline that needs
stretching *now*. I've built the table so October/April sit at `1.0`
(no change from what you gave me), stretching further into winter and
compressing back down through summer:

```python
SEASONAL_MULTIPLIER = {
    1: 1.25, 2: 1.25,            # Jan, Feb — deep winter, slowest growth
    3: 1.10,                      # Mar — easing off winter
    4: 1.00,                      # Apr — reference
    5: 0.95,                      # May — ramping into growing season
    6: 0.85, 7: 0.85, 8: 0.85,    # Jun–Aug — summer, thirstiest
    9: 0.95,                      # Sep — easing down
    10: 1.00,                     # Oct — reference (your calibration month)
    11: 1.10,                     # Nov — heading into winter
    12: 1.25,                     # Dec — deep winter
}
```

A plain 12-entry dict, keyed by calendar month, each value independently
editable — I picked this representation specifically because you asked
to be able to tune thresholds, and a lookup table is far easier to
reason about and adjust than a continuous seasonal formula.

### 4c. Temperature factor — asymmetric, heat-dominant, with a hard override

Using tomorrow's forecast high too (see 4d for why), not just today's:

```python
def temperature_factor(forecast_high_c: float) -> float:
    if forecast_high_c >= 30:
        return "DAILY"       # override: every plant checked, ignore range entirely
    if forecast_high_c >= 28:
        return 0.65          # hot — ranges shrink sharply
    if forecast_high_c >= 25:
        return 0.85          # warm — noticeably thirstier
    if forecast_high_c <= 10:
        return 0.95          # cold — mild shortening only (heating dries the air)
    return 1.00               # 10–25°C — comfortable, no adjustment
```

Four tunable thresholds (10, 25, 28, 30°C) and three tunable factors
(0.95, 0.85, 0.65), plus the explicit 30°C+ override you specified.
Deliberately asymmetric per your instruction — cold floors at a mild
0.95, heat has three escalating steps down to a full override.

### 4d. Combining the two, and warning a day ahead

```
effective_low  = range_days[0] * seasonal_multiplier * temperature_factor + learned_adjustment_days
effective_high = range_days[1] * seasonal_multiplier * temperature_factor + learned_adjustment_days
due = days_since(last_watered) >= effective_low   # unless deferred_until is still in the future
```

**The brief always displays the original configured range** ("usual
2–4"), never the computed `effective_low`/`effective_high` — matching
your own example phrasing exactly. The adjustment changes *when* a
plant gets flagged, not what number gets shown; `days_since(last_watered)`
is always the real, honest day count.

**Ahead-of-heat warning**: `weather.py` currently fetches a single-day
forecast (`forecast_days=1`). I'm proposing a new small function there,
`forecast_highs(postcode, days=2) -> list[float]`, reusing the existing
`postcode_to_coords` step (just bumping the Open-Meteo `forecast_days`
parameter) rather than duplicating the postcode→coordinates logic in a
new plant-specific fetcher. `plant_care.py` uses `[today_high,
tomorrow_high]`: if tomorrow crosses the 28°C/30°C thresholds while
today doesn't, the morning brief gets a distinct, separate line —
"Heads up — tomorrow's forecast is 31°C, so give everything a quick
check today just in case" — rather than silently waiting for the heat
to arrive before reacting. This is a separate branch in the output,
not folded into the normal per-plant due list, since it's structurally
a different kind of warning (anticipatory, whole-collection) from "this
specific plant is due."

### 4e. Brief integration

Reuses `brief.py`'s existing `is_morning_send()` (ADR-0002's "single
source of truth," not a second time check) — the plant section is
populated only on the 07:00 send, empty string on the 16:30 send,
following exactly the same silent-when-empty contract as `tv_line`.

**Open question for you**: your instructions say "Brief integration
(morning brief only)" — I've read this as "scoped to the morning
time-of-day" (appears in *both* text and voice for the 07:00 send,
silent on the 16:30 send), consistent with how every other section
(calendar, TV, news) already flows through `BriefData` into both
surfaces. If you actually meant "text brief only, never voice," that's
a one-line change (just don't add the field to the voice prompt's
data block) — tell me which you want. I've written the rest of this
proposal assuming the first (both surfaces, morning-only).

Grouped phrasing, matching your example:

```
🌱 The basil's at day 3 of its usual 2–4 and the pink quill's at day 8
of its usual 7–10 — finger test, water if the top inch is dry.
```

Degradation: `plants.json` unreadable/corrupt → a visible one-line
"Plant check unavailable right now (...)" note, same contract as every
other fetcher (`calendar_events.py`, `tv_watchlist.py`) — never raises,
never blocks the rest of the brief.

### 4f. The evening check-in: `plant_checkin.py`

New launchd job, **~19:30 weekdays** (your own spec) —
`com.morningbrief.plant_checkin.plist`, a periodic `StartCalendarInterval`
job like the existing scheduled sends, not a persistent daemon.

Logic: read `state/plant_daily.json`; for every plant still
`"pending"` (flagged this morning, no button pressed yet), build one
combined message:

```
🌱 Evening plant check:

Basil (kitchen windowsill)
[Watered]  [Still damp]  [Not yet]

Pink quill (kitchen windowsill)
[Watered]  [Still damp]  [Not yet]
```

— one inline-keyboard row per plant, `callback_data` shaped
`plant:<id>:<action>` (`watered`/`damp`/`notyet`), sent via
`send_message_with_keyboard.py`. If `plant_daily.json` is missing or
unreadable, or nothing is pending, the job **sends nothing** and just
logs — matching the R2-push precedent (best-effort proactive feature,
silent skip rather than a garbled message) rather than the core
brief's never-silent contract, since this genuinely is optional. On a
genuine failure partway through (e.g. the Telegram call itself errors),
it sends one small supplementary text note via `send_message.py`
("Plant check-in failed today (...)") for visibility, same shape as
the R2-push failure note.

### 4g. `plant_callback.py` — handling a button press

Invoked by the bridge's `callback_commands` routing (3a) with the raw
`callback_data` as `argv[1]`. Must be fast (no network calls — the
~10s answer window in section 1/2 is a hard constraint here, and this
script only ever touches local JSON files, so it's comfortably fast by
construction).

1. Validate strictly: `^plant:([a-z0-9_]{1,40}):(watered|damp|notyet)$`.
   Anything else → print a generic "Didn't understand that" and exit;
   the bridge still answers the callback with that text.
2. Look up the plant id in `plants.json` — unknown id → same generic
   rejection (don't trust `callback_data` just because it parsed).
3. **Idempotency, not message-editing**: check `plant_daily.json` — if
   this plant is no longer `"pending"` (already answered earlier this
   evening), do nothing and reply "Already logged 👍" via the toast.
   This is the deliberate simplification mentioned in section 3a:
   **buttons are not removed or disabled after use**. Re-pressing an
   already-answered button is a safe no-op with instant feedback,
   rather than editing a multi-plant message's keyboard to surgically
   remove one row (which would require `plant_callback.py` to either
   reconstruct the full remaining keyboard from scratch, or for
   MorningBrief scripts to gain their own direct Telegram API access —
   both meaningfully more complex for a cosmetic improvement). Flagging
   this explicitly as a tradeoff, not an oversight — tell me if stale
   buttons bother you enough to warrant the extra complexity.
4. Apply the action:
   - `watered`: `last_watered = today`, clear `deferred_until`, mark
     `plant_daily.json` entry `"watered"`.
   - `damp`: `deferred_until = today + 2 days`, `learned_adjustment_days += 1`
     (small, persistent, one-directional nudge — matches your spec
     exactly: "nudge its learned range longer over time," no symmetric
     shrink-on-early-water signal requested, so none is built).
     `last_watered` is **not** touched, since the plant wasn't
     actually watered.
   - `notyet`: mark `plant_daily.json` entry `"notyet"`, change nothing
     else. The *next morning's* `plant_care.py` run naturally re-evaluates
     `days_since(last_watered)` from scratch and will re-flag it if
     still due — no special "remember to re-ask" logic is needed,
     since due-ness is always recomputed fresh from `last_watered`,
     never cached.
5. Print a short confirmation to stdout (becomes the toast text, per 3a).

### 4h. Free-text logging: `plant_log.py`

Invoked by the bridge's new `text_patterns` routing (3b) when a
message starts with "watered " (case-insensitive), receiving the
remainder as `argv[1]` (e.g. `"the basil"` or `"everything on the
kitchen windowsill"`).

Matching strategy — simple substring containment against known plant
`name`s and `location`s, not fuzzy/NLP matching (consistent with this
project's established "config-driven rules, not model inference"
preference, ADR-0005): lowercase both the input and every plant's name
+ location, check containment either way. `"the basil"` matches
`Basil`'s name. `"everything on the kitchen windowsill"` matches three
plants' `location`. Every match gets `last_watered` set to today. The
script's stdout (one line per matched plant, or a clear "didn't match
anything, try a plant name or location" message) becomes the bridge's
normal `sendMessage` reply.

## 5. Away mode

Two mechanisms, composing rather than competing, per your "Telegram
command and/or calendar" framing:

**Calendar detection (automatic, zero-effort)**: `calendar_events.py`
currently only exposes a formatted *string* (`summarize_calendar()`) —
this needs one new function, `get_events(allowed_calendars) -> list[dict]`,
returning structured `{title, start, end, all_day}` dicts, reusing the
exact same TCC-granted EventKit access and calendar allowlist already
verified working (ADR-0001) — no new permission, no new infrastructure.
A small new module, `plant_away.py`, scans for all-day events whose
title contains a configurable keyword (default: `["away", "holiday",
"trip"]`, in `config.local.json`) overlapping today or starting soon,
and sets `plant_away.json` automatically from the matched event's date
range.

**Manual override**: a message starting with `"/plants away"` (routed
via the same `text_patterns` mechanism as plant logging — e.g. `"/plants
away 5"` for 5 days, or `"/plants away 2026-10-15"` for a specific
return date) sets `plant_away.json` explicitly; `"/plants back"` clears
it early. **Manual always wins** when both are present — simplest rule
that still lets you override a calendar-detected event that's wrong, or
extend/shorten a trip without editing your calendar.

**Effect while away**: the morning brief's plant section is replaced by
one summary line instead of the normal per-plant flagging —
"You're away until Oct 11 — due while away: Basil (~Oct 8), Pink quill
(~Oct 9)" — computed by projecting each plant's `effective_low` forward
against `last_watered`, without the usual "finger test" phrasing (not
actionable from afar). The 19:30 check-in job **skips entirely** while
away (no point prompting for watering you can't do, and no need to
re-ask every evening of a week-long trip). On return, nothing special
happens — `days_since(last_watered)` is still computed honestly from
the real last-watered date, so plants will correctly (and probably
immediately) flag as overdue the first morning back.

## 6. Failure modes — summary

| Failure | Behavior |
|---|---|
| `plants.json` corrupt/unreadable | Morning brief shows a visible "Plant check unavailable" note; never raises, never blocks other sections (matches every existing fetcher). |
| `plant_daily.json` corrupt/missing when check-in runs | Check-in sends nothing, logs only — treated as "nothing pending," not an error worth interrupting an evening for. |
| Check-in's Telegram call fails | One small supplementary text note via `send_message.py`, same shape as the R2-push failure note. |
| `callback_data` malformed/adversarial | Rejected at the bridge (regex) before reaching any script; rejected again inside `plant_callback.py` (unknown id/action) — defense in depth, bridge validates shape, script validates semantics. |
| Button pressed for an already-answered plant | Idempotent no-op, "Already logged" toast — not an error. |
| Bridge down when a button is pressed | Telegram queues the `callback_query` like any update; delivered on the bridge's next `getUpdates` poll once it's back up. If significant time has passed, `answerCallbackQuery` may itself fail ("query too old") — the action still wouldn't be lost silently, since `plant_callback.py` runs and updates state *before* that answer call, but the user wouldn't get the toast confirmation. Edge case, not fixable without changing Telegram's own query-expiry behavior. |
| Forecast fetch fails (for the temperature factor) | `plant_care.py` treats this the same as "can't get a temperature factor" — falls back to `temperature_factor = 1.0` (seasonal-only adjustment) rather than failing the whole plant section over a weather-API hiccup; logged, not surfaced as a separate visible note (weather's own section already surfaces weather-API failures). |

## 7. Draft ADRs

### MorningBrief `DECISIONS.md` — ADR-0006: Plant watering model — config-driven ranges with code-computed seasonal/temperature adjustment, not a fixed schedule

**Context:** Houseplant watering needs vary by season and weather in
ways a fixed per-plant interval can't capture — the same basil needs
water roughly twice as often in August as in January. The brief should
flag plants proactively (ahead of a hot day, not after), using
language the user actually finds useful ("day 3 of its usual 2–4"),
without either hardcoding plant-specific logic or asking an LLM to
infer watering science from a prompt.

**Decision:** Each plant's base range (`range_days`, in
`state/plants.json`) is the user's own given values, never mutated by
the model. Two independently-tunable adjustment layers — a 12-entry
month→multiplier lookup table (seasonal) and a four-threshold
asymmetric temperature factor keyed on forecast high (today and
tomorrow, so heat can be warned about a day ahead) — combine
multiplicatively to compute an effective due-date threshold, with an
explicit hard override (every plant becomes a daily check) at 30°C+.
The brief always displays the *original* configured range, never the
computed effective one, so the user's mental model of each plant stays
anchored to numbers they chose. A `learned_adjustment_days` field
nudges one plant's effective range longer over time specifically in
response to repeated "still damp" signals — the only place this model
learns from feedback rather than from static config.

**Consequences:** Tuning the model (a different summer factor, a
different hot-day threshold) is an edit to two small lookup
tables/dicts, not a code change to the due-date logic itself. The
model is asymmetric by design (heat dominates, cold is mild) and that
asymmetry is a tracked decision, not an accident of whatever numbers
were first tried. `learned_adjustment_days` only ever grows — no
symmetric "shrink on early watering" signal was requested or built;
revisit if that turns out to matter in practice.

### Bizkit `DECISIONS.md` — ADR-0014: Callback-query and prefix-matched text routing extend the existing deterministic-bypass model, never reach `invoke_claude()`

**Context:** `MorningBrief`'s plant feature needs two new interaction
shapes the bridge has never supported: inline-keyboard button presses
(`callback_query` updates, not `message`) and free-text messages with
a fixed lead-in but variable content ("watered the basil"). ADR-0011's
`custom_commands` only covers exact-match full-message text — neither
new shape fits that mechanism as-is, and routing either through
`invoke_claude()` would mean a bare numeric/button-origin payload or
loosely-structured free text reaching a model with tool access, which
is exactly what ADR-0010's permission gate and ADR-0011's "the script
is the trust boundary" design exist to avoid.

**Decision:** Two narrow, deterministic extensions, both bypassing
`invoke_claude()` entirely, matching ADR-0011's existing split (bridge
validates shape/identity, the configured script validates semantics):
`callback_commands` (prefix-before-first-colon routing for
`callback_data`, strict regex-validated at the bridge before any script
runs, resolved with a short ~8s script timeout to fit Telegram's
~10-second callback-answer window) and `text_patterns`
(case-insensitive `str.startswith()` routing only — deliberately never
a general regex or fuzzy match, to preserve the auditability property
these mechanisms are built around). Within a single `getUpdates` batch,
`callback_query` updates are handled before `message` updates
regardless of arrival order, since a slow conversational turn
(`claude_timeout_seconds`, up to 300s) sharing a batch with a button
press would otherwise reliably blow past the callback-answer window.

**Consequences:** The bridge gains two more places where "what's
pre-configured to run" is the entire trust boundary, same as
`custom_commands` — reviewed per-script, same as before. Every
`callback_query` is answered (success, rejection, or timeout alike),
since an un-answered button shows a permanently-loading spinner on the
user's client. Message editing after a button press is explicitly out
of scope for this round (see `MorningBrief`'s `PLANT_CARE_PROPOSAL.md`
section 4g) — idempotent re-presses handle the same underlying problem
more simply, at the cost of stale-looking buttons after use.

## 8. Scope estimate

**MorningBrief:**
- `state/plants.json`, `state/plant_daily.json`, `state/plant_away.json` — seed data + schema, no code.
- `plant_care.py` — new module, ~120-150 lines (seasonal table, temperature factor, due-date logic, ahead-of-heat branch, away-mode summary branch, degrade-on-failure).
- `weather.py` — add `forecast_highs(postcode, days=2)`, ~15 lines, no change to existing `summarize_weather()` behavior.
- `calendar_events.py` — add `get_events(allowed_calendars)` returning structured dicts, ~20 lines, alongside the existing `summarize_calendar()`.
- `plant_away.py` — new module, ~40 lines (calendar-keyword scan + manual override state).
- `brief.py` — one new `BriefData` field, wired through `is_morning_send()`, ~10 lines.
- `voice_script.py` — one new data-block line, conditional on non-empty, ~5 lines (pending your answer on section 4e's open question).
- `plant_checkin.py` — new scheduled entry point, ~60 lines, mirrors `scheduled_send_voice.py`'s structure.
- `plant_callback.py` — new script, ~50 lines (validation, idempotency check, three action branches).
- `plant_log.py` — new script, ~40 lines (substring matching, confirmation text).
- `launchd/com.morningbrief.plant_checkin.plist.template` — new periodic job, weekdays ~19:30.
- `DECISIONS.md` — ADR-0006 (drafted above).
- `config.example.json`/`config.local.json` — away-keyword list.

**Bizkit:**
- `bridge.py` — `callback_query` handling (new function, ~40 lines), batch reordering (~10 lines), `text_patterns` routing (new function, ~25 lines), two new config keys read.
- `send_message_with_keyboard.py` — new primitive, ~40 lines, near-identical to `send_message.py`.
- `config.example.json`/`config.local.json` — `callback_commands`, `callback_command_timeout_seconds`, `text_patterns`.
- `DECISIONS.md` — ADR-0014 (drafted above).

Overall: a genuinely two-repo feature, each side individually
contained and following patterns already established in each
codebase — no new third-party dependencies anywhere, no new external
infrastructure (unlike R2/Cloudflare), no change to the bridge's
existing conversational path or permission gate.

## 9. Open questions needing your decision

1. **"Light" on the pink quill** (section 4a) — care note only, or
   should it change the watering model somehow?
2. **Morning-only scope** (section 4e) — both text and voice on the
   07:00 send (my assumption), or text-only?
3. **Weekend gap, found during investigation, not something you
   asked about**: both existing scheduled jobs
   (`com.morningbrief.scheduled.plist`, the voice equivalent) only run
   **weekdays** — `StartCalendarInterval` has no Saturday/Sunday
   entries at all. Basil's 2–4 day range means a Friday-morning check
   to Monday-morning check (a 3-day real gap) could already be at the
   edge of its range by the time anyone's told, and a hot weekend gets
   zero warning either, since there's no brief at all to carry it.
   Options: (a) accept this — plants survive one missed weekend
   window fine in practice, and you'll notice obviously wilted plants
   yourself; (b) add a lightweight weekend-only job that runs *only*
   the plant check (no train/weather/news) as a small standalone
   Telegram message, Saturday and Sunday mornings. Not scoped into the
   estimate above — tell me if you want (b) and I'll fold it in before
   building anything.
4. **Stale buttons after use** (section 4g) — accept the
   idempotent-no-op simplification, or is editing the message to
   remove answered rows worth the added complexity to you?

Nothing above blocks starting on the parts that aren't in question —
happy to build everything except the specific pieces your answers
would change, if you'd rather not wait on all four before I start.

## 10. Resolved — approved with changes, built in two slices

All four open questions answered, plus five changes on top of the
original proposal:

1. **Pink quill "light"**: light *watering*, not light exposure.
   `care_note` on that plant reads "a small drink and a mist, not a
   soak"; no change to the due-date maths.
2. **Morning scope**: both text and voice on the 07:00 send, as
   assumed.
3. **Weekend gap**: option (b) — `plant_weekend.py`, Sat/Sun ~09:00,
   plant-only/text-only, including the ahead-of-heat warning.
   `plant_checkin.py` runs seven days a week, not weekdays only.
4. **Stale buttons**: idempotent no-op accepted as-is.
5. **`learned_adjustment_days`** capped at 50% of a plant's base
   upper bound, with slow decay (-1 per ~4 weeks without a fresh
   "still damp" signal) so winter learning doesn't persist into
   summer — see `DECISIONS.md` ADR-0006 for the exact tunables.
6. **`plant_log.py`** matches one direction only (plant
   name/location found *in* the input, never the reverse — the
   original design would have matched almost every plant on a short
   input like "watered a"), plus an explicit "everything"/"all"
   keyword (whole-word matched) for logging every plant at once.
7. **Away detection** only treats a calendar event as the listener's
   own away event if it's genuinely multi-day *and* all-day, and the
   title doesn't name another household adult — a new, narrow,
   explicit `household.other_adult_names` config list (separate from
   the LLM-facing `attribution_rules`/`implication_rules`) does the
   "is this someone else's trip" check deterministically.
8. **ADR-0014** (Bizkit) states plainly that the callback-first batch
   sort only covers updates arriving together in one `getUpdates`
   call — a press during an in-flight `claude -p` turn still waits
   for the poll loop; the real backstop is applying state before
   attempting to answer the callback.
9. **`plant_checkin.py`** verifies `plant_daily.json`'s date equals
   today before trusting its contents — a stale file is treated as
   nothing pending, not yesterday's list.

Built in two slices (Bizkit's `telegram-bridge` first, then
MorningBrief), diffs shown and approved separately for each. All
verified against real data before being presented — the TVmaze-style
"test with synthetic data, then confirm against something real"
discipline applied throughout: real calendar events for `get_events()`,
a real 2-day forecast for `forecast_highs()`, real due/grouped-line
output (including pink quill's custom phrasing), the actual cap/decay
math over simulated weeks, the original "watered a" bug reproduced
and confirmed fixed, Sarah's-trip-shouldn't-count-as-Tom's-away
confirmed via the household filter, and the two latency-sensitive
scripts (`plant_callback.py`, `plant_log.py`) confirmed working under
the bridge's own bare interpreter, not just MorningBrief's `.venv`.
