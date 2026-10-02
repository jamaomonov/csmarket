import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QUOTE } from "./fixtures";
import { OverrideCard } from "./OverrideCard";

const api = vi.hoisted(() => ({
  getPricing: vi.fn(),
  savePricing: vi.fn(),
  previewPrice: vi.fn(),
  findPricedItems: vi.fn(),
  saveItemPricing: vi.fn(),
}));
vi.mock("./api", () => api);

const ITEM = {
  slug: "awp-asiimov-ft",
  name: "AWP | Asiimov (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AWP",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  image_url: null,
  active: true,
  hidden: false,
  price_usd: "57.10",
  count: 9,
  cost_usd: "50",
  margin_override_pp: null,
  fixed_price_usd: null,
};

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <OverrideCard />
    </QueryClientProvider>,
  );
}

async function pick(): Promise<void> {
  fireEvent.click(screen.getByLabelText("Только с ручной ценой"));
  fireEvent.click(await screen.findByRole("button", { name: /AWP \| Asiimov/ }));
}

describe("OverrideCard", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.findPricedItems.mockResolvedValue({ items: [ITEM] });
    api.previewPrice.mockResolvedValue({ ...QUOTE, price_usd: "60.00", price_uzs: "762000" });
  });

  it("lists only overridden items when asked", async () => {
    renderCard();
    await pick();
    expect(api.findPricedItems).toHaveBeenCalledWith(undefined, true);
  });

  it("saves a margin override for the chosen item with a key", async () => {
    api.saveItemPricing.mockResolvedValue({ ...ITEM, margin_override_pp: "10" });
    renderCard();
    await pick();
    fireEvent.change(screen.getByLabelText("Наценка, п.п."), { target: { value: "10" } });
    expect(await screen.findByText(/Будет продаваться за \$60\.00/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить цену" }));
    await waitFor(() => {
      expect(api.saveItemPricing).toHaveBeenCalledTimes(1);
    });
    const [slug, body, key] = api.saveItemPricing.mock.calls[0] as [string, unknown, string];
    expect(slug).toBe("awp-asiimov-ft");
    expect(body).toEqual({ margin_override_pp: "10", fixed_price_usd: null });
    expect(key.length).toBeGreaterThanOrEqual(16);
  });

  it("clears the manual price by sending nulls", async () => {
    api.saveItemPricing.mockResolvedValue(ITEM);
    renderCard();
    await pick();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить ручную цену" }));
    await waitFor(() => {
      expect(api.saveItemPricing).toHaveBeenCalledTimes(1);
    });
    expect(api.saveItemPricing.mock.calls[0]?.[1]).toEqual({
      margin_override_pp: null,
      fixed_price_usd: null,
    });
  });
});
