// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewDialog, type ReviewDeal } from "./ReviewDialog";

import type * as ReviewsModule from "@/lib/reviews";

const api = vi.hoisted(() => ({ saveReview: vi.fn() }));
const auth = vi.hoisted(() => ({ user: { email: null as string | null, email_verified: false } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: auth.user, status: "signed_in" }) }));
vi.mock("@/lib/reviews", async (importOriginal) => ({
  ...(await importOriginal<typeof ReviewsModule>()),
  ...api,
}));

const DEAL: ReviewDeal = {
  kind: "market",
  number: "AB12CD34",
  title: "AK-47 | Redline (Field-Tested)",
  image_url: null,
  rarity_color: null,
};

interface Extra {
  deal?: ReviewDeal;
  initialRating?: number;
  editing?: boolean;
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
          editing={extra.editing ?? false}
        />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return { onClose, onLater };
}

beforeEach(() => {
  api.saveReview.mockReset();
  auth.user = { email: null, email_verified: false };
});

describe("ReviewDialog", () => {
  it("lights the skin by its rarity", () => {
    renderDialog({
      deal: { ...DEAL, image_url: "https://cdn.test/ak.png", rarity_color: "#eb4b4b" },
    });
    const light = screen.getByTestId("rarity-light");
    expect(light.style.background).toContain("radial-gradient");
  });

  it("shows the skin without a light when the rarity is unknown", () => {
    renderDialog({ deal: { ...DEAL, image_url: "https://cdn.test/ak.png" } });
    expect(screen.queryByTestId("rarity-light")).toBeNull();
  });

  it("asks about the purchase; the placeholder follows the stars", () => {
    renderDialog();
    expect(
      screen.getByRole("heading", { name: "Скин у вас! Как вам покупка?" }),
    ).toBeInTheDocument();
    expect(screen.getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
    expect(screen.getByText("Выберите оценку")).toBeInTheDocument();
    const box = screen.getByRole("textbox", { name: "Ваш отзыв" });
    expect(box).toHaveAttribute("placeholder", "Пара слов о сделке — по желанию");
    fireEvent.click(screen.getByRole("radio", { name: "2 звезды" }));
    expect(screen.queryByText("Выберите оценку")).toBeNull();
    expect(box).toHaveAttribute("placeholder", "Что пошло не так?");
    fireEvent.click(screen.getByRole("radio", { name: "5 звёзд" }));
    expect(box).toHaveAttribute("placeholder", "Пару тёплых слов — это нам очень помогает");
  });

  it("asks about the sale for a sale", () => {
    renderDialog({ deal: { ...DEAL, kind: "sale", number: "S7K2M9QX" } });
    expect(screen.getByRole("heading", { name: "Как прошла продажа?" })).toBeInTheDocument();
  });

  it("says «Изменить отзыв» when editing", () => {
    renderDialog({ initialRating: 2, editing: true });
    expect(screen.getByRole("heading", { name: "Изменить отзыв" })).toBeInTheDocument();
  });

  it("sends once a star is chosen; a bad review hears «Мы свяжемся с вами»", async () => {
    auth.user = { email: "a@example.com", email_verified: true };
    let answer: (v: unknown) => void = () => undefined;
    api.saveReview.mockReturnValue(new Promise((r) => (answer = r)));
    const { onClose } = renderDialog();
    const send = screen.getByRole("button", { name: "Отправить" });
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "2 звезды" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ваш отзыв" }), {
      target: { value: "  Долго  " },
    });
    fireEvent.click(send);
    expect(await screen.findByRole("button", { name: "Отправляем…" })).toBeDisabled();
    answer({});
    expect(await screen.findByRole("heading", { name: "Спасибо за отзыв!" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Мы свяжемся с вами");
    const done = screen.getByRole("button", { name: "Готово" });
    expect(done).toHaveFocus();
    fireEvent.click(done);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(api.saveReview).toHaveBeenCalledWith(
      "market",
      "AB12CD34",
      { rating: 2, text: "Долго", locale: "ru" },
      expect.stringMatching(/^web-review-/),
    );
  });

  it("promises no contact without a confirmed email", async () => {
    auth.user = { email: "a@example.com", email_verified: false };
    api.saveReview.mockResolvedValue({});
    renderDialog({ initialRating: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Спасибо. Мы разберёмся.");
    expect(screen.queryByText("Мы свяжемся с вами")).toBeNull();
  });

  it("a click on the backdrop closes it only while nothing is typed or changed", () => {
    const { onClose } = renderDialog({ initialRating: 2 });
    const dialog = screen.getByRole("dialog");
    fireEvent.change(screen.getByRole("textbox", { name: "Ваш отзыв" }), {
      target: { value: "Долго ждал" },
    });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Ваш отзыв" }), {
      target: { value: "" },
    });
    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("gives focus back to what opened it", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    renderDialog();
    screen.getByRole("textbox", { name: "Ваш отзыв" }).focus(); // showModal moves focus inside
    cleanup();
    expect(opener).toHaveFocus();
    opener.remove();
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
    expect(screen.getByRole("radio", { name: "4 звезды" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Не сейчас" }));
    expect(onLater).toHaveBeenCalledTimes(1);
  });
});
