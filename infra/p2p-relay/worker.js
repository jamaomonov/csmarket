/**
 * The P2P webhook relay (spec 2026-10-19-p2p-topup, ADR-0021).
 *
 * One Telegram bot, one webhook, two projects. Telegram calls this Worker with the relay's own
 * secret. The update goes to YuPay synchronously: Telegram gets 2xx exactly when YuPay
 * answered 2xx (so `pending_update_count` still means "not yet delivered to YuPay", and a
 * failure makes Telegram retry). csmarket's copy is delivered on its own so csmarket being
 * down never stops YuPay: through the Cloudflare Queue `CSMARKET_QUEUE` when bound (retried
 * with backoff, then a dead-letter queue), else in the background with a few retries, logged.
 * Both projects dedupe by message id, so repeats are harmless.
 *
 * Secrets (wrangler secret put): RELAY_SECRET, YUPAY_URL, YUPAY_SECRET, CSMARKET_URL,
 * CSMARKET_SECRET. The Worker never logs a body (it holds bank notifications).
 */

const HEADER = "X-Telegram-Bot-Api-Secret-Token";
const MAX_BODY = 64 * 1024;
const BACKGROUND_TRIES = 4;

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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** No queue bound: try csmarket a few times in the background (1 s, 4 s, 9 s apart;
 * `RELAY_BACKOFF_MS` scales the step — tests set 0). */
async function backgroundToCsmarket(env, body, fetcher) {
  const step = env.RELAY_BACKOFF_MS === undefined ? 1000 : Number(env.RELAY_BACKOFF_MS);
  for (let attempt = 1; attempt <= BACKGROUND_TRIES; attempt += 1) {
    if (await deliver(fetcher, env.CSMARKET_URL, env.CSMARKET_SECRET, body)) return;
    if (attempt < BACKGROUND_TRIES) await sleep(attempt * attempt * step);
  }
  console.log(JSON.stringify({ event: "relay.csmarket_lost", tries: BACKGROUND_TRIES }));
}

export async function relay(request, env, ctx, fetcher = fetch) {
  if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
  if (!(await same(request.headers.get(HEADER) ?? "", env.RELAY_SECRET))) {
    return new Response("forbidden", { status: 401 });
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).length > MAX_BODY) {
    return new Response("too large", { status: 413 });
  }
  if (!(await deliver(fetcher, env.YUPAY_URL, env.YUPAY_SECRET, body))) {
    console.log(JSON.stringify({ event: "relay.yupay_retry" }));
    return new Response("retry", { status: 502 });
  }
  if (env.CSMARKET_QUEUE) {
    await env.CSMARKET_QUEUE.send({ body });
  } else {
    ctx.waitUntil(backgroundToCsmarket(env, body, fetcher));
  }
  return new Response("ok");
}

/** The `CSMARKET_QUEUE` consumer: deliver each update, retry a failure (Queues backs off). */
export async function consumeCsmarket(batch, env, fetcher = fetch) {
  for (const message of batch.messages) {
    if (await deliver(fetcher, env.CSMARKET_URL, env.CSMARKET_SECRET, message.body.body)) {
      message.ack();
    } else {
      message.retry({ delaySeconds: 30 });
    }
  }
}

export default {
  fetch(request, env, ctx) {
    return relay(request, env, ctx);
  },
  queue(batch, env) {
    return consumeCsmarket(batch, env);
  },
};
