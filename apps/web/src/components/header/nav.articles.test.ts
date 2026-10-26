import { describe, expect, it } from "vitest";

import { mainNav } from "./nav";

describe("mainNav", () => {
  it("carries «Статьи» only when the language has articles", () => {
    expect(mainNav(true).map((e) => e.key)).toContain("articles");
    expect(mainNav(false).map((e) => e.key)).not.toContain("articles");
  });
});
