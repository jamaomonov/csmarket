/**
 * The P2P webhook relay (spec 2026-10-19-p2p-topup, ADR-0021).
 *
 * One Telegram bot, one webhook, two projects: Telegram calls this Worker with the relay's own
 * secret; it forwards the update body unchanged to YuPay and to csmarket, each with that
 * project's own secret, in parallel, and answers Telegram 2xx only when BOTH answered 2xx.
 * Anything else is 502, so Telegram retries; both projects dedupe by message id, so a repeat
 * is harmless — and `getWebhookInfo.pending_update_count` still means "not delivered to both".
 *
 * Secrets (wrangler secret put): RELAY_SECRET, YUPAY_URL, YUPAY_SECRET, CSMARKET_URL,
 * CSMARKET_SECRET. The Worker logs no body (it holds bank notifications).
 */

const HEADER = "X-Telegram-Bot-Api-Secret-Token";
const MAX_BODY = 64 * 1024;

/** Constant-time string comparison through SHA-256 digests. */
export async function same(given, expected) {
  if (!expected) return false;
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(given)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i += 1) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function deliver(fetcher, url, secret, body) {
  try {
    const res = await fetcher(url, {
      method: "POST",
      headers: { "content-type": "application/json", [HEADER]: secret },
      body,
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function relay(request, env, fetcher = fetch) {
  if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
  if (!(await same(request.headers.get(HEADER) ?? "", env.RELAY_SECRET))) {
    return new Response("forbidden", { status: 401 });
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).length > MAX_BODY) {
    return new Response("too large", { status: 413 });
  }
  const [yupay, csmarket] = await Promise.all([
    deliver(fetcher, env.YUPAY_URL, env.YUPAY_SECRET, body),
    deliver(fetcher, env.CSMARKET_URL, env.CSMARKET_SECRET, body),
  ]);
  if (yupay && csmarket) return new Response("ok");
  console.log(JSON.stringify({ event: "relay.retry", yupay, csmarket }));
  return new Response("retry", { status: 502 });
}

export default {
  fetch(request, env) {
    return relay(request, env);
  },
};
