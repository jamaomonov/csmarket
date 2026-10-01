import { describe, expect, it } from "vitest";

import { routing } from "./routing";

describe("routing", () => {
  it("serves ru, uz and en with ru bare", () => {
    expect([...routing.locales].sort()).toEqual(["en", "ru", "uz"]);
    expect(routing.defaultLocale).toBe("ru");
    expect(routing.localePrefix).toBe("as-needed");
  });
  it("does not redirect by browser language or write a locale cookie", () => {
    // A URL means one language for everybody; Cloudflare also will not cache a
    // response that sets a cookie.
    expect(routing.localeDetection).toBe(false);
    expect(routing.localeCookie).toBe(false);
  });
});
