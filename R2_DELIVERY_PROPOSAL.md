# Voice Brief → Cloudflare R2 Delivery: Design Proposal

Investigation-first, per instructions. No implementation yet — this
whole document is for review.

## 1. Investigation findings

### 1a. iOS Shortcuts audio format — verified, not assumed

`"Get Contents of URL"` → `"Play Sound"`/`"Play Audio"` in Shortcuts
supports most common formats including both **m4a and mp3** — confirmed
via Apple Support docs and Automators community threads, not guessed.
No format-compatibility reason to prefer one over the other.

Good news: `voice_audio_convert.py` already has `wav_to_mp3()`
(96kbps), written during the voice-edition build for exactly this v2
step and unused until now. No new conversion code needed — just wire
the existing function in.

One unrelated reliability note surfaced during research, not a format
issue: some users report Shortcuts' blocking-until-playback-finishes
behavior can trip Siri's "this is taking a while" intervention on long
audio, particularly on HomePod. Not something the delivery pipeline
can fix — flagging since you're building the Shortcut yourself and
might hit it.

### 1b. Custom headers in Shortcuts — verified, not assumed

`"Get Contents of URL"`'s advanced parameters (`Show More`) include a
`Headers` section with a `+ Add new header` option for static
key/value headers. Confirmed via Apple's own Shortcuts guide. This is
what makes the header-based access mechanism (section 2) viable.

### 1c. R2 API token permissions — verified against Cloudflare's docs directly

Fetched `developers.cloudflare.com/r2/api/tokens/` directly rather than
trusting a summary. Four tiers exist: **Admin Read & Write**, **Admin
Read only**, **Object Read & Write**, **Object Read only**. **There is
no write-only tier** — the finest-grained option that includes write
access is "Object Read & Write," scoped to one or more specific
buckets. Your instruction was "write-only if R2's token model allows
it" — it doesn't, so the honest minimum is **Object Read & Write,
scoped to exactly one bucket** (not "all buckets," not Admin).

The token issuance also only shows the Secret Access Key once — the
setup steps in section 4 account for that.

### 1d. R2's S3-compatible API mechanics — verified against Cloudflare's docs and a working reference implementation

- Region is literally the string `"auto"` for all R2 S3-API requests —
  not a real AWS region, confirmed directly in Cloudflare's docs.
- Endpoint: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, path-style
  bucket addressing (`/<bucket>/<key>`) works.
- Standard AWS SigV4 signing applies (canonical request → string-to-sign
  → HMAC signing-key chain → `Authorization` header). Verified the exact
  mechanics against a detailed third-party writeup of signing R2
  requests by hand, cross-checked against Cloudflare's own token docs.
  `UNSIGNED-PAYLOAD` is only valid for presigned URLs, not header-based
  auth — a PUT needs the actual SHA-256 of the body in
  `x-amz-content-sha256`, meaning the file gets hashed once in memory
  (trivial at this file size, ~1MB).

**Recommendation: hand-rolled SigV4 via stdlib (`hashlib`/`hmac`/
`urllib.request`), not `boto3`.** This matches the project's existing
pattern exactly — `send_voice.py` (Bizkit) hand-rolls multipart/form-data
encoding via stdlib rather than pulling in `requests`, for the same
reason: one well-defined HTTP operation doesn't justify a heavy
dependency. `boto3`+`botocore` would pull in a meaningfully large
dependency chain (`botocore`, `s3transfer`, `jmespath`, a pinned
`urllib3`/`python-dateutil` range) for a single PUT call run twice a
day. SigV4 for one operation is well-documented, bounded, and testable
— consistent with how this project has handled every other integration
so far.

### 1e. Cloudflare Workers R2 binding API — verified against Cloudflare's reference docs

