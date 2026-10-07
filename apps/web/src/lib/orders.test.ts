import { SessionApiError } from "@csmarket/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BalanceTooLowError,
  BuyingDisabledError,
  createAndPay,
  createOrder,
  devPayOrder,
  devTrade,
  getOrder,
  isPayProvider,
  listOrders,
  OfferGoneError,
  OrderNotPayableError,
  payOrder,
  PriceChangedError,
  TradeLinkError,
  type OrderOut,
} from "./orders";

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));

const KEY = "web-order-0123456789abcdef";

const ORDER: OrderOut = {
  number: "A1B2C3",
  status: "pending",
  slug: "ak-47-redline-ft",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  image_url: null,
  price_uzs: "381000",
  price_usd: "30.000000",
  created_at: "2026-10-02T10:00:00Z",
  expires_at: "2026-10-02T10:15:00Z",
  paid_at: null,
  delivered_at: null,
  paid_with: null,
  refunded_to: null,
  payable: true,
  trade: null,
};

const conflict = (body: Record<string, unknown>, status = 409) =>
  new SessionApiError(status, "Conflict", { type: "https://x/conflict", ...body });

async function createError(err: unknown): Promise<unknown> {
  api.apiPost.mockRejectedValueOnce(err);
  return createOrder({ slug: "s", listing_id: "wx:1", price_uzs: 1 }, KEY).catch((e: unknown) => e);
}

async function payError(err: unknown): Promise<unknown> {
  api.apiPost.mockRejectedValueOnce(err);
  return payOrder("A1B2C3", { provider: "wallet", locale: "ru" }, KEY).catch((e: unknown) => e);
}

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
});

describe("createOrder", () => {
  it("posts the offer and the price with the caller's key", async () => {
    api.apiPost.mockResolvedValueOnce(ORDER);
    const body = { slug: "ak-47-redline-ft", listing_id: "wx:7", price_uzs: 381000 };
    await expect(createOrder(body, KEY)).resolves.toBe(ORDER);
    expect(api.apiPost).toHaveBeenCalledWith("/api/v1/orders", body, { idempotencyKey: KEY });
  });

  it("a moved price carries the server's new price", async () => {
    const err = await createError(conflict({ code: "price_changed", price_uzs: "400100" }));
    expect(err).toBeInstanceOf(PriceChangedError);
    expect((err as PriceChangedError).priceUzs).toBe("400100");
  });

  it("a gone offer carries the next one, or null", async () => {
    const next = await createError(
      conflict({
        code: "offer_gone",
        next_offer: { listing_id: "sl:38029384123", price_uzs: "393700" },
      }),
    );
    expect(next).toBeInstanceOf(OfferGoneError);
    expect((next as OfferGoneError).nextOffer).toEqual({
      listing_id: "sl:38029384123",
      price_uzs: "393700",
    });
    const lis = await createError(
      conflict({
        code: "offer_gone",
        next_offer: { listing_id: "ls:125345", price_uzs: "171800" },
      }),
    );
    expect((lis as OfferGoneError).nextOffer).toEqual({
      listing_id: "ls:125345",
      price_uzs: "171800",
    });
    const none = await createError(conflict({ code: "offer_gone", next_offer: null }));
    expect((none as OfferGoneError).nextOffer).toBeNull();
    const junk = await createError(conflict({ code: "offer_gone", next_offer: { id: "x" } }));
    expect((junk as OfferGoneError).nextOffer).toBeNull();
    const numeric = await createError(
      conflict({ code: "offer_gone", next_offer: { listing_id: 9, price_uzs: "1" } }),
    );
    expect((numeric as OfferGoneError).nextOffer).toBeNull();
  });

  it("a refused trade link says which refusal", async () => {
    const missing = await createError(conflict({ code: "trade_link_missing" }));
    expect(missing).toBeInstanceOf(TradeLinkError);
    expect((missing as TradeLinkError).code).toBe("trade_link_missing");
    expect((missing as TradeLinkError).reason).toBeNull();
    const bad = await createError(conflict({ code: "trade_link_bad", reason: "private" }));
    expect((bad as TradeLinkError).code).toBe("trade_link_bad");
    expect((bad as TradeLinkError).reason).toBe("private");
    const odd = await createError(conflict({ code: "trade_link_bad", reason: "weird" }));
    expect((odd as TradeLinkError).reason).toBe("invalid");
  });

  it("buying switched off is its own error", async () => {
    expect(await createError(conflict({ code: "buying_disabled" }))).toBeInstanceOf(
      BuyingDisabledError,
    );
  });

  it("anything else passes through untouched", async () => {
    const outage = new SessionApiError(503, "Unavailable", { code: "rate_unavailable" });
    expect(await createError(outage)).toBe(outage);
    const unknown = conflict({ code: "something_new" });
    expect(await createError(unknown)).toBe(unknown);
    const notProblem = new SessionApiError(409, "Conflict", "plain text");
    expect(await createError(notProblem)).toBe(notProblem);
    const network = new TypeError("Failed to fetch");
    expect(await createError(network)).toBe(network);
  });
});

