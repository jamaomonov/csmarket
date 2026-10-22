import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAYOUT_DETAIL } from "./fixtures";
import { PayoutActions } from "./PayoutActions";
import { type PayoutDetail } from "./payoutsApi";

import { useAuthStore } from "@/features/auth/authStore";

vi.mock("./payoutsApi", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  markPaid: vi.fn(),
  rejectPayout: vi.fn(),
  cancelPayout: vi.fn(),
  undoPayout: vi.fn(),
}));

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const wrap = (node: ReactNode) => <QueryClientProvider client={qc}>{node}</QueryClientProvider>;

const REVERTED: PayoutDetail = {
  ...PAYOUT_DETAIL,
  can_cancel: true,
  paid_needs_override: true,
  request: { ...PAYOUT_DETAIL.request, flags: ["rolled_back"] },
};

describe("PayoutActions", () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: "admin",
      me: { id: "admin-1", display_name: "Owner", roles: ["admin"] },
    });
  });

  it("closes an open «Отклонить» when a refetch says the trade was reverted", () => {
    const { rerender } = render(wrap(<PayoutActions detail={PAYOUT_DETAIL} onStale={vi.fn()} />));
    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }));
    expect(screen.getByRole("button", { name: "Да, отклонить" })).toBeInTheDocument();
    rerender(wrap(<PayoutActions detail={REVERTED} onStale={vi.fn()} />));
    expect(screen.queryByRole("button", { name: "Да, отклонить" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Подтверждение" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Отклонить" })).toBeNull();
  });

  it("keeps «Отменить (откат)» in the sticky decision bar", () => {
    render(wrap(<PayoutActions detail={REVERTED} onStale={vi.fn()} />));
    const bar = screen.getByTestId("decision-bar");
    expect(within(bar).getByRole("button", { name: "Отменить (откат)" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Выплачено" })).toBeInTheDocument();
  });

  it("still offers the cancel when the request can no longer be paid", () => {
    render(wrap(<PayoutActions detail={{ ...REVERTED, can_decide: false }} onStale={vi.fn()} />));
    expect(screen.getByRole("button", { name: "Отменить (откат)" })).toBeInTheDocument();
  });
});
