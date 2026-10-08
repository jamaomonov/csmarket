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

function routeGets(inventory: () => Promise<unknown> = () => Promise.resolve(INVENTORY)) {
  api.apiGet.mockImplementation((path: string) =>
    path.startsWith("/api/v1/sell/inventory")
      ? inventory()
      : path === "/api/v1/payout-cards"
        ? Promise.resolve({ items: [] })
        : Promise.reject(new Error(path)),
  );
}

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
});
