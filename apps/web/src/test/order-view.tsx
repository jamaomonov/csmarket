import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { vi } from "vitest";

import { OrderView } from "@/components/order/OrderView";

/** Render the order page body in ru with a fresh query client (no retries by default). */
export function renderOrderView(number: string): RenderResult & { client: QueryClient } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <OrderView locale="ru" number={number} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  return { ...render(tree), client };
}

/** The order page's `data-state`. */
export const orderState = (): string | null =>
  screen.getByTestId("order-status").getAttribute("data-state");

/** Run `ms` of fake time, plus the 0 ms timers a query's answer rides on. */
export async function tick(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms + 20);
  });
}