describe("payOrder", () => {
  it("posts the provider and the locale with a key of its own", async () => {
    api.apiPost.mockResolvedValueOnce({ order: ORDER, intent_url: null });
    await payOrder("A1B2C3", { provider: "click", locale: "uz" }, KEY);
    expect(api.apiPost).toHaveBeenCalledWith(
      "/api/v1/orders/A1B2C3/pay",
      { provider: "click", locale: "uz" },
      { idempotencyKey: KEY },
    );
  });

  it("a short balance and an unpayable order are typed", async () => {
    const short = await payError(
      new SessionApiError(409, "Conflict", {
        type: "x/insufficient-balance",
        code: "balance_too_low",
      }),
    );
    expect(short).toBeInstanceOf(BalanceTooLowError);
    const expired = await payError(conflict({ code: "order_not_payable", reason: "expired" }));
    expect(expired).toBeInstanceOf(OrderNotPayableError);
    expect((expired as OrderNotPayableError).reason).toBe("expired");
    const paid = await payError(conflict({ code: "order_not_payable", reason: "paid" }));
    expect((paid as OrderNotPayableError).reason).toBe("paid");
  });

  it("an unknown kassa or a key mismatch stays generic", async () => {
    const provider = new SessionApiError(422, "Unprocessable", { code: "order_provider" });
    expect(await payError(provider)).toBe(provider);
    const mismatch = conflict({ code: "idempotency_mismatch" });
    expect(await payError(mismatch)).toBe(mismatch);
  });
});

describe("isPayProvider", () => {
  it("knows the pay route's methods and nothing else", () => {
    for (const p of ["wallet", "click", "payme", "uzum", "mock"])
      expect(isPayProvider(p)).toBe(true);
    expect(isPayProvider("cash")).toBe(false);
  });
});

describe("reads and dev helpers", () => {
  it("reads one order and a page of orders", async () => {
    api.apiGet.mockResolvedValue(ORDER);
    await getOrder("A1/B");
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/orders/A1%2FB");
    await listOrders();
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/me/orders");
    await listOrders("c 1");
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/me/orders?cursor=c%201");
  });

  it("dev pay and dev trade post to the dev routes", async () => {
    api.apiPost.mockResolvedValue(ORDER);
    await devPayOrder("A1B2C3");
    expect(api.apiPost).toHaveBeenLastCalledWith("/api/v1/dev/orders/A1B2C3/pay", {});
    await devTrade("A1B2C3", "accept");
    expect(api.apiPost).toHaveBeenLastCalledWith("/api/v1/dev/orders/A1B2C3/trade", {
      action: "accept",
    });
  });

  it("a dev pay of an order that moved on is a typed refusal", async () => {
    api.apiPost.mockRejectedValueOnce(conflict({ code: "order_not_payable", reason: "expired" }));
    await expect(devPayOrder("A1")).rejects.toBeInstanceOf(OrderNotPayableError);
  });
});

describe("createAndPay", () => {
  const body = { slug: "s", listing_id: "wx:1", price_uzs: 381000 };
  const pay = { provider: "wallet", locale: "ru" } as const;
  let n = 0;
  const payKey = () => `web-pay-0000000000-${String(++n)}`;

  it("creates, then pays with a fresh key, and answers the number", async () => {
    api.apiPost
      .mockResolvedValueOnce(ORDER)
      .mockResolvedValueOnce({ order: ORDER, intent_url: null });
    await expect(createAndPay(body, pay, KEY, payKey)).resolves.toEqual({
      number: "A1B2C3",
      opened: true,
    });
    const keys = api.apiPost.mock.calls.map(
      (c) => (c[2] as { idempotencyKey: string }).idempotencyKey,
    );
    expect(keys[0]).toBe(KEY);
    expect(keys[1]).not.toBe(KEY);
  });

  it("an expired replay answers null without paying", async () => {
    api.apiPost.mockResolvedValueOnce({ ...ORDER, status: "cancelled", payable: false });
    await expect(createAndPay(body, pay, KEY, payKey)).resolves.toBeNull();
    expect(api.apiPost).toHaveBeenCalledTimes(1);
  });

  it("a paid replay goes to its page and never pays again", async () => {
    api.apiPost.mockResolvedValueOnce({ ...ORDER, status: "buying", payable: false });
    await expect(createAndPay(body, pay, KEY, payKey)).resolves.toEqual({
      number: "A1B2C3",
      opened: false,
    });
    expect(api.apiPost).toHaveBeenCalledTimes(1);
  });

  it("pay refusing an expired order answers null; a paid one answers the number", async () => {
    api.apiPost
      .mockResolvedValueOnce(ORDER)
      .mockRejectedValueOnce(conflict({ code: "order_not_payable", reason: "expired" }));
    await expect(createAndPay(body, pay, KEY, payKey)).resolves.toBeNull();
    api.apiPost
      .mockResolvedValueOnce(ORDER)
      .mockRejectedValueOnce(conflict({ code: "order_not_payable", reason: "paid" }));
    await expect(createAndPay(body, pay, KEY, payKey)).resolves.toEqual({
      number: "A1B2C3",
      opened: false,
    });
  });

  it("other pay failures are thrown", async () => {
    api.apiPost
      .mockResolvedValueOnce(ORDER)
      .mockRejectedValueOnce(new SessionApiError(409, "Conflict", { code: "balance_too_low" }));
    await expect(createAndPay(body, pay, KEY, payKey)).rejects.toBeInstanceOf(BalanceTooLowError);
  });
});
