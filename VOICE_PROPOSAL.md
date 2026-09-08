# Morning Brief — "Jarvis" Voice Edition: Design Proposal

Status: **design approved for v1** (§8) — Anthropic SDK, `claude-opus-4-8`,
voice alongside the existing text brief. Nothing has been implemented or
committed yet; this document is the reference for building it. §9 covers
what's still open for v2, which doesn't block starting v1.

## 1. Pipeline — validated, with one change proposed

Your four-step pipeline is sound. One addition: a **degradation contract**
that applies across the whole pipeline, not just within each step (see
§4) — this is what makes "alongside the existing text brief" actually safe
to build without risking the one thing that already works reliably.

1. **Data gathering** — unchanged. `trains.py`, `weather.py`, `politics.py`
   keep fetching and degrading exactly as they do today.
2. **Scripting** — send the gathered data to the Claude API with a
   scripting prompt, producing a ~60–90s spoken-word script. Confirmed
   below as a direct Anthropic API call, not a re-use of the `claude -p`
   CLI pattern `politics.py` already uses — see §7, open question 1.
3. **TTS** — Piper first, ElevenLabs as a paid fallback if quality
   disappoints. Confirmed viable (see §2). Piper outputs WAV; a **new
   step not in your original list** is required: converting WAV to both
   OGG/Opus (Telegram) and MP3 (storage) via `ffmpeg`, which isn't
   installed on this machine yet (see §2).
4. **Delivery** — phased as you described. v1 is Telegram-only and needs
   no new cloud infrastructure. v2 needs a Cloudflare account with R2 and
   Workers (see §5) — flagging this now because it's a materially bigger
   step than anything this project has needed so far (a new external
   provider, not just an API key).

## 2. New dependencies

**uv-managed (Python, this project):**
- `piper-tts` — the TTS engine itself. Actively maintained (v1.8.0,
  Sept 2026), by the Open Home Foundation (the original `rhasspy/piper`
  repo is archived). **License note:** now GPL-3.0 (was MIT under the old
  repo) — worth knowing since Bizkit's own code is unlicensed/private, but
  not a blocker for personal, non-distributed use like this.
- `anthropic` — the official SDK, for the scripting step (see open
  question 1).
- `boto3` (v2 only) — R2 is S3-compatible; `boto3` is the standard way to
  push objects to it.

**System-level, not uv-managed (needs your approval, like the Node
install earlier):**
- `ffmpeg`, via Homebrew. Needed for WAV → OGG/Opus and WAV → MP3
  conversion — there's no clean pure-Python path that avoids it. This
  machine doesn't have it yet (checked before writing this).

**Not needed:** ElevenLabs adds no new *dependency* — it's just another
HTTPS call with a Keychain-stored key, following the exact pattern
`trains.py` already uses. Only pull it in if Piper's quality genuinely
disappoints on a real listen — per Bizkit's own "no speculative tooling"
principle, I'd build and evaluate Piper first rather than wiring up both
from day one.

**Worth flagging on hardware:** this machine is an older Intel Mac
(i7-4770HQ). Piper was explicitly designed to run in real time on a
Raspberry Pi, so CPU speed shouldn't be a real constraint — but "shouldn't
be a problem" is a claim to verify by actually running it, not something
to assume going in.

## 3. Scripting step — what the prompt needs to produce

Feed the scripting prompt **structured data**, not the emoji-formatted
text string `brief.py` currently builds for Telegram — see §6 for why
that means a small refactor. A rough prompt shape:

> You're writing a ~60–90 second spoken morning briefing script for one
> person, to be read aloud by a TTS voice. Given this data — train status,
> weather, and headline summaries — write natural, conversational
> spoken-word prose. Not a list, not a data dump: transitions between
> topics the way a person would talk. If a data point is unavailable, say
> so naturally rather than skipping it silently. Output only the script
> text, nothing else.

This call needs **no tool access** — same reasoning already established
for `politics.py`'s summarization call: the input is data your own
fetchers produced, but treating the synthesis step as tool-free is cheap
insurance and keeps the security posture consistent across the project.

## 4. Failure modes and the degradation contract

This is the part worth being most disciplined about, because "never
silently not arrive" is a correctness requirement, not a nice-to-have.

**Layered fallback**, not one big try/except:

| Failure point | Fallback |
|---|---|
| Script generation fails (Claude API error/timeout) | Skip straight to sending the existing **text** brief via Telegram — the proven path, untouched by any of this |
| TTS fails (Piper error, or model missing) | Same — fall back to text |
| Audio conversion fails (`ffmpeg` error) | Same — fall back to text |
| Telegram voice upload fails, but audio was generated fine | Fall back to sending the **text** brief instead, so you still get *something* that morning |
| R2 push fails (v2), but Telegram voice succeeded | **Not** a full fallback — you already have your voice note. Log it, skip the storage step, move on. The Shortcuts flow just won't see today's update; next scheduled run tries again |

