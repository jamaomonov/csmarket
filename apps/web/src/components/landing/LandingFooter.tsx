/** The landing's footer: what csmarket is, market categories, service and help links. */
import { getTranslations } from "next-intl/server";

import { PayMarks } from "./Wordmarks";

import { Link } from "@/i18n/navigation";
import { telegramUrl } from "@/lib/landing";
import { categoryPath, REVIEWS, SELL, STEAM_TOPUP } from "@/lib/paths";

const MARKET_LINKS = ["knives", "gloves", "rifles", "pistols", "cases"] as const;

export async function LandingFooter({ locale }: { locale: string }) {
  const tg = telegramUrl();
  const t = await getTranslations({ locale, namespace: "web.landing.footer" });
  const tCat = await getTranslations({ locale, namespace: "web.skins.category" });
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
            </ul>
          </nav>
          <nav aria-label={t("help")}>
            <h4>{t("help")}</h4>
            <ul>
              <li>
                <a href="#faq">{t("faq")}</a>
              </li>
              {tg !== "" && (
                <li>
                  <a href={tg} rel="noopener noreferrer" target="_blank">
                    Telegram
                  </a>
                </li>
              )}
            </ul>
          </nav>
        </div>
        <div className="foot-b">
          <span>© {new Date().getFullYear()} csmarket.uz</span>
          <span>{t("legal")}</span>
        </div>
      </div>
    </footer>
  );
}
