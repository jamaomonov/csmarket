// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { ReviewList } from "./ReviewList";

import type { PublicReview } from "@/lib/reviews";

const ITEM: PublicReview = {
  id: "r1",
  author_name: "Gabe",
  author_avatar_url: null,
  rating: 5,
  text: "<b>hi</b>",
  kind: "market",
  skin_name: "AK-47 | Redline (Field-Tested)",
  locale: "ru",
  created_at: "2026-10-23T10:00:00Z",
};

function renderList(items: PublicReview[]) {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <ReviewList items={items} locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("ReviewList", () => {
  it("renders a review's text as text", () => {
    const { container } = renderList([ITEM]);
    expect(screen.getByText("<b>hi</b>")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByRole("img", { name: "Оценка 5 из 5" })).toBeInTheDocument();
    expect(screen.getByText("AK-47 | Redline (Field-Tested)")).toBeInTheDocument();
  });

  it("names a sale «Продажа скинов» and a nameless author «Пользователь Steam»", () => {
    renderList([{ ...ITEM, kind: "sale", skin_name: null, author_name: null }]);
    expect(screen.getByText("Продажа скинов")).toBeInTheDocument();
    expect(screen.getByText("Пользователь Steam")).toBeInTheDocument();
  });
});
