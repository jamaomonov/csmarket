import ru from "@csmarket/i18n/locales/ru/web.json";
import { describe, expect, it } from "vitest";

import { sellFaq } from "./sell-seo";

describe("sell SEO copy", () => {
  it("reads the catalogue's questions and drops malformed ones", () => {
    const faq = sellFaq(ru.sell.guide.faq);
    expect(faq.length).toBe(9);
    expect(faq[0]?.question).toBe("Где продать скины и вывести деньги на карту в Узбекистане?");
    expect(sellFaq([{ q: "x" }, null, "y", { q: "a", a: "b" }])).toEqual([
      { question: "a", answer: "b" },
    ]);
    expect(sellFaq("nope")).toEqual([]);
  });

  it("the questions name no percent or fee: assistants quote them (owner)", () => {
    for (const e of sellFaq(ru.sell.guide.faq)) {
      expect(`${e.question} ${e.answer}`).not.toMatch(/%|комисс/i);
    }
  });
});
