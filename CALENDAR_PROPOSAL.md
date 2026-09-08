# Morning Brief — Calendar Awareness: Design Proposal

Investigation-first, per instructions. Everything in section 1 below was
empirically verified on this machine before any design work started — no
implementation has happened; this whole document is for review.

## 1. Investigation findings

### 1a. TCC/permissions — the make-or-break question

**Verified working, end-to-end, under a real `launchd` LaunchAgent, using
the exact production interpreter.**

What was tested (all read-only, no project files touched):

1. A throwaway scratch venv built directly against
   `~/.local/share/uv/python/cpython-3.13.14-macos-x86_64-none/bin/python3.13`
   — the literal binary `MorningBrief/.venv/bin/python3` resolves to via
   symlinks. Confirmed via `codesign`/`readlink` this was byte-identical
   to what a real launchd job would invoke, not a stand-in.
2. `pyobjc-framework-EventKit` installed into that scratch venv only.
   Confirmed via PyPI metadata that `pyobjc-core` 12.2.2 ships a
   `cp313-macosx_10_13_universal2` wheel — covers Python 3.13, Intel and
   Apple Silicon, macOS 10.13+. No repeat of the onnxruntime wheel-gap
   problem.
3. A throwaway `launchd` LaunchAgent (`com.bizkit.caltest`, loaded via
   `launchctl load` + `kickstart -k`, same mechanism the real MorningBrief
   jobs use) ran a script calling
   `EKEventStore.requestFullAccessToEventsWithCompletion_`.
4. Confirmed via `TCC.db` directly that this exact interpreter path had
   **zero prior Calendar grant** before the test — a genuinely cold start,
   not reusing some pre-existing trust.
5. Result: **access granted on the first launchd-triggered attempt**, no
   hang, no manual step performed during the run itself. `TCC.db` recorded
   a fresh, permanent grant keyed to that interpreter path.
6. Re-tested after `launchctl unload` + `launchctl load` (simulating a
   re-registration, e.g. after editing the plist): access remained
   granted, no re-prompt, `authorizationStatusForEntityType_` returned
   `3` (authorized) immediately. **Confirmed: survives re-registration.**
7. Reboot persistence was **not** live-tested (didn't reboot your machine
   for this) — but `TCC.db` is Apple's standard persistent SQLite store,
   not session state, so this is documented behavior rather than a real
   risk. Flagging as the one unverified-by-me claim in this list.

**One honest caveat**: no permission dialog was visibly triggered or
handled by me during any of this — access was simply granted. I can't
see your screen, so I can't rule out a system prompt appeared and
resolved itself on your end without me noticing. Functionally the
outcome is what matters (it works, and persists), but if you *did* see a
Calendar permission prompt during this session, that's worth mentioning
— it would confirm the normal interactive-grant path rather than
whatever silent path this appears to have taken.

**Practical implication for the design**: TCC grants are bound to the
specific interpreter binary's path/identity, not to the project or
script. This matters if `MorningBrief`'s Python version or the uv-managed
interpreter path ever changes (e.g. a future `.python-version` bump) —
that would require a fresh grant, exactly like the `onnxruntime`/Python
3.13 pin already requires care before bumping.

### 1b. Calendars found — allowlist decided: `Home`, `thomasandrewfaber@gmail.com`

```
- 'Birthdays'                       source='Other'                       (auto-generated from Contacts, not writable)
- 'Home'                            source='iCloud'                      writable
- 'Work'                            source='iCloud'                      writable
- 'Holidays in United Kingdom'      source='Google'                      not writable
- 'sarahfoxfaber@gmail.com'         source='Google'                      not writable
- 'thomasandrewfaber@gmail.com'     source='Google'                      writable
- 'sarahfoxfaber@gmail.com'         source='sarahfoxfaber@gmail.com'     not writable
- 'UK Holidays'                     source='Subscribed Calendars'        not writable
```

