"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { ENTRIES_KEY } from "@/components/balance/EntriesList";
import { API_BASE, session } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BALANCE_KEY } from "@/lib/balance";
import { orderKey, ORDERS_KEY } from "@/lib/orders";
import { OrderSocket, wsUrl } from "@/lib/realtime";

/** The access token, re-minted from the refresh cookie when memory has none. */
async function currentToken(): Promise<string | null> {
  const token = session.getAccessToken();
  if (token) return token;
  return (await session.refreshAccessToken()) ? session.getAccessToken() : null;
}

/**
 * Keep one order socket open while a buyer is signed in: a nudge re-reads that order, the
 * orders list, the balance and its entries. Polling on the order page stays as it was.
 */
export function useOrderSocket(): void {
  const { status, user } = useAuth();
  const qc = useQueryClient();
  const userId = status === "signed_in" ? (user?.id ?? null) : null;

  useEffect(() => {
    if (userId === null) return;
    const socket = new OrderSocket({
      url: wsUrl(API_BASE),
      getToken: currentToken,
      refreshToken: () => session.refreshAccessToken(),
      onChanged: (number) => {
        void qc.invalidateQueries({ queryKey: orderKey(number) });
        void qc.invalidateQueries({ queryKey: ORDERS_KEY });
        void qc.invalidateQueries({ queryKey: BALANCE_KEY });
        void qc.invalidateQueries({ queryKey: ENTRIES_KEY });
      },
    });
    socket.start();
    return () => {
      socket.stop();
    };
  }, [userId, qc]);
}
