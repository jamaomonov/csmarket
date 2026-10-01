import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "./AuthGuard";
import { useAuthStore } from "./authStore";

function renderAt(path: string): void {
  const router = createMemoryRouter(
    [
      { path: "/login", element: <p>login page</p> },
      { element: <AuthGuard />, children: [{ path: "/", element: <p>dashboard</p> }] },
    ],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
}

describe("AuthGuard", () => {
  beforeEach(() => {
    useAuthStore.setState({
      status: "loading",
      me: null,
      bootstrap: vi.fn(() => Promise.resolve()),
    });
  });

  it("sends anonymous visitors to /login", async () => {
    useAuthStore.setState({ status: "anonymous" });
    renderAt("/");
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("refuses a signed-in non-admin", async () => {
    useAuthStore.setState({ status: "forbidden" });
    renderAt("/");
    expect(await screen.findByText(/Нет доступа/)).toBeInTheDocument();
  });

  it("lets an admin through", async () => {
    useAuthStore.setState({
      status: "admin",
      me: { id: "u", display_name: "Owner", roles: ["admin"] },
    });
    renderAt("/");
    expect(await screen.findByText("dashboard")).toBeInTheDocument();
  });
});
