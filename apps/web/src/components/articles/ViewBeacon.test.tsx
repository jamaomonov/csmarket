// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ API_BASE: "https://api.test" }));

import { ViewBeacon } from "./ViewBeacon";

describe("ViewBeacon", () => {
  it("sends one beacon for the article", () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    const { rerender } = render(<ViewBeacon slug="top" />);
    rerender(<ViewBeacon slug="top" />);
    expect(beacon).toHaveBeenCalledTimes(1);
    expect(beacon).toHaveBeenCalledWith("https://api.test/api/v1/articles/top/view");
  });
});
