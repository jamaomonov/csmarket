// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkinBuyPanel } from "./SkinBuyPanel";
import { SkinOffersProvider, useSelectedOffer } from "./SkinOffers";

import type { Me } from "@/lib/auth";
import type { OrderOut } from "@/lib/orders";
import type * as SkinsModule from "@/lib/skins";
import type { ReactNode } from "react";

import { fetchSkinListings } from "@/lib/skins";

interface Opts {
  idempotencyKey?: string;
}

const m = vi.hoisted(() => {
  const auth: { value: Record<string, unknown> } = { value: {} };
  return {
    push: vi.fn(),
    refreshMe: vi.fn(() => Promise.resolve()),
    auth,
    create: vi.fn<(body: unknown, key: string | undefined) => Promise<unknown>>(),
    pay: vi.fn<(path: string, body: unknown, key: string | undefined) => Promise<unknown>>(),
    check: vi.fn<() => Promise<unknown>>(),
    balance: vi.fn<() => Promise<unknown>>(),
    providers: vi.fn<() => Promise<unknown>>(),
  };
});

vi.mock("@/lib/api", () => ({
  session: {
    apiPost: (path: string, body: unknown, opts?: Opts) => {
      if (path === "/api/v1/orders") return m.create(body, opts?.idempotencyKey);
      if (path.endsWith("/pay")) return m.pay(path, body, opts?.idempotencyKey);
      if (path === "/api/v1/me/trade-link/check") return m.check();
      return Promise.reject(new Error(`unexpected POST ${path}`));
    },
    apiGet: (path: string) => {
      if (path === "/api/v1/wallet") return m.balance();
      if (path === "/api/v1/payments/providers") return m.providers();
      return Promise.reject(new Error(`unexpected GET ${path}`));
    },
  },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => m.auth.value }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: m.push }),
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/skins", async (importOriginal) => ({
  ...(await importOriginal<typeof SkinsModule>()),
  fetchSkinListings: vi.fn(),
}));

// A made-up link: never a real token in tests.
const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=12345&token=FakeTok0";

const USER: Me = {
  id: "u1",
  steam_id: "76561190000000001",
  display_name: "Buyer",
  avatar_url: null,
  email: null,
  email_verified: false,
  locale: "ru",
  trade_link: LINK,
  trade_link_verdict: "ok",
  trade_link_reason: null,
  trade_link_checked_at: "2026-10-02T09:00:00Z",
  roles: [],
  created_at: "2026-10-01T00:00:00Z",
};

const offer = (id: number, usd: string, uzs: string) => ({
  listing_id: id,
  price_usd: usd,
  price_uzs: uzs,
  float_value: 0.2,
  paint_seed: 1,
  stickers: [],
  inspect_url: null,
});

const order = (number: string, over: Partial<OrderOut> = {}): OrderOut => ({
  number,
  status: "pending",
  slug: "ak",
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
  ...over,
});

const conflict = (body: Record<string, unknown>) =>
  new SessionApiError(409, "Conflict", { type: "https://x/conflict", ...body });

function signedIn(user: Partial<Me> = {}) {
  m.auth.value = {
    status: "signed_in",
    user: { ...USER, ...user },
    signInHref: (l: string) => `http://api/start?locale=${l}`,
    refreshMe: m.refreshMe,
  };
}

/** Stands in for a listings row's «Выбрать». */
function Choose({ id }: { id: number }) {
  const { select } = useSelectedOffer();
  return (
    <button
      type="button"
      onClick={() => {
        select(id);
      }}
    >
      {`pick ${String(id)}`}
    </button>
  );
}

function panel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = () => (
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SkinOffersProvider slug="ak">
          <SkinBuyPanel slug="ak" locale="ru" />
          <Choose id={2} />
        </SkinOffersProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  const view = render(tree());
  return {
    rerender: () => {
      view.rerender(tree());
    },
  };
}

const flat = (s: string | null | undefined) => (s ?? "").replace(/\s/g, " ");
const buyButton = (price: string) =>
  screen.findByRole("button", { name: (n) => flat(n) === `Купить за ${price} сум` });
/** The button once it can be pressed (the kassas and the balance have loaded). */
async function ready(price: string): Promise<HTMLElement> {
  const button = await buyButton(price);
  await waitFor(() => {
    expect(button).toBeEnabled();
  });
  return button;
}
const createKeys = () => m.create.mock.calls.map(([, key]) => key);

beforeEach(() => {
  for (const f of [m.push, m.refreshMe, m.create, m.pay, m.check, m.balance, m.providers]) {
    f.mockReset();
  }
  m.refreshMe.mockResolvedValue(undefined);
  vi.mocked(fetchSkinListings).mockResolvedValue({
    degraded: false,
    items: [offer(2, "31.00", "393700"), offer(1, "30.00", "381000")],
  });
  m.balance.mockResolvedValue({ balance_uzs: "0" });
  m.providers.mockResolvedValue({ providers: [{ slug: "click" }, { slug: "mock" }] });
  m.create.mockResolvedValue(order("A100"));
  m.pay.mockResolvedValue({ order: order("A100"), intent_url: null });
  signedIn();
});

