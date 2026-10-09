import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OrderStatusChip } from "./StatusChip";

describe("OrderStatusChip", () => {
  it("names the status", () => {
    render(<OrderStatusChip status="trade_sent" />);
    expect(screen.getByTestId("order-status")).toHaveTextContent("обмен отправлен");
  });

  it("says an accepted trade under Steam's protection is not stuck", () => {
    render(<OrderStatusChip status="trade_sent" protectedUntil="2026-10-15T11:00:00+00:00" />);
    const chip = screen.getByTestId("order-status");
    expect(chip).toHaveTextContent(/^принят, защита до 15\.10$/);
    expect(chip).toHaveAttribute("title", expect.stringContaining("15.10.2026"));
  });

  it("ignores protection on any other status", () => {
    render(<OrderStatusChip status="cancelled" protectedUntil="2026-10-15T11:00:00+00:00" />);
    expect(screen.getByTestId("order-status")).toHaveTextContent("отменён");
  });

  it("a delivered trade still under estimated protection says so with ≈", () => {
    const until = new Date(Date.now() + 3 * 86_400_000).toISOString();
    render(<OrderStatusChip status="delivered" protectedUntil={until} estimated />);
    expect(screen.getByTestId("order-status")).toHaveTextContent(/^принят, защита до ≈ /);
  });
});