The general shape: anything upstream of "you got a message" falls back to
the last-known-good delivery mechanism (text via `send_message.py`).
Anything downstream of that (R2, podcast feed) fails independently and
noisily in the log, without taking down what already worked. This mirrors
the same principle already in `httputil.py`/`logutil.py` — retry, log,
degrade gracefully, never fail silently — just applied one layer higher.

## 5. Storage access — recommendation

Your three options, evaluated against the actual constraint (personal
data, a Shortcuts consumer that can do a plain GET or a GET with one
fixed header, no OAuth):

- **Unguessable path on a public bucket** — simplest, but the *entire*
  security model is "nobody finds this URL." No revocation without
  changing the URL (which breaks "stable"), and R2's public-bucket
  tooling (r2.dev subdomains, custom domains) has had real
  misconfiguration foot-guns reported. Weakest option for content that
  includes your schedule and movements.
- **Presigned URLs** — the standard S3-style answer, but they **expire by
  design** (practically capped around 7 days with static credentials).
  That directly conflicts with "stable, predictable URL" — a Shortcut
  can't just re-fetch the same saved URL indefinitely, and solving that
  means either a manifest-refresh dance (adds a second request and a
  second thing to keep working) or manual re-signing, which isn't
  "predictable" for you either.
- **Cloudflare Worker in front of a private R2 bucket, gating on a
  static token** — **recommended.** The bucket itself is never public.
  The Worker exposes one stable path (e.g. `latest.mp3`), checks a long
  random token passed as a query parameter against a secret stored in
  the Worker's own environment (constant-time comparison), and proxies
  the object through if it matches. This is a well-documented pattern
  specifically because it decouples "the URL never changes" from "the
  bucket stays private."

  For your Shortcut: one saved URL, e.g.
  `https://brief.yourdomain.example/latest.mp3?key=<64-char-random>`,
  fetched with a single "Get Contents of URL" action — no custom headers
  needed, though Shortcuts supports those too if you'd rather move the
  token to a header. Rotating the token later (e.g. after a suspected
  leak) is a one-line Worker secret update plus re-saving the Shortcut —
  it doesn't touch R2 or the rest of the pipeline.

  **Honest tradeoff:** this is real new infrastructure — a Cloudflare
  account, an R2 bucket, a deployed Worker, ideally a custom domain
  routed through it. Nothing else in this project has needed an external
  cloud provider before; everything's lived on your Mac plus free data
  APIs. Worth confirming you're up for that step before v2 starts (v1
  needs none of this).

## 6. Structural changes to MorningBrief

To keep text and voice cleanly separated without duplicating the fetch
logic, split `brief.py`'s current single `build_brief() -> str` into a
data layer and a presentation layer:

```python
# brief.py (refactored)
def gather_brief_data() -> BriefData:      # trains + weather + politics -> structured data
def format_text(data: BriefData) -> str:   # existing emoji-joined format — unchanged output
def build_brief() -> str:                  # gather + format_text — same signature as today, nothing breaks
```

New voice-specific package, kept separate from the existing flat-file
layout so a voice-pipeline bug can never touch the text path by accident:

```
voice/
  script.py          — BriefData -> spoken script (Anthropic API call, no tools)
  tts.py              — script text -> WAV (Piper)
  audio_convert.py    — WAV -> OGG/Opus (Telegram) and WAV -> MP3 (storage), via ffmpeg
  storage.py          — v2: push MP3 to R2 at the stable key (boto3)
  rss.py               — v2, optional: maintain a podcast feed.xml alongside the R2 object
scheduled_send_voice.py  — new entry point implementing the degradation contract in §4
```

**Bizkit-side addition** (small, mirrors the existing pattern exactly):
`services/telegram-bridge/send_voice.py`, a sibling to the already-shipped
`send_message.py` — same Keychain token, same `allowed_user_id`-as-chat-id
approach, but a multipart POST to Telegram's `sendVoice` instead of JSON
to `sendMessage`. This is the same "standalone, minimal primitive" shape
as `send_message.py` (Bizkit `DECISIONS.md` ADR-0012) — not a new
mechanism, just a new capability alongside it.

**Scheduling:** a new, separate `launchd` job
(`com.morningbrief.voice.scheduled.plist`), firing weekday mornings only
— distinct from the existing twice-daily text job so a voice-pipeline
failure can never affect the text schedule's reliability. **Decided:
alongside, not instead of** — the existing morning text run stays exactly
as it is while the voice edition is being built and tuned. A config flag
(`voice_mode: "alongside" | "voice_only"`) is worth adding so this can be
switched later without a code change, once the voice pipeline is trusted.

**New secrets** (Keychain, same pattern as everything else in this
project — `realtimetrains-api-token`, etc.):
- `morningbrief-anthropic-api-key` — for the scripting step
- `morningbrief-r2-access-key-id` / `morningbrief-r2-secret-access-key`
  (v2 only)
- The Worker's gating token isn't a local secret at all — it lives in
  Cloudflare's Worker environment and is embedded directly in your saved
  iOS Shortcut.

