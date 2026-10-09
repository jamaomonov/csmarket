/** «О csmarket»: the SEO text — two columns on desktop, folded on phones. */
import { getTranslations } from "next-intl/server";

import { ReadMore } from "./ReadMore";

interface Block {
  h: string;
  p: string;
}

export async function About({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.about" });
  const blocks = t.raw("blocks") as Block[]; // the catalogue's own array of {h, p}
  return (
    <section aria-labelledby="lp-about">
      <div className="wrap">
        <div className="about">
          <div className="about-h">
            <div>
              <div className="kicker">{t("kicker")}</div>
              <h2 id="lp-about">{t("title")}</h2>
            </div>
            <p>{t("intro")}</p>
          </div>
          <ReadMore label={t("readMore")}>
            {blocks.map((b) => (
              <div key={b.h} className="blk">
                <h3>{b.h}</h3>
                <p>{b.p}</p>
              </div>
            ))}
          </ReadMore>
        </div>
      </div>
    </section>
  );
}
