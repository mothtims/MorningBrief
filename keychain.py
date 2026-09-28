"""
Shared Keychain lookup for every Keychain-backed secret in this project
(RTT refresh token, Anthropic API key, R2 credentials) - the same
shared-utility precedent as httputil.py's retry logic, previously
duplicated near-identically across trains.py/voice_script.py/
voice_storage.py.

Timeout is deliberately short (10s): a working lookup returns near-
instantly. A `security` call that hasn't returned by then almost always
means macOS is blocking on an interactive Keychain authorization prompt
with no one there to click it - exactly what hung a real scheduled run
for over 10 hours on 2026-09-24 (no timeout existed at the time; see
CHANGELOG.md). Failing fast here lets each caller's normal degradation
contract (a visible fallback note) run instead of a silent, unbounded
hang - the whole point of that contract is defeated if the lookup
feeding it can block forever.
"""

from __future__ import annotations

import subprocess

LOOKUP_TIMEOUT_SECONDS = 10


def load_secret(service_name: str) -> str:
    """Raises RuntimeError on any failure, including a timeout -
    callers already handle Exception generically for their own
    degradation contract, so this doesn't need a distinct exception
    type for the timeout case."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service_name, "-w"],
            capture_output=True,
            text=True,
            timeout=LOOKUP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Keychain lookup for '{service_name}' timed out after "
            f"{LOOKUP_TIMEOUT_SECONDS}s - likely blocked on an interactive "
            f"authorization prompt with no one to click it (e.g. under a "
            f"headless launchd run). Check for a pending Keychain prompt "
            f"and dismiss it, then re-run."
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read '{service_name}' from Keychain: {result.stderr.strip()}"
        )
    return result.stdout.strip()
