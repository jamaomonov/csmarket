import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { groupDigits, MoneyField, MoneyInput, ungroup } from "./MoneyInput";

const NB = " ";

describe("groupDigits / ungroup", () => {
  it("groups the whole part only", () => {
    expect(groupDigits("2000000")).toBe(`2${NB}000${NB}000`);
    expect(groupDigits("-1500.255")).toBe(`-1${NB}500.255`);
    expect(groupDigits("999")).toBe("999");
    expect(groupDigits("")).toBe("");
  });
  it("leaves what is not a number as typed, for the form to refuse", () => {
    expect(groupDigits("12a")).toBe("12a");
    expect(groupDigits("1,5")).toBe("1,5");
  });
  it("drops every kind of space", () => {
    expect(ungroup(`2${NB}000\u202f000 `)).toBe("2000000");
  });
});

function Controlled({ onValue }: { onValue: (v: string) => void }) {
  const [v, setV] = useState("");
  return (
    <MoneyInput
      label="Сумма"
      unit="сум"
      value={v}
      onChange={(next) => {
        setV(next);
        onValue(next);
      }}
    />
  );
}

describe("MoneyInput", () => {
  it("shows groups and hands back digits only", () => {
    const seen = vi.fn();
    render(<Controlled onValue={seen} />);
    const field = screen.getByRole("textbox", { name: "Сумма, сум" });
    expect(field).toHaveAttribute("inputmode", "numeric");
    fireEvent.change(field, { target: { value: "2000000" } });
    expect(field).toHaveValue(`2${NB}000${NB}000`);
    expect(seen).toHaveBeenLastCalledWith("2000000");
    fireEvent.change(field, { target: { value: `2${NB}000${NB}0005` } });
    expect(seen).toHaveBeenLastCalledWith("20000005");
    expect(screen.getByText("сум")).toBeInTheDocument();
  });

  it("takes a decimal keyboard for dollars and a visible label in a field", () => {
    render(
      <MoneyField label="Максимум" unit="$" decimal value="1500.5" onChange={() => undefined} />,
    );
    const field = screen.getByLabelText("Максимум, $");
    expect(field).toHaveAttribute("inputmode", "decimal");
    expect(field).toHaveValue(`1${NB}500.5`);
  });
});
