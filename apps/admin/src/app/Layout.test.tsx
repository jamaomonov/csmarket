import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Layout } from "./Layout";

vi.mock("@/features/auth/authStore", () => ({
  useAuthStore: (pick: (s: { me: null; signOut: () => void }) => unknown) =>
    pick({ me: null, signOut: () => undefined }),
}));

describe("Layout", () => {
  it("links the pricing page from the menu", () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Цены" })).toHaveAttribute("href", "/pricing");
  });
});
