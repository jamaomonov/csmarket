import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SteamOfferValue, TradeLinkValue } from "./SteamLinks";

const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=AbCdXY";

describe("SteamLinks", () => {
  it("hides the token on screen, opens and copies the whole link", async () => {
    const write = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText: write } });
    render(<TradeLinkValue link={LINK} />);
    const shown = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••";
    expect(screen.getByRole("link", { name: shown })).toHaveAttribute("href", LINK);
    expect(document.body.textContent).not.toContain("AbCdXY");
    fireEvent.click(screen.getByRole("button", { name: "Скопировать трейд-ссылку" }));
    await waitFor(() => {
      expect(write).toHaveBeenCalledWith(LINK);
    });
  });

  it("shows an erased (masked) link as text only", () => {
    render(
      <TradeLinkValue link="https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••XY" />,
    );
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("says when no link is saved", () => {
    render(<TradeLinkValue link={null} />);
    expect(screen.getByText("не указана")).toBeInTheDocument();
  });

  it("turns an offer id into the offer's Steam link", () => {
    render(<SteamOfferValue offerId="9435502856" />);
    const url = "https://steamcommunity.com/tradeoffer/9435502856/";
    expect(screen.getByRole("link", { name: url })).toHaveAttribute("href", url);
    expect(screen.getByRole("button", { name: "Скопировать ссылку на оффер" })).toBeInTheDocument();
  });
});
