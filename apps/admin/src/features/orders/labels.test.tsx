import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { orderChip } from "./labels";

import { Status } from "@/components/Status";

function chip(...args: Parameters<typeof orderChip>) {
  render(<Status {...orderChip(...args)} testId="order-status" />);
  return screen.getByTestId("order-status");
}

describe("orderChip", () => {
  it("names the status", () => {
    expect(chip("trade_sent")).toHaveTextContent("обмен отправлен");
  });

  it("an accepted trade under Steam's protection reads «принят», the end under it", () => {
    const el = chip("trade_sent", "2026-10-15T11:00:00+00:00");
    expect(el).toHaveTextContent(/^принят$/);
    expect(el).toHaveAttribute("title", expect.stringContaining("15.10.2026"));
    expect(screen.getByText("защита до 15.10")).toBeInTheDocument();
  });

  it("ignores protection on any other status", () => {
    expect(chip("cancelled", "2026-10-15T11:00:00+00:00")).toHaveTextContent("отменён");
  });

  it("a delivered trade still under estimated protection says so with ≈", () => {
    const until = new Date(Date.now() + 3 * 86_400_000).toISOString();
    chip("delivered", until, true);
    expect(screen.getByText(/^защита до ≈ /)).toBeInTheDocument();
  });
});
