/**
 * The footer of the catalogue, item, landing-type and legal pages: the same links as the
 * home page's footer (sections, popular weapons, buying by payment method, cheap skins,
 * service, legal), so every indexable page links to every hub. The home page keeps its own,
 * styled `LandingFooter`.
 */
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { LEGAL_DOCS } from "@/lib/legal";
import {
  categoryPath,
  CHEAP,
  legalPath,
  MARKET,
  PAY_METHODS,
  PAY_NAMES,
  payPath,
  REVIEWS,
  SELL,
  STEAM_TOPUP,
  weaponPath,
} from "@/lib/paths";
import { weaponSlug } from "@/lib/skin-landing";

const CATEGORIES = ["knives", "gloves", "rifles", "pistols", "smgs", "cases", "agents"] as const;
const WEAPONS = ["AK-47", "AWP", "M4A1-S", "Desert Eagle", "Karambit", "Butterfly Knife"];

interface ColumnProps {
  title: string;
  links: { href: string; label: string }[];
}

function Column({ title, links }: ColumnProps) {
  return (
    <nav aria-label={title}>
      <h2 className="text-fg mb-2 text-[13px] font-bold">{title}</h2>
      <ul className="space-y-1.5">
        {links.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className="hover:text-fg">
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export async function SiteFooter({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.footer" });
  const tCat = await getTranslations({ locale, namespace: "web.skins.category" });
  const tBuy = await getTranslations({ locale, namespace: "web.seoPages.footer" });
  const tLegal = await getTranslations({ locale, namespace: "legal" });
  return (
    <footer className="border-border text-fg-dim border-t text-[13px]">
      <div className="mx-auto grid max-w-[1320px] grid-cols-2 gap-6 px-4 pb-28 pt-8 sm:px-6 md:grid-cols-4 md:pb-10">
        <Column
          title={t("market")}
          links={[
            { href: MARKET, label: t("market") },
            ...CATEGORIES.map((c) => ({ href: categoryPath(c), label: tCat(c) })),
          ]}
        />
        <Column
          title={t("weapons")}
          links={WEAPONS.map((w) => ({ href: weaponPath(weaponSlug(w)), label: w }))}
        />
        <Column
          title={tBuy("title")}
          links={[
            ...PAY_METHODS.map((m) => ({
              href: payPath(m),
              label: tBuy("pay", { method: PAY_NAMES[m] }),
            })),
            { href: CHEAP, label: tBuy("cheap") },
          ]}
        />
        <Column
          title={t("service")}
          links={[
            { href: SELL, label: t("sell") },
            { href: STEAM_TOPUP, label: t("steam") },
            { href: REVIEWS, label: t("reviews") },
          ]}
        />
        <div className="col-span-2 space-y-2 md:col-span-4">
          <nav aria-label={tLegal("index.title")} className="flex flex-wrap gap-x-4 gap-y-1">
            {LEGAL_DOCS.map((doc) => (
              <Link key={doc} href={legalPath(doc)} className="hover:text-fg">
                {tLegal(`${doc}.title`)}
              </Link>
            ))}
          </nav>
          <p>
            © {new Date().getFullYear()} csmarket.uz · {t("legal")}
          </p>
        </div>
      </div>
    </footer>
  );
}
