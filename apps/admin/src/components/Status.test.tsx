import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Reason, Status } from "./Status";

describe("Status", () => {
  it("names a known status in the dictionary's words and tone", () => {
    render(<Status of="payment" code="succeeded" testId="chip" />);
    const chip = screen.getByTestId("chip");
    expect(chip).toHaveTextContent(/^оплачен$/);
    expect(chip.className).toContain("text-success");
  });

  it("reads an unknown code as «другой статус» with the code small beside it", () => {
    render(<Status of="order" code="teleported" testId="chip" />);
    const chip = screen.getByTestId("chip");
    expect(chip).toHaveTextContent("другой статус");
    expect(screen.getByText("teleported")).toHaveClass("text-meta");
    expect(chip.className).toContain("text-fg-muted");
  });

  it("takes a tone override and a second line", () => {
    render(<Status of="sale" code="credited" tone="danger" sub="защита до 15.10" testId="chip" />);
    expect(screen.getByTestId("chip").className).toContain("text-danger");
    expect(screen.getByText("защита до 15.10")).toBeInTheDocument();
  });
});

describe("Reason", () => {
  it("translates a known reason", () => {
    render(<Reason of="return" code="not_accepted" />);
    expect(screen.getByText("обмен не принят")).toBeInTheDocument();
  });

  it("an unknown reason reads «другая причина» and keeps the code", () => {
    const { container } = render(<Reason of="failure" code="moon_phase" />);
    expect(container).toHaveTextContent("другая причина moon_phase");
    expect(screen.getByText("moon_phase")).toHaveClass("text-meta");
  });
});
