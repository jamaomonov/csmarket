/** The landing's footer: what csmarket is, market categories, service and help links. */
import { getTranslations } from "next-intl/server";

import { PayMarks } from "./Wordmarks";

import { Link } from "@/i18n/navigation";
import { LEGAL_DOCS } from "@/lib/legal";
import {
  categoryPath,
  CHEAP,
  PAY_METHODS,
  PAY_NAMES,
  legalPath,
  payPath,
  REVIEWS,
  SELL,
  STEAM_TOPUP,
  weaponPath,
} from "@/lib/paths";
import { weaponSlug } from "@/lib/skin-landing";
import { TELEGRAM_LINKS } from "@/lib/telegram";

const MARKET_LINKS = ["knives", "gloves", "rifles", "pistols", "cases"] as const;
/** The most searched models, linked to their indexable `/weapon/<slug>` pages. */
const WEAPONS = ["AK-47", "AWP", "M4A1-S", "Desert Eagle", "Karambit", "Butterfly Knife"];

export async function LandingFooter({ locale }: { locale: string }) {
  const t = await getTranslations({ locale, namespace: "web.landing.footer" });
  const tCat = await getTranslations({ locale, namespace: "web.skins.category" });
  const tBuy = await getTranslations({ locale, namespace: "web.seoPages.footer" });
  const tLegal = await getTranslations({ locale, namespace: "legal" });
  return (
    <footer className="site">
      <div className="wrap">
        <div className="foot">
          <div>
            <p>{t("about")}</p>
            <div className="foot-pay">
              <PayMarks />
            </div>
          </div>
          <nav aria-label={t("market")}>
            <h4>{t("market")}</h4>
            <ul>
              {MARKET_LINKS.map((c) => (
                <li key={c}>
                  <Link href={categoryPath(c)}>{tCat(c)}</Link>
                </li>
              ))}
            </ul>
          </nav>
          <nav aria-label={t("weapons")}>
            <h4>{t("weapons")}</h4>
            <ul>
              {WEAPONS.map((w) => (
                <li key={w}>
                  <Link href={weaponPath(weaponSlug(w))}>{w}</Link>
                </li>
              ))}
            </ul>
          </nav>
          <nav aria-label={tBuy("title")}>
            <h4>{tBuy("title")}</h4>
            <ul>
              {PAY_METHODS.map((m) => (
                <li key={m}>
                  <Link href={payPath(m)}>{tBuy("pay", { method: PAY_NAMES[m] })}</Link>
                </li>
              ))}
              <li>
                <Link href={CHEAP}>{tBuy("cheap")}</Link>
              </li>
            </ul>
          </nav>
          <nav aria-label={t("service")}>
            <h4>{t("service")}</h4>
            <ul>
              <li>
                <Link href={SELL}>{t("sell")}</Link>
              </li>
              <li>
                <Link href={STEAM_TOPUP}>{t("steam")}</Link>
              </li>
              <li>
                <Link href={REVIEWS}>{t("reviews")}</Link>
              </li>
              <li>
                <a href="https://docs.csmarket.uz">{t("api")}</a>
              </li>
              <li>
                <a href="#faq">{t("faq")}</a>
              </li>
            </ul>
          </nav>
          <nav aria-label={t("telegram")}>
            <h4>{t("telegram")}</h4>
            <ul>
              {TELEGRAM_LINKS.map((l) => (
                <li key={l.key}>
                  <a href={l.href} rel="noopener noreferrer" target="_blank">
                    {t(l.key)}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        {/* Two rows: the documents, then the copyright beside the trademark note. */}
        <div className="foot-b">
          <nav aria-label={tLegal("index.title")} className="foot-legal">
            {LEGAL_DOCS.map((doc) => (
              <Link key={doc} href={legalPath(doc)}>
                {tLegal(`${doc}.title`)}
              </Link>
            ))}
          </nav>
          <p className="foot-note">
            <span>© {new Date().getFullYear()} csmarket.uz</span>
            <span>{t("legal")}</span>
          </p>
        </div>
      </div>
    </footer>
  );
}
