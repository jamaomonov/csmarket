import { expect, it, vi } from "vitest";

const moved = vi.hoisted(() => vi.fn());
vi.mock("@/i18n/navigation", () => ({ permanentRedirect: moved }));

import Page from "./page";

it("moved for good to /account/transactions, in the same locale", async () => {
  await Page({ params: Promise.resolve({ locale: "uz" }) });
  expect(moved).toHaveBeenCalledWith({ href: "/account/transactions", locale: "uz" });
});
