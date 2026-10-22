import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkinThumb } from "./SkinThumb";

const URL = "https://community.akamai.steamstatic.com/economy/image/abc";

describe("SkinThumb", () => {
  it("shows the picture at the list size", () => {
    const { container } = render(<SkinThumb url={URL} />);
    expect(container.querySelector("img")).toHaveAttribute("src", `${URL}/128fx96f`);
  });

  it("shows a placeholder without a picture", () => {
    render(<SkinThumb url={null} />);
    expect(screen.getByTestId("skin-thumb-empty")).toBeInTheDocument();
  });

  it("falls back to the placeholder when the picture fails to load", () => {
    const { container } = render(<SkinThumb url={URL} />);
    const img = container.querySelector("img");
    if (img === null) throw new Error("no img");
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByTestId("skin-thumb-empty")).toBeInTheDocument();
  });
});
