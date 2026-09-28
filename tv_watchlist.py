"""
TV watchlist: for each show in an allowlist (name + TVmaze show ID,
resolved once and stored in config - see TV_TECH_PROPOSAL.md section
1a), checks TVmaze's free no-key API for an episode airing today or in
the next ~48h.

Three-way contract, different from the other fetchers: nothing airing
in the window returns "" (empty string) so the caller omits the
section entirely - most days this is silent by design, and that
silence must cost nothing. Something airing returns a short line.
TVmaze being unreachable returns a visible degraded note, never "" and
never raises - same visibility principle as weather/trains/politics,
just not the *default* outcome the way it is for them.

Anime note: TVmaze tracks the original Japanese broadcast (network
field, e.g. MBS/NTV/AbemaTV/TV Tokyo/Fuji TV for the anime entries in
this watchlist), not any UK streaming platform's release. Window math
below uses `airstamp` (an absolute UTC instant), not the plain
`airdate` string (JST-relative) - late-night JST broadcast slots can
fall on what's still the previous calendar day in UK time, and airdate
alone would misclassify that.

Broadcaster-lag note (found 2026-09-29, Lanterns): the same class of
problem also hits Western shows whose UK availability lags their
tracked source-network schedule - TVmaze only tracks HBO's US Sunday
21:00 ET slot for Lanterns, which converts to ~02:00 BST Monday, hours
before most UK viewers actually watch it that evening. An optional
per-show "watch_offset_hours" in config shifts the *effective* airtime
used for both the window check and the displayed time, independent of
TVmaze's own (US-centric) data. Because TVmaze's nextepisode pointer
flips the moment the raw US airtime passes - which can happen well
before the shifted, user-relevant time - both nextepisode and
previousepisode are checked, not just nextepisode; otherwise a
still-pending (per the offset) episode would already have rolled off
into "previous" and never be seen. This also happens to fix a latent
gap for un-offset shows too: an episode that aired earlier *today*
would previously have been missed the same way once nextepisode
advanced past it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httputil import get_json
from logutil import get_logger

log = get_logger("tv_watchlist")

TVMAZE_BASE = "https://api.tvmaze.com"
WINDOW_HOURS = 48


def _candidate_episodes(show_id: int) -> list[dict]:
    data = get_json(f"{TVMAZE_BASE}/shows/{show_id}?embed[]=nextepisode&embed[]=previousepisode", log)
    embedded = data.get("_embedded", {})
    return [ep for ep in (embedded.get("nextepisode"), embedded.get("previousepisode")) if ep]


def _effective_airstamp(ep: dict, offset_hours: float) -> datetime | None:
    airstamp = ep.get("airstamp")
    if not airstamp:
        return None
    return datetime.fromisoformat(airstamp.replace("Z", "+00:00")) + timedelta(hours=offset_hours)


def _airs_in_window(ep: dict, offset_hours: float = 0, now: datetime | None = None) -> bool:
    air_dt = _effective_airstamp(ep, offset_hours)
    if air_dt is None:
        return False

    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone()
    start_of_today_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today_utc = start_of_today_local.astimezone(timezone.utc)
    window_end = now + timedelta(hours=WINDOW_HOURS)

    return start_of_today_utc <= air_dt <= window_end


def _relative_day_label(air_dt: datetime, now: datetime) -> str:
    """"Mon 21:00" is ambiguous to whoever reads it next - the
    voice-script prompt never tells the model today's actual weekday
    (only a vague morning/afternoon/evening bucket), so a bare weekday
    abbreviation left it to guess whether "Mon" meant today or some
    future Monday. It guessed wrong once ("later in the week" for a
    show airing within the hour) - computed here instead, since this
    code reliably knows the real current date and the model doesn't
    need to."""
    delta_days = (air_dt.astimezone().date() - now.astimezone().date()).days
    if delta_days <= 0:
        return "today"
    if delta_days == 1:
        return "tomorrow"
    return air_dt.astimezone().strftime("%A")


def _format_line(name: str, ep: dict, offset_hours: float = 0, now: datetime | None = None) -> str:
    bits = [name]

    season, number = ep.get("season"), ep.get("number")
    if season is not None and number is not None:
        bits.append(f"S{season}E{number}")

    ep_name = ep.get("name")
    if ep_name:
        bits.append(f'"{ep_name}"')

    label = " ".join(bits)

    air_dt = _effective_airstamp(ep, offset_hours)
    if air_dt is not None:
        now = now or datetime.now(timezone.utc)
        day_label = _relative_day_label(air_dt, now)
        time_str = air_dt.astimezone().strftime("%H:%M")
        return f"{label} airs {day_label} at {time_str}"
    return f"{label} airs soon"


def summarize_tv_watchlist(watchlist: list[dict]) -> str:
    if not watchlist:
        return ""

    upcoming = []
    errors = 0
    last_exc: Exception | None = None

    for show in watchlist:
        offset_hours = show.get("watch_offset_hours", 0)
        try:
            candidates = _candidate_episodes(show["tvmaze_id"])
        except Exception as exc:
            log.warning("TVmaze lookup failed for %r: %s", show["name"], exc)
            errors += 1
            last_exc = exc
            continue
        for ep in candidates:
            if _airs_in_window(ep, offset_hours=offset_hours):
                upcoming.append((show["name"], ep, offset_hours))
                break  # next/previous won't both match in practice; avoid a double mention if they somehow did

    if errors == len(watchlist):
        log.error("All %d TVmaze lookups failed: %s", errors, last_exc, exc_info=True)
        return f"TV watchlist unavailable right now ({last_exc})."

    if not upcoming:
        return ""

    log.info("%d show(s) airing in the next %dh out of %d watched", len(upcoming), WINDOW_HOURS, len(watchlist))
    return "; ".join(_format_line(name, ep, offset_hours) for name, ep, offset_hours in upcoming)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    config_path = Path(__file__).resolve().parent / "config.local.json"
    watchlist = json.loads(config_path.read_text()).get("tv_watchlist", [])
    result = summarize_tv_watchlist(watchlist)
    print(result or "(nothing airing in the window - silent by design)")
