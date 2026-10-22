import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ConfirmSheet } from "./ConfirmSheet";

function Harness({ withField = false }: { withField?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
      >
        Вернуть деньги
      </button>
      {open ? (
        <ConfirmSheet
          title="Вернуть деньги"
          onClose={() => {
            setOpen(false);
          }}
        >
          {withField ? <textarea aria-label="Причина" /> : null}
          <div>
            <button type="button">Отмена</button>
            <button type="button">Вернуть</button>
          </div>
        </ConfirmSheet>
      ) : null}
    </>
  );
}

function openFrom(trigger: HTMLElement) {
  trigger.focus();
  fireEvent.click(trigger);
}

describe("ConfirmSheet on desktop", () => {
  it("focuses the main answer when there is no field; Esc closes and refocuses the trigger", () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Вернуть деньги" });
    openFrom(trigger);
    expect(screen.getByRole("group", { name: "Подтверждение" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Вернуть" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Подтверждение" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("focuses the first field when there is one", () => {
    render(<Harness withField />);
    openFrom(screen.getByRole("button", { name: "Вернуть деньги" }));
    expect(screen.getByLabelText("Причина")).toHaveFocus();
  });
});
