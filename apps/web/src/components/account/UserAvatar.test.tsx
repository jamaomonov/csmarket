// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UserAvatar } from "./UserAvatar";

describe("UserAvatar", () => {
  it("shows the Steam avatar when there is one", () => {
    const { container } = render(
      <UserAvatar
        user={{ avatar_url: "https://avatars.test/a.jpg", display_name: "Jam" }}
        size={40}
      />,
    );
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "https://avatars.test/a.jpg");
    expect(img).toHaveAttribute("width", "40");
  });

  it("falls back to the name's first letter", () => {
    render(<UserAvatar user={{ avatar_url: null, display_name: "jam" }} size={28} />);
    expect(screen.getByText("J")).toBeInTheDocument();
  });

  it("and to a neutral glyph without a name", () => {
    const { container } = render(<UserAvatar user={{ avatar_url: null, display_name: null }} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
