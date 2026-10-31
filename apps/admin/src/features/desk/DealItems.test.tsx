import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DealPage } from "./DealPage";
import { deal, item } from "./fixtures";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  DESK_KEY: ["admin", "desk"],
  getDeal: vi.fn(),
  patchDeal: vi.fn(),
  sendDeposit: vi.fn(),
  sellItem: vi.fn(),
  moveItem: vi.fn(),
  writeOff: vi.fn(),
  getRate: vi.fn(),
  addItems: vi.fn(),
  removeItem: vi.fn(),
  undoItem: vi.fn(),
  loadInventory: vi.fn(),
  listTraders: vi.fn(),
}));
vi.mock("./api", () => api);
vi.mock("@/features/catalogue/SkinSearch", () => ({ SkinSearch: () => null }));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/desk/deals/d1"]}>
        <Routes>
          <Route path="/desk/deals/:id" element={<DealPage />} />
          <Route path="/desk" element={<p>desk list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function confirm() {
  return screen.getByRole("group", { name: "Подтверждение" });
}

describe("DealPage: skins", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => {
      if (typeof f === "function") f.mockReset();
    });
    api.getDeal.mockResolvedValue(deal());
    api.getRate.mockResolvedValue({ usd_uzs: "13000" });
    api.listTraders.mockResolvedValue({ items: [] });
  });

  it("moves an item to stock", async () => {
    api.moveItem.mockResolvedValue(deal());
    renderPage();
    const [first] = await screen.findAllByRole("radio", { name: "Себе" });
    if (first) fireEvent.click(first);
    await waitFor(() => {
      expect(api.moveItem).toHaveBeenCalledWith("i1", "stock");
    });
  });

  it("keeps the price form open when the save fails", async () => {
    api.patchDeal.mockRejectedValue(new ApiError(409, "Conflict", { code: "price_locked" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Изменить цену" }));
    fireEvent.change(screen.getByLabelText("Сколько заплачено, $"), { target: { value: "1200" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить цену" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Цену уже не изменить");
    expect(screen.getByRole("button", { name: "Сохранить цену" })).toBeInTheDocument();
  });

  it("removes an open skin after asking", async () => {
    api.removeItem.mockResolvedValue(deal({ items: [item({ id: "i2" })] }));
    renderPage();
    const [menu] = await screen.findAllByRole("button", { name: /Ещё: / });
    if (menu) fireEvent.click(menu);
    fireEvent.click(screen.getByRole("menuitem", { name: "Убрать из сделки" }));
    expect(api.removeItem).not.toHaveBeenCalled();
    fireEvent.click(within(confirm()).getByRole("button", { name: "Убрать" }));
    await waitFor(() => {
      expect(api.removeItem).toHaveBeenCalledWith("i1");
    });
  });

  it("shows a sold skin's profit and undoes the sale after asking", async () => {
    api.getDeal.mockResolvedValue(
      deal({
        items: [
          item({
            destination: "stock",
            state: "sold",
            cost_usd: "54",
            sold_usd: "70",
            sold_where: "Buff",
          }),
        ],
      }),
    );
    api.undoItem.mockResolvedValue(deal());
    renderPage();
    const skins = await screen.findByRole("list", { name: "Скины" });
    expect(skins).toHaveTextContent("+$16.00");
    fireEvent.click(within(skins).getByRole("button", { name: "Отменить продажу" }));
    fireEvent.click(within(confirm()).getByRole("button", { name: "Отменить продажу" }));
    await waitFor(() => {
      expect(api.undoItem).toHaveBeenCalledWith("i1");
    });
  });

  it("adds skins from the trader's inventory", async () => {
    api.loadInventory.mockResolvedValue({
      items: [
        {
          asset_id: "100",
          name: "AK-47 | Redline (Field-Tested)",
          image_url: null,
          price_usd: "800",
        },
        {
          asset_id: "200",
          name: "M4A1-S | Printstream",
          image_url: "https://img.test/p.png",
          price_usd: "90",
        },
      ],
    });
    api.addItems.mockResolvedValue(deal());
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Добавить скин" }));
    fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
    const inv = await screen.findByRole("list", { name: "Инвентарь трейдера" });
    // A skin already in the deal is not offered again.
    expect(within(inv).getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.click(within(inv).getByRole("checkbox", { name: "M4A1-S | Printstream" }));
    fireEvent.click(screen.getByRole("button", { name: "Добавить 1 скин" }));
    await waitFor(() => {
      expect(api.addItems).toHaveBeenCalledWith("d1", [
        {
          name: "M4A1-S | Printstream",
          asset_id: "200",
          image_url: "https://img.test/p.png",
          skinslink_usd: "90",
          destination: "skinslink",
        },
      ]);
    });
  });
});
