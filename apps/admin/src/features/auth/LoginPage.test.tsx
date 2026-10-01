import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("starts the admin Steam flow", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Войти через Steam" });
    expect(link.getAttribute("href")).toBe("/api/v1/auth/steam/start?app=admin&locale=ru");
  });
});
