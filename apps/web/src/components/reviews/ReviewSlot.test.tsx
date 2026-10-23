// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewSlot } from "./ReviewSlot";

import type * as ReviewsModule from "@/lib/reviews";
import type { DealReview } from "@/lib/reviews";

const api = vi.hoisted(() => ({ getDealReview: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: null, status: "signed_in" }) }));
vi.mock("@/lib/reviews", async (importOriginal) => ({
  ...(await importOriginal<typeof ReviewsModule>()),
  ...api,
}));

const BASE: DealReview = {
  kind: "market",
  number: "AB12CD34",
  can_review: true,
  editable_until: "2026-11-06T10:00:00Z",
  review: null,
};
const MINE = {
  rating: 4,
  text: "Норм",
  locale: "ru",
  created_at: "2026-10-23T10:00:00Z",
  updated_at: "2026-10-23T10:00:00Z",
};

function renderSlot() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <ReviewSlot kind="market" number="AB12CD34" title="AK-47 | Redline" imageUrl={null} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.getDealReview.mockReset();
});

describe("ReviewSlot", () => {
  it("offers «Оставить отзыв» and opens the modal", async () => {
    api.getDealReview.mockResolvedValue(BASE);
    renderSlot();
    fireEvent.click(await screen.findByRole("button", { name: "Оставить отзыв" }));
    expect(
      await screen.findByRole("heading", { name: "Скин у вас! Как вам покупка?" }),
    ).toBeInTheDocument();
  });

  it("shows the stars given and «Изменить» within 14 days", async () => {
    api.getDealReview.mockResolvedValue({ ...BASE, review: MINE });
    renderSlot();
    expect(await screen.findByRole("img", { name: "Оценка 4 из 5" })).toBeInTheDocument();
    expect(screen.getByText("Норм")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Изменить" }));
    expect(await screen.findByRole("heading", { name: "Изменить отзыв" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Ваш отзыв" })).toHaveValue("Норм");
  });

  it("shows the stars without «Изменить» after 14 days", async () => {
    api.getDealReview.mockResolvedValue({ ...BASE, can_review: false, review: MINE });
    renderSlot();
    expect(await screen.findByRole("img", { name: "Оценка 4 из 5" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Изменить" })).toBeNull();
  });

  it("shows nothing for a deal that cannot be reviewed", async () => {
    api.getDealReview.mockResolvedValue({ ...BASE, can_review: false });
    renderSlot();
    await waitFor(() => {
      expect(api.getDealReview).toHaveBeenCalledWith("market", "AB12CD34");
    });
    expect(screen.queryByRole("button")).toBeNull();
  });
});
