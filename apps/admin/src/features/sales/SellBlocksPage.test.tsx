import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SellBlocksPage } from "./SellBlocksPage";

const api = vi.hoisted(() => ({ listSellBlocks: vi.fn(), setSellBlock: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

describe("SellBlocksPage", () => {
  beforeEach(() => {
    api.listSellBlocks.mockReset().mockResolvedValue({
      items: [
        {
          user: { id: "u-1", display_name: "Ivan" },
          blocked: true,
          reason: "one card, five accounts",
          blocked_by: { id: "a-1", display_name: "Owner" },
          blocked_at: "2026-10-12T10:00:00Z",
        },
      ],
    });
    api.setSellBlock.mockReset().mockResolvedValue({});
  });

  it("an empty list leads to the payouts, where blocks are made", async () => {
    api.listSellBlocks.mockResolvedValue({ items: [] });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <SellBlocksPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Никому не запрещено.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Заявки на выплату" })).toHaveAttribute(
      "href",
      "/payouts",
    );
  });

  it("lists the blocked users and lifts a block", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <SellBlocksPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "Ivan" })).toHaveAttribute("href", "/users/u-1");
    expect(screen.getByText("one card, five accounts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Разрешить" }));
    await waitFor(() => {
      expect(api.setSellBlock).toHaveBeenCalledWith(
        "u-1",
        false,
        null,
        expect.stringMatching(/^admin-sell-unblock-/),
      );
    });
  });
});
