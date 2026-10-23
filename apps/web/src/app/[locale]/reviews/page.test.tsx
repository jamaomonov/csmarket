// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import ReviewsPage, { generateMetadata } from "./page";

vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((key: string) => key),
  setRequestLocale: () => undefined,
}));
const server = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/lib/server-api", () => server);
vi.mock("@/components/ComingSoon", () => ({ ComingSoon: () => null }));
vi.mock("@/components/reviews/ReviewList", () => ({ ReviewList: () => null }));
vi.mock("@/components/reviews/ReviewsMore", () => ({ ReviewsMore: () => null }));

import { ComingSoon } from "@/components/ComingSoon";

const ON = { enabled: true, count: 2, items: [], next_cursor: null };
const page = () => ReviewsPage({ params: Promise.resolve({ locale: "ru" }) });
const meta = () => generateMetadata({ params: Promise.resolve({ locale: "ru" }) });

describe("reviews page", () => {
  it("is «Скоро» and noindex while the page is off", async () => {
    server.apiGet.mockResolvedValue({ ...ON, enabled: false });
    expect((await page()).type).toBe(ComingSoon);
    expect((await meta()).robots).toEqual({ index: false, follow: true });
  });

  it("is «Скоро» when the API cannot say", async () => {
    server.apiGet.mockRejectedValue(new Error("down"));
    expect((await page()).type).toBe(ComingSoon);
    expect((await meta()).robots).toEqual({ index: false, follow: true });
  });

  it("asks for the visitor's locale, cached 5 minutes", async () => {
    server.apiGet.mockResolvedValue(ON);
    const out = await page();
    expect(out.type).not.toBe(ComingSoon);
    expect(server.apiGet).toHaveBeenCalledWith("/reviews?locale=ru", {
      revalidate: 300,
      tags: ["reviews"],
    });
  });

  it("claims no average rating: only 4–5★ reviews are shown (owner ruling)", async () => {
    server.apiGet.mockResolvedValue(ON);
    expect(JSON.stringify((await page()).props)).not.toContain("AggregateRating");
  });

  it("is indexed with its own canonical while on", async () => {
    server.apiGet.mockResolvedValue(ON);
    const m = await meta();
    expect(m.title).toBe("title");
    expect(m.robots).toMatchObject({ index: true, follow: true });
    expect(m.alternates?.canonical).toBe("https://csmarket.uz/reviews");
  });
});
