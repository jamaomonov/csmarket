// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewDialog, type ReviewDeal } from "./ReviewDialog";

import type * as ReviewsModule from "@/lib/reviews";

const api = vi.hoisted(() => ({ saveReview: vi.fn() }));
vi.mock("@/lib/reviews", async (importOriginal) => ({
  ...(await importOriginal<typeof ReviewsModule>()),
  ...api,
}));

const DEAL: ReviewDeal = {
  kind: "market",
  number: "AB12CD34",
  title: "AK-47 | Redline (Field-Tested)",
  image_url: null,
};

interface Extra {
  deal?: ReviewDeal;
  initialRating?: number;
}

function renderDialog(extra: Extra = {}) {
  const onClose = vi.fn();
  const onLater = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
        <ReviewDialog
          deal={extra.deal ?? DEAL}
          initialRating={extra.initialRating ?? null}
          onClose={onClose}
          onLater={onLater}
        />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return { onClose, onLater };
}

beforeEach(() => {
  api.saveReview.mockReset();
});

describe("ReviewDialog", () => {
  it("asks about the purchase; the placeholder follows the stars", () => {
    renderDialog();
    expect(
      screen.getByRole("heading", { name: "Обмен прошёл! Как вам покупка?" }),
    ).toBeInTheDocument();
    const box = screen.getByRole("textbox", { name: "Ваш отзыв" });
    expect(box).toHaveAttribute("placeholder", "Пару тёплых слов — это нам очень помогает");
    fireEvent.click(screen.getByRole("radio", { name: "2 звезды" }));
    expect(box).toHaveAttribute("placeholder", "Расскажите, что случилось?");
    fireEvent.click(screen.getByRole("radio", { name: "5 звёзд" }));
    expect(box).toHaveAttribute("placeholder", "Пару тёплых слов — это нам очень помогает");
  });

  it("asks about the sale for a sale", () => {
    renderDialog({ deal: { ...DEAL, kind: "sale", number: "S7K2M9QX" } });
    expect(screen.getByRole("heading", { name: "Как прошла продажа?" })).toBeInTheDocument();
  });

  it("sends once a star is chosen; a bad review hears «Мы свяжемся с вами»", async () => {
    api.saveReview.mockResolvedValue({});
    renderDialog();
    const send = screen.getByRole("button", { name: "Отправить" });
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "2 звезды" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ваш отзыв" }), {
      target: { value: "  Долго  " },
    });
    fireEvent.click(send);
    expect(await screen.findByRole("heading", { name: "Спасибо за отзыв!" })).toBeInTheDocument();
    expect(screen.getByText("Мы свяжемся с вами")).toBeInTheDocument();
    expect(api.saveReview).toHaveBeenCalledWith(
      "market",
      "AB12CD34",
      { rating: 2, text: "Долго", locale: "ru" },
      expect.stringMatching(/^web-review-/),
    );
  });

  it("only thanks a good review", async () => {
    api.saveReview.mockResolvedValue({});
    renderDialog();
    fireEvent.click(screen.getByRole("radio", { name: "5 звёзд" }));
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("heading", { name: "Спасибо за отзыв!" })).toBeInTheDocument();
    expect(screen.queryByText("Мы свяжемся с вами")).toBeNull();
  });

  it("says so when the send fails and keeps the text", async () => {
    api.saveReview.mockRejectedValue(new Error("down"));
    renderDialog({ initialRating: 3 });
    fireEvent.change(screen.getByRole("textbox", { name: "Ваш отзыв" }), {
      target: { value: "Долго" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не получилось отправить.");
    expect(screen.getByRole("textbox", { name: "Ваш отзыв" })).toHaveValue("Долго");
  });

  it("opens with the star chosen on the strip; «Не сейчас» hands back", () => {
    const { onLater } = renderDialog({ initialRating: 4 });
    expect(screen.getByRole("radio", { name: "4 звезды" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: "Не сейчас" }));
    expect(onLater).toHaveBeenCalledTimes(1);
  });
});
