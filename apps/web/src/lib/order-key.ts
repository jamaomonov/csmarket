/** The idempotency key of `POST /orders`, kept per (offer, trade link) across retries. */

export interface OrderKey {
  listingId: number;
  tradeLink: string;
  key: string;
}

/**
 * One order key per offer and trade link: a retry of the same purchase replays the order
 * already opened; another offer — or another link — is a new order. The API replays a
 * keyed order whatever the body says, so a key that outlived a link change would send the
 * skin to the old link.
 */
export function orderKeyFor(
  current: OrderKey | null,
  listingId: number,
  tradeLink: string,
  mint: () => string,
): OrderKey {
  return current?.listingId === listingId && current.tradeLink === tradeLink
    ? current
    : { listingId, tradeLink, key: mint() };
}

/** A fresh `POST /orders` key (16–160 chars on the API side). */
export function mintOrderKey(): string {
  return `web-order-${crypto.randomUUID()}`;
}

/** A fresh `POST /orders/{number}/pay` key: one per pay call. */
export function mintPayKey(): string {
  return `web-pay-${crypto.randomUUID()}`;
}
