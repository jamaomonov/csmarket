// @vitest-environment jsdom
import ru from "@csmarket/i18n/locales/ru/web.json";
import { act, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SkinTradeCard } from "./SkinTradeCard";

import type { SkinTradeOut } from "@/lib/orders";
import type { ReactNode } from "react";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const base: SkinTradeOut = {
  state: "buying",
  reason_code: null,
  offer_url: null,
  send_until: null,
  release_date: null,
  seller: null,
  refunded_to: null,
};

// A made-up offer id.
const OFFER = "https://steamcommunity.com/tradeoffer/1000000001/";

function card(over: Partial<SkinTradeOut>) {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru }}>
      <SkinTradeCard trade={{ ...base, ...over }} locale="ru" />
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe("SkinTradeCard", () => {
  it("says the offer is on its way while buying", () => {
    card({});
    expect(screen.getByText("Обмен в Steam")).toBeInTheDocument();
    expect(
      screen.getByText("Покупаем скин — обмен придёт в Steam через минуту."),
    ).toBeInTheDocument();
  });

  it("links the sent offer, names the seller and says until when to accept", () => {
    card({
      state: "offer_sent",
      offer_url: OFFER,
      send_until: new Date(Date.now() + 25 * 60_000).toISOString(),
      seller: {
        name: "seller-one",
        avatar_url: "https://avatars.steamstatic.com/x.jpg",
        level: 12,
        joined_at: null,
      },
    });
    expect(screen.getByText("Обмен отправлен — примите его в Steam.")).toBeInTheDocument();
    const open = screen.getByRole("link", { name: "Открыть обмен в Steam" });
    expect(open).toHaveAttribute("href", OFFER);
    expect(open).toHaveAttribute("target", "_blank");
    expect(open).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Продавец")).toBeInTheDocument();
    expect(screen.getByText("seller-one")).toBeInTheDocument();
    expect(screen.getByText(/^Примите до \d{2}:\d{2}$/)).toBeInTheDocument();
  });

  it("re-renders every minute and drops the accept-by line once it has passed", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-02T10:00:00Z"));
    card({ state: "offer_sent", offer_url: OFFER, send_until: "2026-10-02T10:01:30Z" });
    expect(screen.getByText(/^Примите до/)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText(/^Примите до/)).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.queryByText(/^Примите до/)).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть обмен в Steam" })).toBeInTheDocument();
  });

  it("an offer without a link or seller yet still says it was sent", () => {
    card({ state: "offer_sent" });
    expect(screen.getByText("Обмен отправлен — примите его в Steam.")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText("Продавец")).toBeNull();
  });

  it("says received and until when Steam protects it", () => {
    card({ state: "accepted", release_date: "2026-10-09T16:00:00Z" });
    expect(screen.getByText("Получено")).toBeInTheDocument();
    expect(screen.getByText(/^Steam защищает обмен до 9 октября$/)).toBeInTheDocument();
  });

  it("a released trade reads received, with no protection line", () => {
    card({ state: "released", release_date: "2026-10-09T16:00:00Z" });
    expect(screen.getByText("Получено")).toBeInTheDocument();
    expect(screen.queryByText(/защищает/)).toBeNull();
  });

  it("says the money is back for a declined offer", () => {
    card({ state: "failed", reason_code: "not_accepted", refunded_to: "balance" });
    expect(
      screen.getByText("Обмен не состоялся — деньги вернулись на баланс."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть баланс" })).toHaveAttribute(
      "href",
      "/account/transactions",
    );
  });

  it("asks to try again later when the skin could not be bought", () => {
    card({ state: "failed", reason_code: "try_later", refunded_to: "balance" });
    expect(screen.getByText(/Попробуйте через несколько минут/)).toBeInTheDocument();
    expect(screen.queryByText(/Обмен не состоялся/)).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть баланс" })).toBeInTheDocument();
  });

  it("names the trade link when it was the reason, with the money on the balance", () => {
    card({ state: "failed", reason_code: "trade_link", refunded_to: "balance" });
    expect(
      screen.getByText("Трейд-ссылка не подошла — проверьте её в профиле. Деньги на балансе."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Обмен не состоялся/)).toBeNull();
    expect(screen.getByRole("link", { name: "Открыть баланс" })).toBeInTheDocument();
  });

  it("never says the money is on the balance for a link refusal without a refund", () => {
    card({ state: "failed", reason_code: "trade_link", refunded_to: null });
    expect(screen.queryByText(/Трейд-ссылка не подошла/)).toBeNull();
    expect(screen.queryByText(/Деньги на балансе/)).toBeNull();
    expect(
      screen.getByText("Мы проверяем покупку. Статус обновится на этой странице."),
    ).toBeInTheDocument();
  });

  it("does not promise a refund that has not landed", () => {
    card({ state: "failed", reason_code: "not_accepted", refunded_to: null });
    expect(screen.queryByText(/вернулись/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Открыть баланс" })).toBeNull();
    expect(
      screen.getByText("Мы проверяем покупку. Статус обновится на этой странице."),
    ).toBeInTheDocument();
  });

  it.each<[SkinTradeOut["state"]]>([["buying"], ["accepted"], ["failed"]])(
    "a purchase under review reads «мы проверяем» in state %s, and promises nothing",
    (state) => {
      card({
        state,
        reason_code: "support",
        offer_url: OFFER,
        send_until: new Date(Date.now() + 60_000).toISOString(),
        release_date: "2026-10-09T16:00:00Z",
      });
      expect(
        screen.getByText("Мы проверяем покупку. Статус обновится на этой странице."),
      ).toBeInTheDocument();
      expect(screen.queryByText(/вернулись/)).toBeNull();
      expect(screen.queryByText("Получено")).toBeNull();
      expect(screen.queryByText(/Покупаем скин/)).toBeNull();
      expect(screen.queryByRole("link", { name: "Открыть баланс" })).toBeNull();
    },
  );

  it("a purchase under review never hides an offer the buyer can accept", () => {
    card({
      state: "offer_sent",
      reason_code: "support",
      offer_url: OFFER,
      send_until: new Date(Date.now() + 25 * 60_000).toISOString(),
      seller: { name: "seller-one", avatar_url: null, level: null, joined_at: null },
    });
    expect(screen.getByText("Обмен отправлен — примите его в Steam.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть обмен в Steam" })).toHaveAttribute(
      "href",
      OFFER,
    );
    expect(screen.getByText(/^Примите до/)).toBeInTheDocument();
    expect(screen.getByText("seller-one")).toBeInTheDocument();
    expect(
      screen.getByText("Мы проверяем покупку. Статус обновится на этой странице."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/вернулись/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Открыть баланс" })).toBeNull();
  });

  it("an offer under review with no link yet reads «мы проверяем» only", () => {
    card({ state: "offer_sent", reason_code: "support" });
    expect(screen.getByText(/Мы проверяем покупку/)).toBeInTheDocument();
    expect(screen.queryByText(/Обмен отправлен/)).toBeNull();
  });

  it("a purchase under review that was refunded by hand says where the money went", () => {
    card({ state: "failed", reason_code: "support", refunded_to: "balance" });
    expect(screen.getByText(/Мы проверяем покупку/)).toBeInTheDocument();
    expect(
      screen.getByText("Обмен не состоялся — деньги вернулись на баланс."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть баланс" })).toBeInTheDocument();
  });
});