For the Worker side (section 2): `bucket.get(key)` returns an
`R2ObjectBody` with an `.uploaded` property — a native JS `Date` of
when the object was actually uploaded — and a `.writeHttpMetadata(headers)`
method that populates standard HTTP headers (including Content-Type)
from the object's stored metadata. This directly supports "freshness =
object's Last-Modified": the Worker sets
`headers.set('Last-Modified', object.uploaded.toUTCString())`, so
whatever check your Shortcut does against Last-Modified reflects the
real R2 upload time, not some Worker-side approximation.

## 2. Access mechanism — recommendation

Evaluated against your stated constraints (Shortcuts can only send a
fixed URL and/or one fixed static header, no dynamic auth; content is
personal — schedule and movements; URLs leak into logs in ways headers
generally don't):

- **Unguessable path on a public bucket** — rejected. The entire
  security model is "nobody finds this URL," with no revocation short
  of changing the URL (which breaks "stable").
- **Presigned URLs** — rejected. They expire by design (practically
  capped around 7 days with static credentials) — directly conflicts
  with a Shortcut that saves one URL indefinitely.
- **Cloudflare Worker in front of a private R2 bucket, gating on a
  static token passed as a custom HTTP header — recommended.** The
  bucket is never public. The Worker checks a long random token in a
  header (not a query parameter) against a secret in its own
  environment, constant-time compared, and proxies the object through
  on match.

**Header over query parameter, specifically because you flagged it**:
URLs get logged at nearly every HTTP hop by default — CDN/edge access
logs, any intermediate proxy, browser history if ever opened in Safari
to test — while headers generally aren't captured to the same degree.
For content this personal, that asymmetry is worth the one extra field
in the Shortcut's header list. (The original v1 voice proposal had
mentioned either as viable without a strong preference; this revises
that to a firm header recommendation given the constraint you've now
made explicit.)

