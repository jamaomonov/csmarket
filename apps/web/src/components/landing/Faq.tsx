/** The visible FAQ (native `<details>`, the first open) and its FAQPage JSON-LD. */
import { getTranslations } from "next-intl/server";

import { PlusIcon } from "./Icons";

import { JsonLd } from "@/components/JsonLd";
import { telegramUrl } from "@/lib/landing";

export interface FaqItem {
  q: string;
  a: string;
}

/** The FAQPage graph for exactly the questions on the page. */
export function faqJsonLd(items: FaqItem[]): object {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((i) => ({
      "@type": "Question",
      name: i.q,
      acceptedAnswer: { "@type": "Answer", text: i.a },
    })),
  };
}

export async function Faq({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.faq" });
  const items = t.raw("items") as FaqItem[]; // the catalogue's own array of {q, a}
  const tg = telegramUrl();
  return (
    <section aria-labelledby="lp-faq" id="faq">
      <div className="wrap faq-wrap">
        <div>
          <div className="kicker">{t("kicker")}</div>
          <h2 id="lp-faq">{t("title")}</h2>
          {tg !== "" && (
            <p className="sec-lead">
              <a href={tg} rel="noopener noreferrer" target="_blank">
                {t("lead")}
              </a>
            </p>
          )}
        </div>
        <div className="faq">
          {items.map((item, i) => (
            <details key={item.q} open={i === 0}>
              <summary>
                {item.q}
                <span className="pm">
                  <PlusIcon />
                </span>
              </summary>
              <div className="a">
                <p>{item.a}</p>
              </div>
            </details>
          ))}
        </div>
      </div>
      <JsonLd data={faqJsonLd(items)} />
    </section>
  );
}