describe("SkinBuyPanel — who can buy", () => {
  it("asks a visitor to sign in with Steam", async () => {
    m.auth.value = { status: "anonymous", user: null, signInHref: (l: string) => `/start?l=${l}` };
    panel();
    const link = await screen.findByRole("link", { name: "Войдите через Steam, чтобы купить" });
    expect(link).toHaveAttribute("href", "/start?l=ru");
    expect(screen.queryByRole("button", { name: /Купить за/ })).not.toBeInTheDocument();
  });

  it("asks for a trade link when there is none", async () => {
    signedIn({ trade_link: null, trade_link_verdict: null });
    panel();
    expect(await screen.findByText("Добавьте трейд-ссылку, чтобы купить")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Добавить ссылку" })).toHaveAttribute(
      "href",
      "/account",
    );
    expect(screen.queryByRole("button", { name: /Купить за/ })).not.toBeInTheDocument();
  });

  it("shows why a bad link cannot receive the skin and does not let it buy", async () => {
    signedIn({ trade_link_verdict: "bad", trade_link_reason: "private" });
    panel();
    expect(await screen.findByText(/Инвентарь скрыт/)).toBeInTheDocument();
    expect(await buyButton("381 000")).toBeDisabled();
    expect(m.check).not.toHaveBeenCalled();
  });

  it("checks an unchecked link once, then lets it buy", async () => {
    signedIn({ trade_link_verdict: null, trade_link_reason: null, trade_link_checked_at: null });
    let finish: (v: unknown) => void = () => undefined;
    m.check.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const view = panel();
    expect(await screen.findByText("Проверяем трейд-ссылку…")).toBeInTheDocument();
    expect(await buyButton("381 000")).toBeDisabled();
    view.rerender();
    act(() => {
      finish({ trade_link: LINK, verdict: "ok", reason: null, checked_at: null });
    });
    await waitFor(async () => {
      expect(await buyButton("381 000")).toBeEnabled();
    });
    expect(m.check).toHaveBeenCalledTimes(1);
    expect(m.refreshMe).toHaveBeenCalled();
  });

  it("a check that finds the link bad blocks the purchase", async () => {
    signedIn({ trade_link_verdict: null, trade_link_reason: null });
    m.check.mockResolvedValue({ trade_link: LINK, verdict: "bad", reason: "trade_ban" });
    panel();
    expect(await screen.findByText(/ограничение на обмен/)).toBeInTheDocument();
    expect(await buyButton("381 000")).toBeDisabled();
  });
});

