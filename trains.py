"""
Realtime Trains fetcher.

Auth is a two-step exchange (see README.md / CHANGELOG.md for how this
was verified against the real API): a long-lived refresh token (in
Keychain) is exchanged for a short-lived access token, which is cached
to state/rtt_access_token.json until its validUntil expiry so we don't
re-exchange on every request against the 30/min rate limit.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / "state"
ACCESS_TOKEN_CACHE = STATE_DIR / "rtt_access_token.json"
KEYCHAIN_SERVICE_NAME = "realtimetrains-api-token"
BASE_URL = "https://data.rtt.io"


def _load_refresh_token() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE_NAME, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read Realtime Trains token from Keychain "
            f"(service '{KEYCHAIN_SERVICE_NAME}'): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _http_get_json(url: str, bearer_token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer_token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_access_token() -> str:
    if ACCESS_TOKEN_CACHE.exists():
        cached = json.loads(ACCESS_TOKEN_CACHE.read_text())
        valid_until = datetime.fromisoformat(cached["validUntil"])
        if valid_until > datetime.now(timezone.utc):
            return cached["token"]

    refresh_token = _load_refresh_token()
    data = _http_get_json(f"{BASE_URL}/api/get_access_token", refresh_token)

    STATE_DIR.mkdir(exist_ok=True)
    ACCESS_TOKEN_CACHE.write_text(json.dumps(data))
    return data["token"]


def get_departures(from_crs: str, to_crs: str, time_from_iso: str, window_minutes: int = 60) -> list[dict]:
    access_token = get_access_token()
    query = urllib.parse.urlencode(
        {
            "code": from_crs,
            "filterTo": to_crs,
            "timeFrom": time_from_iso,
            "timeWindow": window_minutes,
        }
    )
    data = _http_get_json(f"{BASE_URL}/gb-nr/location?{query}", access_token)
    return data.get("services", [])


def summarize_leg(from_crs: str, to_crs: str, departs_hhmm: str) -> str:
    """Fetch the service closest to `departs_hhmm` today and describe it in plain text."""
    today = datetime.now().strftime("%Y-%m-%d")
    hour, minute = departs_hhmm.split(":")
    time_from = f"{today}T{int(hour)-1:02d}:{minute}:00+01:00"

    try:
        services = get_departures(from_crs, to_crs, time_from, window_minutes=120)
    except Exception as exc:
        return f"Train status unavailable right now ({exc})."

    if not services:
        return f"No scheduled {from_crs}→{to_crs} service found near {departs_hhmm}."

    # Pick the service whose scheduled departure is closest to the target time.
    target = datetime.strptime(f"{today} {departs_hhmm}", "%Y-%m-%d %H:%M")

    def _closeness(service: dict) -> float:
        sched = service["temporalData"]["departure"]["scheduleAdvertised"]
        sched_dt = datetime.fromisoformat(sched).replace(tzinfo=None)
        return abs((sched_dt - target).total_seconds())

    service = min(services, key=_closeness)
    departure = service["temporalData"]["departure"]
    operator = service["scheduleMetadata"]["operator"]["name"]
    scheduled = departure["scheduleAdvertised"][11:16]

    if departure.get("isCancelled"):
        return f"{operator} {scheduled} {from_crs}→{to_crs}: CANCELLED."

    lateness = departure.get("realtimeAdvertisedLateness", 0) or 0
    platform = service.get("locationMetadata", {}).get("platform", {})
    platform_str = platform.get("actual") or platform.get("planned")
    platform_text = f"platform {platform_str}" if platform_str else "platform not yet announced"

    if lateness == 0:
        status = "on time"
    else:
        status = f"running {lateness} min late"

    return f"{operator} {scheduled} {from_crs}→{to_crs}: {status}, {platform_text}."


if __name__ == "__main__":
    import sys

    from_crs, to_crs, departs = sys.argv[1], sys.argv[2], sys.argv[3]
    print(summarize_leg(from_crs, to_crs, departs))
