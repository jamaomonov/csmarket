/** «Популярные скины CS2»: four tabs of live cards, all rendered on the server. */
import { getTranslations } from "next-intl/server";

import { ArrowIcon } from "./Icons";
import { LandingCard } from "./LandingCard";
import { PopularTabs } from "./PopularTabs";

import type { SkinItem } from "@csmarket/utils/skins";

import { Link } from "@/i18n/navigation";
import { type PopularTab, POPULAR_TABS } from "@/lib/landing";
import { MARKET } from "@/lib/paths";

export async function Popular({
  lists,
  locale,
}: {
  lists: Record<PopularTab, SkinItem[]>;
  locale: string;
}) {
  const t = await getTranslations({ locale, namespace: "web.landing.popular" });
  const tSkins = await getTranslations({ locale, namespace: "web.skins" });
  const panels = POPULAR_TABS.map((tab) => ({
    key: tab,
    label: t(`tabs.${tab}`),
    node:
      lists[tab].length === 0 ? (
        <p className="sec-lead" style={{ gridColumn: "1/-1" }}>
          {t("empty")}
        </p>
      ) : (
        lists[tab].map((item) => (
          <LandingCard
            key={item.slug}
            item={item}
            locale={locale}
            pieces={t("pieces", { count: item.count })}
            vanilla={tSkins("vanilla")}
          />
        ))
      ),
  }));
  return (
    <section className="pop" aria-labelledby="lp-pop">
      <PopularTabs
        label={t("tabsLabel")}
        panels={panels}
        title={
          <div>
            <div className="kicker">{t("kicker")}</div>
            <h2 id="lp-pop">{t("title")}</h2>
          </div>
        }
        footer={
          <div style={{ display: "flex", justifyContent: "center", marginTop: 24 }}>
            <Link className="btn btn-secondary" href={MARKET}>
              {t("all")}
              <ArrowIcon />
            </Link>
          </div>
        }
      />
    </section>
  );
}