Decided: `config.local.json`'s `calendar_allowlist` will be `["Home",
"thomasandrewfaber@gmail.com"]`. This sidesteps the `sarahfoxfaber@gmail.com`
duplicate-source issue entirely (neither is allowlisted) and both holiday
calendars are excluded too. The dedupe-by-`(title, start, end)` logic in
the design below stays in as cheap insurance regardless.

Tell me which of the 8 to allowlist and I'll write them into config.

### 1c. Edge cases — verified against real data where possible

- **All-day events**: `isAllDay` is `True`/`False` on `EKEvent` as
  expected. Internally, an all-day event's `startDate`/`endDate` are
  stored as UTC instants offset by the local UTC offset (e.g. a
  16 Sept all-day event showed `start=2026-09-15 23:00:00 +0000` because
  BST is UTC+1) — naive UTC-date comparison would misclassify which
  calendar day it belongs to. Verified my test script's approach (using
  `NSCalendar.startOfDayForDate_` in the local timezone, not raw UTC
  date comparison) classifies these correctly. The real module needs to
  use the same local-calendar-day approach, not string-slice the date.
- **Timezone handling**: timed events reported their zone correctly and
  automatically as `Europe/London (BST) offset 3600 (Daylight)` — DST is
  handled by EventKit itself, no manual math needed. All-day events
  report `timeZone=None`, which is correct (they're not tied to a clock
  instant).
- **Multi-day events spanning today**: no real example existed in the
  next 21 days to test against, so this is designed defensively rather
  than empirically confirmed. The fetch already uses
  `predicateForEventsWithStartDate_endDate_calendars_` against a
  local-midnight-to-midnight window, which by Apple's documented
  semantics returns events that *overlap* the window, not just events
  that *start* in it — so a multi-day event should already be included
  correctly. Worth a real test once one exists on the calendar, but not
  a blocker.
- **Empty day**: verified for real — today has zero events, and the
  fetch correctly returned an empty list. This is the "clear day today"
  case from the goal description, confirmed working as-is.

## 2. Design

### New module: `calendar_events.py` (flat layout, matches `trains.py`/`weather.py`/`politics.py`)

```python
def summarize_calendar(allowed_calendar_names: list[str]) -> str:
    """Returns a short natural-language summary of today's events from
    the allowlisted calendars, or a plain 'no events' line, or a
    degraded-but-visible message on failure - never raises."""
```

Internals:
- Request calendar access (`EKEventStore`, `pyobjc-framework-EventKit`).
  First run on a given interpreter triggers/confirms the TCC grant (see
  1a); subsequent runs are instant.
- Filter `store.calendarsForEntityType_` down to the configured
  allowlist by title.
- Fetch today's local-midnight-to-midnight window via
  `predicateForEventsWithStartDate_endDate_calendars_`.
- Dedupe by `(title, startDate, endDate)` — cheap insurance against the
  duplicate-source problem found in 1b, regardless of what gets
  allowlisted.
- Sort by start time; all-day events listed first (or last — happy to
  take a preference), then timed events in order.
- Build a plain-language line, e.g.:
  `"Nothing on the calendar today."` /
  `"Sarah's birthday (all day). Also: meet Isla at the top of the road at 3:30."`
  This is intentionally *not* the final spoken phrasing — that's
  `voice_script.py`'s job, same as train/weather/politics data today.
  This function's output is closer to structured-but-readable, matching
  the style `trains.py`/`weather.py` already produce.

### Config: explicit allowlist, matching the existing `config.local.json` pattern

```json
{
  "calendar_allowlist": ["Home", "thomasandrewfaber@gmail.com"]
}
```

Added to `config.example.json` as a template key (empty array), and
`config.local.json` gets your actual picks once you've chosen from 1b.

### Wiring into `brief.py`

```python
@dataclass
class BriefData:
    train_line: str
    weather_line: str
    politics_line: str
    calendar_line: str          # new

def gather_brief_data() -> BriefData:
    ...
    calendar_line=summarize_calendar(config.get("calendar_allowlist", [])),

def format_text(data: BriefData) -> str:
    return (
        f"📅 {data.calendar_line}\n\n"
        f"🚆 {data.train_line}\n\n"
        f"🌤 {data.weather_line}\n\n"
        f"📰 {data.politics_line}"
    )
