import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useIdempotencyKey } from "./useIdempotencyKey";

describe("useIdempotencyKey", () => {
  it("keeps the key while the body is the same", () => {
    const { result } = renderHook(() => useIdempotencyKey("admin-adjust"));
    const first = result.current.keyFor('{"amount":1}');
    expect(first).toMatch(/^admin-adjust-[0-9a-f-]{36}$/);
    expect(result.current.keyFor('{"amount":1}')).toBe(first);
  });

  it("issues a new key when the body changes", () => {
    const { result } = renderHook(() => useIdempotencyKey("admin-adjust"));
    const first = result.current.keyFor('{"amount":1}');
    expect(result.current.keyFor('{"amount":2}')).not.toBe(first);
  });

  it("issues a new key for the same body after reset", () => {
    const { result } = renderHook(() => useIdempotencyKey("admin-adjust"));
    const first = result.current.keyFor('{"amount":1}');
    act(() => {
      result.current.reset();
    });
    expect(result.current.keyFor('{"amount":1}')).not.toBe(first);
  });
});
