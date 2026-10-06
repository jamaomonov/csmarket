# P2P selling — parked idea (2026-10-06)

> Not planned. The owner wants to revisit this after launch, once real buys go through.
> This note keeps the conversation so it does not have to be had again.

## The idea

A light P2P market beside the Waxpeer supply: a seller lists skins from their inventory; a
buyer pays; the seller sends the Steam trade offer to the buyer themselves; we track the
offer; on success the money lands on the seller's **hold** balance and moves to their main
balance after **7 days** unless either side disputes or Steam rolls the trade back.

## What we already have

- Steam sign-in, trade link and its check (`auth`, `users`).
- A double-entry wallet (`wallet`): a hold is one more account kind plus a migration.
- Orders, the trade state machine, the worker queue, the scheduler, WebSocket, email and the
  admin with a manual trade verdict (`orders`, `realtime`, `notifications`, `admin`).

## What is new

1. **Listings** — the seller's inventory from Steam's public inventory endpoint (must be
   public), item, price, publish; a `listings` table; the catalogue merges P2P lots with
   Waxpeer's.
2. **Buy flow** — the buyer pays into our escrow (as orders do today); the seller is notified
   and has a deadline (say 24 h) to send, otherwise cancel + refund.
3. **Trade verification** — the hard part. Steam does not tell us about other people's trades.
   - **Chrome extension (preferred):** runs on `steamcommunity.com` under the seller's session,
     reads the offer (exact `assetid`), can pre-open the offer to the buyer, reports status.
     What Skinport / Waxpeer / CSFloat / DMarket do. Desktop Chrome/Edge only; store review
     1–2 weeks; open source and minimal permissions or sellers will not install it; breaks
     when Steam changes markup. **Never auto-harvest the seller's API key** (the «API scam»
     mechanic).
   - **Seller's Steam Web API key (fallback, phones):** `IEconService/GetTradeOffers` with the
     seller's key. Reliable; some sellers refuse.
   - **The extension's report is a signal, not proof** — it runs on the seller's machine and
     the seller is the party with a motive to lie. Independent check on our side: poll the
     buyer's public inventory for the `assetid` the extension reported, or the buyer confirms
     receipt; disputes go to the admin's manual verdict (exists).
4. **7-day hold** — ledger kind `seller_hold`; a scheduler job releases to the main balance
   after 7 days with no dispute. Dispute = buyer «не получил» / seller «отменить» → admin.
   Seven days because Steam reverts trades of hijacked accounts in about that window.
5. **Screens** — seller: inventory, my lots, sales, hold, dispute; admin: lot moderation,
   disputes.

## Mixing P2P lots with the provider's (owner's question, 2026-10-06)

Split by **delivery time**, never by source, and at the **offer** level, not the item's. One
catalogue item, all offers under it, each with a badge — the way TM (market.csgo) and
CS.MONEY do it.

- **Card:** price = the cheapest offer of either source, count = all offers. One badge by the
  cheapest offer: ⚡ «Мгновенно» (provider) or 🕐 «До 12 часов» (our seller). A new filter
  section «Доставка»: Мгновенно / До 12 часов (default: all); a `delivery` facet in
  `/skins/facets`.
- **Item page:** a segmented control over the offers — Все / ⚡ Мгновенно / 🕐 До 12 часов;
  sorted by price, instant first on a tie; every row badged; a P2P row also shows the seller's
  level (deals, success rate, time on the site). Float, pattern and stickers per offer, as now.
- **Buying:** the button says what happens — «Купить — получите сразу» / «Купить — продавец
  отправит до 12 часов». For P2P the 12 hours are a rule, not a label: a timer on the order
  page, auto-cancel + refund when the seller has not sent in time. Buyer notified (WS + email)
  when the offer is sent.
- **Inside:** one offer shape for both sources — `source: waxpeer | p2p`,
  `delivery: instant | up_to_12h`, price, float. P2P lots come from our DB (always fresh),
  Waxpeer from the 90-s cache; merged in `GET /skins/{slug}/listings`; cards take the minimum
  of both in the 5-min snapshot.
- **Two rules:** the customer never sees the source («Waxpeer», «провайдер», «P2P») — only the
  delivery time (AGENTS §12 and it hides where we buy); prices sort honestly, no boost for our
  own lots — waiting 12 hours must simply be cheaper than getting it now.

## To decide before starting

- **Payout.** Crediting the balance is easy; today the balance only buys skins. Card payouts
  through Click / Payme are a separate project and an acquirer agreement as a legal entity.
- **Fraud.** Wrong item or float — caught only with the extension / API key. Buying one's own
  lot with kassa money is laundering: limits and most likely KYC.
- **Commission** and a minimum lot price.

## Size

About M4a plus half of M4b; the extension adds roughly 15–20 % (its own `apps/extension`,
MV3, a content script on `steamcommunity.com/tradeoffer/*`, a background worker, account
linking by a one-time code, two or three API endpoints). Start with `superpowers:brainstorming`
→ spec → plan, as every milestone.

Related spec hooks: the `sell` module slot and the `sell_payout` ledger kind (spec §17).