Draft ADR for `DECISIONS.md` (mirrors ADR-0001/ADR-0002's format):

---

### ADR-0003: R2 delivery — Worker-gated static header token, not an unguessable URL or presigned URLs

**Context:** v2 needs the voice brief reachable by an iOS Shortcut's
`"Get Contents of URL"` action — a consumer limited to a fixed,
pre-saved URL and optionally one fixed custom header, with no dynamic
auth support (no OAuth, no per-request signing). The file carries
personal schedule/movement information, so access control matters.
Three approaches were evaluated: an unguessable path on a public
bucket, presigned URLs, and a Cloudflare Worker gating a private
bucket on a static token.

**Decision:** A Cloudflare Worker in front of a private R2 bucket,
checking a long random static token passed as a custom HTTP header
(`X-Brief-Token`), constant-time-compared against a Worker environment
secret, proxying the R2 object through on match. Header chosen over
query parameter because URLs are logged by default at nearly every
HTTP hop (edge/CDN logs, intermediate proxies, browser history) while
headers generally aren't — meaningful for content this personal. An
unguessable-path public bucket was rejected because its entire security
model is "nobody finds this URL," with no revocation short of changing
the URL (breaking "stable"). Presigned URLs were rejected because they
expire by design (~7 days with static credentials), conflicting with a
Shortcut that saves one URL indefinitely.

**Consequences:** This is new external infrastructure beyond this
machine — a Cloudflare account, an R2 bucket, a deployed Worker.
**Two independent secrets exist and must not be confused**: the R2 API
token (Object Read & Write, scoped to one bucket — R2's token model has
no true write-only tier) authenticates the Python pipeline's *push* to
R2, stored in Keychain like every other credential in this project
(`morningbrief-r2-access-key-id`/`morningbrief-r2-secret-access-key`).
The Worker's gating token authenticates the phone's *read* from the
Worker — it lives only in the Worker's own environment and is embedded
in the saved Shortcut; it never touches this codebase, Keychain, or any
config file. Rotating the gating token later is a one-line Worker
secret update plus re-saving the Shortcut, touching neither R2 nor the
Python pipeline.

---

## 3. Pipeline change

### New module: `voice_storage.py` (flat layout)

```python
def push_latest_brief(mp3_path: Path, account_id: str, bucket: str) -> None:
    """Raises on failure - caller wraps this in its own try/except.
    An R2 push failure must never block or delay Telegram delivery,
    which has already happened by the time this runs."""
```

Sketch of the SigV4 mechanics (verified against section 1d/1e above):

```python
def push_latest_brief(mp3_path: Path, account_id: str, bucket: str) -> None:
    access_key = _load_keychain_secret(R2_ACCESS_KEY_ID_SERVICE)
    secret_key = _load_keychain_secret(R2_SECRET_ACCESS_KEY_SERVICE)

    payload = mp3_path.read_bytes()
    payload_hash = hashlib.sha256(payload).hexdigest()
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    host = f"{account_id}.r2.cloudflarestorage.com"
    canonical_uri = f"/{bucket}/{OBJECT_KEY}"   # OBJECT_KEY = "latest.mp3"

    # ... canonical request -> string-to-sign -> signing-key chain ->
    # Authorization header (standard SigV4, region="auto") ...

    req = urllib.request.Request(
        f"https://{host}{canonical_uri}", data=payload, method="PUT",
        headers={"Content-Type": "audio/mpeg", "x-amz-content-sha256": payload_hash,
                 "x-amz-date": amz_date, "Authorization": authorization},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"R2 PUT returned unexpected status {resp.status}")
```

Stable key: `latest.mp3`, overwritten every run — no timestamped keys,
per your "stable path" requirement. `R2_ACCOUNT_ID`/`R2_BUCKET` aren't
secret (account ID and bucket name), so they go in `config.local.json`
alongside the other non-secret settings; only the access key ID and
secret access key go in Keychain.

### `scheduled_send_voice.py` integration

Added strictly *after* the existing Telegram voice send succeeds —
never before, never blocking it:

```python
# existing flow unchanged through send_voice_note(ogg_path)...

mp3_path = tmp_dir / "brief.mp3"
try:
    wav_to_mp3(wav_path, mp3_path)
    push_latest_brief(mp3_path, config["r2_account_id"], config["r2_bucket"])
except Exception as exc:
    log.error("R2 push failed: %s", exc, exc_info=True)
    try:
        send_text_note(f"R2 upload failed today ({exc}) - voice/text still delivered normally via Telegram.")
    except Exception:
        pass   # a broken notification must never break an otherwise-successful run
```

**Flagging one mechanical difference from the existing fallback
pattern, since you asked about failure modes explicitly**: the
TTS/conversion/upload failures already in this file *prepend* a note
onto the text-brief fallback *before* sending it (there's no separate
message, because the whole point is "text arrives instead of voice").
R2 failure is different — by the time it's discovered, Telegram
delivery (voice or text) has *already succeeded*. So the visibility
note here has to be a small **separate, supplementary** Telegram
message, not something woven into a message that's already gone out.
Functionally the same principle (a real, visible note — never just a
log line), just a different delivery shape because of where in the
pipeline this failure happens. `send_text_note()` would be a thin new
helper alongside the existing `send_text_fallback()`, reusing
`SEND_MESSAGE_SCRIPT`.

## 4. Credentials and setup — exact steps

You create these; here's precisely what and how minimal:

**R2 bucket + API token** (Cloudflare dashboard → R2):
1. Create a bucket — e.g. name it `morningbrief-brief`.
2. R2 → *Manage API Tokens* → *Create API Token*.
3. Permission: **"Object Read & Write"** (the minimum tier that
   includes write — see 1c, no write-only tier exists).
4. Scope: restrict to the **specific bucket** you just created — not
   "Apply to all buckets," not an Admin tier.
5. Create it. Cloudflare shows the **Access Key ID** and **Secret
   Access Key** exactly once — copy both immediately.
6. Store both in Keychain, matching this project's existing pattern
   (same as `realtimetrains-api-token`):
   ```
   security add-generic-password -s morningbrief-r2-access-key-id -a morningbrief -w '<paste access key id>'
   security add-generic-password -s morningbrief-r2-secret-access-key -a morningbrief -w '<paste secret access key>'
   ```
7. Tell me your Cloudflare **account ID** and the **bucket name** —
   neither is secret, both go straight into `config.local.json`.

**The Worker** (Cloudflare dashboard → Workers & Pages):
1. Create a new Worker, paste in the script I'll write once you've
   confirmed this proposal (checks the `X-Brief-Token` header against
   an environment secret, reads `latest.mp3` from a bound R2 bucket,
   returns it with `Last-Modified` set from `object.uploaded`).
2. Bind the R2 bucket you created above to the Worker (dashboard →
   Worker → Settings → Bindings → R2 Bucket).
3. Set a Worker secret (dashboard → Worker → Settings → Variables) —
   generate a long random token yourself (e.g. `openssl rand -hex 32`
   in Terminal) and store it as a secret named `BRIEF_ACCESS_TOKEN`.
   **This token never comes to me or into this codebase** — you
   generate it, set it in the Worker, and use the same value directly
   in your Shortcut's header field.
4. Use the free `*.workers.dev` subdomain Cloudflare assigns
   automatically — no custom domain needed unless you want a prettier
   URL later; keeping this minimal per your "not in scope" note on the
   Shortcut itself.
5. Give me the resulting `*.workers.dev` URL once deployed, so I can
   do the end-to-end verification in section 5 (I only need the URL —
   never the token value itself, since I can't reach your phone or
   Cloudflare account to test with it anyway; you'll do the actual
   phone-side header setup yourself when you build the Shortcut).

## 5. Verification plan

Before this counts as done:
1. A real scheduled-style trigger (`uv run python3
   scheduled_send_voice.py`, same as every other verification in this
   project) — confirm the MP3 lands in R2 (checked via a signed `HEAD`
   request from this machine, same credentials as the push).
2. Confirm the Worker serves it correctly with a valid token and
   correctly rejects a missing/wrong token (`curl` from this machine —
   verifies the Worker logic without needing your phone).
3. Real phone fetch over cellular — you do this once I give you the
   Worker URL and confirm the header value format; not something I can
   do myself.
4. `CHANGELOG.md` entry, `CONTEXT.md` current-state update, and
   `DECISIONS.md` ADR-0003 (drafted above) committed.

## 6. Scope estimate

- `voice_storage.py`: new module, ~80-100 lines (SigV4 signing is the
  bulk of it; no new dependency).
- `cloudflare/brief-worker.js`: new file (not Python, doesn't run on
  this machine) — the Worker script, ~30-40 lines, for you to paste
  into the Cloudflare dashboard.
- `scheduled_send_voice.py`: one new post-success step, wrapped in its
  own try/except; one small new `send_text_note()` helper.
- `voice_audio_convert.py`: no changes — `wav_to_mp3()` already exists.
- `config.example.json`/`config.local.json`: `r2_account_id`,
  `r2_bucket` keys (not secret).
- `pyproject.toml`/`uv.lock`: **no new dependencies** — stdlib only.
- `DECISIONS.md`: ADR-0003 (drafted above).
- No launchd/schedule changes — rides the existing voice job.

Not in scope, per your note: the iOS Shortcut itself, podcast RSS, any
change to the Telegram path.

## 7. Open items for your sign-off

- Confirm the access-mechanism recommendation (Worker + private bucket
  + header token) and the header-over-query-param reasoning.
- Confirm "Object Read & Write scoped to one bucket" as the accepted
  minimum, given no write-only tier exists.
- Confirm the separate-supplementary-message shape for R2-push-failure
  visibility (section 3), since it's mechanically different from the
  existing inline-fallback-note pattern.
- Once confirmed: I'll write `voice_storage.py` and the Worker script
  for your review, then you create the Cloudflare account/bucket/token/
  Worker per section 4 and hand me the account ID, bucket name, and
  Worker URL to run the verification in section 5.
