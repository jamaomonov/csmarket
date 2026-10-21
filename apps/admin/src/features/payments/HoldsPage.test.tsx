import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type Hold } from "./api";
import { HoldsPage } from "./HoldsPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ getHolds: vi.fn(), decideHold: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const OPEN: Hold = {
  id: "h1",
  number: "TU-0001",
  kind: "topup",
  provider: "payme",
  amount_uzs: "1500000",
  reason: "kassa_limit",
  window_sum_uzs: "2500000",
  limit_uzs: "2000000",
  user: { id: "u1", display_name: "Aziz" },
  created_at: "2026-10-21T10:00:00Z",
  decision: null,
  decided_by: null,
  decided_at: null,
};
const DECIDED: Hold = {
  ...OPEN,
  id: "h2",
  number: "TU-0002",
  decision: "released",
  decided_by: { id: "a1", display_name: "Owner" },
  decided_at: "2026-10-21T11:00:00Z",
};

function firstButton(name: string): HTMLElement {
  const found = screen.getAllByRole("button", { name })[0];
  if (found === undefined) throw new Error(`no button ${name}`);
  return found;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HoldsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HoldsPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getHolds.mockImplementation((state: string) =>
      Promise.resolve({ items: state === "open" ? [OPEN] : [DECIDED], next_cursor: null }),
    );
    api.decideHold.mockResolvedValue(DECIDED);
  });

  it("lists an open hold with its reason, amount and user link", async () => {
    renderPage();
    expect(await screen.findByText("TU-0001")).toBeInTheDocument();
    expect(screen.getAllByText("Лимит кассы").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1\s500\s000\sсум/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Aziz" })[0]).toHaveAttribute("href", "/users/u1");
    expect(api.getHolds).toHaveBeenCalledWith("open", null);
  });

  it("releases after a confirm and the row leaves the list", async () => {
    renderPage();
    await screen.findByText("TU-0001");
    api.getHolds.mockResolvedValue({ items: [], next_cursor: null });
    fireEvent.click(firstButton("Пропустить"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Пропустить платёж TU-0001?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Пропустить" }));
    await waitFor(() => {
      expect(api.decideHold).toHaveBeenCalledOnce();
    });
    const [id, act, key] = api.decideHold.mock.calls[0] as [string, string, string];
    expect([id, act]).toEqual(["h1", "release"]);
    expect(key).toMatch(/^admin-hold-release-/);
    await waitFor(() => {
      expect(screen.queryByText("TU-0001")).not.toBeInTheDocument();
    });
  });

  it("marks a card return after a confirm", async () => {
    renderPage();
    await screen.findByText("TU-0001");
    fireEvent.click(firstButton("Вернул на карту"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("На баланс ничего не зачислится");
    fireEvent.click(within(dialog).getByRole("button", { name: "Вернул на карту" }));
    await waitFor(() => {
      expect(api.decideHold).toHaveBeenCalledOnce();
    });
    expect(api.decideHold.mock.calls[0]?.slice(0, 2)).toEqual(["h1", "returned"]);
  });

  it("says the hold was already decided", async () => {
    api.decideHold.mockRejectedValue(new ApiError(409, "conflict", { code: "hold_decided" }));
    renderPage();
    await screen.findByText("TU-0001");
    fireEvent.click(firstButton("Пропустить"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Пропустить" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("уже решён");
  });

  it("the «Решённые» tab reads decided holds with who and what", async () => {
    renderPage();
    await screen.findByText("TU-0001");
    fireEvent.click(screen.getByRole("tab", { name: "Решённые" }));
    expect(await screen.findByText("TU-0002")).toBeInTheDocument();
    expect(api.getHolds).toHaveBeenCalledWith("decided", null);
    expect(screen.getAllByText(/Пропущен/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Owner/).length).toBeGreaterThan(0);
  });
});
