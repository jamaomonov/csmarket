import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UsersPage } from "./UsersPage";

const api = vi.hoisted(() => ({
  listUsers: vi.fn(),
  getUserCard: vi.fn(),
  banUser: vi.fn(),
  unbanUser: vi.fn(),
  adjustBalance: vi.fn(),
}));
vi.mock("./api", () => api);

// Fake 17-digit IDs; never a real account.
const ROW = {
  id: "u-1",
  display_name: "Ivan",
  avatar_url: null,
  steam_id: "76561190000000001",
  roles: [],
  banned_at: null,
  created_at: "2026-09-30T10:00:00Z",
  balance_uzs: "70000",
  api_key: null,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("UsersPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("lists users with balance, role and the ban badge", async () => {
    api.listUsers.mockResolvedValue({
      items: [
        ROW,
        {
          ...ROW,
          id: "u-2",
          display_name: "Boss",
          steam_id: "76561190000000002",
          roles: ["admin"],
          banned_at: null,
        },
        {
          ...ROW,
          id: "u-3",
          display_name: null,
          steam_id: "76561190000000003",
          banned_at: "2026-09-30T12:00:00Z",
        },
      ],
      next_cursor: null,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: "Ivan" });
    expect(link).toHaveAttribute("href", "/users/u-1");
    const row = link.closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText(/70\s000 сум/)).toBeInTheDocument();
    expect(screen.getByText("администратор")).toBeInTheDocument();
    expect(screen.getByText("заблокирован")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Без имени" })).toHaveAttribute("href", "/users/u-3");
    expect(api.listUsers).toHaveBeenCalledWith({});
  });

  it("searches by name or Steam ID", async () => {
    api.listUsers.mockResolvedValue({ items: [ROW], next_cursor: null });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Имя или Steam ID"), {
      target: { value: "  ivan " },
    });
    await waitFor(() => {
      expect(api.listUsers).toHaveBeenCalledWith({ q: "ivan" });
    });
  });

  it("loads the next page behind «Показать ещё»", async () => {
    api.listUsers
      .mockResolvedValueOnce({ items: [ROW], next_cursor: "c-2" })
      .mockResolvedValueOnce({
        items: [{ ...ROW, id: "u-9", display_name: "Older", steam_id: "76561190000000009" }],
        next_cursor: null,
      });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByRole("link", { name: "Older" })).toBeInTheDocument();
    expect(api.listUsers).toHaveBeenLastCalledWith({ cursor: "c-2" });
    expect(screen.queryByRole("button", { name: "Показать ещё" })).not.toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    api.listUsers.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    expect(await screen.findByText("Никого не нашли.")).toBeInTheDocument();
  });
});
