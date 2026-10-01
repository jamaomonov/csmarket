import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createTopup,
  devPay,
  getBalance,
  getEntries,
  getProviders,
  getTopup,
  QUICK_AMOUNTS,
  signedUzs,
  TOPUP_MAX,
  TOPUP_MIN,
  topupAttemptKey,
  type AttemptStore,
} from "./balance";

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));

describe("topupAttemptKey", () => {
  it("keeps one key per (amount, provider), so a retry replays the same top-up", () => {
    const store: AttemptStore = { current: null };
    const first = topupAttemptKey(store, "50000:click");
    expect(first.length).toBeGreaterThanOrEqual(16);
    expect(first.length).toBeLessThanOrEqual(160);
    expect(topupAttemptKey(store, "50000:click")).toBe(first);
  });

  it("mints a new key once the amount or the provider changes", () => {
    const store: AttemptStore = { current: null };
    const first = topupAttemptKey(store, "50000:click");
    const otherAmount = topupAttemptKey(store, "60000:click");
    expect(otherAmount).not.toBe(first);
    const otherProvider = topupAttemptKey(store, "60000:payme");
    expect(otherProvider).not.toBe(otherAmount);
    // Going back is a new request too: the old one may already be paid.
    expect(topupAttemptKey(store, "50000:click")).not.toBe(first);
  });
});

describe("limits", () => {
  it("mirror the API's top-up bounds", () => {
    expect(TOPUP_MIN).toBe(1000);
    expect(TOPUP_MAX).toBe(10_000_000);
    for (const v of QUICK_AMOUNTS) {
      expect(v).toBeGreaterThanOrEqual(TOPUP_MIN);
      expect(v).toBeLessThanOrEqual(TOPUP_MAX);
    }
  });
});

describe("signedUzs", () => {
  it("prints the sign the ledger sent, with a real minus", () => {
    expect(signedUzs("ru", "+50000").replace(/\s/g, " ")).toBe("+50 000 сум");
    expect(signedUzs("ru", "-10000").replace(/\s/g, " ")).toBe("−10 000 сум");
    expect(signedUzs("uz", "+1000").replace(/\s/g, " ")).toBe("+1 000 soʻm");
  });
});

describe("API calls", () => {
  beforeEach(() => {
    api.apiGet.mockReset().mockResolvedValue({});
    api.apiPost.mockReset().mockResolvedValue({});
  });

  it("reads the balance, the providers (anonymously) and a top-up", async () => {
    await getBalance();
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/wallet");
    await getProviders();
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/payments/providers", {
      anonymous: true,
    });
    await getTopup("T12/x", "uz");
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/wallet/topups/T12%2Fx?locale=uz");
  });

  it("pages the history by cursor", async () => {
    await getEntries();
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/wallet/entries");
    await getEntries("a+b/c=");
    expect(api.apiGet).toHaveBeenLastCalledWith("/api/v1/wallet/entries?cursor=a%2Bb%2Fc%3D");
  });

  it("opens a top-up with the caller's key", async () => {
    await createTopup({ amount_uzs: 50_000, provider: "click", locale: "ru" }, "k".repeat(20));
    expect(api.apiPost).toHaveBeenCalledWith(
      "/api/v1/wallet/topups",
      { amount_uzs: 50_000, provider: "click", locale: "ru" },
      { idempotencyKey: "k".repeat(20) },
    );
  });

  it("pays a top-up through the dev route", async () => {
    await devPay("T1");
    expect(api.apiPost).toHaveBeenCalledWith("/api/v1/dev/topups/T1/pay", {});
  });
});
