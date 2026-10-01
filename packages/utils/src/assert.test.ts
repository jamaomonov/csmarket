import { describe, expect, it } from "vitest";

import { assertNever } from "./assert";

describe("assertNever", () => {
  it("throws with the offending value in the message", () => {
    expect(() => assertNever("oops" as never)).toThrow(/"oops"/);
  });
});
