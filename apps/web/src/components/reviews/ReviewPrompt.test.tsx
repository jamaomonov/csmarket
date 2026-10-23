// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewPrompt } from "./ReviewPrompt";

import type * as ReviewsModule from "@/lib/reviews";
import type { PendingDeal } from "@/lib/reviews";

import { REVIEW_PENDING_KEY } from "@/lib/reviews";

const m = vi.hoisted(() => ({
  auth: { value: { status: "signed_in" } },
  pending: vi.fn(),
  snooze: vi.fn(),
  dismiss: vi.fn(),
  save: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => m.auth.value }));
const nav = vi.hoisted(() => ({ path: "/ru/market" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.path }));
vi.mock("@/lib/reviews", async (importOriginal) => ({
  ...(await importOriginal<typeof ReviewsModule>()),
  getPendingReview: m.pending,
  snoozeReview: m.snooze,
  dismissReview: m.dismiss,
  saveReview: m.save,
}));

const OLD: PendingDeal = {
  kind: "market",
  number: "AB12CD34",
  title: "AK-47 | Redline (Field-Tested)",
  image_url: null,
  items: 1,
  done_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
};
const fresh = (number: string): PendingDeal => ({
  ...OLD,
  number,
  done_at: new Date().toISOString(),
});

function mount(): QueryClient {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <ReviewPrompt />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return client;
}

const nudge = (client: QueryClient) =>
  act(() => client.invalidateQueries({ queryKey: REVIEW_PENDING_KEY }));

beforeEach(() => {
  window.sessionStorage.clear();
  nav.path = "/ru/market";
  document.body.style.paddingBottom = "";
  m.auth.value = { status: "signed_in" };
  for (const f of [m.pending, m.snooze, m.dismiss, m.save]) f.mockReset();
  m.snooze.mockResolvedValue(undefined);
  m.dismiss.mockResolvedValue(undefined);
});

describe("ReviewPrompt", () => {
  it("shows the strip once per visit for a deal pending at load", async () => {
    m.pending.mockResolvedValue({ deal: OLD });
    mount();
    expect(
      await screen.findByText("Как прошла покупка AK-47 | Redline (Field-Tested)?"),
    ).toBeInTheDocument();
    cleanup();
    mount();
    await waitFor(() => {
      expect(m.pending).toHaveBeenCalledTimes(2);
    });
    expect(screen.queryByText(/Как прошла покупка/)).toBeNull();
  });

  it("a socket nudge opens the modal for a deal that just succeeded", async () => {
    m.pending.mockResolvedValue({ deal: null });
    const client = mount();
    // the load's own read must land first: a nudge during it cancels it (cancelRefetch)
    await waitFor(() => {
      expect(client.getQueryData(REVIEW_PENDING_KEY)).toEqual({ deal: null });
    });
    m.pending.mockResolvedValue({ deal: fresh("EF56GH78") });
    await nudge(client);
    expect(
      await screen.findByRole("heading", { name: "Обмен прошёл! Как вам покупка?" }),
    ).toBeInTheDocument();
  });

  it("«Не сейчас» on the strip snoozes the deal, × dismisses it", async () => {
    m.pending.mockResolvedValue({ deal: OLD });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Не сейчас" }));
    await waitFor(() => {
      expect(m.snooze).toHaveBeenCalledWith(
        "market",
        "AB12CD34",
        expect.stringMatching(/^web-review-/),
      );
    });
    expect(screen.queryByText(/Как прошла покупка/)).toBeNull();
    cleanup();
    window.sessionStorage.clear();
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Больше не спрашивать" }));
    await waitFor(() => {
      expect(m.dismiss).toHaveBeenCalledWith(
        "market",
        "AB12CD34",
        expect.stringMatching(/^web-review-/),
      );
    });
  });

  it("a star on the strip opens the modal with that star chosen", async () => {
    m.pending.mockResolvedValue({ deal: OLD });
    mount();
    const strip = await screen.findByRole("complementary", { name: "Отзыв о сделке" });
    fireEvent.click(within(strip).getByRole("radio", { name: "4 звезды" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: "4 звезды" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("does not open the modal for an older deal after a send", async () => {
    m.pending.mockResolvedValue({ deal: null });
    const client = mount();
    await waitFor(() => {
      expect(m.pending).toHaveBeenCalledTimes(1);
    });
    m.pending.mockResolvedValue({ deal: fresh("EF56GH78") });
    await nudge(client);
    fireEvent.click(await screen.findByRole("radio", { name: "5 звёзд" }));
    m.save.mockResolvedValue({});
    m.pending.mockResolvedValue({ deal: OLD }); // the next, older deal
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("heading", { name: "Спасибо за отзыв!" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    await waitFor(() => {
      expect(m.pending).toHaveBeenCalledTimes(3);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/Как прошла покупка/)).toBeNull();
  });

  it("asks nothing of a signed-out visitor", () => {
    m.auth.value = { status: "anonymous" };
    mount();
    expect(m.pending).not.toHaveBeenCalled();
  });

  it("signing out hides the strip and forgets the deal", async () => {
    m.pending.mockResolvedValue({ deal: OLD });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = () => (
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
          <ReviewPrompt />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
    const { rerender } = render(tree());
    expect(await screen.findByText(/Как прошла покупка/)).toBeInTheDocument();
    m.auth.value = { status: "anonymous" };
    rerender(tree());
    expect(screen.queryByText(/Как прошла покупка/)).toBeNull();
    expect(client.getQueryData(REVIEW_PENDING_KEY)).toBeUndefined();
  });

  it("keeps the strip off a page with its own bottom bar (buy, sell)", async () => {
    m.pending.mockResolvedValue({ deal: OLD });
    nav.path = "/ru/item/ak-47-redline-field-tested";
    const client = mount();
    await waitFor(() => {
      expect(client.getQueryData(REVIEW_PENDING_KEY)).toEqual({ deal: OLD });
    });
    await act(() => Promise.resolve());
    expect(screen.queryByText(/Как прошла покупка/)).toBeNull();
  });

  it("leaves room under the page for the strip", async () => {
    m.pending.mockResolvedValue({ deal: OLD });
    mount();
    await screen.findByText(/Как прошла покупка/);
    expect(document.body.style.paddingBottom).not.toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Не сейчас" }));
    expect(document.body.style.paddingBottom).toBe("");
  });
});
