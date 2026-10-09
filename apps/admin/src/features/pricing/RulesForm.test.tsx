import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { PRICING } from "./fixtures";
import { fromRules, type RulesDraft, toRules } from "./rules-draft";
import { RulesForm } from "./RulesForm";

function Harness({ onSave }: { onSave: (d: RulesDraft) => void }) {
  const [draft, setDraft] = useState(fromRules(PRICING.rules));
  return (
    <RulesForm
      draft={draft}
      dirty
      saving={false}
      error={null}
      onChange={setDraft}
      onReset={() => {
        setDraft(fromRules(PRICING.rules));
      }}
      onSave={() => {
        onSave(draft);
      }}
    />
  );
}

describe("RulesForm", () => {
  it("round-trips the document unchanged", () => {
    expect(toRules(fromRules(PRICING.rules))).toEqual(PRICING.rules);
  });

  it("adds and removes bracket rows and category markups", () => {
    const onSave = vi.fn();
    render(<Harness onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Добавить брекет" }));
    const froms = screen.getAllByLabelText("от $");
    expect(froms).toHaveLength(3);
    fireEvent.change(froms[2] as HTMLInputElement, { target: { value: "100" } });
    fireEvent.change(screen.getAllByLabelText("%")[2] as HTMLInputElement, {
      target: { value: "2" },
    });
    fireEvent.click(
      screen.getAllByRole("button", { name: "Удалить брекет" })[1] as HTMLButtonElement,
    );
    fireEvent.click(screen.getByRole("button", { name: "Добавить категорию" }));
    const keys = screen.getAllByLabelText("Категория (slug)");
    fireEvent.change(keys.at(-1) as HTMLInputElement, { target: { value: "knives" } });
    fireEvent.change(
      screen.getAllByLabelText("Надбавка категории, п.п.").at(-1) as HTMLInputElement,
      {
        target: { value: "2" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    const saved = toRules(onSave.mock.calls[0]?.[0] as RulesDraft);
    expect(saved.retail).toEqual([
      { from_usd: "0", percent: "10" },
      { from_usd: "100", percent: "2" },
    ]);
    expect(saved.category_pp).toEqual({ stickers: "5", knives: "2" });
  });

  it("edits the cheap tail, and clearing its bound turns it off", () => {
    const onSave = vi.fn();
    render(<Harness onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Хвост: наклейки, п.п."), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(toRules(onSave.mock.calls[0]?.[0] as RulesDraft).cheap_tail).toEqual({
      max_cost_usd: "1",
      sticker_pp: "3",
      low_liquidity_pp: "1",
    });
    fireEvent.change(screen.getByLabelText("Хвост: себестоимость до, $"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(toRules(onSave.mock.calls[1]?.[0] as RulesDraft).cheap_tail).toBeNull();
  });

  it("the Steam cap is a checkbox", () => {
    const onSave = vi.fn();
    render(<Harness onSave={onSave} />);
    fireEvent.click(screen.getByLabelText("Не дороже Steam"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(toRules(onSave.mock.calls[0]?.[0] as RulesDraft).cap_at_steam).toBe(true);
  });
});
