import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActionBar, EmptySections, More, Row } from "./Section";

describe("More", () => {
  it("folds technical fields under «Подробнее» until opened", () => {
    render(
      <More>
        <Row label="Project id">6f1c2a52</Row>
      </More>,
    );
    const details = screen.getByText("6f1c2a52").closest("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Подробнее"));
    expect(details).toHaveAttribute("open");
  });
});

describe("ActionBar", () => {
  it("groups the page's actions under a label", () => {
    render(
      <ActionBar label="Действия">
        <button type="button">Разобрано</button>
      </ActionBar>,
    );
    expect(screen.getByRole("group", { name: "Действия" })).toContainElement(
      screen.getByRole("button", { name: "Разобрано" }),
    );
  });
});

describe("EmptySections", () => {
  it("folds empty sections into one line", () => {
    render(<EmptySections names={["Заказы", "Продажи", "Пополнения"]} />);
    expect(screen.getByTestId("empty-sections")).toHaveTextContent(
      "Пока пусто: Заказы, Продажи, Пополнения.",
    );
  });

  it("renders nothing when every section has something", () => {
    const { container } = render(<EmptySections names={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
