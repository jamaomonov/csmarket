// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { preferBalance, usePreferBalance } from "./prefer-balance";

const base = { picked: false, fallback: "click" };

describe("preferBalance", () => {
  it("selects the balance when it covers the price and the buyer has not chosen", () => {
    expect(preferBalance("click", { ...base, ready: true })).toBe("wallet");
  });

  it("goes back to the default when the auto-picked balance stops covering", () => {
    expect(preferBalance("wallet", { ...base, ready: false })).toBe("click");
  });

  it("leaves a kassa alone while the balance cannot pay", () => {
    expect(preferBalance("payme", { ...base, ready: false })).toBe("payme");
  });

  it("never overrides what the buyer picked by hand", () => {
    expect(preferBalance("payme", { ...base, ready: true, picked: true })).toBe("payme");
    expect(preferBalance("wallet", { ...base, ready: false, picked: true })).toBe("wallet");
  });
});

describe("usePreferBalance", () => {
  function useMethod(ready: boolean) {
    const [method, setMethod] = useState("");
    const markPicked = usePreferBalance(ready, setMethod, "click");
    return { method, setMethod, markPicked };
  }

  it("follows the balance until the buyer picks, then stays put", () => {
    const { result, rerender } = renderHook(({ ready }) => useMethod(ready), {
      initialProps: { ready: true },
    });
    expect(result.current.method).toBe("wallet");
    rerender({ ready: false });
    expect(result.current.method).toBe("click");
    act(() => {
      result.current.markPicked();
      result.current.setMethod("payme");
    });
    rerender({ ready: true });
    expect(result.current.method).toBe("payme");
  });
});
