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
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httputil import get_json
from logutil import get_logger

log = get_logger("tv_watchlist")

TVMAZE_BASE = "https://api.tvmaze.com"
WINDOW_HOURS = 48


def _next_episode(show_id: int) -> dict | None:
    data = get_json(f"{TVMAZE_BASE}/shows/{show_id}?embed=nextepisode", log)
    return data.get("_embedded", {}).get("nextepisode")


def _airs_in_window(ep: dict, now: datetime | None = None) -> bool:
    airstamp = ep.get("airstamp")
    if not airstamp:
        return False

    air_dt = datetime.fromisoformat(airstamp.replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone()
    start_of_today_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today_utc = start_of_today_local.astimezone(timezone.utc)
    window_end = now + timedelta(hours=WINDOW_HOURS)

    return start_of_today_utc <= air_dt <= window_end


def _format_line(name: str, ep: dict) -> str:
    bits = [name]

    season, number = ep.get("season"), ep.get("number")
    if season is not None and number is not None:
        bits.append(f"S{season}E{number}")

    ep_name = ep.get("name")
    if ep_name:
        bits.append(f'"{ep_name}"')

    label = " ".join(bits)

    airstamp = ep.get("airstamp")
    if airstamp:
        air_dt = datetime.fromisoformat(airstamp.replace("Z", "+00:00")).astimezone()
        return f"{label} airs {air_dt.strftime('%a %H:%M')}"
    return f"{label} airs soon"


def summarize_tv_watchlist(watchlist: list[dict]) -> str:
    if not watchlist:
        return ""

    upcoming = []
    errors = 0
    last_exc: Exception | None = None

    for show in watchlist:
        try:
            ep = _next_episode(show["tvmaze_id"])
        except Exception as exc:
            log.warning("TVmaze lookup failed for %r: %s", show["name"], exc)
            errors += 1
            last_exc = exc
            continue
        if ep and _airs_in_window(ep):
            upcoming.append((show["name"], ep))

    if errors == len(watchlist):
        log.error("All %d TVmaze lookups failed: %s", errors, last_exc, exc_info=True)
        return f"TV watchlist unavailable right now ({last_exc})."

    if not upcoming:
        return ""

    log.info("%d show(s) airing in the next %dh out of %d watched", len(upcoming), WINDOW_HOURS, len(watchlist))
    return "; ".join(_format_line(name, ep) for name, ep in upcoming)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    config_path = Path(__file__).resolve().parent / "config.local.json"
    watchlist = json.loads(config_path.read_text()).get("tv_watchlist", [])
    result = summarize_tv_watchlist(watchlist)
    print(result or "(nothing airing in the window - silent by design)")
