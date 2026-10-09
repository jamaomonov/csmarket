import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { OrdersRedirect } from "./OrdersRedirect";

function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="where">{pathname + search}</p>;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/orders" element={<OrdersRedirect />} />
        <Route path="/trades" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OrdersRedirect", () => {
  it("keeps the query string", () => {
    renderAt("/orders?q=O7K2M9QX&view=hold");
    expect(screen.getByTestId("where")).toHaveTextContent("/trades?q=O7K2M9QX&view=hold");
  });

  it("works without one", () => {
    renderAt("/orders");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/trades$/);
  });
});
