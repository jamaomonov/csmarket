import { describe, expect, it } from "vitest";

import { imageMarkdown, insertAt } from "./insert";

describe("insertAt", () => {
  it("puts inline text at the caret", () => {
    expect(insertAt("ab", 1, "X", false)).toEqual({ text: "aXb", caret: 2 });
  });

  it("puts a block on a line of its own", () => {
    expect(insertAt("abc", 1, "[[skin:x]]", true)).toEqual({
      text: "a\n\n[[skin:x]]\n\nbc",
      caret: 15,
    });
    expect(insertAt("", 0, "[[skin:x]]", true)).toEqual({ text: "[[skin:x]]\n\n", caret: 12 });
    expect(insertAt("a\n\n", 3, "[[skin:x]]", true).text).toBe("a\n\n[[skin:x]]\n\n");
  });
});

describe("imageMarkdown", () => {
  it("carries the size for the storefront", () => {
    expect(
      imageMarkdown({
        hash: "h",
        url: "/media/h.png",
        width: 640,
        height: 360,
        content_type: "image/png",
      }),
    ).toBe("![](/media/h.png?w=640&h=360)");
  });
});
