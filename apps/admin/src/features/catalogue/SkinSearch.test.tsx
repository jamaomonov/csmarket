import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { type AdminSkinItem } from "./api";
import { SkinSearch } from "./SkinSearch";

function item(slug: string, name: string, over: Partial<AdminSkinItem> = {}): AdminSkinItem {
  return {
    slug,
    name,
    phase: null,
    category: "rifles",
    weapon: "AK-47",
    exterior: "FT",
    stattrak: false,
    souvenir: false,
    image_url: null,
    active: true,
    hidden: false,
    price_usd: "27.38",
    count: 12,
    ...over,
  };
}

const FT = item("ak-ft", "AK-47 | Redline (Field-Tested)");
const MW = item("ak-mw", "AK-47 | Redline (Minimal Wear)", { price_usd: null, count: 0 });

function renderSearch(onPick = vi.fn()) {
  const find = vi.fn().mockResolvedValue({ items: [FT, MW] });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SkinSearch find={find} onPick={onPick} />
    </QueryClientProvider>,
  );
  return { find, onPick, input: screen.getByRole("combobox", { name: "Найти скин" }) };
}

describe("SkinSearch", () => {
  it("passes what was typed as is, pipe and star included", async () => {
    const { find, input } = renderSearch();
    fireEvent.change(input, { target: { value: "★ AK-47 | Redline" } });
    expect(await screen.findByRole("option", { name: /Field-Tested/ })).toBeInTheDocument();
    expect(find).toHaveBeenCalledWith("★ AK-47 | Redline");
  });

  it("shows price and stock, or that the skin is not on sale", async () => {
    const { input } = renderSearch();
    fireEvent.change(input, { target: { value: "redline" } });
    expect(await screen.findByText("$27.38 · 12 шт.")).toBeInTheDocument();
    expect(screen.getByText("нет в продаже · 0 шт.")).toBeInTheDocument();
  });

  it("picks with the arrows and Enter, then clears", async () => {
    const { input, onPick } = renderSearch();
    fireEvent.change(input, { target: { value: "redline" } });
    await screen.findByRole("option", { name: /Minimal Wear/ });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith(MW);
    expect(input).toHaveValue("");
  });

  it("says when nothing matched", async () => {
    const { find, input } = renderSearch();
    find.mockResolvedValue({ items: [] });
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(await screen.findByText(/Ничего не нашлось/)).toBeInTheDocument();
  });
});
