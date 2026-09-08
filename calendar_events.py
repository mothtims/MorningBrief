"""
Calendar fetcher: reads today's events from an explicit allowlist of
macOS Calendar.app calendars via EventKit (pyobjc-framework-EventKit) -
local read only, no Google API integration. See DECISIONS.md ADR-0001
and CALENDAR_PROPOSAL.md for why local EventKit over icalBuddy or a
cloud API, and for the TCC/permissions investigation behind this.

TCC note: the first request from a given interpreter binary establishes
(or confirms) the Calendar access grant - this was verified to work
under a real headless launchd LaunchAgent using this project's actual
.venv interpreter, and to survive job re-registration. If this
project's Python version/interpreter path ever changes, the grant needs
re-confirming - same caveat class as the onnxruntime/Python 3.13 pin in
voice_tts.py.
"""

from __future__ import annotations

import time
from datetime import datetime

import EventKit
from Foundation import NSCalendar, NSCalendarUnitDay, NSDate, NSRunLoop, NSTimeZone

from logutil import get_logger

log = get_logger("calendar_events")

ACCESS_REQUEST_TIMEOUT_SECONDS = 30


def _request_access(store: EventKit.EKEventStore) -> bool:
    result = {"granted": None, "done": False}

    def _completion(granted, error):
        result["granted"] = granted
        result["done"] = True

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(_completion)
    else:
        store.requestAccessToEntityType_completion_(EventKit.EKEntityTypeEvent, _completion)

    run_loop = NSRunLoop.currentRunLoop()
    deadline = time.time() + ACCESS_REQUEST_TIMEOUT_SECONDS
    while not result["done"] and time.time() < deadline:
        run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

    return bool(result["granted"])


def _todays_events(store: EventKit.EKEventStore, allowed_calendar_names: list[str]) -> list:
    local_calendar = NSCalendar.currentCalendar()
    local_calendar.setTimeZone_(NSTimeZone.localTimeZone())

    now = NSDate.date()
    start_of_today = local_calendar.startOfDayForDate_(now)
    start_of_tomorrow = local_calendar.dateByAddingUnit_value_toDate_options_(
        NSCalendarUnitDay, 1, start_of_today, 0
    )

    all_calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    calendars = [c for c in all_calendars if c.title() in allowed_calendar_names]
    if not calendars:
        return []

    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_of_today, start_of_tomorrow, calendars
    )
    return list(store.eventsMatchingPredicate_(predicate))


def _dedupe(events: list) -> list:
    seen = set()
    deduped = []
    for ev in events:
        key = (ev.title(), ev.startDate(), ev.endDate())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)
    return deduped


def _format_events(events: list) -> str:
    if not events:
        return "Nothing on the calendar today."

    events = sorted(events, key=lambda ev: (not ev.isAllDay(), ev.startDate()))

    bits = []
    for ev in events:
        title = ev.title()
        if ev.isAllDay():
            bits.append(f"{title} (all day)")
        else:
            # NSDate is a UTC instant; converting via the Unix timestamp
            # and datetime.fromtimestamp() renders it in the system's
            # local timezone (DST-aware), matching what a human reading
            # their own calendar would expect to see.
            local_dt = datetime.fromtimestamp(ev.startDate().timeIntervalSince1970())
            bits.append(f"{title} at {local_dt.strftime('%H:%M')}")

    return " Also: ".join(bits) if len(bits) > 1 else bits[0]


def summarize_calendar(allowed_calendar_names: list[str]) -> str:
    """Returns a short natural-language summary of today's events from
    the allowlisted calendars - never raises, matching the same
    degradation contract as weather.py/trains.py."""
    if not allowed_calendar_names:
        return "No calendars configured."

    try:
        store = EventKit.EKEventStore.alloc().init()
        if not _request_access(store):
            return "Calendar access not granted."
        events = _dedupe(_todays_events(store, allowed_calendar_names))
    except Exception as exc:
        log.error("Calendar read failed: %s", exc, exc_info=True)
        return f"Calendar unavailable right now ({exc})."

    log.info("Found %d event(s) today across %d allowlisted calendar(s)", len(events), len(allowed_calendar_names))
    return _format_events(events)


if __name__ == "__main__":
    import sys

    names = sys.argv[1:] or ["Home", "thomasandrewfaber@gmail.com"]
    print(summarize_calendar(names))
