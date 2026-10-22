import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { When } from "./When";

afterEach(() => {
  vi.useRealTimers();
});

describe("When", () => {
  it("says how long ago, with the full date in the tooltip", () => {
    vi.useFakeTimers({ now: new Date(2026, 9, 22, 12, 0) });
    const iso = new Date(2026, 9, 22, 9, 30).toISOString();
    render(<When iso={iso} />);
    const time = screen.getByText("2 ч назад");
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("title", "22.10.2026 09:30");
    expect(time).toHaveAttribute("dateTime", iso);
  });

  it("an older row reads as a date", () => {
    vi.useFakeTimers({ now: new Date(2026, 9, 22, 12, 0) });
    render(<When iso={new Date(2026, 9, 3, 8, 0).toISOString()} />);
    expect(screen.getByText("03.10 08:00")).toBeInTheDocument();
  });
});
