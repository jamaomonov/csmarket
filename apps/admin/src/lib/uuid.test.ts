import { describe, expect, it } from "vitest";

import { newUuid } from "./uuid";

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("newUuid", () => {
  it("uses crypto.randomUUID when the context offers it", () => {
    expect(newUuid({ randomUUID: () => "11111111-1111-4111-8111-111111111111" })).toBe(
      "11111111-1111-4111-8111-111111111111",
    );
  });

  it("falls back to getRandomValues outside a secure context", () => {
    const source = { getRandomValues: <T extends ArrayBufferView>(a: T): T => a };
    expect(newUuid(source)).toBe("00000000-0000-4000-8000-000000000000");
    expect(newUuid({ getRandomValues: (a) => crypto.getRandomValues(a) })).toMatch(V4);
  });

  it("returns a v4 uuid by default", () => {
    expect(newUuid()).toMatch(V4);
  });
});
