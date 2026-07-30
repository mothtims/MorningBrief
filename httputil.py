"""
Shared HTTP-GET-with-retry for the fetchers. Added 2026-07-30 after a
transient weather API 503 went straight to a degraded message with
nothing logged anywhere — see CHANGELOG.md. Retries transient failures
(5xx, network/timeout errors); raises immediately on 4xx, since
retrying a bad request won't change the outcome.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from logging import Logger

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0


def get_bytes(
    url: str,
    log: Logger,
    headers: dict | None = None,
    timeout: int = 15,
) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code < 500:
                log.error("Non-retryable HTTP %s from %s: %s", exc.code, url, exc)
                raise
            log.warning(
                "HTTP %s from %s (attempt %s/%s)", exc.code, url, attempt, RETRY_ATTEMPTS
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            log.warning(
                "Network error from %s (attempt %s/%s): %s", url, attempt, RETRY_ATTEMPTS, exc
            )
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    log.error("Giving up on %s after %s attempts: %s", url, RETRY_ATTEMPTS, last_exc)
    raise last_exc


def get_json(
    url: str,
    log: Logger,
    headers: dict | None = None,
    timeout: int = 15,
) -> dict:
    return json.loads(get_bytes(url, log, headers=headers, timeout=timeout).decode("utf-8"))
