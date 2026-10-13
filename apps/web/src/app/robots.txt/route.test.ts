import { expect, test } from "vitest";

import { dynamic, GET } from "./route";

test("robots.txt opens the catalogue and names the sitemap index", async () => {
  const body = await GET().text();
  expect(body).toContain("Allow: /\n");
  // No blanket `Disallow: /` (the pre-launch policy): only the private paths are listed.
  expect(body).not.toMatch(/^Disallow: \/$/m);
  expect(body).not.toContain("Host:");
  expect(body).toContain("Sitemap: https://csmarket.uz/sitemap.xml");
});

test("keeps crawlers off the API, the account and the sign-in callback, in every locale", async () => {
  const body = await GET().text();
  for (const rule of ["/api/", "/account", "/*/account", "/auth/", "/*/auth/"]) {
    expect(body).toContain(`Disallow: ${rule}\n`);
  }
});

test("declares content signals and welcomes AI crawlers", async () => {
  const body = await GET().text();
  const signals = body.match(/Content-Signal: search=yes, ai-input=yes, ai-train=no/g) ?? [];
  expect(signals.length).toBe(2); // one per group (* and the AI-crawler group)
  expect(body).toContain("User-Agent: GPTBot");
  expect(body).toContain("User-Agent: ClaudeBot");
});

test("is rendered per request", () => {
  expect(dynamic).toBe("force-dynamic");
});

test("tells Yandex which query parameters never change a page", async () => {
  const body = await GET().text();
  expect(body).toMatch(/^Clean-param: utm_source&.*&yclid&ysclid&fbclid$/m);
  expect(body).toContain("Clean-param: sort&cursor /market\n");
  // Only in the `*` group, which Yandex reads: before the AI-crawler group starts.
  expect(body.indexOf("Clean-param")).toBeLessThan(body.indexOf("User-Agent: GPTBot"));
});