describe("SkinBuyPanel — payment method", () => {
  it("pre-selects the balance when it covers the price", async () => {
    m.balance.mockResolvedValue({ balance_uzs: "500000" });
    panel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Баланс/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByRole("button", { name: "Click" })).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps a kassa when the balance is short and says how much is missing", async () => {
    m.balance.mockResolvedValue({ balance_uzs: "380000" });
    panel();
    const tile = await screen.findByRole("button", { name: /Не хватает 1\s000 сум/ });
    expect(tile).toBeDisabled();
    expect(screen.getByRole("button", { name: "Click" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("link", { name: "Пополнить" })).toHaveAttribute(
      "href",
      "/account/balance",
    );
  });
});

describe("SkinBuyPanel — buying", () => {
  it("pays from the balance and goes to the order", async () => {
    m.balance.mockResolvedValue({ balance_uzs: "500000" });
    panel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Баланс/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    fireEvent.click(await ready("381 000"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledWith("/orders/A100");
    });
    expect(m.create).toHaveBeenCalledWith(
      { slug: "ak", listing_id: 1, price_uzs: 381000 },
      expect.any(String),
    );
    const [orderKey] = createKeys();
    expect(orderKey?.length).toBeGreaterThanOrEqual(16);
    const [path, body, payKey] = m.pay.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/orders/A100/pay");
    expect(body).toEqual({ provider: "wallet", locale: "ru" });
    expect(payKey?.length).toBeGreaterThanOrEqual(16);
    expect(payKey).not.toBe(orderKey);
  });

  it("through a kassa it goes to the order page, which opens the kassa", async () => {
    m.pay.mockResolvedValue({ order: order("A100"), intent_url: "https://kassa.example/pay" });
    panel();
    fireEvent.click(await ready("381 000"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledWith("/orders/A100?go=1&via=click");
    });
    expect(m.pay.mock.calls[0]?.[1]).toEqual({ provider: "click", locale: "ru" });
  });

  it("buys the offer chosen in the list", async () => {
    panel();
    await buyButton("381 000");
    fireEvent.click(screen.getByRole("button", { name: "pick 2" }));
    fireEvent.click(await ready("393 700"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalled();
    });
    expect(m.create.mock.calls[0]?.[0]).toEqual({ slug: "ak", listing_id: 2, price_uzs: 393700 });
  });

  it("a double click sends one order", async () => {
    let finish: (o: OrderOut) => void = () => undefined;
    m.create.mockReturnValue(
      new Promise<OrderOut>((resolve) => {
        finish = resolve;
      }),
    );
    panel();
    const button = await ready("381 000");
    fireEvent.click(button);
    fireEvent.click(button);
    act(() => {
      finish(order("A100"));
    });
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledTimes(1);
    });
    expect(m.create).toHaveBeenCalledTimes(1);
    expect(m.pay).toHaveBeenCalledTimes(1);
  });

  it("a moved price is shown, kept on the offer and sent on the next press with the same key", async () => {
    m.create
      .mockRejectedValueOnce(conflict({ code: "price_changed", price_uzs: "400100" }))
      .mockResolvedValueOnce(order("A100", { price_uzs: "400100" }));
    panel();
    fireEvent.click(await ready("381 000"));
    expect(flat((await screen.findByRole("status")).textContent)).toBe(
      "Цена изменилась: теперь 400 100 сум",
    );
    fireEvent.click(await ready("400 100"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledWith("/orders/A100?go=1&via=click");
    });
    expect(m.create.mock.calls[1]?.[0]).toEqual({ slug: "ak", listing_id: 1, price_uzs: 400100 });
    const [first, second] = createKeys();
    expect(second).toBe(first);
  });

  it("a sold offer moves to the next one, which a new press buys", async () => {
    m.create
      .mockRejectedValueOnce(
        conflict({ code: "offer_gone", next_offer: { listing_id: 2, price_uzs: "393700" } }),
      )
      .mockResolvedValueOnce(order("A200"));
    panel();
    fireEvent.click(await ready("381 000"));
    expect(flat((await screen.findByRole("status")).textContent)).toBe(
      "Этот лот уже купили. Следующий — 393 700 сум",
    );
    fireEvent.click(await ready("393 700"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledWith("/orders/A200?go=1&via=click");
    });
    expect(m.create.mock.calls[1]?.[0]).toMatchObject({ listing_id: 2, price_uzs: 393700 });
    const [first, second] = createKeys();
    expect(second).not.toBe(first);
  });

  it("says when no offers are left", async () => {
    vi.mocked(fetchSkinListings).mockResolvedValue({
      degraded: false,
      items: [offer(1, "30.00", "381000")],
    });
    m.create.mockRejectedValueOnce(conflict({ code: "offer_gone", next_offer: null }));
    panel();
    fireEvent.click(await ready("381 000"));
    expect(await screen.findByText("Предложения закончились")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Купить за/ })).not.toBeInTheDocument();
  });

  it("a replayed order that expired is retried once with a fresh key", async () => {
    m.pay
      .mockRejectedValueOnce(conflict({ code: "order_not_payable", reason: "expired" }))
      .mockResolvedValueOnce({ order: order("A300"), intent_url: null });
    m.create.mockResolvedValueOnce(order("A100")).mockResolvedValueOnce(order("A300"));
    panel();
    fireEvent.click(await ready("381 000"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledWith("/orders/A300?go=1&via=click");
    });
    const [first, second] = createKeys();
    expect(m.create).toHaveBeenCalledTimes(2);
    expect(second).not.toBe(first);
    expect(second?.length).toBeGreaterThanOrEqual(16);
  });

  it("a replayed order that is already paid goes to its page and is never bought again", async () => {
    m.create.mockResolvedValueOnce(order("A100", { status: "buying", payable: false }));
    panel();
    fireEvent.click(await ready("381 000"));
    await waitFor(() => {
      expect(m.push).toHaveBeenCalledWith("/orders/A100");
    });
    expect(m.create).toHaveBeenCalledTimes(1);
    expect(m.pay).not.toHaveBeenCalled();
  });

  it("a trade link the API refuses reads as the verdict, and the profile is re-read", async () => {
    m.create.mockRejectedValueOnce(conflict({ code: "trade_link_bad", reason: "hold" }));
    panel();
    fireEvent.click(await ready("381 000"));
    expect(await screen.findByText(/Steam задерживает обмены/)).toBeInTheDocument();
    expect(await buyButton("381 000")).toBeDisabled();
    expect(m.refreshMe).toHaveBeenCalled();
  });

  it("never shows the API's own text", async () => {
    m.create.mockRejectedValueOnce(
      new SessionApiError(503, "Service Unavailable", {
        title: "Upstream market timeout",
        detail: "market said no",
        code: "rate_unavailable",
      }),
    );
    panel();
    fireEvent.click(await ready("381 000"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не получилось оформить заказ. Попробуйте ещё раз.",
    );
    expect(document.body.textContent).not.toMatch(/market|Unavailable|timeout/i);
    expect(await buyButton("381 000")).toBeEnabled();
  });

  it("explains how delivery works", async () => {
    panel();
    expect(
      await screen.findByText(
        "После оплаты продавец отправит обмен в Steam. Примите его — скин ваш.",
      ),
    ).toBeInTheDocument();
  });
});
