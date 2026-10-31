import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { deal } from "./fixtures";
import { NewDealPage } from "./NewDealPage";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  getRate: vi.fn(),
  loadInventory: vi.fn(),
  createDeal: vi.fn(),
  listTraders: vi.fn(),
}));
vi.mock("./api", () => api);
vi.mock("@/features/catalogue/SkinSearch", () => ({
  SkinSearch: ({ onPick }: { onPick: (i: { name: string; image_url: string | null }) => void }) => (
    <button
      type="button"
      onClick={() => {
        onPick({ name: "M4A4 | Howl (Minimal Wear)", image_url: "https://img.test/howl.png" });
      }}
    >
      pick from catalogue
    </button>
  ),
}));

const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abc";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/desk/new"]}>
        <Routes>
          <Route path="/desk/new" element={<NewDealPage />} />
          <Route path="/desk/deals/:id" element={<p>deal page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function loadInventory() {
  fireEvent.change(screen.getByLabelText("Трейд-ссылка"), { target: { value: LINK } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
  return screen.findByRole("list", { name: "Инвентарь трейдера" });
}

describe("NewDealPage", () => {
  beforeEach(() => {
    api.getRate.mockReset().mockResolvedValue({ usd_uzs: "13000" });
    api.listTraders.mockReset().mockResolvedValue({ items: [] });
    api.loadInventory.mockReset().mockResolvedValue({
      items: [
        {
          asset_id: "101",
          name: "AWP | Asiimov (Field-Tested)",
          image_url: null,
          price_usd: "400",
        },
        {
          asset_id: "100",
          name: "AK-47 | Redline (Field-Tested)",
          image_url: "https://img.test/100.png",
          price_usd: "800",
        },
      ],
    });
    api.createDeal.mockReset().mockResolvedValue(deal());
  });

  it("posts the checked skins with their destinations and the soʻm price at the rate", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "trader one" } });
    const inv = await loadInventory();
    expect(within(inv).queryAllByRole("radio")).toEqual([]); // the switch shows once ticked
    // Dearest first.
    const boxes = within(inv).getAllByRole("checkbox");
    expect(boxes[0]).toHaveAccessibleName("AK-47 | Redline (Field-Tested)");
    // Skinslink's dollars also in soʻm at the CBU rate (800 × 13 000), in brackets
    expect(await within(inv).findByText(/10\s400\s000/)).toBeInTheDocument();
    fireEvent.click(within(inv).getByText("AK-47 | Redline (Field-Tested)")); // the whole row ticks
    fireEvent.click(within(inv).getByRole("checkbox", { name: "AWP | Asiimov (Field-Tested)" }));
    const [, second] = within(inv).getAllByRole("radio", { name: "Себе" });
    if (second) fireEvent.click(second);
    fireEvent.change(screen.getByLabelText("Сколько заплачено, сум"), {
      target: { value: "14 300 000" },
    });
    await waitFor(() => {
      expect(screen.getByLabelText("Курс (ЦБ на сегодня)")).toHaveValue("13000");
    });
    expect(screen.getByRole("region", { name: "Итог сделки" })).toHaveTextContent(
      "Заплачено $1 100.00 · Skinslink $1 200.00 · +$100.00",
    );
    fireEvent.click(screen.getByRole("button", { name: "Сохранить сделку" }));
    await waitFor(() => {
      expect(api.createDeal).toHaveBeenCalledTimes(1);
    });
    expect(api.createDeal.mock.calls[0]?.[0]).toEqual({
      trader: "trader one",
      trade_link: LINK,
      method: "direct",
      items: [
        {
          name: "AK-47 | Redline (Field-Tested)",
          asset_id: "100",
          image_url: "https://img.test/100.png",
          skinslink_usd: "800",
          destination: "skinslink",
        },
        {
          name: "AWP | Asiimov (Field-Tested)",
          asset_id: "101",
          skinslink_usd: "400",
          destination: "stock",
        },
      ],
      paid_amount: "14300000",
      paid_currency: "UZS",
      rate: "13000",
    });
    expect(await screen.findByText("deal page")).toBeInTheDocument();
  });

  it("suggests a known trader and fills the last trade link", async () => {
    api.listTraders.mockResolvedValue({
      items: [
        {
          trader: "Trader One",
          deals: 3,
          paid_usd: "3000",
          profit_usd: "250",
          reverts: 0,
          last_trade_link: LINK,
          last_deal_at: "2026-10-29T10:00:00Z",
        },
      ],
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "trad" } });
    fireEvent.click(await screen.findByRole("button", { name: /Trader One/ }));
    expect(screen.getByLabelText("Трейдер")).toHaveValue("Trader One");
    expect(screen.getByLabelText("Трейд-ссылка")).toHaveValue(LINK);
    expect(api.listTraders).toHaveBeenCalledWith("trad");
  });

  it("selects every skin at once and saves a guarantor deal", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "t" } });
    await loadInventory();
    fireEvent.click(screen.getByRole("button", { name: "Выбрать все" }));
    fireEvent.click(screen.getByRole("radio", { name: "через гаранта" }));
    fireEvent.change(screen.getByLabelText("Гарант"), { target: { value: "garant42" } });
    fireEvent.change(screen.getByLabelText("Заметка"), { target: { value: "из чата" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить сделку" }));
    await waitFor(() => {
      expect(api.createDeal).toHaveBeenCalledTimes(1);
    });
    const body = api.createDeal.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(body).toMatchObject({ method: "guarantor", guarantor: "garant42", note: "из чата" });
    expect(body.items).toHaveLength(2);
  });

  it("a catalogue skin keeps its picture and takes an estimate", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "t" } });
    fireEvent.click(screen.getByRole("button", { name: "pick from catalogue" }));
    fireEvent.change(screen.getByLabelText("Оценка M4A4 | Howl (Minimal Wear), $"), {
      target: { value: "1500" },
    });
    expect(screen.getByRole("region", { name: "Итог сделки" })).toHaveTextContent(
      "Skinslink $1 500.00",
    );
    fireEvent.click(screen.getByRole("button", { name: "Сохранить сделку" }));
    await waitFor(() => {
      expect(api.createDeal).toHaveBeenCalledTimes(1);
    });
    expect(api.createDeal.mock.calls[0]?.[0]).toMatchObject({
      items: [
        {
          name: "M4A4 | Howl (Minimal Wear)",
          image_url: "https://img.test/howl.png",
          skinslink_usd: "1500",
          destination: "stock",
        },
      ],
    });
  });

  it("a soʻm price without a rate cannot be saved", async () => {
    api.getRate.mockResolvedValue({ usd_uzs: null });
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "t" } });
    const inv = await loadInventory();
    const [box] = within(inv).getAllByRole("checkbox");
    if (box) fireEvent.click(box);
    fireEvent.change(screen.getByLabelText("Сколько заплачено, сум"), {
      target: { value: "1000000" },
    });
    await waitFor(() => {
      expect(api.getRate).toHaveBeenCalled();
    });
    expect(screen.getByRole("button", { name: "Сохранить сделку" })).toBeDisabled();
  });

  it("filters a long inventory by name", async () => {
    api.loadInventory.mockResolvedValue({
      items: Array.from({ length: 25 }, (_, n) => ({
        asset_id: String(n),
        name: n === 7 ? "★ Karambit | Doppler (Factory New)" : `Skin ${String(n)}`,
        image_url: null,
        price_usd: "1",
      })),
    });
    renderPage();
    await loadInventory();
    fireEvent.change(screen.getByLabelText("Найти в инвентаре"), {
      target: { value: "karambit" },
    });
    const inv = screen.getByRole("list", { name: "Инвентарь трейдера" });
    expect(within(inv).getAllByRole("checkbox")).toHaveLength(1);
  });
});
