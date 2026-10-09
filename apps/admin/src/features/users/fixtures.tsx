/** Shared fixtures for the user-card tests. Fake IDs only; never a real account. */
import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { type AdminUserCard } from "./api";
import { UserCard } from "./UserCard";
import { ORDER_ROW } from "../orders/fixtures";

// Fake IDs and a fake, already-masked trade link; never a real account.
export const STEAM_ID = "76561190000000001";
export const CARD: AdminUserCard = {
  user: {
    id: "u-1",
    steam_id: STEAM_ID,
    display_name: "Ivan",
    avatar_url: null,
    email: "ivan@example.test",
    locale: "uz",
    roles: [],
    banned_at: null,
    ban_reason: null,
    created_at: "2026-09-01T10:00:00Z",
    trade_link_masked: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••zz",
    trade_link_verdict: "warn",
    trade_link_reason: "hold",
    trade_link_checked_at: "2026-09-30T10:00:00Z",
  },
  balance_uzs: "30000",
  entries: [
    {
      id: "e-2",
      kind: "admin_adjust",
      currency: "UZS",
      amount_usd: null,
      amount_uzs: "-20000",
      created_at: "2026-09-30T11:00:00Z",
      reference_number: null,
      actor: "admin:a-1",
      reason: "Ошибочное начисление",
    },
    {
      id: "e-1",
      kind: "topup",
      currency: "UZS",
      amount_usd: null,
      amount_uzs: "+50000",
      created_at: "2026-09-30T10:00:00Z",
      reference_number: "T100001",
      actor: "payments",
      reason: null,
    },
  ],
  topups: [
    {
      number: "T100001",
      amount_uzs: "50000",
      status: "succeeded",
      provider: "click",
      created_at: "2026-09-30T09:55:00Z",
      succeeded_at: "2026-09-30T10:00:00Z",
    },
  ],
  orders: [ORDER_ROW],
  usd_wallet_enabled: false,
  balance_usd: "0.000",
  api_key_id: null,
  usd_entries: [],
};

export function renderCard(qc: QueryClient, seed?: (qc: QueryClient) => void) {
  seed?.(qc);
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/users/u-1"]}>
        <Routes>
          <Route path="/users/:id" element={<UserCard />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
