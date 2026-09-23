/**
 * Gates read access to the "latest.mp3" object in a private R2 bucket
 * behind a static token passed as the X-Brief-Token header - never a
 * query parameter, since URLs (including query strings) get logged at
 * nearly every HTTP hop by default while headers generally aren't.
 * See R2_DELIVERY_PROPOSAL.md section 2 and DECISIONS.md ADR-0003 for
 * the full reasoning.
 *
 * Deployment (Cloudflare dashboard, not this repo - this file is not
 * executed on the Mac, it's pasted into the Workers editor):
 *   1. Create a Worker, paste this in.
 *   2. Settings -> Bindings -> R2 Bucket -> bind the bucket as `BRIEF_BUCKET`.
 *   3. Settings -> Variables -> add a Secret named `BRIEF_ACCESS_TOKEN`
 *      (generate with `openssl rand -hex 32` - this token is never
 *      shared with the Python pipeline or stored in this repo; it only
 *      needs to match what you put in the Shortcut's header field).
 *   4. Use the free *.workers.dev URL - no custom domain required.
 *
 * The object's real R2 upload time (`.uploaded`) is passed through as
 * Last-Modified, not the time of this request, so a Shortcut checking
 * freshness sees the true push time.
 */

const OBJECT_KEY = "latest.mp3";

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }

    const token = request.headers.get("X-Brief-Token") || "";
    if (!timingSafeEqual(token, env.BRIEF_ACCESS_TOKEN || "")) {
      return new Response("Forbidden", { status: 403 });
    }

    const object = await env.BRIEF_BUCKET.get(OBJECT_KEY);
    if (!object) {
      return new Response("Not found", { status: 404 });
    }

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);
    headers.set("last-modified", object.uploaded.toUTCString());
    headers.set("cache-control", "no-store");

    if (request.method === "HEAD") {
      return new Response(null, { headers });
    }
    return new Response(object.body, { headers });
  },
};

// Not cryptographically bulletproof against a sophisticated timing
// attack (this Worker's own scheduling jitter dominates any signal),
// but avoids the most obvious short-circuit-on-first-mismatch leak.
// Proportionate for a personal single-user tool, not a bank.
function timingSafeEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
