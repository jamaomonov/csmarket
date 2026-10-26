import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

const mediaUrl = (p: string) => `https://api.test/api/v1${p}`;
const renderSkin = (slug: string) => <span data-testid="skin">{slug}</span>;

function md(source: string) {
  return render(<Markdown source={source} mediaUrl={mediaUrl} renderSkin={renderSkin} />);
}

describe("Markdown", () => {
  it("renders headings lists tables and links", () => {
    md(
      [
        "## Ножи",
        "",
        "- **Бабочка**",
        "- *Керамбит*",
        "",
        "| Скин | Цена |",
        "| --- | --- |",
        "| AK | 10 |",
        "",
        "[Каталог](/market) и [Steam](https://steamcommunity.com)",
      ].join("\n"),
    );
    expect(screen.getByRole("heading", { level: 2, name: "Ножи" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Каталог" })).toHaveAttribute("href", "/market");
    const external = screen.getByRole("link", { name: "Steam" });
    expect(external).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(external).toHaveAttribute("target", "_blank");
  });

  it("renders raw HTML as text and drops unsafe urls", () => {
    const { container } = md(
      [
        "<script>alert(1)</script>",
        "",
        '<img src="x" onerror="alert(1)">',
        "",
        "[click](javascript:alert(1))",
        "",
        "![evil](https://evil.test/x.png)",
      ].join("\n"),
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    const link = screen.queryByRole("link", { name: "click" });
    expect(link?.getAttribute("href") ?? "").not.toContain("javascript");
  });

  it("renders a skin embed only on its own line", () => {
    md(["Смотрите:", "", "[[skin:ak-47-redline]]", "", "текст [[skin:inline]] дальше"].join("\n"));
    const skins = screen.getAllByTestId("skin");
    expect(skins.map((s) => s.textContent)).toEqual(["ak-47-redline"]);
    expect(screen.getByText(/текст \[\[skin:inline\]\] дальше/)).toBeInTheDocument();
  });

  it("maps media paths through mediaUrl and keeps the alt", () => {
    md("![Бабочка в руке](/media/abc.webp?w=640&h=360)");
    const img = screen.getByRole("img", { name: "Бабочка в руке" });
    expect(img).toHaveAttribute("src", "https://api.test/api/v1/media/abc.webp?w=640&h=360");
  });

  it("hands media images to renderImage when given", () => {
    render(
      <Markdown
        source="![a](/media/abc.png?w=10&h=20)"
        mediaUrl={mediaUrl}
        renderSkin={renderSkin}
        renderImage={({ src, alt, width, height }) => (
          <span data-testid="pic">{`${src}|${alt}|${String(width)}|${String(height)}`}</span>
        )}
      />,
    );
    expect(screen.getByTestId("pic").textContent).toBe(
      "https://api.test/api/v1/media/abc.png?w=10&h=20|a|10|20",
    );
  });

  it("demotes h1 to h2", () => {
    md("# Заголовок");
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Заголовок" })).toBeInTheDocument();
  });
});
