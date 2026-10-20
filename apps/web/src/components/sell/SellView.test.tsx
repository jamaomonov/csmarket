// apps/web/src/components/sell/SellView.test.tsx
// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SellView } from "./SellView";

import type { Inventory, SellConfig } from "@/lib/sell";

const auth = vi.hoisted((): { value: Record<string, unknown> } => ({ value: {} }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  api: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ session: api }));
const push = vi.hoisted(() => vi.fn());
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push }),
}));

const CONFIG: SellConfig = {
  enabled: true,
  balance_bonus_pct: "2",
  card_fee_pct: { uzcard: "5", humo: "5", uzum_visa: "5" },
  card_min_uzs: "30000",
  min_sum_uzs: "11300",
  max_cards: 3,
};
const INVENTORY: Inventory = {
  items: [
    {
      asset_id: "101",
      name: "P250 | Sand Dune (Field-Tested)",
      image_url: "https://img.test/101.png",
      exterior: "Field-Tested",
      rarity_color: null,
      category: null,
      price_uzs: "5600",
    },
    {
      asset_id: "100",
      name: "AK-47 | Redline (Field-Tested)",
      image_url: "https://img.test/100.png",
      exterior: "Field-Tested",
      rarity_color: "#d32ce6",
      category: "rifles",
      price_uzs: "149600",
    },
  ],
  max_items: 50,
  min_sum_uzs: "11300",
  fetched_at: "2026-10-08T10:00:00Z",
};
const SIGNED_IN = {
  status: "signed_in",
  user: {
    id: "u1",
    trade_link: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE",
  },
  signInHref: () => "/auth",
  refreshMe: vi.fn(),
};

function routeGets(
  inventory: () => Promise<unknown> = () => Promise.resolve(INVENTORY),
  cards: () => Promise<unknown> = () => Promise.resolve({ items: [] }),
) {
  api.apiGet.mockImplementation((path: string) =>
    path.startsWith("/api/v1/sell/inventory")
      ? inventory()
      : path === "/api/v1/payout-cards"
        ? cards()
        : Promise.reject(new Error(path)),
  );
}

const cardCalls = () =>
  api.apiGet.mock.calls.filter(([path]) => path === "/api/v1/payout-cards").length;
const HUMO = "9860123456789015";
const SAVED_HUMO = { id: "c1", type: "humo", last4: "9015", created_at: "2026-10-08T10:00:00Z" };

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <SellView locale="ru" config={CONFIG} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

/** The first of the cart copies (the desktop aside and the mobile sheet share the text). */
const first = (els: HTMLElement[]): HTMLElement => {
  const [el] = els;
  if (!el) throw new Error("no element");
  return el;
};
const card = (name: RegExp) => screen.getByRole("button", { name });

