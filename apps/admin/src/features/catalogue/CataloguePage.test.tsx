import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CataloguePage } from "./CataloguePage";

const api = vi.hoisted(() => ({
  getStatus: vi.fn(),
  findItems: vi.fn(),
  setHidden: vi.fn(),
  listAliases: vi.fn(),
  putAlias: vi.fn(),
  deleteAlias: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CataloguePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ITEM = {
  slug: "ak-47-redline-ft",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  image_url: null,
  active: true,
  hidden: false,
  price_usd: "10.00",
  count: 5,
};

describe("CataloguePage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getStatus.mockResolvedValue({
      items_total: 35000,
      items_active: 21000,
      items_hidden: 3,
      prices_updated_at: "2026-10-01T10:00:00Z",
      import_job: {
        finished_at: "2026-10-01T03:00:00Z",
        ok: true,
        counters: { files: 11, rows: 35000, changed: 12 },
        error: null,
      },
      price_sync_job: {
        finished_at: "2026-10-01T10:00:00Z",
        ok: false,
        counters: {},
        error: "thin_snapshot",
      },
      fx: { usd_uzs: "12700.0000", fetched_at: "2026-10-01T09:00:00Z", source: "cbu" },
      sync_enabled: true,
      waxpeer_key_set: true,
    });
    api.findItems.mockResolvedValue({ items: [ITEM] });
    api.listAliases.mockResolvedValue({ items: [{ alias: "ак", text: "ak-47" }] });
  });

  it("shows counts, job outcomes and the rate", async () => {
    renderPage();
    expect(await screen.findByText(/21\s000/)).toBeInTheDocument();
    expect(screen.getByText(/Цены не обновились/)).toBeInTheDocument(); // price_sync_job.ok === false
    expect(screen.getByText(/12\s700/)).toBeInTheDocument();
  });

  it("hides an item", async () => {
    api.setHidden.mockResolvedValue({ ...ITEM, hidden: true });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Найти скин"), { target: { value: "redline" } });
    fireEvent.click(await screen.findByRole("button", { name: "Скрыть" }));
    await waitFor(() => {
      expect(api.setHidden).toHaveBeenCalledWith("ak-47-redline-ft", true);
    });
  });

  it("adds an alias", async () => {
    api.putAlias.mockResolvedValue({ alias: "редлайн", text: "redline" });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Как ищут"), { target: { value: "редлайн" } });
    fireEvent.change(screen.getByLabelText("Что найти"), { target: { value: "redline" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await waitFor(() => {
      expect(api.putAlias).toHaveBeenCalledWith("редлайн", "redline");
    });
  });

  it("deletes an alias", async () => {
    api.deleteAlias.mockResolvedValue(undefined);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    await waitFor(() => {
      expect(api.deleteAlias).toHaveBeenCalledWith("ак");
    });
  });

  it("lists hidden items without a query and offers to show them", async () => {
    api.findItems.mockResolvedValue({ items: [{ ...ITEM, hidden: true }] });
    api.setHidden.mockResolvedValue(ITEM);
    renderPage();
    fireEvent.click(await screen.findByLabelText("Только скрытые"));
    fireEvent.click(await screen.findByRole("button", { name: "Показать" }));
    await waitFor(() => {
      expect(api.setHidden).toHaveBeenCalledWith("ak-47-redline-ft", false);
    });
    expect(api.findItems).toHaveBeenCalledWith({ hidden: true });
  });
});
