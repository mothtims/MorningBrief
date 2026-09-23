"""
Pushes the voice brief's MP3 to Cloudflare R2 at a stable "latest.mp3"
key, overwritten every run, via R2's S3-compatible API. Uses a
hand-rolled AWS SigV4 signer (hashlib/hmac/urllib only) rather than
boto3 - same reasoning as Bizkit's send_voice.py hand-rolling
multipart/form-data instead of pulling in `requests`: one well-defined
HTTP operation doesn't justify a heavy dependency. See
R2_DELIVERY_PROPOSAL.md section 1d for the verified SigV4/R2 mechanics
(region is literally "auto", not a real AWS region) and DECISIONS.md
ADR-0003 for the access-mechanism design this is one half of - this
module only handles the *push*; the *read* side (Cloudflare Worker +
header token) is a completely separate secret that never touches this
codebase.
"""

from __future__ import annotations

import hashlib
import hmac
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from logutil import get_logger

log = get_logger("voice.storage")

R2_ACCESS_KEY_ID_SERVICE = "morningbrief-r2-access-key-id"
R2_SECRET_ACCESS_KEY_SERVICE = "morningbrief-r2-secret-access-key"
OBJECT_KEY = "latest.mp3"
REGION = "auto"
SERVICE = "s3"


def _load_keychain_secret(service_name: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service_name, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read {service_name} from Keychain: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def _build_authorization_header(
    access_key: str,
    secret_key: str,
    host: str,
    canonical_uri: str,
    payload_hash: str,
    amz_date: str,
    date_stamp: str,
) -> str:
    canonical_headers = (
        f"content-type:audio/mpeg\n"
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        ["PUT", canonical_uri, "", canonical_headers, signed_headers, payload_hash]
    )

    credential_scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    signing_key = _signing_key(secret_key, date_stamp, REGION, SERVICE)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def push_latest_brief(mp3_path: Path, account_id: str, bucket: str) -> None:
    """Raises on failure - caller wraps this in its own try/except.
    An R2 push failure must never block or delay Telegram delivery,
    which has already happened by the time this runs (see
    scheduled_send_voice.py - this is a post-success, best-effort
    mirror, not part of the delivery-critical path)."""
    access_key = _load_keychain_secret(R2_ACCESS_KEY_ID_SERVICE)
    secret_key = _load_keychain_secret(R2_SECRET_ACCESS_KEY_SERVICE)

    payload = mp3_path.read_bytes()
    payload_hash = hashlib.sha256(payload).hexdigest()

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host = f"{account_id}.r2.cloudflarestorage.com"
    canonical_uri = f"/{bucket}/{OBJECT_KEY}"

    authorization = _build_authorization_header(
        access_key, secret_key, host, canonical_uri, payload_hash, amz_date, date_stamp
    )

    req = urllib.request.Request(
        f"https://{host}{canonical_uri}",
        data=payload,
        method="PUT",
        headers={
            "Content-Type": "audio/mpeg",
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            "Authorization": authorization,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"R2 PUT returned unexpected status {resp.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"R2 PUT failed: HTTP {exc.code} {exc.reason} - {exc.read()[:500]}") from exc

    log.info("Pushed %s (%d bytes) to R2 bucket %s as %s", mp3_path.name, len(payload), bucket, OBJECT_KEY)


if __name__ == "__main__":
    import json
    import sys

    config_path = Path(__file__).resolve().parent / "config.local.json"
    config = json.loads(config_path.read_text())

    mp3_arg = Path(sys.argv[1])
    push_latest_brief(mp3_arg, config["r2_account_id"], config["r2_bucket"])
    print(f"Pushed {mp3_arg} to R2")
