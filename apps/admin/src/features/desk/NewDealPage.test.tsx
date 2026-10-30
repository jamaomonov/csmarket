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
}));
vi.mock("./api", () => api);
vi.mock("@/features/catalogue/SkinSearch", () => ({ SkinSearch: () => null }));

/** A `<p>` whose whole text matches — the sums sit in their own spans. */
function para(re: RegExp) {
  return (_: string, el: Element | null) => el?.tagName === "P" && re.test(el.textContent);
}

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

describe("NewDealPage", () => {
  beforeEach(() => {
    api.getRate.mockReset().mockResolvedValue({ usd_uzs: "13000" });
    api.loadInventory.mockReset().mockResolvedValue({
      items: [
        {
          asset_id: "100",
          name: "AK-47 | Redline (Field-Tested)",
          image_url: "https://img.test/100.png",
          price_usd: "800",
        },
        {
          asset_id: "101",
          name: "AWP | Asiimov (Field-Tested)",
          image_url: null,
          price_usd: "400",
        },
      ],
    });
    api.createDeal.mockReset().mockResolvedValue(deal());
  });

  it("posts the checked skins with their destinations and the soʻm price at the rate", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "trader one" } });
    fireEvent.change(screen.getByLabelText("Трейд-ссылка"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
    const inv = await screen.findByRole("list", { name: "Инвентарь трейдера" });
    expect(within(inv).queryAllByRole("radio")).toEqual([]); // the switch shows once ticked
    // Skinslink's dollars also in soʻm at the CBU rate (800 × 13 000), in brackets
    expect(await within(inv).findByText(/10\s400\s000/)).toBeInTheDocument();
    fireEvent.click(within(inv).getByText("AK-47 | Redline (Field-Tested)")); // the whole row ticks
    fireEvent.click(within(inv).getByRole("checkbox", { name: "AWP | Asiimov (Field-Tested)" }));
    const [, second] = within(inv).getAllByRole("radio", { name: "Себе" });
    if (second) fireEvent.click(second);
    expect(
      screen.getByText(para(/Skinslink сейчас даст за отмеченное: \$1\s200/)),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Сколько заплачено, сум"), {
      target: { value: "14 300 000" },
    });
    await waitFor(() => {
      expect(screen.getByLabelText("Курс (ЦБ на сегодня)")).toHaveValue("13000");
    });
    expect(screen.getByRole("region", { name: "Итог сделки" })).toHaveTextContent("2 скина");
    expect(
      screen.getByText(para(/Прибыль, если Skinslink заплатит как сейчас: \+?\$100/)),
    ).toBeInTheDocument();
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

  it("a soʻm price without a rate cannot be saved", async () => {
    api.getRate.mockResolvedValue({ usd_uzs: null });
    renderPage();
    fireEvent.change(screen.getByLabelText("Трейдер"), { target: { value: "t" } });
    fireEvent.change(screen.getByLabelText("Трейд-ссылка"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
    const inv = await screen.findByRole("list", { name: "Инвентарь трейдера" });
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
    fireEvent.change(screen.getByLabelText("Трейд-ссылка"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Загрузить инвентарь" }));
    fireEvent.change(await screen.findByLabelText("Найти в инвентаре"), {
      target: { value: "karambit" },
    });
    const inv = screen.getByRole("list", { name: "Инвентарь трейдера" });
    expect(within(inv).getAllByRole("checkbox")).toHaveLength(1);
  });
});