```

Calendar first, on the theory that "what's happening today" is the most
useful thing to read first — open to reordering.

### Wiring into `voice_script.py`

Add a `calendar_line` slot to `SCRIPT_PROMPT_TEMPLATE`, e.g.:

```
Calendar: {calendar_line}
```

alongside the existing `Train:`/`Weather:`/`Politics headlines:` lines.
No other prompt changes needed — the existing tone/length instructions
("weave naturally," "mention degraded data rather than skip it") already
cover how calendar data should be folded in.

**Decision flag for you**: adding a fourth data source to the same
~140-170 word budget means something has to give — either the target
word count needs to increase slightly (longer briefing) or the prompt
needs an explicit "if all four are present, keep each one brief" nudge.
I'd lean toward the second (keep runtime the same, prompt for brevity
per item) but this is a genuine trade-off, not a mechanical change.

### Failure mode

`summarize_calendar()` follows the exact same contract already
established by `weather.py`/`trains.py` (`except Exception: return f"..."`
rather than raising) — this already produces a *visible* failure message
by construction, not a silent one:

```python
except Exception as exc:
    log.error("Calendar read failed: %s", exc, exc_info=True)
    return f"Calendar unavailable right now ({exc})."
```

This means no new visibility mechanism is needed (unlike the voice
pipeline's fallback, which needed one added retroactively) — calendar
failure surfaces the same way weather/train failures already do, in both
the text brief and, once folded into the script prompt, the voice
briefing too. The brief as a whole still goes out regardless (each
fetcher is independent, per the existing contract) — a calendar failure
can't block trains/weather/politics, and vice versa.

## 3. Decision record

Decided: a new project-local `MorningBrief/DECISIONS.md`, not Bizkit's —
calendar reading is entirely local to this project, unlike the
`send_message.py`/`send_voice.py` primitives that justified using
Bizkit's log. The file now exists as `ADR-0001`; the entry (same text
as the draft below) is committed there. Earlier decisions (Piper vs.
ElevenLabs, direct SDK vs. `claude -p`, flat-file layout) stay as prose
in `VOICE_PROPOSAL.md` rather than being retroactively backfilled —
new decisions from this point on go in `DECISIONS.md`.

---

### ADR-0001 (in `MorningBrief/DECISIONS.md`): Local EventKit read for calendar awareness, not Google Calendar API

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
(see investigation section above). Since Calendar.app already syncs the
Google account locally, no separate Google API integration or cloud auth
is needed; this also automatically covers any future calendar source
added through Calendar.app itself, not just Google.

**Consequences:** TCC's Calendar grant is bound to the specific
interpreter binary's path (`~/.local/share/uv/python/cpython-3.13.14-.../python3.13`
as of this writing) — same caveat class as the existing
`onnxruntime`/Python-3.13 pin: changing the interpreter (e.g. a future
Python version bump) requires re-confirming the grant, not just
re-testing functionality. The read is strictly one-way and read-only —
no write access is requested or needed. `pyobjc-framework-EventKit` adds
a real dependency (pulls in `pyobjc-core` and Cocoa bindings), heavier
than this project's other dependencies, but has proper wheel coverage
for this platform (verified, see 1a) so doesn't reopen the onnxruntime
wheel-gap problem.

---

## 4. Scope estimate

- `calendar_events.py`: new module, ~60-80 lines including dedupe logic
  — similar size to `weather.py`.
- `brief.py`: add one field to `BriefData`, one line in
  `gather_brief_data()`, one line in `format_text()`. Small, mechanical.
- `voice_script.py`: one new template slot, no logic changes.
- `config.example.json`/`config.local.json`: one new key.
- `pyproject.toml`/`uv.lock`: one new dependency
  (`pyobjc-framework-EventKit`).
- No launchd/plist changes — calendar data flows through the existing
  text and voice pipelines, doesn't need its own schedule.
- Testing: a real day with at least one timed and one all-day event
  would be the most useful manual check before calling this done — happy
  to wait for one to occur naturally, or add a test event temporarily if
  you'd rather not wait.

Overall: small, contained addition — most of the real risk (the TCC
question) was exactly what section 1 exists to retire before any of this
gets built.