describe("SellView", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    push.mockReset();
    auth.value = SIGNED_IN;
    routeGets();
  });

  it("asks a visitor to sign in", () => {
    auth.value = { status: "signed_out", user: null, signInHref: () => "/auth" };
    view();
    expect(screen.getByText("Войдите через Steam, чтобы продать скины.")).toBeInTheDocument();
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it("asks for a trade link first", () => {
    auth.value = { ...SIGNED_IN, user: { id: "u1", trade_link: null } };
    view();
    expect(screen.getByText(/Добавьте ссылку на обмен/)).toBeInTheDocument();
  });

  it("shows the inventory's own layout, empty, while it loads", () => {
    api.apiGet.mockImplementation((path: string) =>
      path === "/api/v1/sell/inventory" ? new Promise(() => undefined) : Promise.resolve([]),
    );
    view();
    const loading = screen.getByRole("status", { name: "Загружаем ваш инвентарь…" });
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading.querySelectorAll("[data-skeleton-card]")).toHaveLength(8);
    expect(loading.querySelector("[data-skeleton-cart]")).not.toBeNull();
  });

  it("lists the items we buy, dearest first, and says what is shown", async () => {
    view();
    const names = await screen.findAllByText(/Redline|Sand Dune/);
    expect(names[0]).toHaveTextContent("Redline");
    expect(
      screen.getByText("Показаны предметы, которые можно продать сейчас."),
    ).toBeInTheDocument();
  });

  it("adds the balance bonus to the payout", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(card(/Sand Dune/));
    expect(screen.getAllByTestId("sell-payout")[0]).toHaveTextContent(/158\s300/);
  });

  it("keeps «Продать» off under the minimum and says how much to add", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Sand Dune/ }));
    const submit = screen.getAllByRole("button", { name: /Добавьте ещё на 5\s700/ })[0];
    expect(submit).toBeDisabled();
  });

  it("says selling accepts the buyback terms, with a link to them", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    for (const link of screen.getAllByRole("link", { name: "условия выкупа" })) {
      expect(link).toHaveAttribute("href", "/legal/sell");
    }
  });

  it("lets ten cheap items through: rounding each down must not block the sale", async () => {
    const letters = "ABCDEFGHIJ".split("");
    const base = INVENTORY.items[0];
    if (!base) throw new Error("no base item");
    routeGets(() =>
      Promise.resolve({
        ...INVENTORY,
        items: letters.map((l, i) => ({
          ...base,
          asset_id: String(200 + i),
          name: `Skin ${l}`,
          price_uzs: "1100", // 0.10 $ each, rounded down to 100
        })),
      }),
    );
    view();
    for (const l of letters) {
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(`Skin ${l}`) }));
    }
    // 10 x 1 100 = 11 000 is under the 11 300 hint, yet the API accepts it (spec §3).
    const submit = first(screen.getAllByRole("button", { name: /Продать за/ }));
    expect(submit).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Добавьте ещё/ })).toBeNull();
  });

  it("sells with a key and the payout it showed, then opens the sale", async () => {
    api.apiPost.mockResolvedValue({ number: "S7K2M9QX" });
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за 152\s500/ })));
    await waitFor(() => {
      expect(push).toHaveBeenCalledWith("/account/sales/S7K2M9QX");
    });
    const [path, body, options] = api.apiPost.mock.calls[0] as [
      string,
      unknown,
      { idempotencyKey: string },
    ];
    expect(path).toBe("/api/v1/sell");
    expect(body).toEqual({
      asset_ids: ["100"],
      payout: { to: "balance" },
      expected_payout_uzs: 152_500,
    });
    expect(options.idempotencyKey).toMatch(/^web-sell-/);
  });

  it("re-reads the inventory when the prices moved", async () => {
    api.apiPost.mockRejectedValue(new SessionApiError(409, "Conflict", { code: "prices_changed" }));
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за/ })));
    expect(await screen.findAllByText(/Цены обновились/)).not.toHaveLength(0);
    await waitFor(() => {
      expect(api.apiGet).toHaveBeenCalledWith("/api/v1/sell/inventory?refresh=1");
    });
  });

  it("mints a new key after a refusal, and keeps it after a lost answer", async () => {
    api.apiPost
      .mockRejectedValueOnce(new SessionApiError(503, "Unavailable", { code: "sales_unavailable" }))
      .mockRejectedValueOnce(new Error("network"))
      .mockRejectedValueOnce(new Error("network"));
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    const sell = async () => {
      fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за/ })));
      await waitFor(() => {
        expect(screen.getAllByRole("button", { name: /Продать за/ })[0]).toBeEnabled();
      });
    };
    await sell();
    await sell();
    await sell();
    const keys = api.apiPost.mock.calls.map(
      (c) => (c[2] as { idempotencyKey: string }).idempotencyKey,
    ); // test: the options shape is known
    expect(keys[1]).not.toBe(keys[0]);
    expect(keys[2]).toBe(keys[1]);
  });

  it("explains a Steam refusal of the account", async () => {
    routeGets(() =>
      Promise.reject(
        new SessionApiError(409, "Conflict", { code: "steam_refused", reason: "profile_private" }),
      ),
    );
    view();
    expect(await screen.findByText(/Профиль Steam скрыт/)).toBeInTheDocument();
  });

  it("checks a new card's number against its type", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("radio", { name: /Новая карта Humo/ })));
    fireEvent.change(first(screen.getAllByLabelText(/Номер карты Humo/)), {
      target: { value: "8600 1234 5678 9012" },
    });
    expect(screen.getAllByText("Это не карта Humo")[0]).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Продать за/ })[0]).toBeDisabled();
  });

  it("a typo in a full number asks to check it, not that it is another card", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("radio", { name: /Новая карта Humo/ })));
    fireEvent.change(first(screen.getAllByLabelText(/Номер карты Humo/)), {
      target: { value: "9860 1234 5678 9016" },
    });
    expect(screen.getAllByText("Номер карты с ошибкой — проверьте цифры.")[0]).toBeInTheDocument();
    expect(screen.queryByText("Это не карта Humo")).toBeNull();
  });

  it("after a refused card sale, re-reads the cards and pays to the one now saved", async () => {
    let saved = false;
    routeGets(undefined, () => Promise.resolve({ items: saved ? [SAVED_HUMO] : [] }));
    api.apiPost.mockImplementation(() => {
      saved = true;
      return Promise.reject(new SessionApiError(409, "Conflict", { code: "prices_changed" }));
    });
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("radio", { name: /Новая карта Humo/ })));
    fireEvent.change(first(screen.getAllByLabelText(/Номер карты Humo/)), {
      target: { value: HUMO },
    });
    const before = cardCalls();
    fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за/ })));
    await waitFor(() => {
      expect(cardCalls()).toBeGreaterThan(before);
    });
    await waitFor(() => {
      expect(first(screen.getAllByRole("radio", { name: /Humo •••• 9015/ }))).toHaveAttribute(
        "aria-checked",
        "true",
      );
    });
    expect(screen.queryAllByLabelText(/Номер карты Humo/)).toHaveLength(0);
  });

  it("a saved card deleted elsewhere: says so, re-reads the cards, falls back to the balance", async () => {
    let gone = false;
    routeGets(undefined, () => Promise.resolve({ items: gone ? [] : [SAVED_HUMO] }));
    api.apiPost.mockImplementation(() => {
      gone = true;
      return Promise.reject(new SessionApiError(404, "Not Found", null));
    });
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(await screen.findAllByRole("radio", { name: /Humo •••• 9015/ })));
    fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за/ })));
    expect(await screen.findAllByText("Этой карты больше нет — выберите другую.")).not.toHaveLength(
      0,
    );
    await waitFor(() => {
      expect(screen.queryAllByRole("radio", { name: /Humo •••• 9015/ })).toHaveLength(0);
    });
    expect(first(screen.getAllByRole("radio", { name: /Баланс csmarket/ }))).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("a minimum refused by the API says the minimum sum", async () => {
    api.apiPost.mockRejectedValue(
      new SessionApiError(409, "Conflict", { code: "below_minimum", min_sum_uzs: "11300" }),
    );
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за/ })));
    expect(await screen.findAllByText(/Минимальная сумма продажи — 11\s300/)).not.toHaveLength(0);
  });

  it("a Steam refusal at the sale names the account's problem", async () => {
    api.apiPost.mockRejectedValue(
      new SessionApiError(409, "Conflict", { code: "steam_refused", reason: "trade_banned" }),
    );
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    fireEvent.click(first(screen.getAllByRole("button", { name: /Продать за/ })));
    expect(await screen.findAllByText(/запрет обменов/)).not.toHaveLength(0);
  });

  it("says what happens after «Продать», per payout", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Redline/ }));
    expect(screen.getAllByText(/Примите обмен в Steam/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/на баланс через 7 дней/)[0]).toBeInTheDocument();
    fireEvent.click(first(screen.getAllByRole("radio", { name: /Новая карта Humo/ })));
    expect(
      screen.getAllByText(/поступят на карту в течение 12 часов после 7 дней защиты Steam/)[0],
    ).toBeInTheDocument();
  });

  it("links to the seller's sales", async () => {
    view();
    await screen.findAllByText(/Redline/);
    expect(screen.getByRole("link", { name: "Мои продажи" })).toHaveAttribute(
      "href",
      "/account/trades?type=sales",
    );
  });

  it("«Выбрать все» under a filter keeps the items chosen outside it", async () => {
    view();
    fireEvent.click(await screen.findByRole("button", { name: /Sand Dune/ }));
    fireEvent.change(screen.getByPlaceholderText("Поиск по названию"), {
      target: { value: "Redline" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Выбрать все" }));
    expect(screen.getAllByText(/Выбрано 2 скина/)[0]).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Снять выбор" })).toBeInTheDocument();
  });

  describe("an inventory refusal says what to do", () => {
    const refuse = (body: Record<string, unknown>, status = 409) => {
      routeGets(() => Promise.reject(new SessionApiError(status, "Refused", body)));
    };

    it("a bad trade link: the reason, the link form to change it, no retry", async () => {
      auth.value = {
        ...SIGNED_IN,
        user: { ...SIGNED_IN.user, trade_link_verdict: "warn", trade_link_reason: "hold" },
      };
      refuse({ code: "trade_link_bad", reason: "hold" });
      view();
      expect(await screen.findByText(/временный запрет обменов/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Изменить/ })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Повторить" })).toBeNull();
    });

    it("selling switched off: closed for now, no retry", async () => {
      refuse({ code: "sales_disabled" });
      view();
      expect(await screen.findByText(/Выкуп скинов временно недоступен/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Повторить" })).toBeNull();
    });

    it.each([
      ["rate_unavailable", 503, /Курс валюты сейчас недоступен/],
      ["sales_unavailable", 503, /Попробуйте через минуту/],
    ])("%s: says so, with a retry", async (code, status, text) => {
      refuse({ code }, status);
      view();
      expect(await screen.findByText(text)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
    });
  });
});