## 7. Estimated scope

Qualitative, not a schedule — same spirit as `ROADMAP.md`'s own phases.

**v1 (Telegram voice note):**
- `brief.py` refactor (data/text split) — small, low-risk
- `voice/script.py`, `voice/tts.py`, `voice/audio_convert.py` — the real
  work; mostly integration and tuning (voice model choice, prompt
  iteration, opus bitrate tuning to land comfortably under Telegram's
  1MB voice-bubble threshold for a 60–90s clip)
- Bizkit `send_voice.py` — small, closely mirrors existing code
- `scheduled_send_voice.py` + degradation contract + new `launchd` job —
  moderate; this is where the reliability work lives
- New Keychain secret + Anthropic API key signup — a setup step, like
  every other credential in this project

**v2 (R2 + Shortcuts):**
- Cloudflare account/bucket/Worker setup — the biggest unknown, since
  it's genuinely new infrastructure, not just new code
- `voice/storage.py` — small once the Worker exists
- iOS Shortcut itself — outside this repo, built on your phone

**v2 optional (podcast RSS):** smallest piece functionally, but real
scope creep risk if pushed hard. Recommend treating `feed.xml` generation
as a thin addition to `storage.py` (a static, hand-rolled RSS 2.0 file
updated alongside the MP3 push) rather than pulling in a podcasting
library — consistent with keeping this from complicating the design, per
your own instruction.

## 8. Decisions

1. **Scripting call: direct Anthropic API (`anthropic` SDK).** Confirmed
   — not a reuse of `politics.py`'s `claude -p` CLI pattern. This is a
   second, distinct way this project talks to Claude, with its own
   Keychain-stored API key (`morningbrief-anthropic-api-key`).
2. **Model: `claude-opus-4-8`.** Confirmed as the default for the
   scripting call.
3. **Alongside, not instead of, for now.** Confirmed — the existing
   twice-daily text brief keeps running unchanged while the voice
   pipeline is built and tuned. `voice_mode: "alongside" | "voice_only"`
   in config, defaulting to `"alongside"`, so this can flip later without
   a code change.

## 9. Still open — not blockers for starting v1

4. **Cloudflare** — confirm you have (or want to create) an account, and
   whether you have a domain to route the Worker through, or you're fine
   starting with a `workers.dev` subdomain for now. Only needed for v2.
5. **ElevenLabs** — no action needed until/unless Piper's quality
   disappoints in practice; flagging only so it's not forgotten as the
   agreed fallback.

## Draft ADR — for Bizkit's `DECISIONS.md` (pending approval)

Bizkit's most recent entry is ADR-0012; this would land as **ADR-0013**,
number to be confirmed against the live file at implementation time.

---

### ADR-0013: Voice briefing — TTS choice, delivery mechanism, and storage access

**Context:** MorningBrief's text brief is being extended with a spoken
audio edition. This needed three architectural calls: which TTS engine,
how the audio reaches the operator, and — since the audio contains
personal schedule/movement information — how a publicly-reachable copy
of it (for the iOS Shortcuts consumption path) stays access-controlled
without breaking the "stable URL a Shortcut can fetch in one request"
requirement.

**Decision:**
- **TTS: Piper first, local and free.** Runs entirely on this
  workstation, no per-request cost, no new data leaving the machine for
  the synthesis step itself. ElevenLabs (a paid, outbound-call API) is
  the agreed fallback if Piper's quality doesn't hold up in real use —
  not adopted preemptively, per Bizkit's standing "no speculative
  tooling" principle.
- **Delivery is phased and additive, never a single point of failure for
  the existing text brief.** v1 (Telegram voice note via a new
  `send_voice.py` primitive, mirroring the existing `send_message.py`)
  degrades to the already-reliable text path on any failure in the new
  script/TTS/conversion pipeline — the new capability is not allowed to
  make the existing one less reliable. v2 (Cloudflare R2 + Workers, for
  iOS Shortcuts) is independent infrastructure layered on top, not a
  replacement for v1.
- **Storage access: a Cloudflare Worker in front of a private R2
  bucket, gated by a static token on a stable URL path** — not a public
  bucket with an unguessable path, and not presigned URLs. Presigned
  URLs expire by design, which conflicts directly with "a Shortcut can
  fetch the same saved URL indefinitely." A public bucket makes
  obscurity the entire security model for content containing personal
  schedule data. The Worker pattern keeps the bucket private, keeps the
  URL genuinely stable, and makes token rotation a one-line change that
  touches neither R2 nor the rest of the pipeline.

**Consequences:** The audio pipeline is new surface area, but it cannot
regress the reliability of the text brief that already works — every
failure mode in the new pipeline has an explicit fallback to the
existing delivery path (see MorningBrief's `VOICE_PROPOSAL.md` §4). The
v2 storage layer introduces Bizkit's/MorningBrief's first dependency on
external cloud infrastructure beyond free data APIs and Telegram — a
deliberate, scoped exception, not a precedent for reaching for cloud
services by default.
