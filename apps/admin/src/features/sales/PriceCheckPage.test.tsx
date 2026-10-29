import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PriceCheckPage } from "./PriceCheckPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ checkSalePrices: vi.fn() }));
vi.mock("./priceCheckApi", () => api);

const RESULT = {
  items: [
    {
      name: "AK-47 | Redline (Field-Tested)",
      image_url: null,
      skinslink_usd: "12.45",
      original_usd: "14.1",
      price_uzs: "149600",
      margin_usd: "0.62",
    },
  ],
  missing: ["Nope | Gone"],
  totals: {
    skinslink_usd: "12.45",
    items_uzs: "149600",
    balance_uzs: "152500",
    card_uzs: { uzcard: "142100", humo: "142100", uzum_visa: "142100" },
    margin_usd: "0.62",
  },
  rate: "12650.5",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PriceCheckPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PriceCheckPage", () => {
  beforeEach(() => {
    api.checkSalePrices.mockReset();
  });

  it("checks names one per line and shows prices, totals and what is not bought", async () => {
    api.checkSalePrices.mockResolvedValue(RESULT);
    renderPage();
    fireEvent.change(screen.getByLabelText(/Market hash name/), {
      target: { value: " AK-47 | Redline (Field-Tested) \n\nNope | Gone" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));
    await waitFor(() => {
      expect(api.checkSalePrices).toHaveBeenCalledWith({
        names: ["AK-47 | Redline (Field-Tested)", "Nope | Gone"],
      });
    });
    expect(await screen.findByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
    expect(screen.getByText(/без множителей/)).toBeInTheDocument();
    expect(screen.getByText("Nope | Gone")).toBeInTheDocument();
    expect(screen.getByLabelText("Итоги")).toHaveTextContent("На баланс (с бонусом)");
  });

  it("loads a trade link's inventory", async () => {
    api.checkSalePrices.mockResolvedValue({ ...RESULT, missing: [] });
    renderPage();
    const link = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abc";
    fireEvent.change(screen.getByLabelText("Трейд-ссылка Steam"), { target: { value: link } });
    fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
    await waitFor(() => {
      expect(api.checkSalePrices).toHaveBeenCalledWith({ trade_link: link });
    });
  });

  it("says why Steam refused", async () => {
    api.checkSalePrices.mockRejectedValue(
      new ApiError(409, "Conflict", { code: "steam_refused", reason: "profile_private" }),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейд-ссылка Steam"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("профиль или инвентарь закрыт");
  });
});
