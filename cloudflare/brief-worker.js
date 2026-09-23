/**
 * Gates read access to the "latest.mp3" object in a private R2 bucket
 * behind a static token passed as the X-Brief-Token header - never a
 * query parameter, since URLs (including query strings) get logged at
 * nearly every HTTP hop by default while headers generally aren't.
 * See R2_DELIVERY_PROPOSAL.md section 2 and DECISIONS.md ADR-0003 for
 * the full reasoning.
 *
 * Every non-success path (wrong method, missing/wrong token, missing
 * secret, missing object) returns the exact same 404 response - no
 * 403/405 - so a probe can't distinguish "wrong token" from "nothing
 * here" from "method not supported." Fails closed: if BRIEF_ACCESS_TOKEN
 * itself is unset or empty, every request gets the same 404, rather
 * than an empty header matching an empty secret and serving the file
 * unauthenticated. This matters concretely during setup - the token
 * secret and the R2 binding aren't necessarily configured in the same
 * step, so there's a real window where the secret could be unset.
 *
 * Deployment (Cloudflare dashboard, not this repo - this file is not
 * executed on the Mac, it's pasted into the Workers editor):
 *   1. Create a Worker, paste this in.
 *   2. Settings -> Bindings -> R2 Bucket -> bind the bucket as `BRIEF_BUCKET`.
 *   3. Settings -> Variables -> add a Secret named `BRIEF_ACCESS_TOKEN`
 *      (generate with `openssl rand -hex 32` - this token is never
 *      shared with the Python pipeline or stored in this repo; it only
 *      needs to match what you put in the Shortcut's header field).
 *      Do this *before* relying on the deployment - until it's set,
 *      every request 404s by design (see above), so there's no window
 *      where the file is reachable without it.
 *   4. Use the free *.workers.dev URL - no custom domain required.
 *
 * The object's real R2 upload time (`.uploaded`) is passed through as
 * Last-Modified, not the time of this request, so a Shortcut checking
 * freshness sees the true push time.
 */

const OBJECT_KEY = "latest.mp3";

function notFound() {
  return new Response("Not Found", { status: 404 });
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  return crypto.subtle.digest("SHA-256", bytes);
}

// Both inputs are hashed to a fixed-length SHA-256 digest before
// comparison - digests are always 32 bytes regardless of the original
// token's length, so crypto.subtle.timingSafeEqual (which throws on
// unequal-length inputs) never needs a length branch, and there's no
// timing signal tied to the original token length either.
async function tokensMatch(provided, expected) {
  const [providedDigest, expectedDigest] = await Promise.all([
    sha256(provided),
    sha256(expected),
  ]);
  return crypto.subtle.timingSafeEqual(providedDigest, expectedDigest);
}

export default {
  async fetch(request, env) {
    const secret = env.BRIEF_ACCESS_TOKEN;
    if (!secret) {
      // Fail closed: an unset/empty secret must never be reachable,
      // not even by an empty or missing header.
      return notFound();
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return notFound();
    }

    const token = request.headers.get("X-Brief-Token") || "";
    if (!token || !(await tokensMatch(token, secret))) {
      return notFound();
    }

    const object = await env.BRIEF_BUCKET.get(OBJECT_KEY);
    if (!object) {
      return notFound();
    }

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);
    headers.set("last-modified", object.uploaded.toUTCString());
    headers.set("cache-control", "private, no-store");

    if (request.method === "HEAD") {
      return new Response(null, { headers });
    }
    return new Response(object.body, { headers });
  },
};
