import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SteamOfferValue, TradeLinkValue } from "./SteamLinks";

const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=AbCdXY";

describe("SteamLinks", () => {
  it("shows the whole trade link as a link to open or copy", () => {
    render(<TradeLinkValue link={LINK} />);
    expect(screen.getByRole("link", { name: LINK })).toHaveAttribute("href", LINK);
    expect(screen.getByRole("button", { name: "Скопировать трейд-ссылку" })).toBeInTheDocument();
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
