import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Accordion } from "./Accordion";

describe("Accordion", () => {
  it("starts closed, opens on click, wires aria", () => {
    render(<Accordion title="Редкость">Covert</Accordion>);
    const head = screen.getByRole("button", { name: "Редкость" });
    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Covert")).toBeNull();
    fireEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "true");
    const region = screen.getByRole("region", { name: "Редкость" });
    expect(head.getAttribute("aria-controls")).toBe(region.id);
    expect(region).toHaveTextContent("Covert");
  });

  it("can start open", () => {
    render(
      <Accordion title="Качество" defaultOpen>
        FN
      </Accordion>,
    );
    expect(screen.getByText("FN")).toBeInTheDocument();
  });

  it("uses the one focus style (ring with an offset)", () => {
    render(<Accordion title="Цена">x</Accordion>);
    expect(screen.getByRole("button", { name: "Цена" }).className).toContain(
      "focus-visible:ring-offset-2",
    );
  });
});
