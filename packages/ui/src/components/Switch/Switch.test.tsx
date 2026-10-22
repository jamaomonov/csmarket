import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Switch } from "./Switch";

function Controlled() {
  const [on, setOn] = useState(false);
  return (
    <Switch label="Выкуп" states={["включён", "выключен"]} checked={on} onCheckedChange={setOn} />
  );
}

describe("Switch", () => {
  it("is a switch named by its label, its state in words", () => {
    render(<Controlled />);
    const sw = screen.getByRole("switch", { name: "Выкуп" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(sw).toHaveAccessibleDescription("выключен");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    expect(sw).toHaveAccessibleDescription("включён");
  });

  it("does not fire when disabled", () => {
    const onChange = vi.fn();
    render(<Switch label="Доверенный" checked={false} onCheckedChange={onChange} disabled />);
    fireEvent.click(screen.getByRole("switch", { name: "Доверенный" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows a hint beside the state", () => {
    render(
      <Switch
        label="Запретить оплату кассой"
        checked
        onCheckedChange={() => undefined}
        states={["да", "нет"]}
        hint="только баланс"
      />,
    );
    expect(screen.getByRole("switch")).toHaveAccessibleDescription("да · только баланс");
  });
});
