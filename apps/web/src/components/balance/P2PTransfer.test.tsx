// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { P2PTransfer } from "./P2PTransfer";

import type { P2PTransferInfo } from "@/lib/balance";

const NOW = new Date("2026-10-19T10:00:00Z");
const TRANSFER: P2PTransferInfo = {
  card_number: "9860000000004321",
  holder: "TEST HOLDER",
  amount_uzs: "100037",
  expires_at: "2026-10-19T10:08:30Z",
  status: "pending",
};

function view(info: P2PTransferInfo, supportUrl = "https://t.me/support") {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <P2PTransfer locale="ru" number="T123" transfer={info} supportUrl={supportUrl} now={NOW} />
    </NextIntlClientProvider>,
  );
}

describe("P2PTransfer", () => {
  it("shows the card by fours, the holder, the exact amount and the time left", () => {
    view(TRANSFER);
    expect(screen.getByText("9860 0000 0000 4321")).toBeInTheDocument();
    expect(screen.getByText("TEST HOLDER")).toBeInTheDocument();
    expect(screen.getByTestId("p2p-amount")).toHaveTextContent(/100\s037 сум/);
    expect(screen.getByText(/Переведите ровно/)).toBeInTheDocument();
    expect(screen.getByTestId("p2p-left")).toHaveTextContent("8:30");
  });

  it("copies the card number and the amount as plain digits", () => {
    const writeText = vi.fn<(t: string) => Promise<void>>().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    view(TRANSFER);
    fireEvent.click(screen.getByRole("button", { name: "Скопировать номер карты" }));
    fireEvent.click(screen.getByRole("button", { name: "Скопировать сумму" }));
    expect(writeText.mock.calls.map((c) => c[0])).toEqual(["9860000000004321", "100037"]);
  });

  it("once the time is out, offers a new request and the support with the request number", () => {
    view({ ...TRANSFER, expires_at: "2026-10-19T09:59:00Z", status: "expired" });
    expect(screen.getByText("Время на перевод вышло")).toBeInTheDocument();
    expect(screen.getByText(/T123/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Написать в поддержку" })).toHaveAttribute(
      "href",
      "https://t.me/support",
    );
    expect(screen.getByRole("link", { name: "Новая заявка" })).toBeInTheDocument();
  });
});
